# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reddit (via PullPush API)

Uses api.pullpush.io as backend instead of reddit.com/search.json
to avoid 403 blocks from Reddit on datacenter IPs.
"""

import json
from datetime import datetime
from urllib.parse import urlencode, urlparse

# about
about = {
    "website": 'https://www.reddit.com/',
    "wikidata_id": 'Q1136',
    "official_api_documentation": 'https://api.pullpush.io/',
    "use_official_api": False,
    "require_api_key": False,
    "results": 'JSON',
}

# engine dependent config
categories = ['social media']
page_size = 25
# Minimum score threshold — filters out spam bots (score=1, 0 comments)
min_score = 3

# PullPush API
base_url = 'https://www.reddit.com'
search_url = 'https://api.pullpush.io/reddit/submission/search?{query}'


def request(query, params):
    # PullPush has no relevance ranking. An unquoted multi-word query matches
    # loosely and, sorted by score, returns the highest-scoring posts that share
    # any common word — "organize home videos" came back with a desk lamp build
    # and a PMP exam question. Quoted, the same query returns "I am looking for a
    # system to organize home videos by people, events" and "Home movies in
    # Jellyfin?". So quote it: for research, phrase precision beats recall, and
    # without it this engine is not usable at all.
    if ' ' in query.strip() and not (query.startswith('"') and query.endswith('"')):
        query = f'"{query}"'

    query = urlencode({
        'q': query,
        'size': page_size,
        'sort': 'score',
        'order': 'desc',
        'score': f'>{min_score}',
    })
    params['url'] = search_url.format(query=query)
    return params


def response(resp):
    img_results = []
    text_results = []

    search_results = json.loads(resp.text)

    if 'data' not in search_results:
        return []

    posts = search_results.get('data', [])

    for post in posts:
        # Skip spam: low-score posts with zero engagement
        score = post.get('score', 0)
        num_comments = post.get('num_comments', 0)
        if score < 2 and num_comments == 0:
            continue

        permalink = post.get('permalink', '')
        url = f'{base_url}{permalink}' if permalink else ''
        title = post.get('title', '')

        if not url or not title:
            continue

        params = {'url': url, 'title': title}

        thumbnail = post.get('thumbnail', '')
        url_info = urlparse(thumbnail)

        if url_info.netloc and url_info.path and thumbnail not in ('self', 'default', 'nsfw', 'spoiler', ''):
            params['img_src'] = post.get('url', url)
            params['thumbnail_src'] = thumbnail
            params['template'] = 'images.html'
            img_results.append(params)
        else:
            # PullPush returns created_utc as a number for most posts and as a
            # string for some, and fromtimestamp raises TypeError on a string.
            # Latent until queries started matching real posts.
            created_utc = post.get('created_utc') or 0
            try:
                created_utc = float(created_utc)
            except (TypeError, ValueError):
                created_utc = 0
            if created_utc:
                params['publishedDate'] = datetime.fromtimestamp(created_utc)

            content = post.get('selftext', '')
            if len(content) > 500:
                content = content[:500] + '...'
            params['content'] = content

            subreddit = post.get('subreddit', '')
            score = post.get('score', 0)
            num_comments = post.get('num_comments', 0)
            if subreddit:
                metadata = f'r/{subreddit}'
                if score:
                    metadata += f' | {score} points'
                if num_comments:
                    metadata += f' | {num_comments} comments'
                params['metadata'] = metadata

            text_results.append(params)

    return img_results + text_results
