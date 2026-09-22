# Runtime contract

## Boundaries

The CLI parses JSON. Graph validates directed adjacency and emits bounded inert
context. Engine validates tasks before side effects, chooses deterministic dispatch
or explicit model collaboration, and verifies the exact output. Providers translate
between the runtime and external CLI JSON. Store performs atomic JSON persistence.

The public Python interfaces are Engine(Store(path), provider, router, models,
Limits()).run(task), Graph.from_dict(data).context(), and Graph.trace(route).
Provider.run(task, context, model) returns ProviderResult. Router.decide(state)
returns action/confidence/provider_model/usage. A host can supply custom adapters.

## State transitions

validated -> deterministic/cache -> checked -> accepted | needs_review

validated -> configured model -> optional JEV route -> reserved worker call ->
optional independent peer and synthesis -> checked -> optional next configured
model -> accepted | needs_review | blocked | budget_exhausted

The router consumes a call before invocation. All panel calls share that ledger.
No model response can alter configuration, the budget, or the acceptance checks.
Provider failures become generic events; sensitive stderr is not recorded.

## Cache and provenance

Only deterministic operations are cached. Input identity includes version, task,
checks, model list and limits. The artifact digest and TTL are checked on every
read; the acceptance gate is rerun. Version changes invalidate results. Developers
changing deterministic semantics must bump the version; Python/platform identity
is not needed for the three platform-independent operations currently provided.

Checkpoints store task and output digests, event names, attempted calls, known
tokens, unknown-usage calls and a next-action hint. They are factual audit records,
not hidden reasoning transcripts or a transaction log for automatic resumption.

## Deliberate limitations

No automatic arbitrary tools, autonomous file edits, or external publication.
No global price catalog; no fabricated precision for unknown usage. Graph retrieval
is breadth-first, not embedding search. Calls in a panel are sequential and use
the same initial model. Token/time bounds are observable thresholds with per-call
timeouts, not exact preemptive billing caps. Domain-specific claim verification is
responsibility of the host's stronger checks and evidence collection.
