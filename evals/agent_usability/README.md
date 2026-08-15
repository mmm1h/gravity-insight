# Agent usability suite

This directory contains the question set for the repeatable Agent-usability
measurement. It is deliberately separate from product tests: these prompts are
analysis-journey examples, not examples copied from recognizer tables, selectors,
or routing tests.

## Version and construction

`gravity-agent-usability-2026-08-15.v2` covers all 48 counted rows in
`docs/analysis-journeys.md`: 33 executable journeys and 15 explicitly missing
journeys. Every journey contributes ten prompts:

- three ordinary Chinese phrasings;
- three ordinary English phrasings;
- one Chinese and one English adjacent-product boundary phrasing;
- one Chinese and one English missing-input/capability-gap phrasing.

The count is therefore `48 journeys × (3 zh normal + 3 en normal + 2 boundary
+ 2 missing) = 480 cases`. Development and holdout each contain five cases per
journey, so `48 × 5 = 240` in each split. The split is by expression family,
not by randomly shuffling duplicate sentences.

The author read only the journey ledger and caller-facing workflow before the
question-set commit. The source revision and content hashes are recorded in
`suite.json`. The question set was committed before inspecting or changing the
routing implementation.

## Holdout boundary

`cases/development.jsonl` is intentionally visible and may be used for local
iteration. `cases/holdout.sealed.json` contains an authenticated encrypted
payload. Its 32-byte key has exactly one fixed location in an evaluation
checkout: `.local/agent-usability/holdout.key`. In this worktree that is
`D:\git-pjt\wt-holdout-custody\.local\agent-usability\holdout.key`. The path is
explicitly ignored by Git. Normal holdout output contains only aggregate layer
scores; it omits prompts, per-case outcomes, card text, and tracebacks.

The **custodian** is the release-evaluation owner or process that creates this
file and runs the formal whole-suite evaluation. It is an operating role, not a
recovery service: the implementation line does not receive prompt-level output,
and only the custodian should initiate formal holdout runs. Generate the key
once from the repository root with this exact command; exclusive creation makes
an accidental overwrite fail:

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path; python -c "from pathlib import Path; import os; p=Path(r'.local/agent-usability/holdout.key'); p.parent.mkdir(parents=True, exist_ok=True); f=p.open('xb'); f.write(os.urandom(32)); f.close(); print(p.resolve())"
```

Use the fixed path directly; there is no `<custodian-key>` placeholder:

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python scripts\agent_usability_eval.py run --split holdout --holdout-key .local\agent-usability\holdout.key --output-dir tmp\agent-usability
```

There is no password derivation, escrow, backup, or recovery path. If the key is
lost, the sealed payload is permanently unreadable. Mark that payload and suite
hash obsolete, author a new holdout from the then-current counted journey
ledger, generate a new key at the same fixed path, seal a new suite version, and
establish a new baseline. A plaintext hash can confirm reconstructed bytes but
cannot recover them; do not imply otherwise.

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

The practical protection target is narrower: prevent the normal implementation
line from feedback-fitting through “run the score, inspect failed sentences,
add keywords.” It does not defend against deliberate bypass.

## Files

- `suite.json`: version, counts, split rule, source revision, and hashes.
- `cases/development.jsonl`: visible development cases.
- `cases/holdout.sealed.json`: authenticated sealed holdout cases.

Do not add prompt-level holdout diagnostics, a single-case selector, or a
command that accepts arbitrary holdout prompts. Those would recreate the oracle
this split is intended to remove.
