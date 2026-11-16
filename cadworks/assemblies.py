"""Assembly recipes: which parts go together, how they are joined, and how the
pivot limit is found.

SolidCraft links part files into an assembly as rigid components, and a linked
sub-assembly does not articulate, so every assembly here places its parts
directly. The fixed side (cup, rod end body, outer sleeve) is grounded and the
pin side (ball, spacers, bolt, tabs) moves on one joint named "Pivot".
"""
from __future__ import annotations

import math
from pathlib import Path

from . import parts as P
from .sc import Script, mm

Z = [0, 0, 1]


class Assembly:
    def __init__(self, key: str, title: str, kind: str, files: dict[str, Path], catalog: dict[str, P.Part]):
        self.key, self.title, self.kind = key, title, kind
        self.files, self.catalog = files, catalog
        self.s = Script()
        self.members: list[dict] = []
        self.fixed: list[str] = []
        self.moving: list[str] = []
        self.exclude: list[list[str]] = []
        self.pivot: dict | None = None
        self.needed: list[P.Part] = []   # generic parts to build first

    def add(self, name: str, part_key: str, z: float = 0.0, side: str = "fixed") -> str:
        part = self.catalog[part_key]
        self.s.cmd("component.insert_design", path=str(self.files.get(part_key, Path("not-built-yet")).resolve()), name=name,
                   translate=[0, 0, mm(z)])
        props = {"vendor": part.vendor, **{k: v for k, v in part.properties.items() if k != "source"}}
        self.s.cmd("component.metadata.set", component=name, bom_type=part.bom_type,
                   properties={k: v for k, v in props.items() if v})
        occ = f"{name}:1"
        (self.fixed if side == "fixed" else self.moving).append(occ)
        self.members.append({"name": name, "occurrence": occ, "part": part_key,
                             "part_number": part.part_number, "side": side})
        return occ

    def flip_onto(self, occ: str, anchor: str, point, axis) -> None:
        """Turn a part inserted at the origin so its +Z lies along `axis` at `point` on the anchor."""
        self.s.cmd("joint.create", type="rigid", name=f"Seat {occ}", flip=True,
                   a={"occurrence": anchor, "point": [mm(c) for c in point], "z": list(axis)},
                   b={"occurrence": occ, "point": [0, 0, 0], "z": Z})

    def pin_stack(self, stack: float, bolt: float) -> None:
        """Reference tabs either side of a stack `stack` wide, with a bolt and nut through them."""
        t = P.TAB_THICKNESS
        length = math.ceil((stack + 2 * t + 0.875 * bolt + 0.125) / 0.25) * 0.25
        for part in (P.tab(bolt), P.hex_bolt(bolt, length), P.hex_nut(bolt)):
            if part.key not in self.catalog:
                self.catalog[part.key] = part
                self.needed.append(part)
        tab_key, bolt_key, nut_key = f"REF-TAB-{bolt:.4f}", P.bolt_key(bolt, length), f"HEX-NUT-{bolt:.4f}"
        self.add("Tab top", tab_key, stack / 2, "moving")
        self.add("Tab bottom", tab_key, -stack / 2 - t, "moving")
        self.add("Bolt", bolt_key, -stack / 2 - t, "moving")
        self.add("Nut", nut_key, stack / 2 + t, "moving")

    def finish(self, pivot_type: str, a: str, b: str, find_limits: bool) -> None:
        flipped = {c["params"]["b"]["occurrence"] for c in self.s.commands
                   if c["command"] == "joint.create" and c["params"]["name"].startswith("Seat ")}
        self.s.cmd("occurrence.ground", occurrence=self.fixed[0], grounded=True)
        held = [o for o in self.fixed if o not in flipped]
        if len(held) > 1:
            self.s.cmd("joint.rigid_group", occurrences=held)
        self.s.cmd("joint.create", type=pivot_type, name="Pivot", flip=True,
                   a={"occurrence": a, "point": [0, 0, 0], "z": Z},
                   b={"occurrence": b, "point": [0, 0, 0], "z": Z})
        group = [b] + [o for o in self.moving if o != b and o not in flipped]
        if len(group) > 1:
            self.s.cmd("joint.rigid_group", occurrences=group)
        self.s.cmd("joint.list")
        self.pivot = {"joint": "Pivot", "type": pivot_type, "fixed": a, "moving": b}
        if find_limits:
            self.s.cmd("joint.find_limits", joint="Pivot", index=1, occurrences=self.moving,
                       against=self.fixed, exclude_pairs=self.exclude)


def _spacers(asm: Assembly, spacer_key: str | None, ball_occ: str, ball_width: float, bore: float):
    """Add a spacer pair (or none) on the ball faces. Returns (stack width, bolt diameter)."""
    if not spacer_key:
        return ball_width, bore
    sp = asm.catalog[spacer_key]
    top = asm.add("Spacer top", spacer_key, ball_width / 2, "moving")
    bottom = asm.add("Spacer bottom", spacer_key, 0, "moving")
    asm.flip_onto(bottom, ball_occ, (0, 0, -ball_width / 2), (0, 0, -1))
    return ball_width + 2 * sp.dims["shoulder_height"], sp.dims["bolt"]


def uniball(recipe: dict, files, catalog) -> Assembly:
    bearing, cup_key, spacer_key = recipe["bearing"], recipe["cup"], recipe["spacer"]
    b, c = catalog[bearing].dims, catalog[cup_key].dims
    asm = Assembly(recipe["key"], recipe["title"], "uniball", files, catalog)
    cup = asm.add("Cup", cup_key)
    race = asm.add("Race", bearing)
    asm.add("Snap ring", c["snap_ring"], b["race_width"] / 2 + catalog[c["snap_ring"]].dims["thickness"] / 2)
    ball = asm.add("Ball", f"{bearing}.ball", side="moving")
    stack, bolt = _spacers(asm, spacer_key, ball, b["ball_width"], b["bore"])
    asm.pin_stack(stack, bolt)
    asm.exclude = [[race, ball]]
    asm.finish("ball", race, ball, find_limits=True)
    return asm


def rod_end(recipe: dict, files, catalog) -> Assembly:
    re_key, nut_key, spacer_key = recipe["rod_end"], recipe.get("jam_nut"), recipe.get("spacer")
    d = catalog[re_key].dims
    asm = Assembly(recipe["key"], recipe["title"], "rod_end", files, catalog)
    body = asm.add("Rod end", re_key)
    if nut_key:
        nut = asm.add("Jam nut", nut_key)
        x = d["length"] - d["thread_length"] + catalog[nut_key].dims["width"] / 2 + 0.25
        asm.flip_onto(nut, body, (x, 0, 0), (1, 0, 0))
    ball = asm.add("Ball", f"{re_key}.ball", side="moving")
    stack, bolt = _spacers(asm, spacer_key, ball, d["ball_width"], d["bore"])
    asm.pin_stack(stack, bolt)
    asm.exclude = [[body, ball]]
    asm.finish("ball", body, ball, find_limits=True)
    return asm


def bushing_pivot(recipe: dict, files, catalog) -> Assembly:
    bush_key, outer_key, inner_key = recipe["bushing"], recipe["outer"], recipe.get("inner")
    bu, o = catalog[bush_key].dims, catalog[outer_key].dims
    asm = Assembly(recipe["key"], recipe["title"], "bushing_pivot", files, catalog)
    outer = asm.add("Outer sleeve", outer_key)
    asm.add("Bushing top", bush_key, o["length"] / 2)
    bottom = asm.add("Bushing bottom", bush_key, 0)
    asm.flip_onto(bottom, outer, (0, 0, -o["length"] / 2), (0, 0, -1))
    if inner_key:
        i = catalog[inner_key].dims
        pin = asm.add("Inner sleeve", inner_key, side="moving")
        stack, bolt = i["length"], i["id"]
    else:
        pin = None
        stack, bolt = o["length"] + 2 * bu["flange_length"], bu["id"]
    asm.pin_stack(stack, bolt)
    asm.finish("revolute", outer, pin or "Bolt:1", find_limits=False)
    return asm


BUILDERS = {"uniball": uniball, "rod_end": rod_end, "bushing_pivot": bushing_pivot}
