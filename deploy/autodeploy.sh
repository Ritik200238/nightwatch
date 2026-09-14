#!/usr/bin/env bash
# Ship the backend the same way the desk ships: a push to main reaches production.
#
# Runs on the box from cron every few minutes. It only deploys a commit whose CI run
# passed, so a broken push cannot reach the live demo, and it rolls back by itself if the
# new build fails its health check. Nothing here needs a key or an inbound connection:
# the box pulls, GitHub is never asked to push.
#
#   */5 * * * * /home/ubuntu/nightwatch/deploy/autodeploy.sh >> /home/ubuntu/autodeploy.log 2>&1
set -uo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/nightwatch}"
REPO="${REPO:-Ritik200238/nightwatch}"
BRANCH="${BRANCH:-main}"
HEALTH="http://127.0.0.1:8000/health"
LOCK="/tmp/nightwatch-autodeploy.lock"

say() { printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }

# One deploy at a time: a slow build must not overlap the next cron tick.
exec 9>"$LOCK"
flock -n 9 || { say "another deploy is running; skipping"; exit 0; }

cd "$APP_DIR" || { say "no $APP_DIR"; exit 1; }

git fetch --quiet origin "$BRANCH" || { say "fetch failed"; exit 1; }
local_sha=$(git rev-parse HEAD)
remote_sha=$(git rev-parse "origin/$BRANCH")
[ "$local_sha" = "$remote_sha" ] && exit 0

say "new commit ${remote_sha:0:8}: $(git log -1 --format=%s "origin/$BRANCH")"

# Only deploy what CI accepted. A public repo answers this without a token.
conclusion=$(curl -fsSL --max-time 30 \
  "https://api.github.com/repos/$REPO/commits/$remote_sha/check-runs" \
  | python3 -c "
import json, sys
runs = json.load(sys.stdin).get('check_runs', [])
ci = [r for r in runs if r['name'] in ('python', 'web')]
if not ci:
    print('pending'); raise SystemExit
if any(r['status'] != 'completed' for r in ci):
    print('pending')
elif all(r['conclusion'] == 'success' for r in ci):
    print('success')
else:
    print('failure')
" 2>/dev/null)

case "$conclusion" in
  success) ;;
  pending) say "CI still running; will retry next tick"; exit 0 ;;
  failure) say "CI failed on ${remote_sha:0:8}; refusing to deploy"; exit 0 ;;
  *)       say "could not read CI status; refusing to deploy"; exit 0 ;;
esac

say "deploying ${remote_sha:0:8}"
# --force on purpose: this box is a deploy target, not a workspace. The repository is
# the only source of truth for what runs here, and a stray local edit (even a file mode)
# must not be able to wedge every future deploy. Untracked files, .env included, survive.
git -c advice.detachedHead=false checkout --quiet --force "$remote_sha" || { say "checkout failed"; exit 1; }

if ! docker compose build api; then
  say "build failed; rolling back to ${local_sha:0:8}"
  git checkout --quiet "$local_sha"
  exit 1
fi

docker compose up -d api recorder

# The API rebuilds its feature cache on boot; give it a minute before judging it.
for _ in $(seq 1 24); do
  sleep 5
  if curl -fsS --max-time 10 "$HEALTH" | grep -q '"ok":true'; then
    say "healthy on ${remote_sha:0:8}"
    docker image prune -f >/dev/null 2>&1
    # Every build leaves layers behind. Unchecked over a three-week judging window they
    # are the most likely thing to fill a 40 GB disk and take the demo down; 2 GB is
    # enough to keep the next build fast.
    docker builder prune -f --keep-storage 2GB >/dev/null 2>&1
    say "disk $(df -h / | awk 'NR==2 {print $5" used, "$4" free"}')"
    exit 0
  fi
done

say "unhealthy after two minutes; rolling back to ${local_sha:0:8}"
git checkout --quiet "$local_sha"
docker compose build api && docker compose up -d api recorder
exit 1
