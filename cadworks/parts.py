"""Part families. Each function takes one data row (inches) and returns a list
of Part objects: the script that builds it, its expected volume, and the
numbers an assembly needs to place it.

Origin conventions (all axes on world Z unless noted):
  bearing race / ball   centre of the ball
  rod end body / ball   centre of the ball, bolt axis Z, shank along +X
  uniball cup           centre of the installed bearing, lip towards -Z
  snap ring             its own mid-plane
  spacer                the face that sits on the ball at z = 0, head towards +Z,
                        pin (inside the ball) towards -Z
  bushing               the flange face that sits on the sleeve end at z = 0,
                        flange towards +Z, body (inside the sleeve) towards -Z
  sleeve, jam nut       its own centre

Bolts, nuts, washers and mount tabs are left to the builder and are not modelled.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .sc import Script, mm, sphere_slice_volume

PI = math.pi


@dataclass
class Part:
    key: str                 # file stem, unique
    family: str
    part_number: str         # "" for reference geometry
    description: str
    vendor: str
    script: Script
    volume_in3: float | None  # analytic, None when not worked out
    dims: dict = field(default_factory=dict)
    estimated: list = field(default_factory=list)
    bom_type: str = "purchased"
    properties: dict = field(default_factory=dict)
    title: str = ""          # readable name without the part number
    name: str = ""           # file stem and design-tree name: title plus "(vendor part number)"
    folder: str = ""         # folder under parts/
    material: str = ""
    xrefs: list = field(default_factory=list)


XREFS: dict[str, list] = {}   # part number -> [{other_vendor, other_part_number, relation, note}]
INTERNAL = "_internal"        # helper pieces that are not things you buy


def num(v: float) -> str:
    """0.75 for 3/4, 1 for 1.000: decimals, because file names cannot hold a slash."""
    return f"{v:.4f}".rstrip("0").rstrip(".")


def inch(v: float) -> str:
    return num(v) + "in"


def f(row: dict, key: str) -> float:
    return float(row[key])


def _finish(row: dict, key: str, family: str, body: str, material: str, script: Script,
            volume, dims: dict, estimated=(), part_number=None, description=None,
            bom_type="purchased", title: str = "", folder: str = "") -> Part:
    pn = row.get("part_number", "") if part_number is None else part_number
    desc = description or row.get("description", "")
    vendor = row.get("vendor", "")
    props = {k: row[k] for k in ("thread", "source") if row.get(k)}
    xrefs = XREFS.get(pn, []) if pn else []
    if pn:
        name = f"{title} ({vendor} {pn})"
    else:
        name = title
    script.material(body, material)
    script.metadata(pn, desc, vendor, {
        "family": family, "units": "in", "dims": dims, "estimated": list(estimated),
        "also_available_as": xrefs, **props,
    })
    return Part(key, family, pn, desc, vendor, script, volume, dims, list(estimated), bom_type, props,
                title, name, folder, material, xrefs)


def _socket_ring(od: float, width: float, ball_dia: float) -> list:
    """Profile of a ring with a spherical bore (a race, or a rod end head)."""
    R, h = ball_dia / 2, width / 2
    ri = math.sqrt(R * R - h * h)
    return [(ri, -h), (od / 2, -h), (od / 2, h), (ri, h), ("arc", (ri, -h), (0, 0), True)]


def _ball(bore: float, width: float, ball_dia: float) -> list:
    R, h = ball_dia / 2, width / 2
    rf = math.sqrt(R * R - h * h)
    return [(bore / 2, -h), (rf, -h), ("arc", (rf, h), (0, 0), False), (bore / 2, h)]


def spherical_bearing(row: dict) -> list[Part]:
    pn = row["part_number"]
    B, D, W, T, bd = (f(row, k) for k in ("bore", "od", "ball_width", "race_width", "ball_dia"))
    dims = {"bore": B, "od": D, "ball_width": W, "race_width": T, "ball_dia": bd,
            "catalog_misalignment_deg": f(row, "catalog_misalignment_deg")}
    race = Script()
    race.revolve("Race", _socket_ring(D, T, bd))
    v_race = PI * (D / 2) ** 2 * T - sphere_slice_volume(bd, T)
    ball = Script()
    ball.revolve("Ball", _ball(B, W, bd))
    v_ball = sphere_slice_volume(bd, W) - PI * (B / 2) ** 2 * W
    return [
        _finish(row, pn, "spherical_bearing", "Race", row["material"], race, v_race, dims,
                title=f"Uniball {inch(B)} bore x {inch(D)} OD", folder="Uniballs"),
        _finish(row, f"{pn}.ball", "spherical_bearing_ball", "Ball", row["material"], ball, v_ball, dims,
                part_number="", description=f"Ball of {pn} (moves in the race; counted in the BOM with the race)",
                bom_type="reference", title=f"Uniball Ball {inch(B)} bore (for {pn})", folder=INTERNAL),
    ]


def thread_name(row: dict) -> str:
    """'3/4-16 UNF-3A LH' -> '0.75-16 LH'."""
    tpi = row["thread"].split("-")[1].split()[0]
    return f"{num(f(row, 'thread_dia'))}-{tpi} {row['hand']}"


def rod_end(row: dict) -> list[Part]:
    pn = row["part_number"]
    B, D, W, T, bd, A, td, C = (f(row, k) for k in (
        "bore", "head_dia", "ball_width", "head_width", "ball_dia", "length", "thread_dia", "thread_length"))
    dims = {"bore": B, "head_dia": D, "ball_width": W, "head_width": T, "ball_dia": bd,
            "length": A, "thread": row["thread"], "thread_dia": td, "thread_length": C, "hand": row["hand"],
            "catalog_misalignment_deg": f(row, "catalog_misalignment_deg")}
    body = Script()
    body.revolve("Body", _socket_ring(D, T, bd))
    # Shank: starts inside the head ring, clear of the socket, and runs to A from the ball centre.
    x0 = math.sqrt((D / 2) ** 2 - (T / 2) ** 2) - 0.02
    body.cylinder("Shank", td, A - x0, base=(x0, 0, 0), axis="X")
    # Cosmetic thread over the threaded length, from the free end. SolidCraft's shaft threads have no
    # Unified form, so it is given as the same 60-degree profile in millimetres (3/4-16 is M19.05x1.5875);
    # the feature name carries the real callout.
    tpi = float(row["thread"].split("-")[1].split()[0])
    body.cmd("solid.thread", face=[mm((x0 + A) / 2), 0, mm(td / 2)],
             designation=f"M{num(td * 25.4)}x{num(25.4 / tpi)}",
             hand="left" if row["hand"] == "LH" else "right", length=mm(C), name=f"Thread {row['thread']}")
    ball = Script()
    ball.revolve("Ball", _ball(B, W, bd))
    v_ball = sphere_slice_volume(bd, W) - PI * (B / 2) ** 2 * W
    dims["thread_feature"] = f"cosmetic, M{num(td * 25.4)}x{num(25.4 / tpi)} (the Unified size in millimetres)"
    est = ["shank is a plain cylinder at thread major diameter with a cosmetic thread; "
           "no neck or grease fitting modelled"]
    return [
        _finish(row, pn, "rod_end", "Body", row["material"], body, None, dims, est,
                title=f"Rod End {inch(B)} bore, {thread_name(row)}", folder="Rod Ends"),
        _finish(row, f"{pn}.ball", "rod_end_ball", "Ball", row["material"], ball, v_ball, dims,
                part_number="", description=f"Ball of {pn} (moves in the body; counted in the BOM with the body)",
                bom_type="reference", title=f"Rod End Ball {inch(B)} bore (for {pn})", folder=INTERNAL),
    ]


SPACER_LABELS = {  # style tag -> words used in the name, most specific first
    "flat_top": "Flat Top", "stepped": "Stepped", "hourglass": "Hourglass", "radius_cone": "Radius",
    "thin_edge": "Thin Edge", "thick_edge": "Thick Edge", "trophy_truck": "Trophy Truck",
    "total_chaos": "Total Chaos",
}


def spacer(row: dict) -> list[Part]:
    """Vendors publish six dimensions per spacer (ball bore, bolt, shoulder height, head diameter,
    half stack, pin depth). Everything else about the head shape is scaled from product photos."""
    base, *tags = row["style"].split("/")
    pn = row["part_number"]
    E, Db, A, Bh, C, F = (f(row, k) for k in (
        "ball_bore", "bolt", "shoulder_height", "head_dia", "half_stack", "pin_depth"))
    F = min(F, C - A) if C - A > 0 else F  # two pins must not meet inside the ball
    rb, rp, rh = Db / 2, E / 2, Bh / 2
    words = [SPACER_LABELS[t] for t in tags if t != "radius_cone"]
    label = " ".join(words + (["Radius"] if "radius_cone" in tags else []) + [base.capitalize()])
    if base == "cone" and "hourglass" in tags:
        label = "Hourglass"
    dims = {"ball_bore": E, "bolt": Db, "shoulder_height": A, "head_dia": Bh, "half_stack": C,
            "pin_depth": F, "style": label.lower()}
    pin = [(rb, -F), (rp, -F), (rp, 0)]
    vol, est = None, []
    if base == "straight":
        head = [(rh, 0), (rh, A)]
        vol = PI * (rp * rp * F + rh * rh * A) - PI * rb * rb * (F + A)
    elif base == "misalignment":
        # Seat flange at the ball, a waist, then a cone out to the head (Kartek's measuring diagram).
        rn = max(0.89 * rp, rb + 0.06)
        rf = max(rh, rp + 0.05)
        tall = "flat_top" in tags or "stepped" in tags
        hk = min(A, 0.75) if tall else A          # height over which the waist and cone happen
        head = [(rf, 0), (rf, 0.04 * hk), (rn, 0.20 * hk), (rn, 0.30 * hk), (rh, hk - 0.05)]
        if "stepped" in tags:                      # the top steps down to register in a recess
            rs = max(rb + 0.1, rh - 0.2)
            head += [(rh, A - 0.25), (rs, A - 0.25), (rs, A)]
            dims["step_dia"] = round(2 * rs, 4)
            est.append("step_dia and step height")
        else:
            head.append((rh, A))
        dims.update({"waist_dia": round(2 * rn, 4), "flange_dia": round(2 * rf, 4)})
        est += ["waist_dia", "flange_dia", "flange and cone heights"]
    elif "hourglass" in tags:
        # A full-width base on the ball, a waist, and a full-width head.
        rn = max(0.89 * rp, rb + 0.06)
        head = [(rh, 0), (rh, 0.30 * A), (rn, 0.45 * A), (rn, 0.60 * A), (rh, 0.85 * A), (rh, A)]
        dims["waist_dia"] = round(2 * rn, 4)
        est += ["waist_dia", "base, waist and head heights"]
    elif "radius_cone" in tags:
        # The pin diameter carries on as a neck, then sweeps out to the head on a concave radius.
        r = min(rh - rp, A - 0.05)
        land = max(0.03, min(0.12, A - r - 0.02))
        z0 = A - r - land
        head = ([(rp, z0)] if z0 > 1e-6 else []) + [("arc", (rp + r, z0 + r), (rp + r, z0), True)]
        if rp + r < rh - 1e-6:
            head.append((rh, z0 + r))
        head.append((rh, A))
        dims.update({"flare_radius": round(r, 4), "edge_height": round(land, 4)})
        est += ["flare_radius", "edge_height"]
    else:
        # A cone straight off the ball face out to the head, finishing in a flat edge.
        land = 0.06 if "thin_edge" in tags else max(0.06, A - (rh - rp))
        head = [(rh, A - land), (rh, A)]
        dims["edge_height"] = round(land, 4)
        est.append("edge_height (cone angle)")
    prof = pin + head + [(rb, A)]
    s = Script()
    s.revolve("Spacer", prof)
    title = f"{label} Spacer {inch(E)} to {inch(Db)} bolt, {inch(2 * C)} stack"
    return [_finish(row, pn, "spacer", "Spacer", "stainless", s, vol, dims, est, title=title, folder="Spacers")]


def cup(row: dict) -> list[Part]:
    pn = row["part_number"]
    bo, H, D, lid, lt, gd, gw = (f(row, k) for k in (
        "bearing_od", "height", "od", "lip_id", "lip_thickness", "groove_dia", "groove_width"))
    T = _race_width_for(row)  # seat depth equals the race width
    zb = -T / 2 - lt          # bottom (lip) face
    zs = -T / 2               # bearing seat
    zg0, zg1 = T / 2, T / 2 + gw
    zt = zb + H
    prof = [(lid / 2, zb), (D / 2, zb), (D / 2, zt), (bo / 2, zt), (bo / 2, zg1), (gd / 2, zg1),
            (gd / 2, zg0), (bo / 2, zg0), (bo / 2, zs), (lid / 2, zs)]
    vol = PI * ((D / 2) ** 2 * H - (lid / 2) ** 2 * lt - (bo / 2) ** 2 * (zt - zs)
                - ((gd / 2) ** 2 - (bo / 2) ** 2) * gw)
    dims = {"bearing_od": bo, "height": H, "od": D, "lip_id": lid, "lip_thickness": lt,
            "groove_dia": gd, "groove_width": gw, "seat_depth": T,
            "bottom_z": round(zb, 4), "top_z": round(zt, 4), "snap_ring": row["snap_ring"]}
    s = Script()
    s.revolve("Cup", prof)
    est = [e.strip() for e in row.get("estimated", "").split(";") if e.strip()]
    title = f"Uniball Cup {inch(bo)} bore x {inch(D)} OD x {inch(H)} tall"
    return [_finish(row, pn, "uniball_cup", "Cup", row["material"], s, vol, dims, est, title=title,
                    folder="Uniball Cups")]


_RACE_WIDTHS: dict[str, float] = {}


def _race_width_for(cup_row: dict) -> float:
    for name in cup_row["fits"].split(";"):
        if name.strip() in _RACE_WIDTHS:
            return _RACE_WIDTHS[name.strip()]
    raise KeyError(f"no bearing in data for cup {cup_row['part_number']}")


def register_bearing(row: dict) -> None:
    _RACE_WIDTHS[row["part_number"]] = f(row, "race_width")


def snap_ring(row: dict) -> list[Part]:
    od, i, t = f(row, "od"), f(row, "id"), f(row, "thickness")
    s = Script()
    s.revolve("Ring", [(i / 2, -t / 2), (od / 2, -t / 2), (od / 2, t / 2), (i / 2, t / 2)])
    vol = PI * ((od / 2) ** 2 - (i / 2) ** 2) * t
    est = [e.strip() for e in row.get("estimated", "").split(";") if e.strip()] + ["modelled as a closed ring"]
    return [_finish(row, row["part_number"], "snap_ring", "Ring", row["material"], s, vol,
                    {"od": od, "id": i, "thickness": t}, est,
                    title=f"Snap Ring {inch(od)} OD x {inch(t)} thick", folder="Snap Rings")]


def jam_nut(row: dict) -> list[Part]:
    af, w, d = f(row, "hex"), f(row, "width"), f(row, "thread_dia")
    s = Script()
    s.hex_prism("Nut", af, w, z0=-w / 2, hole=d)
    vol = (math.sqrt(3) / 2 * af * af - PI * d * d / 4) * w
    return [_finish(row, row["part_number"], "jam_nut", "Nut", row["material"], s, vol,
                    {"hex": af, "width": w, "thread": row["thread"], "thread_dia": d, "hand": row["hand"]},
                    ["bore is at thread major diameter; thread not modelled"],
                    title=f"Jam Nut {thread_name(row)}", folder="Jam Nuts")]


def bushing(row: dict) -> list[Part]:
    i, od, L, fl, fd = (f(row, k) for k in ("id", "od", "body_length", "flange_length", "flange_dia"))
    s = Script()
    s.revolve("Bushing", [(i / 2, -L), (od / 2, -L), (od / 2, 0), (fd / 2, 0), (fd / 2, fl), (i / 2, fl)])
    vol = PI * ((od / 2) ** 2 * L + (fd / 2) ** 2 * fl - (i / 2) ** 2 * (L + fl))
    return [_finish(row, row["part_number"], "bushing", "Bushing", row["material"], s, vol,
                    {"id": i, "od": od, "body_length": L, "flange_length": fl, "flange_dia": fd},
                    title=f"{row['material'].capitalize()} Bushing {inch(i)} ID x {inch(od)} OD x {inch(L + fl)} long",
                    folder="Bushings")]


def sleeve(row: dict) -> list[Part]:
    od, i, L = f(row, "od"), f(row, "id"), f(row, "length")
    s = Script()
    s.revolve("Sleeve", [(i / 2, -L / 2), (od / 2, -L / 2), (od / 2, L / 2), (i / 2, L / 2)])
    vol = PI * ((od / 2) ** 2 - (i / 2) ** 2) * L
    est = [e.strip() for e in row.get("estimated", "").split(";") if e.strip()]
    return [_finish(row, row["part_number"], f"{row['kind']}_sleeve", "Sleeve", row["material"], s, vol,
                    {"od": od, "id": i, "length": L, "kind": row["kind"]}, est,
                    title=f"{row['kind'].capitalize()} Sleeve {inch(od)} OD x {inch(i)} ID x {inch(L)} long",
                    folder=f"{row['kind'].capitalize()} Sleeves")]
