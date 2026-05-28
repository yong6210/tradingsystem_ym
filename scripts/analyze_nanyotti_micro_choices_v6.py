#!/usr/bin/env python3
"""Build a granular decision audit from the Nanyotti v5 evidence matrix."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any


ROOT = Path("/Users/yumin/Documents/trading")
DEEP = ROOT / "reports/research/nanyotti_export/deep_dive"
V5_JSON = DEEP / "cause_effect_matrix_v5.json"
OUT_JSON = DEEP / "micro_choice_decision_matrix_v6.json"
OUT_MD = DEEP / "micro_choice_decision_matrix_v6_ko.md"
OUT_CASE_MD = DEEP / "micro_choice_case_audit_v6_ko.md"
OUT_INDEX_CSV = DEEP / "micro_choice_evidence_index_v6.csv"


@dataclass(frozen=True)
class MicroChoice:
    choice_id: str
    layer: str
    title: str
    question: str
    choose: str
    reject: str
    trigger: str
    reason: str
    failure_if_wrong: str
    system_variable: str
    tags_any: tuple[str, ...] = ()
    tags_all: tuple[str, ...] = ()
    actions_any: tuple[str, ...] = ()
    results_any: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    min_score: int = 1


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    title: str
    keywords: tuple[str, ...]
    purpose: str
    expected_choices: tuple[str, ...]


def clean(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def md_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return clean(text).replace("|", "\\|").replace("\n", "<br>")


def compact(value: str, limit: int = 260) -> str:
    value = clean(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


CHOICES: tuple[MicroChoice, ...] = (
    MicroChoice(
        "MC01",
        "market",
        "먼저 장세를 정한다",
        "지금은 추세장, 박스, 전환, 원웨이, 지저분한 장 중 무엇인가?",
        "상위 추세와 하위 반응을 분리해 현재 장세 라벨을 먼저 붙인다.",
        "가격이 움직였다는 이유만으로 바로 롱/숏을 고르지 않는다.",
        "추세, 우세, 원웨이, 구름대 이탈/안착, 방향성 문맥",
        "자료는 진입보다 장세 분류를 먼저 요구한다. 같은 가격대도 장세가 다르면 물량과 목표가 달라진다.",
        "장세 라벨 없이 진입하면 중앙 probe와 역추세 물타기가 늘어난다.",
        "market_regime, primary_bias, one_way_score, messy_score",
        tags_any=("trend_bias", "one_way", "cloud"),
        keywords=("추세", "우세", "원웨이", "이탈", "안착"),
    ),
    MicroChoice(
        "MC02",
        "market",
        "큰 방향과 단타 방향을 분리한다",
        "주력 방향과 짧게 먹는 방향이 같은가 다른가?",
        "primary_bias와 scalp_side를 따로 둔다.",
        "롱/숏 중 하나만 정답이라고 고정하지 않는다.",
        "짧게는 숏 길게는 롱, 역추세, 오를 땐 숏/내릴 땐 롱",
        "자료는 단기 반응과 큰 추세가 서로 다를 수 있음을 반복한다.",
        "반대 방향 단타를 주력처럼 키우면 원웨이에서 평단이 죽는다.",
        "primary_bias, scalp_side, side_alignment",
        tags_any=("countertrend", "trend_bias"),
        tags_all=("trend_bias", "countertrend"),
    ),
    MicroChoice(
        "MC03",
        "market",
        "원웨이 위험이면 역추세를 줄인다",
        "한 방향으로 계속 밀리며 반응이 약한가?",
        "역추세 신규 진입을 줄이고 기존 물량도 반응 때 축소한다.",
        "원웨이 반대 포지션을 평소처럼 물타지 않는다.",
        "원웨이, 무저항, 강한 상승/하락, 승부구간 이탈",
        "원웨이에서는 차트가 반대 포지션을 살려주는 시간이 짧다.",
        "작은 반응을 기다리다 손실 복구 심리와 강제 손절이 커진다.",
        "one_way_score, one_way_against, forced_trim",
        tags_any=("one_way",),
        keywords=("원웨이", "무저항", "물량을 크게 줄", "능동적으로 물량을 축소"),
    ),
    MicroChoice(
        "MC04",
        "market",
        "매매하지 않는 선택을 인정한다",
        "지금 위치가 지지와 저항의 중앙인가, 손익비가 나쁜가?",
        "관망, 소량, probe_only 중 하나를 선택한다.",
        "항상 포지션을 열어두려고 하지 않는다.",
        "관망, 중앙, 애매, 손익비, 주요 지점까지 거리",
        "순환매는 반응 가능한 마디에서만 물량을 쓰는 운용법이다.",
        "중앙값에서 진입하면 마디 반응보다 repair_stop이 먼저 나온다.",
        "bad_rr, no_trade, probe_only, battle_disabled",
        tags_any=("bad_rr_watch",),
        actions_any=("no_trade",),
        keywords=("관망", "중앙", "손익비", "애매"),
    ),
    MicroChoice(
        "MC05",
        "zone",
        "롱/숏 시나리오를 동시에 세운다",
        "롱 지지와 숏 저항이 각각 어디인가?",
        "양쪽 plan을 만들고 먼저 닿는 마디만 실행한다.",
        "하나의 방향만 머릿속에 두고 반대 구간을 무시하지 않는다.",
        "롱 전략과 숏 전략이 같은 메시지 안에 함께 등장",
        "자료의 시나리오는 방향 예측보다 대응 구간표에 가깝다.",
        "반대 마디를 놓치면 스위칭/감축 기준이 사라진다.",
        "long_plan, short_plan, first_touch_side",
        tags_any=("scenario_zone",),
        keywords=("롱(Long)", "숏(Short)", "Long", "Short", "시나리오"),
    ),
    MicroChoice(
        "MC06",
        "zone",
        "1차/2차/승부를 역할로 분리한다",
        "이 가격은 정찰인가, 평단 조정인가, 승부인가?",
        "1차는 작게, 2차는 평단 보정, 승부는 강한 마디에서만 쓴다.",
        "모든 진입을 같은 크기와 같은 의미로 처리하지 않는다.",
        "1차, 2차, 3차, 승부구간, 구간별 물량",
        "자료는 가격대를 단계와 물량 역할로 함께 제시한다.",
        "역할 구분이 없으면 probe가 주력 손실원이 된다.",
        "entry_stage, role, stage_size_cap",
        tags_any=("probe_first", "second_add", "battle_zone"),
        keywords=("1차", "2차", "승부", "정찰병"),
    ),
    MicroChoice(
        "MC07",
        "zone",
        "승부구간은 사전 계획된 주 이벤트다",
        "여기가 단순 물타기 자리인가, 처음부터 기다린 강한 마디인가?",
        "battle zone을 primary trigger로 저장하고 대기한다.",
        "battle을 물린 뒤에만 발생하는 추가 진입으로 제한하지 않는다.",
        "승부 구간, 주요 지지/저항, 저깨롱/고깨숏, 구름대 중첩",
        "실제 자료에서 승부구간은 미리 정해 둔 가격대다.",
        "battle이 거의 발생하지 않고 probe만 누적된다.",
        "battle_zone_primary, battle_permission, reason_stack",
        tags_any=("battle_zone",),
        tags_all=("scenario_zone", "battle_zone"),
    ),
    MicroChoice(
        "MC08",
        "zone",
        "이미 진행된 구간은 제외한다",
        "이 1차 자리는 이미 반응했는가?",
        "touched/reacted 구간은 retired 처리하고 다음 단계만 본다.",
        "같은 가격대를 새 1차처럼 반복해서 쓰지 않는다.",
        "이미 진행, 이미 진입, 제외, 탈출 기회 놓침",
        "한 번 반응한 마디는 기대 반응이 소진될 수 있다.",
        "늦은 재진입이 탈출 욕심과 뒤늦은 추격으로 변한다.",
        "zone_state, touched_at, reacted_at, retired_until",
        tags_any=("already_touched",),
        keywords=("이미", "제외", "기회", "놓침"),
    ),
    MicroChoice(
        "MC09",
        "zone",
        "구름대는 단독 진입 신호가 아니다",
        "구름대가 지지/저항을 주는가, 아니면 이격/충돌만 있는가?",
        "구름대는 reason_stack과 무효화 기준으로 사용한다.",
        "구름대 하나만 보고 진입하지 않는다.",
        "구름대 지지, 구름대 저항, 이탈, 안착, 이격",
        "구름대는 방향 예언보다 반응 품질과 시나리오 무효화에 더 가깝다.",
        "단일 지표 진입은 횡보장 휩쏘에 약하다.",
        "cloud_state_1h, cloud_state_4h, cloud_gap_atr",
        tags_any=("cloud",),
        keywords=("구름", "일목", "이격", "안착", "이탈"),
    ),
    MicroChoice(
        "MC10",
        "zone",
        "매물대는 평균가 밀집으로 해석한다",
        "이 매물대는 신규 진입 자리인가, 물량을 덜 자리인가?",
        "매물대 반응은 진입과 감축 둘 다의 근거로 본다.",
        "매물대가 보인다는 이유만으로 무조건 새 포지션을 열지 않는다.",
        "매물대, 지지, 저항, 평단 집중",
        "자료는 매물대를 시장 참여자 평균가가 몰린 구간으로 설명한다.",
        "매물대에서 물량 감축을 놓치면 다시 물린다.",
        "supply_zone_score, demand_zone_score, trim_zone",
        tags_any=("supply_demand",),
        keywords=("매물", "지지", "저항", "평단 집중"),
    ),
    MicroChoice(
        "MC11",
        "zone",
        "꼬리와 저깨롱/고깨숏은 확인이 필요하다",
        "꼬리를 깼다가 회복했는가, 아니면 그대로 이탈했는가?",
        "꼬리 재방문, 이탈 후 회복, 종가 위치를 함께 본다.",
        "도지/망치/꼬리를 단독 반전 신호로 쓰지 않는다.",
        "꼬리, 저깨롱, 고깨숏, 도지, 망치, 리테스트",
        "자료는 꼬리를 타점 후보로 보지만 시장 강도와 함께 보라고 한다.",
        "단독 꼬리 진입은 추세장에 계속 밀릴 수 있다.",
        "wick_reclaim, tail_fill_state, close_position",
        tags_any=("wick_tail",),
        keywords=("꼬리", "저깨롱", "고깨숏", "망치", "도지"),
    ),
    MicroChoice(
        "MC12",
        "zone",
        "2/4/6/8과 라운드는 보조 가점이다",
        "숫자 마디가 다른 이유와 겹치는가?",
        "라운드 레벨은 구름/매물/꼬리/추세와 결합될 때만 인정한다.",
        "숫자만 보고 진입하지 않는다.",
        "2/4/6/8, 2468, 100K, 1K, 마디가",
        "숫자 마디는 심리적 반응을 만들지만 단독 기대값은 낮다.",
        "숫자마다 주문하면 1년 전체에서 균등하게 수수료 손실이 난다.",
        "round_level_tag, confluence_count",
        tags_any=("round_level_2468",),
        keywords=("2468", "2,4,6,8", "100K", "마디가", "1K"),
    ),
    MicroChoice(
        "MC13",
        "entry",
        "처음부터 크게 들어가지 않는다",
        "첫 진입인가, 검증된 반응 이후인가?",
        "처음은 정찰/소량으로 시작하고 승부 전 여력을 남긴다.",
        "첫 자리에서 풀시드 또는 큰 비중을 쓰지 않는다.",
        "정찰병, 소량, 분할, 1차 진입",
        "순환매는 다음 단계에서 평단을 고칠 여력이 있어야 한다.",
        "첫 진입이 크면 2차/승부가 아니라 손절만 남는다.",
        "probe_units, base_units, remaining_capacity_ratio",
        tags_any=("probe_first",),
        keywords=("정찰", "소량", "분할", "1차 진입"),
    ),
    MicroChoice(
        "MC14",
        "entry",
        "추매 이유를 구분한다",
        "추매가 좋은 자리인가, 빠른 탈출 욕심인가?",
        "추매는 더 좋은 마디와 회복 계산이 있을 때만 한다.",
        "탈출 욕심, 뇌동, 불리한 위치에서의 추매를 하지 않는다.",
        "추매 이유, 빠른 탈출 욕심, 좋은 자리가 아님, 추가 매수",
        "자료는 2025-06-12 사례에서 나쁜 추매를 명확히 감점한다.",
        "나쁜 추매는 평단 수술이 아니라 리스크 증가가 된다.",
        "add_reason, add_quality, chase_to_escape_flag",
        tags_any=("second_add", "failure_case"),
        keywords=("추매 이유", "빠른 탈출", "좋은 자리가 아님", "뇌동"),
    ),
    MicroChoice(
        "MC15",
        "entry",
        "추격은 별도 모듈로 짧게 처리한다",
        "추격인가, 눌림 진입인가, 복구 진입인가?",
        "추격은 확인 조건과 짧은 목표/손절을 별도로 둔다.",
        "추격 포지션을 평단 수술용 재고와 섞지 않는다.",
        "추격, 돌파매매, 뒤늦은 추격, 눌림 후 추격",
        "추격은 수익 확장 모듈이지 평균가 복구 모듈이 아니다.",
        "늦은 추격이 손실 포지션으로 바뀌어 repair_stop을 유발한다.",
        "chase_role, chase_confirmation, chase_max_hold",
        tags_any=("chase",),
        keywords=("추격", "돌파매매", "뒤늦은"),
    ),
    MicroChoice(
        "MC16",
        "entry",
        "추세 방향과 역추세 물량을 비대칭으로 둔다",
        "이 진입은 추세가 살려주는 방향인가?",
        "추세 방향은 정상 물량, 역추세는 소량/짧은 목표로 제한한다.",
        "역추세를 추세 방향과 같은 크기로 운용하지 않는다.",
        "상승 탄력 강함, 숏 보수적, 롱 우선, 역추세",
        "자료는 같은 날에도 롱/숏 물량 성격이 다르다고 말한다.",
        "역추세 크기가 같으면 작은 반응 실패에 계좌가 흔들린다.",
        "side_alignment_size_multiplier",
        tags_any=("countertrend", "trend_bias"),
        keywords=("보수적", "짧게", "역추세", "상승 탄력"),
    ),
    MicroChoice(
        "MC17",
        "inventory",
        "좋은 평단을 계산으로 판정한다",
        "내 평단/회복가가 기대 반응 안에 있는가?",
        "recovery_distance와 expected_reaction을 비교한다.",
        "평단이 낮아졌다는 느낌만으로 홀딩하지 않는다.",
        "평단, 회복선, 멘징, 200~300불, 1K 반등",
        "자료의 좋은 평단은 차트가 살려줄 수 있는 평단이다.",
        "회복 거리가 반응 폭보다 멀면 추가 진입은 손실 확대다.",
        "recovery_price, expected_reaction, repair_efficiency",
        tags_any=("repair_avg",),
        keywords=("평단", "멘징", "회복", "200~300", "1K"),
    ),
    MicroChoice(
        "MC18",
        "inventory",
        "반응이 오면 먼저 덜어낸다",
        "평단 근처 또는 기대 반응이 왔는가?",
        "battle/chase/base 순서로 물량을 줄여 여력을 회복한다.",
        "평단을 찍었는데도 더 큰 수익만 기대하며 버티지 않는다.",
        "정리, 축소, 덜어, 일부 익절, 물량 정리",
        "자료는 반응 감축 실패를 큰 실수로 평가한다.",
        "반응 때 못 줄이면 다음 하락/상승에서 수습 불가 상태가 된다.",
        "reduce_on_reaction, role_priority_trim",
        tags_any=("reduce_on_reaction",),
        actions_any=("reduce",),
        keywords=("정리", "축소", "덜", "줄", "일부"),
    ),
    MicroChoice(
        "MC19",
        "inventory",
        "일부 손절은 순환매의 일부다",
        "확정손실을 내면 더 좋은 재진입과 청산가 조정이 가능한가?",
        "일부 손절로 위험 수량을 줄이고 재진입 여력을 만든다.",
        "손실 확정을 무조건 실패로 보고 버티지 않는다.",
        "일부 손절, 확정손실, 손절 순환, 청산가 조정",
        "자료는 손절 순환매를 물량 수술의 한 방식으로 설명한다.",
        "손절을 못 하면 더 큰 청산/풀시드 위험으로 이동한다.",
        "loss_rotation_trim, liquidation_buffer_repair",
        tags_any=("loss_rotation",),
        actions_any=("stop", "reduce"),
        keywords=("확정손실", "손절", "청산가"),
    ),
    MicroChoice(
        "MC20",
        "inventory",
        "풀시드 근접이면 add 금지다",
        "추가 진입 여력과 청산 버퍼가 충분한가?",
        "capacity가 낮으면 reduce_only 또는 stop_only로 바꾼다.",
        "풀시드 상태에서 순환매라고 부르며 더하지 않는다.",
        "풀시드, 시드 60%, 여력, 청산, 레버리지",
        "순환매는 남은 수량으로 다음 선택을 할 수 있어야 한다.",
        "여력 없는 계좌는 순환매가 아니라 손절 대기 상태가 된다.",
        "remaining_capacity_ratio, liquidation_buffer_pct",
        tags_any=("leverage_capacity",),
        keywords=("풀시드", "시드", "여력", "청산", "레버리지"),
    ),
    MicroChoice(
        "MC21",
        "inventory",
        "좋은 평단이면 전부 덜 필요는 없다",
        "평단이 좋고 박스권/추세가 버텨주는가?",
        "코어 물량은 남기고 추가 물량만 회전시킨다.",
        "모든 수익 포지션을 기계적으로 다 줄이지 않는다.",
        "좋은 평단, 홀딩, 박스권, 일부 물량은 계속 보유",
        "자료에는 순환매를 돌리지 않고 홀딩하는 예외도 있다.",
        "좋은 코어까지 다 팔면 큰 추세 수익을 놓친다.",
        "core_position_units, hold_permission",
        tags_any=("repair_avg", "profit_trim"),
        actions_any=("hold",),
        keywords=("홀딩", "계속 보유", "좋은 평단", "박스권"),
    ),
    MicroChoice(
        "MC22",
        "exit",
        "익절은 목표가 아니라 재고관리다",
        "지금 익절은 수익 확정인가, 위험 물량 제거인가?",
        "역할별로 추가 물량부터 익절하고 코어는 별도 판단한다.",
        "익절을 단순 TP 한 줄로 처리하지 않는다.",
        "익절, 일부 익절, 전량 익절, 수익 전환",
        "자료의 익절은 다음 순환 여력을 만드는 행위다.",
        "익절이 늦으면 수익 포지션이 다시 손실 재고가 된다.",
        "profit_trim_role_order, reaction_take_profit",
        tags_any=("profit_trim",),
        results_any=("profit",),
        keywords=("익절", "수익", "이익"),
    ),
    MicroChoice(
        "MC23",
        "exit",
        "승부구간 이탈은 무효화다",
        "승부구간이 깨졌는가?",
        "추가 물타기보다 축소/손절/시나리오 무효화를 먼저 한다.",
        "승부구간을 지나도 계속 같은 시나리오로 버티지 않는다.",
        "승부 구간 이탈, 손절 원칙, 무효화",
        "승부는 큰 물량을 쓰는 자리인 동시에 틀리면 빨리 인정하는 자리다.",
        "승부구간 이탈 뒤 물타기는 손실 비선형 확대를 만든다.",
        "battle_invalidation, scenario_invalidated",
        tags_any=("battle_zone", "loss_rotation"),
        keywords=("승부 구간 이탈", "벗어나는", "즉각 손절", "무효"),
    ),
    MicroChoice(
        "MC24",
        "exit",
        "스위칭은 조건부 회복 기술이다",
        "기존 방향이 죽고 반대 방향 회복 기대값이 더 좋은가?",
        "repair_efficiency, failed_rescue, opposite_score, capacity를 확인한 뒤 스위칭한다.",
        "익절했거나 뺐다는 이유만으로 바로 반대로 잡지 않는다.",
        "스위칭, 전환, 반대 포지션, 멘징",
        "자료의 스위칭은 손실 이전과 회복 계산이 붙은 고난도 선택이다.",
        "습관적 왕복은 수수료와 양쪽 손절을 만든다.",
        "switch_permission, opposite_zone_score",
        tags_any=("switch",),
        actions_any=("switch",),
        keywords=("스위칭", "전환", "반대 포지션"),
    ),
    MicroChoice(
        "MC25",
        "exit",
        "양방/헷징은 기본 모드가 아니다",
        "양방을 열면 기존 손실을 실제로 이전할 수 있는가?",
        "헷징은 별도 스위치와 엄격한 조건에서만 허용한다.",
        "불리하다고 즉흥적으로 양방을 열지 않는다.",
        "헷징, 양방, 반대 포지션 수익",
        "자료상 양방은 고급 복구 기술이며 원웨이에서는 적용 위험이 크다.",
        "양방을 잘못 열면 손실을 양쪽으로 복제한다.",
        "hedge_enabled, hedge_transfer_plan",
        tags_any=("hedge",),
        keywords=("헷징", "양방"),
    ),
    MicroChoice(
        "MC26",
        "exit",
        "거래 종료도 전략이다",
        "차트 구조가 끝났거나 변동성이 줄어 양쪽이 열렸는가?",
        "무포 또는 종료를 선택하고 다음 구조를 기다린다.",
        "복구하고 싶어서 계속 재진입하지 않는다.",
        "매매 종료, 차트의 끝, 변동성 축소, 도박성",
        "자료는 횡보가 길어지고 방향이 양쪽으로 열리면 멈춘다.",
        "끝난 구조에서 계속 거래하면 수수료와 휩쏘 손실이 누적된다.",
        "session_end_state, cooldown_until",
        tags_any=("bad_rr_watch", "failure_case"),
        keywords=("매매 종료", "차트의 끝", "변동성 축소", "도박"),
    ),
    MicroChoice(
        "MC27",
        "execution",
        "시간봉 갱신과 본장 변동을 구분한다",
        "지금 움직임이 시간봉/본장 이벤트 직전인가 직후인가?",
        "갱신 전후 기대 반응과 실패 기준을 다르게 둔다.",
        "시간 이벤트를 무시하고 같은 진입 규칙을 적용하지 않는다.",
        "시간봉 갱신, 본장, 오전장, 새벽, 뉴스",
        "자료에는 시간봉 갱신 전 윗꼬리 기대 같은 실행 맥락이 나온다.",
        "이벤트 직전 추매는 기대 반응이 틀리면 바로 나쁜 자리가 된다.",
        "time_event_risk, session_context",
        tags_any=("event_macro",),
        keywords=("시간봉", "본장", "오전장", "새벽", "뉴스"),
    ),
    MicroChoice(
        "MC28",
        "execution",
        "체결/거래소 오류를 리스크로 둔다",
        "대량 감축이 필요한 순간 체결 실패 가능성이 있는가?",
        "대량 포지션은 감축 주문 실패를 별도 리스크로 계산한다.",
        "정리 시도 실패를 전략 밖 우연으로만 처리하지 않는다.",
        "거래소 오류, 체결 안 됨, 로딩, 렉",
        "자료에는 물량 정리 실패가 손실 확대의 직접 원인으로 나온다.",
        "체결 실패를 고려하지 않으면 백테스트가 실제 위험을 과소평가한다.",
        "execution_failure_risk, reduce_order_slicing",
        tags_any=("execution_error",),
        keywords=("오류", "체결", "렉", "로딩"),
    ),
    MicroChoice(
        "MC29",
        "risk",
        "고레버리지는 별도 타점 모드다",
        "이 레버리지에서 순환매 여력이 있는가?",
        "고레버리지는 타점/빠른 손절 모드로 분리한다.",
        "10배라는 숫자만 보고 순환매 가능하다고 보지 않는다.",
        "10배, 고레버리지, 천불챌린지, 타점, 빠른 손절",
        "자료는 고레버리지에서 순환매가 어렵다고 명시한다.",
        "레버리지와 사용률을 혼동하면 작은 변동에도 강제 손절된다.",
        "mode=scalp_precision, leverage_capacity_gate",
        tags_any=("leverage_capacity", "loss_rotation"),
        keywords=("10배", "고레버리지", "천불챌린지", "타점"),
    ),
    MicroChoice(
        "MC30",
        "risk",
        "심리적 복구 욕심을 플래그로 둔다",
        "지금 진입 이유가 복구 욕심인가, 구조적 이유인가?",
        "복구 욕심이 감지되면 size를 줄이고 재진입 쿨다운을 둔다.",
        "손실을 빨리 메우려고 좋은 자리 아닌 곳에서 추가하지 않는다.",
        "빠른 탈출 욕심, 복구 심리, 무리, 뇌동, 판단 오류",
        "자료의 실패 사례는 심리적 이유가 기술적 이유를 덮는 순간 발생한다.",
        "복구 욕심은 나쁜 추매와 정리 실패를 연쇄로 만든다.",
        "revenge_trade_flag, cooldown_after_loss",
        tags_any=("failure_case",),
        keywords=("욕심", "복구 심리", "무리", "뇌동", "판단 오류"),
    ),
)


CASES: tuple[CaseSpec, ...] = (
    CaseSpec(
        "C01",
        "2025-06-06 100K 급락 후 반등 복구",
        ("100K", "100k", "101.4K", "70BTC", "30BTC", "시드 60%"),
        "라운드 넘버, 대량 진입, 평단 수술, 반응 감축을 동시에 검증하는 핵심 사례",
        ("MC07", "MC17", "MC18", "MC20", "MC22"),
    ),
    CaseSpec(
        "C02",
        "2025-06-12 나쁜 추매와 정리 실패",
        ("2025.06.12", "109.7K", "108.6K", "빠른 탈출 욕심", "70개 중 20개", "거래소창 오류"),
        "좋은 자리 아닌 추매, 체결 실패, 풀시드 위험이 어떻게 손실로 이어지는지 보는 실패 사례",
        ("MC14", "MC18", "MC20", "MC28", "MC30"),
    ),
    CaseSpec(
        "C03",
        "2025-06-22 손절 순환매와 거래 종료",
        ("2025-06-22", "손절 순환매", "차트의 끝", "변동성 축소", "도박성", "매매 종료"),
        "일부 손절, 스위칭, 구조 종료 판단을 분해하는 사례",
        ("MC19", "MC24", "MC26", "MC30"),
    ),
    CaseSpec(
        "C04",
        "2025-08-12 원웨이 손실과 스위칭 복구",
        ("120.6K", "121K", "1K 하락", "구름대 저항", "원웨이", "물량을 크게 줄"),
        "원웨이 반대 포지션 감축 실패와 이후 스위칭 회복 조건을 보는 사례",
        ("MC03", "MC18", "MC24", "MC09"),
    ),
    CaseSpec(
        "C05",
        "2025-05-09 숏 물림 후 롱 헷징/스위칭",
        ("숏으로 물려", "롱 헷징", "롱 포지션 스위칭", "110BTC", "멘징"),
        "스위칭/헷징이 언제 복구 기술이 되는지 보는 사례",
        ("MC24", "MC25", "MC17", "MC20"),
    ),
    CaseSpec(
        "C06",
        "2026-04~05 시나리오 메시지",
        ("2026.04", "2026.05", "1차 진입", "2차 진입", "승부 구간", "관점"),
        "롱/숏 동시 플랜, 1차/2차/승부, 이미 진행된 구간 제외를 검증하는 실시간 시나리오 샘플",
        ("MC05", "MC06", "MC07", "MC08", "MC16"),
    ),
    CaseSpec(
        "C07",
        "구름대/매물대/PDF 교육 자료",
        ("구름대", "매물대", "일목", "평단 집중", "지지", "저항"),
        "지표를 단독 신호가 아니라 반응 품질 점수로 바꿔야 하는 근거",
        ("MC09", "MC10", "MC11", "MC12"),
    ),
    CaseSpec(
        "C08",
        "천불챌린지와 고레버리지",
        ("천불챌린지", "고레버리지", "10배", "타점", "손절"),
        "고레버리지를 순환매 모드와 분리해야 하는 근거",
        ("MC20", "MC29", "MC19"),
    ),
)


def score_choice(evidence: dict[str, Any], choice: MicroChoice) -> int:
    tags = set(evidence.get("tags") or [])
    actions = set(evidence.get("actions") or [])
    results = set(evidence.get("results") or [])
    snippet = str(evidence.get("snippet") or "")
    score = 0
    if choice.tags_all and all(tag in tags for tag in choice.tags_all):
        score += len(choice.tags_all) + 1
    elif choice.tags_all:
        return 0
    score += sum(1 for tag in choice.tags_any if tag in tags)
    score += sum(1 for action in choice.actions_any if action in actions)
    score += sum(1 for result in choice.results_any if result in results)
    score += sum(1 for keyword in choice.keywords if keyword and keyword in snippet)
    return score


def assign_choices(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for choice in CHOICES:
        score = score_choice(evidence, choice)
        if score >= choice.min_score:
            matches.append({"choice_id": choice.choice_id, "score": score})
    matches.sort(key=lambda item: (-item["score"], item["choice_id"]))
    return matches


def load_v5() -> dict[str, Any]:
    return json.loads(V5_JSON.read_text(encoding="utf-8"))


def is_noise_evidence(item: dict[str, Any]) -> bool:
    snippet = str(item.get("snippet") or "")
    source_ref = str(item.get("source_ref") or "")
    source_path = str(item.get("source_path") or "")
    admin_markers = (
        "절대 수익을 보장",
        "투자를 추천",
        "따라 하시는 것을",
        "미성년자",
        "운영진",
        "개인정보",
        "가상자산 투자 주의사항",
        "법률을 준수",
        "원금 손실 가능성",
        "자기 책임 원칙",
        "UID 인증",
        "추방 처리",
        "불법광고",
        "클린 봇",
    )
    if any(marker in snippet for marker in admin_markers):
        return True
    if source_ref == "message3" and "messages.json" in source_path:
        return True
    return False


def strategy_evidence(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in raw["evidence"] if not is_noise_evidence(item)]


def build_case_hits(evidence: list[dict[str, Any]], evidence_choices: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    case_hits: dict[str, list[dict[str, Any]]] = {}
    for case in CASES:
        hits: list[dict[str, Any]] = []
        for item in evidence:
            haystack = " ".join(
                [
                    str(item.get("snippet") or ""),
                    str(item.get("source_path") or ""),
                    str(item.get("date") or ""),
                ]
            )
            if any(keyword in haystack for keyword in case.keywords):
                choices = [match["choice_id"] for match in evidence_choices.get(item["evidence_id"], [])]
                hits.append({**item, "choice_ids": choices})
        hits.sort(key=lambda row: (row.get("date") or "", row.get("source_path") or "", row.get("line_start") or 0))
        case_hits[case.case_id] = hits
    return case_hits


def build_summary(evidence: list[dict[str, Any]], original_evidence_count: int) -> dict[str, Any]:
    evidence_choices = {item["evidence_id"]: assign_choices(item) for item in evidence}
    choice_counts = Counter()
    layer_counts = Counter()
    source_counts = Counter()
    choice_by_source_type: dict[str, Counter[str]] = defaultdict(Counter)
    co_occurrence = Counter()
    uncovered = []

    choice_by_id = {choice.choice_id: choice for choice in CHOICES}
    for item in evidence:
        matches = evidence_choices[item["evidence_id"]]
        if not matches:
            uncovered.append(item["evidence_id"])
        ids = [match["choice_id"] for match in matches]
        for choice_id in ids:
            choice_counts[choice_id] += 1
            layer_counts[choice_by_id[choice_id].layer] += 1
            choice_by_source_type[str(item.get("source_type") or "")][choice_id] += 1
        source_counts[str(item.get("source_path") or "")] += 1
        for left, right in combinations(sorted(set(ids)), 2):
            co_occurrence[f"{left}+{right}"] += 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "original_evidence_count": original_evidence_count,
        "excluded_noise_count": original_evidence_count - len(evidence),
        "evidence_count": len(evidence),
        "choice_count": len(CHOICES),
        "assigned_evidence_count": len(evidence) - len(uncovered),
        "uncovered_evidence_count": len(uncovered),
        "choice_counts": dict(choice_counts.most_common()),
        "layer_counts": dict(layer_counts.most_common()),
        "source_counts": dict(source_counts.most_common()),
        "choice_by_source_type": {key: dict(value.most_common()) for key, value in choice_by_source_type.items()},
        "co_occurrence": dict(co_occurrence.most_common(40)),
        "uncovered_evidence_ids": uncovered[:200],
    }


def top_evidence_for_choice(evidence: list[dict[str, Any]], evidence_choices: dict[str, list[dict[str, Any]]], choice_id: str, limit: int = 5) -> list[dict[str, Any]]:
    rows = []
    for item in evidence:
        score = 0
        for match in evidence_choices.get(item["evidence_id"], []):
            if match["choice_id"] == choice_id:
                score = int(match["score"])
                break
        if score:
            rows.append((score, item))
    rows.sort(key=lambda pair: (-pair[0], {"A": 0, "B": 1, "C": 2}.get(pair[1].get("quality"), 9), pair[1].get("source_path", "")))
    return [item for _score, item in rows[:limit]]


def write_json(raw: dict[str, Any], summary: dict[str, Any], evidence_choices: dict[str, list[dict[str, Any]]], case_hits: dict[str, list[dict[str, Any]]]) -> None:
    payload = {
        "summary": summary,
        "choices": [asdict(choice) for choice in CHOICES],
        "evidence_choice_assignments": evidence_choices,
        "cases": [
            {
                "case": asdict(case),
                "evidence_count": len(case_hits[case.case_id]),
                "evidence_ids": [item["evidence_id"] for item in case_hits[case.case_id]],
            }
            for case in CASES
        ],
        "v5_summary": raw.get("summary", {}),
        "v4_backtest": raw.get("v4_backtest", {}),
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_index_csv(evidence: list[dict[str, Any]], evidence_choices: dict[str, list[dict[str, Any]]]) -> None:
    with OUT_INDEX_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "evidence_id",
                "source_type",
                "quality",
                "date",
                "source_path",
                "line_start",
                "tags",
                "actions",
                "results",
                "choice_ids",
                "snippet",
            ],
        )
        writer.writeheader()
        for item in evidence:
            writer.writerow(
                {
                    "evidence_id": item["evidence_id"],
                    "source_type": item.get("source_type", ""),
                    "quality": item.get("quality", ""),
                    "date": item.get("date", ""),
                    "source_path": item.get("source_path", ""),
                    "line_start": item.get("line_start", ""),
                    "tags": ",".join(item.get("tags") or []),
                    "actions": ",".join(item.get("actions") or []),
                    "results": ",".join(item.get("results") or []),
                    "choice_ids": ",".join(match["choice_id"] for match in evidence_choices.get(item["evidence_id"], [])),
                    "snippet": item.get("snippet", ""),
                }
            )


def write_matrix_md(raw: dict[str, Any], summary: dict[str, Any], evidence_choices: dict[str, list[dict[str, Any]]]) -> None:
    evidence = raw["evidence"]
    choice_by_id = {choice.choice_id: choice for choice in CHOICES}
    lines = [
        "# 순환매 미시 선택 매트릭스 v6",
        "",
        "이 문서는 v5의 `원인 -> 판단 -> 행동 -> 결과`를 더 잘게 쪼개서, 실제 시스템이 매 순간 선택해야 하는 작은 결정을 정리한 것이다. 목표는 `롱/숏 진입 신호`가 아니라 `왜 이 선택은 하고, 왜 반대 선택은 하지 않는지`를 기계 규칙으로 바꾸는 것이다.",
        "",
        "## 1. 커버리지",
        "",
        f"- v5 원본 근거 단위: `{summary['original_evidence_count']}`",
        f"- 관리/법률 고지 제외: `{summary['excluded_noise_count']}`",
        f"- 전략 근거 단위: `{summary['evidence_count']}`",
        f"- 미시 선택 수: `{summary['choice_count']}`",
        f"- 선택이 매핑된 근거: `{summary['assigned_evidence_count']}`",
        f"- 미분류 근거: `{summary['uncovered_evidence_count']}`",
        f"- 레이어 분포: `{json.dumps(summary['layer_counts'], ensure_ascii=False)}`",
        "",
        "## 2. 선택 빈도 상위",
        "",
        "| choice | count | layer | meaning |",
        "|---|---:|---|---|",
    ]
    for choice_id, count in list(summary["choice_counts"].items())[:30]:
        choice = choice_by_id[choice_id]
        lines.append(f"| `{choice_id}` | {count} | {choice.layer} | {md_cell(choice.title)} |")

    lines.extend(
        [
            "",
            "## 3. 전체 미시 선택 사전",
            "",
            "| id | layer | 질문 | 해야 하는 선택 | 하지 말아야 할 선택 | 트리거 | 시스템 변수 | 근거 수 |",
            "|---|---|---|---|---|---|---|---:|",
        ]
    )
    for choice in CHOICES:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{choice.choice_id}` {md_cell(choice.title)}",
                    md_cell(choice.layer),
                    md_cell(choice.question),
                    md_cell(choice.choose),
                    md_cell(choice.reject),
                    md_cell(choice.trigger),
                    f"`{md_cell(choice.system_variable)}`",
                    str(summary["choice_counts"].get(choice.choice_id, 0)),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 4. 선택별 이유와 실패 조건",
            "",
        ]
    )
    for choice in CHOICES:
        lines.extend(
            [
                f"### {choice.choice_id}. {choice.title}",
                "",
                f"- 판단 질문: {choice.question}",
                f"- 선택: {choice.choose}",
                f"- 배제: {choice.reject}",
                f"- 이유: {choice.reason}",
                f"- 틀리면 생기는 문제: {choice.failure_if_wrong}",
                f"- 구현 변수: `{choice.system_variable}`",
                "",
                "| evidence | source | tags/actions | snippet |",
                "|---|---|---|---|",
            ]
        )
        for item in top_evidence_for_choice(evidence, evidence_choices, choice.choice_id, limit=4):
            tags = ",".join(item.get("tags") or [])
            actions = ",".join(item.get("actions") or [])
            tag_action = tags if not actions else f"{tags} / actions={actions}"
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_cell(item["evidence_id"]),
                        md_cell(f"{item.get('source_path')}:{item.get('line_start')}"),
                        md_cell(tag_action),
                        md_cell(compact(item.get("snippet") or "")),
                    ]
                )
                + " |"
            )
        lines.append("")

    lines.extend(
        [
            "## 5. 같이 자주 등장하는 선택",
            "",
            "| pair | count | interpretation |",
            "|---|---:|---|",
        ]
    )
    for pair, count in list(summary["co_occurrence"].items())[:25]:
        left, right = pair.split("+")
        interpretation = f"{choice_by_id[left].title} + {choice_by_id[right].title}"
        lines.append(f"| `{pair}` | {count} | {md_cell(interpretation)} |")

    lines.extend(
        [
            "",
            "## 6. v4 백테스트에 대한 직접 판정",
            "",
            "v4는 방향 분포가 아니라 선택 우선순위가 틀렸다. 자료는 `관망 -> 좋은 마디 대기 -> 역할별 진입 -> 반응 감축 -> 평단 재계산 -> 무효화/스위칭` 순서인데, v4는 `probe 진입 -> 손실 수술`이 너무 앞섰다.",
            "",
            "| v4 문제 | 누락된 미시 선택 | 수정 방향 |",
            "|---|---|---|",
            "| probe가 손실 중심 | `MC04`, `MC08`, `MC12`, `MC13` | 중앙값/이미 진행/숫자 단독/초기 과진입 차단 |",
            "| battle 거의 없음 | `MC06`, `MC07` | battle을 사전 계획된 주 이벤트로 승격 |",
            "| repair_stop 과다 | `MC17`, `MC18`, `MC19` | 기대 반응 안에서만 평단 수술, 반응 감축 우선 |",
            "| profit_trim 부족 | `MC18`, `MC22` | 익절을 재고관리 이벤트로 먼저 실행 |",
            "| 스위칭 단순화 위험 | `MC24`, `MC25` | 스위칭/헷징은 회복가 이전 조건 통과 시만 허용 |",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def choice_chain_for_case(case: CaseSpec, hits: list[dict[str, Any]]) -> list[str]:
    observed = Counter(choice_id for item in hits for choice_id in item.get("choice_ids", []))
    chain: list[str] = []
    for choice_id in case.expected_choices:
        count = observed.get(choice_id, 0)
        chain.append(f"`{choice_id}` {'확인' if count else '근거 부족'}({count})")
    extras = [choice_id for choice_id, _ in observed.most_common(8) if choice_id not in case.expected_choices]
    if extras:
        chain.append("추가 관찰: " + ", ".join(f"`{item}`({observed[item]})" for item in extras[:6]))
    return chain


def write_case_md(case_hits: dict[str, list[dict[str, Any]]]) -> None:
    choice_by_id = {choice.choice_id: choice for choice in CHOICES}
    lines = [
        "# 순환매 케이스별 미시 선택 감사 v6",
        "",
        "이 문서는 자료 속 대표 케이스를 `상황 -> 선택지 -> 실제 선택 -> 선택하지 않은 것 -> 시스템 반영`으로 다시 분해한 것이다.",
        "",
    ]
    for case in CASES:
        hits = case_hits[case.case_id]
        observed = Counter(choice_id for item in hits for choice_id in item.get("choice_ids", []))
        lines.extend(
            [
                f"## {case.case_id}. {case.title}",
                "",
                f"- 목적: {case.purpose}",
                f"- 근거 수: `{len(hits)}`",
                f"- 기대 선택 체인: {' -> '.join(choice_chain_for_case(case, hits))}",
                "",
                "| 선택 | 자료상 의미 | 구현 체크 |",
                "|---|---|---|",
            ]
        )
        for choice_id in case.expected_choices:
            choice = choice_by_id[choice_id]
            status = "확인" if observed.get(choice_id, 0) else "근거 부족"
            lines.append(
                f"| `{choice_id}` {md_cell(choice.title)} | {md_cell(choice.reason)} | {status}: `{choice.system_variable}` |"
            )
        lines.extend(["", "| evidence | source | choices | snippet |", "|---|---|---|---|"])
        sample = sorted(
            hits,
            key=lambda item: (
                -len(set(item.get("choice_ids", [])) & set(case.expected_choices)),
                item.get("source_path") or "",
                item.get("line_start") or 0,
            ),
        )[:8]
        for item in sample:
            lines.append(
                "| "
                + " | ".join(
                    [
                        md_cell(item["evidence_id"]),
                        md_cell(f"{item.get('source_path')}:{item.get('line_start')}"),
                        md_cell(",".join(item.get("choice_ids", [])[:8])),
                        md_cell(compact(item.get("snippet") or "", 320)),
                    ]
                )
                + " |"
            )
        lines.append("")

    lines.extend(
        [
            "## 구현상 테스트해야 할 작은 선택",
            "",
            "1. `no_trade`가 실제로 주문 수를 줄이는지, 줄인 주문이 손실 주문인지 확인한다.",
            "2. `battle_zone_primary`를 켰을 때 battle 비중이 늘되 MDD가 급증하지 않는지 본다.",
            "3. `reaction_trim`이 repair_stop보다 먼저 실행되는지 이벤트 순서를 검사한다.",
            "4. `already_touched`가 같은 마디 반복 진입을 줄이는지 본다.",
            "5. `switch_permission`이 단순 왕복이 아니라 회복가 이전 조건에서만 켜지는지 확인한다.",
            "6. `capacity_gate`를 켰을 때 풀시드 근접 add가 사라지는지 본다.",
            "",
        ]
    )
    OUT_CASE_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    raw = load_v5()
    evidence = strategy_evidence(raw)
    evidence_choices = {item["evidence_id"]: assign_choices(item) for item in evidence}
    summary = build_summary(evidence, len(raw["evidence"]))
    case_hits = build_case_hits(evidence, evidence_choices)
    write_json(raw, summary, evidence_choices, case_hits)
    write_index_csv(evidence, evidence_choices)
    write_matrix_md(raw, summary, evidence_choices)
    write_case_md(case_hits)
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print(f"wrote {OUT_CASE_MD}")
    print(f"wrote {OUT_INDEX_CSV}")


if __name__ == "__main__":
    main()
