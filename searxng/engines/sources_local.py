"""SearXNG engine — Solograph multi-source vector search.

Queries the solograph-search HTTP API (search_server.py).
Generic engine: configure source_name per engine instance in config.yaml.
"""

from urllib.parse import urlencode

about = {
    "website": "https://github.com/fortunto2/solograph",
    "use_official_api": False,
    "require_api_key": False,
    "results": "JSON",
}

categories = ["it", "apps"]
paging = False

# Config — set in config.yaml engine entry
api_url = "http://solograph-search:8002"
source_name = ""  # e.g. "producthunt", "youtube"; empty = search all sources


def request(query, params):
    qs = {"q": query, "n": 10}
    if source_name:
        qs["source"] = source_name
    params["url"] = f"{api_url}/search?{urlencode(qs)}"
    return params


def response(resp):
    results = []
    data = resp.json()

    for item in data.get("results", []):
        title = item.get("title", "")
        url = item.get("url", "")
        content = item.get("content", "")

        if not title or not url:
            continue

        results.append({
            "title": title,
            "url": url,
            "content": content,
        })

    return results
