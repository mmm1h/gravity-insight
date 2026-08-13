# Error Classification Alignment

## Decision

The documented exit-code semantics are authoritative for Agent control flow:

- caller errors mean the request can be corrected locally and retried;
- permission failures mean the upstream account or authorization must change;
- local contract, privacy, and policy blocks mean the SDK rejected execution
  before an upstream request was allowed.

Therefore permission failures belong to `upstream` / exit 3, while local
privacy and policy blocks belong to `local` / exit 4. Reclassifying these
failures does not remove any read capability, alter an operation contract, or
change whether a request is sent. It only makes the existing fail-closed result
machine-decidable without encouraging an Agent to retry unchanged input.

## Scope

This unit will change only the shared error classification and domain-owned
error construction needed to preserve those semantics. It will not introduce
an error category or exit code, unify domain result models, change the shared
Plan/Agent/CLI spine, or edit `docs/agent-workflow.md`.

## Compatibility

This is an intentional breaking behavior change for callers that branch on
process exit status. Permission paths move from exit 2 to exit 3. Local policy
and privacy blocks currently represented as caller `UNSUPPORTED` move from
exit 2 to exit 4. Error codes, messages, envelopes, request validation, and
read capabilities remain available as before.

## Verification

Add focused contract coverage for category ownership, update only existing
assertions whose expected exit status changes, and run both complete test
collectors plus compiler, quality, CLI-help, and diff checks with the
worktree-local interpreter.
