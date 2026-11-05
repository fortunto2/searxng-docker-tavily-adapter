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
  cluster/guard.py status     streak, eviction, other connected replicas, last moves
  SEARCH_GUARD_KEYCHAIN=<item> cluster/guard.py install    launchd agent (macOS)
  cluster/guard.py uninstall

<item> is a Keychain entry holding a Cloudflare API token that can read tunnels. The
account and tunnel come from the container's own tunnel token.
"""
from __future__ import annotations

import base64
import json
import os
import plistlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONTAINER = "searxng-cloudflared"
PROBE = "https://www.google.com/generate_204"
READY = "http://127.0.0.1:8081/ready"
SLOW = 1.5  # seconds for one HTTPS request; a healthy line answers in 0.2-0.5
N = 3  # checks in a row before acting
STATE = Path.home() / ".local/state/search-guard"
LABEL = "org.searxng-cluster.guard"
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def keychain_item() -> str:
    """From the env (install, launchd) or the installed plist (status from a shell)."""
    if os.environ.get("SEARCH_GUARD_KEYCHAIN"):
        return os.environ["SEARCH_GUARD_KEYCHAIN"]
    try:
        return plistlib.loads(PLIST.read_bytes())["EnvironmentVariables"]["SEARCH_GUARD_KEYCHAIN"]
    except Exception:
        return ""


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


def container() -> tuple[bool, tuple[str, str] | None]:
    """(running, (account, tunnel)) of the cloudflared container; None when there is none."""
    r = sh("docker", "inspect", CONTAINER)
    if r.returncode != 0:
        return False, None
    info = json.loads(r.stdout)[0]
    words = (info["Config"].get("Cmd") or []) + [e.split("=", 1)[-1] for e in info["Config"].get("Env") or []]
    token = next((w for w in words if w.startswith("eyJ")), "")
    if not token:
        return bool(info["State"]["Running"]), None
    meta = json.loads(base64.b64decode(token + "=" * (-len(token) % 4)))
    return bool(info["State"]["Running"]), (meta["a"], meta["t"])


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


def others(tunnel: tuple[str, str], own: list[str], running: bool) -> int | None:
    """Connectors on the tunnel that are not this node, None when the API cannot be read.

    Our own past connector ids are excluded: right after a restart the dead one is still
    listed for a while and once passed for "another replica" (04.11.2026). While running
    with no known id of ours among them, one of the listed ones is assumed to be us.
    """
    try:
        api_token = sh("security", "find-generic-password", "-s", keychain_item(), "-w").stdout.strip()
        req = urllib.request.Request(
            f"https://api.cloudflare.com/client/v4/accounts/{tunnel[0]}/cfd_tunnel/{tunnel[1]}",
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
        return {}


def save(st: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "state.json").write_text(json.dumps(st))


def log(msg: str) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / "guard.log", "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def restart_if_dead(st: dict, alive: bool | None) -> bool:
    # A network switch (VPN on/off, new wifi) can leave cloudflared running with no
    # connection and not recovering for minutes (seen 04.11.2026). A restart re-registers.
    st["dead"] = st.get("dead", 0) + 1 if alive is False else 0
    if st["dead"] < 2 or sh("docker", "restart", CONTAINER).returncode != 0:
        return False
    st["dead"] = 0
    log("restarted cloudflared: running but no tunnel connection for 2 checks")
    return True


def leave_if_slow(st: dict, tunnel: tuple[str, str], secs: float) -> None:
    if st["streak"] > -N:
        return
    n = others(tunnel, st["own"], running=True)
    if n and sh("docker", "stop", CONTAINER).returncode == 0:
        st["evicted"] = True
        log(f"left the pool: {-st['streak']} slow checks, last {secs:.1f}s, {n} other replica(s) serve")


def rejoin_if_good_or_alone(st: dict, tunnel: tuple[str, str], secs: float) -> None:
    good = st["streak"] >= N
    if not good and others(tunnel, st["own"], running=False) != 0:
        return
    if sh("docker", "start", CONTAINER).returncode == 0:
        st["evicted"] = False
        why = f"{st['streak']} good checks" if good else "no other replica left"
        log(f"back in the pool: {why}, last {secs:.1f}s")


def check() -> int:
    st = load()
    st.setdefault("own", [])
    secs = probe()
    # One signed streak: +k after k good checks in a row, -k after k slow ones.
    prev = st.get("streak", 0)
    st["streak"] = (min(prev, 0) - 1) if secs > SLOW else (max(prev, 0) + 1)
    st["last_probe_s"] = round(secs, 2)
    running, tunnel = container()
    if tunnel is None:
        save(st)
        return 0
    if running:
        alive, cid = ready()
        if cid and cid not in st["own"]:
            st["own"] = (st["own"] + [cid])[-5:]
        if not restart_if_dead(st, alive):
            leave_if_slow(st, tunnel, secs)
    elif st.get("evicted"):  # a container stopped by hand is left alone
        rejoin_if_good_or_alone(st, tunnel, secs)
    save(st)
    return 0


def install() -> int:
    if not keychain_item():
        print("set SEARCH_GUARD_KEYCHAIN to the Keychain item with a Cloudflare API token")
        return 2
    STATE.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": ["/usr/bin/python3", str(Path(__file__).resolve())],
        "StartInterval": 60,
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "SEARCH_GUARD_KEYCHAIN": keychain_item(),
        },
        "StandardErrorPath": str(STATE / "stderr.log"),
    }))
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
    running, tunnel = container()
    n = others(tunnel, st.get("own", []), running) if tunnel else None
    print(json.dumps({**st, "running_now": running, "other_replicas_now": n}, indent=1))
    log_file = STATE / "guard.log"
    if log_file.exists():
        print("".join(log_file.read_text().splitlines(True)[-5:]), end="")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    sys.exit({"check": check, "status": status, "install": install, "uninstall": uninstall}.get(cmd, lambda: print(__doc__) or 2)())
