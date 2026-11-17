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
  weld-in bung          the face the jam nut seats on at x = 0, thread axis along +X (as a rod end shank), body towards +X

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


def _shoulder_ball(bore: float, width: float, ball_dia: float, shoulder_dia: float) -> list:
    """A ball with misalignment shoulders: the sphere runs out into a plain cylinder of
    shoulder_dia that carries on to the full ball width (HIN, HAB, COM8T-101/103)."""
    R, h, rs = ball_dia / 2, width / 2, shoulder_dia / 2
    z0 = math.sqrt(R * R - rs * rs)   # where the sphere meets the shoulder
    return [(bore / 2, -h), (rs, -h), (rs, -z0), ("arc", (rs, z0), (0, 0), False), (rs, h), (bore / 2, h)]


def _grooved_ring(od: float, width: float, ball_dia: float, land: float, gw: float, depth: float) -> list:
    """A race with a V staking groove in each face, `land` in from the OD (WSSX-TV, FKSSX-TV)."""
    R, h = ball_dia / 2, width / 2
    ri = math.sqrt(R * R - h * h)
    ro, r1 = od / 2 - land, od / 2 - land - gw
    rm = (ro + r1) / 2
    return [(ri, -h), (r1, -h), (rm, -h + depth), (ro, -h), (od / 2, -h), (od / 2, h), (ro, h),
            (rm, h - depth), (r1, h), (ri, h), ("arc", (ri, -h), (0, 0), True)]


def _opt(row: dict, key: str) -> float | None:
    return float(row[key]) if row.get(key, "").strip() else None


def spherical_bearing(row: dict) -> list[Part]:
    """A uniball: race and ball. Optional columns: shoulder_dia (a ball with misalignment
    shoulders out to ball_width) and groove_land / groove_width / groove_depth (staking grooves)."""
    pn = row["part_number"]
    B, D, W, T, bd = (f(row, k) for k in ("bore", "od", "ball_width", "race_width", "ball_dia"))
    S, gl, gw, gd = (_opt(row, k) for k in ("shoulder_dia", "groove_land", "groove_width", "groove_depth"))
    dims = {"bore": B, "od": D, "ball_width": W, "race_width": T, "ball_dia": bd,
            "catalog_misalignment_deg": f(row, "catalog_misalignment_deg")}
    est = [e.strip() for e in row.get("estimated", "").split(";") if e.strip()]
    race = Script()
    v_race = PI * (D / 2) ** 2 * T - sphere_slice_volume(bd, T)
    if gl is not None:
        dims.update({"groove_land": gl, "groove_width": gw, "groove_depth": gd})
        race.revolve("Race", _grooved_ring(D, T, bd, gl, gw, gd))
        v_race -= 2 * (gw * gd / 2) * 2 * PI * (D / 2 - gl - gw / 2)   # two V rings, by Pappus
    else:
        race.revolve("Race", _socket_ring(D, T, bd))
    ball = Script()
    if S is not None:
        dims["shoulder_dia"] = S
        z0 = math.sqrt((bd / 2) ** 2 - (S / 2) ** 2)
        ball.revolve("Ball", _shoulder_ball(B, W, bd, S))
        v_ball = sphere_slice_volume(bd, 2 * z0) + PI * (S / 2) ** 2 * (W - 2 * z0) - PI * (B / 2) ** 2 * W
    else:
        ball.revolve("Ball", _ball(B, W, bd))
        v_ball = sphere_slice_volume(bd, W) - PI * (B / 2) ** 2 * W
    # Titles become file names: series and vendor tell lined, unlined, grooved and maker apart.
    metric = "-M" in row["series"]
    size = (lambda v: f"{round(v * 25.4)}mm") if metric else inch
    title = f"Uniball {size(B)} bore x {size(D)} OD, {row['vendor']} {row['series']}"
    if S is not None:
        title += f", {inch(W)} wide shoulder ball"
    return [
        _finish(row, pn, "spherical_bearing", "Race", row["material"], race, v_race, dims, est,
                title=title, folder="Uniballs"),
        _finish(row, f"{pn}.ball", "spherical_bearing_ball", "Ball", row["material"], ball, v_ball, dims, est,
                part_number="", description=f"Ball of {pn} (moves in the race; counted in the BOM with the race)",
                bom_type="reference", title=f"Uniball Ball {size(B)} bore (for {pn})", folder=INTERNAL),
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


# The ball a spacer of each bore is shaped around: (ball diameter, ball width, the FK part it comes from).
# A misalignment spacer's seat is a band of the same sphere as the ball, so as the ball tilts the seat
# slides under the rod end or race face with it, and the angled cone above is what finally touches.
SEAT_BALL = {
    0.5: (0.937, 0.625, "JMX8"), 0.625: (1.125, 0.750, "JMX10"), 0.75: (1.312, 0.875, "JMX12"),
    0.875: (1.312, 0.875, "JMX14"), 1.0: (1.875, 1.375, "WSSX16T / JMX16"), 1.5: (2.750, 1.962, "WSSX24T"),
}

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
        # A seat band on the ball's own sphere, narrowing to a waist, then a straight cone out to the
        # head (Kartek's measuring diagram). The seat starts at the edge of the ball's flat face.
        bd, bw, ref = SEAT_BALL[E]
        # 0.008in under the ball's radius: the band rides just clear of the socket's spherical bore, as
        # a real spacer does, rather than sitting on the same surface (which a collision check counts as touching)
        R, c = bd / 2 - 0.008, -bw / 2             # sphere radius, and its centre below the seat face
        r0 = math.sqrt(R * R - c * c)              # edge of the ball's flat face
        rn = min(max(0.89 * rp, rb + 0.06), 0.85 * r0)
        zn = math.sqrt(R * R - rn * rn) + c        # where the sphere comes in to the waist
        tall = "flat_top" in tags or "stepped" in tags
        hk = min(A, 0.75) if tall else A           # height over which the seat and cone happen
        head = [(r0, 0), ("arc", (rn, zn), (0, c), False), (rh, hk - 0.05)]
        if "stepped" in tags:                      # the top steps down to register in a recess
            rs = max(rb + 0.1, rh - 0.2)
            head += [(rh, A - 0.25), (rs, A - 0.25), (rs, A)]
            dims["step_dia"] = round(2 * rs, 4)
            est.append("step_dia and step height")
        else:
            head.append((rh, A))
        dims.update({"seat_dia": round(2 * r0, 4), "seat_sphere_dia": bd, "waist_dia": round(2 * rn, 4),
                     "seat_matched_to": ref})
        est += [f"seat sphere matched to the FK {ref} ball", "waist_dia", "cone start height"]
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


# Vendors publish a cup's outside diameter, height and the uniball it takes, nothing inside. The lip,
# groove and the land above the groove follow one rule, scaled on the bore (the uniball OD) from the first
# cup's estimate; the sheet says so wherever a row lists them as estimated.
CUP_ESTIMATES = {
    "lip_id": "lip_id: the lip overlaps the uniball race by 5.3% of the bore each side",
    "lip_thickness": "lip_thickness: what is left of the height once the uniball, the groove and a land of "
                     "7.06% of the bore above the groove are taken off (the groove sits near the open end, as "
                     "the product photos show)",
    "groove_dia": "groove_dia: a standard internal retaining ring groove (ANSI B27.7 / Truarc N5000 class) "
                  "for that housing bore",
    "groove_width": "groove_width: the N5000-class groove width for that housing bore",
}


def cup(row: dict) -> list[Part]:
    """A weld-in uniball cup: a bore the uniball presses into, a lip on one side and a snap ring groove on
    the other. Optional columns: bore_undersize (sold under size, honed to the uniball after welding) and,
    for a wobble stopper housing (style wobble_stopper), end_holes / end_hole_dia / end_hole_depth /
    end_hole_bc: tapped holes in each end face for the end plates, modelled as plain tap-drill holes."""
    pn = row["part_number"]
    bo, H, D, lid, lt, gd, gw = (f(row, k) for k in (
        "bearing_od", "height", "od", "lip_id", "lip_thickness", "groove_dia", "groove_width"))
    seat_for, T = _seat_bearing(row)  # seat depth equals the race width
    under = _opt(row, "bore_undersize") or 0.0
    bb = bo - under           # the bore as sold
    zb = -T / 2 - lt          # bottom (lip) face
    zs = -T / 2               # bearing seat
    zg0, zg1 = T / 2, T / 2 + gw
    zt = zb + H
    prof = [(lid / 2, zb), (D / 2, zb), (D / 2, zt), (bb / 2, zt), (bb / 2, zg1), (gd / 2, zg1),
            (gd / 2, zg0), (bb / 2, zg0), (bb / 2, zs), (lid / 2, zs)]
    vol = PI * ((D / 2) ** 2 * H - (lid / 2) ** 2 * lt - (bb / 2) ** 2 * (zt - zs)
                - ((gd / 2) ** 2 - (bb / 2) ** 2) * gw)
    dims = {"bearing_od": bo, "height": H, "od": D, "lip_id": lid, "lip_thickness": lt,
            "groove_dia": gd, "groove_width": gw, "seat_depth": T, "seat_depth_from": seat_for,
            "bottom_z": round(zb, 4), "top_z": round(zt, 4), "snap_ring": row["snap_ring"]}
    if under:
        dims.update({"bore_as_sold": round(bb, 4), "bore_undersize": under})
    s = Script()
    s.revolve("Cup", prof)
    est = [CUP_ESTIMATES.get(e.strip(), e.strip()) for e in row.get("estimated", "").split(";") if e.strip()]
    style = row.get("style") or "weld_in"
    if style == "wobble_stopper":
        n, hd, hdep, bc = int(row["end_holes"]), f(row, "end_hole_dia"), f(row, "end_hole_depth"), f(row, "end_hole_bc")
        for end, z0 in (("lip", zb), ("snap ring", zt - hdep)):
            for k in range(n):
                a = math.radians(45 + k * 360 / n)
                s.cylinder(f"End plate hole {end} {k + 1}", hd, hdep,
                           base=(bc / 2 * math.cos(a), bc / 2 * math.sin(a), z0), operation="cut")
        vol -= 2 * n * PI * (hd / 2) ** 2 * hdep
        dims.update({"end_holes_each_end": n, "end_hole_dia": hd, "end_hole_depth": hdep, "end_hole_bc": bc})
        est.append(f"end plate holes: {n} each end for 10-32 screws (published), drawn as {num(hd)}in tap-drill "
                   f"holes {num(hdep)}in deep on a {num(bc)}in circle at 45 degrees (position, size and depth "
                   "from the photo; the threads are not modelled)")
        title = f"Wobble Stopper Housing {inch(bo)} bore x {inch(D)} OD x {inch(H)} wide, {row['vendor']}"
    else:
        title = f"Uniball Cup {inch(bo)} bore x {inch(D)} OD x {inch(H)} tall, {row['vendor']}"
        if under:
            title += f", {num(under)}in undersize bore"
    dims["style"] = style.replace("_", " ")
    return [_finish(row, pn, "uniball_cup", "Cup", row["material"], s, vol, dims, est, title=title,
                    folder="Uniball Cups")]


_RACE_WIDTHS: dict[str, float] = {}


def _seat_bearing(cup_row: dict) -> tuple[str, float]:
    """The first bearing in the cup's `fits` that is in the data, and its race width."""
    for name in cup_row["fits"].split(";"):
        if name.strip() in _RACE_WIDTHS:
            return name.strip(), _RACE_WIDTHS[name.strip()]
    raise KeyError(f"no bearing in data for cup {cup_row['part_number']}")


def register_bearing(row: dict) -> None:
    _RACE_WIDTHS[row["part_number"]] = f(row, "race_width")


def snap_ring(row: dict) -> list[Part]:
    od, i, t = f(row, "od"), f(row, "id"), f(row, "thickness")
    s = Script()
    s.revolve("Ring", [(i / 2, -t / 2), (od / 2, -t / 2), (od / 2, t / 2), (i / 2, t / 2)])
    vol = PI * ((od / 2) ** 2 - (i / 2) ** 2) * t
    est = [e.strip() for e in row.get("estimated", "").split(";") if e.strip()]
    if est:   # no vendor publishes ring sizes: they follow the groove of the cups they fit
        est.append("sized to sit in the estimated groove of the cups it fits: OD 0.005in under the groove "
                   "diameter, radial section 6.94% of the cup bore, N5000-class thickness")
    est.append("modelled as a closed ring (no gap or lugs)")
    # Two rings with the same size are told apart by type and vendor: FK sells true internal rings with
    # lugs, Kartek mostly an external-type ring for the same groove.
    kind = {"internal": "Internal Snap Ring", "external": "External-Type Snap Ring"}.get(row.get("ring_type", ""),
                                                                                       "Snap Ring")
    dims = {"od": od, "id": i, "thickness": t}
    if row.get("ring_type"):
        dims["ring_type"] = row["ring_type"]
    return [_finish(row, row["part_number"], "snap_ring", "Ring", row["material"], s, vol, dims, est,
                    title=f"{kind} {inch(od)} OD x {inch(t)} thick, {row['vendor']}", folder="Snap Rings")]


def jam_nut(row: dict) -> list[Part]:
    af, w, d = f(row, "hex"), f(row, "width"), f(row, "thread_dia")
    s = Script()
    s.hex_prism("Nut", af, w, z0=-w / 2, hole=d)
    vol = (math.sqrt(3) / 2 * af * af - PI * d * d / 4) * w
    est = [e.strip() for e in row.get("estimated", "").split(";") if e.strip()]
    # Metric threads ('M16x2.0 6H LH') keep their callout; steel nuts keep the plain title, other
    # materials say so, so a steel and an aluminum nut of the same thread get different file names.
    thd = f"{row['thread'].split()[0]} {row['hand']}" if row["thread"].startswith("M") else thread_name(row)
    mat = "" if row["material"] == "steel" else f"{row['material'].capitalize()} "
    return [_finish(row, row["part_number"], "jam_nut", "Nut", row["material"], s, vol,
                    {"hex": af, "width": w, "thread": row["thread"], "thread_dia": d, "hand": row["hand"]},
                    ["bore is at thread major diameter; thread not modelled"] + est,
                    title=f"{mat}Jam Nut {thd}", folder="Jam Nuts")]


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


def safety_washer(row: dict) -> list[Part]:
    od, i, t = f(row, "od"), f(row, "id"), f(row, "thickness")
    s = Script()
    s.revolve("Washer", [(i / 2, -t / 2), (od / 2, -t / 2), (od / 2, t / 2), (i / 2, t / 2)])
    vol = PI * ((od / 2) ** 2 - (i / 2) ** 2) * t
    est = [e.strip() for e in row.get("estimated", "").split(";") if e.strip()]
    p = _finish(row, row["part_number"].replace("/", "-"), "safety_washer", "Washer", row["material"], s, vol,
                {"od": od, "id": i, "thickness": t}, est,
                title=f"Safety Washer {inch(i)} ID x {inch(od)} OD x {inch(t)} thick", folder="Safety Washers")
    p.name = p.name.replace("/", "-")   # Kartek numbers such as KTK1/2SW cannot go in a file name
    return [p]


# ---- weld-in bungs --------------------------------------------------------------------------------------
# Threaded inserts welded into a tube end so a male rod end screws in. Kartek publishes the thread, the total
# length, the diameter that goes into the tube (or the square size) and the tube it fits, plus head and
# shoulder lengths for the stepped ones. Proportions it does not publish are listed in `estimated`.

BUNG_LABELS = {"standard_round": "Weld-In Bung", "heavy_duty_round": "Heavy Duty Weld-In Bung",
               "step": "Step Weld-In Bung", "square_tapered": "Square Tapered Bung"}
BUNG_EDGE = 0.03   # the small chamfer on outside edges seen in the product photos


def _revolve_about_x(s: Script, name: str, profile: list, operation: str = "new") -> None:
    """Script.revolve with the profile's r along world Y and z along world X, so it turns about X."""
    s.revolve(name, profile, operation)
    sketch = next(c for c in reversed(s.commands) if c["command"] == "sketch.create")
    sketch["params"]["plane"] = {"origin": [0, 0, 0], "x_dir": [0, 1, 0], "y_dir": [1, 0, 0]}
    if operation != "new":   # a cut changes the existing body; it must not name a new one
        s.commands[-1]["params"].pop("body_name")


def _revolved_volume(profile: list) -> float:
    """Pappus: the volume of a closed polygon of (r, z) points turned a full circle."""
    s = sum((r0 + r1) * (r0 * z1 - r1 * z0)
            for (r0, z0), (r1, z1) in zip(profile, profile[1:] + profile[:1]))
    return abs(PI * s / 3)


def _square_disc_area(a: float, r: float) -> float:
    """Area where a square of side a and a disc of radius r on the same centre overlap."""
    h = a / 2
    if r <= h:
        return PI * r * r
    if r >= h * math.sqrt(2):
        return a * a
    return PI * r * r - 4 * (r * r * math.acos(h / r) - h * math.sqrt(r * r - h * h))


def bung(row: dict) -> list[Part]:
    style, pn, hand = row["style"], row["part_number"], row["hand"]
    td, tpi, L = f(row, "thread_dia"), int(row["tpi"]), f(row, "length")
    dm = td - 1.082532 / tpi                                 # basic minor diameter of a Unified internal thread
    through = row["threaded_through"] != "no"
    T = L if through else round(0.75 * L * 16) / 16         # thread depth from the jam nut face
    c = BUNG_EDGE
    thread = f"{num(td)}-{tpi} {hand}"
    dims = {"style": style.replace("_", " "), "thread": row["thread"], "thread_dia": td, "tpi": tpi,
            "hand": hand, "length": L, "thread_depth": T, "bore_dia": td}
    if T < L:
        dims["through_bore_dia"] = round(dm, 4)
    est = [f"thread depth {num(T)}in: Kartek says only that it is not threaded all the way through; "
           "taken as 3/4 of the length" if T < L else
           "threaded all the way through: Kartek's page has no note either way",
           "bore at thread major diameter, as the jam nuts; past the thread depth at the basic minor "
           "diameter (tap drill assumed); the thread is cosmetic only"]
    # the bore as (r, z) points from the far end back to the jam nut face
    bore = ([(dm / 2, L), (dm / 2, T), (td / 2, T)] if T < L else [(td / 2, L)]) + [(td / 2, 0)]
    s = Script()
    if style == "square_tapered":
        a = f(row, "square")
        rt = max(0.35 * a, td / 2 + 0.125)                   # turned end face, then a 45 degree taper
        rc = a / 2 * math.sqrt(2)                            # where the taper reaches the square's corners
        s.cmd("solid.box", length=mm(L), width=mm(a), height=mm(a), corner=[0, mm(-a / 2), mm(-a / 2)],
              operation="new", name="Bar", body_name="Bung")
        _revolve_about_x(s, "Taper", [(rt, 0), (rc + 0.05, 0), (rc + 0.05, rc + 0.05 - rt)], "cut")
        e = 0.05                                             # the bore cutter runs past both ends
        _revolve_about_x(s, "Bore", [(0, L + e)] + [(r, L + e if z == L else -e if z == 0 else z)
                                                    for r, z in bore] + [(0, -e)], "cut")
        n, xc = 4000, rc - rt
        step = xc / n
        outer = sum((1 if i in (0, n) else 4 if i % 2 else 2) * _square_disc_area(a, rt + i * step)
                    for i in range(n + 1)) * step / 3 + a * a * (L - xc)
        vol = outer - PI / 4 * (td * td * T + dm * dm * (L - T))
        dims.update({"square": a, "top_dia": round(2 * rt, 4), "fits_tube": "not stated by Kartek",
                     "insertion_length": 0.0})
        est += [f"turned end {num(round(2 * rt, 4))}in across with a 45 degree taper out to the corners "
                "(from the product photo)",
                "Kartek does not say what it fits: taken as welded on to a square tube or plate end, "
                "so nothing goes inside a tube (insertion_length 0)"]
        title = f"{BUNG_LABELS[style]} {thread}, {inch(a)} square x {inch(L)} long"
    else:
        to, wall, od = f(row, "tube_od"), f(row, "tube_wall"), f(row, "od")
        B = od / 2
        if style == "step":
            H, h = to / 2, f(row, "head_length")
            outside = [(H - c, 0), (H, c), (H, h - (H - B)), (B, h), (B, L - c), (B - c, L)]
            insertion = f(row, "shoulder_length")
            dims.update({"base_dia": od, "head_dia": to, "head_length": h, "shoulder_length": insertion})
            est += ["head diameter taken as the tube OD (Kartek gives only the base diameter)",
                    "45 degree weld chamfer from the head down to the base diameter, inside the head length"]
        else:
            outside = [(B - c, 0), (B, c), (B, L - c), (B - c, L)]
            insertion = L
            dims["od"] = od
            est.append("insertion length: shoulderless, so all of it, taken as flush with the tube end")
        est.append(f"{num(c)}in chamfers on the outside edges")
        profile = outside + bore
        _revolve_about_x(s, "Bung", profile)
        vol = _revolved_volume(profile)
        dims.update({"tube_od": to, "tube_wall": wall, "tube_id": round(to - 2 * wall, 4),
                     "insertion_length": insertion})
        title = f"{BUNG_LABELS[style]} {thread} for {inch(to)} x {inch(wall)} wall tube"
    s.cmd("solid.thread", face=[mm(T / 2), mm(td / 2), 0], **{"from": [0, mm(td / 2), 0]},
          designation=f"M{num(td * 25.4)}x{num(25.4 / tpi)}", hand="left" if hand == "LH" else "right",
          length=mm(T), name=f"Thread {row['thread']}")
    dims["thread_feature"] = f"cosmetic, M{num(td * 25.4)}x{num(25.4 / tpi)} (the Unified size in millimetres)"
    return [_finish(row, pn, "bung", "Bung", row["material"], s, vol, dims, est, title=title,
                    folder="Weld-In Bungs")]
