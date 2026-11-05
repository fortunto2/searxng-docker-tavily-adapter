#!/usr/bin/env bash
# Start (or update) this machine as a search cluster node. Run from the repo root on the node:
#   printf '%s' "$TUNNEL_TOKEN" | cluster/node-up.sh      # first time: token on stdin
#   cluster/node-up.sh                                     # later: reuses cluster/node.env
# Needs docker with compose >= 2.24 and config.yaml rendered by cluster/render-node-config.py.
set -euo pipefail
cd "$(dirname "$0")/.."
ENV=cluster/node.env
if [ ! -t 0 ]; then
  tok=$(cat)
  if [ -n "$tok" ]; then
    umask 077
    printf 'CLOUDFLARE_TUNNEL_TOKEN=%s\n' "$tok" > "$ENV"
  fi
fi
[ -s "$ENV" ] || { echo "no $ENV: pipe the tunnel token on stdin" >&2; exit 2; }
[ -s config.yaml ] || { echo "no config.yaml: render it with cluster/render-node-config.py" >&2; exit 2; }
git pull --ff-only -q || echo "git pull failed, starting the checked-out version" >&2
docker compose -f docker-compose.yaml -f cluster/node.override.yaml --env-file "$ENV" \
  --profile cloudflare up -d --build redis searxng tavily-adapter searxng-mcp cloudflared
for _ in $(seq 1 30); do
  if curl -fsS -m 5 http://127.0.0.1:8013/health >/dev/null 2>&1; then
    echo "node up: adapter healthy, tunnel connector started"; exit 0
  fi
  sleep 2
done
echo "adapter did not report healthy in 60s: docker compose logs tavily-adapter" >&2
exit 1
