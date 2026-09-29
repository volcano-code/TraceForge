# 0.3.2.dev0 — submission intent and business-flow verification

## Scope and origin

This repair is based on `c004395b32374b1d5f802c2e7d4934b74baeb5b9` / source snapshot commit `436bd3337b602e37413d2d7f317b44150ffb9469`. The baseline Git tree was verified against the downloaded GitHub Actions snapshot. `main` is not merged. No model, arbitrary repository or product GitHub delivery is enabled.

## Changes

- A submission intent freezes its request payload and idempotency key. A lost response, navigation failure or same-session route change does not allocate a new key. Concurrent clicks share the request; successful receipts are reused. Only an explicit new-task action after confirmation allocates another key.
- The same controller is used by the React and diagnostic workbenches. Credentials and intents stay in memory. Hard reload/logout recovery is NOT implemented: check the task list after those actions. Unknown outcomes cannot be discarded silently to obtain a new key. Old-session callbacks cannot restore cleared intents.
- Docker attempts record invocation, decoded execution, validation and cleanup separately. A cleanup failure cannot erase a previously observed completed result. Unknown is null, not false. The reported completed counter is a lower bound, not a count of every container start. The auto-removed container ID is not fabricated. This is not a persisted orphan ledger.
- Authenticated metadata now returns versioned historical acceptance scope. The UI shows the backend version and distinguishes historical CI from current-host authority; coding_agent_ready remains false.
- Eight real-browser cases are defined: login, committed-response loss with navigation/retry/local delivery, approval scope binding with simulated delivery/replay, rejection, developer privilege rejection, cancellation while awaiting review, stale approval payload and historical acceptance display.
- CI requires the existing npm lockfile and disables persisted checkout credentials.

## Local results at initial submission

The default backend suite completed with **191 passed, 0 failed, 0 errors, 0 skipped**. Node tests: **38 passed**. TypeScript syntax-only inspection: **11 files, 0 syntax errors**; this is not a production build. Initial diagnostics regression checks on the old source failed before the fix; their logs are retained separately. No coverage percentage was recalculated.

## Hosted acceptance for the actual code revision

Validated code commit: `c0a001409da2dc225cfaa1201aad94611acda1dc` (Git tree `a5a3e127a385f59c488592fe8403df8bb06944b5`).

- Quality workflow: https://github.com/volcano-code/TraceForge/actions/runs/36552032368 — backend, frontend and PostgreSQL all succeeded.
- Rootless workflow: https://github.com/volcano-code/TraceForge/actions/runs/36552032370 — succeeded with six reviewed-fixture executions.

| Gate | Observed result and limitation |
|---|---|
| Python | 191 passed; 0 failures/errors/skips, verified in downloaded hosted JUnit |
| Node | 38 protocol/intent tests; 23 existing + 15 new; local log and hosted step pass |
| React | Strict npm ci, TypeScript/Vite production build and Vitest passed |
| Chromium | 8 tests passed with 0 failures/errors/skips; real browser/API/worker, not a model task |
| PostgreSQL | Existing explicit integration gate passed; not a full concurrent-production certification |
| HTTP + worker | 13 checks passed; also repeated locally |
| Simulated delivery | 6 scenarios passed; also repeated locally; no real product PR |
| Docker | 6 launch invocations and 6 confirmed completed outputs, 0 unknown; all cleanup confirmed; 3 expected pre-fix failures and 3 post-fix passes |

The browser lost-response test commits a real POST via route.fetch, drops the browser response, navigates away and back, then retries the same key. It checks one matching run and one RUN_CREATED event. The separate database regression checks one Run and one Outbox row. Scope-change, rejection, stale approval, developer permissions, waiting-approval cancellation and local/simulated delivery are exercised without stubbing the backend.

Docker timeout/cancellation/cleanup-failure counter regressions use explicit fakes, not live fault injection. Actual Docker success gates remain limited to the six reviewed examples. No hostile-repository isolation certificate or persisted orphan reconciliation is claimed. Browser cancellation is at WAITING_APPROVAL, not while malicious code runs. The shared controller's native diagnostic wiring has syntax/protocol validation, not a newly added native browser suite.

Artifacts downloaded and SHA256 checked:

- Backend artifact `11025038278`: `0d8aa6844551420f3aee7cfa93c41e51b60a4bb72901cc56ee5807d96f995f05`.
- Frontend artifact `11024692594`: `03a80d7bd63405fb442c4bdee52c5fc99443b987367867bda89ea914c191e430` (8-case JUnit and two screenshots).
- Rootless artifact `11024329397`: `ea901a1d4f5f9d8bcd80f27c57738fa20fa7ae5c1958d772625161befdac8bf9` (attempt records, inspection and JUnit).

The local environment has no Docker and npm access failed; no local live-container or browser result is claimed. Those results come from the hosted runners. This document is a later documentation-only update; historical status on the UI is separately labeled and does not authorize the current host.

## Reproduce

```sh
python -m pip install -e '.[test]'
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
node --test tests-js/*.test.mjs
cd frontend
npm ci
npm run build
npm test
CI=true npm run test:e2e
```

The browser suite starts disposable local API/worker services and uses synthetic credentials. Docker/PostgreSQL are separate explicit live gates in `.github/workflows/`. No existing gate was disabled, silently skipped or replaced with a stub to claim live integration.

## Remaining product work

True Coding Runtime/model integration, a configured-repository validator independent of fixed answers, writable isolated coding workspaces and a product GitHub App are not part of this repair. Pending Docker orphan recovery and comprehensive hostile-code security tests also remain. A project-development PR is not a product-generated repair PR.
