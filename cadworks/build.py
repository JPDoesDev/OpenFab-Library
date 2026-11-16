"""Build every part and assembly: python -m cadworks.build [filter ...]

Reads data/*.csv and data/assemblies.json, runs the generated scripts through
solidcraft-cli, checks each part's volume against the analytic value, finds
each ball joint's collision limit, and writes build/ plus catalog.json.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from . import assemblies as A
from . import parts as P
from .sc import IN, Script, measure, run

ROOT = Path(__file__).resolve().parent.parent
DATA, BUILD = ROOT / "data", ROOT / "build"
FAMILIES = [  # (csv, generator); bearings first so cups can look up the race width
    ("spherical_bearings", P.spherical_bearing), ("rod_ends", P.rod_end), ("spacers", P.spacer),
    ("cups", P.cup), ("snap_rings", P.snap_ring), ("jam_nuts", P.jam_nut),
    ("bushings", P.bushing), ("sleeves", P.sleeve),
]
VOLUME_TOL = 0.002


def rows(name: str) -> list[dict]:
    with open(DATA / f"{name}.csv", newline="") as fh:
        return list(csv.DictReader(fh))


def build_part(part: P.Part, files: dict, report: dict) -> None:
    folder = BUILD / "parts" / part.family
    folder.mkdir(parents=True, exist_ok=True)
    design, step = folder / f"{part.key}.sc", folder / f"{part.key}.step"
    run(part.script, save=design, out=[step], keep=BUILD / "scripts" / "parts" / f"{part.key}.json")
    m = measure(design)
    bodies = m["bodies"]
    vol = sum(b["volume_mm3"] for b in bodies) / IN ** 3
    entry = {"part_number": part.part_number, "family": part.family, "vendor": part.vendor,
             "description": part.description, "bom_type": part.bom_type,
             "file": str(design.relative_to(ROOT)), "step": str(step.relative_to(ROOT)),
             "dims_in": part.dims, "estimated": part.estimated, "volume_in3": round(vol, 5),
             **part.properties}
    problems = []
    if len(bodies) != 1 or not bodies[0]["closed"]:
        problems.append(f"{len(bodies)} bodies, closed={[b['closed'] for b in bodies]}")
    if any(t.get("error") or t.get("warning") for t in m["timeline"]):
        problems.append("timeline: " + "; ".join(str(t.get("error") or t.get("warning"))
                                                  for t in m["timeline"] if t.get("error") or t.get("warning")))
    if part.volume_in3 is not None:
        err = abs(vol - part.volume_in3) / part.volume_in3
        entry["volume_check"] = "ok" if err <= VOLUME_TOL else f"off by {err:.2%}"
        if err > VOLUME_TOL:
            problems.append(f"volume {vol:.5f} in3, expected {part.volume_in3:.5f}")
    else:
        entry["volume_check"] = "not checked"
    files[part.key] = design
    report["parts"][part.key] = entry
    if problems:
        report["problems"].append(f"{part.key}: " + "; ".join(problems))


def build_assembly(recipe: dict, files: dict, catalog: dict, report: dict) -> None:
    asm = A.BUILDERS[recipe["kind"]](recipe, files, catalog)
    for part in asm.needed:
        if part.key not in files:
            build_part(part, files, report)
    # generic parts were added to the catalog while the recipe ran; rebuild now that their files exist
    asm = A.BUILDERS[recipe["kind"]](recipe, files, catalog)
    folder = BUILD / "assemblies" / asm.kind
    folder.mkdir(parents=True, exist_ok=True)
    design, step, bom = (folder / f"{asm.key}{ext}" for ext in (".sc", ".step", ".bom.csv"))
    results = run(asm.s, save=design, keep=BUILD / "scripts" / "assemblies" / f"{asm.key}.json")
    joints = next(r for r in reversed(results) if isinstance(r, dict) and "joints" in r and "conflicts" in r)
    entry = {"title": asm.title, "kind": asm.kind, "file": str(design.relative_to(ROOT)),
             "step": str(step.relative_to(ROOT)), "bom": str(bom.relative_to(ROOT)),
             "members": asm.members, "pivot": dict(asm.pivot)}
    problems = []
    if joints["conflicts"] or joints["floating"] or joints["errors"]:
        problems.append(f"joints: conflicts={joints['conflicts']} floating={joints['floating']} errors={joints['errors']}")
    post = Script()
    limits = next((r for r in reversed(results) if isinstance(r, dict) and "gap_method" in r), None)
    if limits:
        v = limits["values"][0]
        lim = min(abs(v["min"]), abs(v["max"]))
        by = v["max_by"] if abs(v["max"]) <= abs(v["min"]) else v["min_by"]
        if isinstance(by, dict):
            entry["pivot"].update({"max_misalignment_deg": round(lim, 2), "limited_by": [by["a"], by["b"]]})
            post.cmd("joint.limits", joint="Pivot", index=1, min=-round(lim, 2), max=round(lim, 2))
        else:
            entry["pivot"].update({"max_misalignment_deg": None, "limited_by": by})
            problems.append(f"limit search ended with {by!r}")
        if limits["overlapping_at_start"]:
            problems.append(f"overlapping at start: {limits['overlapping_at_start']}")
    post.cmd("inspect.interference")
    post.cmd("assembly.bom", path=str(bom.resolve()))
    res = run(post, start=design, save=design, out=[step], keep=BUILD / "scripts" / "assemblies" / f"{asm.key}.post.json")
    clash = next((r for r in res if isinstance(r, dict) and ("pairs" in r or "interferences" in r)), {})
    hits = clash.get("interferences") or clash.get("pairs") or []
    hits = [h for h in hits if isinstance(h, dict) and h.get("volume_mm3", 0) > 0.5]
    if asm.kind == "bushing_pivot":
        # a urethane bushing is larger than its sleeve bore: that overlap is the press fit, not a fault
        fit = [h for h in hits if {h.get("a"), h.get("b")} <= {"Sleeve", "Bushing", "Bushing (2)"}]
        hits = [h for h in hits if h not in fit]
        if fit:
            entry["press_fit_overlap_mm3"] = round(max(h["volume_mm3"] for h in fit), 1)
    if hits:
        problems.append("interference at rest: " + ", ".join(f"{h.get('a')}/{h.get('b')} {h.get('volume_mm3'):.1f} mm3" for h in hits))
    bom_rows = next((r["rows"] for r in res if isinstance(r, dict) and "rows" in r), [])
    entry["bom_rows"] = [{"part_number": r["part_number"], "count": r["count"], "description": r["description"]}
                         for r in bom_rows]
    report["assemblies"][asm.key] = entry
    if problems:
        report["problems"].append(f"{asm.key}: " + "; ".join(problems))


def main(argv: list[str]) -> int:
    only = [a.lower() for a in argv]
    want = lambda key: not only or any(o in key.lower() for o in only)
    report = {"units": "inches (dims_in); files are SolidCraft designs with STEP copies",
              "parts": {}, "assemblies": {}, "problems": []}
    files: dict[str, Path] = {}
    catalog: dict[str, P.Part] = {}
    recipes = json.loads((DATA / "assemblies.json").read_text())
    recipes = [r for r in recipes if want(r["key"])]
    needed = {v for r in recipes for v in r.values() if isinstance(v, str)}
    for name, gen in FAMILIES:
        for row in rows(name):
            if name == "spherical_bearings":
                P.register_bearing(row)
            for part in gen(row):
                catalog[part.key] = part
    if only:  # a filtered run builds just what the chosen assemblies use
        for r in recipes:
            needed.update(catalog[r[k]].dims.get("snap_ring", "") for k in ("cup",) if k in r)
        todo = [p for k, p in catalog.items() if k.split(".ball")[0] in needed or want(k)]
    else:
        todo = list(catalog.values())
    for part in todo:
        try:
            build_part(part, files, report)
        except Exception as e:  # keep going: one bad part should not hide the others
            report["problems"].append(f"{part.key}: {e}")
        print("part", part.key, report["parts"].get(part.key, {}).get("volume_check", "FAILED"), flush=True)
    for recipe in recipes:
        try:
            build_assembly(recipe, files, catalog, report)
            piv = report["assemblies"][recipe["key"]]["pivot"]
            print("assembly", recipe["key"], piv.get("max_misalignment_deg", "free"), flush=True)
        except Exception as e:
            report["problems"].append(f"{recipe['key']}: {e}")
            print("assembly", recipe["key"], "FAILED", flush=True)
    out = ROOT / "catalog.json" if not only else BUILD / "catalog.partial.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n")
    print(f"\n{len(report['parts'])} parts, {len(report['assemblies'])} assemblies, "
          f"{len(report['problems'])} problems -> {out.relative_to(ROOT)}")
    for p in report["problems"]:
        print("  PROBLEM", p)
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
