# Hosted acceptance scope

The repair was uploaded to `volcano-code/TraceForge`, branch `fix/m2-hardening-20260929`. Main is not changed or merged. Source was transferred with compressed-payload and decoded-source SHA256 checks and then committed as normal individual files. Temporary write-enabled import workflows have been removed from the current tree.

## Evidence, not inferred status

First hosted quality run: https://github.com/volcano-code/TraceForge/actions/runs/36463157386 (commit 797e452b85a4aab0f812a6a19074cd5139ea1c82).

* React TypeScript/Vite build passed.
* Vitest passed with Playwright files excluded.
* Real Chromium workbench E2E passed: **one** test, authenticated login and fixture-project listing. This does not cover the complete browser approval/delivery flow.
* PostgreSQL integration passed: a disposable schema, migrations and schema check, concurrent same-key creation, single claimant, fixture validation and local idempotent delivery. Not a full PostgreSQL stress or disaster-recovery certification.
* Backend initially failed 1/166 cases due to the process-exit test reading `/proc` after the child disappeared. The test has been corrected and two disappearance regressions added. A fresh full run is mandatory.

The committed lockfile was resolved on a hosted runner using `--package-lock-only --ignore-scripts`; subsequent CI uses `npm ci`. Installing and building is separate from security approval of every transitive dependency.

## Current gates

Read actual Actions results for the latest commit; workflow YAML alone proves nothing. The backend suite contains 168 tests after the procfs repair; Node protocol/stream tests contain 23 cases. Local HTTP smoke contains 13 checks; simulated-delivery fault suite contains 6 scenarios.

The strict rootless Docker workflow is a separate gate. It never disables host security policy or falls back to host execution. Its six-fixture smoke, even if passing, is not a malicious-code escape test or general isolation guarantee. An external smoke result does not automatically become an authenticated readiness attestation.

No SDK/model loop, real product GitHub App authorization, real product PR or automatic merge has been performed. A repair PR created by ChatGPT is a repository publication action, not proof of TraceForge's PR-delivery feature.

Historical local report `reports/repair/summary.json` records the pre-hosted 166-test snapshot; it is not the final CI score. Final logs/artifacts are linked from the PR and Actions.
