#!/usr/bin/env python3
"""Build a detailed research corpus from the Nanyotti Telegram export."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader


DEFAULT_EXPORT_DIR = Path("/Users/yumin/Downloads/Telegram Desktop/ChatExport_2026-05-26")
DEFAULT_OUTPUT_DIR = Path("reports/research/nanyotti_export/deep_dive")

LOCAL_ATTACHMENT_PREFIXES = ("photos/", "video_files/", "files/", "images/")
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
PDF_EXTS = {".pdf"}
TEXT_EXTS = {".txt"}

KEYWORD_GROUPS = {
    "trend": ["추세", "상승장", "하락장", "롱추세", "숏추세", "방향", "원웨이", "일방"],
    "cloud": ["구름", "일목", "이평", "갭", "저항", "지지"],
    "mountain": ["산맥"],
    "zone": ["매물대", "박스", "저점", "고점", "꼬리", "전저", "전고", "중앙값", "2구간", "4구간", "6구간", "8구간"],
    "candle": ["캔들", "음봉", "양봉", "돌파", "휩쏘", "FVG", "회복", "추격"],
    "position": ["비중", "물량", "평단", "분할", "불타기", "물타기", "익절", "손절", "축소", "정리"],
    "flip": ["스위칭", "전환", "롱", "숏", "양방"],
    "risk": ["리스크", "청산", "시드", "레버리지", "10배", "풀시드", "위험", "멘탈"],
    "review": ["복기", "라이브", "하이라이트", "챌린지", "매매"],
    "scenario": ["시나리오", "관점", "알람", "구간", "대응", "진입근거"],
}


@dataclass(frozen=True)
class FileMeta:
    rel_path: str
    abs_path: str
    ext: str
    category: str
    size_bytes: int
    mtime_iso: str
    is_thumb: bool
    metadata: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--storyboards", action="store_true", help="Extract contact sheets for videos.")
    parser.add_argument("--frames-per-video", type=int, default=8)
    parser.add_argument("--max-videos", type=int, default=0, help="Limit storyboard generation; 0 means all videos.")
    return parser.parse_args()


def clean_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def parse_telegram_datetime(title: str | None) -> str | None:
    if not title:
        return None
    try:
        parsed = datetime.strptime(title.strip(), "%d.%m.%Y %H:%M:%S UTC%z")
    except ValueError:
        return None
    return parsed.isoformat()


def classify_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in TEXT_EXTS:
        return "text"
    if ext in {".html", ".css", ".js"}:
        return "export_ui"
    return "other"


def safe_slug(value: str, limit: int = 120) -> str:
    slug = re.sub(r"[^\w.\-가-힣]+", "_", value, flags=re.UNICODE).strip("_")
    if len(slug) > limit:
        suffix = Path(slug).suffix
        slug = slug[: limit - len(suffix)] + suffix
    return slug or "item"


def json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def link_for(path: Path, label: str | None = None) -> str:
    return f"[{md_escape(label or path.name)}]({path.as_posix()})"


def parse_messages(export_dir: Path) -> list[dict[str, Any]]:
    html_path = export_dir / "messages.html"
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    messages: list[dict[str, Any]] = []

    for div in soup.find_all("div", class_="message"):
        classes = div.get("class", [])
        message_id = div.get("id", "")
        if "service" in classes:
            body = div.find("div", class_="body")
            messages.append(
                {
                    "id": message_id,
                    "kind": "service",
                    "date_iso": None,
                    "date_title": None,
                    "from_name": None,
                    "text": clean_text(body.get_text("\n", strip=True) if body else ""),
                    "attachments": [],
                    "external_links": [],
                    "reactions": [],
                    "video_duration_label": None,
                }
            )
            continue

        body = div.find("div", class_="body")
        date_div = div.find("div", class_="date")
        from_div = div.find("div", class_="from_name")
        text_div = div.find("div", class_="text")

        attachments: list[dict[str, Any]] = []
        external_links: list[str] = []
        for anchor in div.find_all("a", href=True):
            href = anchor["href"]
            classes_value = " ".join(anchor.get("class", []))
            if href.startswith(("http://", "https://")):
                external_links.append(href)
                continue
            if href.startswith(LOCAL_ATTACHMENT_PREFIXES):
                attachments.append(
                    {
                        "rel_path": href,
                        "category": classify_file(export_dir / href),
                        "classes": classes_value,
                        "exists": (export_dir / href).exists(),
                    }
                )

        reactions: list[dict[str, Any]] = []
        for reaction in div.find_all("span", class_="reaction"):
            emoji = reaction.find("span", class_="emoji")
            count = reaction.find("span", class_="count")
            reactions.append(
                {
                    "emoji": clean_text(emoji.get_text("", strip=True) if emoji else ""),
                    "count": int(clean_text(count.get_text("", strip=True) or "0")) if count else 0,
                }
            )

        duration_div = div.find("div", class_="video_duration")
        messages.append(
            {
                "id": message_id,
                "kind": "message",
                "date_iso": parse_telegram_datetime(date_div.get("title") if date_div else None),
                "date_title": date_div.get("title") if date_div else None,
                "from_name": clean_text(from_div.get_text(" ", strip=True) if from_div else ""),
                "text": clean_text(text_div.get_text("\n", strip=True) if text_div else ""),
                "attachments": attachments,
                "external_links": sorted(set(external_links)),
                "reactions": reactions,
                "video_duration_label": clean_text(duration_div.get_text("", strip=True) if duration_div else ""),
            }
        )

    return messages


def ffprobe(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}
    if proc.returncode != 0:
        return {"error": proc.stderr.strip() or f"ffprobe exited {proc.returncode}"}
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"invalid ffprobe json: {exc}"}

    streams = raw.get("streams", [])
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    fmt = raw.get("format", {})
    duration = fmt.get("duration")
    return {
        "duration_sec": float(duration) if duration not in (None, "N/A") else None,
        "format_name": fmt.get("format_name"),
        "bit_rate": int(fmt["bit_rate"]) if str(fmt.get("bit_rate", "")).isdigit() else None,
        "video_streams": [
            {
                "codec": stream.get("codec_name"),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "r_frame_rate": stream.get("r_frame_rate"),
                "avg_frame_rate": stream.get("avg_frame_rate"),
            }
            for stream in video_streams
        ],
        "audio_streams": [
            {
                "codec": stream.get("codec_name"),
                "channels": stream.get("channels"),
                "sample_rate": stream.get("sample_rate"),
            }
            for stream in audio_streams
        ],
        "has_audio": bool(audio_streams),
    }


def image_meta(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            return {"width": image.width, "height": image.height, "mode": image.mode, "format": image.format}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def extract_pdf_text(path: Path, output_dir: Path) -> dict[str, Any]:
    target_dir = output_dir / "pdf_text"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{safe_slug(path.stem)}.txt"
    try:
        reader = PdfReader(str(path))
        pages = []
        for idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(f"\n\n--- page {idx} ---\n{text}")
        full_text = clean_text("".join(pages))
        target_path.write_text(full_text, encoding="utf-8")
        return {
            "page_count": len(reader.pages),
            "text_chars": len(full_text),
            "text_path": str(target_path),
            "preview": full_text[:1500],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def build_file_inventory(export_dir: Path, output_dir: Path) -> list[FileMeta]:
    files: list[FileMeta] = []
    for path in sorted(p for p in export_dir.rglob("*") if p.is_file()):
        rel_path = path.relative_to(export_dir).as_posix()
        stat = path.stat()
        category = classify_file(path)
        metadata: dict[str, Any] = {}
        if category == "video":
            metadata = ffprobe(path)
        elif category == "image":
            metadata = image_meta(path)
        elif category == "pdf":
            metadata = extract_pdf_text(path, output_dir)
        elif category == "text":
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                metadata = {"text_chars": len(text), "preview": clean_text(text[:1500])}
            except Exception as exc:  # noqa: BLE001
                metadata = {"error": str(exc)}

        files.append(
            FileMeta(
                rel_path=rel_path,
                abs_path=str(path),
                ext=path.suffix.lower(),
                category=category,
                size_bytes=stat.st_size,
                mtime_iso=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                is_thumb="_thumb" in path.stem or path.name.endswith("_thumb.jpg"),
                metadata=metadata,
            )
        )
    return files


def tag_message(text: str) -> list[str]:
    tags: list[str] = []
    lowered = text.lower()
    for group, keywords in KEYWORD_GROUPS.items():
        for keyword in keywords:
            if keyword.lower() in lowered:
                tags.append(group)
                break
    return tags


def build_attachment_records(messages: list[dict[str, Any]], file_by_rel: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for message in messages:
        for attachment in message["attachments"]:
            rel_path = attachment["rel_path"]
            file_meta = file_by_rel.get(rel_path)
            records.append(
                {
                    "message_id": message["id"],
                    "date_iso": message["date_iso"],
                    "date_title": message["date_title"],
                    "text_preview": message["text"][:400],
                    "rel_path": rel_path,
                    "category": attachment["category"],
                    "exists": attachment["exists"],
                    "file_meta": file_meta,
                }
            )
    return records


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(round(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def write_overview(
    output_dir: Path,
    export_dir: Path,
    messages: list[dict[str, Any]],
    file_inventory: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> None:
    message_items = [m for m in messages if m["kind"] == "message"]
    dated = [m["date_iso"] for m in message_items if m["date_iso"]]
    file_counts = Counter(item["category"] for item in file_inventory)
    ext_counts = Counter(item["ext"] or "(none)" for item in file_inventory)
    attachment_counts = Counter(item["category"] for item in attachments)
    total_video_sec = sum(
        (item["metadata"].get("duration_sec") or 0)
        for item in file_inventory
        if item["category"] == "video" and isinstance(item["metadata"], dict)
    )

    keyword_counts = Counter()
    tagged_messages = []
    for message in message_items:
        tags = tag_message(message["text"])
        for tag in tags:
            keyword_counts[tag] += 1
        if tags:
            tagged_messages.append(message)

    lines = [
        "# Nanyotti Telegram Corpus Overview",
        "",
        f"- Export directory: `{export_dir}`",
        f"- Parsed messages: `{len(message_items)}` normal, `{len(messages) - len(message_items)}` service/date separators",
        f"- Date range: `{min(dated) if dated else ''}` to `{max(dated) if dated else ''}`",
        f"- Physical files: `{len(file_inventory)}`",
        f"- Local attachments referenced by messages: `{len(attachments)}`",
        f"- Total video duration by ffprobe: `{fmt_duration(total_video_sec)}`",
        "",
        "## File Categories",
        "",
        "| category | files |",
        "|---|---:|",
    ]
    for category, count in sorted(file_counts.items()):
        lines.append(f"| {category} | {count} |")

    lines.extend(["", "## Extension Counts", "", "| extension | files |", "|---|---:|"])
    for ext, count in sorted(ext_counts.items()):
        lines.append(f"| {ext} | {count} |")

    lines.extend(["", "## Referenced Attachment Categories", "", "| category | references |", "|---|---:|"])
    for category, count in sorted(attachment_counts.items()):
        lines.append(f"| {category} | {count} |")

    lines.extend(["", "## Strategy Keyword Coverage", "", "| tag | messages |", "|---|---:|"])
    for tag, count in keyword_counts.most_common():
        lines.append(f"| {tag} | {count} |")

    lines.extend(
        [
            "",
            "## Output Files",
            "",
            "- `messages.json`: parsed Telegram message records.",
            "- `attachments.json`: message-to-local-file references with file metadata.",
            "- `corpus_inventory.json`: physical file inventory with media metadata.",
            "- `strategy_message_index.md`: message-level strategy evidence index.",
            "- `video_catalog.md`: video metadata and source-message context.",
            "- `pdf_catalog.md`: PDF extraction status and previews.",
            "- `video_storyboards/`: contact sheets when `--storyboards` is used.",
        ]
    )

    (output_dir / "corpus_overview.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_strategy_index(output_dir: Path, messages: list[dict[str, Any]]) -> None:
    rows = []
    for message in messages:
        if message["kind"] != "message":
            continue
        tags = tag_message(message["text"])
        if not tags:
            continue
        attachment_labels = ", ".join(item["rel_path"] for item in message["attachments"])
        text = message["text"]
        rows.append(
            [
                message["date_iso"] or "",
                message["id"],
                ", ".join(tags),
                attachment_labels,
                text[:1200],
            ]
        )

    lines = [
        "# Strategy Message Evidence Index",
        "",
        "이 파일은 전략화에 필요한 메시지를 태그 기준으로 빠짐없이 다시 읽기 위한 원장입니다.",
        "",
        "| date | id | tags | attachments | text preview |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(md_escape(cell) for cell in row) + " |")
    (output_dir / "strategy_message_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_video_catalog(output_dir: Path, attachments: list[dict[str, Any]], file_inventory: list[dict[str, Any]]) -> None:
    attach_by_rel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attachment in attachments:
        if attachment["category"] == "video":
            attach_by_rel[attachment["rel_path"]].append(attachment)

    videos = [item for item in file_inventory if item["category"] == "video"]
    lines = [
        "# Video Catalog",
        "",
        "| rel_path | duration | resolution | audio | message date | message id | message context |",
        "|---|---:|---|---|---|---|---|",
    ]
    for video in videos:
        meta = video["metadata"]
        video_stream = (meta.get("video_streams") or [{}])[0] if isinstance(meta, dict) else {}
        resolution = ""
        if video_stream.get("width") and video_stream.get("height"):
            resolution = f"{video_stream.get('width')}x{video_stream.get('height')}"
        linked = attach_by_rel.get(video["rel_path"], [{}])
        for idx, attachment in enumerate(linked):
            lines.append(
                "| "
                + " | ".join(
                    md_escape(str(value))
                    for value in [
                        video["rel_path"] if idx == 0 else "",
                        fmt_duration(meta.get("duration_sec")) if isinstance(meta, dict) else "",
                        resolution,
                        "yes" if isinstance(meta, dict) and meta.get("has_audio") else "no",
                        attachment.get("date_iso", ""),
                        attachment.get("message_id", ""),
                        attachment.get("text_preview", "")[:500],
                    ]
                )
                + " |"
            )
    (output_dir / "video_catalog.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_pdf_catalog(output_dir: Path, file_inventory: list[dict[str, Any]], attachments: list[dict[str, Any]]) -> None:
    attach_by_rel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attachment in attachments:
        if attachment["category"] == "pdf":
            attach_by_rel[attachment["rel_path"]].append(attachment)

    lines = [
        "# PDF Catalog",
        "",
        "| rel_path | pages | extracted chars | text file | message date | message context |",
        "|---|---:|---:|---|---|---|",
    ]
    for item in file_inventory:
        if item["category"] != "pdf":
            continue
        meta = item["metadata"]
        linked = attach_by_rel.get(item["rel_path"], [{}])
        for idx, attachment in enumerate(linked):
            text_path = Path(meta.get("text_path", "")) if isinstance(meta, dict) and meta.get("text_path") else None
            lines.append(
                "| "
                + " | ".join(
                    md_escape(str(value))
                    for value in [
                        item["rel_path"] if idx == 0 else "",
                        meta.get("page_count", "") if isinstance(meta, dict) else "",
                        meta.get("text_chars", "") if isinstance(meta, dict) else "",
                        link_for(text_path, text_path.name) if text_path else "",
                        attachment.get("date_iso", ""),
                        attachment.get("text_preview", "")[:500],
                    ]
                )
                + " |"
            )
    (output_dir / "pdf_catalog.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def extract_frame(video_path: Path, timestamp: float, target_path: Path) -> bool:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=360:-1",
        "-y",
        str(target_path),
    ]
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and target_path.exists() and target_path.stat().st_size > 0


def storyboard_for_video(
    video: dict[str, Any],
    output_dir: Path,
    frames_per_video: int,
) -> dict[str, Any]:
    video_path = Path(video["abs_path"])
    meta = video["metadata"] if isinstance(video["metadata"], dict) else {}
    duration = meta.get("duration_sec")
    if not duration:
        return {"rel_path": video["rel_path"], "status": "skipped_no_duration"}

    slug = safe_slug(video["rel_path"].replace("/", "__"))
    frame_dir = output_dir / "video_storyboards" / "_frames" / slug
    sheet_path = output_dir / "video_storyboards" / f"{slug}.jpg"
    sample_count = max(1, frames_per_video)
    timestamps = [duration * (idx + 0.5) / sample_count for idx in range(sample_count)]
    frame_paths: list[Path] = []
    for idx, timestamp in enumerate(timestamps, start=1):
        target = frame_dir / f"frame_{idx:02d}.jpg"
        if extract_frame(video_path, timestamp, target):
            frame_paths.append(target)

    if not frame_paths:
        return {"rel_path": video["rel_path"], "status": "failed_no_frames"}

    images = [Image.open(path).convert("RGB") for path in frame_paths]
    cell_w = max(image.width for image in images)
    cell_h = max(image.height for image in images) + 36
    cols = min(4, len(images))
    rows = math.ceil(len(images) / cols)
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h + 48), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((8, 8), f"{video['rel_path']} | {fmt_duration(duration)}", fill=(0, 0, 0), font=font)

    for idx, image in enumerate(images):
        col = idx % cols
        row = idx // cols
        x = col * cell_w
        y = 48 + row * cell_h
        sheet.paste(image, (x, y + 20))
        draw.text((x + 6, y + 4), fmt_duration(timestamps[idx]), fill=(0, 0, 0), font=font)

    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(sheet_path, quality=88)
    for image in images:
        image.close()
    return {
        "rel_path": video["rel_path"],
        "status": "ok",
        "storyboard_path": str(sheet_path),
        "frame_count": len(frame_paths),
        "duration_sec": duration,
    }


def write_storyboards(
    output_dir: Path,
    file_inventory: list[dict[str, Any]],
    frames_per_video: int,
    max_videos: int,
) -> list[dict[str, Any]]:
    videos = [item for item in file_inventory if item["category"] == "video"]
    if max_videos > 0:
        videos = videos[:max_videos]

    results = [storyboard_for_video(video, output_dir, frames_per_video) for video in videos]
    json_dump(output_dir / "video_storyboards.json", results)

    lines = [
        "# Video Storyboards",
        "",
        "| rel_path | status | duration | frames | storyboard |",
        "|---|---|---:|---:|---|",
    ]
    for result in results:
        sheet = Path(result["storyboard_path"]) if result.get("storyboard_path") else None
        lines.append(
            "| "
            + " | ".join(
                md_escape(str(value))
                for value in [
                    result.get("rel_path", ""),
                    result.get("status", ""),
                    fmt_duration(result.get("duration_sec")),
                    result.get("frame_count", ""),
                    link_for(sheet, sheet.name) if sheet else "",
                ]
            )
            + " |"
        )
    (output_dir / "storyboard_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return results


def main() -> None:
    args = parse_args()
    export_dir = args.export_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser()
    if not output_dir.is_absolute():
        output_dir = (Path.cwd() / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    messages = parse_messages(export_dir)
    file_inventory_meta = build_file_inventory(export_dir, output_dir)
    file_inventory = [item.__dict__ for item in file_inventory_meta]
    file_by_rel = {item["rel_path"]: item for item in file_inventory}
    attachments = build_attachment_records(messages, file_by_rel)

    for message in messages:
        message["strategy_tags"] = tag_message(message["text"]) if message["kind"] == "message" else []

    json_dump(output_dir / "messages.json", messages)
    json_dump(output_dir / "corpus_inventory.json", file_inventory)
    json_dump(output_dir / "attachments.json", attachments)

    write_overview(output_dir, export_dir, messages, file_inventory, attachments)
    write_strategy_index(output_dir, messages)
    write_video_catalog(output_dir, attachments, file_inventory)
    write_pdf_catalog(output_dir, file_inventory, attachments)

    if args.storyboards:
        write_storyboards(output_dir, file_inventory, args.frames_per_video, args.max_videos)

    print(f"output_dir={output_dir}")
    print(f"messages={sum(1 for item in messages if item['kind'] == 'message')}")
    print(f"files={len(file_inventory)}")
    print(f"attachments={len(attachments)}")


if __name__ == "__main__":
    main()
