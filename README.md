# CAD-Works

Common off-road fabrication hardware as SolidCraft parts and ready-mated assemblies:
spherical bearings (uniballs), rod ends (heims), misalignment spacers, weld-in cups,
snap rings, jam nuts, pivot bushings and sleeves. Every part carries its vendor part
number, so an assembly's bill of materials comes out ready to order from.

Status: first slice. 130 parts and 25 assemblies covering the 1" uniball stack, the
3/4" rod end and the common sleeve-bushing pivots. No licence has been chosen yet.

## Layout

| Path | What it holds |
|---|---|
| `data/*.csv` | One table per part family, in inches: dimensions, part numbers, cross-references, sources |
| `data/assemblies.json` | Assembly recipes: which parts go together |
| `cadworks/` | Python (standard library only) that turns the data into SolidCraft scripts and runs them |
| `catalog.json` | Generated index: every part and assembly, its dimensions, files, BOM and pivot limit |
| `build/` | Generated designs (`.sc`), STEP copies, BOM CSVs and the scripts that made them (not in git) |
| `ref/` | Vendor source material the data was taken from |

## Build

Needs `solidcraft-cli` (SolidCraft 0.43 or later) on the path.

    python -m cadworks.build            # everything, about a minute
    python -m cadworks.build JMX12T     # only assemblies whose name contains the text

The build checks each part's volume against the analytic value, checks each assembly
for interference at rest, and fails loudly on any mismatch.

## How the assemblies work

- The fixed side (cup, rod end body, outer sleeve) is grounded. The pin side (ball,
  spacers, bolt, reference tabs) moves on one joint named `Pivot`.
- Uniballs and rod ends use a ball joint. Its tilt limit (`pitch`) is found by sweeping
  the joint until parts collide, then stored on the joint. `catalog.json` records the
  angle and which two parts touch first.
- Bushing pivots use a revolute joint with no limit.
- A bearing is two files, race and ball, so the ball can move. The race (or rod end
  body) carries the part number; the ball and the reference tabs are left out of the BOM.
- SolidCraft links a sub-assembly in as one rigid block, so to keep a pivot moving in
  your own design, insert the part files directly and recreate the joint rather than
  linking a finished assembly. Each assembly's script in `build/scripts/` shows how.

## Accuracy

Dimensions come from the FK Rod Ends 2017 catalog and Kartek's product pages. Where a
vendor does not publish a dimension it is estimated, and the part's `estimated` list in
`catalog.json` says which. The main ones:

- misalignment spacers: only six dimensions are published; the waist and seat flange are
  scaled from photos, and these set the pivot limit
- uniball cup: lip and snap ring groove
- rod end: plain cylindrical shank, no thread or neck
- AutoFab kit sleeves: inferred from the kit size and its bushings
- cone, hourglass, stepped and flat-top spacers are in the data but not modelled yet

Threads are not modelled. Urethane bushings overlap their sleeves by the press fit.
