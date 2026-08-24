# SPDX-License-Identifier: AGPL-3.0-or-later
"""Product Hunt (GraphQL API v2)

Launch data for idea research: what shipped in a space, how it was positioned,
and how much traction it got. Votes and comments are the demand signal a plain
web result does not carry.

Needs a developer token from https://www.producthunt.com/v2/oauth/applications,
set as `api_token` on the engine entry in config.yaml.
"""

import json
from datetime import datetime

from searx.exceptions import SearxEngineAPIException

about = {
    "website": "https://www.producthunt.com/",
    "official_api_documentation": "https://api.producthunt.com/v2/docs",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

categories = ["it", "apps"]
paging = False

api_url = "https://api.producthunt.com/v2/api/graphql"
api_token = ""
page_size = 20

# PH caps a page at 20 edges whatever `first` says — verified, first=200 still
# returns 20 with hasNextPage=true.
_WINDOW = 20

_FIELDS = """
      name tagline description url votesCount commentsCount createdAt website
      topics(first: 4) { edges { node { name } } }
"""

# Two lanes in one request, because neither works alone:
#   byTopic — a real server-side filter, which is the only way to search a space
#             when the page cap is 20.
#   top     — the votes-ordered top 20 filtered client-side on the query terms,
#             catching products whose topic slug does not match the wording.
# An unknown topic slug returns 0 posts rather than an error, so the topic lane is
# safe to send for any query. $q is deliberately absent: PH has no free-text post
# search, and declaring an unused variable makes it reject the whole query with
# "Variable $q is declared by Search but not used".
_QUERY = ("""
query Search($topic: String!, $n: Int!) {
  byTopic: posts(first: $n, order: VOTES, topic: $topic) { edges { node { %(f)s } } }
  top:     posts(first: $n, order: VOTES)                { edges { node { %(f)s } } }
}
""" % {"f": _FIELDS})


def request(query, params):
    params["url"] = api_url
    params["method"] = "POST"
    params["headers"]["Authorization"] = f"Bearer {api_token}"
    params["headers"]["Content-Type"] = "application/json"
    params["headers"]["Accept"] = "application/json"
    # PH topic slugs are lowercase and hyphenated: "video editing" -> "video-editing"
    topic = "-".join(query.lower().split())
    params["data"] = json.dumps(
        {"query": _QUERY, "variables": {"topic": topic, "n": _WINDOW}}
    )
    params["raw_query"] = query
    return params


def _matches(node, terms):
    haystack = " ".join(
        [
            node.get("name") or "",
            node.get("tagline") or "",
            node.get("description") or "",
            " ".join(t["node"]["name"] for t in node.get("topics", {}).get("edges", [])),
        ]
    ).lower()
    return all(t in haystack for t in terms)


def _item(node):
    topics = ", ".join(
        t["node"]["name"] for t in node.get("topics", {}).get("edges", [])
    )
    parts = [node.get("tagline") or ""]
    desc = node.get("description") or ""
    if desc and desc != node.get("tagline"):
        parts.append(desc[:400])
    if topics:
        parts.append(f"Topics: {topics}")

    item = {
        "url": node["url"],
        "title": node["name"],
        "content": " — ".join(x for x in parts if x),
        "metadata": f"{node.get('votesCount', 0)} votes | "
                    f"{node.get('commentsCount', 0)} comments",
    }
    created = node.get("createdAt")
    if created:
        try:
            item["publishedDate"] = datetime.fromisoformat(
                created.replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except ValueError:
            pass
    return item


def response(resp):
    data = json.loads(resp.text)
    if "errors" in data:
        # Returning [] here would make a bad api_token or a GraphQL error look like
        # "no results" — the silent-loss failure the unresponsive_engines plumbing
        # exists to kill. Raise so it lands there instead.
        raise SearxEngineAPIException(
            "; ".join(str(e.get("message", e)) for e in data["errors"])[:200]
        )
    payload = data.get("data") or {}

    raw = ""
    try:
        raw = resp.search_params.get("raw_query") or ""
    except AttributeError:
        pass
    terms = [t for t in raw.lower().split() if t]

    results = []
    seen = set()
    # Topic matches first: that is the server's own classification, so it ranks
    # above a keyword hit in a tagline.
    for lane, keyword_filter in (("byTopic", False), ("top", True)):
        for edge in (payload.get(lane) or {}).get("edges", []):
            node = edge.get("node") or {}
            if not node.get("name") or not node.get("url") or node["url"] in seen:
                continue
            if keyword_filter and terms and not _matches(node, terms):
                continue
            seen.add(node["url"])
            results.append(_item(node))
            if len(results) >= page_size:
                return results
    return results
