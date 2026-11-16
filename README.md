# OpenFab Library

Common off-road fabrication hardware as SolidCraft parts and ready-mated assemblies:
spherical bearings (uniballs), rod ends (heims), misalignment spacers, weld-in cups,
snap rings, jam nuts, pivot bushings and sleeves. Every part carries its vendor part
number, so an assembly's bill of materials comes out ready to order from.

Status: first slice, covering the 1" uniball stack, the 3/4" rod end and the common
sleeve-bushing pivots. `catalog.json` lists every part and assembly.

## What the licence means for builders

OpenFab Library is open hardware under the CERN Open Hardware Licence v2, Weakly Reciprocal
(CERN-OHL-W). In practice:

- **Use the parts in anything.** Personal or commercial, no fee and no permission needed.
- **Your own designs stay yours.** A chassis, arm, link or any other assembly you build
  that uses these parts is not affected by this licence. You can keep it private, sell
  it, or release it under whatever terms you like.
- **Share fixes and improvements to the parts themselves.** If you correct a dimension,
  improve a model or add a new size, and you pass that changed part on to anyone, publish
  the change under this same licence so every other builder gets it too. Opening an issue
  or pull request here is the easiest way.

The whole point is that when one person finds an error or measures a real part, the
library gets better for everyone. The short version above is a summary, not the legal
text; the full terms are at the end of this file and in [LICENSE](LICENSE).

## Layout

| Path | What it holds |
|---|---|
| `data/*.csv` | One table per part family, in inches: dimensions, part numbers, sources |
| `data/cross_reference.csv` | Other vendors' numbers for the same or an equivalent part |
| `data/assemblies.json` | Assembly recipes: which parts go together |
| `openfab/` | Python (standard library only) that turns the data into SolidCraft scripts and runs them |
| `catalog.json` | Generated index: every part and assembly, its dimensions, files, BOM and pivot limit |
| `release/` | Generated output, ready to zip and publish (not in git); see below |

## Build

Needs `solidcraft-cli` (SolidCraft 0.43 or later) on the path.

    python -m openfab.build            # everything, about a minute; rebuilds release/ from scratch
    python -m openfab.build JMX12T     # only assemblies whose key contains the text

`catalog.json` records the SolidCraft version that built the release. SolidCraft's file
format changes between versions, so the `.step` copies are the safe choice for older installs.

The build checks each part's volume against the analytic value, checks each assembly
for interference at rest and for broken or absolute links, and fails loudly on any of them.

## The release folder

    release/
      parts/
        Uniballs/          Uniball 1in bore x 2.125in OD (FK WSSX16T).sc  .step  .png  .txt
        Rod Ends/          Rod End 0.75in bore, 0.75-16 RH (FK JMX12T).sc ...
        Spacers/  Uniball Cups/  Snap Rings/  Jam Nuts/  Bushings/
        Inner Sleeves/  Outer Sleeves/
        _internal/         bearing balls: helpers the assemblies need, not things you buy
      assemblies/
        Uniball Stacks/    Uniball Stack 1in, misalignment spacers, 0.75in bolt, 2.76in stack.sc  .step  .png  .bom.csv
        Rod End Links/  Bushing Pivots/
      scripts/             the SolidCraft command scripts that built every file
      catalog.json  README.md  LICENSE

## Names and part numbers

- **File names are readable** and use decimal inches (0.75in is 3/4"), because a file name
  cannot hold a slash. A part's name ends with its maker and part number in brackets.
  SolidCraft shows the same name in the design tree when the part is inserted.
- **The part number lives inside the file** as a design property, so `assembly.bom` in
  SolidCraft lists it for anything you build from these parts, whatever the files are called.
- **The maker's own number comes first.** A part is filed under the original maker's number
  (FK's `WSSX16T`, not a reseller's stock number for it). Kartek's own parts use Kartek's number.
- **Cross-references** go in `data/cross_reference.csv`: one row per other vendor's number,
  marked `same part`, `equivalent` or `sold in kit`. They show up in each part's `.txt` sheet,
  in `catalog.json` and in the `also_available_as` column of every assembly BOM. When you find
  that one vendor's part matches another's, add a row there.
- **Each part has a `.txt` sheet** beside it with part number, vendor, cross-references,
  dimensions and which dimensions are estimated.
- **Each part and assembly has a `.png`** beside it: one orthographic three-quarter view for
  quick reference.

## How the assemblies work

- The fixed side (cup, rod end body, outer sleeve) is grounded. The pin side (ball and
  spacers, or the inner sleeve) moves on one joint named `Pivot`.
- Uniballs and rod ends use a ball joint. Its tilt limit (`pitch`) is found by sweeping
  the joint until parts collide, then stored on the joint. `catalog.json` records the
  angle and which two parts touch first.
- Bushing pivots use a revolute joint with no limit.
- Bolts, nuts, washers and mount tabs are not included; that hardware is the builder's choice.
  A rod end or uniball with no spacers therefore has no stored limit: your mount sets it.
- A bearing is two files, race and ball, so the ball can move. The race (or rod end
  body) carries the part number; the ball is left out of the BOM.
- SolidCraft links a sub-assembly in as one rigid block, so to keep a pivot moving in
  your own design, insert the part files directly and recreate the joint rather than
  linking a finished assembly. Each assembly's script in `build/scripts/` shows how.

## Accuracy

Dimensions come from the [FK Rod Ends 2017 Industrial Catalog](https://www.fkrodends.com/catalogs/)
and Kartek's product pages; each data row names its source. The vendor material itself is
not part of this repository. Where a
vendor does not publish a dimension it is estimated, and the part's `estimated` list in
`catalog.json` says which. The main ones:

- misalignment spacers: only six dimensions are published; the waist and seat flange are
  scaled from photos, and these set the pivot limit
- uniball cup: lip and snap ring groove
- rod end: plain cylindrical shank with no neck
- AutoFab kit sleeves: inferred from the kit size and its bushings
- cone, radius, hourglass, stepped and flat-top spacer heads follow the same six published
  dimensions, with their shapes scaled from photos

Rod end shanks carry a cosmetic thread over the threaded length, with the right pitch and
hand. SolidCraft has no Unified form for shaft threads, so it is stored as the same profile
in millimetres (3/4-16 shows as M19.05x1.5875) and the feature is named with the real
callout. Jam nut threads are not modelled. Urethane bushings overlap their sleeves by the
press fit.

## Contact and contributing

OpenFab Library is maintained by JPDoesDev.

- Website: [jpdoes.dev](https://jpdoes.dev)
- Email: [jpdoesdev@gmail.com](mailto:jpdoesdev@gmail.com)

Contributions are welcome: corrected dimensions, measurements taken from a real part,
new sizes, new part families and vendor cross-references all make the library more
useful. Open an issue or pull request, or get in touch directly.

**Manufacturers:** if you make builder-focused parts and would like them represented
accurately here, please get in touch. Supplying dimensions or models for your products
helps your customers design around them and order the right part number first time.

## Licence

Copyright 2026 JPDoesDev.

This source describes Open Hardware and is licensed under the CERN-OHL-W v2. You may
redistribute and modify this source and make products using it under the terms of the
CERN-OHL-W v2 (https://ohwr.org/cern_ohl_w_v2.txt).

This source is distributed WITHOUT ANY EXPRESS OR IMPLIED WARRANTY, INCLUDING OF
MERCHANTABILITY, SATISFACTORY QUALITY AND FITNESS FOR A PARTICULAR PURPOSE. Please see
the CERN-OHL-W v2 for applicable conditions. The models are reference geometry, not
engineering data: check every dimension against the real part before you cut or weld.

Vendor names and part numbers are used only to identify the parts being modelled.
OpenFab Library is not affiliated with or endorsed by those vendors.
