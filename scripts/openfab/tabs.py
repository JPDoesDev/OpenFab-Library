"""Weld-on tabs: flat plates cut to an outline, some folded, some carrying a nut.

Origin convention: the tab stands up from its weld edge. The weld edge (or the
apex of a tube notch, for radius tabs: see each part's dims) runs along world X
at z = 0, the tab rises along +Z, and the plate is centred on y = 0 with its
thickness along Y. The front face (+Y) is the face a panel or bracket bolts
against; nuts, dimples, broke edges and bent flanges are on the back (-Y), the
side that goes against the chassis.

Outlines are loops of ("L", (x, z)) straight segments and ("A", (x, z), (cx, cz),
clockwise) arcs, in inches, starting from the loop's first point.
"""
from __future__ import annotations

import math

from .parts import PI, Part, _finish, inch, num
from .sc import Script, mm

FOLDER = "Tabs"
NUT_EDGE = 0.04   # how far an anchor nut's hub stands out past its barrel


# ---- outline geometry ----------------------------------------------------------

def _arc_points(a, b, c, cw, n=720):
    r = math.dist(a, c)
    t0 = math.atan2(a[1] - c[1], a[0] - c[0])
    t1 = math.atan2(b[1] - c[1], b[0] - c[0])
    sweep = t1 - t0
    if cw:
        while sweep >= 0:
            sweep -= 2 * PI
    else:
        while sweep <= 0:
            sweep += 2 * PI
    return [(c[0] + r * math.cos(t0 + sweep * i / n), c[1] + r * math.sin(t0 + sweep * i / n))
            for i in range(1, n + 1)]


def polygon(loop: list) -> list:
    """The loop as a dense polygon, for areas."""
    start = loop[0][1]
    pts, cur = [start], start
    for item in loop[1:] + [("L", start)]:
        if item[0] == "A":
            pts += _arc_points(cur, item[1], item[2], item[3])
        else:
            pts.append(item[1])
        cur = item[1]
    return pts


def area(pts: list) -> float:
    return abs(sum(x0 * z1 - x1 * z0 for (x0, z0), (x1, z1) in zip(pts, pts[1:] + pts[:1]))) / 2


def _plane(origin=(0, 0, 0), x_dir=(1, 0, 0), y_dir=(0, 0, 1)) -> dict:
    return {"origin": [mm(v) for v in origin], "x_dir": list(x_dir), "y_dir": list(y_dir)}


def draw(s: Script, loop: list, holes=(), circles=()) -> None:
    """Sketch commands for a loop (and hole loops, and round holes as (x, z, dia))."""
    for lp in [loop, *holes]:
        start, cur = lp[0][1], lp[0][1]
        for item in lp[1:] + [("L", start)]:
            end = item[1]
            if math.dist(cur, end) < 1e-9:
                continue
            if item[0] == "A":
                s.cmd("sketch.arc.center_point", center=[mm(item[2][0]), mm(item[2][1])],
                      start=[mm(cur[0]), mm(cur[1])], end=[mm(end[0]), mm(end[1])], clockwise=bool(item[3]))
            else:
                s.cmd("sketch.line", points=[[mm(cur[0]), mm(cur[1])], [mm(end[0]), mm(end[1])]], infer=False)
            cur = end
    for x, z, d in circles:
        s.cmd("sketch.circle.center", center=[mm(x), mm(z)], radius=mm(d / 2))


def plate(s: Script, loop: list, t: float, holes=(), circles=()) -> float:
    """Extrude the outline t thick about y = 0; returns its volume in cubic inches. The body is
    "Tab", or "Plate" when pieces will be added later (s.extras), so that the finished body,
    which those pieces start, can be "Tab" without renaming anything."""
    s.cmd("sketch.create", name="Outline", plane=_plane())
    draw(s, loop, holes, circles)
    s.cmd("sketch.finish")
    # the sketch normal is -Y, so a symmetric extrude puts the plate on y = -t/2 .. t/2
    s.cmd("solid.extrude", distance=mm(t), direction="symmetric", operation="new", name="Plate",
          body_name="Plate" if getattr(s, "extras", False) else "Tab")
    a = area(polygon(loop)) - sum(area(polygon(h)) for h in holes) - sum(PI * d * d / 4 for _, _, d in circles)
    return a * t


def tangent_point(p, centre, r, right=True):
    """Where a line from p touches the circle (centre, r), on the right or left side."""
    vx, vz = p[0] - centre[0], p[1] - centre[1]
    m2 = vx * vx + vz * vz
    k = r * math.sqrt(max(m2 - r * r, 0)) / m2
    a = (centre[0] + r * r / m2 * vx - k * vz, centre[1] + r * r / m2 * vz + k * vx)
    b = (centre[0] + r * r / m2 * vx + k * vz, centre[1] + r * r / m2 * vz - k * vx)
    return max(a, b) if right else min(a, b)


def base_edge(w: float, tube: float | None, depth: float | None) -> tuple[list, float]:
    """The weld edge from left to right, with a tube notch if any: (loop items after the
    start point, height of the notch apex). The loop starts at (-w/2, 0)."""
    if not tube:
        return [("L", (w / 2, 0))], 0.0
    r = tube / 2
    if depth is None:                       # the notch spans the whole base
        c = w / 2
        depth = r - math.sqrt(r * r - c * c)
    else:
        c = math.sqrt(r * r - (r - depth) ** 2)
    centre = (0, depth - r)
    items = []
    if c < w / 2 - 1e-9:
        items.append(("L", (-c, 0)))
    items.append(("A", (c, 0), centre, True))
    if c < w / 2 - 1e-9:
        items.append(("L", (w / 2, 0)))
    return items, depth


def round_top(w: float, centre_z: float, r: float, tube=None, depth=None, slot=0.0, hole=0.0) -> list:
    """A base w wide rising on straight sides to a round top of radius r about the hole.
    With `slot`, a slot that wide runs from the hole out through the top, and the hole
    becomes part of the outline (its diameter is `hole`)."""
    base, _ = base_edge(w, tube, depth)
    o = (0, centre_z)
    tr = tangent_point((w / 2, 0), o, r, True)
    tl = (-tr[0], tr[1])
    loop = [("L", (-w / 2, 0)), *base, ("L", tr)]
    if slot:
        h = slot / 2
        top = (h, centre_z + math.sqrt(r * r - h * h))
        inner = (h, centre_z + math.sqrt((hole / 2) ** 2 - h * h))
        loop += [("A", top, o, False), ("L", inner), ("A", (-h, inner[1]), o, True),
                 ("L", (-h, top[1])), ("A", tl, o, False)]
    else:
        loop.append(("A", tl, o, False))
    return loop


def rect(w: float, z0: float, z1: float, chamfer=0.0, radius=0.0, notch=(0.0, 0.0)) -> list:
    """A rectangle from z0 to z1, its top corners chamfered or rounded, with an optional
    notch (width, depth) in the middle of the top edge."""
    h = w / 2
    k = chamfer or radius
    loop = [("L", (-h, z0)), ("L", (h, z0)), ("L", (h, z1 - k))]
    loop.append(("A", (h - k, z1), (h - k, z1 - k), False) if radius else ("L", (h - k, z1)))
    nw, nd = notch
    if nw:
        loop += [("L", (nw / 2, z1)), ("L", (nw / 2, z1 - nd)), ("L", (-nw / 2, z1 - nd)), ("L", (-nw / 2, z1))]
    loop.append(("L", (-h + k, z1)))
    loop.append(("A", (-h, z1 - k), (-h + k, z1 - k), False) if radius else ("L", (-h, z1 - k)))
    return loop


# ---- features on the back face -------------------------------------------------

def sheet(s: Script, t: float, face_point) -> None:
    """Turn the plate into sheet metal so it can be folded. A k-factor of 0.5 keeps the
    folded volume equal to the flat plate's, so the analytic volume still holds."""
    s.cmd("sheet.manage_rules", name="Tab", thickness=f"{num(mm(t))} mm", k_factor="0.5",
          bend_radius=f"{num(mm(t))} mm")
    s.cmd("sheet.convert", body="Plate" if getattr(s, "extras", False) else "Tab",
          face=[mm(v) for v in face_point])


def fold(s: Script, a, b, angle: float, t: float) -> None:
    """Fold along the line a-b (x, z points on the front face), the far side going back (-Y)."""
    s.cmd("sheet.fold", points=[[mm(a[0]), mm(t / 2), mm(a[1])], [mm(b[0]), mm(t / 2), mm(b[1])]],
          angle=f"{num(angle)} deg")


def _convex_span(poly: list, z: float):
    """Where the row at height z crosses a convex polygon: (x0, x1) or None."""
    xs = []
    for (x0, z0), (x1, z1) in zip(poly, poly[1:] + poly[:1]):
        if (z0 - z) * (z1 - z) <= 0 and z0 != z1:
            xs.append(x0 + (z - z0) * (x1 - x0) / (z1 - z0))
    return (min(xs), max(xs)) if len(xs) >= 2 else None


def _slot_area_union(hub_r: float, lugs: list, lug_r: float, rows: int = 6000) -> float:
    """Area of a hub circle (radius hub_r about the origin) joined to a round-ended arm of
    half-width lug_r out to each lug centre (x, z), by exact spans on fine rows."""
    circles = [((0.0, 0.0), hub_r), ((0.0, 0.0), lug_r)] + [(lug, lug_r) for lug in lugs]
    rects = []
    for lx, lz in lugs:
        L = math.hypot(lx, lz)
        nx, nz = -lz / L * lug_r, lx / L * lug_r
        rects.append([(nx, nz), (lx + nx, lz + nz), (lx - nx, lz - nz), (-nx, -nz)])
    lo = min([-hub_r, -lug_r] + [z - lug_r for _, z in lugs])
    hi = max([hub_r, lug_r] + [z + lug_r for _, z in lugs])
    dz = (hi - lo) / rows
    total = 0.0
    for i in range(rows):
        z = lo + (i + 0.5) * dz
        spans = []
        for (cx, cz), r in circles:
            if abs(z - cz) < r:
                w = math.sqrt(r * r - (z - cz) ** 2)
                spans.append((cx - w, cx + w))
        for poly in rects:
            sp = _convex_span(poly, z)
            if sp:
                spans.append(sp)
        spans.sort()
        cur = None
        for a, b in spans:
            if cur is None or a > cur[1]:
                if cur:
                    total += cur[1] - cur[0]
                cur = [a, b]
            else:
                cur[1] = max(cur[1], b)
        if cur:
            total += cur[1] - cur[0]
    return total * dz


def _op(s: Script) -> dict:
    """Pieces added after the plate go into their own body, "Tab", which the plate is then
    combined into. A folded tab is sheet metal, and SolidCraft warns when a plain solid
    feature changes a sheet body, so the plate is only ever a tool, never a target."""
    if not getattr(s, "extra", False):
        s.extra = True
        return {"operation": "new", "body_name": "Tab"}
    return {"operation": "join", "targets": ["Tab"]}


def _merge(s: Script) -> None:
    s.cmd("solid.combine", target="Tab", tools=["Plate"], operation="join")
    s.extra = False


def _cyl(s: Script, name: str, dia: float, height: float, base, axis=(0, -1, 0)) -> None:
    s.cmd("solid.cylinder", diameter=mm(dia), height=mm(height), base=[mm(c) for c in base], axis=list(axis),
          name=name, **_op(s))


def _arm(s: Script, name: str, centre, lug, lug_r: float, y0: float, height: float) -> None:
    """A round-ended arm from the hub centre to a lug, height thick from y0 back."""
    (cx, cz), (lx, lz) = centre, lug
    L = math.hypot(lx, lz)
    nx, nz = -lz / L * lug_r, lx / L * lug_r
    p = [(cx + nx, cz + nz), (cx + lx + nx, cz + lz + nz), (cx + lx - nx, cz + lz - nz), (cx - nx, cz - nz)]
    loop = [("L", p[0]), ("L", p[1]), ("A", p[2], (cx + lx, cz + lz), True), ("L", p[3]),
            ("A", p[0], (cx, cz), True)]
    # a plane on the back face whose normal points back (-Y): x along X, y along Z gives -Y
    s.cmd("sketch.create", name=f"{name} outline", plane=_plane((0, y0, 0)))
    draw(s, loop)
    s.cmd("sketch.finish")
    s.cmd("solid.extrude", distance=mm(height), name=name, **_op(s))


def nut(s: Script, kind: str, centre_z: float, t: float, d: float, tpi: int, lugs_deg: list,
        cc: float, lug_r: float, est: list, dims: dict) -> float:
    """A nut on the back of the tab at (0, centre_z), joined to it. Returns the volume added.

    fixed:   an anchor nut, a round barrel on a flange with riveted lugs
    floater: a square nut in a riveted cage, modelled as its envelope: a flat cage with
             round ends and a square barrel
    nutsert: a flanged insert pressed through the tab, modelled as a round boss
    """
    y0 = -t / 2
    tf = 0.05                                   # flange / cage thickness
    hb = round(d + 0.03, 3)                     # barrel height from the back face
    db = round(d + 0.19, 3)                     # barrel across
    vol = 0.0
    lugs = [(cc / 2 * math.cos(math.radians(a)), cc / 2 * math.sin(math.radians(a))) for a in lugs_deg]
    if kind == "nutsert":
        db, hb = round(d + 0.25, 3), 0.2
        _cyl(s, "Nutsert", db, hb, (0, y0, centre_z))
        vol += PI * db * db / 4 * hb
        est.append(f"nutsert modelled as a {num(db)}in boss {num(hb)}in proud of the back face "
                   "(Kartek gives only the thread)")
    elif kind == "fixed":
        hub = db / 2 + NUT_EDGE
        _cyl(s, "Nut hub", 2 * hub, tf, (0, y0, centre_z))
        for i, lug in enumerate(lugs, 1):
            _arm(s, f"Nut lug {i}", (0, centre_z), lug, lug_r, y0, tf)
        _cyl(s, "Nut barrel", db, hb, (0, y0, centre_z))
        flange = _slot_area_union(hub, lugs, lug_r)
        vol += flange * tf + PI * db * db / 4 * (hb - tf)
        est.append(f"anchor nut: {num(db)}in barrel {num(hb)}in proud of the back face on a {num(tf)}in "
                   f"flange with lugs {num(2 * lug_r)}in wide, from the product photos; Kartek gives the "
                   f"thread and the {num(cc)}in rivet centres")
    elif kind == "floater":
        side = db
        _arm(s, "Nut cage", (lugs[1][0], centre_z + lugs[1][1]), (lugs[0][0] - lugs[1][0], lugs[0][1] - lugs[1][1]),
             lug_r, y0, tf)
        ang = lugs_deg[0]
        s.cmd("sketch.create", name="Nut outline", plane=_plane((0, y0, 0)))
        c, sn, h = math.cos(math.radians(ang)), math.sin(math.radians(ang)), side / 2
        corners = [(-h, -h), (h, -h), (h, h), (-h, h)]
        pts = [(x * c - z * sn, centre_z + x * sn + z * c) for x, z in corners]
        draw(s, [("L", p) for p in pts])
        s.cmd("sketch.finish")
        s.cmd("solid.extrude", distance=mm(hb), name="Nut", **_op(s))
        L = math.dist(lugs[0], lugs[1])
        cage = L * 2 * lug_r + PI * lug_r * lug_r
        vol += cage * tf + side * side * hb - side * min(side, 2 * lug_r) * tf   # the nut overlaps the cage
        est.append(f"floater nut modelled as its envelope: a cage with {num(2 * lug_r)}in wide rivet ends, {num(tf)}in thick "
                   f"on {num(cc)}in rivet centres and a {num(side)}in square nut {num(hb)}in proud of the back face")
    _merge(s)
    # the threaded bore through the nut and the plate, at the thread's major diameter (as the jam nuts)
    e = 0.02
    s.cmd("solid.cylinder", diameter=mm(d), height=mm(t + hb + 2 * e), base=[0, mm(t / 2 + e), mm(centre_z)],
          axis=[0, -1, 0], operation="cut", targets=["Tab"], name="Thread bore")
    vol -= PI * d * d / 4 * hb
    s.cmd("solid.thread", face=[mm(d / 2), mm(y0 - hb / 2), mm(centre_z)],
          **{"from": [mm(d / 2), mm(y0 - hb), mm(centre_z)]},
          designation=f"M{num(d * 25.4)}x{num(25.4 / tpi)}", hand="right", length=mm(hb), name="Thread")
    est.append("bore at the thread's major diameter; the thread is cosmetic only")
    dims.update({"nut": kind, "nut_height": hb})
    return vol


def dimple(s: Script, x: float, z: float, t: float, hole: float, outer: float, depth: float) -> float:
    """A countersink dimple pressed back (-Y) around a hole: the plate between the hole and
    `outer` is replaced by a conical band of the same thickness. The plate is cut out to
    `outer` already; returns the band's volume (the same as the flat ring it replaces)."""
    rh, ro = hole / 2, outer / 2
    s.cmd("sketch.create", name="Dimple profile", plane=_plane((x, 0, z), (1, 0, 0), (0, 1, 0)))
    prof = [(ro, t / 2), (ro, -t / 2), (rh, -t / 2 - depth), (rh, t / 2 - depth)]
    for a, b in zip(prof, prof[1:] + prof[:1]):
        s.cmd("sketch.line", points=[[mm(a[0]), mm(a[1])], [mm(b[0]), mm(b[1])]], infer=False)
    s.cmd("sketch.finish")
    s.cmd("solid.revolve", axis="y", name="Dimple", **_op(s))
    _merge(s)
    return PI * t * ((outer / 2) ** 2 - (hole / 2) ** 2)


# ---- styles -----------------------------------------------------------------------

def _f(row, k, default=None):
    v = row.get(k, "").strip()
    return float(v) if v else default


QUARTER_TURN = {  # button size -> (main hole, dimple outer dia, rivet c-c of the matching S-spring)
    "5": (0.40, 0.75, 1.0),
    "6": (0.50, 0.90, 1.375),
}
RIVET_HOLE = 0.129    # a #30 drill for the S-spring's 1/8in rivets
DIMPLE_DEPTH = 0.09


def tab(row: dict) -> list[Part]:
    style, pn = row["style"], row["part_number"]
    t = _f(row, "thickness")
    est = [e.strip() for e in row.get("estimated", "").split(";") if e.strip()]
    dims: dict = {"style": style.replace("_", " "), "thickness": t}
    if row.get("thickness_assumed") == "yes":
        est.insert(0, f"thickness {num(t)}in: not published by Kartek; "
                      + ("taken as 0.090in sheet to suit the spring and button stack-up"
                         if style.startswith("quarter_turn") else "taken as 3/16in"))
    s = Script()
    s.extras = bool(row.get("nut")) or row.get("dimpled") == "yes"
    W, L, C = _f(row, "width"), _f(row, "length"), _f(row, "center")
    hole = _f(row, "hole")
    tube, depth = _f(row, "tube_od"), _f(row, "notch_depth")
    thread_dia = _f(row, "thread_dia")
    vol = 0.0

    if style in ("round_top", "nut_round_top"):
        _, apex = base_edge(W, tube, depth)
        cz = apex + C
        r = L - C
        slot = _f(row, "slot", 0.0)
        hd = hole if hole else round(thread_dia + 1 / 32, 4)
        loop = round_top(W, cz, r, tube, depth, slot, hd)
        vol = plate(s, loop, t, circles=[] if slot else [(0, cz, hd)])
        dims.update({"width": W, "center": C, "length": L, "top_radius": round(r, 4), "hole": hd})
        if tube:
            dims.update({"tube_od": tube, "notch_depth": round(apex, 4),
                         "measured_from": "the top of the tube notch"})
        if slot:
            dims["slot"] = slot
        centre = cz
    elif style in ("rect", "nut_rect", "quarter_turn"):
        z0 = -_f(row, "flange", 0.0)
        loop = rect(W, z0, L, _f(row, "chamfer", 0.0), _f(row, "corner_radius", 0.0),
                    (_f(row, "notch_width", 0.0), _f(row, "notch_depth", 0.0)))
        centre = C
        circles = []
        hd = hole if hole else (round(thread_dia + 1 / 32, 4) if thread_dia else None)
        if hd:
            circles.append((0, C, hd))
        dims.update({"width": W, "length": L, "center": C})
        if hd:
            dims["hole"] = hd
        for k in ("chamfer", "corner_radius", "notch_width", "notch_depth"):
            if _f(row, k):
                dims[k] = _f(row, k)
        if style == "quarter_turn":
            hole_d, outer, cc = QUARTER_TURN[row["button"]]
            hole_d = hole or hole_d
            cut = _f(row, "dimple_dia", outer) if row.get("dimpled") == "yes" else hole_d
            circles = [(0, C, cut), (-cc / 2, C, RIVET_HOLE), (cc / 2, C, RIVET_HOLE)]
            dims.update({"hole": hole_d, "button": f"#{row['button']}", "rivet_holes": RIVET_HOLE,
                         "rivet_centres": cc})
        vol = plate(s, loop, t, circles=circles)
    elif style == "quarter_turn_light":
        # the light-duty "bat" tab: a round lobe round the button hole, a small lobe at
        # each rivet, two lightening holes and a notched flange folded back at the bottom
        hole_d, outer, cc = QUARTER_TURN[row["button"]]
        fl, rn, rl = 0.3, 0.18, 0.19
        rm = L - C
        zl = C + 0.05
        X = cc / 2 + rl
        lobe = (cc / 2, zl)
        a120 = (lobe[0] + rl * math.cos(math.radians(120)), zl + rl * math.sin(math.radians(120)))
        m25 = (rm * math.cos(math.radians(25)), C + rm * math.sin(math.radians(25)))
        loop = [("L", (-X, -fl)), ("L", (-rn, -fl)), ("A", (rn, -fl), (0, -fl), True), ("L", (X, -fl)),
                ("L", (X, zl)), ("A", a120, lobe, False), ("L", m25),
                ("A", (-m25[0], m25[1]), (0, C), False), ("L", (-a120[0], a120[1])),
                ("A", (-X, zl), (-lobe[0], zl), False)]
        tri = [(0.15, 0.16), (cc / 2 - 0.04, 0.16), (cc / 2 * 0.73, C * 0.5)]
        holes = [[("L", p) for p in tri], [("L", (-x, z)) for x, z in reversed(tri)]]
        circles = [(0, C, outer if row.get("dimpled") == "yes" else hole_d),
                   (-cc / 2, zl, RIVET_HOLE), (cc / 2, zl, RIVET_HOLE)]
        vol = plate(s, loop, t, holes, circles)
        dims.update({"length": L, "center": C, "width": round(2 * X, 4), "hole": hole_d,
                     "button": f"#{row['button']}", "rivet_holes": RIVET_HOLE, "rivet_centres": cc,
                     "flange": fl})
        est += [f"outline (lobes, lightening holes, {num(2 * rn)}in flange notch) and width from the product photos",
                f"rivet holes on the {num(cc)}in centres of the matching S-spring"]
        centre = C
    elif style == "broke_nut":
        # a flat centre the published width across, with a wing each side folded back to
        # straddle a tube
        a, m = 0.3, 0.06       # m keeps the outline's corners out of the bend zone
        z1, z2 = 0.3 * L, 0.7 * L
        h = W / 2
        loop = [("L", (-h - m, 0)), ("L", (h + m, 0)), ("L", (h + a, z1)), ("L", (h + a, z2)), ("L", (h + m, L)),
                ("L", (-h - m, L)), ("L", (-h - a, z2)), ("L", (-h - a, z1))]
        hd = round(thread_dia + 1 / 32, 4) if row["nut"] != "nutsert" else thread_dia
        vol = plate(s, loop, t, circles=[(0, C, hd)])
        sheet(s, t, (0, t / 2, 0.08))
        ang = _f(row, "fold_angle", 30)
        fold(s, (h, 0), (h, L), ang, t)
        fold(s, (-h, 0), (-h, L), ang, t)
        dims.update({"width": W, "length": L, "center": C, "hole": hd, "wing": a, "fold_angle": ang})
        est += [f"wings {num(a)}in each side, folded back {num(ang)} degrees on a {num(t)}in inside radius, "
                "from the product photos (Kartek's width is the flat centre)"]
        centre = C
    elif style == "arch":
        op, band, top_w, open_bot, open_top, end_h = (_f(row, k) for k in (
            "opening", "band", "top_width", "opening_bottom", "opening_top", "end_height"))
        H = op + band
        hw = W / 2
        loop = [("L", (-hw, 0)), ("L", (-open_bot / 2, 0)), ("L", (-open_top / 2, op)), ("L", (open_top / 2, op)),
                ("L", (open_bot / 2, 0)), ("L", (hw, 0)), ("L", (hw, end_h)), ("L", (top_w / 2, H)),
                ("L", (-top_w / 2, H)), ("L", (-hw, end_h))]
        vol = plate(s, loop, t)
        dims.update({"length_along_base": W, "opening_height": op, "height": H, "opening_bottom": open_bot,
                     "opening_top": open_top, "top_width": top_w})
        est.append(f"height {num(H)}in, top {num(top_w)}in, opening {num(open_bot)}in at the base narrowing to "
                   f"{num(open_top)}in, ends {num(end_h)}in high: scaled from Kartek's dimensioned photo")
        centre = None
    elif style == "channel":
        # a round-topped web with a tube notch across its whole width, and a tapered flange
        # bent back along each side (modelled with sharp corners)
        _, apex = base_edge(W, tube, None)
        r = W / 2
        cz = apex + L - r
        loop = [("L", (-W / 2, 0)), *base_edge(W, tube, None)[0], ("L", (W / 2, cz)), ("A", (-W / 2, cz), (0, cz), False)]
        vol = plate(s, loop, t)
        d, zt = _f(row, "flange_depth"), _f(row, "flange_height")
        tri = [(-t / 2, 0), (-t / 2 - d, 0), (-t / 2, zt)]
        for side, x0 in (("Right", W / 2 - t), ("Left", -W / 2)):
            s.cmd("sketch.create", name=f"{side} flange outline", plane=_plane((x0, 0, 0), (0, 1, 0), (0, 0, 1)))
            draw(s, [("L", p) for p in tri])
            s.cmd("sketch.finish")
            s.cmd("solid.extrude", distance=mm(t), operation="join", name=f"{side} flange")
        vol += 2 * area(tri) * t
        dims.update({"width_outside": W, "tube_od": tube, "notch_depth": round(apex, 4),
                     "length_from_notch_top": L, "flange_depth": d, "flange_height": zt,
                     "measured_from": "the bottom corners of the web"})
        est.append(f"side flanges {num(d)}in deep at the base tapering to nothing {num(zt)}in up, from the "
                   "product photo; bends modelled as sharp corners")
        centre = None
    else:
        raise ValueError(f"tabs.csv: unknown style {style!r} for {pn}")

    # folds that the plate styles carry (broke-edge quarter-turn tabs)
    if style in ("quarter_turn", "quarter_turn_light") and row.get("edge") == "broke":
        fl = _f(row, "flange", 0.3)
        sheet(s, t, (0, t / 2, 0.5 * C))
        half = dims["width"] / 2
        fold(s, (-half, 0), (half, 0), 90, t)
        dims["flange"] = fl
        dims["edge"] = "broke: a flange folded back 90 degrees at the bottom"
        if style == "quarter_turn":
            est.append(f"flange {num(fl)}in (flat) folded back 90 degrees on a {num(t)}in inside radius; "
                       "Kartek's overall height is taken from the fold line")
    elif style.startswith("quarter_turn"):
        dims["edge"] = "flat"
    if style.startswith("quarter_turn"):
        if row.get("dimpled") == "yes":
            hole_d, outer, cc = QUARTER_TURN[row["button"]]
            outer = _f(row, "dimple_dia", outer)
            hole_d = dims["hole"]
            vol += dimple(s, 0, C, t, hole_d, outer, DIMPLE_DEPTH)
            dims.update({"dimple_dia": outer, "dimple_depth": DIMPLE_DEPTH})
            est.append(f"dimple {num(outer)}in across, pressed {num(DIMPLE_DEPTH)}in back; rivet holes left plain")
        if style == "quarter_turn" and "width" not in row.get("published", ""):
            est.append(f"width {num(W)}in, hole {num(dims['hole'])}in and corner shape from the product photos")
            est.append(f"rivet holes on the {num(dims['rivet_centres'])}in centres of the matching S-spring")

    if row.get("nut"):
        vol += nut(s, row["nut"], centre, t, thread_dia, int(row["tpi"]),
                   [float(a) for a in row["lug_angles"].split()] if row.get("lug_angles") else [0, 180],
                   _f(row, "lug_cc", 1.0), _f(row, "lug_r", 0.15), est, dims)
        dims["thread"] = row["thread"]
    for k in ("sold_as",):
        if row.get(k):
            dims[k] = row[k]
    return [_finish(row, pn, "tab", "Tab", row["material"], s, vol, dims, est, title=row["title"], folder=FOLDER)]
