# Validation â€” 2026-09-22

## Observed integrations

- Canonical local JEV connector: authenticated through its existing secure store.
- Initial release advice: second_opinion; event-driven consultation; evidence gate.
  Provider reported jev-1.13.0, 617 input and 127 output tokens.
- New JEV adapter: single action, confidence 1.0, 422 input and 50 output tokens.
- End-to-end auto routing + configured Codex worker: accepted READY, 2 calls,
  19,208 reported input+output tokens across that run, 9.944349 seconds.
  Configured worker ID: gpt-5.6-luna. Provider-selected backend identity is not
  independently exposed by the CLI. Complete usage refers only to this run,
  not this entire development conversation, images, or independent reviewers.
- Offline text example: 24 characters / 26 UTF-8 bytes / 4 words; 0 model calls.
- Repeat: cache_hit true with acceptance checks rerun.

The live test proves connectivity and basic orchestration only. It is not a
reasoning benchmark or a token-savings comparison. In particular, a tiny prompt
can still incur substantial CLI context overhead; no savings percentage is claimed.

## Automated tests

52 tests passed locally on Python 3.13; clean wheel installation and out-of-tree CLI execution also passed.

Run `python -m unittest discover -s tests -v`. Tests cover cycles and dangling
edges; strict context limits; cache identity/TTL/corruption/NaN; atomic writes;
path traversal rejection; final synthesis gating; independent peer context;
shared budgets; unknown usage; safe provider failures; and UTF-8 structured output.
The CI workflow runs on Ubuntu and Windows with Python 3.11 and 3.13.
See release notes and GitHub Actions for final executed counts and statuses.

## Scope of checks

The runtime verifies declared text or JSON criteria. Scientific validity and
application performance require stronger external experiments. The HUEVOS panel
example has formatting checks only; it cannot establish printing-time savings.

## Preserved history and publication hygiene

The original v1 README hash and source commit are in history-preservation.json.
The original Git history is retained; root HTML/PDF research artifacts are unchanged.
Nine historical blobs and release text files were screened for recognizable key
formats without printing potential values; none were found. This check is not a
proof of absence of every kind of private data. No local JEV source tree, credential
store, existing telemetry, private opportunities or personal runtime cache was copied.
The new repository retains the source repository's private visibility.
