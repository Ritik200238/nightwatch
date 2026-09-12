# Deploying Nightwatch

Three processes, one SQLite database:

| process | what it does | must be always-on? |
|---|---|---|
| `api` | FastAPI on :8000. Analysis, calibration, chat. | yes: the judges open the demo here |
| `recorder` | Snapshots order books every 60 s, refreshes hourly bars every 15 min, calendars every 6 h, news every 30 min, scores matured tickets every 15 min. | yes: without it exit-cost history and calibration stop growing |
| `web` | Next.js desk on :3000. Static shell; every number comes from the API. | yes |

The database is a single file (`nightwatch.sqlite`, ~190 MB with 24 tokens of hourly
history from Jan 2025). SQLite in WAL mode is safe for one writer (the recorder) plus
readers (the API) on the same filesystem. Do **not** put the file on a network share.

## Option A: one VM with Docker Compose (recommended)

Any 2 vCPU / 4 GB box works. Ubuntu 24.04 commands:

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
git clone <repo> nightwatch && cd nightwatch
cp .env.example .env            # set ANTHROPIC_API_KEY, NEXT_PUBLIC_API_URL
docker compose build
```

Seed the database. Either copy an existing one (minutes):

```bash
docker volume create nightwatch_nightwatch-data
docker run --rm -v nightwatch_nightwatch-data:/data -v "$PWD/data:/src" alpine \
  sh -c "cp /src/nightwatch.sqlite /data/ && chown 10001:10001 /data/nightwatch.sqlite"
```

or backfill from the public APIs (hours; resumable):

```bash
docker compose run --rm api nightwatch sync --core
docker compose run --rm api nightwatch calendars
docker compose run --rm api nightwatch news
```

Then:

```bash
docker compose up -d
curl -s localhost:8000/health
```

Put a TLS reverse proxy in front (Caddy is two lines):

```
api.example.com  { reverse_proxy localhost:8000 }
desk.example.com { reverse_proxy localhost:3000 }
```

and rebuild `web` with `NEXT_PUBLIC_API_URL=https://api.example.com` (it is baked in at
build time).

## Option B: web on Vercel, API + recorder on a VM

`web/` deploys to Vercel unchanged (framework preset: Next.js, root directory `web`).
Set the environment variable `NEXT_PUBLIC_API_URL` to the public API URL. The API must
then allow that origin: set `NIGHTWATCH_CORS=https://<your-app>.vercel.app` on the VM.

## Environment variables

| name | default | meaning |
|---|---|---|
| `NIGHTWATCH_DATA_DIR` | `./data` | where the SQLite file lives |
| `NIGHTWATCH_CORS` | `*` | comma-separated allowed origins for the API |
| `NIGHTWATCH_LIVE_BOOK` | `1` | `0` disables live order-book fetches in the API (offline demo) |
| `ANTHROPIC_API_KEY` | unset | enables the `/chat` language layer; everything else works without it |
| `FRED_API_KEY` | unset | optional; FRED works unauthenticated for the CSV endpoints used |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | API URL baked into the web build |

## Health and uptime

* `GET /health` returns bar count, order-book snapshot count, the timestamp of the last
  book, and the warm-up state. Point any uptime monitor at it.
* The recorder logs a heartbeat every 10 ticks and every job run; `docker compose logs -f recorder`.
* The API warms the feature frames for every token on start (about a minute for 24
  tokens); until then `/health` reports `warm.state = running` and analyses are slower.

## Checklist before the judging window (2026-09-22 to 2026-10-07)

1. `/health` reachable over HTTPS from a phone network.
2. Recorder heartbeat advancing; `last_book_ts` in `/health` within the last 2 minutes.
3. A TSLA ticket on the desk returns a verdict in under 5 s after warm-up.
4. Calibration page shows matured forecasts and the tail-adjustment table.
5. Uptime monitor on `/health` with an alert to a phone.
