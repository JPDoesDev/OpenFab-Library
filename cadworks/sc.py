"""Thin helpers for writing SolidCraft command scripts and running them headless.

Everything in data/ is in inches; SolidCraft scripts take millimetres, so the
helpers convert. Parts are bodies of revolution about world Z unless noted.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

IN = 25.4
CLI = "solidcraft-cli"
META_KEY = "works.cad.library"

# name -> (SolidCraft material name, density g/cm3 if it has to be created, colour)
MATERIALS = {
    "steel": ("Steel", None, None),
    "4130": ("Steel", None, None),
    "stainless": ("Stainless Steel", None, None),
    "delrin": ("Acetal (Delrin)", 1.41, "#1c1c1c"),
    "nylatron": ("Nylatron", 1.16, "#6f7377"),
    "urethane": ("Polyurethane", 1.20, "#a01818"),
}


def mm(v: float) -> float:
    return round(v * IN, 6)


class Script:
    """An ordered list of SolidCraft commands."""

    def __init__(self) -> None:
        self.commands: list[dict] = []

    def cmd(self, command: str, **params) -> None:
        self.commands.append({"command": command, "params": params})

    # ---- geometry -------------------------------------------------------
    def revolve(self, name: str, profile: list, operation: str = "new") -> None:
        """Revolve a closed (r, z) profile, in inches, about world Z.

        `profile` items are (r, z) for a straight segment to that point, or
        ("arc", (r, z), (cr, cz), clockwise) for an arc to that point. The
        first item is the start point; the loop closes back to it.
        """
        self.cmd("sketch.create", name=f"{name} profile",
                 plane={"origin": [0, 0, 0], "x_dir": [1, 0, 0], "y_dir": [0, 0, 1]})
        ends = [p[1] if p[0] == "arc" else p for p in profile]
        for i in range(1, len(profile) + 1):
            item = profile[i % len(profile)]
            a = [mm(ends[i - 1][0]), mm(ends[i - 1][1])]
            b = [mm(ends[i % len(profile)][0]), mm(ends[i % len(profile)][1])]
            if a == b:
                continue  # the profile already ends on its start point
            if item[0] == "arc" and i < len(profile):
                c = item[2]
                self.cmd("sketch.arc.center_point", center=[mm(c[0]), mm(c[1])],
                         start=a, end=b, clockwise=bool(item[3]))
            else:
                self.cmd("sketch.line", points=[a, b], infer=False)
        self.cmd("sketch.finish")
        self.cmd("solid.revolve", axis="y", operation=operation, name=name, body_name=name)

    def hex_prism(self, name: str, across_flats: float, height: float, z0: float = 0.0,
                  hole: float | None = None) -> None:
        """A hexagonal prism along Z from z0 to z0 + height, optionally bored."""
        self.cmd("sketch.create", name=f"{name} hex", plane="XY", offset=mm(z0))
        self.cmd("sketch.polygon.circumscribed", center=[0, 0], radius=mm(across_flats / 2), sides=6)
        if hole:
            self.cmd("sketch.circle.center", center=[0, 0], radius=mm(hole / 2))
        self.cmd("sketch.finish")
        self.cmd("solid.extrude", distance=mm(height), operation="new", name=name, body_name=name)

    def cylinder(self, name: str, dia: float, height: float, base=(0, 0, 0), axis="Z",
                 operation: str = "join") -> None:
        self.cmd("solid.cylinder", diameter=mm(dia), height=mm(height),
                 base=[mm(c) for c in base], axis=axis, operation=operation, name=name)

    # ---- properties -----------------------------------------------------
    def material(self, body: str, key: str) -> None:
        name, density, colour = MATERIALS[key]
        if density is not None:
            self.cmd("material.create", name=name, density_g_cm3=density, color=colour)
        self.cmd("material.assign", bodies=[body], material=name)

    def metadata(self, part_number: str, description: str, vendor: str, extra: dict) -> None:
        self.cmd("document.metadata.set", values={
            "part_number": part_number,
            "description": description,
            "organization": vendor,
            "project": "CAD-Works",
            META_KEY: extra,
        })


def run(script: Script, save: Path | None = None, out: list[Path] | None = None,
        start: Path | None = None, keep: Path | None = None) -> list:
    """Run a script headless and return the per-command results."""
    target = keep or (save.with_suffix(".script.json") if save else Path("script.json"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"commands": script.commands}, indent=1))
    args = [CLI, "run", str(target), "--results"]
    if start:
        args += ["--in", str(start)]
    if save:
        args += ["--save", str(save)]
    for o in out or []:
        args += ["--out", str(o)]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{target}: {r.stderr.strip()[-600:]}")
    data = json.loads(r.stdout)
    return data if isinstance(data, list) else data.get("results", data)


def measure(design: Path) -> dict:
    r = subprocess.run([CLI, "eval", "--in", str(design)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{design}: {r.stderr.strip()[-600:]}")
    return json.loads(r.stdout)


def sphere_slice_volume(ball_dia: float, width: float) -> float:
    """Volume of a sphere between two parallel planes width apart, centred."""
    R, h = ball_dia / 2, width / 2
    return math.pi * (2 * R * R * h - 2 * h ** 3 / 3)
