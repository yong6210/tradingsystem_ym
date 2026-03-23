# README / Docs Sync Policy

## Purpose

- `README.md` is the entry document.
- `docs/*` holds detailed protocols, strategy notes, and runbooks.
- `tests/*` and endpoint response models confirm public contract shape.
- Operator UI and operator dashboard show the live operating picture.

Keep these layers aligned without turning the README into a full spec dump.

## Review Triggers

Run a README/docs sync check when any of the following changes:

- Public endpoint path, method, or top-level contract
- Authority boundary or approval surface meaning
- Operator dashboard or operator UI labels, sections, or navigation
- `validation/report` or `operations/checklist` topline semantics
- Execution/control semantics such as preview, approve, submit, reconcile, kill-switch, close-only, or rollout policy
- TradingView mirror meaning or context-vs-authority wording
- Bootstrap or optional integration path
- Docs index structure or canonical start-here docs

## PR / Task Check Block

Use this block in PRs or task reviews when a public contract may have changed:

- `[ ] README impact 없음 / 반영 완료`
- `[ ] Docs Index impact 없음 / 반영 완료`
- `[ ] Operator UI / Operator Dashboard impact 없음 / 반영 완료`
- `[ ] API Quick Path impact 없음 / 반영 완료`
- `[ ] Authority Map impact 없음 / 반영 완료`

Use `영향 없음` only when the external path, label, order, and meaning remain unchanged.

## Always Review First

These README sections go stale fastest:

- `Start Here`
- `Authority Map`
- `Operator Surfaces`
- `API Quick Path`

## Review On Demand

Review these when related meaning changes:

- `Full API Catalog`
- `Quick Start`
- `Notes`
- `TradingView Mirror`
- `Optional Integrations`
- `Alert Wiring`
- `Worker`
- `Docs Index`

## Responsibility Split

- README explains where to start and what each surface means.
- Docs explain the detailed rules and operating protocols.
- Tests and response models confirm the contract.
- Operator surfaces show the current operating picture.

If the repo later adds a PR template, mirror the `PR / Task Check Block` there.
