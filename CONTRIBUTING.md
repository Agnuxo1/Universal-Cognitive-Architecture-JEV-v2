# Contributing

Use Python 3.11 or later. Install with `python -m pip install -e .` and run
`python -m unittest discover -s tests -v`. The suite is offline: never require
live credentials in unit tests. Keep provider integration checks opt-in.

Submit a focused change with the concrete problem, observed behavior, and a
regression test. New providers must report missing usage as unknown, sanitize
errors, and respect the shared call budget. No provider may authorize an external
side effect. New deterministic operations require explicit dispatch and tests;
do not execute Markdown, graph content, or model-generated code.

Preserve versions/v1 and historical root artifacts. State performance claims
with baseline, workload, model, complete usage, hardware, and uncertainty.
