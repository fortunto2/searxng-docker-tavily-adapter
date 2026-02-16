# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reddit (via OAuth API)

Uses Reddit's official OAuth API (oauth.reddit.com) for search.
Requires client_id and client_secret from https://www.reddit.com/prefs/apps/
Tokens are cached and auto-refreshed (1 hour TTL).

Rate limits (OAuth): 1000 requests per 10 minutes (600 seconds).
Engine tracks remaining quota from response headers and backs off when low.
"""

import json
import logging
import time
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# about
about = {
    "website": "https://www.reddit.com/",
    "wikidata_id": "Q1136",
    "official_api_documentation": "https://www.reddit.com/dev/api/",
    "use_official_api": True,
    "require_api_key": True,
    "results": "JSON",
}

# engine dependent config
categories = ["social media"]
page_size = 25

# OAuth credentials — set from config.yaml engine entry
client_id = ""
client_secret = ""
user_agent = "SearXNG:reddit_api:1.0 (by /u/searxng-adapter)"

# Token cache
_token = None
_token_expires = 0

# Rate limit tracking (from Reddit response headers)
# Reddit allows 1000 requests per 10 minutes
_rate_remaining = 1000
_rate_reset = 0  # timestamp when quota resets
_RATE_SAFETY_FLOOR = 50  # stop sending when fewer than this remain


def _get_token():
    """Get OAuth token using client_credentials grant. Cached for ~59 minutes."""
    global _token, _token_expires

    if _token and time.time() < _token_expires:
        return _token

    import base64

    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = Request(
        "https://www.reddit.com/api/v1/access_token",
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": f"Basic {credentials}",
            "User-Agent": user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    _token = data["access_token"]
    _token_expires = time.time() + data.get("expires_in", 3600) - 60
    return _token


def _is_rate_limited():
    """Check if we should back off to protect the quota."""
    now = time.time()
    # If reset time has passed, quota is refreshed
    if now > _rate_reset:
        return False
    if _rate_remaining < _RATE_SAFETY_FLOOR:
        wait = int(_rate_reset - now)
        logger.warning(
            f"Reddit API rate limit: {_rate_remaining} remaining, "
            f"backing off for {wait}s until reset"
        )
        return True
    return False


def request(query, params):
    # Back off if close to rate limit
    if _is_rate_limited():
        return None

    token = _get_token()
    query_params = urlencode(
        {
            "q": query,
            "limit": page_size,
            "sort": "relevance",
            "t": "all",
            "type": "link",
            "restrict_sr": False,
        }
    )
    params["url"] = f"https://oauth.reddit.com/search?{query_params}"
    params["headers"] = {
        "Authorization": f"Bearer {token}",
        "User-Agent": user_agent,
    }
    return params


def response(resp):
    global _rate_remaining, _rate_reset

    # Update rate limit tracking from response headers
    try:
        remaining = resp.headers.get("x-ratelimit-remaining")
        reset = resp.headers.get("x-ratelimit-reset")
        used = resp.headers.get("x-ratelimit-used")
        if remaining is not None:
            _rate_remaining = int(float(remaining))
        if reset is not None:
            _rate_reset = time.time() + int(float(reset))
        if used is not None:
            logger.debug(f"Reddit API: used={used}, remaining={_rate_remaining}, reset_in={reset}s")
    except (ValueError, TypeError):
        pass

    results = []

    try:
        data = json.loads(resp.text)
    except (json.JSONDecodeError, AttributeError):
        return results

    listing = data.get("data", {})
    children = listing.get("children", [])

    for child in children:
        post = child.get("data", {})

        title = post.get("title", "")
        permalink = post.get("permalink", "")
        if not title or not permalink:
            continue

        url = f"https://www.reddit.com{permalink}"

        # Build content from selftext
        content = post.get("selftext", "")
        if len(content) > 500:
            content = content[:500] + "..."

        # Metadata
        subreddit = post.get("subreddit", "")
        score = post.get("score", 0)
        num_comments = post.get("num_comments", 0)

        result = {
            "url": url,
            "title": title,
            "content": content,
        }

        # Published date
        created_utc = post.get("created_utc", 0)
        if created_utc:
            result["publishedDate"] = datetime.fromtimestamp(created_utc)

        # Metadata line
        if subreddit:
            metadata = f"r/{subreddit}"
            if score:
                metadata += f" | {score} points"
            if num_comments:
                metadata += f" | {num_comments} comments"
            result["metadata"] = metadata

        # Thumbnail handling
        thumbnail = post.get("thumbnail", "")
        if thumbnail and thumbnail not in ("self", "default", "nsfw", "spoiler", ""):
            result["img_src"] = post.get("url", url)
            result["thumbnail_src"] = thumbnail
            result["template"] = "images.html"

        results.append(result)

    return results
