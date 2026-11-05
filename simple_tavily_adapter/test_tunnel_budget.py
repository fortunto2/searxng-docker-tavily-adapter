"""The node's outside budget: tunnel traffic is limited, local traffic is not."""
from fastapi.testclient import TestClient

import main


def _client(rpm: int) -> TestClient:
    main.TUNNEL_RPM = rpm
    main._tunnel_hits.clear()
    return TestClient(main.app)


def test_tunnel_requests_over_budget_get_429():
    c = _client(2)
    codes = [c.post("/search", json={}, headers={"cf-ray": "x"}).status_code for _ in range(3)]
    assert codes[:2] == [422, 422]  # passed the budget, then failed validation (no query)
    assert codes[2] == 429


def test_mcp_header_counts_as_tunnel():
    c = _client(1)
    c.post("/extract", json={}, headers={"x-via-tunnel": "1"})
    r = c.post("/search", json={}, headers={"x-via-tunnel": "1"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_local_requests_are_not_limited():
    c = _client(1)
    assert all(c.post("/search", json={}).status_code == 422 for _ in range(5))


def test_zero_turns_it_off():
    c = _client(0)
    assert all(c.post("/search", json={}, headers={"cf-ray": "x"}).status_code == 422 for _ in range(5))
