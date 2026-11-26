from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from carousel_builder import build_carousel_slides
from fb_analytics_loop import HISTORY_FILE, save_history, sync_page_insights
from fb_idea_generator import generate_daily_post, get_daily_slot_eat
from fb_publisher import FacebookPublisher
from fb_reel_renderer import render_reel

LOCAL_TZ = ZoneInfo("Africa/Nairobi")
OUTPUT_DIR = Path("output_daily")


def run_daily_engine() -> None:
    now_local = datetime.now(LOCAL_TZ)
    slot, scheduled_at = get_daily_slot_eat(now_local)
    print(
        "=== SMARTSORT.TECH FACEBOOK DAILY ENGINE STARTED "
        f"({now_local.strftime('%Y-%m-%d %H:%M %Z')}) ==="
    )
    history = sync_page_insights(HISTORY_FILE)
    history.setdefault("past_topics", [])
    history.setdefault("top_performing_topics", [])
    history.setdefault("published_posts", [])

    schedule_key = f"{scheduled_at.date().isoformat()}:{slot['format']}"
    if any(
        post.get("schedule_key") == schedule_key
        for post in history["published_posts"]
    ):
        print(f"\n[=] Today's {slot['day']} post is already scheduled; skipping.")
        return

    if scheduled_at <= now_local:
        raise ValueError(
            f"Today's {slot['day']} publish time has passed; refusing to schedule "
            "a post in the past."
        )

    post = generate_daily_post(
        past_topics=history["past_topics"][-60:],
        winning_topics=history["top_performing_topics"],
        now=now_local,
    )
    title = post["title"]
    scheduled_text = post["scheduled_readable_eat"]
    print(
        f"\n--- [{post['day']}] {post['format'].upper()}: {title} "
        f"({scheduled_text}) ---"
    )
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    publisher = FacebookPublisher()
    date_prefix = scheduled_at.strftime("%Y-%m-%d")

    if post["format"] == "carousel":
        slide_dir = OUTPUT_DIR / f"{date_prefix}_carousel"
        slide_paths = build_carousel_slides(post, output_dir=slide_dir)
        result = publisher.publish_carousel(
            image_paths=slide_paths,
            caption=post["caption"],
            scheduled_unix=post["scheduled_unix_time"],
            first_comment=post.get("first_comment"),
        )
        post_id = result["post_id"]
        record = {
            "day": post["day"],
            "format": post["format"],
            "title": title,
            "post_id": post_id,
            "first_comment": post.get("first_comment"),
            "comment_status": result["comment_status"],
        }
    else:
        reel_path = OUTPUT_DIR / f"{date_prefix}_reel.mp4"
        render_reel(
            post,
            output_path=str(reel_path),
            work_dir=str(OUTPUT_DIR / "tmp" / date_prefix),
        )
        result = publisher.publish_reel(
            video_path=str(reel_path),
            description=post["caption"],
            scheduled_unix=post["scheduled_unix_time"],
            first_comment=post.get("first_comment"),
        )
        post_id = result["video_id"]
        record = {
            "day": post["day"],
            "format": post["format"],
            "title": title,
            "video_id": post_id,
            "first_comment": post.get("first_comment"),
            "comment_status": result["comment_status"],
        }

    history["past_topics"].append(title)
    record.update(
        {
            "schedule_key": schedule_key,
            "scheduled_unix": post["scheduled_unix_time"],
            "scheduled_for": scheduled_text,
        }
    )
    history["published_posts"].append(record)
    history["past_topics"] = history["past_topics"][-60:]
    history["published_posts"] = history["published_posts"][-80:]
    save_history(history, HISTORY_FILE)
    print("\n=== DAILY POST PROCESSED ===")


if __name__ == "__main__":
    run_daily_engine()
