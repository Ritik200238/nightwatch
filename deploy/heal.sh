#!/usr/bin/env bash
# Restart a container that has gone unhealthy.
#
# Docker's restart policy covers a process that exits. It does not cover one that is
# still running and no longer working: a wedged HTTP server, or a recorder that has
# stopped writing order books. Both containers already declare what healthy means, and
# this turns that declaration into an action.
#
# Judging runs for two weeks with nobody watching, so the failure this guards against is
# the demo being quietly dead for a day. Runs from cron every five minutes, next to the
# autodeploy job; it does nothing at all when everything is healthy.
set -uo pipefail

cd /home/ubuntu/nightwatch || exit 1
LOG=/home/ubuntu/heal.log
say() { echo "$(date -u +%FT%TZ) $*" >> "$LOG"; }

# One restart per run. If two containers are unwell, the next tick takes the second.
for service in api recorder; do
  cid=$(docker compose ps -q "$service" 2>/dev/null)
  [ -z "$cid" ] && continue
  state=$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null)
  health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null)

  if [ "$state" != "running" ]; then
    say "$service is $state; starting it"
    docker compose up -d "$service" >> "$LOG" 2>&1
    exit 0
  fi

  if [ "$health" = "unhealthy" ]; then
    # Say why, so the log explains itself later.
    reason=$(docker inspect --format '{{range .State.Health.Log}}{{.Output}}{{end}}' "$cid" 2>/dev/null | tail -c 200 | tr '\n' ' ')
    say "$service unhealthy, restarting. last check said: ${reason:-nothing}"
    docker compose restart "$service" >> "$LOG" 2>&1
    exit 0
  fi
done
exit 0
