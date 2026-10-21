# Skins

Every skin is one CSS file in this folder (`src/dustbunny/skins/`). The file name is the skin's id (`amoled.css` → `amoled`;
only `a-z`, `0-9` and `-`). The server reads the folder while it runs – a new or changed file shows up
in the web UI after a few seconds, no rebuild needed.

The format and the colour names are the same as in ShopWiz and the Feierabend design system, so a
skin file works in all of them.

**Your own skins without touching the code:** put the file into `/data/skins` in the container (or set
`SKINS_DIR`). A file with the name of a built-in skin replaces it. With Docker Compose, mount a folder:

```yaml
volumes:
  - ./my-skins:/data/skins:ro
```

## Format

```css
/*
 * Dustbunny skin – one line about it
 *
 * name: Ocean               ← shown in the app
 * name.de: Ozean            ← name in another language (optional, one line per language)
 * scheme: dark              ← light or dark: what the browser gets for its own parts
 * order: 50                 ← position in the list (optional; built-in: 10, 20, 30, 40)
 */
:root {
  --bg: #0b1a2a;            /* page background */
  --surface: #11263b;       /* cards, the list */
  --surface-2: #183049;     /* chips, inputs */
  --ink: #e8f1fa;           /* text */
  --muted: #97adc2;         /* quieter text */
  --line: #24405c;          /* borders */
  --dusk: #7cc4ff;          /* accent: checkboxes, links, progress, selection */
  --dusk-soft: #173b5c;     /* soft accent background */
  --sun: #ffc24a;           /* main buttons, "important" */
  --sun-soft: #4a3713;      /* soft background of important rows */
  --alert: #ff8a73;         /* errors, delete */
  --ok: #6fd3a0;            /* online dot, list group (chain, "bought at …"); text on --surface and --surface on it */
  --control: #6f8aa3;       /* checkbox borders, drag handles */
  --control-ink: #c9d8e6;
  --on-dusk: #06223a;       /* text/check mark on the accent */
  --on-sun: #241605;        /* text on main buttons */
  --on-alert: #2a0904;      /* text on red buttons */
  --focus-bg: #000000;      /* focus mode */
  --focus-ink: #ffffff;
  --focus-dim: #7a7a7a;
  --shadow: 0 1px 2px rgba(0, 0, 0, 0.4), 0 16px 40px -22px rgba(0, 0, 0, 0.9);
}
```

`default: dark` (or `light`) in the header makes a skin the one a dark (or light) browser gets until
someone picks a skin – the built-in `dark.css` and `light.css` have it.

Colors are `#rrggbb`. A missing color is taken from the standard skin of the same kind (light or dark).
Anything else (other properties, `url()`, `@import`, other selectors) is ignored – a skin only
changes colors.

## Readability

The server checks every skin against WCAG AA when it reads it: text at least 4.5:1 on its backgrounds,
checkbox borders at least 3:1. Shortfalls are written to the server log (`skin "ocean": low contrast: …`) –
the skin is still offered. The built-in skins have to pass: `pytest` fails otherwise.

The skin picker shows each skin as a square split along the diagonal: `--bg` top left, `--dusk`
bottom right.

## What Dustbunny uses the colours for

| Colour | In Dustbunny |
|---|---|
| `--dusk` | in use: active folders, selection, focus ring |
| `--sun` | orphaned folders (space you can win back), the scan button, the brand |
| `--alert` | only when a result can't be trusted (failed source, incomplete report) |
| `--on-sun` | text on the scan button |

`--ok`, `--control*` and `--focus-*` are part of the shared format; Dustbunny doesn't use them yet.
