#!/usr/bin/env python3
"""Take this node out of the search tunnel's pool while its uplink is bad.

Every node of the cluster is a replica of one Cloudflare tunnel, and Cloudflare sends a
request to the geographically closest replica whether or not that node's internet is
any good. A laptop on hotel wifi stays connected and answers in 10 s. This guard asks
the node itself: one HTTPS request to PROBE, timed. After N slow checks in a row it
stops the node's cloudflared container, but only while another replica is connected,
so the cluster never goes dark because of it. It starts the container again after N
good checks, or at once when no other replica is left (slow beats nothing). It also
restarts the container when cloudflared runs but holds no tunnel connection for two
checks in a row (its /ready metrics endpoint, published on 127.0.0.1:8081).

  cluster/guard.py            one check; launchd runs it every 60 s
  cluster/guard.py status     last check, streaks, connected replicas
  cluster/guard.py install    write and load the launchd agent (macOS)
  cluster/guard.py uninstall

Settings (env): SEARCH_GUARD_KEYCHAIN (Keychain item holding a Cloudflare API token
that can read tunnels, default cloudflare-api-token), SEARCH_GUARD_CONTAINER
(searxng-cloudflared), SEARCH_GUARD_PROBE, SEARCH_GUARD_SLOW (seconds, 1.5),
SEARCH_GUARD_N (3). The tunnel and account are read from the container's own token.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONTAINER = os.environ.get("SEARCH_GUARD_CONTAINER", "searxng-cloudflared")

PROBE = os.environ.get("SEARCH_GUARD_PROBE", "https://www.google.com/generate_204")
SLOW = float(os.environ.get("SEARCH_GUARD_SLOW", "1.5"))
N = int(os.environ.get("SEARCH_GUARD_N", "3"))
READY = os.environ.get("SEARCH_GUARD_READY", "http://127.0.0.1:8081/ready")
STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "search-guard"
LABEL = "org.searxng-cluster.guard"
# install remembers the Keychain item, so `status` from a shell finds it without the env var.
_saved = STATE / "keychain"
KEYCHAIN = os.environ.get("SEARCH_GUARD_KEYCHAIN") or (_saved.read_text().strip() if _saved.exists() else "cloudflare-api-token")
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def sh(*cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def probe() -> float:
    """Seconds for one HTTPS request, 99 on failure."""
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(PROBE, timeout=8) as r:
            r.read(1)
    except Exception:
        return 99.0
    return time.monotonic() - t0


def container() -> tuple[bool, str]:
    """(running, tunnel token) of the cloudflared container."""
    r = sh("docker", "inspect", CONTAINER)
    if r.returncode != 0:
        return False, ""
    info = json.loads(r.stdout)[0]
    words = (info["Config"].get("Cmd") or []) + [e.split("=", 1)[-1] for e in info["Config"].get("Env") or []]
    token = next((w for w in words if w.startswith("eyJ")), "")
    return bool(info["State"]["Running"]), token


def ready() -> tuple[bool | None, str]:
    """(holds a tunnel connection?, connector id) of our own cloudflared; None when its
    metrics are not reachable."""
    try:
        with urllib.request.urlopen(READY, timeout=5) as r:
            d = json.load(r)
        return d.get("readyConnections", 0) > 0, d.get("connectorId", "")
    except urllib.error.HTTPError as e:  # 503 = no connection registered
        return (False, "") if e.code == 503 else (None, "")
    except Exception:
        return None, ""


def others(token: str, own: list[str], running: bool) -> int | None:
    """Connectors on the tunnel that are not this node, None when the API cannot be read.

    Our own past connector ids are excluded: right after a restart the dead one is still
    listed for a while and once passed for "another replica" (04.11.2026). While running
    with no known id of ours among them, one of the listed ones is assumed to be us.
    """
    try:
        meta = json.loads(base64.b64decode(token + "=" * (-len(token) % 4)))
        api_token = sh("security", "find-generic-password", "-s", KEYCHAIN, "-w").stdout.strip()
        req = urllib.request.Request(
            f"https://api.cloudflare.com/client/v4/accounts/{meta['a']}/cfd_tunnel/{meta['t']}",
            headers={"Authorization": f"Bearer {api_token}"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            ids = {c["client_id"] for c in json.load(r)["result"]["connections"]}
    except Exception:
        return None
    n = len(ids - set(own))
    if running and not ids & set(own):
        n = max(n - 1, 0)
    return n


def load() -> dict:
    try:
        return json.loads((STATE / "state.json").read_text())
    except Exception:
        return {"bad": 0, "good": 0, "evicted": False}


def save(st: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "state.json").write_text(json.dumps(st))


def log(msg: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / "guard.log", "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def check() -> int:
    st = load()
    secs = probe()
    slow = secs > SLOW
    st["bad"], st["good"] = (st["bad"] + 1, 0) if slow else (0, st["good"] + 1)
    running, token = container()
    st["last"] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "probe_s": round(secs, 2), "running": running}
    if not token:
        st["last"]["note"] = f"no container {CONTAINER}"
        save(st)
        return 0
    alive, cid = ready() if running else (None, "")
    st.setdefault("own", [])
    if cid and cid not in st["own"]:
        st["own"] = (st["own"] + [cid])[-5:]
    st["dead"] = st.get("dead", 0) + 1 if alive is False else 0
    st["last"]["ready"] = alive
    if running and st["dead"] >= 2:
        # A network switch (WARP on/off, new wifi) can leave cloudflared running with no
        # connection and not recovering for minutes (seen 04.11.2026). A restart re-registers.
        if sh("docker", "restart", CONTAINER).returncode == 0:
            st["dead"] = 0
            log("restarted cloudflared: running but no tunnel connection for 2 checks")
    elif running and st["bad"] >= N:
        n = others(token, st["own"], running=True)
        st["last"]["others"] = n
        if n is not None and n >= 1:
            if sh("docker", "stop", CONTAINER).returncode == 0:
                st["evicted"] = True
                log(f"left the pool: {st['bad']} slow checks, last {secs:.1f}s, {n} other replica(s) serve")
    elif not running and st["evicted"]:
        n = others(token, st["own"], running=False)
        st["last"]["others"] = n
        if st["good"] >= N or n == 0:
            if sh("docker", "start", CONTAINER).returncode == 0:
                st["evicted"] = False
                why = f"{st['good']} good checks" if st["good"] >= N else "no other replica left"
                log(f"back in the pool: {why}, last {secs:.1f}s")
    save(st)
    return 0


def install() -> int:
    path = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    PLIST.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>{Path(__file__).resolve()}</string></array>
  <key>StartInterval</key><integer>60</integer>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>{path}</string>
    <key>SEARCH_GUARD_KEYCHAIN</key><string>{KEYCHAIN}</string>
  </dict>
  <key>StandardErrorPath</key><string>{STATE}/stderr.log</string>
</dict></plist>
""")
    STATE.mkdir(parents=True, exist_ok=True)
    _saved.write_text(KEYCHAIN + "\n")
    sh("launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}")
    r = sh("launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST))
    print(f"installed {PLIST}" if r.returncode == 0 else f"launchctl: {r.stderr.strip()}")
    return r.returncode


def uninstall() -> int:
    sh("launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}")
    PLIST.unlink(missing_ok=True)
    print(f"removed {PLIST}")
    return 0


def status() -> int:
    st = load()
    running, token = container()
    n = others(token, st.get("own", []), running) if token else None
    print(json.dumps({**st, "running_now": running, "other_replicas_now": n}, indent=1))
    log_file = STATE / "guard.log"
    if log_file.exists():
        print("".join(log_file.read_text().splitlines(True)[-5:]), end="")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    sys.exit({"check": check, "status": status, "install": install, "uninstall": uninstall}.get(cmd, lambda: print(__doc__) or 2)())
