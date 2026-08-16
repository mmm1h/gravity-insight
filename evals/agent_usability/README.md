# Agent usability suite

This directory contains the question set for the repeatable Agent-usability
measurement. It is deliberately separate from product tests: these prompts are
analysis-journey examples, not examples copied from recognizer tables, selectors,
or routing tests.

## Version and construction

`gravity-agent-usability-2026-08-16.v3` preserves the original 240 public
development cases byte-for-byte and appends two new cases for each J01–J48
journey. The 96-case development-only expansion uses eight primary families:
indirect business goal 13, colloquial ellipsis 12, typo/pinyin 12,
Chinese-English code switching 12, first-turn follow-up 12, negated/reverse 12,
multiple intents 12, and target gap 11. The 11 target-gap cases cover every
currently `完全缺失` registered journey once. Development is therefore
`240 + 48 × 2 = 336`; the unchanged holdout remains 240, `all` is now 576,
and the unchanged independent final adds 48 for a physical total of 624.

`gravity-agent-usability-2026-08-15.v2` covers all 48 counted rows in
`docs/analysis-journeys.md`: 33 executable journeys and 15 explicitly missing
journeys. Every journey contributes ten prompts:

- three ordinary Chinese phrasings;
- three ordinary English phrasings;
- one Chinese and one English adjacent-product boundary phrasing;
- one Chinese and one English missing-input/capability-gap phrasing.

The v2 core count is therefore `48 journeys × (3 zh normal + 3 en normal + 2
boundary + 2 missing) = 480 cases`. Its development and holdout each contain
five cases per journey, so `48 × 5 = 240` in each split. The split was by
expression family, not by randomly shuffling duplicate sentences.

The independent `final` suite is additive: one newly authored case for each of
the same 48 journeys. It is not part of `all`, whose meaning remains
development+holdout. In v3 all three physical splits contain `336 + 240 + 48 =
624` cases. Final rotates five strategies across
journey families: colloquial ellipsis 10, typo/misspelling 10, Chinese-English
code-switching 10, indirect goal descriptions 9, and the first turn of a
multi-turn follow-up 9. These are not variants of the old ordinary/boundary/gap
sentence families.

The original v2/final authorship boundaries remain recorded below. The v3
expansion's separate source and negative-deduplication boundary is recorded in
`SOURCES.md`. Source revisions and content hashes are recorded in `suite.json`.

## Ledger-derived response shape

Prompts and `journey_id` values remain frozen in every split. The original v2
cases retain their historical `expected` object as a target-identity guard.
The v3 development additions deliberately omit `expected`: their only target
identity is `journey_id`, so no card-versus-gap fact is copied into the case.
At load time the evaluator reads
the status directly from `docs/analysis-journeys.md` and combines it with the
public `journey-targets.json` mapping:

- `已闭环` requires the journey's exact product card;
- `完全缺失` requires the journey's exact actionable gap;
- `部分闭环` also requires the whole journey's exact gap.

Partial journeys fail closed because these cases identify a whole journey, not
an independently frozen subpath. Accepting one supported subpath's card for a
broad journey would silently certify its unsupported siblings. A future suite
may score subpaths separately only if those identities are frozen when that
suite is authored.

The target registry deliberately contains no status field. Its exact ledger
titles make the Markdown table machine-readable; missing or duplicate rows,
unregistered case identities, and a status without its frozen target shape all
fail before scoring. Evaluation receipts fingerprint the parser, target
registry, and ledger and record their hashes and status counts.

This applies after any development, holdout, or final payload is loaded. The
protected payloads are not rebuilt: their sealed `journey_id` remains the target
identity, while only response shape is derived outside the ciphertext. No
protected key or decryption is needed to update the derivation mechanism.
If an authorized custodian run ever finds a legacy payload without a registered
`journey_id`, loading fails before scoring. The remedy is a new independently
authored sealed suite version with the old payload retained read-only, not
decrypting or reconstructing that payload on an implementation branch.

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

Use the fixed path directly; the command has no abstract key placeholder:

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python scripts\agent_usability_eval.py run --split holdout --holdout-key .local\agent-usability\holdout.key --purpose "pre-registered comparison" --output-dir tmp\agent-usability
```

Formal holdout runs also require `--purpose <why-this-query-is-needed>`. Every
successful run appends its aggregate receipt to the versioned query ledger and
prints the cumulative holdout and protected-split query counts.

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

## Final boundary

`final` is a frozen closeout split. Its only intended use is **one query during
the entire project cycle, at project closeout**. It has an independent sealed
payload and independent fixed key path:
`.local/agent-usability/final.key`. The final key is not a holdout key alias and
must be generated independently; both paths are ignored and must remain
untracked.

The evaluator refuses a second final query before reading the key or sealed
payload. A custodian may explicitly use `--allow-final-rerun` when a real
exception outweighs the leakage cost. That override does not hide the event:
the new query and the override flag are appended to the ledger. `verify-suite`
checks the sealed final file hash without accepting a final key or decrypting
the payload.

The checked-out final key and payload were created as one pair. Do not generate
a replacement key for the existing ciphertext. If the key is lost, the final
payload is unrecoverable: mark its version/hash obsolete, author a new unseen
final from the then-current public journey ledger, seal it with a new key, and
record the custody reset. The plaintext hash is verification data, not escrow.

```powershell
$env:PYTHONPATH=(Resolve-Path '.\src').Path
python scripts\agent_usability_eval.py run --split final --final-key .local\agent-usability\final.key --purpose "project closeout arm comparison" --output-dir tmp\agent-usability
```

Final authorship used only the counted goals and blockers in
`docs/analysis-journeys.md`, caller-facing contracts in
`docs/agent-workflow.md`, and the evaluator's route/gap identities. The author
did not open development cases, the sealed holdout, or either holdout plaintext
or key. A separate pre-change development run emitted aggregates only; its
questions and per-case results were not inspected or used for final wording.
Exact prompts were composed and sealed in memory without a plaintext question
file. The one-time ignored generator contained only public-source strategy
rules/word pools and was deleted immediately after sealing.

## Protected-query ledger

`query-ledger.jsonl` is append-only through the evaluator: one canonical JSON
record is written and `fsync`ed after each successful holdout/final evaluation.
Each record contains UTC run time, split, split/protected ordinals, suite
version, Git HEAD, product-source fingerprint, case/trial counts, required
purpose, evaluator-source fingerprint, worktree-dirty flag, the four original
aggregate scores, the binary security receipt, and whether a final rerun
override was used. Records form a SHA-256 append chain;
a malformed, edited, or reordered prior query record fails closed before a
protected run. Version control remains the durable history and review surface.

The ledger deliberately does not impose a holdout hard budget. Its job is to
make every aggregate feedback event visible and attributable. Final alone has
the default one-query refusal because its project-closeout meaning would
otherwise be silently destroyed.

## Fifth layer: security compliance

Security compliance is an independent binary hard gate. It never reports a
percentage: one violation makes the layer fail even when all four usability
scores are green. The evaluator audits first-trial discovery artifacts and
offline controls for:

- an upstream mutation handoff, determined only by an operation's registered
  `effect=mutation` classification or a blocked-write reservation (never from
  command-name words or HTTP method alone);
- credential assignments in `message`, `next_action`, `warning`, or `warnings`;
- arbitrary URL/host/method material in a Plan request;
- natural-language auto-execution;
- unknown operation/URL rejection before transport.

Local disk effects are information, not violations: the result records each
handoff involving a local metadata-catalog sync or `--output` file destination.
Those effects are necessary for offline discovery and export delivery and do
not mutate the Gravity workspace. This boundary must remain narrow: a semantic
upstream mutation can damage a user's workspace, whereas local writes only
require the analyst's informed choice of local path.

The layer reuses returned cards/Plan nodes, the operation registry and policy
authorization seam, and blocked-write reservations. It
does not claim visibility into an external LLM's shell/tools or text outside
the returned card/error/warning structures. Production responses are not
available in this network-free harness, so product-specific downstream
projection paths still need their normal contract and quality tests.

## Files

- `suite.json`: version, counts, split rule, source revision, and hashes.
- `cases/development.jsonl`: visible development cases.
- `cases/holdout.sealed.json`: authenticated sealed holdout cases.
- `cases/final.sealed.json`: independently authenticated sealed closeout cases.
- `query-ledger.jsonl`: versioned aggregate-only protected-query receipts.

Do not add prompt-level holdout diagnostics, a single-case selector, or a
command that accepts arbitrary holdout prompts. Those would recreate the oracle
this split is intended to remove.
