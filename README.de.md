# Dustbunny

**Findet verwaiste Docker-Appdata-Ordner – die Ordner, die liegen bleiben, wenn du einen Stack löschst.**

🇬🇧 [English version](README.md) (maßgeblich)

<p>
  <img src="docs/screenshots/dashboard.png" width="520" alt="Übersicht: verwaiste Datenmenge, Speicher nach Kategorie, Ordnerliste mit Begründungen">
  <img src="docs/screenshots/phone-dark.png" width="220" alt="Dieselbe Übersicht auf dem Handy, dunkler Skin, auf Deutsch">
</p>

Wenn du in Portainer einen Stack entfernst (oder `docker compose down` machst und die Compose-Datei löschst),
bleiben seine Bind-Mounts – etwa `/opt/appdata/<stack>` – auf der Platte. Docker vergisst sie, sobald der
Container weg ist. Dustbunny listet jeden Ordner in deinen Appdata-Verzeichnissen auf und sagt dir, welche
nichts mehr verwendet, warum, wie groß sie sind und seit wann sie verwaist sind.

**Dustbunny liest nur.** Es ändert und löscht nichts.

---

## Inhalt

- [Funktionen](#funktionen)
- [So funktioniert es](#so-funktioniert-es)
- [Installation mit Docker / Portainer](#installation-mit-docker--portainer)
- [Einstellungen](#einstellungen)
- [Quellen](#quellen)
- [Benachrichtigungen](#benachrichtigungen)
- [Ordnergrößen und Rechte](#ordnergrößen-und-rechte)
- [Skins](#skins)
- [Sprachen](#sprachen)
- [API und Kommandozeile](#api-und-kommandozeile)
- [Entwicklung](#entwicklung)

## Funktionen

| | |
|---|---|
| **Findet verwaiste Ordner** | Jeder Ordner in deinen Scan-Verzeichnissen wird gegen laufende und gestoppte Container, Portainer-Stacks (auch gestoppte) und Compose-Dateien geprüft. |
| **Begründet alles** | Zu jedem Ordner steht, warum er verwaist ist oder wer ihn verwendet – Container, Stack, Art der Einbindung. |
| **Größe und Alter** | Belegter Platz wie bei `du`, letzte Änderung irgendwo im Ordner und „seit 23 Tagen verwaist“. |
| **Im Zweifel sicher** | Ein Ordner, der noch verwendet werden könnte, zählt als verwendet. Fällt eine Quelle aus, ist das Ergebnis als unvollständig markiert und es geht keine Benachrichtigung raus. |
| **Benachrichtigungen** | Neue oder behobene verwaiste Ordner über [Apprise](https://github.com/caronc/apprise): ntfy, Discord, E-Mail, Telegram, Gotify … |
| **Weboberfläche** | Fürs Handy gemacht, mehrere Skins, Deutsch und Englisch, Ordner mit einem Klick ignorieren. |
| **Nur lesend** | Schreibgeschützte Mounts, ein Socket-Proxy, der nur Lesen erlaubt, schreibgeschütztes Container-Dateisystem. |

## So funktioniert es

- **Ordner:** jeder direkte Unterordner eines Scan-Verzeichnisses (`/opt/appdata/sonarr`, …).
- **Verweise:** jeder Host-Pfad, den etwas noch verwendet oder definiert:
  - Mounts aus der Docker-API – laufende **und** gestoppte Container, auch Named Volumes, die an einen
    Host-Ordner gebunden sind (`driver_opts.device`);
  - Portainer-Stacks – wichtig, weil ein gestoppter Stack keine Container hat, seine Daten aber braucht;
  - Compose-Dateien in Ordnern, die du angibst (Dockge, Komodo, reines Compose).
  Compose-Dateien werden richtig gelesen (kurze und lange Volume-Schreibweise, Named Volumes, `env_file`,
  `secrets`, `configs`, `include`, Variablen aus der Stack-Umgebung oder `.env`) und zusätzlich nach jedem
  absoluten Pfad durchsucht.
- Ein Ordner wird **verwendet**, wenn ein Verweis auf ihn oder auf etwas darin zeigt.
- Wer das ganze Scan-Verzeichnis (oder einen Elternordner) einbindet – Backup-Tools, Dateimanager –, wird als
  *bindet das ganze Scan-Verzeichnis ein* angezeigt, zählt aber **nicht** als Verwendung.
- Pfade mit einer Variable, die Dustbunny nicht auflösen kann (`${DATA}/sonarr`), schützen trotzdem einen
  Ordner mit diesem Namen.

| Kategorie | Bedeutung |
|---|---|
| **Aktiv** | von einem laufenden Container verwendet |
| **Gestoppt** | nur von gestoppten Containern verwendet |
| **Nur definiert** | steht noch in einer Stack- oder Compose-Datei, aber es gibt keinen Container |
| **Verwaist** | nichts verweist darauf |
| **Ignoriert** | Ignorier-Regel, in der Oberfläche ignoriert, symbolischer Link oder Systemordner |

Im Zweifel zählt ein Ordner als verwendet: Ein übersehener verwaister Ordner kostet etwas Platz, ein
fälschlich als verwaist gemeldeter Ordner könnte Daten kosten.

## Installation mit Docker / Portainer

Das Image gibt es für `amd64` und `arm64`: `ghcr.io/jake-double-one/dustbunny:latest`.

**Portainer:** *Stacks → Add stack → Web editor*, [`docker-compose.yml`](docker-compose.yml) einfügen, die
mit `←` markierten Zeilen anpassen, *Deploy the stack*. Oder *Repository* mit
`https://github.com/Jake-double-one/dustbunny` und dem Compose-Pfad `docker-compose.yml`.

**Kommandozeile:**

```sh
curl -O https://raw.githubusercontent.com/Jake-double-one/dustbunny/main/docker-compose.yml
# SCAN_ROOTS und die Volume-Zeilen anpassen, dann:
docker compose up -d
```

Dann `http://<host>:8077` öffnen. Der erste Scan startet sofort.

> [!IMPORTANT]
> **Binde deine Appdata unter genau demselben Pfad ein wie auf dem Host.** Docker meldet Host-Pfade, also
> muss `/opt/appdata` auch im Container `/opt/appdata` sein:
>
> ```yaml
> volumes:
>   - /opt/appdata:/opt/appdata:ro   # richtig
>   # - /opt/appdata:/appdata:ro     # falsch: jeder Ordner sähe verwaist aus
> ```
>
> Geht das nicht (z. B. Unraid `/mnt/user` gegenüber `/mnt/cache` oder ein Ordner hinter einem Symlink),
> setze `PATH_ALIASES=/host/pfad=/container/pfad`. Dustbunny warnt, wenn nichts in ein Scan-Verzeichnis zeigt.

Die Compose-Datei enthält zwei Dienste:

- **dustbunny** – läuft als root *ohne jede Fähigkeit außer Lesen* (`DAC_READ_SEARCH`), mit schreibgeschütztem
  Dateisystem, schreibgeschützten Appdata-Mounts und `no-new-privileges`.
- **socket-proxy** – lässt Dustbunny Container und Volumes auflisten, sonst nichts. Den Docker-Socket selbst
  sieht Dustbunny nie.

## Einstellungen

Alle Einstellungen sind Umgebungsvariablen. Die vollständige Tabelle mit allen Standardwerten steht in der
[englischen README](README.md#configuration); die wichtigsten:

| Variable | Beschreibung |
|---|---|
| `SCAN_ROOTS` | **Pflicht.** Appdata-Ordner, kommagetrennt. Jeden unter demselben Pfad einbinden. |
| `IGNORE` | Zu überspringende Ordner: Namen oder Pfade, Globs erlaubt (`backup-*,/opt/appdata/behalten`) |
| `PATH_ALIASES` | Pfad-Übersetzungen `HOST=LOKAL`, kommagetrennt |
| `SCAN_INTERVAL` | `30m`, `6h` (Standard), `1d` … `0` = nur auf Knopfdruck |
| `PORTAINER_URL`, `PORTAINER_API_KEY` | Portainer-Adresse und Zugriffstoken (*My account → Access tokens*) |
| `PORTAINER_ENDPOINT_ID` | Nur Stacks dieser Umgebung (die Zahl in ihrer Portainer-Adresse) |
| `PORTAINER_INSECURE` | `true` bei selbstsigniertem Zertifikat |
| `COMPOSE_DIRS` | Ordner mit einem Stack pro Unterordner |
| `NOTIFY_URLS`, `NOTIFY_ON`, `NOTIFY_LANGUAGE` | Apprise-URLs, `change` oder `always`, `en` oder `de` |
| `AUTH_USER` / `AUTH_PASSWORD` | Passwort für die Oberfläche. Empfohlen, wenn andere sie erreichen können. |

## Quellen

**Docker:** Alle Container, laufende und gestoppte, mit Bind-Mounts, an Host-Ordner gebundenen Named Volumes
und den Compose-Labels. Der Socket-Proxy braucht `CONTAINERS=1` und `VOLUMES=1`.

**Portainer:** Nötig, wenn du Stacks in Portainer stoppst: Portainer entfernt dabei die Container, dann sagt
nur noch die Stack-Datei, dass die Daten gebraucht werden. Mehrere Hosts in einem Portainer: setze
`PORTAINER_ENDPOINT_ID` auf den Host, auf dem Dustbunny läuft.

**Compose-Ordner:** Für Dockge, Komodo oder reines `docker compose`: `COMPOSE_DIRS=/opt/stacks` liest
Compose-Dateien in diesem Ordner und in jedem Unterordner. Unter demselben Pfad einbinden, damit relative
Pfade (`./config`) stimmen.

## Benachrichtigungen

`NOTIFY_URLS` mit einer oder mehreren [Apprise-URLs](https://github.com/caronc/apprise/wiki), z. B.
`ntfy://ntfy.sh/mein-thema`. Die Nachricht nennt neu verwaiste Ordner mit Größe und Ordner, die nicht mehr
verwaist sind. Unvollständige Ergebnisse benachrichtigen nie.

## Ordnergrößen und Rechte

Appdata-Ordner gehören oft verschiedenen Benutzern und sind für andere nicht lesbar (`700`).

- **Standard in `docker-compose.yml`:** `user: "0:0"` mit `cap_drop: ALL` und nur `cap_add: DAC_READ_SEARCH`.
  Dieser root kann jede Datei lesen, aber nirgends schreiben außer in `/data`.
- **Ohne root:** die Zeilen `user` und `cap_add` entfernen. Dustbunny läuft dann als uid 1000; Größen fremder
  Ordner sind als unvollständig markiert, die Erkennung selbst ist davon nicht betroffen.

## Skins

Wähle einen Skin mit den Farbfeldern oben rechts; die Wahl merkt sich der Browser. Eingebaut: *Dunkel*,
*AMOLED*, *Hell*, *Mango*. Eigene Skins: eine CSS-Datei nach `/data/skins` legen – sie erscheint nach wenigen
Sekunden. Das Format (dasselbe wie bei ShopWiz und im Feierabend-Designsystem) steht in
[`src/dustbunny/skins/README.md`](src/dustbunny/skins/README.md).

## Sprachen

Oberfläche und Benachrichtigungen gibt es auf Englisch und Deutsch. **Neue Sprache:**
[`src/dustbunny/locales/en.json`](src/dustbunny/locales/en.json) nach `<code>.json` kopieren, Werte
übersetzen, `language.name` setzen – sie erscheint automatisch im Sprachmenü. `pytest` prüft, dass alle
Schlüssel und `{Platzhalter}` vorhanden sind. Die Begriffe erklärt [`docs/glossary.md`](docs/glossary.md).

## API und Kommandozeile

`GET /api/report` liefert den letzten Bericht als JSON, `POST /api/scan` startet einen Scan,
`GET /healthz` ist der Gesundheitscheck. `dustbunny --once --json` macht einen einzelnen Scan ohne Webserver.
Details in der [englischen README](README.md#api-and-command-line).

## Entwicklung

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest
```

## Lizenz

MIT. Schriften: IBM Plex Mono und Instrument Sans unter der SIL Open Font License.
