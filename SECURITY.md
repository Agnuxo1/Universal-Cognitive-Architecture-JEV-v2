# Security

Do not include credentials, private task inputs, caches, checkpoints, or provider
transcripts in issues or commits. Report a suspected vulnerability privately via
the repository owner's GitHub profile; do not post exploitable details publicly.

This runtime has no arbitrary command task type. Knowledge graphs are inert JSON.
Codex workers run in a temporary directory using read-only sandbox and ephemeral
sessions. Codex still uses the user's installed configuration and integrations:
review those integrations before sensitive use. A read-only filesystem sandbox is
not a guarantee that every installed external integration lacks side effects.

JEV uses an explicitly configured, trusted local connector. Its credentials remain
in the existing connector's vault or environment. Never place keys in task/config
JSON. There is no automatic OpenAI API fallback. Provider subprocess errors are
reduced to generic statuses. Checkpoints contain IDs, digests and event metadata;
result caches and command output may contain task data and must remain local.

Hash validation detects accidental corruption; it is not authentication against
an attacker who controls the storage directory. Cache and checkpoint writes are
atomic, but this release does not provide multi-user locking or encrypted storage.
Only deterministic accepted outputs are cached. A failed or ambiguous model result
is never silently accepted. The final checks verify exactly their declared scope;
a nonempty check alone proves no factual correctness.
