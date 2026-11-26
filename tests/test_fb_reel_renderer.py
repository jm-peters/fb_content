import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fb_reel_renderer import _scene_cards


class PixabayFallbackTests(unittest.TestCase):
    def test_http_error_uses_branded_background_for_scene(self):
        response = Mock(status_code=400)
        reel_data = {
            "title": "Test Reel",
            "scenes": [
                {
                    "on_screen_text": "Scene title",
                    "visual_prompt": "a developer workspace",
                    "duration_seconds": 10,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("fb_reel_renderer.requests.get", return_value=response),
                patch("fb_reel_renderer._make_terminal_card") as make_card,
            ):
                segments = _scene_cards(
                    reel_data,
                    Path(temp_dir),
                    duration=10,
                    pixabay_api_key="test-key",
                )

        self.assertEqual(len(segments), 1)
        self.assertIsNone(make_card.call_args.args[-1])


if __name__ == "__main__":
    unittest.main()
