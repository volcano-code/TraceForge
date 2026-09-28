# TraceForge

**Evidence-driven, approval-bound control plane for software-engineering agents.**

This repository contains the imported and repaired **0.3.1-dev.0** source, based on the archived `v0.3.0-M2-start` delivery. It is not an autonomous Coding Agent yet.

## What works

The local workflow uses three reviewed synthetic bugs: reproduce an actual failing test, apply a known fixture patch, independently re-check the result, audit a hash-bound evidence bundle, require reviewer approval, and deliver an idempotent local or simulated receipt. Worker state, events, approvals and delivery operations are persisted. Unknown external results are reconciled without blind retries.

The fixtures are deterministic. Passing their tests is **not** an LLM benchmark or a guarantee for hostile repositories. Uploading this source to GitHub is separate from the product's GitHub App integration, which remains disabled.

## This repair

* Refuse rootless Docker configurations that do not report enforceable cgroup v2/systemd CPU, memory, swap and PID controls.
* Do not mistake a Docker preflight for a live isolation test.
* Check execution authority before spawning a process; stop on check failure.
* Use consistent Run -> Outbox locking, refreshed ORM state and strict lease expiry.
* Reconnect React SSE streams from the last acknowledged cursor, reject cross-run events and stop on authentication failure.
* Separate Vitest from Playwright discovery; make explicitly requested E2E tests fail rather than silently skip missing prerequisites.
* Generate the password required by Compose when bootstrapping a new local environment.

Details and test limitations: [repair report](docs/RELEASE_REPAIR.md).

## Local quickstart (Linux / WSL2)

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python scripts/bootstrap.py
python -m traceforge.cli init
python scripts/dev.py
```

Open `http://127.0.0.1:8000/workbench`. Use the reviewer token generated in your **local** `.env`. Never commit it. The working native page is a diagnostic UI; the separate React workbench requires its own build and browser validation.

```bash
python -m pytest -q
node --test tests-js/*.test.mjs
python scripts/http_smoke_m1.py
python scripts/reliability_demo.py --output reports/local/reliability
cd frontend
npm install     # use npm ci once an audited lockfile has been committed
npm run build
npm test
```

## Explicit integration gates

```bash
python -m traceforge.cli doctor
python -m traceforge.cli sandbox-smoke
python -m pytest tests_live/test_docker_gate.py -q
# A disposable test PostgreSQL database URL is required:
python -m pytest tests_live/test_postgres_gate.py -q
```

Missing Docker, database credentials or browser dependencies are **blocked gates**, not passing tests. There is no fallback from failed Docker isolation to host execution. Do not open this local-only system to the public Internet or run arbitrary repositories.

## Source and safety

The agent execution plane must never hold production credentials, grant its own approval, alter trusted verification, merge code, or deploy production. See [security](docs/SECURITY.md), [execution boundary](docs/M2_EXECUTION.md), and [architecture](docs/ARCHITECTURE.md).

The SDK adapters, real model loop, production identity, GitHub App and real PR pipeline remain future integration work. Planned technologies are not presented as implemented capabilities.
