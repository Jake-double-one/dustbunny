<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg">
  <img src="docs/logo-light.svg" width="96" align="right" alt="Dustbunny logo: bunny ears peeking out of a folder">
</picture>

# Dustbunny

**Finds orphaned Docker appdata folders – the folders that stay behind after you delete a stack.**

🇩🇪 [Deutsche Version](README.de.md)

<p>
  <img src="docs/screenshots/dashboard.png" width="520" alt="Dashboard: orphaned size, storage by category, folder list with reasons">
  <img src="docs/screenshots/phone-dark.png" width="220" alt="The same dashboard on a phone, dark skin, in German">
</p>

When you remove a stack in Portainer (or run `docker compose down` and delete the compose file), its
bind mounts – e.g. `/opt/appdata/<stack>` – stay on disk. Docker forgets them as soon as the container is
gone. Dustbunny lists every folder in your scan roots (e.g. `/opt/appdata`) and tells you which ones nothing uses anymore,
why it thinks so, how big they are and since when they are orphaned.

**Dustbunny only reads.** It never changes or deletes anything.

---

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Install with Docker / Portainer](#install-with-docker--portainer)
- [Configuration](#configuration)
- [Sources](#sources)
- [Notifications](#notifications)
- [Folder sizes and permissions](#folder-sizes-and-permissions)
- [Reverse proxy](#reverse-proxy)
- [Skins](#skins)
- [Languages](#languages)
- [AI agents (MCP)](#ai-agents-mcp)
- [API and command line](#api-and-command-line)
- [Development](#development)
- [Roadmap](#roadmap)

## Features

| | |
|---|---|
| **Finds orphaned folders** | Every folder in your scan roots is checked against running and stopped containers, Portainer stacks (also stopped ones) and compose files. |
| **Explains itself** | Each folder shows why it is orphaned or who uses it – container, stack, mount type. |
| **Size and age** | Disk usage like `du`, last change anywhere in the folder, and "orphaned for 23 days". |
| **Safe when in doubt** | A folder that might still be used counts as used. If a source fails, the result is marked incomplete and no notification goes out. |
| **Notifications** | Newly orphaned folders and folders that are no longer orphaned, via [Apprise](https://github.com/caronc/apprise): ntfy, Discord, e-mail, Telegram, Gotify, … |
| **Web UI** | Works on the phone, several skins, English and German, ignore a folder with one click. |
| **Read-only by design** | Read-only mounts, a socket proxy that only allows reading, read-only container file system. |

## How it works

- **Folders:** every direct subfolder of a scan root (`/opt/appdata/sonarr`, `/opt/appdata/radarr`, …).
- **References:** every host path that something still uses or defines:
  - container mounts from the Docker API – running **and** stopped containers, including named volumes
    that are bound to a host folder (`driver_opts.device`);
  - Portainer stacks – important because a stopped stack has no containers, but needs its data;
  - compose files in folders you name (Dockge, Komodo, plain compose).
  Compose files are read properly (short and long volume syntax, named volumes, `env_file`, `secrets`,
  `configs`, `include`, variables from the stack environment or `.env`) and also searched for any absolute
  path as a safety net.
- A folder is **in use** if a reference points at it or at anything inside it.
- A mount of the whole scan root (or a parent of it) – backup tools, file managers – is shown as
  *mounts the whole scan root*, but does **not** count as use. Otherwise it would hide every orphan.
- Paths with a variable Dustbunny can't resolve (`${DATA}/sonarr`) still protect a folder with that name.

| Category | Meaning |
|---|---|
| **Active** | used by a running container |
| **Stopped** | used only by stopped containers |
| **Defined only** | still in a stack or compose file, but no container exists |
| **Orphaned** | nothing references it |
| **Ignored** | ignore rule, ignored in the web UI, symbolic link or system folder (`lost+found`, `@eaDir`, …) |

When in doubt, a folder counts as used: a missed orphaned folder costs a little disk space, a live folder
shown as orphaned could cost data. For the same reason Dustbunny stays quiet when it can't be sure:

- If a source fails or a scan root can't be read, the result is marked **incomplete**.
- If a path can't be checked fully (an unknown variable, an unreadable compose file), the result is marked
  **uncertain** and a hint says what to fix.

In both cases there are no notifications, and "orphaned for … days" doesn't change.

## Install with Docker / Portainer

The image is published for `amd64` and `arm64`: `ghcr.io/jake-double-one/dustbunny:latest`.

**Portainer:** *Stacks → Add stack → Web editor*, paste [`docker-compose.yml`](docker-compose.yml), adjust
the lines marked with `←`, *Deploy the stack*. Or choose *Repository* with
`https://github.com/Jake-double-one/dustbunny` and the compose path `docker-compose.yml`.

**Command line:**

```sh
curl -O https://raw.githubusercontent.com/Jake-double-one/dustbunny/main/docker-compose.yml
# adjust SCAN_ROOTS and the volume lines, then:
docker compose up -d
```

Open `http://<host>:8077`. The first scan starts right away.

To build the image from this repository instead of pulling it:
`docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`.

> [!IMPORTANT]
> **Mount your appdata under exactly the same path as on the host.** Docker reports host paths, so
> `/opt/appdata` must be `/opt/appdata` inside the container too:
>
> ```yaml
> volumes:
>   - /opt/appdata:/opt/appdata:ro   # right
>   # - /opt/appdata:/appdata:ro     # wrong: every folder would look orphaned
> ```
>
> If that's not possible (e.g. Unraid `/mnt/user` vs. `/mnt/cache`, or a symlinked folder), set
> `PATH_ALIASES=/host/path=/container/path`. Dustbunny warns when nothing points into a scan root.

The compose file contains two services:

- **dustbunny** – runs as root *without any capability except reading* (`DAC_READ_SEARCH`), with a read-only
  file system, read-only appdata mounts and `no-new-privileges`. See
  [Folder sizes and permissions](#folder-sizes-and-permissions).
- **socket-proxy** ([tecnativa/docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy)) –
  lets Dustbunny list containers and volumes, nothing else. Dustbunny never sees the Docker socket itself.

## Configuration

All settings are environment variables.

| Variable | Default | Description |
|---|---|---|
| `SCAN_ROOTS` | – | **Required.** Appdata folders, comma-separated. Mount each under the same path. |
| `IGNORE` | | Folders to skip: names or paths, globs allowed, comma-separated (`backup-*,/opt/appdata/keep`) |
| `PATH_ALIASES` | | `HOST=LOCAL` path translations, comma-separated |
| `SCAN_INTERVAL` | `6h` | `30m`, `6h`, `1d` … `0` = no scheduled scans (one at start, then on *Scan now*). After an incomplete scan, the next one comes after 2 minutes. |
| `SCAN_SIZES` | `true` | Calculate size and last change (reads every file's metadata) |
| `DOCKER_ENABLED` | `true` | Ask the Docker API |
| `DOCKER_HOST` | local socket | e.g. `tcp://socket-proxy:2375` |
| `PORTAINER_URL` | | e.g. `https://192.168.1.10:9443` |
| `PORTAINER_API_KEY` | | Portainer → *My account* → *Access tokens* |
| `PORTAINER_ENDPOINT_ID` | | Only stacks of this environment (the number in its Portainer URL) |
| `PORTAINER_INSECURE` | `false` | Accept a self-signed certificate |
| `COMPOSE_DIRS` | | Folders with one stack per subfolder, comma-separated |
| `NOTIFY_URLS` | | Apprise URLs, comma-separated |
| `NOTIFY_ON` | `change` | `change`: newly orphaned folders or folders no longer orphaned · `always`: after every scan |
| `NOTIFY_LANGUAGE` | `en` | Language of notifications (`en`, `de`, …) |
| `AUTH_USER` / `AUTH_PASSWORD` | | Password for the web UI (Basic Auth). Recommended if others can reach it. |
| `MCP_ENABLED` | `false` | Let AI agents connect via MCP at `/mcp` – see [AI agents (MCP)](#ai-agents-mcp) |
| `MCP_TOKEN` | | Secret key for MCP, at least 24 characters (`openssl rand -hex 24`) |
| `MCP_ALLOW_CHANGES` | `false` | Agents may also ignore folders (never more) |
| `HOST` / `PORT` | `0.0.0.0` / `8080` | Address and port the web server listens on inside the container |
| `DATA_DIR` | `/data` | State (SQLite) and your own skins |
| `SKINS_DIR` | `$DATA_DIR/skins` | Folder for your own skins |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error` |

## Sources

### Docker

All containers are read, running and stopped: bind mounts, named volumes bound to a host folder, and the
compose labels (project folder and compose files). The socket proxy needs `CONTAINERS=1` and `VOLUMES=1`.
Without `VOLUMES=1`, Dustbunny can't see which folder a named volume uses and marks the result incomplete.

### Portainer

Needed when you stop stacks in Portainer: Portainer removes their containers, so only the stack file still
says that the data is needed. Dustbunny reads every stack file with its environment variables. Create an
access token under *My account → Access tokens*; a user that can see the stacks is enough.

- Several environments (hosts) in one Portainer: set `PORTAINER_ENDPOINT_ID` to the one Dustbunny runs on,
  otherwise stacks of other hosts protect folders with the same path here.
- Relative paths in Portainer stacks point into Portainer's own data folder and are skipped.
- Stacks with additional compose files: only the main file is read (shown as a hint).

### Compose folders

For Dockge, Komodo or plain `docker compose`: `COMPOSE_DIRS=/opt/stacks` reads compose files directly in
that folder and in each subfolder (`/opt/stacks/<stack>/compose.yaml`, `.env` included). Mount the folder
under the same path, so relative paths (`./config`) resolve correctly.

## Notifications

Set `NOTIFY_URLS` to one or more [Apprise URLs](https://github.com/caronc/apprise/wiki), for example
`ntfy://ntfy.sh/my-topic`, `discord://webhook_id/webhook_token`, `tgram://bot_token/chat_id`,
`mailtos://user:password@example.com`. The first scan lists all orphaned folders it finds; after that, a
message lists newly orphaned folders with their size and folders that are no longer orphaned. Incomplete or
uncertain results never notify.

## Folder sizes and permissions

Appdata folders often belong to different users and are not readable for others (`700`). Two ways:

- **Default in `docker-compose.yml`:** `user: "0:0"` with `cap_drop: ALL` and only `cap_add:
  DAC_READ_SEARCH`. This root can read every file but cannot write anywhere except `/data` – the appdata
  mounts and the container file system are read-only.
- **Without root:** remove the `user` and `cap_add` lines. Dustbunny runs as uid 1000 and reads what that
  user may read (folders of most linuxserver.io images use uid 1000). Sizes of other folders are marked as
  incomplete; detection itself is not affected.

Switching between both ways is safe: the files in `/data` stay writable for both. If you use a host folder
instead of the `dustbunny-data` volume, it must be writable for uid 1000 or group 0.

## Reverse proxy

Dustbunny works behind Traefik, Nginx Proxy Manager, Caddy and the like without extra settings:

- **Keep the port private.** Set the port to `"127.0.0.1:8077:8080"` in `docker-compose.yml` (proxy on the
  same host), or remove `ports:` and let the proxy reach `dustbunny:8080` through a shared Docker network.
  Otherwise the open port goes around the proxy and its login.
- **Login:** either Dustbunny's own (`AUTH_USER` / `AUTH_PASSWORD`, passed through by the proxy) or the
  proxy's (Authelia, Authentik, …) – then leave Dustbunny's empty and keep the port private as above.
- **Proxy headers** (`X-Forwarded-For`, `X-Forwarded-Proto`) are not needed and are ignored: Dustbunny
  doesn't use the client address for anything, uses only relative links and sets no cookies.
- **Sub-path** (`https://example.com/dustbunny/`): works when the proxy strips the prefix (Traefik
  `StripPrefix`, Nginx `proxy_pass http://dustbunny:8080/;`).
- `/healthz` needs no password, for health checks of the proxy or of Docker.

## Skins

Pick a skin with the swatches at the top right; the choice is saved in the browser. Built in: *Dark*,
*AMOLED*, *Light*, *Mango*. Until you pick one, the light or dark skin follows your system.

Your own skin: put a CSS file into `/data/skins` (or mount a folder there) – it shows up within seconds,
no restart needed. The format, shared with ShopWiz and the Feierabend design system, is described in
[`src/dustbunny/skins/README.md`](src/dustbunny/skins/README.md).

## Languages

The web UI and notifications speak English and German. The browser language decides; you can switch at the
top right.

**Adding a language:** copy [`src/dustbunny/locales/en.json`](src/dustbunny/locales/en.json) to
`<code>.json` (e.g. `fr.json`), translate the values and set `language.name`. It appears in the language
menu automatically. `pytest` checks that the file has every key and the same `{placeholders}`. Keys ending in
`_one` / `_other` are plural forms; languages with more forms can add `_zero`, `_two`, `_few`, `_many` (as in
`Intl.PluralRules`) – the web UI uses them, notifications use `_one` / `_other`. The terms are explained in [`docs/glossary.md`](docs/glossary.md).

## AI agents (MCP)

AI agents can work with Dustbunny through the [Model Context Protocol](https://modelcontextprotocol.io):
"Which appdata folders are orphaned and how big are they?", "Why is paperless only defined?",
"Scan again and tell me what changed."

1. Set `MCP_ENABLED: "true"` and a secret `MCP_TOKEN` (at least 24 characters, e.g. `openssl rand -hex 24`).
2. Connect the agent:

| Agent | How |
|---|---|
| **Claude** (web, desktop, app) | Settings → Connectors → *Add custom connector* → name "Dustbunny", address `https://<your-server>/mcp/<MCP_TOKEN>` |
| **ChatGPT** | Settings → Apps & Connectors → developer mode → *Create connector* → the same address, no authentication |
| **Grok** | grok.com/connectors → *New connector* → *Custom* → the same address |
| **Claude Code** | `claude mcp add --transport http dustbunny https://<your-server>/mcp --header "Authorization: Bearer <MCP_TOKEN>"` |
| **Other clients** | `POST /mcp` with `Authorization: Bearer <MCP_TOKEN>`, or the address with the key |

Cloud agents (Claude, ChatGPT, Grok) call Dustbunny from their servers, so it must be reachable from the
internet over **HTTPS** – put it behind your [reverse proxy](#reverse-proxy). Agents on your own network
(Claude Code, Claude Desktop with a local connector) can use `http://<host>:8077`.

**What agents can do:** `get_summary` (counts, orphaned size, whether the result is complete), `list_folders`
(by category or search), `get_folder` (reasons, which containers and stacks use it and how big their paths are), `start_scan`. With
`MCP_ALLOW_CHANGES: "true"` also `set_folder_ignored`. Never possible: anything that touches a folder –
Dustbunny can't, so agents can't either.

**Keep the key secret:** it is the only protection of `/mcp` (Basic Auth doesn't apply there). Whoever has it
can read the folder list. Change `MCP_TOKEN` to cut all agents off. The agent's provider sees the folder
names and paths it asks about. With `LOG_LEVEL=debug`, the access log shows request paths, including the key.

## API and command line

| Endpoint | |
|---|---|
| `GET /api/report` | The last report as JSON (folders, categories, reasons, references, sources) |
| `GET /api/status` | Scan state, last and next scan, configuration problems |
| `POST /api/scan` | Start a scan |
| `POST /api/ignore` | `{"path": "/opt/appdata/x", "ignored": true}` |

POST requests must send JSON (`Content-Type: application/json`), so other web pages can't trigger them:
`curl -X POST -H 'Content-Type: application/json' -d '{}' http://host:8077/api/scan`.
| `GET /healthz` | Health check (no password needed) |

Reasons and warnings come with a `code`, `params` and an English `message`.

A single scan without the web server, e.g. for scripts:

```sh
docker run --rm -v /opt/appdata:/opt/appdata:ro -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -e SCAN_ROOTS=/opt/appdata --user 0:0 ghcr.io/jake-double-one/dustbunny --once --json
```

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest
SCAN_ROOTS=/opt/appdata .venv/bin/dustbunny          # web UI on http://localhost:8080
```

`http://localhost:8080/?demo` shows demo data (`scripts/demo_report.py` creates it).

**Releasing:** write the release notes to `docs/releases/vX.Y.Z.md`, set `version` in `pyproject.toml`,
then tag and push (`git tag vX.Y.Z && git push origin vX.Y.Z`). CI tests, builds the image for amd64 and
arm64, pushes it to ghcr.io and publishes the GitHub release with these notes.

```
src/dustbunny/
  collectors/      docker_socket.py, portainer.py, compose_files.py – where references come from
  compose_parser.py, interpolation.py   reading compose files and ${VARIABLES}
  matcher.py       which folder is used by what – the core rules
  scanner.py       folders, sizes, ages
  state.py         SQLite: orphaned since, ignored folders, last report
  notify.py        Apprise
  server.py        FastAPI: API, web UI, scheduled scans
  locales/         one JSON file per language
  skins/           one CSS file per skin
  web/             the web UI (no build step)
docs/              design, glossary, screenshots
```

## Roadmap

- Quarantine and delete orphaned folders – opt-in, with a dry run, a fresh check right before acting and an
  audit log. Not in this version: Dustbunny only reads.
- Prometheus `/metrics`, a Homepage / Homarr widget.
- Several Portainer environments in one view, unused Docker volumes.

## License

MIT. Fonts: IBM Plex Mono and Instrument Sans, SIL Open Font License (see `src/dustbunny/web/static/fonts`).
