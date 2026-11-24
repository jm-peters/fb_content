import textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Brand Palette: SmartSort terminal slate + electric cyan and verified green
BG_COLOR = (13, 17, 23)          # #0D1117
CARD_BG = (22, 30, 42)
ACCENT_CYAN = (56, 189, 248)     # #38BDF8
ACCENT_AMBER = (16, 185, 129)   # #10B981
TEXT_WHITE = (248, 250, 252)     # #F8FAFC
TEXT_MUTED = (148, 163, 184)     # #94A3B8


def load_font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    # Works seamlessly on both Ubuntu (GitHub Actions) and Windows/Mac
    if mono:
        candidates = (
            ["DejaVuSansMono-Bold.ttf", "consolab.ttf"]
            if bold
            else ["DejaVuSansMono.ttf", "consola.ttf"]
        )
    elif bold:
        candidates = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "arialbd.ttf",
            "DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "arial.ttf",
            "DejaVuSans.ttf",
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_header_and_footer(draw: ImageDraw.ImageDraw, slide_num: int, total_slides: int, tag: str):
    f_brand = load_font(27, bold=True, mono=True)
    f_tag = load_font(23, bold=True, mono=True)
    f_footer = load_font(24, bold=False, mono=True)

    # Top-left brand pill
    draw.text((70, 65), "SMARTSORT // TERMINAL", fill=ACCENT_CYAN, font=f_brand)

    # Top-right category pill
    bbox = draw.textbbox((0, 0), tag.upper(), font=f_tag)
    tag_w = bbox[2] - bbox[0]
    draw.rounded_rectangle(
        [1010 - tag_w - 36, 56, 1010, 108], radius=14, fill=CARD_BG, outline=ACCENT_CYAN, width=2
    )
    draw.text((1010 - tag_w - 18, 67), tag.upper(), fill=TEXT_WHITE, font=f_tag)

    # Bottom progress bar + swipe prompt
    draw.line([(70, 1235), (1010, 1235)], fill=CARD_BG, width=4)
    progress_w = int(940 * (slide_num / total_slides))
    draw.line([(70, 1235), (70 + progress_w, 1235)], fill=ACCENT_CYAN, width=6)

    draw.text((70, 1258), f"[{slide_num:02d} / {total_slides:02d}]", fill=TEXT_MUTED, font=f_footer)
    swipe_text = "SWIPE FOR NEXT ->" if slide_num < total_slides else "SAVE & SHARE THIS GUIDE"
    draw.text((740 if slide_num < total_slides else 670, 1258), swipe_text, fill=ACCENT_AMBER, font=f_footer)


def render_carousel(post_id: str, pillar_tag: str, carousel_data: dict, out_root: Path = Path("output_fb")) -> list[Path]:
    post_dir = out_root / post_id
    post_dir.mkdir(parents=True, exist_ok=True)

    slides_content = carousel_data["slides"]
    total_slides = len(slides_content) + 2  # Cover + Content Slides + Action Summary Slide
    generated_paths = []

    f_hero = load_font(74, bold=True)
    f_title = load_font(54, bold=True)
    f_body = load_font(38, bold=False)
    # --- SLIDE 1: HOOK COVER SLIDE ---
    img = Image.new("RGB", (1080, 1350), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw_header_and_footer(draw, 1, total_slides, pillar_tag)

    # Decorative accent bar
    draw.rounded_rectangle([70, 250, 190, 266], radius=8, fill=ACCENT_AMBER)

    wrapped_cover = textwrap.wrap(carousel_data["cover_title"], width=22)
    y = 310
    for line in wrapped_cover:
        draw.text((70, y), line, fill=TEXT_WHITE, font=f_hero)
        y += 92

    # Subtitle card
    y += 40
    sub_lines = textwrap.wrap(carousel_data["cover_subtitle"], width=42)
    card_h = len(sub_lines) * 52 + 60
    draw.rounded_rectangle([70, y, 1010, y + card_h], radius=24, fill=CARD_BG)
    sub_y = y + 30
    for line in sub_lines:
        draw.text((105, sub_y), line, fill=ACCENT_CYAN, font=f_body)
        sub_y += 52

    p1 = post_dir / "slide_01.png"
    img.save(p1, "PNG")
    generated_paths.append(p1)

    # --- CONTENT SLIDES (2 .. N-1) ---
    for idx, slide in enumerate(slides_content, start=2):
        img = Image.new("RGB", (1080, 1350), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw_header_and_footer(draw, idx, total_slides, pillar_tag)

        # Number badge
        draw.rounded_rectangle([70, 185, 205, 242], radius=14, fill=ACCENT_CYAN)
        draw.text((88, 199), f"STEP {idx - 1:02d}", fill=BG_COLOR, font=load_font(24, bold=True, mono=True))

        # Slide Heading
        heading_lines = textwrap.wrap(slide["heading"], width=28) or [""]
        if len(heading_lines) > 3:
            heading_lines = heading_lines[:3]
            heading_lines[-1] = heading_lines[-1].rstrip(" .") + "..."
        y = 300
        for line in heading_lines:
            draw.text((70, y), line, fill=TEXT_WHITE, font=f_title)
            y += 68

        # Main Plain-English Explanation
        y += 28
        body_lines = textwrap.wrap(slide["body"], width=50) or [""]
        if len(body_lines) > 7:
            body_lines = body_lines[:7]
            body_lines[-1] = body_lines[-1].rstrip(" .") + "..."
        for line in body_lines:
            draw.text((70, y), line, fill=TEXT_MUTED, font=load_font(34))
            y += 44

        # Bottom Callout Box (Requirements / Action Step / Pro Tip)
        if slide.get("callout"):
            callout_lines = textwrap.wrap(slide["callout"], width=48)
            if len(callout_lines) > 3:
                callout_lines = callout_lines[:3]
                callout_lines[-1] = callout_lines[-1].rstrip(" .") + "..."
            box_h = len(callout_lines) * 42 + 92
            box_top = min(max(y + 35, 875), 975)
            draw.rounded_rectangle(
                [70, box_top, 1010, box_top + box_h], radius=22, fill=CARD_BG, outline=ACCENT_AMBER, width=2
            )
            callout_label = "COPY / PASTE" if slide.get("slide_type") == "code_tip" else "SMARTSORT TIP"
            draw.text(
                (105, box_top + 18),
                f"[ {callout_label} ]",
                fill=ACCENT_CYAN,
                font=load_font(22, bold=True, mono=True),
            )
            cy = box_top + 48
            for cline in callout_lines:
                draw.text((105, cy), cline, fill=ACCENT_AMBER, font=load_font(30, bold=True))
                cy += 42

        p_slide = post_dir / f"slide_{idx:02d}.png"
        img.save(p_slide, "PNG")
        generated_paths.append(p_slide)

    # --- FINAL SLIDE: SUMMARY & CONVERSATION STARTER ---
    img = Image.new("RGB", (1080, 1350), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw_header_and_footer(draw, total_slides, total_slides, pillar_tag)

    draw.text((70, 260), "Quick Action Checklist", fill=ACCENT_AMBER, font=f_title)
    summary_lines = textwrap.wrap(carousel_data["closing_takeaway"], width=40)
    if len(summary_lines) > 5:
        summary_lines = summary_lines[:5]
        summary_lines[-1] = summary_lines[-1].rstrip(" .") + "..."
    y = 370
    for line in summary_lines:
        draw.text((70, y), line, fill=TEXT_WHITE, font=f_body)
        y += 56

    draw.rounded_rectangle([70, 760, 1010, 1030], radius=24, fill=CARD_BG)
    q_lines = textwrap.wrap(carousel_data["discussion_question"], width=38)
    if len(q_lines) > 3:
        q_lines = q_lines[:3]
        q_lines[-1] = q_lines[-1].rstrip(" .") + "..."
    qy = 810
    for qline in q_lines:
        draw.text((105, qy), qline, fill=ACCENT_CYAN, font=f_body)
        qy += 54

    p_last = post_dir / f"slide_{total_slides:02d}.png"
    img.save(p_last, "PNG")
    generated_paths.append(p_last)

    return generated_paths


def build_carousel_slides(carousel_data: dict, output_dir: str | Path) -> list[str]:
    """Render a generated carousel into ordered 1080x1350 PNG slide paths."""
    required = ("cover_title", "cover_subtitle", "slides", "closing_takeaway", "discussion_question")
    missing = [key for key in required if key not in carousel_data]
    if missing:
        raise ValueError(f"Carousel is missing required fields: {', '.join(missing)}")
    if not carousel_data["slides"]:
        raise ValueError("Carousel must contain at least one content slide")

    output_path = Path(output_dir)
    paths = render_carousel(
        post_id=output_path.name,
        pillar_tag=carousel_data.get("tag", carousel_data.get("pillar", "SMARTSORT")),
        carousel_data=carousel_data,
        out_root=output_path.parent,
    )
    return [str(path) for path in paths]
