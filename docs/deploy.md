# Deploying Nightwatch

**Live as of 2026-09-12:** the desk is at https://nightwatch-gules.vercel.app (Vercel,
project `nightwatch`, root directory `web`, connected to the `main` branch so every push
redeploys). The backend runs on an AWS Lightsail box in Mumbai (ap-south-1), 1 GB plan,
static IP, port 8000 open, with the API and the recorder as containers. Measured there:
API 230 MB of memory with all 24 tokens warm, a full verdict in 1.5 s, the calibration
page in 1.3 s.

Three processes, one SQLite database:

| process | what it does | must be always-on? |
|---|---|---|
| `api` | FastAPI on :8000. Analysis, calibration, chat. | yes: the judges open the demo here |
| `recorder` | Snapshots order books every 60 s, refreshes hourly bars every 15 min, calendars every 6 h, news every 30 min, scores matured tickets every 15 min. | yes: without it exit-cost history and calibration stop growing |
| `web` | Next.js desk on :3000. Static shell; every number comes from the API. | yes |

The database is a single file (`nightwatch.sqlite`, ~190 MB with 24 tokens of hourly
history from Jan 2025). SQLite in WAL mode is safe for one writer (the recorder) plus
readers (the API) on the same filesystem. Do **not** put the file on a network share.

## Recommended: web on Vercel, backend on one small box

The desk is a Next.js app and belongs on Vercel. The API and the recorder cannot live
there: Vercel functions run on a read-only filesystem that is thrown away between calls
and stop after 300 seconds, while the recorder writes to a SQLite file every minute and
must stay alive for weeks. So the backend gets one small always-on machine.

The browser never calls that machine directly. The desk ships a same-origin proxy at
`/api` (`web/src/app/api/[...path]/route.ts`) which forwards to
`NIGHTWATCH_API_ORIGIN` server-side. That is what makes a plain-http backend usable from
an https page without buying a domain or installing a certificate.

### A. The backend on AWS Lightsail (about $12/month, prorated)

Lightsail is the simplest thing AWS sells: a fixed-price Linux box with a static IP and a
firewall in one screen. The $12 plan is 4 GB of memory, 2 vCPUs and 80 GB of disk, which
is the comfortable size for this workload. A new AWS account currently gets $100 of
credits immediately and up to $200 over six months, which covers the judging window.

1. Lightsail console -> **Create instance** -> Linux/Unix -> OS only -> **Ubuntu 24.04**
   -> the **$12** plan -> name it `nightwatch` -> Create.
2. **Networking** tab -> **Attach static IP** (free while attached to a running instance).
3. **Networking** -> IPv4 Firewall -> **Add rule** -> Custom, TCP, port **8000**. Leave
   SSH as it is.
4. **Connect using SSH** (the browser button works), then:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/deploy/lightsail-setup.sh      | bash -s -- https://github.com/<owner>/<repo>.git
   ```

   (The repository is private, so either make it public first, clone it with a personal
   access token, or copy the folder up with `scp` and run `bash deploy/lightsail-setup.sh`.)

   The script installs Docker, builds the images and starts the API and the recorder. It
   prints the two ways to give it data: copy an existing `nightwatch.sqlite`, or backfill
   from the public APIs on the box. Start only what the box needs:
   `docker compose up -d api recorder`. A plain `docker compose up -d` would also start
   the web desk, which belongs on Vercel and only wastes memory here.
5. Check it: `curl -s localhost:8000/health`, and from your own machine
   `curl -s http://<static-ip>:8000/health`.

EC2 works the same way if you prefer it: t4g.small or larger, Ubuntu 24.04, security
group open on 8000, then run the same script.

### B. The desk on Vercel

1. Import the repository, set **Root Directory** to `web`. The framework preset is
   Next.js; nothing else needs changing.
2. Environment variables:
   * `NIGHTWATCH_API_ORIGIN` = `http://<static-ip>:8000` (server-side only, never
     reaches the browser)
   * `NEXT_PUBLIC_API_URL` = `/api`
3. Deploy. Open the URL and check the status pill in the header: it shows the token count
   and the age of the last order-book snapshot.

If the pill says the API is offline, the backend is unreachable: check the firewall rule
and that `docker compose ps` shows both containers up.

### C. Everything on one box instead (no Vercel)

`docker compose up -d` starts the web desk too, on port 3000. Put Caddy in front if you
have a domain:

```
desk.example.com { reverse_proxy localhost:3000 }
api.example.com  { reverse_proxy localhost:8000 }
```

and rebuild the web image with `NEXT_PUBLIC_API_URL=https://api.example.com`.

## Appendix: the same thing on any other VPS

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

## Environment variables

| name | default | meaning |
|---|---|---|
| `NIGHTWATCH_DATA_DIR` | `./data` | where the SQLite file lives |
| `NIGHTWATCH_CORS` | `*` | comma-separated allowed origins for the API |
| `NIGHTWATCH_LIVE_BOOK` | `1` | `0` disables live order-book fetches in the API (offline demo) |
| `ANTHROPIC_API_KEY` | unset | enables the `/chat` language layer; everything else works without it |
| `FRED_API_KEY` | unset | optional; FRED works unauthenticated for the CSV endpoints used |
| `NEXT_PUBLIC_API_URL` | `/api` when the page is not on localhost | where the browser sends API calls; `/api` uses the same-origin proxy |
| `NIGHTWATCH_API_ORIGIN` | unset | where that proxy forwards to, e.g. `http://12.34.56.78:8000`. Server-side only |

## How changes reach production

Both halves deploy on a push to `main`, and neither needs a key stored anywhere:

* **The desk**: Vercel is connected to the repository and builds every push.
* **The backend**: the box runs `deploy/autodeploy.sh` from cron every five minutes. It
  fetches `main`, and deploys only if that commit's CI run passed. If the new build fails
  its health check within two minutes it rolls back to the previous commit by itself.
  The log is `/home/ubuntu/autodeploy.log`.

To deploy immediately instead of waiting for the tick:

```bash
ssh ubuntu@<ip> /home/ubuntu/nightwatch/deploy/autodeploy.sh
```

## Health and uptime

* `GET /health` returns bar count, order-book snapshot count, the timestamp of the last
  book, and the warm-up state. Point any uptime monitor at it.
* `GET /sources` lists every upstream feed with when it was last pulled, how many rows it
  holds and the newest thing in it. It is the fastest way to tell a dead feed from a quiet
  market, and the desk shows the same six rows in its sidebar.
* **Self-healing**: `deploy/heal.sh` runs from cron every five minutes and restarts a
  container that is running but unhealthy - a wedged API, or a recorder that has not
  written an order book in five minutes. Docker's restart policy only covers a process
  that exits. The log is `/home/ubuntu/heal.log`, and it stays empty while all is well.
* The recorder logs a heartbeat every 10 ticks and every job run; `docker compose logs -f recorder`.
* The API warms the feature frames for every token on start (about a minute for 24
  tokens); until then `/health` reports `warm.state = running` and analyses are slower.

## Checklist before the judging window (2026-09-22 to 2026-10-07)

1. `/health` reachable over HTTPS from a phone network.
2. Recorder heartbeat advancing; `last_book_ts` in `/health` within the last 2 minutes.
3. A TSLA ticket on the desk returns a verdict in under 5 s after warm-up.
4. Calibration page shows matured forecasts and the tail-adjustment table.
5. Uptime monitor on `/health` with an alert to a phone.
