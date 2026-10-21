# Design

The web UI follows the **Feierabend** design system by the project's author
([Jake-double-one/design-systems](https://github.com/Jake-double-one/design-systems)): the same fonts,
colour names and building blocks.

## Skins

Colours come from skins: one CSS file each in `src/dustbunny/skins/` (built in) or `/data/skins` (your
own), in the format shared with ShopWiz. The server reads them at runtime, checks contrast (WCAG AA) and
puts them into the page; the picker at the top right switches between them. Nothing picked = the light or
dark skin follows the system. See [`src/dustbunny/skins/README.md`](../src/dustbunny/skins/README.md).

## Colour meaning

| Token | Feierabend | Dustbunny |
|---|---|---|
| `--dusk` | worked time, selection | **in use**: active folders, selection, focus ring |
| `--dusk` tint (42 % on `--surface-2`) | – | stopped containers; hatched = defined only |
| `--sun` | quitting time (reserved) | **space you can win back**: orphaned folders, the scan button, the brand |
| `--alert` | negative balance | only when a result can't be trusted: incomplete report, failed source |
| hint with a `--sun` edge | information | warnings that need attention |

Gold stays rare. An orphaned folder isn't an error, it's space you can win back, so it's gold, not red.
Gold is never used as text colour (too little contrast on light skins); it marks with dots, bars and fills.

## Building blocks

- **One big number:** the orphaned size.
- **Storage rail** (the Feierabend timeline): storage of all folders by category.
- **Stats grid:** active, stopped, defined only, orphaned.
- **Hints:** only when they apply.
- **Folder list:** one `<details>` row per folder, opening to the path, the reasons and every reference.
- **Pills:** filters (selected = `--dusk-soft`); gold only for *Scan now*.

## Language

See [glossary.md](glossary.md). One wink only, in the empty state: "No dust bunnies … 🐇".

## Fonts

IBM Plex Mono and Instrument Sans, bundled as WOFF2 (Latin subset incl. umlauts) under the SIL Open Font
License (`src/dustbunny/web/static/fonts/OFL-*.txt`). Nothing is loaded from Google Fonts: the UI works
offline and makes no third-party requests.
