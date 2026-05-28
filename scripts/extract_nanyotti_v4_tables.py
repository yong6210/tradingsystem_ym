#!/usr/bin/env python3
"""Generate structured v4 tables from the Nanyotti Telegram research corpus."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path("/Users/yumin/Documents/trading")
DEEP = ROOT / "reports/research/nanyotti_export/deep_dive"
MESSAGES_JSON = DEEP / "messages.json"
OUTPUT_DIR = DEEP


STRATEGY_WORDS = {
    "추세",
    "구름",
    "매물",
    "손절",
    "익절",
    "평단",
    "물량",
    "순환",
    "승부",
    "저깨롱",
    "고깨숏",
    "롱",
    "숏",
    "원웨이",
    "관망",
    "분할",
    "추격",
    "불타기",
    "헷징",
    "스위칭",
    "리스크",
    "시나리오",
    "지지",
    "저항",
    "이탈",
    "돌파",
    "꼬리",
    "산맥",
}


def clean(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def md_cell(value: object) -> str:
    text = "" if value is None else str(value)
    text = clean(text)
    return text.replace("|", "\\|")


def message_kind(message: dict) -> str:
    text = message.get("text") or ""
    attachment_paths = " ".join(item.get("rel_path", "") for item in message.get("attachments", []))
    if any(term in text for term in ("해킹", "클린 봇", "클린봇", "공지", "이벤트 채널", "불법광고", "비트겟 피드백")):
        return "admin/security"
    if "매매 시나리오" in text or "시나리오" in text or "관점 공유" in text:
        return "scenario"
    if "복기" in text or "하이라이트" in text or "손실" in text and "수익" in text:
        return "case_review"
    if attachment_paths.endswith(".pdf") or any(term in text for term in ("자료 공유", "캔들 자료", "차트 자료", "지표 활용법", "설명 영상")):
        return "education"
    if "스윙계좌" in text:
        return "swing_account"
    if "천불챌린지" in text:
        return "challenge"
    if any(term in text for term in STRATEGY_WORDS):
        return "strategy_note"
    return "other"


def extract_prices(text: str) -> list[str]:
    patterns = [
        r"\b\d{2,3}(?:\.\d+)?\s*[kK]\b",
        r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b",
        r"\b\d{2,3}\.\d\b",
    ]
    prices: list[str] = []
    for pattern in patterns:
        prices.extend(re.findall(pattern, text))
    seen: set[str] = set()
    result: list[str] = []
    for price in prices:
        normalized = price.replace(" ", "")
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def extract_segment(text: str, label_patterns: list[str], window: int = 220) -> str:
    hits: list[str] = []
    for pattern in label_patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            start = max(0, match.start() - 35)
            end = min(len(text), match.end() + window)
            hits.append(clean(text[start:end]))
    compact: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        if hit not in seen:
            seen.add(hit)
            compact.append(hit)
    return " / ".join(compact[:3])


def extract_direction_bias(text: str) -> str:
    flags: list[str] = []
    if any(term in text for term in ("롱이 우세", "롱 우세", "롱의 힘", "롱 힘", "상방", "눌림목 롱", "롱 위주")):
        flags.append("long_bias")
    if any(term in text for term in ("숏이 우세", "숏 우세", "하방", "숏 위주", "하락 추세", "하방 추세")):
        flags.append("short_bias")
    if any(term in text for term in ("관망", "손익비", "애매", "쉬", "매매를 쉬")):
        flags.append("bad_rr/watch")
    if "원웨이" in text:
        flags.append("one_way_risk")
    if "구름대" in text:
        flags.append("cloud")
    if "저깨롱" in text:
        flags.append("low_break_long")
    if "고깨숏" in text:
        flags.append("high_break_short")
    if "추격" in text:
        flags.append("chase")
    return ", ".join(flags)


def compact_strategy_summary(text: str) -> str:
    sentences = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s+|(?<=요\.)\s+", clean(text))
    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        score = sum(1 for word in STRATEGY_WORDS if word in sentence)
        if score:
            scored.append((score, sentence))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    chosen = [sentence for _, sentence in scored[:2]]
    if not chosen:
        chosen = [clean(text)[:220]]
    return " / ".join(chosen)[:520]


def write_timeline(messages: list[dict]) -> None:
    rows = [
        "# 메시지 타임라인 전략 분류 v4",
        "",
        "| date | id | type | attachments | prices | bias/tags | strategy summary |",
        "|---|---|---|---|---|---|---|",
    ]
    counts = Counter()
    for message in messages:
        if message.get("kind") != "message":
            continue
        kind = message_kind(message)
        counts[kind] += 1
        if kind in {"admin/security", "other"}:
            continue
        text = message.get("text") or ""
        attachments = "; ".join(item.get("rel_path", "") for item in message.get("attachments", []))
        prices = ", ".join(extract_prices(text)[:16])
        bias = extract_direction_bias(text)
        if message.get("strategy_tags"):
            bias = (bias + ", " if bias else "") + ",".join(message["strategy_tags"])
        rows.append(
            "| "
            + " | ".join(
                md_cell(value)
                for value in [
                    (message.get("date_iso") or "")[:10],
                    message.get("id"),
                    kind,
                    attachments,
                    prices,
                    bias,
                    compact_strategy_summary(text),
                ]
            )
            + " |"
        )

    rows.extend(["", "## Type Counts", "", "| type | count |", "|---|---:|"])
    for kind, count in counts.most_common():
        rows.append(f"| {md_cell(kind)} | {count} |")
    (OUTPUT_DIR / "message_timeline_strategy_map_v4_ko.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_scenarios(messages: list[dict]) -> None:
    rows = [
        "# 시나리오 가격대 추출 v4",
        "",
        "자동 추출 표라 일부 문장은 길게 남겼다. 목적은 1차/2차/승부구간/관망 조건이 어떤 식으로 반복되는지 확인하는 것이다.",
        "",
        "| date | id | price refs | directional hints | long segment | short segment | battle/risk segment |",
        "|---|---|---|---|---|---|---|",
    ]
    for message in messages:
        if message.get("kind") != "message":
            continue
        if message_kind(message) != "scenario":
            continue
        text = clean(message.get("text") or "")
        rows.append(
            "| "
            + " | ".join(
                md_cell(value)
                for value in [
                    (message.get("date_iso") or "")[:10],
                    message.get("id"),
                    ", ".join(extract_prices(text)[:24]),
                    extract_direction_bias(text),
                    extract_segment(text, [r"롱\(Long\)", r"Long", r"롱 포지션", r"롱\(.*?\)", r"롱은", r"롱 "]),
                    extract_segment(text, [r"숏\(Short\)", r"Short", r"숏 포지션", r"숏\(.*?\)", r"숏은", r"숏 "]),
                    extract_segment(text, [r"승부\s*구간", r"주의", r"원웨이", r"관망", r"손익비", r"이탈", r"손절"]),
                ]
            )
            + " |"
        )
    (OUTPUT_DIR / "scenario_zone_extraction_v4_ko.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_rule_keyword_matrix(messages: list[dict]) -> None:
    categories = {
        "trend": ["추세", "우세", "원웨이", "상방", "하방", "전환"],
        "cloud": ["구름대", "일목", "이격", "리딩"],
        "position": ["물량", "평단", "비중", "풀시드", "수량"],
        "risk": ["손절", "청산", "리스크", "위험", "관망", "손익비"],
        "repair": ["순환", "멘징", "복구", "손절 순환", "수술"],
        "flip": ["스위칭", "헷징", "양방", "롱", "숏"],
        "zones": ["매물대", "저항", "지지", "꼬리", "저깨롱", "고깨숏", "산맥", "2차", "1차", "승부"],
        "chase": ["추격", "돌파", "불타기", "눌림"],
    }
    evidence: dict[str, list[str]] = defaultdict(list)
    for message in messages:
        if message.get("kind") != "message":
            continue
        text = clean(message.get("text") or "")
        if not text:
            continue
        for category, words in categories.items():
            if any(word in text for word in words):
                evidence[category].append(f"{(message.get('date_iso') or '')[:10]} {message.get('id')}: {compact_strategy_summary(text)}")

    rows = ["# 규칙 후보 키워드 매트릭스 v4", ""]
    for category in categories:
        rows.extend([f"## {category}", "", "| evidence |", "|---|"])
        for item in evidence[category][:40]:
            rows.append(f"| {md_cell(item)} |")
        rows.append("")
    (OUTPUT_DIR / "rule_keyword_matrix_v4_ko.md").write_text("\n".join(rows), encoding="utf-8")


def main() -> None:
    messages = json.loads(MESSAGES_JSON.read_text(encoding="utf-8"))
    write_timeline(messages)
    write_scenarios(messages)
    write_rule_keyword_matrix(messages)
    print("wrote v4 tables")


if __name__ == "__main__":
    main()
