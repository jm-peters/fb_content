import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from main import run_daily_engine


class DailyEngineIdempotencyTests(unittest.TestCase):
    def test_existing_schedule_is_skipped_before_generation(self):
        eat = ZoneInfo("Africa/Nairobi")
        now = datetime(2026, 11, 30, 20, tzinfo=eat)
        scheduled_at = datetime(2026, 11, 30, 19, tzinfo=eat)
        slot = {"day": "Monday", "format": "carousel", "hour_eat": 19}
        history = {
            "past_topics": [],
            "top_performing_topics": [],
            "published_posts": [{"schedule_key": "2026-11-30:carousel"}],
        }

        with (
            patch("main.datetime") as datetime_mock,
            patch("main.get_daily_slot_eat", return_value=(slot, scheduled_at)),
            patch("main.sync_page_insights", return_value=history),
            patch("main.generate_daily_post") as generate_post,
        ):
            datetime_mock.now.return_value = now
            run_daily_engine()

        generate_post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
