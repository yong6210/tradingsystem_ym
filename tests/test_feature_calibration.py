from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db.models import Plan, Zone, ZoneOutcome
from app.db.repositories import OutcomeRepository, PlanRepository
from app.db.session import SessionLocal, init_db
from app.services.context_engine import ContextSnapshot
from app.services.feature_calibration import FeatureCalibrationService
from app.services.plan_generator import PlanGenerator


def _seed_plan_and_outcome(
    *,
    db,
    symbol: str,
    suffix: str,
    zone_type: str,
    entry_model: str,
    regime: str,
    confluence_components: dict[str, float],
    realized_r: int,
    valid_from: datetime,
) -> None:
    zone_id = f"{symbol}_{suffix}_{zone_type.lower()}"
    plan = Plan(
        plan_id=f"{symbol}_{suffix}_plan",
        zone_id=zone_id,
        symbol=symbol,
        timeframe="5m",
        direction="long",
        entry_model=entry_model,
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=98.5,
        tp1=101.0,
        tp2=102.0,
        tp3=103.0,
        split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
        rr_min=1.5,
        rr_base=2.0,
        rr_opt=3.0,
        ev=0.35,
        cost_est=0.08,
        confidence=0.72,
        validity={
            "regime": regime,
            "zone_type": zone_type,
            "confluence_components": confluence_components,
            "meta_reason": "meta_pass",
        },
        state="CLOSED",
        valid_from=valid_from,
        valid_until=valid_from + timedelta(hours=4),
        strategy_version="v1",
    )
    db.add(plan)

    db.add(
        ZoneOutcome(
            zone_id=zone_id,
            symbol=symbol,
            touch_ts=valid_from + timedelta(minutes=5),
            entry_model_used=entry_model,
            entry_ts=valid_from + timedelta(minutes=10),
            entry_price=100.1,
            sl_price=98.5,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            mfe_atr=1.2,
            mae_atr=0.4,
            mfe_pct=1.3,
            mae_pct=0.5,
            hit_1r=realized_r >= 1,
            hit_2r=realized_r >= 2,
            hit_3r=realized_r >= 3,
            sweep_detected=False,
            sweep_success=False,
            friction_at_touch=0.18,
            regime_at_touch=0.52,
            strategy_version="v1",
        )
    )


def _context() -> ContextSnapshot:
    return ContextSnapshot(
        symbol="BTCUSDC",
        regime_15m=0.55,
        jump_rate_5m=0.05,
        friction_5m=0.17,
        atr5=0.5,
        atr15=1.0,
        sdir=0.35,
        sevt=-0.08,
        f=0.28,
        v=0.64,
        a=0.18,
        vz=0.52,
        az=0.22,
        last_price=99.1,
        regime_label="range",
    )


def _zone(*, zone_id: str, zone_type: str, dir_bias: str, low: float, high: float, mid: float) -> Zone:
    return Zone(
        zone_id=zone_id,
        symbol="BTCUSDC",
        timeframe="15m",
        type=zone_type,
        low=low,
        high=high,
        mid=mid,
        width_atr=0.4,
        dir_bias=dir_bias,
        created_ts=datetime.now(timezone.utc),
        touch_count=1,
        base_strength=79.0,
        quality=75.0,
        state="active",
        stats={"p1r": 0.70, "p2r": 0.50, "p3r": 0.28, "ev_r": 0.42, "sample_size": 96},
        strategy_version="v1",
    )


def test_feature_calibration_generates_runtime_overrides_from_recent_outcomes(tmp_path: Path) -> None:
    init_db()
    settings = PlanGenerator().settings
    original_snapshot_dir = settings.feature_calibration_snapshot_dir
    original_report_dir = settings.feature_calibration_report_dir
    original_min_matches = settings.feature_calibration_min_matches
    original_min_regime_matches = settings.feature_calibration_min_regime_matches
    original_min_generated_plans = settings.feature_calibration_min_generated_plans

    symbol = f"FCAL{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=4)

    try:
        settings.feature_calibration_snapshot_dir = str(tmp_path / "snapshots")
        settings.feature_calibration_report_dir = str(tmp_path / "reports")
        settings.feature_calibration_min_matches = 4
        settings.feature_calibration_min_regime_matches = 2
        settings.feature_calibration_min_generated_plans = 4

        with SessionLocal() as db:
            for index in range(4):
                _seed_plan_and_outcome(
                    db=db,
                    symbol=symbol,
                    suffix=f"ob_win_{index}",
                    zone_type="OB",
                    entry_model="LIMIT",
                    regime="range",
                    confluence_components={
                        "liquidity": 92.0,
                        "fvg_displacement": 12.0,
                        "htf_alignment": 78.0,
                        "ob_freshness": 83.0,
                        "trend_proxy": 58.0,
                    },
                    realized_r=2,
                    valid_from=base + timedelta(hours=index),
                )
            for index in range(2):
                _seed_plan_and_outcome(
                    db=db,
                    symbol=symbol,
                    suffix=f"fvg_loss_{index}",
                    zone_type="FVG",
                    entry_model="CONFIRM",
                    regime="range",
                    confluence_components={
                        "liquidity": 14.0,
                        "fvg_displacement": 91.0,
                        "htf_alignment": 30.0,
                        "ob_freshness": 22.0,
                        "trend_proxy": 40.0,
                    },
                    realized_r=0,
                    valid_from=base + timedelta(hours=8 + index),
                )
            db.commit()

            service = FeatureCalibrationService(
                PlanGenerator(),
                settings=settings,
                plan_repo=PlanRepository(db),
                outcome_repo=OutcomeRepository(db),
            )
            payload = service.generate(
                symbol=symbol,
                regime_label="range",
                feature_importance={"available": True, "baseline": {"generated_plans": 6}},
                write_report=True,
            )

            assert payload["available"] is True
            assert payload["matched_samples"] == 6
            assert Path(payload["snapshot_path"]).exists()
            assert Path(payload["report_path"]).exists()
            assert payload["recommended_weights"]["liquidity"] > payload["baseline_weights"]["liquidity"]
            assert payload["recommended_weights"]["fvg_displacement"] < payload["baseline_weights"]["fvg_displacement"]
            assert payload["zone_type_multipliers"]["OB"]["active_multiplier"] > 1.0
            assert payload["zone_type_multipliers"]["FVG"]["active_multiplier"] < 1.0

            runtime = service.runtime_payload(symbol=symbol, regime_label="range")
            assert runtime is not None
            assert runtime["available"] is True
            assert runtime["by_regime"]["range"]["feature_weights_active"] == payload["recommended_weights"]
            assert runtime["zone_type_multipliers"]["OB"]["active_multiplier"] == payload["zone_type_multipliers"]["OB"]["active_multiplier"]
    finally:
        settings.feature_calibration_snapshot_dir = original_snapshot_dir
        settings.feature_calibration_report_dir = original_report_dir
        settings.feature_calibration_min_matches = original_min_matches
        settings.feature_calibration_min_regime_matches = original_min_regime_matches
        settings.feature_calibration_min_generated_plans = original_min_generated_plans


def test_feature_calibration_requires_minimum_generated_plans(tmp_path: Path) -> None:
    init_db()
    settings = PlanGenerator().settings
    original_snapshot_dir = settings.feature_calibration_snapshot_dir
    original_report_dir = settings.feature_calibration_report_dir
    original_min_matches = settings.feature_calibration_min_matches
    original_min_generated_plans = settings.feature_calibration_min_generated_plans

    symbol = f"FCMIN{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=3)

    try:
        settings.feature_calibration_snapshot_dir = str(tmp_path / "snapshots")
        settings.feature_calibration_report_dir = str(tmp_path / "reports")
        settings.feature_calibration_min_matches = 4
        settings.feature_calibration_min_generated_plans = 5

        with SessionLocal() as db:
            for index in range(4):
                _seed_plan_and_outcome(
                    db=db,
                    symbol=symbol,
                    suffix=f"ob_{index}",
                    zone_type="OB",
                    entry_model="LIMIT",
                    regime="range",
                    confluence_components={
                        "liquidity": 80.0,
                        "fvg_displacement": 20.0,
                        "htf_alignment": 70.0,
                        "ob_freshness": 76.0,
                        "trend_proxy": 55.0,
                    },
                    realized_r=1,
                    valid_from=base + timedelta(hours=index),
                )
            db.commit()

            service = FeatureCalibrationService(
                PlanGenerator(),
                settings=settings,
                plan_repo=PlanRepository(db),
                outcome_repo=OutcomeRepository(db),
            )
            payload = service.generate(
                symbol=symbol,
                regime_label="range",
                feature_importance={"available": True, "baseline": {"generated_plans": 2}},
                write_report=False,
            )

            assert payload["available"] is False
            assert payload["reason"] == "insufficient_generated_plans"
            assert payload["matched_samples"] == 4
            assert payload["report_path"] is None
    finally:
        settings.feature_calibration_snapshot_dir = original_snapshot_dir
        settings.feature_calibration_report_dir = original_report_dir
        settings.feature_calibration_min_matches = original_min_matches
        settings.feature_calibration_min_generated_plans = original_min_generated_plans


def test_feature_calibration_runtime_payload_tolerates_legacy_snapshot_without_generated_at(tmp_path: Path) -> None:
    settings = PlanGenerator().settings
    original_snapshot_dir = settings.feature_calibration_snapshot_dir
    try:
        settings.feature_calibration_snapshot_dir = str(tmp_path / "snapshots")
        service = FeatureCalibrationService(PlanGenerator(), settings=settings)
        snapshot_path = service._latest_snapshot_path(service._snapshot_dir(), symbol="BTCUSDC", regime_label="range")
        snapshot_path.write_text(
            json.dumps(
                {
                    "available": True,
                    "symbol": "BTCUSDC",
                    "regime_label": "range",
                    "baseline_generated_plans": 5,
                    "matched_samples": 3,
                    "baseline_weights": {},
                    "previous_weights": {},
                    "recommended_weights": {},
                    "current_scores": {},
                    "ewma_scores": {},
                    "by_regime": {},
                    "zone_type_multipliers": {},
                }
            ),
            encoding="utf-8",
        )

        payload = service.runtime_payload(symbol="BTCUSDC", regime_label="range")

        assert payload is not None
        assert payload["available"] is True
        assert payload["generated_at"]
    finally:
        settings.feature_calibration_snapshot_dir = original_snapshot_dir


def test_feature_calibration_tolerates_malformed_numeric_settings_and_snapshot(tmp_path: Path) -> None:
    settings = PlanGenerator().settings
    original_values = {
        "feature_calibration_snapshot_dir": settings.feature_calibration_snapshot_dir,
        "feature_calibration_report_dir": settings.feature_calibration_report_dir,
        "feature_calibration_alpha": settings.feature_calibration_alpha,
        "feature_calibration_max_delta": settings.feature_calibration_max_delta,
        "feature_calibration_min_weight": settings.feature_calibration_min_weight,
        "feature_calibration_min_generated_plans": settings.feature_calibration_min_generated_plans,
    }
    try:
        settings.feature_calibration_snapshot_dir = str(tmp_path / "snapshots")
        settings.feature_calibration_report_dir = str(tmp_path / "reports")
        settings.feature_calibration_alpha = "bad"
        settings.feature_calibration_max_delta = float("inf")
        settings.feature_calibration_min_weight = "bad"
        settings.feature_calibration_min_generated_plans = "bad"

        service = FeatureCalibrationService(PlanGenerator(), settings=settings)
        payload = service.generate(
            symbol="BTCUSDC",
            regime_label="range",
            feature_importance={
                "available": True,
                "baseline": {"generated_plans": "4"},
                "by_feature": {"liquidity": {"importance_score": "bad"}},
            },
            write_report=False,
        )

        assert payload["available"] is True
        assert payload["alpha"] == 0.35
        assert payload["baseline_generated_plans"] == 4

        snapshot_path = service._latest_snapshot_path(service._snapshot_dir(), symbol="BTCUSDC", regime_label="range")
        snapshot_path.write_text(
            json.dumps(
                {
                    "available": True,
                    "symbol": "BTCUSDC",
                    "regime_label": "range",
                    "baseline_generated_plans": "bad",
                    "matched_samples": float("inf"),
                    "baseline_weights": {"liquidity": "bad"},
                    "previous_weights": {"liquidity": float("inf")},
                    "recommended_weights": {"liquidity": "bad"},
                    "current_scores": {"liquidity": "bad"},
                    "ewma_scores": {"liquidity": float("inf")},
                    "by_regime": {"range": {"matched_samples": "bad", "feature_weights_active": {"liquidity": "bad"}}},
                    "zone_type_multipliers": {"OB": {"active_multiplier": "bad", "matched_samples": "bad"}},
                }
            ),
            encoding="utf-8",
        )

        runtime = service.runtime_payload(symbol="BTCUSDC", regime_label="range")

        assert runtime is not None
        assert runtime["baseline_generated_plans"] == 0
        assert runtime["matched_samples"] == 0
        assert runtime["zone_type_multipliers"]["OB"]["active_multiplier"] == 1.0
    finally:
        for key, value in original_values.items():
            setattr(settings, key, value)


def test_plan_generator_applies_feature_calibration_to_validity_metadata() -> None:
    generator = PlanGenerator()
    calibration = {
        "available": True,
        "matched_samples": 18,
        "by_regime": {
            "range": {
                "feature_weights_active": {
                    "liquidity": 0.32,
                    "fvg_displacement": 0.12,
                    "htf_alignment": 0.20,
                    "ob_freshness": 0.22,
                    "trend_proxy": 0.14,
                }
            }
        },
        "zone_type_multipliers": {
            "OB": {"active_multiplier": 1.08},
            "LP": {"active_multiplier": 1.0},
            "FVG": {"active_multiplier": 0.92},
            "FLIP": {"active_multiplier": 1.0},
        },
    }

    ranked = generator.generate(
        symbol="BTCUSDC",
        zones=[
            _zone(zone_id="z_support", zone_type="OB", dir_bias="support", low=98.8, high=99.2, mid=99.0),
            _zone(zone_id="z_target", zone_type="LP", dir_bias="resistance", low=101.8, high=102.2, mid=102.0),
        ],
        context=_context(),
        importance_calibration=calibration,
    )

    assert ranked
    validity = ranked[0].plan.validity
    assert validity["feature_calibration_available"] is True
    assert validity["feature_calibration_samples"] == 18
    assert validity["feature_weights_active"]["liquidity"] == 0.32
    assert validity["feature_weights_active"]["fvg_displacement"] == 0.12
    assert validity["zone_type_multiplier_active"] == pytest.approx(1.080518, rel=1e-6)
