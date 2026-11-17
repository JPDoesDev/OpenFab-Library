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

import math

from . import parts as P
from .parts import inch
from .sc import Script, mm

Z = [0, 0, 1]
FOLDERS = {"uniball": "Uniball Stacks", "rod_end": "Rod End Links", "bushing_pivot": "Bushing Pivots"}
LINK_PREFIX = ""   # from the generated script's folder to components/, set by the build


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
        self.bare_limit: float | None = None  # worked out by hand when nothing in the assembly stops the ball
        self.bare_limit_by: str | None = None  # what sets bare_limit, when it is not the bore edge at the face

    def add(self, role: str, part_key: str, z: float = 0.0, side: str = "fixed") -> str:
        part = self.catalog[part_key]
        n = self.count[part_key] = self.count.get(part_key, 0) + 1
        # paths are relative to the script's own folder, so the repository can live anywhere
        path = LINK_PREFIX + self.files[part_key]
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


def bare_limit(bore: float, ball_dia: float, face_width: float) -> float:
    """Tilt, in degrees, at which the edge of the ball's bore reaches the edge of the joint's flat face.

    With no spacers the bolt through the bore is what meets the rod end or race, and it does so where
    the bore's wall lines up with the rim of the socket opening. The rim lies on the ball's sphere at
    half the face width from the centre; the bore wall is its radius off the tilted axis.
    """
    R = ball_dia / 2
    return round(math.degrees(math.acos(bore / 2 / R) - math.asin(face_width / 2 / R)), 2)


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


SEAT_TOL = 0.010    # a misalignment spacer's seat sphere must match the ball's diameter and width this closely
STACK_TOL = 0.020   # a spacer pair's stack must leave room for this ball: 2 x (half stack - shoulder) = ball width


def uniball_spacer_problem(b: dict, sp: dict) -> str | None:
    """Why a spacer cannot go in this uniball's ball, or None if it can.

    Spacers are made for one ball width: the vendor's half stack less the shoulder is half the ball they
    expect, and the pins meet in the middle of it. A misalignment spacer's seat is also a band of one ball's
    sphere (parts.SEAT_BALL), so it only seats on a ball of that diameter and width.
    """
    if b.get("shoulder_dia"):
        return "a shoulder ball takes no spacers"
    if abs(sp["ball_bore"] - b["bore"]) > 1e-4:
        return f"spacer is for a {inch(sp['ball_bore'])} bore, the ball is {inch(b['bore'])}"
    made_for = 2 * (sp["half_stack"] - sp["shoulder_height"])
    if abs(made_for - b["ball_width"]) > STACK_TOL:
        return f"spacer pair is made for a {inch(round(made_for, 3))} wide ball, this one is {inch(b['ball_width'])}"
    if "seat_sphere_dia" in sp:
        bd, bw, ref = P.SEAT_BALL[sp["ball_bore"]]
        if abs(bd - b["ball_dia"]) > SEAT_TOL or abs(bw - b["ball_width"]) > SEAT_TOL:
            return (f"misalignment seat is shaped for the {ref} ball ({inch(bd)} x {inch(bw)} wide), "
                    f"this ball is {inch(b['ball_dia'])} x {inch(b['ball_width'])} wide")
    return None


def uniball_bare_limit(b: dict, c: dict, ring: dict, lift: float) -> tuple[float, str]:
    """Tilt at which a spacer-less uniball first meets something, worked out in the plane of the tilt.

    No spacers means the bolt (the bore's diameter) is what swings past the race, snap ring and cup; a ball
    with misalignment shoulders swings its shoulder (and the shoulder's end corners) as well. Ball and race
    share a sphere, so that pair is left out, as in the collision search. The cup and ring sit `lift` above
    their nominal place (a race narrower than the cup's seat sits on the lip). Returns (degrees, what touches).
    """
    R, T, W, B = b["ball_dia"] / 2, b["race_width"], b["ball_width"], b["bore"]
    rs = (b.get("shoulder_dia") or 0) / 2
    Tc, rt = c["seat_depth"], ring["thickness"]
    zb, zs, zg, zt = c["bottom_z"] + lift, -Tc / 2 + lift, Tc / 2 + lift, c["top_z"] + lift
    # fixed material as (r_min, r_max, z_min, z_max, name) in the half plane; the race's own ring
    # is from its spherical bore out, handled below
    regions = [(c["lip_id"] / 2, c["od"] / 2, zb, zs, "the cup lip"),
               (ring["id"] / 2, ring["od"] / 2, zg, zg + rt, "the snap ring"),
               (b["od"] / 2, c["od"] / 2, zs, zt, "the cup wall")]
    rims = [(math.sqrt(R * R - (T / 2) ** 2), T / 2, "the race's face edge"),
            (math.sqrt(R * R - (T / 2) ** 2), -T / 2, "the race's face edge")]
    for r0, r1, z0, z1, name in regions:
        rims += [(r0, z0, name), (r0, z1, name)]
    corners = [(rs, W / 2), (rs, -W / 2)] if rs else []

    def in_moving(x: float, z: float) -> bool:   # a point in the ball's own frame
        if abs(x) < B / 2:
            return True                          # the bolt, along the whole axis
        return bool(rs) and abs(x) < rs and abs(z) <= W / 2 and x * x + z * z > R * R

    def fixed_at(x: float, z: float) -> str | None:   # a point in the cup's frame
        r = abs(x)
        if abs(z) <= T / 2 and r * r + z * z > (R + 1e-4) ** 2 and r < b["od"] / 2:
            return "the race"
        return next((name for r0, r1, z0, z1, name in regions if r0 < r < r1 and z0 < z < z1), None)

    for step in range(1, 9001):
        t = math.radians(step / 100)
        ct, st = math.cos(t), math.sin(t)
        for r, z, name in rims:
            for x in (r, -r):   # into the ball's frame: rotate back by the tilt
                if in_moving(x * ct + z * st, -x * st + z * ct):
                    return round(step / 100, 2), name
        for x0, z0 in corners:
            for x in (x0, -x0):
                hit = fixed_at(x * ct - z0 * st, x * st + z0 * ct)
                if hit:
                    return round(step / 100, 2), f"the shoulder's end against {hit}"
    raise ValueError("nothing stops the ball within 90 degrees")


def uniball(recipe: dict, files, catalog) -> Assembly:
    """A uniball pressed into a cup against its lip, held by the cup's own snap ring, with a spacer pair or
    none. A race narrower than the bearing the cup's seat was cut for sits on the lip with the gap under the
    ring, as it does in the real cup."""
    bearing, cup_key, spacer_key = recipe["bearing"], recipe["cup"], recipe["spacer"]
    b, c = catalog[bearing].dims, catalog[cup_key].dims
    ring_key = c["snap_ring"]
    ring = catalog[ring_key].dims
    if abs(b["od"] - c["bearing_od"]) > 1e-3 or c.get("bore_undersize"):
        raise ValueError(f"{bearing} ({inch(b['od'])} OD) does not fit the bore of {cup_key}")
    lift = (c["seat_depth"] - b["race_width"]) / 2   # the cup (and its ring) up, so the race sits on the lip
    if lift < -1e-4:
        raise ValueError(f"{bearing} is wider than the seat of {cup_key}")
    if spacer_key:
        why = uniball_spacer_problem(b, catalog[spacer_key].dims)
        if why:
            raise ValueError(f"{spacer_key} in {bearing}: {why}")
    asm = Assembly(recipe, "uniball", files, catalog)
    asm.add("Cup", cup_key, lift)
    race = asm.add("Bearing", bearing)
    asm.add("Snap ring", ring_key, lift + c["seat_depth"] / 2 + ring["thickness"] / 2)
    ball = asm.add("Ball", f"{bearing}.ball", side="moving")
    stack, bolt, wording = _spacers(asm, spacer_key, ball, b["ball_width"], b["bore"])
    what = "Wobble Stopper Stack (no end plates)" if c.get("style") == "wobble stopper" else "Uniball Stack"
    ids = f"{bearing} in {cup_key}" + (f", {spacer_key}" if spacer_key else "")
    asm.name = (f"{what} {inch(b['bore'])}, {wording}, {inch(bolt)} bolt hole, "
                f"{inch(asm.stated_stack or stack)} stack ({ids})")
    asm.exclude = [[race, ball]]
    if not spacer_key:
        asm.bare_limit, by = uniball_bare_limit(b, c, ring, lift)
        moving = "the ball's shoulder or bore" if b.get("shoulder_dia") else "the edge of the ball's bore"
        asm.bare_limit_by = (f"{moving} reaching {by}" if not by.startswith("the shoulder's") else by) + \
            " (worked out in the plane of the tilt from the catalog dimensions; no spacers)"
    asm.finish("ball", race, ball, find_limits=asm.bare_limit is None)
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
    asm.name = f"Rod End Link {inch(d['bore'])} {d['hand']}, {wording}, {inch(bolt)} bolt hole, {inch(asm.stated_stack or stack)} stack"
    asm.exclude = [[body, ball]]
    if not spacer_key:
        asm.bare_limit = bare_limit(d["bore"], d["ball_dia"], d["head_width"])
    asm.finish("ball", body, ball, find_limits=asm.bare_limit is None)
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
                f"{inch(bolt)} bolt hole")
    if pin:
        asm.finish("revolute", outer, pin, find_limits=False)
    else:
        asm.hold_all()   # the bolt runs straight in the bushings, so nothing here turns
    return asm


BUILDERS = {"uniball": uniball, "rod_end": rod_end, "bushing_pivot": bushing_pivot}
