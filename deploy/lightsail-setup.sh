#!/usr/bin/env bash
# One-shot setup for a fresh Ubuntu box (AWS Lightsail, EC2, or any VPS).
#
#   curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/deploy/lightsail-setup.sh | bash -s -- <git-url>
#
# or, after cloning:  bash deploy/lightsail-setup.sh
#
# Installs Docker, builds the images, and starts the API and the recorder. It does NOT
# seed the database; see the two options printed at the end.
set -euo pipefail

REPO_URL="${1:-}"
APP_DIR="${APP_DIR:-$HOME/nightwatch}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "Checking the machine"
free -m | awk 'NR==2 {printf "  memory: %d MB total, %d MB free\n", $2, $7}'
df -h / | awk 'NR==2 {printf "  disk:   %s free of %s\n", $4, $2}'
if [ "$(free -m | awk 'NR==2 {print $2}')" -lt 1800 ]; then
  echo "  WARNING: under 2 GB of memory. The analog engine holds several tokens of history in"
  echo "  memory at once; 4 GB is the comfortable size. Continuing anyway."
fi

say "Keeping the API in memory"
# See deploy/sysctl-nightwatch.conf for the measurement behind this.
if [ -f "$(dirname "$0")/sysctl-nightwatch.conf" ]; then
  sudo cp "$(dirname "$0")/sysctl-nightwatch.conf" /etc/sysctl.d/60-nightwatch.conf
  sudo sysctl -q -p /etc/sysctl.d/60-nightwatch.conf || true
fi

say "Installing Docker"
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq ca-certificates curl git
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" |
    sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo usermod -aG docker "$USER"
  echo "  Docker installed. Group membership applies on your next login; this script uses sudo."
fi
DOCKER="sudo docker"

say "Fetching the code"
if [ -n "$REPO_URL" ] && [ ! -d "$APP_DIR/.git" ]; then
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
[ -f .env ] || cp .env.example .env

say "Building the API image (a few minutes the first time)"
$DOCKER compose build api

say "Starting the API and the recorder"
# Only these two. The web desk goes to Vercel; running it here wastes memory.
$DOCKER compose up -d api recorder

say "Done. The API is on port 8000 of this machine."
cat <<'EOF'

Next, give it data. Either copy a database you already have:

    # from your laptop
    scp data/nightwatch.sqlite ubuntu@<ip>:/tmp/
    # on the box
    sudo docker compose run --rm -v /tmp:/src api sh -c 'cp /src/nightwatch.sqlite /data/'
    sudo docker compose restart api

or build one here from the public APIs (hours, resumable):

    sudo docker compose run --rm api nightwatch universe
    sudo docker compose run --rm api nightwatch sync --core
    sudo docker compose run --rm api nightwatch calendars
    sudo docker compose run --rm api nightwatch news
    sudo docker compose run --rm api nightwatch replay --tickers TSLA NVDA AAPL MSFT AMZN GOOGL --max-points 100

Then check it:

    curl -s localhost:8000/health

Open port 8000 in the cloud firewall (Lightsail: Networking -> IPv4 Firewall -> Add rule,
Custom TCP 8000), and point the Vercel project's NIGHTWATCH_API_ORIGIN at
http://<static-ip>:8000.

Watch it with:  sudo docker compose logs -f recorder
EOF
