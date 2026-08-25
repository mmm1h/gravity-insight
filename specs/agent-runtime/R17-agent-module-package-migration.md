# R17 Agent Module Package Migration

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.2` via `directive.json`; canonical architecture source remains v9.1 |
| Status | `specified`; independent review is required before `ready` |
| Track | Structural migration / technical debt #11 |
| Dependencies | No Requirement dependency; M0 characterization is an entry gate |
| Parallel group | `structural-migration` |
| Shared-spine integration | Required and serialized |
| Delivery mode | `staged_epic`; R17-M1 then R17-M2 |
| Specification baseline | `dev@01e20b49a73f17b8e0c8e76d6a9bc17f4974322b` |
| Implementation branch / worktree / Issue | Unbound until independent review and `ready` binding |
| Production requests | `0`; package-only migration |
| Main integration | Frozen; adding R17 extends `all_index_requirements_fixed_dev` |

## Outcome

Move all 83 root `agent_*.py` modules into a minimal
`gravity_sdk/agents/` domain package while keeping the 527-line
`gravity_sdk.agent` module as the stable facade. The root package falls from
578 to 495 Python files without changing the 147-symbol root API, behavior,
request volume, privacy, execution ownership, or supported consumers.

## Delivery Mode Evidence

R17 has one final outcome and one exit: the complete 83-module migration with
the new package boundary locked. R17-M1 is not a permanently optional
capability; leaving the remaining 34 modules at root cannot close technical
debt #11 or satisfy the final structural invariants. The measured dependency
direction is the safe staging proof: the 49 peripheral modules have zero edges
to the 34 core modules, while the core has 155 edges to the periphery. M1 can
therefore merge and roll back without a root compatibility shim; moving all 83
modules in one branch would discard that independently reversible boundary.

M0 is an entry gate, not an indexed delivery milestone. Its characterization
work does not by itself produce a supported package migration state and must
not be used to claim staged progress.

## Milestones

### M0 Characterization Entry Gate

Before R17-M1 may become `ready`, bind the exact commit, test IDs, fixture
paths, and digests for all four existing characterization deliverables:

- isolated-process root lazy-import first access, cache, unknown attribute,
  `dir()` and `__all__` behavior;
- an installed-wheel import of every shipped Python module outside the source
  checkout;
- a complete old deep-import and string-based import-path inventory with an
  explicit old-to-new mapping;
- the eager-import graph invariant `multi_node_scc_count == 0`.

The separately produced `tmp/codex/dyn-audit/` report plugs into the same
consumer inventory. Its absence does not block R17 at `specified`, but an
unclassified dynamic-import site blocks the affected migration milestone from
becoming `ready`.

### R17-M1 Peripheral Package Slice

Create a minimal `gravity_sdk/agents/__init__.py` and move exactly the 49
peripheral modules named by the M0 inventory, removing the redundant
`agent_` filename prefix one for one. Migrate every known static, string, test,
script, and canonical-consumer reference in the same milestone. M1 acceptance
requires 529 root Python files, 34 remaining root `agent_*.py` files, 49
migrated modules under `agents/`, zero public owner changes, no shim, unchanged
public API bytes, and all M0 gates green. M1 has its own Issue, branch, commit,
acceptance, and revert.

### R17-M2 Core Package Slice And Boundary Lock

After M1 is `fixed_dev`, move the remaining 34 core modules, including
`agent_capabilities`, `agent_composite`, and `agent_handoff`; update `cli.py`,
the root facade/lazy exports, all remaining consumers, and the three physical
paths in `index.json.shared_spine`. Land the permanent structural-invariant
tests in this same milestone so the final migration cannot be accepted without
its anti-regression boundary. M2 has its own Issue, branch, commit, acceptance,
and revert; reverting M2 must leave the accepted M1 state usable.

## Current Baseline

- `src/gravity_sdk/` contains 578 root Python files, including 83
  `agent_*.py` files; the complete package contains 642 Python files.
- `src/gravity_sdk/agent.py` is a 527-line stable facade and remains at root.
- The root public snapshot contains 147 symbols. Six lazy owner routes are
  expected to change only in M2: `capabilities_many` to `.agents.batch`;
  `host_product_catalog` and `host_product_selection_schema` to
  `.agents.host_catalog`; and `assess_host_product_selection`,
  `compile_host_product_selection`, and `resolve_host_product_selection` to
  `.agents.host_selection`.
- The earlier research baseline found 113 deep `agent_*` imports and 187
  string references. Those counts are evidence of migration risk, not frozen
  acceptance numbers; M0 must rederive the exact inventory at the bound R17
  implementation baseline.
- The eager import graph has zero multi-node strongly connected components.
  Runtime-only cycles and the separate graph-community result are diagnostic
  evidence, not permission to change behavior.

## Write Scope

- Move exactly `src/gravity_sdk/agent_*.py` (83 files) to one-for-one
  `src/gravity_sdk/agents/*.py` targets and add only a minimal package
  initializer.
- Update `src/gravity_sdk/agent.py`, `src/gravity_sdk/__init__.py`, known
  static/dynamic import consumers, tests, scripts, fixtures, and active import
  references required by those path changes.
- Move the three shared-spine modules with their core slice and serialize their
  integration; update `src/gravity_sdk/cli.py` imports and the Requirement
  Index shared-spine paths in M2.
- Add characterization, installed-wheel, public-owner migration, consumer
  census, dependency-boundary, and eager-graph gates owned by this migration.
- `src/gravity_sdk/plan_adapters.py` and `src/gravity_sdk/__main__.py` do not
  move and are outside the write scope absent new pre-`ready` evidence and an
  independently reviewed scope revision.

## Non-goals

- No migration of `plan_*`, `analysis_*`, `metadata_*`, `segment_*`, or
  `sdk_*`; their measured cohesion is too low and prefix packaging would add
  cross-package edges.
- No `blob_*` pilot, broad root cleanup, layer-by-layer contract/core/surface
  redesign, logic refactor, second execution path, or public compatibility
  alias.
- No behavior, schema, route, ordering, fingerprint, error, privacy,
  concurrency, request-count, or network change.
- No closure of technical debt #11 after M0 or M1.

## Machine Contract

- Every source `agent_<name>.py` maps to exactly
  `gravity_sdk.agents.<name>`; `gravity_sdk.agent` remains the only root
  `agent*.py` module after M2.
- `gravity_sdk.agents.__init__` imports no business module and exposes no
  parallel facade. Internal modules must not import the package root facade or
  `gravity_sdk.agent`; the allowed direction is the root facade importing the
  package. Dependencies on non-facade root implementation modules are limited
  to the exact M0 inventory and may not increase.
- No old root module, `sys.modules` alias, import hook, or duplicate source file
  may preserve a removed deep path.
- The root symbol names and attributes remain fixed at 147. The owner migration
  ledger permits exactly the six M2 changes listed above and no M1 changes.
- The installed package must contain all 83 migrated modules and retain
  `multi_node_eager_import_scc_count == 0`.

## Current-Behavior Characterization

M0 freezes the root lazy-export protocol, all-module installed-wheel import,
deep import/string consumers, and eager import graph before any move. M1 and M2
also compare representative CLI, SDK, Plan, Agent, happy, empty, partial, and
error outputs; request counts, route/selection order, fingerprints, error
codes, privacy projection, concurrency, and zero-network failures must match
the bound baseline.

## Capability Preservation

All 147 `from gravity_sdk import <symbol>` names and returned attributes remain
available, `gravity_sdk.agent` and its public behavior remain stable, and the
existing selector, catalog, handoff, composite, Plan, CLI, receipt, privacy,
budget, and execution owners retain their semantics. Owner-path changes are
metadata-only and limited to the six explicit M2 entries; no capability may be
removed, weakened, guessed, or duplicated to make the migration pass.

## Consumer Migration

Each milestone migrates all repository imports, patch targets, import strings,
tests, scripts, generated references, and canonical consumer references to its
exact old-to-new map in the same release unit. Before `ready`, the M0 inventory
must absorb `tmp/codex/dyn-audit/`, identify concatenated `prober/*` imports,
and record every unresolved site as a blocker. Re-scan the canonical
`work-dashboard` consumer at both milestones and retain evidence even when no
source edit is required. Lack of outbound network means unknown external deep
importers remain an explicit residual risk; it never authorizes a permanent
shim or a claim of global consumer completeness.

## Safety And Operations

The migration performs no production probe, target request, credential use,
mutation, package installation into a user environment, release, or `main`
promotion. Package discovery must be proven from an isolated built wheel.
Shared-spine final wiring, public-owner fixture updates, generated artifacts,
and coverage artifacts are serialized through one integrator.

## Acceptance

### R17-M1

- Exactly 49 inventory-listed peripheral modules move; root Python files equal
  529, root `agent_*.py` equals 34, and migrated `agents/` modules equal 49.
- The M0 consumer map is exhausted for those paths, no shim exists, and public
  root symbol names, owner mapping, facade behavior, outputs, and request
  behavior are unchanged.
- The installed-wheel all-module import and eager SCC zero gates pass.

### R17-M2 And Parent Exit

- Root `agent_*.py == 0`, root Python files equal 495, and `agents/` contains
  exactly 83 migrated modules, excluding its minimal `__init__.py`.
- The 147 root symbols and their attributes are unchanged; the owner ledger
  contains exactly the six approved changes and no others.
- `gravity_sdk.agent` remains the stable root facade; no removed deep-path shim,
  alias, hook, duplicate source, or second facade exists.
- `agents/` has no back-import through `gravity_sdk` or
  `gravity_sdk.agent`; non-facade root dependencies do not exceed the frozen M0
  set, package initialization remains minimal, and eager multi-node SCC count
  remains exactly 0.
- The three shared-spine paths point to `agents/capabilities.py`,
  `agents/composite.py`, and `agents/handoff.py`; `plan_adapters.py` and
  `__main__.py` remain in place.
- Focused migration, public API, CLI/SDK/Plan/Agent parity, consumer census,
  isolated-wheel, both complete collectors, compiler, quality, usability,
  security, CLI help, and diff gates pass at the exact commands bound before
  each milestone becomes `ready`.
- Technical debt #11 closes only with the parent at `fixed_dev`. `main` remains
  frozen until R17 and every other indexed Requirement are `fixed_dev`,
  integrated validation is green, and the user gives new explicit approval.

## Verification

The independent reviewer must bind exact focused test selectors, fixture
digests, full validation commands, implementation baseline, Issue, branch,
worktree, integrator, and canonical consumer revision before advancing M1 or
M2 to `ready`. Each milestone reruns M0 plus its own numeric and behavioral
gates; parent acceptance reruns the complete repository gate from the fully
integrated M2 tree.

## Rollback

R17-M1 rollback restores the 49 root files and all mapped consumers, then
removes the new package only after the old paths are restored. R17-M2 rollback
restores the 34 core root files, six lazy owners, CLI imports, consumers, and
three shared-spine paths while retaining the accepted M1 package state. Any
symbol loss, unapproved owner change, output/request drift, wheel omission,
consumer failure, boundary violation, or eager cycle requires reverting the
current milestone; no data or external state migration is involved.

## Exit Conditions

R17 exits only when every R17-M1/M2 acceptance predicate is true: root
`agent_*.py == 0`; root Python file count `== 495`; migrated `agents/` module
count `== 83`; root public symbols `== 147`; approved owner changes `== 6`;
eager multi-node SCC count `== 0`; no old-path shim exists; the facade,
behavior, consumers, isolated wheel, and complete gates pass. Any different
number or unresolved consumer leaves R17 incomplete.

## Canonical Owners

The long-lived owners are the `gravity_sdk/agents/` package boundary, the
stable root facade and lazy-export map, public API and owner-migration fixtures,
dependency/import boundary tests, installed-wheel import gate, Requirement
Index shared-spine list, canonical consumer evidence, and technical debt #11.
This Requirement records delivery governance and must not become a second
runtime contract.
