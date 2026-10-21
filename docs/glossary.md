# Glossary

The same word for the same thing, everywhere: web UI, notifications, README, code. English is the
primary language; German is the second. `tests/test_locales.py` guards the key terms.

| Term (EN) | Begriff (DE) | Meaning | Avoid |
|---|---|---|---|
| folder | Ordner | a direct subfolder of a scan root – what Dustbunny judges | directory, Verzeichnis (for these), Leiche |
| scan root | Scan-Verzeichnis | a folder from `SCAN_ROOTS`, e.g. `/opt/appdata` | appdata root, Wurzel |
| reference | Verweis | a host path something uses or defines | link, mapping |
| source | Quelle | where references come from: Docker, Portainer, compose folders | collector (code only) |
| used / in use | verwendet | a reference points at the folder or into it | benutzt, gebraucht |
| **Active** | **Aktiv** | used by a running container | running (for folders) |
| **Stopped** | **Gestoppt** | used only by stopped containers | |
| **Defined only** | **Nur definiert** | in a stack or compose file, no container | |
| **Orphaned** | **Verwaist** | nothing references it | unused, unbenutzt, dangling, dead |
| **Ignored** | **Ignoriert** | skipped on purpose | excluded |
| mounts the whole scan root | bindet das ganze Scan-Verzeichnis ein | a mount of the root or a parent; doesn't count as use | broad mount (code only) |
| incomplete result | unvollständiges Ergebnis | a source failed; orphans may be wrong | |
| scan | Scan | one run over sources and folders | |
| skin | Skin | a colour scheme, one CSS file | theme |

Container states keep Docker's words: *running* / *läuft*, *stopped* / *gestoppt*. A folder is never
"running"; a folder is *active*.

Wording: short, concrete, no machine-room jargon where a plain word works. German uses "du".
