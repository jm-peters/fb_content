import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, call, patch

from google.genai import errors

from fb_idea_generator import (
    CarouselPost,
    CarouselSlide,
    DAILY_SCHEDULE,
    EAT_TZ,
    FALLBACK_GEMINI_MODELS,
    _generate_content_with_fallback,
    generate_daily_post,
    get_daily_slot_eat,
)


class GeminiModelFallbackTests(unittest.TestCase):
    @patch("fb_idea_generator.time.sleep")
    def test_quota_error_retries_then_uses_fallback_model(self, sleep):
        client = Mock()
        response = object()
        quota_error = errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "message": "Quota exceeded",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )
        client.models.generate_content.side_effect = [
            quota_error,
            quota_error,
            quota_error,
            response,
        ]

        result, selected_model = _generate_content_with_fallback(
            client,
            "configured-model",
            contents="Generate a post",
            config=object(),
        )

        self.assertIs(result, response)
        self.assertEqual(selected_model, FALLBACK_GEMINI_MODELS[0])
        self.assertEqual(client.models.generate_content.call_count, 4)
        self.assertEqual(sleep.call_args_list, [call(2), call(4)])

    @patch("fb_idea_generator.time.sleep")
    def test_retryable_server_error_retries_same_model(self, sleep):
        client = Mock()
        response = object()
        unavailable = errors.ServerError(
            503,
            {
                "error": {
                    "code": 503,
                    "message": "Model temporarily unavailable",
                    "status": "UNAVAILABLE",
                }
            },
        )
        client.models.generate_content.side_effect = [unavailable, response]

        result, selected_model = _generate_content_with_fallback(
            client,
            "configured-model",
            contents="Generate a post",
            config=object(),
        )

        self.assertIs(result, response)
        self.assertEqual(selected_model, "configured-model")
        sleep.assert_called_once_with(2)

    def test_non_retryable_error_is_raised(self):
        client = Mock()
        error = errors.ClientError(
            403,
            {
                "error": {
                    "code": 403,
                    "message": "Permission denied",
                    "status": "PERMISSION_DENIED",
                }
            },
        )
        client.models.generate_content.side_effect = error

        with self.assertRaises(errors.ClientError):
            _generate_content_with_fallback(
                client,
                "configured-model",
                contents="Generate a post",
                config=object(),
            )

        client.models.generate_content.assert_called_once()


class DailyPostGenerationTests(unittest.TestCase):
    @staticmethod
    def _carousel() -> CarouselPost:
        slides = [
            CarouselSlide(
                slide_number=index,
                slide_type=(
                    "cover" if index == 1
                    else "summary_cta" if index == 5
                    else "content"
                ),
                badge_text="Guide",
                headline=f"Slide {index}",
                body_points=["First point", "Second point"],
            )
            for index in range(1, 6)
        ]
        return CarouselPost(
            day_of_week="Monday",
            pillar="Test",
            caption="Caption",
            first_comment="Comment",
            slides=slides,
        )

    def test_daily_schedule_matches_weekday_and_publish_time(self):
        for day_index, slot in enumerate(DAILY_SCHEDULE):
            now = datetime(2026, 11, 30, 16, tzinfo=EAT_TZ) + timedelta(days=day_index)
            actual_slot, scheduled_at = get_daily_slot_eat(now)

            self.assertEqual(actual_slot, slot)
            self.assertEqual(scheduled_at.hour, slot["hour_eat"])
            self.assertEqual(scheduled_at.date(), now.date())

    def test_generates_only_one_post_for_today(self):
        monday = datetime(2026, 11, 30, 16, tzinfo=EAT_TZ)
        client = Mock()
        client.models.generate_content.return_value = Mock(parsed=self._carousel())

        with (
            patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}),
            patch("fb_idea_generator._read_analytics_feedback", return_value=""),
            patch("fb_idea_generator.genai.Client", return_value=client),
        ):
            post = generate_daily_post(now=monday)

        client.models.generate_content.assert_called_once()
        self.assertEqual(post["day"], "Monday")
        self.assertEqual(post["format"], "carousel")
        self.assertEqual(post["scheduled_readable_eat"], "2026-11-30 19:00 EAT")

    def test_refuses_to_generate_after_daily_publish_time(self):
        after_publish = datetime(2026, 11, 30, 19, tzinfo=EAT_TZ)

        with (
            patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}),
            patch("fb_idea_generator.genai.Client") as gemini_client,
        ):
            with self.assertRaisesRegex(ValueError, "publish time has passed"):
                generate_daily_post(now=after_publish)

        gemini_client.assert_not_called()

    def test_uses_search_grounding_for_sunday_post(self):
        sunday = datetime(2026, 12, 6, 15, tzinfo=EAT_TZ)
        client = Mock()
        client.models.generate_content.return_value = Mock(parsed=self._carousel())

        with (
            patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}),
            patch("fb_idea_generator._read_analytics_feedback", return_value=""),
            patch("fb_idea_generator.genai.Client", return_value=client),
        ):
            generate_daily_post(now=sunday)

        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertTrue(config.tools)
        self.assertIsNotNone(config.tools[0].google_search)


if __name__ == "__main__":
    unittest.main()
