## Universal Cognitive Architecture · JEV Edition 2.0.0

This release adds a working Python runtime to the original research architecture:
validated graph context, deterministic result caching, explicit acceptance checks,
shared call budgets, optional JEV routing and bounded Codex collaboration.

- 52 offline regression tests pass locally on Python 3.13.
- Clean wheel installation and CLI execution verified outside the source tree.
- Live JEV + Codex route completed successfully (configured gpt-5.6-luna).
- No automatic paid API fallback; missing usage remains unknown.
- Four generated README illustrations, architecture guide and Spanish guide.
- Complete source ancestry, original documents and verbatim v1 README preserved.

Install the attached wheel with `python -m pip install cognitive_architecture_jev-2.0.0-py3-none-any.whl`,
or clone the repository and run `python -m pip install -e .`.
Try `python -m cognitive_architecture run examples/offline-task.json` from the source tree.

Limits: checks validate only their declared scope; time/token bounds are observed
between calls rather than exact preemptive caps; automatic panel resumption is
not implemented. Images are explanatory and not benchmark evidence. No token
savings or improved reasoning accuracy is claimed without a matched benchmark.
