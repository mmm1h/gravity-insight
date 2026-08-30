# R15 Isolated SQL Explorer

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `fixed_dev` |
| Track | Isolated exploratory product |
| Dependencies | R02, R05 |
| Parallel group | `isolated-product` |
| Shared-spine integration | Required and serialized |
| Delivery ledger | This Requirement document; no internal GitHub Issue |
| Baseline | `dev@f29f493c73179efc55692f500a935002b04d915c` |
| Branch / worktree | `codex/r15-isolated-sql-explorer` / `D:\git-pjt\gravity-sdk-wt\r15-isolated-sql-explorer` |
| Feature / merge | `5dbf33bad14a8ce13250d28d337e2e71cb9d8dff` / `dev@a0033700ca9e78b964fd3cf2855f391310bb1f1e` |
| First dialect / parser | SQLite / `sqlglot==30.17.0` |
| Production requests | `0`; temporary local SQLite only |

## Outcome

An explicit caller-provided SQL statement can run in an isolated exploratory session only when a dialect-specific safety adapter proves read-only identity, AST policy, source/function allowlists, transaction mode and enforceable budgets. Results cannot acquire stable production identity without promotion.

## Current Baseline

The current SQL surface executes only workspace-registered products with reviewed SQL, fixed parameters, aggregation privacy and output projection. Arbitrary SQL and automatic Text-to-SQL are intentionally unavailable.

## Plan Owner Verdict And Ready Binding

R02 and R05 are `fixed_dev`. Under the user's continuous implementation
authorization, the plan owner reviewed
`tmp/r15-isolated-sql-explorer-proposal.md` and its architecture conflict ledger,
bound the dialect/parser/identity/budgets/write scope/gates, and advanced R15
through `reviewed` and `ready` to `in_progress`. This does not authorize a
production database, Gravity SQL, credentials, network calls, release or `main`.

- Support exactly SQLite with `sqlglot==30.17.0`; parse one explicit SQLite
  `Select` AST, reject comments and all non-query/set-operation forms, and use
  exact relation/function/output allowlists. No prefix or regex authorizer exists.
- Require an absolute regular database file opened only through generated URI
  `mode=ro`, verified `query_only`, disabled trusted schema/mmap, one read
  transaction and a connection authorizer retained through execution.
- Require engine `setlimit` and progress-handler enforcement. Bound SQL/value/
  column/expression/compound/attach/variable/VDBE/worker resources, statement
  time or VM steps, outer rows, cell bytes and total JSON bytes. Never label a
  client estimate as enforced scan budget.
- Add explicit lazy SDK and `gravity sql explorer inspect|execute|promote` only.
  Local SQLite produces no Runtime transport request; registered SQL and all
  Agent/Plan routing remain unchanged.
- Every result is `exploratory`, completeness `unknown`, allowed claims empty
  and unavailable to stable dependencies. SQL/path/parameters never enter safe
  session/error/promotion metadata or public Receipts.
- Promotion requires a successful value-free source, explicit approval and
  independent review-evidence digest. It validates and explicitly installs a
  versioned `custom-sql` definition, returns its consumer contract, and grants
  no stable Trust.
- Acceptance binds the attack corpus, direct database mutation defense with AST
  bypassed, fake-clock/resource/output budgets, privacy snapshots, promotion
  lifecycle, registered-SQL no-fallback regression, full gates, isolated wheel
  and canonical consumer. Active human docs remain exactly 5,500 lines.

## Implemented Portion

- Feature `5dbf33bad14a8ce13250d28d337e2e71cb9d8dff` was merged as
  `dev@a0033700ca9e78b964fd3cf2855f391310bb1f1e`; the merge tree is byte-identical
  to the fully validated feature tree. Existing Gravity custom-SQL routes,
  registered product compile/query/Evidence, Plan adapters and Insight routing
  are unchanged and never fall back to Explorer on either success or failure.
- The first closed dialect is SQLite with required `sqlglot==30.17.0`. SQLGlot
  receives explicit dialect `sqlite`, must produce exactly one stable canonical
  outer `Select` AST, and carries comment/CTE/table/function/placeholder/output
  evidence. DDL/DML, PRAGMA, ATTACH, multiple statements, comments, set
  operations, star projection, dynamic/attached/system relations, unknown
  functions and output/parameter mismatch stop before caller execution.
- Each inspect/execute opens an absolute existing regular file only through a
  generated `file:` URI with `mode=ro`, applies/readbacks
  `trusted_schema=OFF`, `mmap_size=0` and `query_only=ON`, begins one deferred
  transaction and keeps a SQLite authorizer plus progress handler installed
  through prepare/step. A test bypassed AST and then removed the authorizer;
  the database connection still rejected DELETE and a writable connection
  proved all 120 fixture rows unchanged.
- AST and database authorizer both enforce the exact relation/view/function
  allowlists. A real allowed view executed while its hidden COUNT and base-table
  read were authorized only through the named view/function policy; session
  counts include actual database authorization callbacks rather than AST alone.
- SQLite `setlimit` lowers value/SQL/column/expression/compound/function/attach/
  pattern/trigger/variable/VDBE/worker limits. The progress handler interrupts at
  the earlier fake-clock timeout or VM-step resource budget; a generated outer
  limit and row/cell/total-byte gates return no partial rows. Session metadata
  calls this `sqlite_vm_steps`, never a measured scan-byte budget.
- `gravity.sql-explorer-result.v1` always reports `trust=exploratory`,
  completeness `unknown`, no allowed claims, `stable_dependency_allowed=false`
  and `network_called=false`. SQL, parameters and database paths are absent from
  success/error/session/promotion metadata; no HTTP Receipt is created. Result
  digests bind rows, while the promotion source contains no rows or row digest.
- Lazy `sdk.sql_explorer.inspect()/execute()/promote()` and explicit
  `gravity sql explorer inspect|execute|promote` share one owner. Explorer works
  without configured products and constructs neither Insight nor registered-SQL
  clients. Registered SQL CLI imports SQLGlot only if Explorer is actually used.
- Promotion requires an exact successful value-free source, explicit approval,
  independent review-evidence SHA-256, name/version and a complete existing
  `custom-sql` definition. The canonical workspace validator proves datasource/
  App, exact placeholders, aggregate privacy, projection/semantics, forbidden
  claims and max rows; output adds version/source/review provenance and a
  consumer contract. CLI atomically writes only the explicit output. Automatic
  install/replacement and stable Trust/Journey/Skill/Dashboard/Action use remain
  false.
- R15 focused coverage is `13 tests, 15 subtests`; broader SQL/SDK/Trust/Plan/
  workspace/public/documentation coverage passed `108 tests, 40 subtests`.
  Complete merge-tree gates passed `1747` unittest tests and `1747 passed, 3964
  subtests` under pytest. Compiler remains `237 operations, 11 manifests`;
  quality, all four deterministic generators, root/SQL help, dependency, docs,
  diff checks and touched Ruff passed. Active human docs remain exactly `5500`
  lines.
- Public root exports are additive at `147` lazy entries / `148` `__all__`
  names. Actionable errors remain `1345 = 1178 A + 167 B + 0 C`. Development
  usability remains selection `296/336`, fillability `248/248`, offline terminal
  `53/53`, recovery `5/5`, security violations `0`, skipped production cases
  `283` and production HTTP requests `0`.
- Final isolated wheel `gravity_insight-0.3.0-py3-none-any.whl` has SHA-256
  `a275d5bd16dba237c0d65a74a10a226f737a67cc99e6f9acaf33b18b03cef012`.
  External `site-packages` proved exact SQLGlot metadata, all four packaged
  schemas, root validators and a real temporary mode-ro SQLite aggregate with
  zero transport requests. Canonical
  `work-dashboard@d1915a18278fca8823782a7d13e691a6d5702ad2` remained clean and
  passed `11 tests, 94 subtests`; no consumer migration was required.
- Official parser/database evidence was read from
  https://pypi.org/project/sqlglot/, https://sqlglot.com/sqlglot.html,
  https://sqlite.org/uri.html, https://sqlite.org/pragma.html#pragma_query_only,
  https://sqlite.org/security.html and https://sqlite.org/c3ref/set_authorizer.html.
  Structural technical debt was reviewed and no current entry changed or closed.
  Production/external database probes, Gravity/Provider HTTP or RPC, credentials,
  remote writes, releases and `main` promotion performed by R15: `0`.

## Known Limits

- SQLite is the only dialect and accepts only explicit local regular database
  files. There is no PostgreSQL/MySQL/Gravity Explorer identity adapter; a future
  network dialect must prove its server role/transaction/resource controls and
  use the existing Runtime Governor before becoming executable.
- SQLite VM steps are an enforceable resource budget, not a scan-byte measure.
  Explorer therefore keeps completeness unknown and makes no cost/coverage claim.
- Exploratory rows are returned only to the explicit caller and are not durable
  Runtime evidence. Callers remain responsible for protecting any file/stdout to
  which they explicitly direct those rows.
- Promotion review evidence is external and the Runtime does not infer semantic
  equivalence between SQLite exploration and reviewed registered SQL. Explicit
  promotion validates and atomically installs the reviewed definition, while
  stable Trust still requires the normal same-layer validation lifecycle. R15
  is `fixed_dev`; installation grants no stable identity by itself.

## Scope

- Select explicitly supported SQL dialects and mature parsers.
- Require a separate database-enforced read-only identity and read-only transaction.
- Parse exactly one statement; allow only approved relation/view/function forms.
- Enforce statement timeout and database-supported scan/resource limits plus row/byte output limits.
- Return an exploratory envelope and implement a deterministic review/promotion
  path that registers a Registered SQL Product through an explicit governed
  installation lifecycle.

## Non-goals

- No generated SQL, automatic API fallback, multi-statement execution, DDL/DML or hidden stored-procedure calls.
- No stable Journey, Skill, subscription, Dashboard or Action use before promotion.
- No client-side claim that an unenforceable scan estimate is a hard budget.

## Machine Contract

Session records dialect, parser/version, policy digest, identity class and enforced budgets. Output always has `trust=exploratory` and `completeness=unknown`. Unsupported dialect, unprovable read-only mode or absent server-side budget produces a stable blocked reason before execution.

## Migration And Compatibility

Registered SQL remains the only trusted repeatable SQL product. Explorer is a separate explicit command/service and never intercepts Insight or registered SQL failures. Promotion currently produces a reviewed versioned installation artifact and consumer contract; installation registers the product.

## Safety And Operations

Use a proven parser library; do not hand-roll prefix/regex parsing. Relation and function allowlists are exact. Query text and values follow privacy/logging rules and are not stored in public Receipts. The Runtime Governor owns Explorer transport requests.

## Acceptance

- DDL/DML, multiple statements, comments/tricks, disallowed relations/functions and budget gaps fail closed.
- Database identity cannot mutate even if parser policy fails.
- Timeout/scan/row/byte limits are tested against the selected dialect adapter.
- Explorer output cannot satisfy stable dependencies.
- Promotion registers a normal Registered SQL Product with reviewed projection/privacy through the explicit installation lifecycle.

## Verification

Dialect parser attack corpus, integration tests against a safe test database, read-only role proof, timeout/budget cases, privacy/logging snapshots, promote lifecycle, no-fallback tests and full gates.

## Rollback And Exit

Disable the Explorer command/service without changing registered SQL. Exploratory sessions are not migrated into trusted products automatically.

## Canonical Owners

Explorer session/dialect/policy schemas, SQL service/CLI reference, promotion workflow and security documentation.
