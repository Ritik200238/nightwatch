#!/usr/bin/env bash
# Keep the public demo warm.
#
# The desk is a Vercel function. Left idle it is torn down, and the next visitor pays a
# cold start: measured at eleven seconds against under two for a warm one. That first
# click is the one a judge makes, so it is the one worth paying for.
#
# The box is already awake all the time, so it does the pinging. One request every few
# minutes keeps the function resident and costs nothing worth counting; every route under
# /api is the same function, so warming health warms an analysis too.
set -uo pipefail
curl -fsS --max-time 20 "https://nightwatch-gules.vercel.app/api/health" >/dev/null 2>&1
exit 0
