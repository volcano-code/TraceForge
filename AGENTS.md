# TraceForge repository instructions

This repository is a local-only engineering foundation, not a production agent.
Do not replace trusted verification or authorization with model judgments.
Never turn real PR delivery on before a GitHub App, repository authorization and approval binding are tested.
Do not execute arbitrary repositories on the host. The fixture runner only accepts reviewed bytes.
Do not rename deterministic fixture output as an LLM result.
Read docs/SECURITY.md and docs/ACCEPTANCE.md before modifying runtime boundaries.
Never commit .env or .traceforge. Test source tokens are synthetic test-only values.
