import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

GRAPH_API_VERSION = os.getenv("FB_GRAPH_API_VERSION", "v27.0")
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def _read_response(response: requests.Response, action: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        response.raise_for_status()
        raise RuntimeError(f"{action} returned invalid JSON: {response.text[:500]}") from exc
    if response.status_code >= 400 or "error" in payload:
        raise RuntimeError(f"{action} failed: {payload}")
    response.raise_for_status()
    return payload


class FacebookPublisher:
    def __init__(self, page_id: str | None = None, access_token: str | None = None):
        self.page_id = page_id or os.getenv("FB_PAGE_ID")
        self.access_token = access_token or os.getenv("FB_PAGE_ACCESS_TOKEN")
        if not self.page_id or not self.access_token:
            raise ValueError("Missing FB_PAGE_ID or FB_PAGE_ACCESS_TOKEN environment variables.")

    def _validate_schedule_time(self, scheduled_unix: int | None) -> int | None:
        """Return a Meta-valid schedule or fail before making any API request."""
        if scheduled_unix is None:
            return None
        now_unix = int(time.time())
        min_future = now_unix + 11 * 60
        max_future = now_unix + 29 * 86400
        if scheduled_unix < min_future:
            adjusted = now_unix + 15 * 60
            print(f"[!] Schedule is too close or in the past; moving it to {adjusted}.")
            return adjusted
        if scheduled_unix > max_future:
            raise ValueError("Scheduled publish time cannot exceed 30 days in the future.")
        return scheduled_unix

    def publish_carousel(
        self,
        image_paths: list[str],
        caption: str,
        scheduled_unix: int | None = None,
        first_comment: str | None = None,
    ) -> dict:
        """Upload unpublished photos and attach them to one multi-photo Page post."""
        if not image_paths:
            raise ValueError("image_paths cannot be empty.")
        scheduled_unix = self._validate_schedule_time(scheduled_unix)
        attached_media = []
        print(f"[*] Uploading {len(image_paths)} carousel slides to Page {self.page_id}...")

        for index, image_path in enumerate(image_paths, start=1):
            path = Path(image_path)
            if not path.is_file():
                raise FileNotFoundError(f"Slide not found: {path}")
            with path.open("rb") as image_file:
                response = requests.post(
                    f"{BASE_URL}/{self.page_id}/photos",
                    data={"published": "false", "access_token": self.access_token},
                    files={"source": (path.name, image_file, "image/png")},
                    timeout=60,
                )
            result = _read_response(response, f"Carousel slide {index} upload")
            if not result.get("id"):
                raise RuntimeError(f"Carousel slide {index} upload returned no media ID: {result}")
            attached_media.append({"media_fbid": result["id"]})
            print(f"    [+] Slide {index}/{len(image_paths)} uploaded.")

        payload = {
            "message": caption,
            "attached_media": json.dumps(attached_media),
            "access_token": self.access_token,
        }
        if scheduled_unix is None:
            payload["published"] = "true"
        else:
            payload["published"] = "false"
            payload["scheduled_publish_time"] = scheduled_unix
        result = _read_response(
            requests.post(
                f"{BASE_URL}/{self.page_id}/feed",
                data=payload,
                timeout=60,
            ),
            "Carousel post creation",
        )
        post_id = result.get("id")
        if not post_id:
            raise RuntimeError(f"Carousel post creation returned no post ID: {result}")

        comment_status = "none"
        if first_comment and scheduled_unix is None:
            comment_status = "posted" if self.post_comment(post_id, first_comment) else "pending"
        elif first_comment:
            comment_status = "pending"
            print("[!] First comment not posted: scheduled posts cannot be commented on yet.")
        self._log_status("Carousel", post_id, scheduled_unix)
        return {
            "post_id": post_id,
            "type": "carousel",
            "scheduled_unix": scheduled_unix,
            "comment_status": comment_status,
        }

    def publish_reel(
        self,
        video_path: str,
        description: str,
        scheduled_unix: int | None = None,
        first_comment: str | None = None,
    ) -> dict:
        """Upload a Reel using Meta's start, binary-upload, and finish phases."""
        path = Path(video_path)
        if not path.is_file():
            raise FileNotFoundError(f"Reel video not found: {path}")
        scheduled_unix = self._validate_schedule_time(scheduled_unix)
        file_size = path.stat().st_size
        endpoint = f"{BASE_URL}/{self.page_id}/video_reels"
        print(f"[*] Initializing Reel upload ({file_size / (1024 * 1024):.2f} MB)...")
        start = _read_response(
            requests.post(
                endpoint,
                data={"upload_phase": "start", "access_token": self.access_token},
                timeout=30,
            ),
            "Reel upload initialization",
        )
        video_id = start.get("video_id")
        upload_url = start.get("upload_url")
        if not video_id or not upload_url:
            raise RuntimeError(f"Reel upload initialization omitted video_id or upload_url: {start}")

        print("[*] Uploading Reel video...")
        with path.open("rb") as video_file:
            upload_response = requests.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {self.access_token}",
                    "offset": "0",
                    "file_size": str(file_size),
                    "Content-Type": "application/octet-stream",
                },
                data=video_file,
                timeout=300,
            )
        upload_result = _read_response(upload_response, "Reel binary upload")
        if not upload_result.get("success"):
            raise RuntimeError(f"Reel binary upload was not accepted: {upload_result}")

        finish_payload = {
            "upload_phase": "finish",
            "video_id": video_id,
            "description": description,
            "access_token": self.access_token,
            "is_ai_generated": "true",
        }
        if scheduled_unix is None:
            finish_payload["video_state"] = "PUBLISHED"
        else:
            finish_payload["video_state"] = "SCHEDULED"
            finish_payload["scheduled_publish_time"] = scheduled_unix
        finish = _read_response(
            requests.post(endpoint, data=finish_payload, timeout=60),
            "Reel publishing",
        )
        if not finish.get("success"):
            raise RuntimeError(f"Reel publishing was not confirmed: {finish}")

        comment_status = "none"
        if first_comment and scheduled_unix is None:
            comment_status = "posted" if self.post_comment(video_id, first_comment) else "pending"
        elif first_comment:
            comment_status = "pending"
            print("[!] First comment not posted: scheduled Reels cannot be commented on yet.")
        self._log_status("Reel", video_id, scheduled_unix)
        return {
            "video_id": video_id,
            "type": "reel",
            "scheduled_unix": scheduled_unix,
            "comment_status": comment_status,
        }

    def is_post_published(self, object_id: str, is_reel: bool = False) -> bool:
        fields = "status" if is_reel else "is_published"
        result = _read_response(
            requests.get(
                f"{BASE_URL}/{object_id}",
                params={"fields": fields, "access_token": self.access_token},
                timeout=30,
            ),
            "Post publishing status",
        )
        if not is_reel:
            return bool(result.get("is_published"))
        status = result.get("status") or {}
        phase = status.get("publishing_phase") or {}
        return str(phase.get("publish_status", "")).casefold() == "published"

    def post_comment(self, object_id: str, message: str) -> bool:
        try:
            result = _read_response(
                requests.post(
                    f"{BASE_URL}/{object_id}/comments",
                    data={"message": message, "access_token": self.access_token},
                    timeout=30,
                ),
                "First comment",
            )
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            print(f"[!] First comment request failed: {exc}")
            return False
        if result.get("id"):
            print(f"    [+] First comment added: {result['id']}")
            return True
        else:
            print(f"[!] First comment response did not contain an ID: {result}")
            return False

    @staticmethod
    def _log_status(kind: str, post_id: str, scheduled_unix: int | None) -> None:
        if scheduled_unix is None:
            print(f"[OK] {kind} published now -> ID: {post_id}")
        else:
            scheduled_at = datetime.fromtimestamp(scheduled_unix, tz=timezone.utc)
            print(f"[OK] {kind} scheduled for {scheduled_at.isoformat()} -> ID: {post_id}")


if __name__ == "__main__":
    page_id = os.getenv("FB_PAGE_ID")
    token = os.getenv("FB_PAGE_ACCESS_TOKEN")
    if not page_id or not token:
        print("Set FB_PAGE_ID and FB_PAGE_ACCESS_TOKEN to test Page connection.")
    else:
        info = _read_response(
            requests.get(
                f"{BASE_URL}/{page_id}",
                params={
                    "fields": "id,name,fan_count",
                    "access_token": token,
                },
                timeout=15,
            ),
            "Page connection test",
        )
        print("Connected Page Info:", json.dumps(info, indent=2))
