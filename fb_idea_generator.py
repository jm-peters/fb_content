import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Literal, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

EAT_TZ = timezone(timedelta(hours=3))
DEFAULT_PLAN_PATH = Path("data/weekly_content_plan.json")
DEFAULT_HISTORY_PATH = Path("history.json")


class CarouselSlide(BaseModel):
    slide_number: int
    slide_type: Literal["cover", "content", "code_tip", "summary_cta"]
    badge_text: str
    headline: str = Field(description="Short title, ideally 10 words or fewer")
    body_points: List[str] = Field(
        description="Two to four concise, scannable points",
        min_length=2,
        max_length=4,
    )
    pro_tip_or_code: Optional[str] = None


class CarouselPost(BaseModel):
    day_of_week: str
    pillar: str
    caption: str
    first_comment: str
    slides: List[CarouselSlide] = Field(
        description="Five or six slides: cover, content, summary",
        min_length=5,
        max_length=6,
    )


class ReelScene(BaseModel):
    scene_number: int
    duration_seconds: int
    voiceover_text: str
    on_screen_text: str = Field(description="Short bold card heading")
    visual_prompt: str = Field(description="One concise fact, requirement, or visual detail for the card")
    entity_name: Optional[str] = Field(
        default=None,
        description="Platform/tool name or workflow label shown in the card badge",
    )
    pay_or_impact: Optional[str] = Field(
        default=None,
        description="Verified pay range or practical impact; state 'Varies' rather than guessing",
    )
    requirement: Optional[str] = Field(
        default=None,
        description="Specific entry requirement or one concrete action",
    )
    difficulty: Optional[str] = Field(
        default=None,
        description="Beginner, intermediate, or advanced; do not overstate ease",
    )


class ReelPost(BaseModel):
    day_of_week: str
    pillar: str
    hook_title: str
    caption: str
    first_comment: str
    total_duration_seconds: int = Field(ge=3, le=90)
    scenes: List[ReelScene] = Field(
        description="Three or four short scenes",
        min_length=3,
        max_length=4,
    )


WEEKLY_SCHEDULE = [
    {
        "day": "Monday",
        "hour_eat": 19,
        "format": "carousel",
        "pillar": "Online Income & Task Sites",
        "brief": (
            "Give a realistic beginner guide to legitimate remote task platforms. "
            "State entry requirements and payout caveats; do not promise earnings."
        ),
    },
    {
        "day": "Tuesday",
        "hour_eat": 19,
        "format": "reel",
        "pillar": "If You're Online Making Nothing, Try This",
        "brief": "A 35-45 second practical workflow with realistic expectations and a strong opening hook.",
    },
    {
        "day": "Wednesday",
        "hour_eat": 18,
        "format": "carousel",
        "pillar": "AI Usage & Everyday Productivity",
        "brief": "A practical AI workflow with a reusable prompt or free-tool workflow.",
    },
    {
        "day": "Thursday",
        "hour_eat": 19,
        "format": "reel",
        "pillar": "AI & Tech Problem-Solver",
        "brief": "A 35-45 second Reel solving a relatable everyday tech or AI problem.",
    },
    {
        "day": "Friday",
        "hour_eat": 18,
        "format": "carousel",
        "pillar": "Clean Programming & Dev Shortcuts",
        "brief": "A scannable coding, Git, or VS Code guide with a concrete example.",
    },
    {
        "day": "Saturday",
        "hour_eat": 11,
        "format": "reel",
        "pillar": "Beginner-Friendly Coding & Automation Hack",
        "brief": "A 30-40 second practical automation or developer tip, explained without jargon.",
    },
    {
        "day": "Sunday",
        "hour_eat": 17,
        "format": "carousel",
        "pillar": "Weekly AI & Tech News Digest",
        "brief": (
            "Summarize four useful AI/tech developments from the past seven days, "
            "with a clear date and a practical implication for each."
        ),
    },
]

SYSTEM_INSTRUCTION = """
You are the practical, fact-conscious content strategist for smartsort.tech.
Write for students, job seekers, freelancers, and aspiring developers, especially
in Kenya and other emerging remote-work markets. Be direct, helpful, and honest.
Never promise income or invent platform requirements, payout methods, or news.
If a detail is uncertain, qualify it and direct readers to verify current terms.
Never put clickable URLs in the main caption. Use the first comment for
searchable names and extra context. End Reels with a useful question or save CTA.
Use concise wording that fits a 1080x1350 carousel or a vertical terminal UI card.
"""

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
FALLBACK_GEMINI_MODELS = ("gemini-3.6-flash", "gemini-3.5-flash-lite")


def get_next_monday_eat(now: Optional[datetime] = None) -> datetime:
    """Return the next Monday at 00:00 EAT, or this Monday before 08:00 EAT."""
    now = now or datetime.now(EAT_TZ)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(EAT_TZ)
    days_ahead = (7 - now.weekday()) % 7
    if days_ahead == 0 and now.hour >= 8:
        days_ahead = 7
    return (now + timedelta(days=days_ahead)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _generate_content_with_fallback(client, model_name: str, contents: str, config):
    models = list(dict.fromkeys((model_name, *FALLBACK_GEMINI_MODELS)))
    for index, candidate in enumerate(models):
        try:
            response = client.models.generate_content(
                model=candidate,
                contents=contents,
                config=config,
            )
        except genai.errors.APIError as exc:
            if exc.code != 404 or exc.status != "NOT_FOUND" or index == len(models) - 1:
                raise
            print(
                f"[!] Gemini model {candidate} is unavailable; "
                f"trying {models[index + 1]}."
            )
        else:
            if candidate != model_name:
                print(f"[*] Gemini model fallback selected: {candidate}")
            return response, candidate


def _read_analytics_feedback(history_path: Path) -> str:
    if not history_path.exists():
        return "No prior analytics. Prioritize practical, high-utility evergreen guides."
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[!] Analytics history unavailable: {exc}")
        return "Analytics unavailable. Prioritize practical, high-utility guides."
    if not isinstance(history, dict):
        print("[!] Analytics history is not a JSON object; ignoring it.")
        return "Analytics unavailable. Prioritize practical, high-utility guides."
    winners = history.get("top_performing_topics", [])
    return f"Topics that performed well previously: {winners or 'not enough data'}."


def _normalize_carousel(post: CarouselPost, slot: dict) -> dict:
    slides = post.slides
    if not 5 <= len(slides) <= 6 or slides[0].slide_type != "cover":
        raise ValueError(f"{slot['day']} carousel must contain 5-6 slides and start with a cover")
    if slides[-1].slide_type != "summary_cta":
        raise ValueError(f"{slot['day']} carousel must end with a summary_cta slide")
    content = slides[1:-1]
    if not content:
        raise ValueError(f"{slot['day']} carousel must include content slides")

    return {
        "day": slot["day"],
        "title": slides[0].headline,
        "pillar": post.pillar or slot["pillar"],
        "tag": slot["pillar"],
        "cover_title": slides[0].headline,
        "cover_subtitle": " ".join(slides[0].body_points),
        "slides": [
            {
                "heading": slide.headline,
                "body": " • ".join(slide.body_points),
                "callout": slide.pro_tip_or_code or "",
                "tag": slide.badge_text,
                "slide_type": slide.slide_type,
            }
            for slide in content
        ],
        "closing_takeaway": " ".join(slides[-1].body_points),
        "discussion_question": (
            slides[-1].pro_tip_or_code
            or "Which step will you try first? Share your experience below."
        ),
        "caption": post.caption,
        "first_comment": post.first_comment,
    }


def _normalize_reel(post: ReelPost, slot: dict) -> dict:
    if not 3 <= post.total_duration_seconds <= 90:
        raise ValueError(f"{slot['day']} Reel duration must be between 3 and 90 seconds")
    if not post.scenes:
        raise ValueError(f"{slot['day']} Reel must contain at least one scene")
    script_parts = [scene.voiceover_text.strip() for scene in post.scenes if scene.voiceover_text.strip()]
    if not script_parts:
        raise ValueError(f"{slot['day']} Reel has no voiceover")
    return {
        "day": slot["day"],
        "title": post.hook_title,
        "hook": post.hook_title,
        "script": " ".join(script_parts),
        "scenes": [scene.model_dump() for scene in post.scenes],
        "visual_keywords": [scene.visual_prompt for scene in post.scenes],
        "caption": post.caption,
        "first_comment": post.first_comment,
    }


def generate_weekly_plan(
    past_topics: Optional[list[str]] = None,
    winning_topics: Optional[list[str]] = None,
    output_path: str | Path = DEFAULT_PLAN_PATH,
) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing.")

    model_name = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    client = genai.Client(api_key=api_key)
    base_monday = get_next_monday_eat()
    feedback = _read_analytics_feedback(DEFAULT_HISTORY_PATH)
    avoid_topics = past_topics or []
    winners = winning_topics or []
    plan = {"week_start": base_monday.date().isoformat(), "carousels": [], "reels": []}

    for day_offset, slot in enumerate(WEEKLY_SCHEDULE):
        post_dt = (base_monday + timedelta(days=day_offset)).replace(hour=slot["hour_eat"])
        scheduled_unix = int(post_dt.timestamp())
        schema = CarouselPost if slot["format"] == "carousel" else ReelPost
        request_text = f"""
Create the {slot['day']} {slot['format']} for smartsort.tech.
Pillar: {slot['pillar']}
Brief: {slot['brief']}
Scheduled time (EAT): {post_dt.strftime('%Y-%m-%d %H:%M %Z')}
Previously used topics to avoid repeating: {avoid_topics[-60:]}
Topics that have performed well (use only as inspiration): {winners[:10]}
Analytics context: {feedback}
For Sunday, use current reliable sources and cover only developments from the last
seven days. Include source names and publication dates in the content or first comment.
"""
        config_kwargs = {
            "system_instruction": SYSTEM_INSTRUCTION,
            "response_mime_type": "application/json",
            "response_schema": schema,
        }
        if slot["day"] == "Sunday":
            config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
        print(f"Generating {slot['day']} ({slot['format'].upper()}) — {slot['pillar']}...")
        response, model_name = _generate_content_with_fallback(
            client=client,
            model_name=model_name,
            contents=request_text,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        parsed = response.parsed
        if parsed is None:
            if not response.text:
                raise RuntimeError(f"Gemini returned no structured content for {slot['day']}")
            parsed = schema.model_validate_json(response.text)
        else:
            parsed = schema.model_validate(parsed)

        normalized = (
            _normalize_carousel(parsed, slot)
            if slot["format"] == "carousel"
            else _normalize_reel(parsed, slot)
        )
        normalized["scheduled_unix_time"] = scheduled_unix
        normalized["scheduled_readable_eat"] = post_dt.strftime("%Y-%m-%d %H:%M EAT")
        plan["carousels" if slot["format"] == "carousel" else "reels"].append(normalized)

    titles = [post["title"] for group in ("carousels", "reels") for post in plan[group]]
    if len(titles) != len(set(title.casefold() for title in titles)):
        raise ValueError("Gemini generated duplicate titles in the weekly plan; refusing to publish.")
    previous_titles = {title.strip().casefold() for title in avoid_topics}
    repeated = [title for title in titles if title.strip().casefold() in previous_titles]
    if repeated:
        raise ValueError(f"Gemini repeated recently used topics: {repeated}; refusing to publish.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return plan
