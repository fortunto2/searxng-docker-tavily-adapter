# Search cluster: one hostname, several home machines

Several machines on different home connections serve the same search hostname. A request
goes to the closest one that is up, and nobody changes a URL when a machine sleeps, moves
or loses its wifi.

```mermaid
flowchart LR
  A[agent near node A] --> CF{{Cloudflare edge<br/>Access + tunnel}}
  B[agent near node B] --> CF
  CF -->|closest replica| NA[node A<br/>cloudflared + SearXNG + adapter + MCP]
  CF -->|closest replica| NB[node B<br/>same compose]
  NA --> E[(search engines<br/>from A's home IP)]
  NB --> E2[(search engines<br/>from B's home IP)]
  G[guard.py on A] -. stops A's cloudflared<br/>while A's uplink is bad .-> NA
```

## How it works

- **One tunnel, N replicas.** Every node runs the same `docker-compose.yaml` and the same
  tunnel token. Cloudflare forwards each request to the geographically closest connected
  replica and retries another if that connection fails
  ([Tunnel availability](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-availability/)).
  The ingress names `http://tavily-adapter:8000` and `http://searxng-mcp:8000` resolve on
  every node because the container names are the same.
- **The MCP server is stateless** (`stateless_http=True`), so any node answers any request
  and nothing is sticky.
- **Replicas do no health steering.** A node that is connected but slow (a laptop on bad
  wifi) still gets the traffic near it. `guard.py` closes that gap from the node's side:
  after 3 slow checks it stops its own `cloudflared`, only while another replica is
  connected, and starts it again after 3 good checks or when it is the last one left.
  It also restarts `cloudflared` when the container runs but holds no tunnel connection
  for two checks: a network switch (VPN on/off, new wifi) left it like that for minutes.
  It reads that from cloudflared's `/ready`, so publish the metrics port on the node:
  `127.0.0.1:8081:8081` (`node.override.yaml` already does).
- **Each node searches from its own IP.** Engine captchas and suspensions are per node.
  Run nodes on residential connections: datacenter ranges get captchas on the first queries.

Not used, on purpose: Cloudflare Load Balancing (steers by measured latency and health, but
needs a tunnel per node and is a paid add-on) and a Worker in front (another moving part).
Move to a load balancer when guard-style self-eviction is no longer enough.

## Add a node

On the node (Linux or macOS with Docker, compose >= 2.24, a residential connection, ~400 MB RAM):

```bash
git clone https://github.com/fortunto2/searxng-docker-tavily-adapter && cd searxng-docker-tavily-adapter
security find-generic-password -s <keychain item with the tunnel token> -w | cluster/node-up.sh
```

The tunnel token comes from whoever runs the tunnel, out of band; keep it in the OS keychain
(`secret-tool` on Linux) and pipe it in, never paste it into a file in the repo. `node-up.sh`:

- renders `config.yaml` from `config.example.yaml` when there is none: a fresh
  `server.secret_key`, and every engine that needs a credential disabled (it lists them in the
  first line). It uses the python inside the SearXNG image, so the node installs nothing else;
- keeps the token in `cluster/node.env` (mode 600, gitignored), binds the local ports to
  127.0.0.1 only (Docker bypasses the host firewall), starts the five services and waits until
  they are healthy.

To give a node the main node's engine set instead of the example's, render it there and copy it:
`python3 cluster/render-node-config.py config.yaml | ssh NODE 'cat > searxng-docker-tavily-adapter/config.yaml'`.

Check that it joined: `curl -s 127.0.0.1:8081/ready` on the node shows `readyConnections` of 1 or
more, and `curl -s -X POST 127.0.0.1:8013/search -H 'Content-Type: application/json' -d '{"query":"test","max_results":3}'`
returns results. The tunnel's page in Zero Trust lists one connector per node.

Update later: `cluster/node-up.sh` again (it pulls, reuses `node.env` and `config.yaml`).

## Guard (nodes on unreliable networks)

```bash
SEARCH_GUARD_KEYCHAIN=<Keychain item with a Cloudflare API token that reads tunnels> \
  python3 cluster/guard.py install     # launchd agent, a check every 60 s
python3 cluster/guard.py status
```

Thresholds and the full behaviour are in the docstring of `guard.py`. State and the log of
moves: `~/.local/state/search-guard/`.

## Remove a node

`docker compose -f docker-compose.yaml -f cluster/node.override.yaml down` on it. The
others carry on; nothing to change in Cloudflare.
