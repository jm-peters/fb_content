import asyncio
import io
import os
import subprocess
import textwrap
from pathlib import Path

import edge_tts
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

WIDTH = 1080
HEIGHT = 1920
FPS = 30
PIXABAY_API_URL = "https://pixabay.com/api/"
VOICE = "en-US-AndrewNeural"
BG_COLOR = (13, 17, 23)
CARD_COLOR = (22, 30, 42)
CYAN = (56, 189, 248)
GREEN = (16, 185, 129)
WHITE = (248, 250, 252)
MUTED = (148, 163, 184)


def _format_ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centis:02d}"


def _run_ffmpeg(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "no diagnostic output").strip()
        raise RuntimeError(f"FFmpeg failed: {detail[-2000:]}") from exc


def _ass_safe_text(value: str) -> str:
    return value.replace("\\", "/").replace("{", "").replace("}", "").replace("\n", " ")


async def _generate_tts_and_subs(script_text: str, audio_path: str, ass_path: str) -> float:
    """Generate an Edge TTS voice track and word-timed ASS karaoke captions."""
    word_timings = []
    communicate = edge_tts.Communicate(script_text, VOICE, rate="+6%")
    with open(audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                end = start + chunk["duration"] / 10_000_000
                word_timings.append((chunk["text"], start, end))

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(probe.stdout.strip())
    if not word_timings:
        words = script_text.split()
        word_duration = duration / max(1, len(words))
        word_timings = [
            (word, index * word_duration, (index + 1) * word_duration)
            for index, word in enumerate(words)
        ]

    events = []
    group_size = 4
    for offset in range(0, len(word_timings), group_size):
        group = word_timings[offset:offset + group_size]
        start = group[0][1]
        end = word_timings[offset + group_size][1] if offset + group_size < len(word_timings) else duration
        karaoke_words = []
        for word, word_start, word_end in group:
            centiseconds = max(1, round((word_end - word_start) * 100))
            karaoke_words.append(f"{{\\kf{centiseconds}}}{_ass_safe_text(word)}")
        events.append((start, max(start + 0.05, end), " ".join(karaoke_words)))

    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,68,&H00FFFFFF,&H00F8BD38,&H00121212,&H80000000,-1,0,0,0,100,100,1,0,1,6,2,2,70,70,390,1
Style: Brand,DejaVu Sans,34,&H00F8BD38,&H00FFFFFF,&H00121212,&H00000000,-1,0,0,0,100,100,2,0,1,3,0,8,40,40,95,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,0:00:00.00,{_format_ass_time(duration)},Brand,,0,0,0,,SMARTSORT.TECH // STEP-BY-STEP
"""
    with open(ass_path, "w", encoding="utf-8") as subtitle_file:
        subtitle_file.write(ass_header)
        for start, end, phrase in events:
            subtitle_file.write(
                f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},"
                f"Default,,0,0,0,,{phrase}\n"
            )
    return duration


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (
        ["DejaVuSans-Bold.ttf", "arialbd.ttf"]
        if bold else ["DejaVuSans.ttf", "arial.ttf"]
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    width: int,
    line_height: int,
    max_lines: int,
) -> int:
    lines = textwrap.wrap(text, width=width) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .") + "..."
    y = xy[1]
    for line in lines:
        draw.text((xy[0], y), line, font=font, fill=fill)
        y += line_height
    return y


def _pixabay_background(query: str, api_key: str) -> Image.Image | None:
    try:
        response = requests.get(
            PIXABAY_API_URL,
            params={
                "key": api_key,
                "q": " ".join(query.split())[:100],
                "image_type": "photo",
                "safesearch": "true",
                "per_page": 3,
            },
            timeout=20,
        )
    except requests.RequestException:
        raise RuntimeError("Pixabay image search request failed.") from None
    if response.status_code >= 400:
        raise RuntimeError(f"Pixabay image search failed with HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("Pixabay image search returned invalid JSON.") from None
    hits = payload.get("hits", [])
    image_url = next(
        (hit.get("webformatURL") for hit in hits if hit.get("webformatURL")),
        None,
    )
    if not image_url:
        return None

    try:
        image_response = requests.get(image_url, timeout=30)
    except requests.RequestException:
        raise RuntimeError("Could not download the selected Pixabay image.") from None
    if image_response.status_code >= 400:
        raise RuntimeError(
            f"Pixabay image download failed with HTTP {image_response.status_code}."
        )
    try:
        with Image.open(io.BytesIO(image_response.content)) as image:
            return image.convert("RGB")
    except (OSError, ValueError):
        raise RuntimeError("Pixabay returned invalid image data.") from None


def _make_terminal_card(
    scene: dict,
    index: int,
    count: int,
    title: str,
    output: Path,
    background: Image.Image | None = None,
) -> None:
    if background is None:
        image = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    else:
        fitted_background = ImageOps.fit(background, (WIDTH, HEIGHT)).convert("RGBA")
        overlay = Image.new("RGBA", (WIDTH, HEIGHT), (*BG_COLOR, 205))
        image = Image.alpha_composite(fitted_background, overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    for x in range(0, WIDTH, 90):
        draw.line((x, 0, x, HEIGHT), fill=(24, 32, 44), width=2)
    for y in range(0, HEIGHT, 90):
        draw.line((0, y, WIDTH, y), fill=(24, 32, 44), width=2)

    draw.rectangle((0, 0, WIDTH, 14), fill=CYAN)
    draw.rounded_rectangle((64, 86, 1016, 166), radius=20, fill=CARD_COLOR, outline=CYAN, width=2)
    draw.text((92, 109), "SMARTSORT // FIELD NOTES", font=_load_font(30, True), fill=CYAN)
    draw.text((820, 111), f"[{index:02d}/{count:02d}]", font=_load_font(28, True), fill=WHITE)

    draw.rounded_rectangle((64, 290, 1016, 1380), radius=34, fill=CARD_COLOR, outline=(43, 58, 76), width=3)
    entity_name = scene.get("entity_name") or "SMARTSORT"
    badge = entity_name[:2].upper()
    draw.rounded_rectangle((100, 314, 158, 372), radius=14, fill=GREEN)
    draw.text((112, 328), badge, font=_load_font(24, True), fill=BG_COLOR)
    draw.text((180, 322), "SMARTSORT BREAKDOWN", font=_load_font(26, True), fill=GREEN)
    draw.line((100, 390, 980, 390), fill=(43, 58, 76), width=2)

    y = _draw_wrapped(
        draw,
        scene.get("on_screen_text") or title or f"Step {index}",
        (104, 440),
        _load_font(58, True),
        WHITE,
        24,
        76,
        3,
    )
    details = [
        ("PAY / IMPACT", scene.get("pay_or_impact")),
        ("ENTRY REQUIREMENT", scene.get("requirement")),
        ("DIFFICULTY", scene.get("difficulty")),
    ]
    visible_details = [(label, value) for label, value in details if value]
    if not visible_details and (scene.get("visual_prompt") or scene.get("card_detail")):
        visible_details = [("KEY DETAIL", scene.get("visual_prompt") or scene.get("card_detail"))]
    if visible_details:
        y = max(y + 34, 690)
        panel_bottom = min(y + 110 + 105 * len(visible_details), 1210)
        draw.rounded_rectangle(
            (100, y, 980, panel_bottom), radius=22, fill=BG_COLOR, outline=CYAN, width=2
        )
        row_y = y + 20
        for label, value in visible_details:
            draw.text((132, row_y), label, font=_load_font(23, True), fill=CYAN)
            _draw_wrapped(
                draw, str(value), (132, row_y + 32), _load_font(30, True), WHITE, 42, 38, 2
            )
            if label == "DIFFICULTY":
                level = str(value).casefold()
                active_bars = 1 if "beginner" in level else 3 if "advanced" in level else 2
                for bar in range(3):
                    draw.rounded_rectangle(
                        (850 + bar * 38, row_y + 41, 876 + bar * 38, row_y + 57),
                        radius=7,
                        fill=GREEN if bar < active_bars else (43, 58, 76),
                    )
            row_y += 105

    footer = "REALISTIC STEPS  •  VERIFY CURRENT TERMS"
    draw.text((104, 1290), footer, font=_load_font(23, True), fill=MUTED)
    draw.text((96, 1735), "SAVE BEFORE IT GETS BURIED", font=_load_font(24, True), fill=GREEN)
    draw.text((96, 1815), "smartsort.tech", font=_load_font(30, True), fill=CYAN)
    image.save(output, "PNG")


def _scene_cards(
    reel_data: dict,
    work_dir: Path,
    duration: float,
    pixabay_api_key: str,
) -> list[tuple[Path, float]]:
    source_scenes = reel_data.get("scenes") or []
    scenes = [
        {
            "on_screen_text": scene.get("on_screen_text") or scene.get("card_title"),
            "visual_prompt": scene.get("visual_prompt") or scene.get("card_detail"),
            "entity_name": scene.get("entity_name"),
            "pay_or_impact": scene.get("pay_or_impact"),
            "requirement": scene.get("requirement"),
            "difficulty": scene.get("difficulty"),
            "duration_seconds": scene.get("duration_seconds", 1),
        }
        for scene in source_scenes
    ]
    if not scenes:
        scenes = [
            {"on_screen_text": reel_data.get("title", "SmartSort Breakdown"),
             "visual_prompt": ", ".join(reel_data.get("visual_keywords", [])),
             "duration_seconds": 1}
        ]

    requested = [max(1, int(scene["duration_seconds"])) for scene in scenes]
    total_requested = sum(requested)
    segments = []
    elapsed = 0.0
    for index, (scene, requested_duration) in enumerate(zip(scenes, requested), start=1):
        segment_duration = (
            duration - elapsed
            if index == len(scenes)
            else duration * requested_duration / total_requested
        )
        segment_duration = max(0.1, segment_duration)
        output = work_dir / f"scene_{index:02d}.png"
        background = _pixabay_background(scene.get("visual_prompt", ""), pixabay_api_key)
        if background is None:
            print(f"[!] Pixabay found no image for Reel scene {index}; using the branded background.")
        _make_terminal_card(
            scene,
            index,
            len(scenes),
            reel_data.get("title", ""),
            output,
            background,
        )
        segments.append((output, segment_duration))
        elapsed += segment_duration
    return segments


def render_reel(reel_data: dict, output_path: str, work_dir: str = "build_tmp") -> str:
    """Render a vertical, terminal-card Reel with voiceover and synced captions."""
    pixabay_api_key = os.getenv("PIXABAY_API_KEY")
    if not pixabay_api_key:
        raise ValueError("PIXABAY_API_KEY environment variable is missing.")

    tmp = Path(work_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    day_slug = (reel_data.get("day") or reel_data.get("day_of_week") or "reel").lower()
    audio_path = tmp / f"{day_slug}_voice.mp3"
    ass_path = tmp / f"{day_slug}_subs.ass"
    raw_video_path = tmp / f"{day_slug}_cards.mp4"

    hook = (reel_data.get("hook") or reel_data.get("hook_title") or "").strip()
    body = (reel_data.get("script") or "").strip()
    if not body and reel_data.get("scenes"):
        body = " ".join(scene.get("voiceover_text", "").strip() for scene in reel_data["scenes"])
    narration = body if not hook or body.casefold().startswith(hook.casefold()) else f"{hook} {body}".strip()
    if not narration:
        raise ValueError("Reel requires a non-empty hook or voiceover script.")

    print(f"[*] Generating TTS voiceover and captions for {day_slug.capitalize()} Reel...")
    audio_duration = asyncio.run(_generate_tts_and_subs(narration, str(audio_path), str(ass_path)))
    if not 3 <= audio_duration <= 90:
        raise ValueError(f"Rendered Reel audio must be 3-90 seconds; got {audio_duration:.1f}.")
    duration = audio_duration + 0.2
    scene_segments = _scene_cards(reel_data, tmp, duration, pixabay_api_key)

    ffmpeg_args = ["ffmpeg", "-y"]
    filters = []
    inputs = []
    for index, (image_path, segment_duration) in enumerate(scene_segments):
        ffmpeg_args.extend(
            ["-loop", "1", "-framerate", str(FPS), "-t", f"{segment_duration:.3f}", "-i", str(image_path)]
        )
        filters.append(
            f"[{index}:v]zoompan=z='min(zoom+0.0003,1.035)':d=1:"
            f"s={WIDTH}x{HEIGHT}:fps={FPS},setsar=1,format=yuv420p[v{index}]"
        )
        inputs.append(f"[v{index}]")
    filters.append(f"{''.join(inputs)}concat=n={len(inputs)}:v=1:a=0[outv]")
    ffmpeg_args.extend(
        [
            "-filter_complex", ";".join(filters), "-map", "[outv]", "-t", f"{duration:.3f}",
            "-an", "-c:v", "libx264", "-preset", "fast", "-g", "120",
            "-keyint_min", "60", "-sc_threshold", "0", "-pix_fmt", "yuv420p",
            str(raw_video_path),
        ]
    )
    _run_ffmpeg(ffmpeg_args)

    ass_filter_path = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")
    print(f"[*] Burning captions and encoding final Reel -> {output}")
    _run_ffmpeg(
        [
            "ffmpeg", "-y", "-i", str(raw_video_path), "-i", str(audio_path),
            "-vf", f"ass='{ass_filter_path}'", "-c:v", "libx264", "-preset", "medium",
            "-crf", "22", "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-ac", "2", "-g", "120", "-keyint_min", "60", "-sc_threshold", "0",
            "-shortest",
            "-pix_fmt", "yuv420p", str(output),
        ]
    )
    print(f"[OK] Reel ready: {output} ({duration:.1f}s)")
    return str(output)
