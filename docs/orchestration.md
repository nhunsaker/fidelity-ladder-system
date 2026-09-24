# Orchestration — a durable workflow per expedition (optional)

By default the ladder climbs in-process (`fls.climb.advance_expedition`). An instance that wants
long-running, human-gated rungs to survive restarts and to be visible as history can switch on
**Temporal** orchestration: one workflow per expedition, one activity per rung, the human protocol
as signals, and a status query the admin polls through the harness.

```
FLS_ORCHESTRATION=temporal      # in instance.env; unset = in-process (default)
FLS_PROFILE=harness-poc         # any registered LadderProfile (fls.profile.PROFILES)
TEMPORAL_ADDRESS=127.0.0.1:7233 TEMPORAL_NAMESPACE=default TEMPORAL_TASK_QUEUE=fls-harness
python -m fls.worker            # the worker: workflow + activities on that task queue
```

## What Temporal owns, what the ledger owns

| Concern | Owner |
|---|---|
| sequencing, waiting at a gate, activity timeouts, infrastructure retries, history | Temporal (`fls.orchestration.workflows.HarnessExpedition`) |
| cost accounting, verdicts, human decisions, calibration | the FLS ledger + expedition store (unchanged) |
| the builders' own retry loop (rung 4) | the rung code (`fls.rung4`) inside the activity |

## The human protocol, unchanged

`/pick N`, `/approve`, free-text feedback and kill still arrive through the one door. With a GitHub
surface configured, the signed webhook echo forwards each command as a signal
(`fls.orchestration.client.command_to_signal`). In local mode, `POST /expeditions/{n}/feedback`
(named actor required, fail-closed) records the decision in the ledger and signals the workflow.
The store is never written by the feedback path. `approve` means "approved with no revisions" and
is the only way up; feedback re-runs the current rung with the text attached, bounded by
`WorkflowConfig.max_feedback_rounds`.

## Signals and the query

| Signal | Payload | Effect |
|---|---|---|
| `pick` | int | rung 2 (choose one of N candidates) |
| `approve` | — | advance off rung 3 / 4 / 5 |
| `feedback` | str | re-run the current rung, text in context |
| `kill` | str | park the expedition |

Query `status` → `{number, rung, state, stage, detail, artifacts, spent_normalized_usd, feedback_log,
killed, attempts}`. `stage` is in end-user words (`requested · wireframed · previewed · built ·
shipped`); `state` is the ladder's (`climbing · await-pick · await-approve · await-signoff ·
descended · parked · done`). `GET /expeditions/{n}` merges it as `workflow`.

## Runners and the agentic builder

Activities call a pluggable `Runner` (`fls.orchestration.activities.RUNNER`). `StubRunner` proves
the plumbing (rung 2 runs one real Claude CLI turn so the ledger shows a `claude-code` row;
everything else is canned). Live runners wrap the real rung code.

Agentic builders use `fls.claude_code.ClaudeCodeSession`: `claude -p` with a working directory, an
allowed-tool list, `--mcp-config`, and a **turns + wall-clock** budget from the ANCHOR `worker:`
block. Accounting rides the subscription lane (`usd=0`, `normalized_usd` from the CLI's own cost
figure). The CLI reads its login from `$HOME/.claude` on the worker host; the engine never reads a
credential.

```yaml
worker:                 # optional ANCHOR block; absent = defaults (30 turns / 600 s)
  rungs:
    "2": { max_turns: 25,  wall_clock_s: 600 }
    "3": { max_turns: 40,  wall_clock_s: 900 }
    "4": { max_turns: 120, wall_clock_s: 2400 }
```

## Tests

`engine/tests/test_orchestration_workflow.py` runs the workflow under Temporal's time-skipping test
server (downloaded on first use; the suite skips if it cannot start). Happy path through every
gate, feedback re-run, bounded rounds, kill, descended rung, and the command mapping.
