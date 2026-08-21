# R15 Isolated SQL Explorer

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `specified` |
| Track | Isolated exploratory product |
| Dependencies | R02, R05 |
| Parallel group | `isolated-product` |
| Shared-spine integration | Required and serialized |

## Outcome

An explicit caller-provided SQL statement can run in an isolated exploratory session only when a dialect-specific safety adapter proves read-only identity, AST policy, source/function allowlists, transaction mode and enforceable budgets. Results cannot acquire stable production identity without promotion.

## Current Baseline

The current SQL surface executes only workspace-registered products with reviewed SQL, fixed parameters, aggregation privacy and output projection. Arbitrary SQL and automatic Text-to-SQL are intentionally unavailable.

## Scope

- Select explicitly supported SQL dialects and mature parsers.
- Require a separate database-enforced read-only identity and read-only transaction.
- Parse exactly one statement; allow only approved relation/view/function forms.
- Enforce statement timeout and database-supported scan/resource limits plus row/byte output limits.
- Return an exploratory envelope and implement a deterministic review/promote path to Registered SQL Product.

## Non-goals

- No generated SQL, automatic API fallback, multi-statement execution, DDL/DML or hidden stored-procedure calls.
- No stable Journey, Skill, subscription, Dashboard or Action use before promotion.
- No client-side claim that an unenforceable scan estimate is a hard budget.

## Machine Contract

Session records dialect, parser/version, policy digest, identity class and enforced budgets. Output always has `trust=exploratory` and `completeness=unknown`. Unsupported dialect, unprovable read-only mode or absent server-side budget produces a stable blocked reason before execution.

## Migration And Compatibility

Registered SQL remains the only trusted repeatable SQL product. Explorer is a separate explicit command/service and never intercepts Insight or registered SQL failures. Promotion creates a reviewed versioned product and consumer contract.

## Safety And Operations

Use a proven parser library; do not hand-roll prefix/regex parsing. Relation and function allowlists are exact. Query text and values follow privacy/logging rules and are not stored in public Receipts. The Runtime Governor owns Explorer transport requests.

## Acceptance

- DDL/DML, multiple statements, comments/tricks, disallowed relations/functions and budget gaps fail closed.
- Database identity cannot mutate even if parser policy fails.
- Timeout/scan/row/byte limits are tested against the selected dialect adapter.
- Explorer output cannot satisfy stable dependencies.
- Promotion yields a normal Registered SQL Product with reviewed projection/privacy.

## Verification

Dialect parser attack corpus, integration tests against a safe test database, read-only role proof, timeout/budget cases, privacy/logging snapshots, promote lifecycle, no-fallback tests and full gates.

## Rollback And Exit

Disable the Explorer command/service without changing registered SQL. Exploratory sessions are not migrated into trusted products automatically.

## Canonical Owners

Explorer session/dialect/policy schemas, SQL service/CLI reference, promotion workflow and security documentation.
