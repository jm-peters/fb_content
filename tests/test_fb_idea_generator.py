import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, call, patch

from google.genai import errors

from fb_idea_generator import (
    CarouselPost,
    CarouselSlide,
    FALLBACK_GEMINI_MODELS,
    ReelPost,
    ReelScene,
    _generate_content_with_fallback,
    generate_weekly_plan,
)


class GeminiModelFallbackTests(unittest.TestCase):
    def test_unavailable_model_retries_with_fallback(self):
        client = Mock()
        response = object()
        client.models.generate_content.side_effect = [
            errors.ClientError(
                404,
                {
                    "error": {
                        "code": 404,
                        "message": "This model is no longer available",
                        "status": "NOT_FOUND",
                    }
                },
            ),
            response,
        ]

        result, selected_model = _generate_content_with_fallback(
            client,
            "retired-model",
            contents="Generate a post",
            config=object(),
        )

        self.assertIs(result, response)
        self.assertEqual(selected_model, FALLBACK_GEMINI_MODELS[0])
        self.assertEqual(client.models.generate_content.call_count, 2)

    @patch("fb_idea_generator.time.sleep")
    def test_unavailable_service_retries_then_uses_fallback_model(self, sleep):
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
        client.models.generate_content.side_effect = [
            unavailable,
            unavailable,
            unavailable,
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
    def test_retryable_error_is_retried_on_same_model(self, sleep):
        client = Mock()
        response = object()
        client.models.generate_content.side_effect = [
            errors.ServerError(
                503,
                {
                    "error": {
                        "code": 503,
                        "message": "Model temporarily unavailable",
                        "status": "UNAVAILABLE",
                    }
                },
            ),
            response,
        ]

        result, selected_model = _generate_content_with_fallback(
            client,
            "configured-model",
            contents="Generate a post",
            config=object(),
        )

        self.assertIs(result, response)
        self.assertEqual(selected_model, "configured-model")
        self.assertEqual(client.models.generate_content.call_count, 2)
        sleep.assert_called_once_with(2)

    @patch("fb_idea_generator.time.sleep")
    def test_quota_error_fails_without_retry_or_model_fallback(self, sleep):
        client = Mock()
        client.models.generate_content.side_effect = errors.ClientError(
            429,
            {
                "error": {
                    "code": 429,
                    "message": "Quota exceeded",
                    "status": "RESOURCE_EXHAUSTED",
                }
            },
        )

        with self.assertRaises(errors.ClientError):
            _generate_content_with_fallback(
                client,
                "configured-model",
                contents="Generate a post",
                config=object(),
            )

        client.models.generate_content.assert_called_once()
        sleep.assert_not_called()

    def test_non_model_not_found_error_is_not_retried(self):
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

    def test_all_unavailable_models_raise_last_error(self):
        client = Mock()
        errors_by_model = [
            errors.ClientError(
                404,
                {
                    "error": {
                        "code": 404,
                        "message": f"{model} is unavailable",
                        "status": "NOT_FOUND",
                    }
                },
            )
            for model in ("configured-model", *FALLBACK_GEMINI_MODELS)
        ]
        client.models.generate_content.side_effect = errors_by_model

        with self.assertRaises(errors.ClientError) as raised:
            _generate_content_with_fallback(
                client,
                "configured-model",
                contents="Generate a post",
                config=object(),
            )

        self.assertIs(raised.exception, errors_by_model[-1])
        self.assertEqual(
            client.models.generate_content.call_count,
            1 + len(FALLBACK_GEMINI_MODELS),
        )


class WeeklyPlanResumeTests(unittest.TestCase):
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

    @staticmethod
    def _reel() -> ReelPost:
        scenes = [
            ReelScene(
                scene_number=index,
                duration_seconds=10,
                voiceover_text=f"Scene {index}",
                on_screen_text=f"Scene {index}",
                visual_prompt=f"Visual {index}",
            )
            for index in range(1, 4)
        ]
        return ReelPost(
            day_of_week="Tuesday",
            pillar="Test",
            hook_title="Tuesday Reel",
            caption="Caption",
            first_comment="Comment",
            total_duration_seconds=30,
            scenes=scenes,
        )

    def test_resume_uses_saved_posts_and_original_week_after_quota_error(self):
        schedule = [
            {
                "day": "Monday",
                "hour_eat": 19,
                "format": "carousel",
                "pillar": "Test",
                "brief": "Make a carousel",
            },
            {
                "day": "Tuesday",
                "hour_eat": 19,
                "format": "reel",
                "pillar": "Test",
                "brief": "Make a reel",
            },
        ]
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
        first_client = Mock()
        first_client.models.generate_content.side_effect = [
            Mock(parsed=self._carousel()),
            quota_error,
        ]
        resumed_client = Mock()
        resumed_client.models.generate_content.return_value = Mock(parsed=self._reel())
        original_monday = datetime(2026, 11, 30, tzinfo=timezone(timedelta(hours=3)))
        later_monday = original_monday + timedelta(days=7)

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "weekly_content_plan.json"
            progress_path = Path(temp_dir) / "weekly_content_plan.progress.json"
            with (
                patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}),
                patch("fb_idea_generator.WEEKLY_SCHEDULE", schedule),
                patch("fb_idea_generator._read_analytics_feedback", return_value=""),
                patch("fb_idea_generator.get_next_monday_eat", return_value=original_monday),
                patch("fb_idea_generator.genai.Client", return_value=first_client),
            ):
                with self.assertRaises(errors.ClientError):
                    generate_weekly_plan(output_path=output_path)

            checkpoint = json.loads(progress_path.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["week_start"], "2026-11-30")
            self.assertEqual([post["day"] for post in checkpoint["carousels"]], ["Monday"])

            with (
                patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}),
                patch("fb_idea_generator.WEEKLY_SCHEDULE", schedule),
                patch("fb_idea_generator._read_analytics_feedback", return_value=""),
                patch("fb_idea_generator.get_next_monday_eat") as get_next_monday,
                patch("fb_idea_generator.genai.Client", return_value=resumed_client),
            ):
                get_next_monday.return_value = later_monday
                plan = generate_weekly_plan(output_path=output_path)

            get_next_monday.assert_not_called()
            resumed_client.models.generate_content.assert_called_once()
            self.assertEqual(plan["week_start"], "2026-11-30")
            self.assertEqual([post["day"] for post in plan["carousels"]], ["Monday"])
            self.assertEqual([post["day"] for post in plan["reels"]], ["Tuesday"])
            self.assertEqual(
                plan["reels"][0]["scheduled_readable_eat"],
                "2026-12-01 19:00 EAT",
            )
            self.assertTrue(progress_path.exists())
            self.assertTrue(output_path.exists())


if __name__ == "__main__":
    unittest.main()
