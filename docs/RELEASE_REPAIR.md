# M2-start repair and GitHub publication

## Scope

This is a repaired engineering slice, not full M2 or the four-week MVP. The imported baseline archive SHA256 is `8cf8f299b6619cbee331a29afc584db89b938c3fb590f747ea332bf757c7a9f5`. Previous archives are unchanged.

## Fixed defects

1. Docker rootless preflight ignored unavailable cgroup controls. It now fails before image execution unless the daemon reports cgroup v2, systemd and all required resource capabilities. This is still capability inspection, **not live proof**.
2. Readiness removed the live gate blocker after capability inspection. It now keeps it: no persisted live attestation has been implemented.
3. Revoked execution could spawn a process before the first authorization callback. It now returns before Popen.
4. Worker claim/cancel used inconsistent lock order; preliminary ORM reads could be stale after waiting. Mutations now acquire Run then Outbox, refresh locked objects, and reject expired leases before renewal or result publication. PostgreSQL must separately pass the live gate.
5. React SSE disconnected without retry. It now reconnects with an acknowledged cursor, validates run scope and sequence continuity, and stops on logout or auth errors.
6. Vitest discovered Playwright specs. A separate config restricts unit-test discovery. E2E missing credentials fail instead of skip.
7. Compose required a PostgreSQL password not created by bootstrap. New environments now get one without overwriting existing .env files.

## Local execution evidence

Original baseline: 152 Python tests passed. Ten Docker/readiness regression probes failed on the old source; after fixes the final suite has **166 passed, 0 failed, 0 errors, 0 skipped**. Fourteen new Python cases are included. Node protocol/stream tests: **23 passed**. HTTP plus separate worker: **13 checks**. Independent simulator reliability suite: **6 scenarios**.

These results concern actual reviewed fixtures and local processes. Docker constructor tests use explicit fakes; no live container result is claimed. They are not model fix rates, proof of general safety, or a GitHub exactly-once guarantee. Raw logs are in `reports/repair/` in the downloadable archive. Remote CI results must be read from the actual run and cannot be inferred from workflow YAML.

## Outstanding gates

* Local npm/PyPI DNS remains unavailable. GitHub-hosted validation is requested separately.
* Live Docker and stronger orphan recovery are not certified. No arbitrary-repository execution.
* React build/browser and PostgreSQL are live gates with explicit failures for missing prerequisites.
* OpenHands/DSH/LangGraph/MCP integrations and real model actions have not been implemented.
* Product GitHub App authorization/real PR delivery is still disabled. Publishing this project with the ChatGPT connector does not enable those product capabilities.

## References consulted for this repair

* Docker rootless cgroup limitations: https://docs.docker.com/engine/security/rootless/tips/
* Vitest v3 test include/exclude configuration: https://v3.vitest.dev/config/
* SQLAlchemy locked-object refreshing: https://docs.sqlalchemy.org/en/20/orm/session_api.html

Do not replace a failing gate with skip/pass to make CI green.
