import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

GRAPH_API_VERSION = os.getenv("FB_GRAPH_API_VERSION", "v27.0")
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
HISTORY_FILE = Path("history.json")


def load_history(path: str | Path = HISTORY_FILE) -> dict:
    history_path = Path(path)
    if not history_path.exists():
        return {
            "past_topics": [],
            "top_performing_topics": [],
            "published_posts": [],
            "analytics_by_post": [],
            "last_analytics_sync": None,
        }
    with history_path.open("r", encoding="utf-8") as history_file:
        history = json.load(history_file)
    if not isinstance(history, dict):
        raise ValueError(f"History file must contain a JSON object: {history_path}")
    history.setdefault("past_topics", [])
    history.setdefault("top_performing_topics", [])
    history.setdefault("published_posts", [])
    history.setdefault("analytics_by_post", [])
    history.setdefault("last_analytics_sync", None)
    for key in ("past_topics", "top_performing_topics", "published_posts", "analytics_by_post"):
        if not isinstance(history[key], list):
            raise ValueError(f"History field {key!r} must be a JSON array: {history_path}")
    return history


def save_history(history: dict, path: str | Path = HISTORY_FILE) -> None:
    history_path = Path(path)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = history_path.with_suffix(history_path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as history_file:
        json.dump(history, history_file, indent=2, ensure_ascii=False)
        history_file.write("\n")
    temp_path.replace(history_path)


def _get_api_json(url: str, params: dict, timeout: int = 30) -> dict:
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(f"Meta Graph API error: {payload['error']}")
    return payload


def _get_post_reach(post_id: str, token: str) -> int | None:
    try:
        payload = _get_api_json(
            f"{BASE_URL}/{post_id}/insights",
            {"metric": "post_total_media_view_unique", "access_token": token},
            timeout=15,
        )
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        print(f"[!] Insights unavailable for post {post_id}: {exc}")
        return None

    metrics = payload.get("data", [])
    if not metrics:
        return None
    values = metrics[0].get("values", [])
    if not values:
        return None
    return values[-1].get("value")


def sync_page_insights(history_path: str | Path = HISTORY_FILE) -> dict:
    """Fetch recent Page engagement and update the content-performance memory."""
    page_id = os.getenv("FB_PAGE_ID")
    token = os.getenv("FB_PAGE_ACCESS_TOKEN")
    history = load_history(history_path)
    if not page_id or not token:
        print("[!] Missing FB_PAGE_ID or FB_PAGE_ACCESS_TOKEN; skipping live analytics sync.")
        return history

    print(f"[*] Syncing Page analytics for {page_id}...")
    try:
        payload = _get_api_json(
            f"{BASE_URL}/{page_id}/posts",
            {
                "fields": "id,message,created_time,shares,reactions.summary(true),comments.summary(true)",
                "limit": 25,
                "access_token": token,
            },
        )
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"[!] Page analytics unavailable; continuing with saved history: {exc}")
        return history
    published_by_id = {
        post.get("post_id") or post.get("video_id"): post.get("title")
        for post in history["published_posts"]
        if post.get("post_id") or post.get("video_id")
    }

    scored_posts = []
    for post in payload.get("data", []):
        post_id = post.get("id")
        if not post_id:
            continue
        message = (post.get("message") or "").strip()
        headline = published_by_id.get(post_id) or (
            message.splitlines()[0][:110] if message else "Untitled Post"
        )
        shares = int((post.get("shares") or {}).get("count", 0) or 0)
        reactions = int(
            ((post.get("reactions") or {}).get("summary") or {}).get("total_count", 0) or 0
        )
        comments = int(
            ((post.get("comments") or {}).get("summary") or {}).get("total_count", 0) or 0
        )
        reach = _get_post_reach(post_id, token)
        score = (shares * 3) + (comments * 2) + reactions
        scored_posts.append(
            {
                "post_id": post_id,
                "headline": headline,
                "created_time": post.get("created_time"),
                "reach": reach,
                "reach_metric": "post_total_media_view_unique",
                "shares": shares,
                "comments": comments,
                "reactions": reactions,
                "score": score,
            }
        )

    scored_posts.sort(key=lambda item: (item["score"], item["shares"]), reverse=True)
    history["analytics_by_post"] = scored_posts
    top_topics = [
        post["headline"] for post in scored_posts[:5] if post["score"] > 0
    ]
    if top_topics:
        history["top_performing_topics"] = top_topics
    history["last_analytics_sync"] = datetime.now(timezone.utc).isoformat()
    save_history(history, history_path)
    print(
        f"[OK] Analytics synced ({len(scored_posts)} posts analyzed); "
        f"{len(history['top_performing_topics'])} top topics recorded."
    )
    return history


if __name__ == "__main__":
    sync_page_insights()
