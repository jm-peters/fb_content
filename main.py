from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from carousel_builder import build_carousel_slides
from fb_analytics_loop import HISTORY_FILE, save_history, sync_page_insights
from fb_idea_generator import generate_weekly_plan
from fb_publisher import FacebookPublisher
from fb_reel_renderer import render_reel

LOCAL_TZ = ZoneInfo("Africa/Nairobi")
OUTPUT_DIR = Path("output_weekly")


def _schedule_key(post: dict, post_format: str) -> str:
    scheduled = datetime.fromtimestamp(post["scheduled_unix_time"], tz=LOCAL_TZ)
    return f"{scheduled.date().isoformat()}:{post_format}"


def run_weekly_engine() -> None:
    now_local = datetime.now(LOCAL_TZ)
    print(
        "=== SMARTSORT.TECH FACEBOOK ENGINE STARTED "
        f"({now_local.strftime('%Y-%m-%d %H:%M %Z')}) ==="
    )

    history = sync_page_insights(HISTORY_FILE)
    history.setdefault("past_topics", [])
    history.setdefault("top_performing_topics", [])
    history.setdefault("published_posts", [])

    publisher = FacebookPublisher()
    print("\n[*] Generating the 7-post weekly content plan...")
    weekly_plan = generate_weekly_plan(
        past_topics=history["past_topics"][-60:],
        winning_topics=history["top_performing_topics"],
    )
    if len(weekly_plan.get("carousels", [])) != 4 or len(weekly_plan.get("reels", [])) != 3:
        raise ValueError("Weekly plan must contain exactly four carousels and three Reels.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing_keys = {
        post.get("schedule_key")
        for post in history["published_posts"]
        if post.get("schedule_key")
    }

    posts = [
        (post, "carousel")
        for post in weekly_plan["carousels"]
    ] + [
        (post, "reel")
        for post in weekly_plan["reels"]
    ]
    posts.sort(key=lambda item: item[0]["scheduled_unix_time"])

    for post, post_format in posts:
        day = post["day"]
        title = post["title"]
        schedule_key = _schedule_key(post, post_format)
        scheduled_at = datetime.fromtimestamp(
            post["scheduled_unix_time"], tz=LOCAL_TZ
        )
        scheduled_text = scheduled_at.strftime("%a %b %d, %I:%M %p %Z")
        if schedule_key in existing_keys:
            print(f"\n[=] Already scheduled; skipping {day} {post_format}: {title}")
            continue

        print(f"\n--- [{day}] {post_format.upper()}: {title} ({scheduled_text}) ---")
        if post_format == "carousel":
            slide_dir = OUTPUT_DIR / f"{day.lower()}_carousel"
            slide_paths = build_carousel_slides(post, output_dir=slide_dir)
            result = publisher.publish_carousel(
                image_paths=slide_paths,
                caption=post["caption"],
                scheduled_unix=post["scheduled_unix_time"],
                first_comment=post.get("first_comment"),
            )
            post_id = result["post_id"]
            record = {
                "day": day,
                "format": post_format,
                "title": title,
                "post_id": post_id,
                "first_comment": post.get("first_comment"),
                "comment_status": result["comment_status"],
            }
        else:
            reel_path = OUTPUT_DIR / f"{day.lower()}_reel.mp4"
            render_reel(
                post,
                output_path=str(reel_path),
                work_dir=str(OUTPUT_DIR / "tmp" / day.lower()),
            )
            result = publisher.publish_reel(
                video_path=str(reel_path),
                description=post["caption"],
                scheduled_unix=post["scheduled_unix_time"],
                first_comment=post.get("first_comment"),
            )
            post_id = result["video_id"]
            record = {
                "day": day,
                "format": post_format,
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
        existing_keys.add(schedule_key)
        save_history(history, HISTORY_FILE)

    print("\n=== WEEKLY POSTS PROCESSED ===")


if __name__ == "__main__":
    run_weekly_engine()
