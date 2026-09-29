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

Full React build, browser, PostgreSQL and rootless results for THIS revision remain pending until the hosted workflows complete. Do not substitute the previous version's successful runs. The local environment has no Docker and npm access failed; no local live-container or browser result is claimed.

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
