#!/usr/bin/env python3
"""Render a node's config.yaml from the main node's one.

  python3 cluster/render-node-config.py config.yaml > /path/for/node/config.yaml

A node gets the same engines and routing, minus what is personal to the main node:
a fresh server.secret_key, and every engine credential (api_token, api_key other than
"public", client_id, client_secret, token) removed, with that engine disabled.
"""
import secrets
import sys

import yaml

CRED_KEYS = ("api_token", "api_key", "client_id", "client_secret", "token")


def main() -> int:
    with open(sys.argv[1]) as f:
        cfg = yaml.safe_load(f)
    cfg["server"]["secret_key"] = secrets.token_hex(32)
    dropped = []
    for eng in cfg.get("engines", []):
        creds = [k for k in CRED_KEYS if k in eng and eng[k] not in ("public", "", None)]
        if creds:
            for k in creds:
                del eng[k]
            eng["disabled"] = True
            dropped.append(eng["name"])
    print(f"# rendered by cluster/render-node-config.py; disabled (no creds): {', '.join(dropped) or 'none'}")
    yaml.safe_dump(cfg, sys.stdout, sort_keys=False, allow_unicode=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
