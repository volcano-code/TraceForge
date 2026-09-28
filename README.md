# TraceForge

**Verified Action Infrastructure for Software Engineering Agents**

TraceForge is being developed as a full-stack software-engineering Agent control plane focused on evidence-driven verification, approval-bound side effects, durable execution, reconciliation, and auditable delivery.

## Current import status

Repository initialized for the TraceForge v0.3.0-M2-start source import.

> Source-of-truth code is imported only after its files can be read and verified. No generated placeholder implementation should be treated as the M2-start source.

## Core invariant

```text
Observe → Propose → Evidence → Verify → Approve → Execute → Reconcile
```

The Agent execution plane must not be able to bypass the trusted validator, approval boundary, or delivery service.
