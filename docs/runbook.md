# Runbook
Start python3 -m rfq_review.server --port 19083. This creates only its project SQLite database and binds127.0.0.1. Do not expose the port externally.
Use a demo role, inspect/confirm each source proposal, calculate a demand/date scenario, then use reviewer to record a comparison acknowledgement. A source/scenario/selection change requires a new packet review.
Model mode uses an existing local qwen3:4b; baseline mode needs no GPU. Failure stays manual-review with a deterministic observed fallback; HTTP200 is not model success.
Use a new --db path for a separate demonstration record instead of deleting an existing database. Native browser capture helper expects an already-running authorized Chrome CDP endpoint and creates/closes only its own tab. Browser checks are not part of CI and include explicit client-state mocks.
Timeout or shared marker: follow inference-policy.md. Do not automatically duplicate model calls, stop Ollama, or discard review requests after timeout; query stored packet/audit before a manual retry.
Install check: unittest, frozen evaluator, JS syntax. No external package installation is required.
