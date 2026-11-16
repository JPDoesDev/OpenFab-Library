# CAD-Works release

Off-road fabrication hardware as SolidCraft parts and ready-mated assemblies.
Source, data and the generator: see the CAD-Works repository.

## What is here

| Folder | Contents |
|---|---|
| `parts/<family>/` | One part per vendor part number: `.sc` (SolidCraft), `.step`, and a `.txt` sheet |
| `parts/_internal/` | Helper pieces the assemblies need (bearing balls, reference mount tabs). Not things you buy |
| `assemblies/<kind>/` | Mated assemblies: `.sc`, `.step` and a `.bom.csv` |
| `scripts/` | The SolidCraft command scripts that built every file |
| `catalog.json` | Index of everything: dimensions, files, cross-references, BOMs and pivot limits |

## Names and part numbers

File names say what the part is, in decimal inches (0.75in is 3/4"), and end with the
maker and part number in brackets. The same name appears in SolidCraft's design tree
when you insert the part.

The part number is also stored inside each `.sc` file, so a bill of materials made in
SolidCraft (`assembly.bom`) lists it without any extra work. The number used is the
original maker's wherever one is known (FK's rather than a reseller's). Other vendors'
numbers for the same or an equivalent part are listed under "Also available as" in the
part's `.txt` sheet, in `catalog.json`, and in each assembly's `.bom.csv`.

## Using the parts

- Keep the folder structure together: assemblies link to the part files by relative path.
- To keep a pivot moving in your own design, insert the part files directly and recreate
  the joint; a finished assembly linked into another design comes in as one rigid block.
  The script for each assembly in `scripts/assemblies/` shows the joints it uses.
- Sheets list which dimensions are estimated. Check them against the real part before
  you cut or weld.

Licensed under CERN-OHL-W v2; see `LICENSE`. Your own designs that use these parts are
not affected. Changes to the parts themselves must be shared under the same licence.
