# Agent usability suite

This directory contains the question set for the repeatable Agent-usability
measurement. It is deliberately separate from product tests: these prompts are
analysis-journey examples, not examples copied from recognizer tables, selectors,
or routing tests.

## Version and construction

`gravity-agent-usability-2026-08-15.v1` covers all 47 rows in
`docs/analysis-journeys.md`: 33 executable journeys and 14 explicitly missing
journeys. Every journey contributes ten prompts:

- three ordinary Chinese phrasings;
- three ordinary English phrasings;
- one Chinese and one English adjacent-product boundary phrasing;
- one Chinese and one English missing-input/capability-gap phrasing.

The count is therefore `47 journeys × (3 zh normal + 3 en normal + 2 boundary
+ 2 missing) = 470 cases`. Development and holdout each contain five cases per
journey, so `47 × 5 = 235` in each split. The split is by expression family,
not by randomly shuffling duplicate sentences.

The author read only the journey ledger and caller-facing workflow before the
question-set commit. The source revision and content hashes are recorded in
`suite.json`. The question set was committed before inspecting or changing the
routing implementation.

## Holdout boundary

`cases/development.jsonl` is intentionally visible and may be used for local
iteration. `cases/holdout.sealed.json` contains an authenticated encrypted
payload. Its 32-byte key is not stored in Git and must be supplied explicitly to
an authorized evaluation process. Normal holdout output contains only aggregate
layer scores; it omits prompts, per-case outcomes, card text, and tracebacks.

This blocks the ordinary feedback loop in which an implementation line runs the
suite, copies failed holdout sentences, and adds their exact tokens to a
recognizer. It is not a security boundary against an operator who controls the
evaluation host or key: that operator can modify the evaluator, attach a
debugger, or read process memory. Repeated aggregate submissions can also leak
information adaptively. A real release process must therefore keep key custody
separate from implementation, publish only whole-suite aggregates, and limit
formal holdout runs.

The sealed format uses only Python standard-library primitives: a fresh nonce,
an HMAC-SHA-256 counter-mode keystream, and a separate HMAC-SHA-256 integrity
tag. It exists to keep plaintext out of the repository and routine logs, not to
claim isolation from a local administrator.

## Files

- `suite.json`: version, counts, split rule, source revision, and hashes.
- `cases/development.jsonl`: visible development cases.
- `cases/holdout.sealed.json`: authenticated sealed holdout cases.

Do not add prompt-level holdout diagnostics, a single-case selector, or a
command that accepts arbitrary holdout prompts. Those would recreate the oracle
this split is intended to remove.
