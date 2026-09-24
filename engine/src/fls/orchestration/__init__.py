"""fls.orchestration — Temporal orchestration for the harness PoC (2026-09-10).

One durable workflow per expedition (`HarnessExpedition`, id `exp-{number}`), one activity per
rung, signals for the human protocol (pick / approve / feedback / kill), a status query the Demo
view polls THROUGH the harness. Temporal owns sequencing, waiting, retries, timeouts, and history.
The FLS ledger + expedition store remain the system of record for cost and verdicts.

Layout: `types.py` (dataclass payloads, shared by workflow and activities), `activities.py` (thin
wrappers over rung code via a pluggable Runner), `workflows.py` (the gated loops), `client.py`
(start / signal / status for the harness), `settings.py` (env).
"""
