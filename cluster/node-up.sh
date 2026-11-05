#!/usr/bin/env bash
# Start (or update) this machine as a search cluster node. Run from the repo root on the node:
#   printf '%s' "$TUNNEL_TOKEN" | cluster/node-up.sh      # first time: token on stdin
#   cluster/node-up.sh                                     # later: reuses cluster/node.env
# Needs docker with compose >= 2.24. Without a config.yaml it renders one from config.example.yaml
# (fresh secret, engines that need a key disabled) with the python inside the SearXNG image, so
# the node needs no python packages of its own.
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
git pull --ff-only -q || echo "git pull failed, starting the checked-out version" >&2
if [ ! -s config.yaml ]; then
  echo "no config.yaml: rendering one from config.example.yaml" >&2
  docker run --rm -v "$PWD:/w:ro" --entrypoint /usr/local/searxng/.venv/bin/python3 \
    docker.io/searxng/searxng:latest /w/cluster/render-node-config.py /w/config.example.yaml > config.yaml.tmp
  mv config.yaml.tmp config.yaml
fi
chmod 644 config.yaml  # the searxng container reads it as another user
docker compose -f docker-compose.yaml -f cluster/node.override.yaml --env-file "$ENV" \
  --profile cloudflare up -d --build --wait --wait-timeout 120 \
  redis searxng tavily-adapter searxng-mcp cloudflared
echo "node up: services healthy, tunnel connector started"
