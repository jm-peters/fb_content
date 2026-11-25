import unittest
from unittest.mock import Mock, call, patch

from google.genai import errors

from fb_idea_generator import (
    FALLBACK_GEMINI_MODELS,
    _generate_content_with_fallback,
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


if __name__ == "__main__":
    unittest.main()
