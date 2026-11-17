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
import re

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
        self.bare_reason = BARE_REASON          # what reaches what at that limit

    def add(self, role: str, part_key: str, z: float = 0.0, side: str = "fixed", x: float = 0.0) -> str:
        part = self.catalog[part_key]
        n = self.count[part_key] = self.count.get(part_key, 0) + 1
        # paths are relative to the script's own folder, so the repository can live anywhere
        path = LINK_PREFIX + self.files[part_key]
        self.s.cmd("component.insert_design", path=path, translate=[mm(x), 0, mm(z)], reuse=n > 1)
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


BARE_REASON = ("edge of the ball's bore reaching the edge of the joint's flat face "
               "(worked out from the catalog dimensions; no spacers)")
SHOULDER_REASON = ("ball's shoulder reaching the rim of the rod end's head "
                   "(worked out from the catalog dimensions; no spacers)")


def bare_limit(bore: float, ball_dia: float, face_width: float) -> float:
    """Tilt, in degrees, at which the edge of the ball's bore reaches the edge of the joint's flat face.

    With no spacers the bolt through the bore is what meets the rod end or race, and it does so where
    the bore's wall lines up with the rim of the socket opening. The rim lies on the ball's sphere at
    half the face width from the centre; the bore wall is its radius off the tilted axis.
    """
    R = ball_dia / 2
    return round(math.degrees(math.acos(bore / 2 / R) - math.asin(face_width / 2 / R)), 2)


def shoulder_limit(shoulder_dia: float, ball_dia: float, face_width: float) -> float:
    """Tilt, in degrees, at which a high misalignment ball's shoulder reaches the rim of the head.

    The shoulder is a cylinder that leaves the sphere where its radius meets it, asin(shoulder
    radius / R) from the ball's axis; the rim of the head opening is asin(rim radius / R) from it. The
    ball tilts by the difference before the shoulder meets the rim, well before the bolt would. This
    matches the FK and Aurora catalog angle of every shouldered ball in rod_ends.csv within 0.7 degrees.
    """
    R = ball_dia / 2
    rim = math.sqrt(R * R - (face_width / 2) ** 2)
    return round(math.degrees(math.asin(rim / R) - math.asin(shoulder_dia / 2 / R)), 2)


def _pitch(thread: str) -> float:
    """'3/4-16 UNF-3A LH' or '1-1/4-12 UNF' -> 16, 12 (threads per inch); 'M16 x 2.0' or 'M16x2.0 6H' -> 2.0 (mm)."""
    if thread.startswith("M"):
        size = thread.split()[0]
        return float(size.split("x")[1] if "x" in size else thread.split()[2])
    return float(re.search(r"-(\d+)\s*UN", thread).group(1))


def _same_thread(a: dict, b: dict) -> bool:
    """Whether two parts' dims (thread, thread_dia, hand) describe threads that screw together."""
    return (abs(a["thread_dia"] - b["thread_dia"]) < 1e-3 and a["hand"] == b["hand"]
            and a["thread"].startswith("M") == b["thread"].startswith("M")
            and _pitch(a["thread"]) == _pitch(b["thread"]))


def _bung_words(bung: P.Part) -> str:
    """The bung's title without its thread (the rod end already gives it)."""
    d = bung.dims
    label = P.BUNG_LABELS[d["style"].replace(" ", "_")]
    if "square" in d:
        return f"{label} {inch(d['square'])} square x {inch(d['length'])} long"
    return f"{label} for {inch(d['tube_od'])} x {inch(d['tube_wall'])} wall tube"


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
    asm.name = f"Uniball Stack {inch(b['bore'])}, {wording}, {inch(bolt)} bolt hole, {inch(asm.stated_stack or stack)} stack"
    asm.exclude = [[race, ball]]
    if not spacer_key:
        asm.bare_limit = bare_limit(b["bore"], b["ball_dia"], b["race_width"])
    asm.finish("ball", race, ball, find_limits=asm.bare_limit is None)
    return asm


def _link_size(rend: P.Part) -> str:
    """How a link names its rod end. The main series (a plain-ball FK JMX male whose thread is the
    bore size, as the first links were) is just '0.75in RH'; anything else adds its thread, series and
    kind, so links that differ only in those get different names."""
    d = rend.dims
    metric = d["thread"].startswith("M")
    size = f"{P.num(round(d['bore'] * 25.4, 2))}mm" if metric else inch(d["bore"])
    series = rend.title.split(", ")[2].split()[0]           # '..., JMX chromoly PTFE lined'
    plain = (rend.vendor == "FK" and series == "JMX" and d["style"] == "male" and "shoulder_dia" not in d
             and not metric and abs(d["thread_dia"] - d["bore"]) < 1e-3)
    if plain:
        return f"{size} {d['hand']}"
    kind = ["female"] if d["style"] == "female" else []
    if "shoulder_dia" in d:
        kind.append("high misalignment")
    if rend.material.startswith("aluminium"):
        kind.insert(0, "aluminium")
    return " ".join([size, P._re_thread(d["thread"], d["thread_dia"])[0], d["hand"] + ",", rend.vendor, series] + kind)


def rod_end(recipe: dict, files, catalog) -> Assembly:
    """A rod end and its ball, optionally a jam nut on the shank, a weld-in bung screwed on past the nut
    (the nut seated on the bung's end face), and a pair of spacers in the ball.

    The body, jam nut and bung are the fixed side and the ball and spacers swing on the Pivot joint, so
    the limit search still asks only when the spacers reach the rod end side. Threads, hands, the ball
    bore and (for a misalignment spacer) the ball its seat is shaped around are checked to match.
    """
    re_key, nut_key, spacer_key = recipe["rod_end"], recipe.get("jam_nut"), recipe.get("spacer")
    bung_key = recipe.get("bung")
    rend = catalog[re_key]
    d = rend.dims
    if d["style"] not in ("male", "female") or "stud_thread" in d:
        raise ValueError(f"{re_key}: only male and female rod ends with a plain or shouldered ball are assembled")
    if (nut_key or bung_key) and d["style"] != "male":
        raise ValueError(f"{re_key}: a jam nut or bung goes on a male shank")
    asm = Assembly(recipe, "rod_end", files, catalog)
    body = asm.add("Rod end", re_key)
    x_seat = d["length"] - d["thread_length"] + 0.25   # the nut sits 1/4" along from where the thread starts
    if nut_key:
        nd = catalog[nut_key].dims
        if not _same_thread(d, nd):
            raise ValueError(f"{nut_key} ({nd['thread']}) does not fit {re_key} ({d['thread']})")
        nut = asm.add("Jam nut", nut_key)
        asm.flip_onto(nut, body, (x_seat + nd["width"] / 2, 0, 0), (1, 0, 0))
        x_seat += nd["width"]
    tail = ""
    if bung_key:
        bung = catalog[bung_key]
        bd = bung.dims
        if not _same_thread(d, bd):
            raise ValueError(f"{bung_key} ({bd['thread']}) does not fit {re_key} ({d['thread']})")
        engaged = d["length"] - x_seat
        if engaged > bd["thread_depth"] + 1e-6:
            raise ValueError(f"{re_key}: {engaged:.3f}in of shank would go into {bung_key}, "
                             f"which is threaded only {bd['thread_depth']}in deep")
        # the bung's own frame already has its thread along +X and its seat face at x = 0
        asm.add("Weld-in bung", bung_key, x=x_seat)
        tail = ", " + _bung_words(bung)
    ball = asm.add("Ball", f"{re_key}.ball", side="moving")
    if spacer_key:
        sd = catalog[spacer_key].dims
        if abs(sd["ball_bore"] - d["bore"]) > 1e-3:
            raise ValueError(f"{spacer_key} is for a {sd['ball_bore']}in ball bore, {re_key} has {d['bore']}in")
        if "seat_sphere_dia" in sd and abs(sd["seat_sphere_dia"] - d["ball_dia"]) > 1e-3:
            raise ValueError(f"{spacer_key}'s seat is shaped for a {sd['seat_sphere_dia']}in ball "
                             f"({sd['seat_matched_to']}); {re_key}'s ball is {d['ball_dia']}in")
    stack, bolt, wording = _spacers(asm, spacer_key, ball, d["ball_width"], d["bore"])
    # name_note tells apart spacers that share a style, bolt and stack (such as head diameters)
    note = f", {recipe['name_note']}" if recipe.get("name_note") else ""
    # a metric rod end's own bore and width read in millimetres; Kartek's spacers are inch parts
    size = (lambda v: f"{P.num(round(v * 25.4, 1))}mm") if d["thread"].startswith("M") and not spacer_key else inch
    asm.name = (f"Rod End Link {_link_size(rend)}, {wording}, {size(bolt)} bolt hole, "
                f"{size(asm.stated_stack or stack)} stack{note}{tail}")
    asm.exclude = [[body, ball]]
    if not spacer_key:
        if "shoulder_dia" in d:
            asm.bare_limit = shoulder_limit(d["shoulder_dia"], d["ball_dia"], d["head_width"])
            asm.bare_reason = SHOULDER_REASON
        else:
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
