"""Build every part and assembly into components/: python -m openfab.build [filter ...]  (run from scripts/)

Reads data/*.csv and data/assemblies.json, runs the generated scripts through
solidcraft-cli, checks each part's volume against the analytic value, finds
each ball joint's collision limit, and writes components/ (models, pictures,
sheets, BOMs, index pages, catalog.json) and scripts/generated/. A filtered run builds only the assemblies whose key contains one
of the filters (and the parts they use) and leaves catalog.json alone.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

from . import assemblies as A
from . import parts as P
from .sc import IN, Script, measure, run, snapshot, version

ROOT = Path(__file__).resolve().parent.parent          # scripts/
REPO = ROOT.parent
DATA, OUT, GEN = ROOT / "data", REPO / "components", ROOT / "generated"
A.LINK_PREFIX = os.path.relpath(OUT, GEN / "assemblies").replace(os.sep, "/") + "/"
FAMILIES = [  # (csv, generator); bearings first so cups can look up the race width
    ("spherical_bearings", P.spherical_bearing), ("rod_ends", P.rod_end), ("spacers", P.spacer),
    ("cups", P.cup), ("snap_rings", P.snap_ring), ("jam_nuts", P.jam_nut),
    ("bushings", P.bushing), ("sleeves", P.sleeve),
    ("safety_washers", P.safety_washer),
]
VOLUME_TOL = 0.002


def rows(name: str) -> list[dict]:
    with open(DATA / f"{name}.csv", newline="") as fh:
        return list(csv.DictReader(fh))


def rel(path: Path) -> str:
    return path.relative_to(OUT).as_posix()


def slug(folder: str) -> str:
    """'Rod Ends' -> 'rod-ends': folder names stay lower-case so links and URLs are clean."""
    return folder if folder.startswith("_") else folder.lower().replace(" ", "-")


def sidecar(part: P.Part, entry: dict) -> str:
    """The plain-text sheet that sits beside each part file."""
    lines = [part.title, ""]
    if part.part_number:
        lines += [f"Part number:  {part.part_number}", f"Vendor:       {part.vendor}"]
    else:
        lines += ["Part number:  none (helper geometry, not something you buy)"]
    lines += [f"Description:  {part.description}", f"Material:     {part.material}",
              f"Source:       {part.properties.get('source', 'OpenFab Library')}"]
    if part.xrefs:
        lines += ["", "Also available as:"]
        width = max(len(f"{x['other_vendor']} {x['other_part_number']}") for x in part.xrefs)
        for x in part.xrefs:
            who = f"{x['other_vendor']} {x['other_part_number']}"
            lines.append(f"  {who:<{width}}  {x['relation']}" + (f" - {x['note']}" if x["note"] else ""))
    lines += ["", "Dimensions (inches):"]
    lines += [f"  {k}: {P.num(v) if isinstance(v, float) else v}" for k, v in part.dims.items()]
    if part.estimated:
        lines += ["", "Estimated (not published by the vendor):"] + [f"  {e}" for e in part.estimated]
    lines += ["", f"Volume check: {entry['volume_check']}", ""]
    return "\n".join(lines)


def build_part(part: P.Part, files: dict, report: dict) -> None:
    folder = OUT / "parts" / slug(part.folder)
    folder.mkdir(parents=True, exist_ok=True)
    design, step = folder / f"{part.name}.sc", folder / f"{part.name}.step"
    run(part.script, save=design, out=[step], keep=GEN / "parts" / f"{part.name}.json")
    m = measure(design)
    bodies = m["bodies"]
    snapshot(design, design.with_suffix(".png"), bodies)
    vol = sum(b["volume_mm3"] for b in bodies) / IN ** 3
    entry = {"name": part.name, "part_number": part.part_number, "vendor": part.vendor,
             "family": part.family, "description": part.description, "material": part.material,
             "bom_type": part.bom_type, "also_available_as": part.xrefs,
             "file": rel(design), "step": rel(step), "sheet": rel(design.with_suffix(".txt")),
             "image": rel(design.with_suffix(".png")),
             "dims_in": part.dims, "estimated": part.estimated, "volume_in3": round(vol, 5),
             **part.properties}
    problems = []
    if len(bodies) != 1 or not bodies[0]["closed"]:
        problems.append(f"{len(bodies)} bodies, closed={[b['closed'] for b in bodies]}")
    faults = [str(t.get("error") or t.get("warning")) for t in m["timeline"] if t.get("error") or t.get("warning")]
    if faults:
        problems.append("timeline: " + "; ".join(faults))
    if part.volume_in3 is not None:
        err = abs(vol - part.volume_in3) / part.volume_in3
        entry["volume_check"] = "ok" if err <= VOLUME_TOL else f"off by {err:.2%}"
        if err > VOLUME_TOL:
            problems.append(f"volume {vol:.5f} in3, expected {part.volume_in3:.5f}")
    else:
        entry["volume_check"] = "not checked"
    design.with_suffix(".txt").write_text(sidecar(part, entry))
    files[part.key] = rel(design)
    report["parts"][part.key] = entry
    if problems:
        report["problems"].append(f"{part.key}: " + "; ".join(problems))


def write_bom(path: Path, bom_rows: list[dict]) -> list[dict]:
    out = []
    for i, r in enumerate(bom_rows, 1):
        props = r.get("properties") or {}
        out.append({"item": i, "qty": r["count"], "vendor": props.get("vendor", ""),
                    "part_number": r["part_number"], "description": r["description"],
                    "also_available_as": props.get("also_available_as", "")})
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["item", "qty", "vendor", "part_number", "description", "also_available_as"])
        w.writeheader()
        w.writerows(out)
    return out


def build_assembly(recipe: dict, files: dict, catalog: dict, report: dict, names: set) -> None:
    asm = A.BUILDERS[recipe["kind"]](recipe, files, catalog)
    if asm.name in names:
        raise RuntimeError(f"two assemblies would both be called {asm.name!r}")
    names.add(asm.name)
    folder = OUT / "assemblies" / slug(A.FOLDERS[asm.kind]) / asm.name   # one folder per assembly
    folder.mkdir(parents=True, exist_ok=True)
    design, step, bom = (folder / f"{asm.name}{ext}" for ext in (".sc", ".step", ".bom.csv"))
    scripts = GEN / "assemblies"
    results = run(asm.s, save=design, keep=scripts / f"{asm.name}.json", script_relative=True)
    joints = next(r for r in reversed(results) if isinstance(r, dict) and "joints" in r and "conflicts" in r)
    entry = {"name": asm.name, "description": asm.description, "kind": asm.kind, "file": rel(design),
             "step": rel(step), "bom": rel(bom),
             "script": (scripts / f"{asm.name}.json").relative_to(REPO).as_posix(),
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
        elif by == "turn":
            # nothing in the assembly stops the swing (no spacers): the builder's mount sets the limit
            entry["pivot"].update({"max_misalignment_deg": None,
                                   "limited_by": "nothing in this assembly; your mount tabs set the limit"})
        else:
            entry["pivot"].update({"max_misalignment_deg": None, "limited_by": by})
            problems.append(f"limit search ended with {by!r}")
        if limits["overlapping_at_start"]:
            problems.append(f"overlapping at start: {limits['overlapping_at_start']}")
    if asm.bare_limit is not None:
        entry["pivot"].update({"max_misalignment_deg": asm.bare_limit,
                               "limited_by": "edge of the ball's bore reaching the edge of the joint's flat face "
                                             "(worked out from the catalog dimensions; no spacers)"})
        post.cmd("joint.limits", joint="Pivot", index=1, min=-asm.bare_limit, max=asm.bare_limit)
    post.cmd("inspect.interference")
    post.cmd("assembly.bom")
    post.cmd("component.links")
    res = run(post, start=design, save=design, out=[step], keep=scripts / f"{asm.name}.limits.json")
    snapshot(design, design.with_suffix(".png"), measure(design)["bodies"])
    entry["image"] = rel(design.with_suffix(".png"))
    clash = next((r for r in res if isinstance(r, dict) and "interferences" in r), {})
    hits = [h for h in clash.get("interferences", []) if h.get("volume_mm3", 0) > 0.5]
    if asm.kind == "bushing_pivot":
        # a urethane bushing is larger than its sleeve bore: that overlap is the press fit, not a fault
        fit = [h for h in hits if sorted(str(h.get(k)).split(" (")[0] for k in ("a", "b")) == ["Bushing", "Sleeve"]]
        hits = [h for h in hits if h not in fit]
        if fit:
            entry["press_fit_overlap_mm3"] = round(max(h["volume_mm3"] for h in fit), 1)
    if hits:
        problems.append("interference at rest: " + ", ".join(
            f"{h.get('a')}/{h.get('b')} {h.get('volume_mm3'):.1f} mm3" for h in hits))
    links = next((r.get("links", []) for r in res if isinstance(r, dict) and "links" in r), [])
    entry["links"] = sorted({str(l.get("path")) for l in links})
    absolute = [p for p in entry["links"] if p.startswith("/")]
    broken = [l for l in links if l.get("state") in ("missing", "unreadable", "not_allowed")]
    if broken or absolute or not links:
        problems.append(f"links: {len(links)} found, broken={broken}, absolute={absolute}")
    entry["bom_rows"] = write_bom(bom, next((r["rows"] for r in res if isinstance(r, dict) and "rows" in r), []))
    report["assemblies"][asm.key] = entry
    if problems:
        report["problems"].append(f"{asm.key}: " + "; ".join(problems))


def natural(text: str) -> list:
    """Sort key that puts 0.5in before 0.75in before 1in."""
    return [float(t) if re.fullmatch(r"\d+(?:\.\d+)?", t) else t for t in re.split(r"(\d+(?:\.\d+)?)", text)]


def link(label: str, target: str, start: Path) -> str:
    """A Markdown link from the index page in `start` to a file given relative to components/."""
    return f"[{label}]({quote(os.path.relpath(OUT / target, start).replace(os.sep, '/'))})"


def picture(target: str, start: Path) -> str:
    return f'<img src="{quote(os.path.relpath(OUT / target, start).replace(os.sep, "/"))}" width="150">'


def write_indexes(report: dict) -> None:
    """An index.md in every family folder, with a small picture of each item, and one at the top."""
    top = ["# Components", "",
           f"Every part and assembly in the library. Built with {report['built_with']}; the `.step` files "
           "open in any CAD program.", "",
           "Part numbers are stored inside each `.sc` file, so a SolidCraft bill of materials lists them "
           "for anything you build. `catalog.json` in this folder is the same information for scripts.", ""]
    families: dict[str, list] = {}
    for e in report["parts"].values():
        families.setdefault(e["file"].split("/")[1], []).append(e)
    top += ["## Parts", "", "| Family | Parts |", "|---|---|"]
    for folder in sorted(families, key=lambda f: (f.startswith("_"), f)):
        items = sorted(families[folder], key=lambda e: natural(e["name"]))
        here = OUT / "parts" / folder
        title = "Internal helper pieces" if folder == "_internal" else folder.replace("-", " ").title()
        page = [f"# {title}", ""]
        if folder == "_internal":
            page += ["Bearing balls, split out so the joint in an assembly can move. They have no part "
                     "number of their own; the bearing or rod end they belong to is what you buy.", ""]
        page += ["| | Part | Vendor | Part number | Also available as | Files |", "|---|---|---|---|---|---|"]
        for e in items:
            other = "<br>".join(f"{x['other_vendor']} {x['other_part_number']} ({x['relation']})"
                                for x in e["also_available_as"])
            files = " · ".join([link("SolidCraft", e["file"], here), link("STEP", e["step"], here),
                                link("sheet", e["sheet"], here)])
            name = e["name"].rsplit(" (", 1)[0] if e["part_number"] else e["name"]
            page.append(f"| {picture(e['image'], here)} | {name} | {e['vendor']} | "
                        f"{'`' + e['part_number'] + '`' if e['part_number'] else ''} | {other} | {files} |")
        page += ["", "Sizes are in inches, written as decimals (0.75in is 3/4\"). Each sheet lists the "
                     "dimensions and says which were estimated.", ""]
        (here / "index.md").write_text("\n".join(page))
        top.append(f"| {link(title, f'parts/{folder}/index.md', OUT)} | {len(items)} |")
    kinds: dict[str, list] = {}
    for e in report["assemblies"].values():
        kinds.setdefault(e["file"].split("/")[1], []).append(e)
    top += ["", "## Assemblies", "", "| Type | Assemblies |", "|---|---|"]
    for folder in sorted(kinds):
        items = sorted(kinds[folder], key=lambda e: natural(e["name"]))
        here = OUT / "assemblies" / folder
        title = folder.replace("-", " ").title()
        page = [f"# {title}", "", "Each assembly has its own folder with the SolidCraft file, a STEP copy, "
                "a picture and a bill of materials. Bolts, nuts, washers and mount tabs are not included.", "",
                "| | Assembly | Pivot | Parts | Files |", "|---|---|---|---|---|"]
        for e in items:
            piv = e["pivot"]
            if piv.get("max_misalignment_deg"):
                pivot = f"tilts {piv['max_misalignment_deg']}° each way"
            elif piv.get("type") == "revolute":
                pivot = "turns freely"
            elif piv.get("type") == "ball":
                pivot = "no stored limit; your mount sets it"
            else:
                pivot = "does not move"
            bom = "<br>".join(f"{r['qty']} × {r['vendor']} `{r['part_number']}`" for r in e["bom_rows"])
            files = " · ".join([link("folder", str(Path(e["file"]).parent), here),
                                link("SolidCraft", e["file"], here), link("STEP", e["step"], here),
                                link("BOM", e["bom"], here)])
            page.append(f"| {picture(e['image'], here)} | {e['name']} | {pivot} | {bom} | {files} |")
        page += ["", "Pivot limits come from sweeping the joint until parts touch, and depend on some "
                     "estimated spacer dimensions. Treat them as approximate.", ""]
        (here / "index.md").write_text("\n".join(page))
        top.append(f"| {link(title, f'assemblies/{folder}/index.md', OUT)} | {len(items)} |")
    top += ["", "## Using the files", "",
            "- Keep `parts/` and `assemblies/` together: assemblies link to the part files by relative path.",
            "- To keep a pivot moving in your own design, insert the part files directly and recreate the "
            "joint. A finished assembly linked into another design comes in as one rigid block. The "
            "script for each assembly in `scripts/generated/assemblies/` shows the joints it uses.",
            "- SolidCraft's file format changes between versions. Open the `.sc` files with the version "
            "above or newer, or use the `.step` copies.", ""]
    (OUT / "index.md").write_text("\n".join(top))


def load_catalog() -> dict[str, P.Part]:
    for r in rows("cross_reference"):
        P.XREFS.setdefault(r["part_number"], []).append(
            {k: r[k] for k in ("other_vendor", "other_part_number", "relation", "note")})
    catalog: dict[str, P.Part] = {}
    for name, gen in FAMILIES:
        for row in rows(name):
            if name == "spherical_bearings":
                P.register_bearing(row)
            made = gen(row)
            if not made:   # never drop a data row quietly
                raise SystemExit(f"{name}.csv: no model for {row['part_number']} ({row.get('style', '')})")
            for part in made:
                catalog[part.key] = part
    names = [p.name for p in catalog.values()]
    twice = {n for n in names if names.count(n) > 1}
    if twice:
        raise SystemExit(f"two parts would share a file name: {sorted(twice)}")
    return catalog


def main(argv: list[str]) -> int:
    only = [a.lower() for a in argv]
    report = {"units": "inches (dims_in); file paths are relative to components/",
              "built_with": f"SolidCraft {version()}",
              "parts": {}, "assemblies": {}, "problems": []}
    files: dict[str, str] = {}
    catalog = load_catalog()
    recipes = json.loads((DATA / "assemblies.json").read_text())
    if only:
        recipes = [r for r in recipes if any(o in r["key"].lower() for o in only)]
        used = {v for r in recipes for v in r.values() if isinstance(v, str)}
        used |= {catalog[r["cup"]].dims["snap_ring"] for r in recipes if "cup" in r}
        todo = [p for k, p in catalog.items() if k.removesuffix(".ball") in used]
    else:
        todo = list(catalog.values())
        shutil.rmtree(OUT, ignore_errors=True)   # a full build starts clean, so nothing stale ships
        shutil.rmtree(GEN, ignore_errors=True)
    for part in todo:
        try:
            build_part(part, files, report)
        except Exception as e:  # keep going: one bad part should not hide the others
            report["problems"].append(f"{part.key}: {e}")
        print("part", part.name, "-", report["parts"].get(part.key, {}).get("volume_check", "FAILED"), flush=True)
    names: set[str] = set()
    for recipe in recipes:
        try:
            build_assembly(recipe, files, catalog, report, names)
            entry = report["assemblies"][recipe["key"]]
            print("assembly", entry["name"], "-", entry["pivot"].get("max_misalignment_deg", "no limit"), flush=True)
        except Exception as e:
            report["problems"].append(f"{recipe['key']}: {e}")
            print("assembly", recipe["key"], "FAILED", flush=True)
    for junk in list(OUT.rglob("*.bak")) + list(GEN.rglob("*.bak")):   # SolidCraft's re-save backups
        junk.unlink()
    if not only:
        (OUT / "catalog.json").write_text(json.dumps(report, indent=1) + "\n")
        write_indexes(report)
    print(f"\n{len(report['parts'])} parts, {len(report['assemblies'])} assemblies, "
          f"{len(report['problems'])} problems")
    for p in report["problems"]:
        print("  PROBLEM", p)
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
