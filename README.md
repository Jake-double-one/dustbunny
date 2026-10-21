# Dustbunny

> Finds orphaned Docker appdata folders – the bind-mount directories that stay
> behind after you delete a stack.

**Status: pre-alpha.** The detection core (compose parser, matcher, CLI) works;
Docker/Portainer collectors, web UI and notifications are being built.

When you remove a stack in Portainer (or `docker compose down` and delete the
compose file), its bind mounts – e.g. `/opt/appdata/<stack>` – stay on disk.
Docker forgets them as soon as the container is gone. Dustbunny lists every
folder under your appdata roots and tells you which ones nothing uses anymore,
why it thinks so, and how much space they take.

Dustbunny is **read-only by default**. Deleting (via quarantine) will be an
explicit opt-in feature.

## How detection works

* **Candidates** are the direct subfolders of each configured scan root.
* **References** are host paths that something still uses or defines:
  container mounts (running *and* stopped), Portainer stack files, local
  compose files. Compose files are parsed structurally *and* scanned for
  absolute paths as a safety net.
* A folder is **referenced** if a reference points at it or anything inside it.
* A mount of the whole root (or a parent of it) – backup tools, file managers –
  is shown as *broad access* but does **not** count as usage.
* Paths with variables Dustbunny can't resolve (`${DATA}/sonarr`) still protect
  a folder with a matching name.
* When in doubt, a folder counts as referenced. A missed orphan is harmless;
  a live folder reported as orphan is not.

| Category       | Meaning                                                    |
| -------------- | ---------------------------------------------------------- |
| `active`       | used by a running container                                |
| `stopped`      | used only by stopped containers                            |
| `defined-only` | only mentioned in a stack/compose file, no container       |
| `orphan`       | nothing references it                                      |
| `ignored`      | ignore rule, symlink, nested scan root or system folder    |

If any reference source fails (e.g. Portainer unreachable) the report is
marked `complete: false` and orphans in it must not be acted on.

## Important: mount appdata under the same path

Docker reports **host** paths. Mount your appdata roots into the container
under exactly the same path, otherwise nothing matches:

```yaml
volumes:
  - /opt/appdata:/opt/appdata:ro   # correct
  # - /opt/appdata:/appdata:ro     # wrong: every folder would look orphaned
```

If that's impossible (symlinked roots, `/mnt/user` vs. `/mnt/cache` …) set
`PATH_ALIASES=/host/path=/container/path`.

## Try it (CLI)

```sh
pip install -e ".[dev]"
dustbunny --once --root /opt/appdata --compose /opt/stacks/media/compose.yaml
dustbunny --once --json --root /opt/appdata --references refs.json > report.json
```

## Web UI (prototype)

`web/` holds the dashboard. Until the API exists, it falls back to demo data:

```sh
cd web && python -m http.server 8000   # open http://localhost:8000
python scripts/demo_report.py > web/demo/report.json   # regenerate demo data
```

Design: see [docs/design.md](docs/design.md).

## Configuration

| Variable                    | Default  | Description                                         |
| --------------------------- | -------- | --------------------------------------------------- |
| `SCAN_ROOTS`                | –        | **Required.** Comma-separated appdata roots         |
| `IGNORE`                    |          | Comma-separated globs (folder name or full path)    |
| `PATH_ALIASES`              |          | `HOST=LOCAL` path translations, comma-separated     |
| `SCAN_INTERVAL`             | `6h`     | e.g. `30m`, `6h`, `1d`                              |
| `SCAN_SIZES`                | `true`   | Calculate folder size and last change               |
| `PORTAINER_URL`             |          | e.g. `https://portainer:9443`                       |
| `PORTAINER_API_KEY`         |          | Portainer access token (read access is enough)      |
| `PORTAINER_ENDPOINT_ID`     |          | Only consider stacks of this environment            |
| `PORTAINER_INSECURE`        | `false`  | Skip TLS verification                               |
| `COMPOSE_DIRS`              |          | Folders with compose stacks (Dockge, Komodo, …)     |
| `NOTIFY_URLS`               |          | Apprise URLs                                        |
| `NOTIFY_ON`                 | `change` | `change` or `always`                                |
| `ENABLE_ACTIONS`            | `false`  | Allow quarantine/delete (phase 2)                   |
| `QUARANTINE_RETENTION_DAYS` | `30`     | Purge quarantined folders after N days              |
| `AUTH_USER`/`AUTH_PASSWORD` |          | Protect the web UI                                  |
| `DATA_DIR`                  | `/data`  | State database                                      |

Not all of them are wired up yet – see the roadmap.

## Roadmap

1. ✅ Compose parser
2. ✅ Matcher, report model, `--once --json` CLI
3. Docker socket collector
4. Portainer collector
5. State (first seen, diff) + notifications
6. Web UI + API (UI prototype with demo data ✅)
7. Docker image, compose example, release workflow
8. Quarantine / delete (opt-in)

## Development

```sh
pip install -e ".[dev]"
ruff check . && ruff format --check . && pytest
```

## License

MIT
