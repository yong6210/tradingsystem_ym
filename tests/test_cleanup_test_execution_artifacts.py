from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_cleanup_module():
    script_path = Path("/Users/yumin/Documents/trading/scripts/cleanup_test_execution_artifacts.py")
    spec = importlib.util.spec_from_file_location("cleanup_test_execution_artifacts", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cleanup_patterns_cover_current_execution_transition_prefixes() -> None:
    module = _load_cleanup_module()
    patterns = module._compile_patterns(module.TEST_SYMBOL_PATTERNS)

    samples = (
        "BTCPRIO123USDC",
        "ETHPRIO123USDC",
        "CLUSTER123USDC",
        "PCOLL123USDC",
        "PEXFAST123USDC",
        "PEXFASTSKIP123USDC",
        "PEXCLOSE123USDC",
        "PEXTIME123USDC",
        "STALEDUPE123USDC",
        "STALESUB123USDC",
    )

    for sample in samples:
        assert module._matches_any(sample, patterns), sample
