"""Assembly recipes: which parts go together, how they are joined, and how the
pivot limit is found.

SolidCraft links part files into an assembly as rigid components, and a linked
sub-assembly does not articulate, so every assembly here places its parts
directly. The fixed side (cup, rod end body, outer sleeve) is grounded and the
pin side (ball and spacers, or the inner sleeve) moves on one joint named "Pivot".
Bolts, nuts, washers and mount tabs are the builder's own and are not included.

Components keep their part file's name, so the design tree reads the same as
the parts folder. A part used twice is one component with two occurrences.
"""
from __future__ import annotations

from . import parts as P
from .parts import inch
from .sc import Script, mm

Z = [0, 0, 1]
FOLDERS = {"uniball": "Uniball Stacks", "rod_end": "Rod End Links", "bushing_pivot": "Bushing Pivots"}


def also_available_as(part: P.Part) -> str:
    return "; ".join(f"{x['other_vendor']} {x['other_part_number']} ({x['relation']})" for x in part.xrefs)


class Assembly:
    def __init__(self, recipe: dict, kind: str, files: dict[str, str], catalog: dict[str, P.Part]):
        self.key, self.description, self.kind = recipe["key"], recipe["title"], kind
        self.name = ""                       # readable file name, set by the recipe
        self.files, self.catalog = files, catalog
        self.s = Script()
        self.members: list[dict] = []
        self.fixed: list[str] = []
        self.moving: list[str] = []
        self.seated: set[str] = set()        # occurrences held by their own seating joint
        self.exclude: list[list[str]] = []
        self.pivot: dict | None = None
        self.count: dict[str, int] = {}
        self.stated_stack: float | None = None

    def add(self, role: str, part_key: str, z: float = 0.0, side: str = "fixed") -> str:
        part = self.catalog[part_key]
        n = self.count[part_key] = self.count.get(part_key, 0) + 1
        # paths are relative to the script's folder (scripts/assemblies), so the release can be moved
        path = "../../" + self.files[part_key]
        self.s.cmd("component.insert_design", path=path, translate=[0, 0, mm(z)], reuse=n > 1)
        if n == 1:
            props = {"vendor": part.vendor, "also_available_as": also_available_as(part)}
            self.s.cmd("component.metadata.set", component=part.name, bom_type=part.bom_type,
                       properties={k: v for k, v in props.items() if v})
        occ = f"{part.name}:{n}"
        (self.fixed if side == "fixed" else self.moving).append(occ)
        self.members.append({"role": role, "occurrence": occ, "part": part_key,
                             "part_number": part.part_number, "side": side})
        return occ

    def flip_onto(self, occ: str, anchor: str, point, axis) -> None:
        """Turn a part inserted at the origin so its +Z lies along `axis` at `point` on the anchor."""
        self.seated.add(occ)
        self.s.cmd("joint.create", type="rigid", name=f"Seat {len(self.seated)}", flip=True,
                   a={"occurrence": anchor, "point": [mm(c) for c in point], "z": list(axis)},
                   b={"occurrence": occ, "point": [0, 0, 0], "z": Z})

    def hold_all(self) -> None:
        """An assembly with no moving member: ground it and hold the rest in place."""
        self.s.cmd("occurrence.ground", occurrence=self.fixed[0], grounded=True)
        held = [o for o in self.fixed if o not in self.seated]
        if len(held) > 1:
            self.s.cmd("joint.rigid_group", occurrences=held)
        self.s.cmd("joint.list")
        self.pivot = {"joint": None, "note": "no inner sleeve: the bolt runs directly in the bushings"}

    def finish(self, pivot_type: str, a: str, b: str, find_limits: bool) -> None:
        self.s.cmd("occurrence.ground", occurrence=self.fixed[0], grounded=True)
        held = [o for o in self.fixed if o not in self.seated]
        if len(held) > 1:
            self.s.cmd("joint.rigid_group", occurrences=held)
        self.s.cmd("joint.create", type=pivot_type, name="Pivot", flip=True,
                   a={"occurrence": a, "point": [0, 0, 0], "z": Z},
                   b={"occurrence": b, "point": [0, 0, 0], "z": Z})
        group = [b] + [o for o in self.moving if o != b and o not in self.seated]
        if len(group) > 1:
            self.s.cmd("joint.rigid_group", occurrences=group)
        self.s.cmd("joint.list")
        self.pivot = {"joint": "Pivot", "type": pivot_type, "fixed": a, "moving": b}
        if find_limits:
            self.s.cmd("joint.find_limits", joint="Pivot", index=1, occurrences=self.moving,
                       against=self.fixed, exclude_pairs=self.exclude)


def _spacers(asm: Assembly, spacer_key: str | None, ball_occ: str, ball_width: float, bore: float):
    """Add a spacer pair (or none) on the ball faces. Returns (stack, bolt diameter, wording)."""
    if not spacer_key:
        return ball_width, bore, "no spacers"
    sp = asm.catalog[spacer_key]
    asm.add("Spacer top", spacer_key, ball_width / 2, "moving")
    bottom = asm.add("Spacer bottom", spacer_key, 0, "moving")
    asm.flip_onto(bottom, ball_occ, (0, 0, -ball_width / 2), (0, 0, -1))
    # the vendor's stated stack (2 x half stack) names the assembly; geometry uses the ball width
    asm.stated_stack = 2 * sp.dims["half_stack"]
    return ball_width + 2 * sp.dims["shoulder_height"], sp.dims["bolt"], f"{sp.dims['style']} spacers"


def uniball(recipe: dict, files, catalog) -> Assembly:
    bearing, cup_key, spacer_key = recipe["bearing"], recipe["cup"], recipe["spacer"]
    b, c = catalog[bearing].dims, catalog[cup_key].dims
    asm = Assembly(recipe, "uniball", files, catalog)
    asm.add("Cup", cup_key)
    race = asm.add("Bearing", bearing)
    asm.add("Snap ring", c["snap_ring"], b["race_width"] / 2 + catalog[c["snap_ring"]].dims["thickness"] / 2)
    ball = asm.add("Ball", f"{bearing}.ball", side="moving")
    stack, bolt, wording = _spacers(asm, spacer_key, ball, b["ball_width"], b["bore"])
    asm.name = f"Uniball Stack {inch(b['bore'])}, {wording}, {inch(bolt)} bolt, {inch(asm.stated_stack or stack)} stack"
    asm.exclude = [[race, ball]]
    asm.finish("ball", race, ball, find_limits=True)
    return asm


def rod_end(recipe: dict, files, catalog) -> Assembly:
    re_key, nut_key, spacer_key = recipe["rod_end"], recipe.get("jam_nut"), recipe.get("spacer")
    d = catalog[re_key].dims
    asm = Assembly(recipe, "rod_end", files, catalog)
    body = asm.add("Rod end", re_key)
    if nut_key:
        nut = asm.add("Jam nut", nut_key)
        x = d["length"] - d["thread_length"] + catalog[nut_key].dims["width"] / 2 + 0.25
        asm.flip_onto(nut, body, (x, 0, 0), (1, 0, 0))
    ball = asm.add("Ball", f"{re_key}.ball", side="moving")
    stack, bolt, wording = _spacers(asm, spacer_key, ball, d["ball_width"], d["bore"])
    asm.name = f"Rod End Link {inch(d['bore'])} {d['hand']}, {wording}, {inch(bolt)} bolt, {inch(asm.stated_stack or stack)} stack"
    asm.exclude = [[body, ball]]
    asm.finish("ball", body, ball, find_limits=True)
    return asm


def bushing_pivot(recipe: dict, files, catalog) -> Assembly:
    bush_key, outer_key, inner_key = recipe["bushing"], recipe["outer"], recipe.get("inner")
    bush = catalog[bush_key]
    bu, o = bush.dims, catalog[outer_key].dims
    asm = Assembly(recipe, "bushing_pivot", files, catalog)
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
    asm.name = (f"Bushing Pivot {bush.material.capitalize()} {inch(o['od'])} OD, {inch(stack)} wide, "
                f"{inch(bolt)} bolt")
    if pin:
        asm.finish("revolute", outer, pin, find_limits=False)
    else:
        asm.hold_all()   # the bolt runs straight in the bushings, so nothing here turns
    return asm


BUILDERS = {"uniball": uniball, "rod_end": rod_end, "bushing_pivot": bushing_pivot}
