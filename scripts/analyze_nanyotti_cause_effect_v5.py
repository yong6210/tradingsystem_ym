#!/usr/bin/env python3
"""Extract cause/effect trading rules from the Nanyotti research corpus."""

from __future__ import annotations

import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path("/Users/yumin/Documents/trading")
CORPUS = ROOT / "reports/research/nanyotti_export"
DEEP = CORPUS / "deep_dive"
OUT_JSON = DEEP / "cause_effect_matrix_v5.json"
OUT_MD = DEEP / "cause_effect_matrix_v5_ko.md"
OUT_RULES = DEEP / "strategy_rules_v5_ko.md"
V4_BACKTEST = ROOT / "reports/validation/market_state_rotation_v4_backtest/market_state_rotation_v4_BTCUSDT_5m_365d_full_grid_latest.json"


TAG_PATTERNS: dict[str, list[str]] = {
    "trend_bias": [
        "추세",
        "상승 추세",
        "하락 추세",
        "롱 추세",
        "숏 추세",
        "우세",
        "상방",
        "하방",
        "방향성",
    ],
    "trend_follow": [
        "눌림",
        "눌림목",
        "추세 추종",
        "불타기",
        "돌파 후",
        "따라",
        "추격매수",
        "추격 매수",
        "추격",
    ],
    "countertrend": [
        "역추세",
        "반등 숏",
        "내릴 땐 롱",
        "오를 땐 숏",
        "저항에서 숏",
        "지지에서 롱",
        "짧게",
    ],
    "one_way": [
        "원웨이",
        "일방",
        "무저항",
        "강한 상승",
        "강한 하락",
        "빅롱",
        "빅숏",
        "급락",
        "급등",
    ],
    "bad_rr_watch": [
        "관망",
        "애매",
        "손익비",
        "중앙",
        "중간",
        "도박",
        "무리",
        "진입을 지양",
        "하지 않는",
        "쉬",
    ],
    "cloud": ["구름", "일목", "구름대", "이격", "안착", "이탈"],
    "supply_demand": ["매물대", "매물", "지지", "저항", "평단 집중", "저항선", "지지선"],
    "wick_tail": ["꼬리", "윗꼬리", "아래꼬리", "저깨롱", "고깨숏", "망치", "도지", "리테스트"],
    "round_level_2468": ["2,4,6,8", "2/4/6/8", "2468", "100K", "100k", "라운드", "마디가", "천불", "1K"],
    "scenario_zone": ["1차", "2차", "3차", "4구간", "6구간", "승부", "승부구간", "구간", "시나리오"],
    "probe_first": ["정찰", "소량", "분할", "1차 진입", "작게"],
    "second_add": ["2차", "추매", "추가 매수", "추가매수", "물타기"],
    "battle_zone": ["승부", "풀시드", "대량", "비중을 실", "물량을 확보", "크게"],
    "repair_avg": ["평단", "복구", "멘징", "수술", "탈출", "회복가", "본절"],
    "reduce_on_reaction": ["정리", "축소", "덜", "줄", "일부 익절", "일부 손절", "물량을 덜", "물량 정리"],
    "profit_trim": ["익절", "수익", "확정 이익", "전량 익절", "부분 익절"],
    "loss_rotation": ["손절 순환", "확정손실", "손절", "일부 손절", "손실 감수"],
    "switch": ["스위칭", "전환", "반대 포지션", "롱으로", "숏으로", "갈아", "바꾸"],
    "hedge": ["헷징", "양방", "양방향"],
    "chase": ["추격", "돌파매매", "돌파 매매", "뒤늦은", "따라붙"],
    "already_touched": ["이미", "이미 진행", "이미 나온", "기회를 놓", "놓침", "늦", "늦었"],
    "event_macro": ["트럼프", "마스크", "뉴스", "악재", "호재", "본장", "시간봉", "갱신"],
    "leverage_capacity": ["10배", "레버리지", "시드", "여력", "청산", "풀진입", "사용률", "용량"],
    "failure_case": ["실패", "판단 오류", "감점", "잘못", "위험", "손실", "대응 실패", "복구 심리"],
    "execution_error": ["오류", "렉", "거래소", "로딩", "체결", "정리 시도"],
}

DIRECTION_PATTERNS = {
    "long": ["롱", "Long", "long", "매수", "상방", "반등", "저깨롱"],
    "short": ["숏", "Short", "short", "매도", "하방", "반락", "고깨숏"],
}

ACTION_PATTERNS = {
    "enter": ["진입", "잡", "매수", "매도", "포지션"],
    "add": ["추매", "추가", "불타기", "물타기", "늘", "확보"],
    "reduce": ["정리", "축소", "덜", "줄", "익절", "손절", "감축"],
    "switch": ["스위칭", "전환", "바꾸", "반대 포지션", "양방", "헷징"],
    "hold": ["홀딩", "보유", "버티", "끌고"],
    "stop": ["손절", "이탈", "무효", "청산"],
    "no_trade": ["관망", "지양", "하지 않", "쉬", "도박"],
}

RESULT_PATTERNS = {
    "profit": ["익절", "수익", "이익", "양전", "복구", "멘징", "회복"],
    "loss": ["손실", "손절", "감점", "위험", "실패", "청산", "물림"],
    "missed": ["놓침", "기회", "늦", "대응 실패"],
    "neutral": ["관망", "마감", "종료", "본절"],
}

SOURCE_QUALITY_HINTS = {
    "messages.json": "A",
    "messages.md": "A",
    "pdf_text": "A",
    "video_transcripts_base": "A",
    "transcripts_all": "A",
    "photo_ocr": "B",
    "video_storyboard_ocr": "C",
}


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_type: str
    source_path: str
    source_ref: str
    quality: str
    date: str | None
    line_start: int
    line_end: int
    tags: list[str]
    directions: list[str]
    actions: list[str]
    results: list[str]
    snippet: str


@dataclass(frozen=True)
class Rule:
    rule_id: str
    title: str
    cause: str
    judgement: str
    action: str
    expected_result: str
    failure_mode: str
    system_rule: str
    required_tags: list[str]
    supporting_evidence_ids: list[str]
    support_count: int
    support_sources: list[str]
    priority: str


def clean(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = value.replace("\u200b", "")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def compact(value: str, limit: int = 420) -> str:
    value = clean(value).replace("\n", " / ")
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def fingerprint(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", clean(value)).lower()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"^[\-•*#>\d.)\s]+", "", normalized)
    return normalized[:800]


def md_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return clean(text).replace("|", "\\|").replace("\n", "<br>")


def quality_for(path: Path) -> str:
    text = path.as_posix()
    for marker, quality in SOURCE_QUALITY_HINTS.items():
        if marker in text:
            return quality
    return "B"


def source_type_for(path: Path) -> str:
    text = path.as_posix()
    if path.name in {"messages.json", "messages.md"}:
        return "message"
    if "pdf_text" in text:
        return "pdf"
    if "transcripts" in text:
        return "video_transcript"
    if "photo_ocr" in text:
        return "photo_ocr"
    if "storyboard" in text:
        return "video_ocr"
    return "text"


def match_keys(text: str, patterns: dict[str, list[str]]) -> list[str]:
    return [key for key, words in patterns.items() if any(word in text for word in words)]


def split_units(text: str) -> list[tuple[int, int, str]]:
    lines = text.splitlines()
    units: list[tuple[int, int, str]] = []
    buffer: list[str] = []
    start = 1

    def flush(end_line: int) -> None:
        nonlocal buffer, start
        value = clean("\n".join(buffer))
        if value:
            units.append((start, end_line, value))
        buffer = []

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            flush(idx - 1)
            start = idx + 1
            continue
        if not buffer:
            start = idx
        buffer.append(stripped)
        joined = clean(" ".join(buffer))
        if len(joined) >= 360 or re.search(r"(다\.|요\.|니다\.|됩니다\.|합니다\.|했습니다\.|[.!?])$", stripped):
            flush(idx)
            start = idx + 1
    flush(len(lines))
    return units


def iter_message_units(path: Path) -> list[tuple[str, str | None, int, int, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    units: list[tuple[str, str | None, int, int, str]] = []
    for row in payload:
        if row.get("kind") not in {None, "message"} and row.get("text") is None:
            continue
        text = clean(row.get("text") or "")
        if not text:
            continue
        source_ref = str(row.get("id") or row.get("date") or row.get("date_iso") or path.name)
        date = row.get("date_iso") or row.get("date")
        message_units = split_units(text)
        if not message_units:
            continue
        for start, end, unit in message_units:
            units.append((source_ref, date, start, end, unit))
    return units


def iter_text_units(path: Path) -> list[tuple[str, str | None, int, int, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [(path.name, None, start, end, unit) for start, end, unit in split_units(text)]


def corpus_paths() -> list[Path]:
    paths: list[Path] = []
    candidates = [
        CORPUS / "messages.json",
        CORPUS / "messages.md",
        DEEP / "messages.json",
        DEEP / "photo_ocr.txt",
        DEEP / "video_storyboard_ocr.txt",
    ]
    for path in candidates:
        if path.exists():
            paths.append(path)
    for directory in [
        CORPUS / "pdf_text",
        DEEP / "pdf_text",
        CORPUS / "transcripts_all",
        DEEP / "video_transcripts_base",
    ]:
        if directory.exists():
            paths.extend(sorted(directory.glob("*.txt")))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = path.resolve().as_posix()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def build_evidence() -> list[Evidence]:
    evidence: list[Evidence] = []
    seen_units: set[str] = set()
    eid = 1
    for path in corpus_paths():
        if path.suffix == ".json":
            raw_units = iter_message_units(path)
        else:
            raw_units = iter_text_units(path)
        for source_ref, date, line_start, line_end, unit in raw_units:
            unit_key = fingerprint(unit)
            if len(unit_key) < 12 or unit_key in seen_units:
                continue
            seen_units.add(unit_key)
            tags = match_keys(unit, TAG_PATTERNS)
            if not tags:
                continue
            # Keep only strategy-bearing units. This removes admin notices that
            # merely mention risk in legal disclaimers.
            if len(tags) == 1 and tags[0] in {"event_macro", "execution_error"}:
                continue
            if not any(
                tag in tags
                for tag in {
                    "trend_bias",
                    "trend_follow",
                    "countertrend",
                    "one_way",
                    "bad_rr_watch",
                    "cloud",
                    "supply_demand",
                    "wick_tail",
                    "scenario_zone",
                    "battle_zone",
                    "repair_avg",
                    "reduce_on_reaction",
                    "loss_rotation",
                    "switch",
                    "chase",
                    "leverage_capacity",
                    "failure_case",
                }
            ):
                continue
            directions = match_keys(unit, DIRECTION_PATTERNS)
            actions = match_keys(unit, ACTION_PATTERNS)
            results = match_keys(unit, RESULT_PATTERNS)
            evidence.append(
                Evidence(
                    evidence_id=f"E{eid:04d}",
                    source_type=source_type_for(path),
                    source_path=path.relative_to(ROOT).as_posix(),
                    source_ref=source_ref,
                    quality=quality_for(path),
                    date=str(date)[:10] if date else None,
                    line_start=line_start,
                    line_end=line_end,
                    tags=tags,
                    directions=directions,
                    actions=actions,
                    results=results,
                    snippet=compact(unit, 520),
                )
            )
            eid += 1
    return evidence


def supports(evidence: list[Evidence], required_tags: set[str], *, limit: int = 12) -> list[Evidence]:
    hits = [item for item in evidence if required_tags.issubset(set(item.tags))]
    hits.sort(
        key=lambda item: (
            {"A": 0, "B": 1, "C": 2}.get(item.quality, 9),
            0 if item.source_type in {"message", "video_transcript", "pdf"} else 1,
            item.source_path,
            item.line_start,
        )
    )
    return hits[:limit]


def build_rules(evidence: list[Evidence]) -> list[Rule]:
    specs = [
        {
            "rule_id": "R01",
            "title": "큰 방향과 단타 방향은 분리한다",
            "required_tags": ["trend_bias", "countertrend"],
            "cause": "상위 추세가 살아 있는데 단기 꼬리/저항/지지가 반대 방향 반응을 만든다.",
            "judgement": "반대 방향은 주력 포지션이 아니라 스캘프 또는 재고 조절용 포지션이다.",
            "action": "with-trend 쪽은 정상 물량, against-trend 쪽은 소량·짧은 목표·빠른 무효화를 적용한다.",
            "expected_result": "추세 방향에서 큰 손익을 열어두면서 반대 방향 단타로 수수료/손실을 줄인다.",
            "failure_mode": "반대 방향을 주력처럼 키우면 원웨이장에서 평단이 죽고 방어 감축이 반복된다.",
            "system_rule": "primary_bias와 scalp_side를 별도 상태로 두고, side_alignment별 size/hold/take_profit을 비대칭화한다.",
            "priority": "core",
        },
        {
            "rule_id": "R02",
            "title": "중앙값과 애매한 손익비는 거래하지 않는다",
            "required_tags": ["bad_rr_watch", "scenario_zone"],
            "cause": "현재가가 롱 지지와 숏 저항 사이 중앙이거나 주요 마디까지 거리가 멀다.",
            "judgement": "순환매는 항상 거래하는 방식이 아니라 반응 가능한 마디를 기다리는 방식이다.",
            "action": "no_trade, probe_only, battle_disabled 중 하나로 제한한다.",
            "expected_result": "probe 남발과 수수료 손실을 줄이고 승부 물량을 실제 마디까지 보존한다.",
            "failure_mode": "중앙에서 1차를 자주 넣으면 반응 전에 repair_stop이 먼저 발생한다.",
            "system_rule": "zone_distance_atr와 nearest_opposite_zone_distance를 계산해 bad_rr이면 신규 진입을 차단한다.",
            "priority": "core",
        },
        {
            "rule_id": "R03",
            "title": "승부구간은 마지막 물타기가 아니라 고품질 1차 이벤트다",
            "required_tags": ["battle_zone", "scenario_zone"],
            "cause": "주요 지지/저항, 꼬리, 구름대, 라운드 넘버가 겹치는 가격대가 미리 계획된다.",
            "judgement": "승부구간은 물린 뒤에만 쓰는 구조가 아니라 처음부터 가장 높은 품질의 반응 후보로 봐야 한다.",
            "action": "battle zone에 도달할 때까지 중앙 probe를 줄이고, 도달 시 reason_stack이 충분하면 base/battle을 허용한다.",
            "expected_result": "battle_add 비중이 정상화되고 불리한 probe 손실이 줄어든다.",
            "failure_mode": "battle을 adverse-after-entry로만 정의하면 실제 자료의 승부구간이 백테스트에서 거의 발생하지 않는다.",
            "system_rule": "plan.battle_zone을 primary trigger로 저장하고 touched/invalidated/retired 생명주기를 둔다.",
            "priority": "core",
        },
        {
            "rule_id": "R04",
            "title": "반응이 오면 추가 물량부터 먼저 줄인다",
            "required_tags": ["reduce_on_reaction", "repair_avg"],
            "cause": "큰 물량으로 평단을 당긴 뒤 차트가 평균가 또는 기대 반응을 잠깐 살려준다.",
            "judgement": "이 구간은 버티는 자리가 아니라 다음 순환 여력을 회복하는 자리다.",
            "action": "battle/chase/base 순서로 줄이고, 회복가 도달 전이라도 expected_reaction의 50~80%가 나오면 감축한다.",
            "expected_result": "잔여 물량의 청산 위험과 다음 원웨이 손실을 낮춘다.",
            "failure_mode": "평단 근처 반응에서 덜지 않으면 남은 물량으로 기존 손실을 살릴 수 없어 손실이 커진다.",
            "system_rule": "reduce_on_reaction을 profit_trim보다 우선하는 inventory action으로 둔다.",
            "priority": "core",
        },
        {
            "rule_id": "R05",
            "title": "좋은 평단은 기대 반응 안에서 살아나는 평단이다",
            "required_tags": ["repair_avg", "reduce_on_reaction"],
            "cause": "현재 평단 또는 확정손실 포함 회복가가 차트가 줄 만한 반등/반락 폭 안에 있다.",
            "judgement": "평단의 좋고 나쁨은 진입가 자체가 아니라 recovery_distance / expected_reaction으로 판단한다.",
            "action": "repair_efficiency가 낮으면 홀딩/감축, 높으면 손절 순환매·재진입 대기·스위칭을 선택한다.",
            "expected_result": "계속 물타는 전략이 아니라 계산된 평단 수술 전략이 된다.",
            "failure_mode": "기대 반응보다 회복가가 멀면 추가 진입이 수익 회복이 아니라 손실 확대가 된다.",
            "system_rule": "avg_price, recovery_price, expected_reaction_usd, repair_efficiency를 모든 포지션 루프에 기록한다.",
            "priority": "core",
        },
        {
            "rule_id": "R06",
            "title": "원웨이 반대 포지션은 빠르게 작게 인정한다",
            "required_tags": ["one_way", "reduce_on_reaction"],
            "cause": "강한 한 방향 흐름에서 역추세 포지션이 물리고 작은 반응만 나온다.",
            "judgement": "반대 포지션은 차트가 살려줄 수 있는 시간이 짧고, 반응 실패 뒤 손실이 비선형으로 커진다.",
            "action": "one_way_score가 높고 side_alignment가 against-trend이면 신규 add를 막고 강제 감축/무효화를 앞당긴다.",
            "expected_result": "청산은 피하면서도 repair_stop 반복 빈도를 낮춘다.",
            "failure_mode": "역추세 물량을 키우면 작은 반응에 욕심을 내다 손실 복구 심리가 커진다.",
            "system_rule": "one_way_against_forced_trim은 방어용으로 유지하되, 그 전에 entry gate에서 역추세 크기를 줄인다.",
            "priority": "core",
        },
        {
            "rule_id": "R07",
            "title": "이미 진행된 1차 구간은 재사용하지 않는다",
            "required_tags": ["already_touched", "scenario_zone"],
            "cause": "첫 반응 또는 탈출 기회가 이미 나왔고 같은 가격대의 기대값이 낮아졌다.",
            "judgement": "같은 마디라도 생명주기가 끝난 뒤에는 신규 1차가 아니라 retired zone이다.",
            "action": "zone touched 후 expected reaction이 소진되면 쿨다운을 걸고, 더 깊은 2차/승부 또는 반대 시나리오만 허용한다.",
            "expected_result": "이미 끝난 구간에서 반복 probe를 넣는 손실을 줄인다.",
            "failure_mode": "늦은 재진입은 좋은 자리 추매가 아니라 탈출 욕심/뒤늦은 추격으로 바뀐다.",
            "system_rule": "zone_state = pending/touched/reacted/invalidated/retired를 저장한다.",
            "priority": "core",
        },
        {
            "rule_id": "R08",
            "title": "추격은 독립 모듈이며 목표 폭이 작다",
            "required_tags": ["chase", "trend_follow"],
            "cause": "돌파·원웨이·강한 캔들 뒤에 추세 방향으로 짧은 후속 움직임을 노린다.",
            "judgement": "추격은 순환매 평균가 수술과 목적이 다르며, 늦으면 즉시 나쁜 손익비가 된다.",
            "action": "3회 이상 저항/지지 테스트, 몸통 안착, 눌림 확인 같은 확인 조건 없이는 chase를 금지한다.",
            "expected_result": "chase PnL은 남기되, chase 실패가 repair_stop으로 전염되는 일을 줄인다.",
            "failure_mode": "단순 추세 추격은 고점 롱/저점 숏이 되어 손절 순환매를 유발한다.",
            "system_rule": "chase_entry는 separate role로 두고 max_hold, stop, TP를 base/battle보다 짧게 둔다.",
            "priority": "high",
        },
        {
            "rule_id": "R09",
            "title": "스위칭은 익절 후 습관이 아니라 회복가 이전 기술이다",
            "required_tags": ["switch", "repair_avg"],
            "cause": "기존 방향의 회복가가 기대 반응 밖으로 밀렸고 반대 방향 마디가 더 명확하다.",
            "judgement": "바로 반대로 잡는 행동은 조건부로만 유효하며, 중앙값/풀시드/무효화 기준 부재에서는 금지다.",
            "action": "failed_rescue_count, repair_efficiency, opposite_zone_score, capacity를 모두 통과할 때만 switch를 허용한다.",
            "expected_result": "손실을 무작정 반대로 옮기지 않고 회복 가능성이 높은 방향으로 노출을 재배치한다.",
            "failure_mode": "롱 빼고 즉시 숏 같은 습관화된 왕복은 수수료와 양방 손절을 만든다.",
            "system_rule": "switch_permission = allowed/blocked/reduce_only로 명시하고 로그에 계산 근거를 남긴다.",
            "priority": "high",
        },
        {
            "rule_id": "R10",
            "title": "구름대와 매물대는 방향 예언이 아니라 반응 품질 점수다",
            "required_tags": ["cloud", "supply_demand"],
            "cause": "구름대·매물대·지지저항이 겹치는 곳에서 가격 반응과 이탈이 판단 기준이 된다.",
            "judgement": "지표가 있다고 바로 진입하는 것이 아니라, 지표가 zone_score와 invalidation 기준을 제공한다.",
            "action": "cloud support/resistance, cloud gap, supply concentration, reclaim/reject를 reason_stack에 누적한다.",
            "expected_result": "진입 품질이 높아지고 battle 후보가 더 적게, 더 정확히 발생한다.",
            "failure_mode": "구름/매물 단일 신호는 횡보와 휩쏘에서 probe 남발을 만든다.",
            "system_rule": "minimum_reason_stack을 도입해 단일 마디 진입을 제한한다.",
            "priority": "high",
        },
        {
            "rule_id": "R11",
            "title": "2/4/6/8과 큰 라운드 넘버는 단독 신호가 아니다",
            "required_tags": ["round_level_2468", "supply_demand"],
            "cause": "가격 숫자 마디가 심리적 반응을 만들지만 추세/구름/꼬리와 결합될 때 의미가 커진다.",
            "judgement": "숫자 마디는 zone_score 보조 가점이지 단독 진입 권한이 아니다.",
            "action": "round_level은 support/resistance/wick/cloud 중 하나 이상과 결합될 때만 entry reason으로 인정한다.",
            "expected_result": "모든 숫자 근처에서 주문이 들어가는 과거 v4식 노이즈를 줄인다.",
            "failure_mode": "숫자만 보고 잡으면 시장 전 구간에서 균등 손실이 난다.",
            "system_rule": "round_level_tag는 min_reason_stack을 만족시키는 보조 태그로만 처리한다.",
            "priority": "high",
        },
        {
            "rule_id": "R12",
            "title": "고레버리지는 순환매가 아니라 타점/손절 모드다",
            "required_tags": ["leverage_capacity", "loss_rotation"],
            "cause": "레버리지와 사용률이 높아지면 1차·2차·승부로 나눌 여력이 사라진다.",
            "judgement": "10배 자체보다 실제 계좌 사용률, 잔여 물량, 청산 버퍼가 핵심이다.",
            "action": "capacity가 낮으면 add를 금지하고 stop_only 또는 scalp_only로 전환한다.",
            "expected_result": "공격 모드에서도 순환매의 전제인 재진입 여력을 보존한다.",
            "failure_mode": "풀시드 상태에서 순환매를 한다고 착각하면 손절만 가능한 계좌가 된다.",
            "system_rule": "max_account_exposure, remaining_capacity_ratio, liquidation_buffer를 entry gate에 넣는다.",
            "priority": "core",
        },
    ]
    rules: list[Rule] = []
    for spec in specs:
        required = set(spec["required_tags"])
        hits = supports(evidence, required)
        support_sources = sorted({hit.source_path for hit in hits})
        rules.append(
            Rule(
                rule_id=spec["rule_id"],
                title=spec["title"],
                cause=spec["cause"],
                judgement=spec["judgement"],
                action=spec["action"],
                expected_result=spec["expected_result"],
                failure_mode=spec["failure_mode"],
                system_rule=spec["system_rule"],
                required_tags=spec["required_tags"],
                supporting_evidence_ids=[hit.evidence_id for hit in hits],
                support_count=len([item for item in evidence if required.issubset(set(item.tags))]),
                support_sources=support_sources[:10],
                priority=spec["priority"],
            )
        )
    return rules


def load_v4_summary() -> dict[str, Any]:
    if not V4_BACKTEST.exists():
        return {}
    raw = json.loads(V4_BACKTEST.read_text(encoding="utf-8"))
    top = raw.get("top_results", [{}])[0]
    pure_top = max(raw.get("all_results", []), key=lambda item: item.get("total_return_pct", -10**9), default={})
    diagnostics = top.get("event_diagnostics", {})
    return {
        "path": V4_BACKTEST.relative_to(ROOT).as_posix(),
        "tested_configs": raw.get("tested_configs"),
        "positive_result_count": raw.get("positive_result_count"),
        "monthly_double_candidate_count": raw.get("monthly_double_candidate_count"),
        "aggregate_stats": raw.get("aggregate_stats", {}),
        "distribution_flag_counts": raw.get("distribution_flag_counts", {}),
        "score_top": {
            "model_id": top.get("model_id"),
            "total_return_pct": top.get("total_return_pct"),
            "max_drawdown_pct": top.get("max_drawdown_pct"),
            "trade_like_events": top.get("trade_like_events"),
            "event_counts": top.get("event_counts", {}),
            "event_diagnostics": diagnostics,
        },
        "pure_return_top": {
            "model_id": pure_top.get("model_id"),
            "total_return_pct": pure_top.get("total_return_pct"),
            "max_drawdown_pct": pure_top.get("max_drawdown_pct"),
            "trade_like_events": pure_top.get("trade_like_events"),
            "event_diagnostics": pure_top.get("event_diagnostics", {}),
        },
    }


def summarize(evidence: list[Evidence]) -> dict[str, Any]:
    tag_counts = Counter(tag for item in evidence for tag in item.tags)
    source_type_counts = Counter(item.source_type for item in evidence)
    quality_counts = Counter(item.quality for item in evidence)
    tag_by_source = defaultdict(Counter)
    action_counts = Counter(action for item in evidence for action in item.actions)
    result_counts = Counter(result for item in evidence for result in item.results)
    direction_counts = Counter(direction for item in evidence for direction in item.directions)
    for item in evidence:
        for tag in item.tags:
            tag_by_source[item.source_type][tag] += 1
    snippets_len = [len(item.snippet) for item in evidence]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_files": len(corpus_paths()),
        "evidence_count": len(evidence),
        "tag_counts": dict(tag_counts.most_common()),
        "source_type_counts": dict(source_type_counts.most_common()),
        "quality_counts": dict(quality_counts.most_common()),
        "action_counts": dict(action_counts.most_common()),
        "result_counts": dict(result_counts.most_common()),
        "direction_counts": dict(direction_counts.most_common()),
        "tag_by_source_type": {key: dict(counter.most_common(12)) for key, counter in tag_by_source.items()},
        "snippet_length_median": statistics.median(snippets_len) if snippets_len else 0,
    }


def rule_evidence_table(rule: Rule, evidence_by_id: dict[str, Evidence], *, limit: int = 5) -> list[str]:
    rows = ["| evidence | source | tags | 핵심 문장 |", "|---|---|---|---|"]
    for eid in rule.supporting_evidence_ids[:limit]:
        item = evidence_by_id[eid]
        source = f"{item.source_path}:{item.line_start}"
        rows.append(
            "| "
            + " | ".join(
                [
                    md_cell(eid),
                    md_cell(source),
                    md_cell(", ".join(item.tags)),
                    md_cell(item.snippet),
                ]
            )
            + " |"
        )
    if len(rows) == 2:
        rows.append("| - | - | - | 직접 매칭된 근거가 부족해 다음 분석에서 수동 검토 필요 |")
    return rows


def write_matrix_md(summary: dict[str, Any], rules: list[Rule], evidence: list[Evidence], v4: dict[str, Any]) -> None:
    evidence_by_id = {item.evidence_id: item for item in evidence}
    lines: list[str] = [
        "# 나뇨띠/워뇨띠식 순환매 원인-결과 매트릭스 v5",
        "",
        "이 문서는 메시지, 영상 전사, PDF 텍스트, 사진/OCR 자료를 `상황 원인 -> 판단 -> 행동 -> 결과/실패조건` 형식으로 다시 색인한 결과다. 메시지 날짜를 매매 신호로 쓰지 않고, 시장 데이터에서 매일 재생성할 규칙으로만 사용한다.",
        "",
        "## 1. 분석 범위",
        "",
        f"- 분석 파일 수: `{summary['source_files']}`",
        f"- 전략 근거 단위: `{summary['evidence_count']}`",
        f"- 소스 유형: `{json.dumps(summary['source_type_counts'], ensure_ascii=False)}`",
        f"- 품질 등급: `{json.dumps(summary['quality_counts'], ensure_ascii=False)}`",
        "",
        "## 2. 가장 많이 반복된 판단 축",
        "",
        "| tag | count | 의미 |",
        "|---|---:|---|",
    ]
    tag_meaning = {
        "trend_bias": "큰 방향과 포지션 생존성",
        "supply_demand": "매물대/지지/저항",
        "scenario_zone": "1차/2차/승부/시나리오",
        "repair_avg": "평단/복구/회복가",
        "reduce_on_reaction": "반응 때 물량 감축",
        "one_way": "일방향 장세 위험",
        "bad_rr_watch": "관망/소량/손익비 불량",
        "cloud": "구름대 지지/저항/이탈",
        "wick_tail": "꼬리/저깨롱/고깨숏",
        "chase": "추격/돌파",
        "switch": "스위칭/반대 노출 이동",
        "leverage_capacity": "10배/시드/여력/청산",
    }
    for tag, count in list(summary["tag_counts"].items())[:22]:
        lines.append(f"| `{md_cell(tag)}` | {count} | {md_cell(tag_meaning.get(tag, '보조 판단 축'))} |")

    lines.extend(
        [
            "",
            "## 3. 핵심 원인-판단-행동-결과 규칙",
            "",
        ]
    )
    for rule in rules:
        lines.extend(
            [
                f"### {rule.rule_id}. {rule.title}",
                "",
                f"- 원인: {rule.cause}",
                f"- 판단: {rule.judgement}",
                f"- 행동: {rule.action}",
                f"- 기대 결과: {rule.expected_result}",
                f"- 실패 조건: {rule.failure_mode}",
                f"- 시스템 변수: `{rule.system_rule}`",
                f"- 근거 수: `{rule.support_count}` / 태그: `{', '.join(rule.required_tags)}`",
                "",
                *rule_evidence_table(rule, evidence_by_id),
                "",
            ]
        )

    if v4:
        top = v4.get("score_top", {})
        diag = top.get("event_diagnostics", {})
        pure = v4.get("pure_return_top", {})
        lines.extend(
            [
                "## 4. v4 백테스트 실패 원인과 자료 규칙의 연결",
                "",
                f"- 전체 설정 `{v4.get('tested_configs')}`개 중 플러스 설정 `{v4.get('positive_result_count')}`개, 월 2배 후보 `{v4.get('monthly_double_candidate_count')}`개였다.",
                f"- 점수 1위 수익률은 `{top.get('total_return_pct')}%`, MDD는 `{top.get('max_drawdown_pct')}%`, 주문 유사 이벤트는 `{top.get('trade_like_events')}`개였다.",
                f"- 순수 수익률 1위도 `{pure.get('total_return_pct')}%`에 그쳤다.",
                "",
                "| 진단 | v4 수치 | 자료상 원인 | v5 수정 |",
                "|---|---:|---|---|",
                f"| probe 과다 | `{diag.get('add_by_role', {}).get('probe')}` | 중앙값/이미 진행된 구간/단일 숫자 마디도 진입으로 인정 | bad_rr, already_touched, min_reason_stack으로 probe 차단 |",
                f"| battle 부족 | `{diag.get('add_by_role', {}).get('battle')}` | 승부구간을 물린 뒤 추가 진입으로만 처리 | battle_zone을 사전 계획된 primary event로 승격 |",
                f"| repair stop 과다 | `{diag.get('ratios', {}).get('repair_stop_per_add')}` | 좋은 평단이 아니라 반응 전 진입이 많음 | expected_reaction 대비 recovery_distance로 entry gate 강화 |",
                f"| profit trim 부족 | `{diag.get('ratios', {}).get('profit_trim_per_remove')}` | 평단 근처 반응에서 덜어내는 로직보다 손절 수술이 먼저 작동 | reduce_on_reaction을 우선순위 상향 |",
                f"| side 분포는 정상 | `{json.dumps(diag.get('add_side_share', {}), ensure_ascii=False)}` | 롱/숏 균형 문제가 아니라 진입 품질 문제 | 방향 분포가 아니라 역할/마디 품질을 개선 |",
                "",
            ]
        )

    lines.extend(
        [
            "## 5. 결론",
            "",
            "이번 자료 재분석에서 가장 중요한 결론은 순환매가 `자주 롱숏을 바꾸는 것`이 아니라는 점이다. 반복되는 핵심은 `큰 방향`, `마디 품질`, `평단이 살아날 수 있는 반응 폭`, `반응 때 물량 감축`, `원웨이 반대 포지션 축소`다. v4는 위험 방어는 했지만, 자료가 강조한 `기다림`, `승부구간 사전 계획`, `반응 감축`을 충분히 엔진화하지 못했다.",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def write_strategy_rules(summary: dict[str, Any], rules: list[Rule], v4: dict[str, Any]) -> None:
    top = v4.get("score_top", {}) if v4 else {}
    diag = top.get("event_diagnostics", {}) if top else {}
    lines = [
        "# 순환매 전략 v5 설계안",
        "",
        "목표는 자료의 문장을 그대로 매매 신호로 쓰는 것이 아니라, 같은 판단 구조를 시장 데이터에서 매일 생성하는 것이다. v5는 v4의 리스크 방어 위에 `진입 품질`, `승부구간 생명주기`, `반응 감축`을 추가해야 한다.",
        "",
        "## 1. 상태 변수",
        "",
        "| state | 내용 | 구현 포인트 |",
        "|---|---|---|",
        "| `MarketState` | 상위 추세, 원웨이, 지저분한 장, 구름대 상태 | 1H/4H bias, cloud gap, ATR impulse, failed rescue |",
        "| `ScenarioPlan` | 롱/숏 각각의 1차, 2차, 승부, 무효화, 관망 | side별 `pending/touched/reacted/invalidated/retired` |",
        "| `ZoneQuality` | 마디의 이유 스택 | cloud + supply + wick + round + HTF alignment count |",
        "| `Inventory` | 역할별 수량과 평단 | probe/base/battle/chase 분리 |",
        "| `RepairMath` | 기대 반응과 회복 거리 | `repair_efficiency = recovery_distance / expected_reaction` |",
        "| `ExecutionPolicy` | 현재 허용 행동 | no_trade, probe_only, base_allowed, battle_allowed, reduce_only, switch_allowed |",
        "",
        "## 2. 진입 게이트",
        "",
        "v5에서 신규 진입은 아래 조건을 모두 통과해야 한다.",
        "",
        "1. `min_reason_stack >= 2`: 숫자 마디 단독, 구름 단독, RSI 단독 진입 금지.",
        "2. `bad_rr == false`: 롱 지지와 숏 저항 중앙이면 관망 또는 probe_only.",
        "3. `zone_state != retired`: 이미 1차 반응이 나온 마디는 재사용하지 않음.",
        "4. `side_alignment` 적용: 추세 방향은 정상 물량, 역추세는 25~50% 물량과 짧은 보유.",
        "5. `remaining_capacity_ratio` 적용: 승부 전 여력 부족이면 add 금지.",
        "",
        "## 3. 승부구간 처리",
        "",
        "v4의 핵심 오류는 battle을 `물린 뒤 추가 매수`로 너무 좁게 처리한 것이다. 자료에서는 승부구간이 미리 계획된 강한 마디다.",
        "",
        "v5 규칙:",
        "",
        "- battle zone은 `primary trigger`다.",
        "- 현재가가 중앙이면 battle까지 기다린다.",
        "- battle 도달 전 probe를 남발하지 않는다.",
        "- battle 진입 후 expected_reaction이 나오면 battle 물량부터 줄인다.",
        "- battle 이탈 시 추가 물타기보다 무효화/감축을 먼저 수행한다.",
        "",
        "## 4. 반응 감축",
        "",
        "자료의 반복 패턴은 `좋은 평단을 만들고, 살려줄 때 줄이는 것`이다. v5에서는 익절/손절보다 먼저 재고 감축 판단을 한다.",
        "",
        "```text",
        "if role in {battle, chase, base}",
        "and reaction_from_local_extreme >= expected_reaction * 0.50",
        "and distance_to_avg <= expected_reaction * 0.80:",
        "    reduce role qty first",
        "```",
        "",
        "이 규칙이 없으면 v4처럼 `profit_trim_underuse`와 `repair_stop_overuse`가 동시에 나온다.",
        "",
        "## 5. 스위칭과 양방",
        "",
        "스위칭은 `롱 빼면 바로 숏`이 아니다. 허용 조건은 다음처럼 제한한다.",
        "",
        "- 기존 방향의 `repair_efficiency > 1.1`",
        "- 기존 방향 zone이 invalidated 또는 failed rescue 2회 이상",
        "- 반대 방향 zone score가 기존 방향보다 높음",
        "- 반대 진입 후 확정손실 회복가가 expected_reaction 안에 있음",
        "- 계좌 여력이 남아 있음",
        "",
        "양방/헷징은 기본 v5에는 넣되 `hedge_enabled=false`로 별도 검증한다. 자료상 고급 기술이고, 잘못 넣으면 손실을 양쪽으로 복제할 수 있다.",
        "",
        "## 6. v4 결과에서 바로 고쳐야 할 항목",
        "",
        f"- `probe_adds`: `{diag.get('add_by_role', {}).get('probe')}`. probe가 전략의 주력이 되면 안 된다.",
        f"- `battle_adds`: `{diag.get('add_by_role', {}).get('battle')}`. 승부구간이 거의 발현되지 않았다.",
        f"- `repair_stop_per_add`: `{diag.get('ratios', {}).get('repair_stop_per_add')}`. 진입 후 방어가 너무 자주 발생했다.",
        f"- `profit_trim_per_remove`: `{diag.get('ratios', {}).get('profit_trim_per_remove')}`. 반응 때 덜어내는 구조가 너무 약했다.",
        f"- `realized_pnl_by_role`: `{json.dumps(diag.get('realized_pnl_usd_units_by_role', {}), ensure_ascii=False)}`. probe가 손실의 중심이고 chase/base는 상대적으로 낫다.",
        "",
        "## 7. v5 백테스트 판정 기준",
        "",
        "수익률만 보지 말고 자료 구조가 제대로 재현되는지 먼저 본다.",
        "",
        "| metric | v5 목표 | 이유 |",
        "|---|---:|---|",
        "| `probe_add_share` | 35% 이하 | 정찰은 주력이 아님 |",
        "| `battle_add_share` | 8~20% | 승부구간이 사전 계획대로 작동해야 함 |",
        "| `repair_stop_per_add` | 0.25 이하 | 진입 품질 개선 여부 |",
        "| `profit_or_reaction_trim_per_remove` | 0.25 이상 | 반응 감축 재현 여부 |",
        "| `max_month_add_share` | 15% 이하 | 1년 전체 장에서 고르게 작동 |",
        "| `liquidation/account_ruin` | 0 | 10배라도 생존성 우선 |",
        "",
        "## 8. 구현 순서",
        "",
        "1. v4 `ZonePlan`에 `reason_stack`, `zone_state`, `battle_zone_primary` 추가.",
        "2. entry gate에 `min_reason_stack`, `bad_rr`, `already_touched` 적용.",
        "3. battle을 adverse add가 아니라 primary entry role로 허용.",
        "4. reduce_on_reaction을 손절 수술보다 먼저 실행.",
        "5. switch permission을 계산식으로 제한.",
        "6. 같은 365일 데이터로 v4/v5를 비교하고 주문 분포부터 확인.",
        "",
        "## 9. 규칙 근거 인덱스",
        "",
        "| rule | priority | support | system implication |",
        "|---|---|---:|---|",
    ]
    for rule in rules:
        lines.append(f"| `{rule.rule_id}` {md_cell(rule.title)} | {rule.priority} | {rule.support_count} | {md_cell(rule.system_rule)} |")
    lines.append("")
    lines.append(f"_분석 근거 단위: {summary['evidence_count']}개._")
    OUT_RULES.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    evidence = build_evidence()
    rules = build_rules(evidence)
    summary = summarize(evidence)
    v4 = load_v4_summary()
    payload = {
        "summary": summary,
        "rules": [asdict(rule) for rule in rules],
        "evidence": [asdict(item) for item in evidence],
        "v4_backtest": v4,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_matrix_md(summary, rules, evidence, v4)
    write_strategy_rules(summary, rules, v4)
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print(f"wrote {OUT_RULES}")


if __name__ == "__main__":
    main()
