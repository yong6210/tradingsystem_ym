"""Review every frozen entry without selecting on its outcome."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.btcusdc import load_public_bundle
from app.research.recovery.entry_review import review_entry


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    plans = json.loads((args.source / "plans.json").read_text())
    bundle = load_public_bundle(ROOT, ROOT / "data/historical/btcusdc_public_20260917")
    cards = [review_entry(plan, bundle.trade) for plan in plans]
    # Outcomes are deliberately joined only AFTER all decision cards exist.
    outcomes = json.loads((args.source / "summary.json").read_text())
    results = {r["plan_id"]: r for r in outcomes if r["policy"] == "no_add" and r["cost"] == "base"}
    for card in cards:
        result = results[card["plan_id"]]
        card["after_entry_outcome"] = {k: result[k] for k in ("net_liquidation_pnl", "holding_minutes")}
    paths = [args.source / n for n in ("plans.json", "summary.json")]
    paths += [Path(__file__), ROOT / "app/research/recovery/entry_review.py"]
    payload = dict(kind="REUSED_SAMPLE_DESCRIPTIVE_AUDIT", cards=cards,
                   source_sha256={str(x): hashlib.sha256(x.read_bytes()).hexdigest() for x in paths},
                   live_orders_sent=0, admission_threshold_fitted=False)
    (args.output / "entry_cards.json").write_text(json.dumps(payload, indent=2, allow_nan=False)+"\n")
    rows = ["# 최초 진입 근거 점검", "", "모든 12개 진입을 포함한다. 가격 기준은 진입 직전 완성 1분봉 종가다. 과거 24시간 범위는 설명용이며 목표 도달 확률이나 진입 필터가 아니다.", "",
            "| UTC 진입 | 방향 | 큰 흐름 일치 | 목표 거리 % | 목표 거리 / 직전 24h 범위 | 이후 무추가 손익 USDC |",
            "|---|---|---|---:|---:|---:|"]
    from datetime import datetime, timezone
    for c in cards:
        date = datetime.fromtimestamp(c["decision_ms"]/1000, timezone.utc).strftime("%m-%d %H:%M")
        ratio = "미정" if c["target_to_prior_range"] is None else f'{c["target_to_prior_range"]:.2f}'
        rows.append(f'| {date} | {"롱" if c["side"] == 1 else "숏"} | {"일치" if c["aligned"] else "반대"} | {c["target_distance_pct"]:.2f} | {ratio} | {float(c["after_entry_outcome"]["net_liquidation_pnl"]):.2f} |')
    rows += ["", "12건 모두 목표 시간·도달 근거·중간 구조·구간 상태 이력이 계약에 명시되지 않았다. 이는 당시 거래가 모두 틀렸다는 판정이 아니라 기록만으로 판단을 재현할 수 없다는 뜻이다.", "",
             "구간과 과거 봉의 겹침은 현재 선택한 구간을 과거 가격에 투영한 설명이다. 그 구간이 당시에도 존재했거나 유효했다는 증거로 쓰지 않는다. 이후 손익은 별도 필드에 보관하며 사전 판단에 입력하지 않는다."]
    (args.output / "review.md").write_text("\n".join(rows)+"\n")
    print(args.output / "review.md")


if __name__ == "__main__":
    main()
