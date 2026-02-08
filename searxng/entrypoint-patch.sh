#!/bin/sh
# Remove stale .pyc files for custom engines mounted via volume
# This runs before SearXNG starts to ensure volume-mounted .py files take effect
rm -f /usr/local/searxng/searx/engines/__pycache__/reddit.cpython-*.pyc 2>/dev/null
# Execute original entrypoint
exec /sbin/tini -- /usr/local/searxng/dockerfiles/docker-entrypoint.sh "$@"
