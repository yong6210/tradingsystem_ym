# Auto Trading Rollout Drill Report

- Generated at (UTC): 20260309T050705Z
- Scope: SHADOW -> PAPER -> MICRO_LIVE preflight -> pruning reevaluation
- Mode: temporary drill only

## Drill Setup
- Temporary server overrides:
  - `AUTO_TRADING_ENABLED=true`
  - `AUTO_TRADING_REQUIRE_VALIDATION_GO=false`
  - `AUTO_TRADING_EXECUTION_MODE=MICRO_LIVE`
  - `AUTO_TRADING_MICRO_LIVE_ALLOWED_SYMBOLS=SUIUSDC,BTCUSDC,ETHUSDC`
  - `AUTO_TRADING_MICRO_LIVE_ALLOWED_FAMILIES=legacy_zone_plan,trend_continuation`
- Temporary rollout override:
  - `legacy_zone_plan -> live_enabled=true, max_execution_mode=MICRO_LIVE`
- Selected plan:
  - `plan_zone_9b73567479cb_confirm`
  - symbol: `SUIUSDC`
  - family: `legacy_zone_plan`
  - model: `CONFIRM`

## Results
### 1. SHADOW
- approval_state: `APPROVED_SHADOW`
- submit_decision: `SKIP_SHADOW_ONLY`
- playbook_code: `rollout_shadow_only`
- Meaning: shadow path correctly recorded the intent without submit.

### 2. PAPER
- approval_state: `APPROVED_AUTO`
- submit_decision: `SUBMIT`
- submit result:
  - adapter: `paper`
  - state: `FILLED`
  - submit_status: `FILLED`
- fill ingest result:
  - `PLANNED -> ENTERED`
- Meaning: paper execution path, submission ledger, and fill/state-machine path all worked.

### 3. MICRO_LIVE preflight
- approval_state: `BLOCKED`
- submit_decision: `SKIP_BLOCKED`
- playbook_code: `micro_live_session_not_allowed`
- Meaning: micro-live was correctly blocked because the current session was `inactive` and outside the allowed session list.

### 4. Reconciliation
- symbol-level reconcile (`SUIUSDC`): `healthy=true`, `mismatches=[]`
- global dashboard reconcile summary remained degraded due unrelated pre-existing symbol locks.
- Meaning: the drill symbol was healthy, but global live-readiness is still not clean.

## Pruning Re-evaluation
### Decision
- `contract pruning` remains **deferred**.

### Why
- This drill included SHADOW and PAPER, plus MICRO_LIVE preflight only.
- There was **no actual micro-live order path** because:
  - Binance API credentials are not configured
  - `BINANCE_TRADE_LIVE_ENABLED=false`
  - current session gate blocked MICRO_LIVE before submit
- The optional hold rule in the living docs is still correct: pruning should be re-evaluated **after the first actual live operating cycle**, not after a drill.

### Current recommendation
- Keep the optional hold unchanged.
- Re-evaluate pruning only after:
  1. at least one real MICRO_LIVE session,
  2. execution/reconciliation/alert surfaces are used during that session,
  3. post-session review confirms which duplicated contract fields are actually unnecessary.

## Final Assessment
- SHADOW: pass
- PAPER: pass
- MICRO_LIVE: blocked as designed
- Pruning re-evaluation: not yet actionable
