# Components

Every part and assembly in the library. Built with SolidCraft 0.43.0; the `.step` files open in any CAD program.

Part numbers are stored inside each `.sc` file, so a SolidCraft bill of materials lists them for anything you build. `catalog.json` in this folder is the same information for scripts.

## Parts

| Family | Parts |
|---|---|
| [Bushings](parts/bushings/index.md) | 26 |
| [Inner Sleeves](parts/inner-sleeves/index.md) | 14 |
| [Jam Nuts](parts/jam-nuts/index.md) | 2 |
| [Outer Sleeves](parts/outer-sleeves/index.md) | 14 |
| [Rod Ends](parts/rod-ends/index.md) | 2 |
| [Snap Rings](parts/snap-rings/index.md) | 1 |
| [Spacers](parts/spacers/index.md) | 49 |
| [Uniball Cups](parts/uniball-cups/index.md) | 1 |
| [Uniballs](parts/uniballs/index.md) | 1 |
| [Internal helper pieces](parts/_internal/index.md) | 3 |

## Assemblies

| Type | Assemblies |
|---|---|
| [Bushing Pivots](assemblies/bushing-pivots/index.md) | 16 |
| [Rod End Links](assemblies/rod-end-links/index.md) | 5 |
| [Uniball Stacks](assemblies/uniball-stacks/index.md) | 4 |

## Using the files

- Keep `parts/` and `assemblies/` together: assemblies link to the part files by relative path.
- To keep a pivot moving in your own design, insert the part files directly and recreate the joint. A finished assembly linked into another design comes in as one rigid block. The script for each assembly in `scripts/generated/assemblies/` shows the joints it uses.
- SolidCraft's file format changes between versions. Open the `.sc` files with the version above or newer, or use the `.step` copies.
