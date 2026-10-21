# Design

The web UI uses the **Feierabend** design system by the project's author
([Jake-double-one/design-systems](https://github.com/Jake-double-one/design-systems))
unchanged: same tokens, the same two fonts and the same building blocks. The tokens are in
`web/static/tokens.css`. Only the *meaning* of the colours is mapped to
Dustbunny.

## Colour meaning

| Token                   | Feierabend               | Dustbunny                                                       |
| ----------------------- | ------------------------ | --------------------------------------------------------------- |
| `--dusk`                | worked time, selection   | **in use**: active folders, selection, focus ring               |
| `--dusk` tint (42 %)    | –                        | stopped containers; hatched = only defined in a stack            |
| `--sun`                 | quitting time (reserved) | **dust you can clear**: orphans, the scan button, the brand     |
| `--alert`               | negative balance         | contradictions only: incomplete report, failed source           |
| hint with a gold edge   | information              | warnings that need attention, demo mode                         |

Gold stays rare. An orphan isn't an error, it's space you can win back,
so it's gold and not red. Red only appears when the result itself can't be
trusted.

The stopped/defined tint is mixed from `--dusk` and `--surface-2` with
`color-mix()`. Plain `--dusk-soft` is too close to `--surface-2` in dark mode.

## Building blocks

* **One big number:** the orphaned size. Everything else is smaller.
* **Storage rail** (instead of the timeline): the storage of all folders by
  state. Violet for in use, tinted/hatched for stopped/defined, gold for
  orphaned, empty for ignored.
* **Stats grid:** active, stopped, defined only, orphaned. Only the orphan
  count is coloured.
* **Hints:** shown only when they apply.
* **Folder list:** one `<details>` row per folder, opening up to the path,
  the reasons and every reference.
* **Pills:** filters (violet when selected); gold only for "Scan now".

## Language

German UI uses "du": short, concrete, no jargon. Say "used by running
containers: sonarr", not "bind mount referenced". One wink only, in the
empty state: "Keine Staubmäuse. 🐇".

## Fonts

IBM Plex Mono and Instrument Sans are bundled as WOFF2 (Latin subset,
including umlauts) under the SIL Open Font License. See
`web/static/fonts/OFL-*.txt`. Nothing is loaded from Google Fonts, so the UI
works offline in the LAN and causes no third-party requests.
