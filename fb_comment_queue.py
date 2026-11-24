from datetime import datetime, timezone

import requests

from fb_analytics_loop import HISTORY_FILE, load_history, save_history
from fb_publisher import FacebookPublisher


def process_pending_comments() -> int:
    history = load_history(HISTORY_FILE)
    publisher = FacebookPublisher()
    now = int(datetime.now(timezone.utc).timestamp())
    posted_count = 0
    changed = False

    for record in history["published_posts"]:
        if record.get("comment_status") != "pending" or not record.get("first_comment"):
            continue
        if int(record.get("scheduled_unix", 0)) > now:
            continue

        is_reel = record.get("format") == "reel"
        object_id = record.get("video_id") if is_reel else record.get("post_id")
        if not object_id:
            print(f"[!] Pending comment has no post ID: {record.get('title', 'unknown post')}")
            continue

        try:
            if not publisher.is_post_published(object_id, is_reel=is_reel):
                continue
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"[!] Could not check publish status for {object_id}; will retry: {exc}")
            continue

        if publisher.post_comment(object_id, record["first_comment"]):
            record["comment_status"] = "posted"
            record["comment_posted_at"] = datetime.now(timezone.utc).isoformat()
            posted_count += 1
            changed = True

    if changed:
        save_history(history, HISTORY_FILE)
    print(f"[*] Posted {posted_count} queued first comment(s).")
    return posted_count


if __name__ == "__main__":
    process_pending_comments()
