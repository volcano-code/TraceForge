# TraceForge

**Evidence-driven, approval-bound control plane for software-engineering agents.**

This repository contains repaired **0.3.1-dev.0** source based on the archived `v0.3.0-M2-start` delivery. It is not an autonomous Coding Agent yet. The repair branch is `fix/m2-hardening-20260929`; `main` is unchanged until review.

## What works

The local workflow uses three reviewed synthetic bugs: reproduce an actual failing test, apply a known fixture patch, independently re-check the result, audit a hash-bound evidence bundle, require reviewer approval, and deliver an idempotent local or simulated receipt. Worker state, events, approvals and delivery operations are persisted. Unknown external results are reconciled without blind retries.

The fixtures are deterministic. Passing their tests is **not** an LLM benchmark or a guarantee for hostile repositories. Uploading source through the ChatGPT GitHub connector does not enable the product's GitHub App integration, which remains disabled.

## This repair

* Reject rootless Docker without reported cgroup v2/systemd CPU, memory, swap and PID controls.
* Never interpret Docker capability inspection as a live isolation test.
* Check execution authority before process creation; stop on check failure.
* Consistently lock Run then Outbox, refresh locked state and reject expired leases.
* Reconnect React SSE streams from the last acknowledged cursor, validate run scope and sequence continuity, and stop on authentication failure.
* Separate Vitest from Playwright test discovery; missing explicitly required E2E prerequisites fail instead of skip.
* Generate the Compose database password for new local environments without overwriting existing secrets.
* Correct a real hosted-runner test race: a child reaped between `/proc` inspection and reading is successful cleanup. Add regressions without weakening the child-termination assertion.

## Validation and limitations

GitHub Actions runs backend tests, Node protocol tests, real HTTP plus a separate Worker, simulated delivery faults, React production build and Vitest, a real Chromium workbench smoke test, and an isolated-schema PostgreSQL integration test. An **independent strict rootless Docker gate** records its actual outcome, not an inferred pass.

See [Actions](https://github.com/volcano-code/TraceForge/actions), [repair details](docs/RELEASE_REPAIR.md) and [acceptance scope](docs/HOSTED_ACCEPTANCE.md). A green engineering suite is not the completion of M2 or the four-week MVP. No live LLM call, OpenHands integration, real product PR, hostile-repository isolation certification, or automatic merge is claimed.

## Quickstart (Linux / WSL2)

```bash
git clone --branch fix/m2-hardening-20260929 https://github.com/volcano-code/TraceForge.git
cd TraceForge
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python scripts/bootstrap.py
python -m traceforge.cli init
python scripts/dev.py
```

Open `http://127.0.0.1:8000/workbench` for the native diagnostic UI. Use the reviewer token generated in your **local** `.env`; never commit or publish it.

For the React workbench, keep API/Worker running and open a second terminal:

```bash
cd frontend
npm ci
npm run build
npm test
npm run dev
```

Open `http://127.0.0.1:5173`. The committed npm lockfile is used by CI.

```bash
python -m pytest -q
node --test tests-js/*.test.mjs
python scripts/http_smoke_m1.py
python scripts/reliability_demo.py --output reports/local/reliability
```

## Explicit integration gates

```bash
python -m traceforge.cli doctor
python -m traceforge.cli sandbox-smoke
python -m pytest tests_live/test_docker_gate.py -q
# Requires TF_TEST_POSTGRES_URL pointing to a disposable test database:
python -m pytest tests_live/test_postgres_gate.py -q
```

Missing prerequisites are blocked/failed gates, not passing tests. `doctor` continues to report `coding_agent_ready=false` until the missing integrations and attestations exist. Docker failures never fall back to host execution. Do not expose this local-only system publicly or execute arbitrary repositories.

## Trust boundaries

Execution must not hold production credentials, grant its own approval, alter trusted verification, merge code or deploy production. See [security](docs/SECURITY.md), [execution](docs/M2_EXECUTION.md) and [architecture](docs/ARCHITECTURE.md).

Next work: real runtime/model integration, live isolation and recovery evidence, product GitHub App identity and scoped PR delivery, then broader browser and concurrency coverage. Planned frameworks are not implemented capabilities.
