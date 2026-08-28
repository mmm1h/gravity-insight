# R17 Compact Agent Interaction Package Migration

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.3` via `directive.json`; canonical bytes and consumed one-shot authority are unchanged |
| Status | `fixed_dev`; accepted under `agent_under_standing_owner_delegation`; `owner_review: pending`; not released |
| Track | Structural migration / technical debt #11 |
| Requirement dependencies | None |
| Parallel group | `structural-migration` |
| Shared-spine integration | Required and serialized |
| Delivery mode | `leaf`; one implementation branch/worktree with two serial commit and rollback checkpoints |
| Measurement baseline | `codex/gov-staged-epic@aa46ddf3343d8fb8ea0162b7806403527a2d79d9` |
| Implementation baseline | `dev@26a765a34e16b167093f5133ff2982a5d07d167a` |
| M0 evidence candidate | `codex/m0-characterization@088d1606127439943cab0b79c8cdbdf516af4839` |
| Implementation Issue | `none`; internal structural debt must not receive a self-created GitHub Issue under `docs/maintainers/issues.md` |
| Implementation branch / worktree | `codex/r17-migration` / `D:/git-pjt/gravity-sdk-r17-migration` |
| Production requests | `0`; structural migration only |
| Main integration | Frozen; adding R17 extends `all_index_requirements_fixed_dev` |

## Outcome

R17 delivered the human-reviewed compact Agent interaction manifest: discovery,
selection, binding, cards and handoff. Its 82 exact one-to-one moves live under
`gravity_sdk.agents`; `agent_pagination` was consolidated into the existing
`pagination_completeness.py` owner, and the unused `metadata_inventory()`
wrapper was deleted. Runtime execution, the shared schema validator and the
independent Find protocol retain their existing owners.

This is an explicit, bounded migration decision, not proof of the complete
Agent domain or of general automated boundary independence. The retired legacy
graph/docstring/consumer-count classifier and v4 responsibility-binding
experiment had no Runtime consumers. Their fixed membership and known
import-time side-effect misresolutions did not supply an independent boundary
proof. Their helpers, embedded contracts, signed summaries and self-tests are
retired; Git retains the historical evidence without a new active archive.

At accepted dev integration `125bb84cbb98a575a2ef3c4a577f174027bc908d`,
the root package fell from 578 to 495 Python files and the complete package had
642 files. Those totals are immutable delivery-baseline evidence, not rolling
limits on the evolving package. The delivered boundary had 82 implementation
modules under `agents/`, 147 lazy owners and 148 root `__all__` names. Runtime
responses, request volume, privacy, execution ownership and supported read
capability were unchanged; removed deep paths had no shim. The five facade
dependencies listed below are intentional shared discovery/protocol-owner reuse,
not unfinished work for technical debt #11.

R17 remains one delivered leaf. Phase 1 and Phase 2 are the original serial
commit/rollback checkpoints, not independent milestones. This post-delivery
test/governance retirement is a separate maintenance unit and does not rewrite
either checkpoint or its two-level rollback chain.

## Delivery Acceptance And Historical Evidence

`index.json.delivery_acceptance` records the external plan-owner verdict. The two
satisfied `ready_prerequisites` entries below retain historical M0 and dynamic
ledger bindings; they do not backdate a `ready` verdict or claim new per-requirement
user approval. The former experimental independent-ready requirement is retired.

1. **Satisfied at `dev@113176a381b6d232e95a112d78d1d2f4bc5ac024`.** The M0
   candidate commit `088d1606127439943cab0b79c8cdbdf516af4839` is an ancestor
   of that baseline. M0 content changed after that commit, so the bound
   artefacts are the baseline copies, not the candidate copies:

   | Artefact | SHA-256 |
   | --- | --- |
   | `tests/agent_migration_characterization.py` | `97b3c71842b3904213ec24667ae09f4c821df0384f6667847e3c03f6c9d9d640` |
   | `tests/test_agent_module_migration_characterization.py` | `6e5c0530fbc7b869d896d26cb01ec76649f4bf2a48adeeb0b9968395f4af8ffc` |
   | `tests/test_installed_wheel.py` | `bd8d9cf332354147fd4e11f87ac7d09b48ac7dcf1d4eae164900b0baf7bed117` |
   | `tests/fixtures/public_api_owner_migrations.json` | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
   | `tests/fixtures/public_api_exports.json` | `d6aa4c9bb939f6e56428192ad432300fe985618fae69492cc9e12820dd43c053` |

   The bound visitor now retains self-loops and intersects the exact ledger move
   set plus pagination consolidation; the excluded contracts owner does not
   enter that predicate. This prerequisite remains satisfied with
   `owner_review: pending`.
2. **Satisfied under standing delegation; owner review remains pending.** The
   immutable 238-row errata ledger (SHA-256
   `9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20`,
   schema `gravity.agent-module-reference-dispositions.v2`) remains separate
   from the live checkpoint receipt. The live scanner covers static references,
   dynamic loaders, indirect variables, string patch targets, and opaque forms;
   the current denominator is bound by the live checkpoint markers below.
   Unknown module names and cross-function loaders remain real blockers rather
   than exclusions; the frozen ledger is not regenerated.
3. **Delivered and accepted on dev.** The external plan owner accepted Phase 1
   `4926362f42f9ea68a11e42559a802cb7ba67f6ee`, Phase 2
   `ea33c42eeb82fc7fb8a62ef60e11ba5a8527dc69`, and integration
   `125bb84cbb98a575a2ef3c4a577f174027bc908d`. Full pytest and unittest gates
   passed on that integration (1900 tests; pytest additionally reported 4631
   subtests). Both rollback targets matched their exact trees; independent
   thermo review reported no high-confidence blocker. These are the supplied
   external delivery findings, not a fabricated earlier `ready` approval.

`accepted_by=agent_under_standing_owner_delegation`; `owner_review=pending`;
`phase_1_commit=4926362f42f9ea68a11e42559a802cb7ba67f6ee`;
`phase_2_commit=ea33c42eeb82fc7fb8a62ef60e11ba5a8527dc69`;
`dev_integration_commit=125bb84cbb98a575a2ef3c4a577f174027bc908d`.

The historical candidate audit's 83/83 old-path smoke imports and zero naming
collisions remain historical observations, not an ownership-selection rule.

Machine state shared by this Requirement and `index.md`: `status=fixed_dev`;
`dynamic_import_audit_classification.satisfied=true`;
`schema=gravity.agent-module-reference-dispositions.v2`; `candidate_sites=238`;
`classified_sites=238`; `unclassified_sites=0`; `blocking_sites=0`.

`m0_bound_implementation_baseline=113176a381b6d232e95a112d78d1d2f4bc5ac024`;
`m0_bound_artifact_sha256={"tests/agent_migration_characterization.py":"97b3c71842b3904213ec24667ae09f4c821df0384f6667847e3c03f6c9d9d640","tests/fixtures/public_api_exports.json":"d6aa4c9bb939f6e56428192ad432300fe985618fae69492cc9e12820dd43c053","tests/fixtures/public_api_owner_migrations.json":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570","tests/test_agent_module_migration_characterization.py":"6e5c0530fbc7b869d896d26cb01ec76649f4bf2a48adeeb0b9968395f4af8ffc","tests/test_installed_wheel.py":"bd8d9cf332354147fd4e11f87ac7d09b48ac7dcf1d4eae164900b0baf7bed117"}`;
`ledger_sha256=9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20`.
`live_checkpoint_sha256=8d3b9cde76f88ae22736a99b6b65a469ae7b8ff98b09527518ad395a03b8d6e5`;
`live_checkpoint_tracked_sites=309`.

The required cross-file state gate is
`tests/test_agent_module_reference_dispositions.py::AgentModuleReferenceDispositionTests::test_index_and_specification_state_agree`.
It must load both JSON files as UTF-8 and assert that the R17 Index entry, this
Requirement, and `index.md` all report `fixed_dev`, schema v2, 238 candidate and
classified sites, zero unclassified and blocking sites, and a satisfied
dynamic-audit prerequisite; it must also reject any previous-generation site
count or ledger-schema claim in the three R17 state representations.

## Reviewed Manifest And Target Naming Rule

The frozen `tests/fixtures/agent_module_reference_dispositions.json` is the
human-reviewed migration manifest, not input to an automated boundary selector.
Its 84 reviewed root modules comprise 82 moves, one pagination consolidation and
one retained shared-contract owner; the stable facade remains at its root path.
The compact interaction scope excludes shared Runtime schema validation and the
independent Find protocol because they serve different execution/protocol
responsibilities, not because of prefixes, consumer votes or facade reachability.

The existing `make_module_map` / `_frozen_module_scope` gates enforce exact
unique old/new pairs, one extant owner per move, only the legal Phase 0/1/2
counts, both fixed owners, and rejection of extra root Agent owners. Current
package membership must equal all 82 frozen targets; it cannot be re-selected
to fit the implementation. Public owner preservation uses
`expected_public_exports()`, the unchanged six-row owner ledger and isolated
root-import tests. Complete eager-graph, concept-deletion and canonical-errata
gates remain the other independent migration checks.

Every target removes exactly one adjacent redundant Agent boundary token:
`agent_sources` becomes `agents.sources`, and `relative_date_agent`
becomes `agents.relative_date`. Targets remain unique, including case-folded
names, and cannot alias unrelated root modules. Relative-date remains internal
to handoff and is not a root lazy export.

## Explicit Concept Deletions

`agent_pagination.py` is 29 lines, exports only `compact_pagination`, and has
one importing/calling module: `agent_sources.py`. Phase 1 moves the function
unchanged into `pagination_completeness.py`, updates the caller, and deletes the
module. This removes a single-function forwarding concept in favor of the
existing canonical owner; it is not a fail-closed recognizer merge.

`agent_batch_sources.metadata_inventory()` is a compatibility wrapper whose
body is only `metadata_inventory_state(warnings)[0]`. Static source census finds
zero imports and zero calls to that function; same-spelled dataclass fields are
not callers. Phase 2 deletes only this wrapper while retaining
`metadata_inventory_state()` and its failure ordering. The rebound dynamic
ledger and bound consumer census must also find no real dynamic caller; any
such caller blocks acceptance instead of gaining a shim.

These are the only consolidation/deletion actions. The remaining 48 peripheral
modules move one for one; no recognizer is merged or generalized into a
data-driven registry.

## Excluded Infrastructure

`agent_runtime_contracts.py` remains at the root as the shared Runtime schema
validator owner (`validate_schema`, `JsonSchemaValidator`,
`AgentRuntimeContractError`). It is not copied, aliased or re-exported from
`agents/`. Find remains an independent primary protocol. A later relocation
requires a separate owner decision, not a result from a retired classifier.

## Internal Implementation Plan

The following Phase 1/2 plan and checkpoint commands preserve the original
migration history. Both commits were accepted at the exact revisions above;
they are not instructions to re-run or rewrite that history during retirement.

The implementation binds one `codex/r17-*` branch and one worktree. Phase 1
and Phase 2 are ordered commits on that branch. The accepted Phase 1 commit and
the final Phase 2 commit are recorded as rollback checkpoints; neither creates
another branch, Requirement node, or independently releasable unit.

### Phase 1: Peripheral 48 And Pagination Consolidation

The first serial checkpoint starts from the reviewed R17 baseline on the single
implementation branch. It creates a minimal `gravity_sdk/agents/__init__.py`,
migrates the following 48 modules, consolidates `agent_pagination`, and migrates
every classified repository and canonical-consumer reference:

```text
agent_advertiser_profile agent_analysis_default_dictionary agent_analysis_task
agent_app_catalog agent_app_public_info agent_attribution_performance
agent_attribution_user_detail agent_bilibili_account_performance agent_call_bound
agent_caller_language agent_catalog_parity agent_catalog_refresh agent_client
agent_company_usage agent_custom_audience agent_custom_metric agent_derived_metrics
agent_fixed_snapshots agent_gap agent_input_catalogs agent_intent_text
agent_kanban_mutation agent_lexical_rescue agent_material_asset
agent_metadata_onboarding agent_metadata_search agent_metadata_template
agent_monetization_aggregate agent_mutation_cards agent_order_directory
agent_order_trace agent_promotion_performance agent_realtime_event
agent_realtime_event_catalog agent_report_directory agent_report_mutation
agent_saved_analysis agent_saved_analysis_mutation agent_segment_members
agent_segment_snapshot agent_semantic_compose agent_sql_product_gap
agent_title_package agent_unavailable_promotion agent_unavailable_report
agent_user_journey agent_vocabulary relative_date_agent
```

Phase 1 acceptance requires 529 root Python files, 35 remaining root
`agent_*.py` files, exactly 48 migrated implementation modules under `agents/`,
no `agent_pagination.py`, an unchanged 642-file complete package, 148 root
`__all__` names, 147 lazy owners, zero unresolved classified references, and
zero full-graph SCCs intersecting the migration set. Its accepted commit becomes
the rollback checkpoint and base of Phase 2 but receives no independent
Requirement state.

Rollback from Phase 1 reverts the single Phase 1 commit to the reviewed baseline
checkpoint, restoring all 48 root modules, `agent_pagination.py`, its caller,
and every mapped consumer before removing package targets. It does not switch,
delete, or reset a phase branch because no phase branch exists.

### Phase 2: Core 34 And Boundary Lock

The second serial checkpoint continues on the same branch from accepted Phase
1. It moves the frozen 34-module core and deletes only
`metadata_inventory()`:

```text
agent_analysis agent_batch agent_batch_questions agent_batch_sources
agent_business_pulse agent_capabilities agent_catalog agent_composite
agent_composite_inventory agent_dashboard agent_discovery_policy
agent_discovery_support agent_export agent_handoff agent_host_catalog
agent_host_selection agent_input_resolution agent_intent_routing
agent_lexical_retrieval agent_material_performance agent_monetization_guard
agent_multidim agent_operation_contract agent_output agent_product_inventory
agent_report_routing agent_segment agent_semantic_context agent_semantic_derived
agent_sources agent_sql_product_discovery agent_table_lineage agent_unavailable
agent_unavailable_analysis
```

The reviewed scope split is 34 core plus 49 peripheral modules, including
`agent_pagination`: 154 unique core-to-peripheral edges and zero reverse edges.
The physical move split is 34 core plus 48 peripheral modules; removing the
sole `agent_sources -> agent_pagination` edge gives 153 core-to-moved-peripheral
edges and zero reverse edges.

Phase 2 updates `cli.py`, the facade, lazy owners, remaining consumers, and the
three physical paths in `index.json.shared_spine`. Phase 2 rollback reverts its
single commit to the recorded Phase 1 checkpoint, restoring the 34 core files,
wrapper, owners, imports, consumers, and shared-spine paths. Full R17 rollback
then reverts Phase 1 to the reviewed baseline checkpoint.

## Reproducible Measurements

Run every command from the repository root with the worktree interpreter and
without `PYTHONPATH`.

### Physical Cohort Edges

Membership comes only from the reviewed manifest. This bounded measurement is
not a responsibility classifier; eager SCC detection still uses the existing
complete-package visitor and Tarjan gate.

The final physical edge gate does not depend on old root filenames. Run it at
the final Phase 2 checkpoint on the single branch:

```powershell
$code = @'
import ast, json
from pathlib import Path
package=Path('src/gravity_sdk/agents')
paths={path.stem:path for path in package.glob('*.py') if path.name!='__init__.py'}
nodes=set(paths); edges=set()
for source,path in paths.items():
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'),filename=str(path))):
        targets=[]
        if isinstance(node,ast.Import):
            targets=[alias.name.split('.')[2] for alias in node.names if alias.name.startswith('gravity_sdk.agents.') and len(alias.name.split('.'))>2]
        elif isinstance(node,ast.ImportFrom):
            if node.level==1 and node.module:
                targets=[node.module.split('.')[0]]
            elif node.level==1:
                targets=[alias.name for alias in node.names]
            elif node.level==0 and node.module and node.module.startswith('gravity_sdk.agents.'):
                targets=[node.module.split('.')[2]]
        edges.update((source,target) for target in targets if target in nodes and target!=source)
core=set('''analysis batch batch_questions batch_sources business_pulse capabilities catalog composite composite_inventory dashboard discovery_policy discovery_support export handoff host_catalog host_selection input_resolution intent_routing lexical_retrieval material_performance monetization_guard multidim operation_contract output product_inventory report_routing segment semantic_context semantic_derived sources sql_product_discovery table_lineage unavailable unavailable_analysis'''.split())
peripheral=nodes-core
print(json.dumps({'implementation_modules':len(nodes),'core':len(nodes&core),'peripheral':len(peripheral),'core_to_peripheral':sum(u in core and v in peripheral for u,v in edges),'peripheral_to_core':sum(u in peripheral and v in core for u,v in edges)},sort_keys=True))
'@
& ./.venv/Scripts/python.exe -c $code
```

Final required output is `implementation_modules=82`, `core=34`,
`peripheral=48`, `core_to_peripheral=153`, and `peripheral_to_core=0`.

### File And Public-Surface Counts

```powershell
& ./.venv/Scripts/python.exe -c "import gravity_sdk,json; from pathlib import Path; r=Path('src/gravity_sdk'); a=r/'agents'; s=json.loads(Path('tests/fixtures/public_api_exports.json').read_text(encoding='utf-8')); print(json.dumps({'root_py':len(list(r.glob('*.py'))),'root_agent_py':len(list(r.glob('agent_*.py'))),'package_py':len(list(r.rglob('*.py'))),'agents_implementation_py':len([p for p in a.glob('*.py') if p.name!='__init__.py']) if a.exists() else 0,'lazy_snapshot':len(s),'runtime_exports':len(gravity_sdk._EXPORTS),'root_all':len(gravity_sdk.__all__)},sort_keys=True))"
```

| Metric | Pre-migration baseline | Immutable delivery exit |
| --- | ---: | ---: |
| Root Python files | 578 | 495 |
| Root `agent_*.py` | 83 | 1 |
| Complete-package Python files | 642 | 642 |
| `agents/` implementation modules | 0 | 82 |
| Lazy fixture / runtime owners | 147 / 147 | 147 / 147 |
| Root `__all__` | 148 | 148 |

The sole final root `agent_*.py` must be `agent_runtime_contracts.py`.

Exactly six lazy owners point to the move set. The accepted changes are the two
host catalog/selection schema names to `.agents.host_catalog`, the three host
selection functions to `.agents.host_selection`, and `capabilities_many` to
`.agents.batch`. The six owner changes are delivered and accepted; the ledger is unchanged.

### Concept-Deletion Census

```powershell
rg -n "compact_pagination|agent_pagination" src/gravity_sdk tests scripts
rg -n "metadata_inventory" src/gravity_sdk tests scripts
```

The first command finds one definition/export and exactly one import plus one
call in `agent_sources.py`. The second finds no import or call of
`agent_batch_sources.metadata_inventory()`; other hits are its definition,
`metadata_inventory_state`, `_metadata_inventory`, or dataclass-field access.
The existing concept-deletion tests distinguish the wrapper from same-spelled
fields and preserve the frozen behavior oracle; text hits alone are not proof
of callers or of their absence.

### SCC And Dynamic Audit

Reuse M0's checked-in eager-import visitor and Tarjan enumeration over the one
complete 642-module `gravity_sdk` graph, including package-parent edges emitted
by the visitor. Compute every SCC first, then reject only a multi-node or
self-loop component that intersects the R17 migration set. There are two
pre-existing eager SCCs that do not intersect that set: the `prober` family has
10 modules and the `sql` family has 8 modules. They are recorded comparison
facts, not exclusions from the graph and not reasons to widen or narrow R17.
The baseline and each serial checkpoint must report no SCC intersecting the
migration set.

The immutable dynamic-audit ledger records 84 reviewed modules and 238
manual-review sites under schema v2. The separate live checkpoint scans the
complete tracked reference denominator and fails closed on opaque forms. Both
currently have zero unclassified rows and zero blockers; owner review remains
pending and no count is maintained by narrowing the scanner.

## Historical Migration Write Scope

This is the original migration's scope, now delivered. In particular, the v9.3
one-shot errata permission is consumed and cannot authorize another byte change.
Retirement changes only the two migration test files, R17/Index, #11/roadmap,
AGENTS' stale collector wording and the generated live checkpoint.

- Move exactly the 82 `move` rows to one-for-one
  `src/gravity_sdk/agents/<responsibility-name>.py` targets under the single
  adjacent-boundary-token removal rule and add a
  minimal package initializer.
- Consolidate `compact_pagination` into `pagination_completeness.py`, delete
  `agent_pagination.py`, and delete only the zero-caller `metadata_inventory()`
  wrapper under the gates above.
- Update the facade, root lazy owners, static and classified dynamic consumers,
  tests, scripts, fixtures, and active canonical-consumer references required
  by those path changes.
- Move `agent_capabilities.py`, `agent_composite.py`, and `agent_handoff.py` in
  the core phase; serialize their integration and update `cli.py` imports and
  the Requirement Index shared-spine paths in the same phase.
- Execute 15 governance-document rewrites at the core checkpoint: the 13
  rewrites recorded by the disposition ledger, plus two policy-derived
  `index.md` rewrites for active-governance references added after the ledger
  was frozen. The total comprises three in `AGENTS.md`, four in
  `specs/agent-runtime/architecture-source.md`, three in
  `specs/agent-runtime/index.json`, and five in `specs/agent-runtime/index.md`
  (three ledger-derived and two post-freeze policy-derived), plus the one
  source selector-data rewrite recorded for
  `src/gravity_sdk/__init__.py`. `AGENTS.md` edits are in-place replacements and
  must not grow the documentation budget.
- **Rewriting `architecture-source.md` breaks its digest binding.** That file is
  bound by `directive.json.canonical_source.sha256`. At the core checkpoint,
  one atomic commit must apply only the four allowlisted physical path
  corrections; add a
  new `## v9.3 修订摘要` stating "four physical path corrections; no
  architectural semantic change" while preserving the existing `## v9.2
  修订摘要` and its body; update the `Directive ID / Version` line and the
  reading-order diagram from v9.2 to v9.3; recompute the canonical source
  SHA-256; write that digest to `directive.json.canonical_source.sha256`;
  advance `directive.json.version` to `v9.3`; and set
  `directive.json.supersedes` to version `v9.2` and digest
  `54b5759bde4addbceab0e63853c7e228b1d6643d5d369321c92d0468fb1b6b2c`.
  The final machine assertion below reconstructs the complete expected v9.3
  bytes from the Git-bound v9.2 bytes and must fail on any additional deletion,
  insertion, replacement, digest, version, supersedes, or self-reference.

  `directive.json.canonical_source_errata` records the delegated
  `r17_v9_2_to_v9_3_one_shot_allowlist` decision as
  `authorized_by: agent_under_standing_owner_delegation` with
  `owner_review: pending`; R17 must not elevate that review state. The allowlist
  is initially `unconsumed`; the
  core commit must atomically mark it `consumed` by R17 with `reusable: false`.
  Its fixed source revision, versions, digest, four source replacements derived
  from the checked-in disposition ledger, and three inline metadata edits
  cannot authorize another transition. The derivation selects every
  `rewrite_reference` row for `architecture-source.md`, requires exactly four,
  and applies each action at its audited line and column. Any reuse or other
  change requires a new owner approval and separately revised directive; the
  rule also does not authorize implementation before `ready`, a release, or
  `main` promotion.
- Add or retain characterization, installed-wheel, owner-migration,
  consumer-census, boundary, concept-deletion, and eager-graph gates.
- `agent_runtime_contracts.py`, `plan_adapters.py`, and `__main__.py` do not
  move and are outside implementation scope absent a reviewed revision.

## Non-goals

- No rename or relocation of `agent_runtime_contracts`; no migration of other
  prefix families, `blob_*` pilot, or broad root cleanup.
- No merge of the 48 peripheral modules, data-driven recognizer registry,
  layer redesign, second execution path, compatibility alias, or parallel
  facade.
- No `runtime.py` / `to_jsonable()` SCC work. Its disputed graph result and
  cross-execution-core scope require a separate proposal if pursued.
- No response, schema, route, ordering, fingerprint, error, privacy,
  concurrency, request-count, or network behavior change.
- No new Runtime change, general static analyzer, backdated `ready` verdict,
  new per-requirement user-approval claim, release, or `main` promotion.

## Machine Contract

- The 82 `move` rows map one for one; `agent_pagination` is deleted after
  consolidation; `agent_runtime_contracts.py` remains at its root path;
  `gravity_sdk.agent` remains the stable facade.
- `gravity_sdk.agents.__init__` imports no business module and exposes no
  parallel facade. R17 introduces no facade back-edge. Five pre-migration
  edges remain: `agents.batch -> agent.discover_capabilities`,
  `agents.batch_questions -> agent.DEFAULT_LIMIT`,
  `agents.host_selection -> agent.SCHEMA_VERSION`,
  `agents.input_resolution -> agent.discover_capabilities`, and
  `agents.output -> agent.SCHEMA_VERSION`. They form no eager import cycle, so
  the migration-related SCC gate remains empty. Removing them requires the
  layer redesign excluded by this Requirement. They intentionally reuse the
  single discovery/protocol owners and are not a #11 exit condition. Revisit
  only if a real second owner, changed responsibility or eager cycle requires
  an explicitly approved split; preserve facade behavior and the existing SCC
  gate. A bounded module/symbol-set test locks all five edges.
- No old path for a moved/deleted module, alias, import hook, or duplicate
  source remains. The retained contracts module is not mirrored under
  `agents/`.
- `gravity_sdk.__all__` remains 148 names; the lazy fixture and runtime map
  remain 147 entries; only the six reviewed owner routes may change.
- The installed package contains all 82 migrated modules, the canonical
  pagination helper, and retained contracts module. Tarjan over the complete
  642-module graph has no SCC intersecting the R17 migration set; the unrelated
  pre-existing 10-module `prober` and 8-module `sql` SCCs remain permitted.
- Every candidate in the rebound audit denominator is dispositioned before work
  starts; any later unresolved consumer blocks the affected checkpoint and R17.

## Capability, Safety, And Consumer Preservation

M0 freezes root lazy access, cache, unknown-attribute, `dir()`, `__all__`,
installed-wheel imports, deep/string consumer paths, and the eager graph.
Both checkpoints compare representative CLI, SDK, Plan, Agent, happy, empty,
partial, and error outputs; request counts, selection order, fingerprints,
error codes, privacy projection, concurrency, and zero-network failures match
the bound baseline.

Every import, patch target, import string, test, script, generated reference,
and canonical consumer reference in the bound ledger must move or be explicitly
retained. Re-scan the bound `work-dashboard` revision at both checkpoints.
Unknown external deep
importers remain residual risk and never authorize a permanent shim or a claim
of global consumer completeness.

R17 performs no production probe, target request, credential use, mutation,
installation into a user environment, release, or `main` promotion. Shared
spine, public owners, generated artifacts, and coverage artifacts are
serialized through one integrator.

## Acceptance Commands

The original acceptance procedure below is retained with its checkpoint bindings.
Retirement runs the focused migration/owner/concept/ledger/errata/documentation/
wheel tests, structural and graph exits, both complete collectors serially,
compiler, quality, development usability, CLI help, generator `--check`, the
no-argument canonical errata validator and diff integrity. It does not replay
the original Phase 1 commands against the final tree or alter the rollback chain.

Run the five Phase 1 commands in order on the clean Phase 1 checkpoint commit
and retain their output with that commit SHA. After Phase 2, run both Phase 2
rollback commands and every command from `Structural Exit And Reviewed Owners`
onward on the clean final commit.
Do not substitute the final tree for Phase 1 evidence. Run from the R17
implementation worktree root with no `PYTHONPATH`; every assertion names the
mismatched contract. The two complete collectors are intentionally separate
because CI gates on pytest while unittest discovery remains a required parity
collector.

### Phase 1 Structural Checkpoint

This command is expected to fail on the unmigrated baseline with a
`Phase 1 structural checkpoint not reached` count diff. It passes only after
the 48 peripheral moves and pagination consolidation are physically complete.

```powershell
$code = @'
import json
from pathlib import Path
import gravity_sdk

root = Path('src/gravity_sdk')
agents = root / 'agents'
ledger = json.loads(Path('tests/fixtures/agent_module_reference_dispositions.json').read_text(encoding='utf-8'))
moves = ledger['scope']['one_to_one_moves']
core = set('''analysis batch batch_questions batch_sources business_pulse capabilities catalog composite composite_inventory dashboard discovery_policy discovery_support export handoff host_catalog host_selection input_resolution intent_routing lexical_retrieval material_performance monetization_guard multidim operation_contract output product_inventory report_routing segment semantic_context semantic_derived sources sql_product_discovery table_lineage unavailable unavailable_analysis'''.split())
phase1 = {row['new_module'].rsplit('.', 1)[1] for row in moves} - core
assert len(moves) == 82 and len(core) == 34 and len(phase1) == 48, f'Phase 1 reviewed set mismatch: moves={len(moves)}, core={len(core)}, phase1={len(phase1)}'
snapshot = json.loads(Path('tests/fixtures/public_api_exports.json').read_text(encoding='utf-8'))
actual = {
    'root_py': len(list(root.glob('*.py'))),
    'root_agent_py': len(list(root.glob('agent_*.py'))),
    'package_py': len(list(root.rglob('*.py'))),
    'agents_implementation_py': len([p for p in agents.glob('*.py') if p.name != '__init__.py']),
    'lazy_snapshot': len(snapshot),
    'runtime_exports': len(gravity_sdk._EXPORTS),
    'root_all': len(gravity_sdk.__all__),
}
expected = {'root_py': 529, 'root_agent_py': 35, 'package_py': 642, 'agents_implementation_py': 48, 'lazy_snapshot': 147, 'runtime_exports': 147, 'root_all': 148}
assert actual == expected, f'Phase 1 structural checkpoint not reached: expected={expected}, actual={actual}'
actual_agents = {p.stem for p in agents.glob('*.py') if p.name != '__init__.py'}
assert actual_agents == phase1, f'Phase 1 agents set mismatch: missing={sorted(phase1-actual_agents)}, extra={sorted(actual_agents-phase1)}'
expected_root = sorted([f'agent_{name}.py' for name in core] + ['agent_runtime_contracts.py'])
actual_root = sorted(p.name for p in root.glob('agent_*.py'))
assert actual_root == expected_root, f'Phase 1 root agent set mismatch: missing={sorted(set(expected_root)-set(actual_root))}, extra={sorted(set(actual_root)-set(expected_root))}'
assert not (root / 'agent_pagination.py').exists(), 'Phase 1 pagination consolidation incomplete: agent_pagination.py still exists'
print(json.dumps({'checkpoint': 'phase-1', 'counts': actual, 'phase1_modules': len(actual_agents)}, sort_keys=True))
'@
& ./.venv/Scripts/python.exe -c $code
if ($LASTEXITCODE) { throw 'R17 Phase 1 structural checkpoint assertion failed' }
```

### Phase 1 SCC Checkpoint

This uses the checked-in complete-package eager graph, but intersects its SCCs
with the exact 82 ledger moves plus the pagination consolidation owner. The
target-presence precondition distinguishes an unmigrated tree from an SCC bug.

```powershell
$code = @'
import json
from pathlib import Path
from tests.agent_migration_characterization import eager_import_sccs

root = Path('src/gravity_sdk')
ledger = json.loads(Path('tests/fixtures/agent_module_reference_dispositions.json').read_text(encoding='utf-8'))
moves = ledger['scope']['one_to_one_moves']
core = set('''analysis batch batch_questions batch_sources business_pulse capabilities catalog composite composite_inventory dashboard discovery_policy discovery_support export handoff host_catalog host_selection input_resolution intent_routing lexical_retrieval material_performance monetization_guard multidim operation_contract output product_inventory report_routing segment semantic_context semantic_derived sources sql_product_discovery table_lineage unavailable unavailable_analysis'''.split())
phase1 = [row for row in moves if row['new_module'].rsplit('.', 1)[1] not in core]
def module_path(module):
    return root.joinpath(*module.removeprefix('gravity_sdk.').split('.')).with_suffix('.py')
missing = [row['new_module'] for row in phase1 if not module_path(row['new_module']).is_file()]
old = [row['old_module'] for row in phase1 if module_path(row['old_module']).exists()]
assert not missing and not old and not (root/'agent_pagination.py').exists(), f'Phase 1 SCC precondition not reached: missing_new={len(missing)} {missing[:5]}, old_present={len(old)} {old[:5]}, pagination_old={(root/"agent_pagination.py").exists()}'
migration = {'gravity_sdk.pagination_completeness'}
for row in moves:
    present = [module for module in (row['old_module'], row['new_module']) if module_path(module).is_file()]
    assert len(present) == 1, f'migration owner must be unique for SCC check: row={row}, present={present}'
    migration.add(present[0])
components = eager_import_sccs(root)
crossing = [component for component in components if set(component) & migration]
assert not crossing, f'Phase 1 migration-related eager SCCs remain: {crossing}'
print(json.dumps({'checkpoint': 'phase-1', 'complete_graph_sccs': components, 'migration_related_sccs': crossing}, sort_keys=True))
'@
& ./.venv/Scripts/python.exe -c $code
if ($LASTEXITCODE) { throw 'R17 Phase 1 SCC checkpoint assertion failed' }
```

### Phase 1 Consumer Checkpoint

The runtime import scan rejects exact old owners for the 48 Phase 1 moves. The
independent disposition generator covers dynamic, test, script, and governance
sites; the fixed-revision census covers the canonical consumer.

```powershell
$code = @'
import ast, importlib.util, json
from pathlib import Path

ledger = json.loads(Path('tests/fixtures/agent_module_reference_dispositions.json').read_text(encoding='utf-8'))
core = set('''analysis batch batch_questions batch_sources business_pulse capabilities catalog composite composite_inventory dashboard discovery_policy discovery_support export handoff host_catalog host_selection input_resolution intent_routing lexical_retrieval material_performance monetization_guard multidim operation_contract output product_inventory report_routing segment semantic_context semantic_derived sources sql_product_discovery table_lineage unavailable unavailable_analysis'''.split())
old = {row['old_module'] for row in ledger['scope']['one_to_one_moves'] if row['new_module'].rsplit('.', 1)[1] not in core}
hits = []
for path in sorted(Path('src').rglob('*.py')):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    parts = list(path.relative_to('src').with_suffix('').parts)
    if parts[-1] == '__init__': parts.pop()
    module = '.'.join(parts)
    package = module if path.name == '__init__.py' else module.rpartition('.')[0]
    for node in ast.walk(tree):
        values = []
        if isinstance(node, ast.Import): values = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_module = importlib.util.resolve_name('.' * node.level + (node.module or ''), package)
            else: base_module = node.module or ''
            values = [base_module] + [f'{base_module}.{alias.name}' for alias in node.names if alias.name != '*']
        for value in values:
            if any(value == owner or value.startswith(owner + '.') for owner in old):
                hits.append(f'{path}:{node.lineno}:{value}')
assert not hits, f'Phase 1 runtime imports still target migrated old modules: count={len(hits)}, sample={hits[:20]}'
print('Phase 1 runtime import scan passed: old_owner_hits=0')
'@
& ./.venv/Scripts/python.exe -c $code
if ($LASTEXITCODE) { throw 'R17 Phase 1 runtime import assertion failed' }
& ./.venv/Scripts/python.exe scripts/generate_agent_module_reference_dispositions.py --check
if ($LASTEXITCODE) { throw 'R17 Phase 1 disposition ledger check failed' }
$consumerRoot = Resolve-Path '../work-dashboard'
$consumerRevision = 'd1915a18278fca8823782a7d13e691a6d5702ad2'
& git -C $consumerRoot cat-file -e "$consumerRevision`^{commit}"
if ($LASTEXITCODE) { throw "canonical consumer commit is unavailable: $consumerRevision" }
$legacyPattern = 'gravity_sdk\.agent_[[:alnum:]_]+|src/gravity_sdk/agent_(capabilities|composite|handoff)\.py'
$legacyHits = & git -C $consumerRoot grep -n -E $legacyPattern $consumerRevision -- '*.py' '*.md' '*.json' '*.toml' '*.yaml' '*.yml'
$grepExit = $LASTEXITCODE
if ($grepExit -eq 0) { $legacyHits; throw "canonical consumer still references an R17 legacy path at $consumerRevision" }
if ($grepExit -ne 1) { throw "canonical consumer census failed to execute: git grep exit $grepExit" }
Write-Output "Phase 1 consumer checkpoint passed: runtime_old_owner_hits=0; classified_dynamic_sites=clean; canonical_legacy_hits=0; revision=$consumerRevision"
```

### Phase 1 M0 And Representative Behavior Checkpoint

This gate is intentionally Phase 1-aware: the precondition accepts only the
mixed 34-old/48-new owner state after pagination consolidation. An earlier tree
fails with `Phase 1 behavior checkpoint not reached`; once that precondition is
true, canonical authority drift and behavior failures use separate regression
messages. The M0 and public-API files run in full. The focused cases then cover
CLI exit behavior, SDK and Agent routing, Plan dry-run, partial completeness,
failure isolation, and offline unknown-selector behavior without requiring the
34 Phase 2 owners to have moved.

```powershell
$code = @'
import json
from pathlib import Path

root = Path('src/gravity_sdk')
ledger = json.loads(Path('tests/fixtures/agent_module_reference_dispositions.json').read_text(encoding='utf-8'))
core = set('''analysis batch batch_questions batch_sources business_pulse capabilities catalog composite composite_inventory dashboard discovery_policy discovery_support export handoff host_catalog host_selection input_resolution intent_routing lexical_retrieval material_performance monetization_guard multidim operation_contract output product_inventory report_routing segment semantic_context semantic_derived sources sql_product_discovery table_lineage unavailable unavailable_analysis'''.split())
def module_path(module):
    return root.joinpath(*module.removeprefix('gravity_sdk.').split('.')).with_suffix('.py')
moves = ledger['scope']['one_to_one_moves']
old = sum(module_path(row['old_module']).is_file() for row in moves)
new = sum(module_path(row['new_module']).is_file() for row in moves)
pagination_old = (root / 'agent_pagination.py').is_file()
actual = {'old_moves': old, 'new_moves': new, 'pagination_old': pagination_old}
expected = {'old_moves': 34, 'new_moves': 48, 'pagination_old': False}
assert actual == expected, f'Phase 1 behavior checkpoint not reached: expected={expected}, actual={actual}'
print(json.dumps({'checkpoint': 'phase-1', 'behavior_precondition': actual}, sort_keys=True))
'@
& ./.venv/Scripts/python.exe -c $code
if ($LASTEXITCODE) { throw 'Phase 1 behavior checkpoint not reached: mixed owner precondition failed' }

& ./.venv/Scripts/python.exe scripts/validate_r17_canonical_source_errata.py --phase-1
if ($LASTEXITCODE) { throw 'R17 Phase 1 canonical authority regression after checkpoint preconditions passed' }

$behavior = @(
  'tests/test_agent_module_migration_characterization.py',
  'tests/test_public_api_snapshot.py',
  'tests/test_gravity_insight_agent_surface.py::GravityInsightAgentSurfaceTests::test_cli_all_pages_guard_and_exit_codes_are_stable',
  'tests/test_gravity_sdk.py::GravitySDKTests::test_segment_spec_sdk_and_plan_share_one_safe_execution_path',
  'tests/test_gravity_sdk.py::GravitySDKTests::test_agent_facade_discovers_then_runs_without_cli_argument_ceremony',
  'tests/test_gravity_plan.py::PlanValidationTests::test_dry_run_calls_validation_but_never_execution',
  'tests/test_gravity_plan.py::PlanExecutionTests::test_failure_isolated_sanitized_and_local_exit_wins',
  'tests/test_gravity_plan.py::PlanExecutionTests::test_all_pages_unknown_completeness_is_preserved_capability_gap',
  'tests/test_agent_catalog.py::AgentCatalogTests::test_existing_agent_protocol_is_unchanged',
  'tests/test_agent_catalog.py::AgentCatalogTests::test_unknown_category_and_selector_point_at_catalog_browse'
)
& ./.venv/Scripts/python.exe -m pytest -q $behavior
if ($LASTEXITCODE) { throw 'R17 Phase 1 behavior regression after checkpoint preconditions passed' }
```

### Phase 1 Rollback Checkpoint

The first four Phase 1 commands establish and exercise the complete Phase 1
tree. This command then requires one single-parent commit whose parent is exactly the
reviewed baseline, so every baseline-to-checkpoint change is in that commit.
It reverse-applies the complete binary diff in a temporary Git index and
requires the simulated result tree to equal the baseline tree exactly; the
real index and worktree are not changed.

```powershell
$expectedBranch = 'codex/r17-migration'
$baseline = '26a765a34e16b167093f5133ff2982a5d07d167a'
$actualBranch = (& git branch --show-current).Trim()
if ($actualBranch -ne $expectedBranch) { throw "Phase 1 rollback checkpoint not reached: branch mismatch; expected=$expectedBranch actual=$actualBranch" }
$dirty = @(& git status --porcelain --untracked-files=all)
if ($dirty.Count) { throw "Phase 1 rollback checkpoint not reached: clean tree required; changes=$dirty" }
$phase1Checkpoint = (& git rev-parse HEAD).Trim()
$parents = @(((& git show -s --format=%P $phase1Checkpoint).Trim() -split '\s+') | Where-Object { $_ })
if ($parents.Count -ne 1) { throw "Phase 1 rollback checkpoint not reached: commit must have exactly one parent; checkpoint=$phase1Checkpoint parents=$($parents -join ',')" }
$checkpointParent = $parents[0]
if ($checkpointParent -ne $baseline) { throw "Phase 1 rollback checkpoint not reached: parent must equal reviewed baseline; expected=$baseline actual=$checkpointParent" }
$rangeCount = [int]((& git rev-list --count "$baseline..$phase1Checkpoint").Trim())
if ($rangeCount -ne 1) { throw "Phase 1 rollback checkpoint not reached: baseline range must contain exactly one commit; count=$rangeCount" }
$message = (& git show -s --format=%B $phase1Checkpoint) -join "`n"
if ([regex]::Matches($message, '(?m)^R17-Checkpoint: phase-1\r?$').Count -ne 1) { throw 'Phase 1 rollback checkpoint not reached: requires one exact R17-Checkpoint: phase-1 trailer' }
if ([regex]::Matches($message, "(?m)^R17-Baseline: $baseline\r?$").Count -ne 1) { throw "Phase 1 rollback checkpoint not reached: requires one exact R17-Baseline: $baseline trailer" }
$rollbackDir = 'tmp/r17-acceptance'
New-Item -ItemType Directory -Force $rollbackDir | Out-Null
$rollbackPatch = "$rollbackDir/phase1-$phase1Checkpoint.rollback.patch"
& git diff --binary --full-index --no-renames --output=$rollbackPatch "$baseline..$phase1Checkpoint"
if ($LASTEXITCODE) { throw 'Phase 1 rollback patch generation failed' }
$temporaryIndex = [System.IO.Path]::GetFullPath("$rollbackDir/phase1-$phase1Checkpoint.index")
$previousIndex = $env:GIT_INDEX_FILE
try {
    Remove-Item -LiteralPath $temporaryIndex -Force -ErrorAction SilentlyContinue
    $env:GIT_INDEX_FILE = $temporaryIndex
    & git read-tree $phase1Checkpoint
    if ($LASTEXITCODE) { throw 'Phase 1 temporary index initialization failed' }
    & git apply --cached --reverse --check $rollbackPatch
    if ($LASTEXITCODE) { throw "Phase 1 reverse-apply check failed: $rollbackPatch" }
    & git apply --cached --reverse $rollbackPatch
    if ($LASTEXITCODE) { throw "Phase 1 reverse-apply simulation failed: $rollbackPatch" }
    $rolledBackTree = (& git write-tree).Trim()
    $baselineTree = (& git rev-parse "$baseline`^{tree}").Trim()
    if ($rolledBackTree -ne $baselineTree) { throw "Phase 1 rollback tree mismatch: expected=$baselineTree actual=$rolledBackTree" }
} finally {
    $env:GIT_INDEX_FILE = $previousIndex
    Remove-Item -LiteralPath $temporaryIndex -Force -ErrorAction SilentlyContinue
}
Write-Output "Phase 1 rollback checkpoint passed: baseline=$baseline; parent=$checkpointParent; checkpoint=$phase1Checkpoint; simulated_tree=$rolledBackTree"
```

### Phase 2 Rollback Checkpoints

Phase 2 is also exactly one commit. Its `R17-Phase-1` trailer binds the accepted
Phase 1 SHA; its only parent must equal that SHA, and the Phase 1 commit must in
turn have the reviewed baseline as its only parent. The helper below simulates
each rollback in a temporary index. The `phase-1` invocation proves the final
commit returns exactly to the Phase 1 tree. The `baseline` invocation proves
the required ordered rollback, first Phase 2 to Phase 1 and then Phase 1 to the
baseline; it rejects retaining Phase 2 while removing Phase 1.

```powershell
function Test-R17Phase2Rollback {
    param([Parameter(Mandatory)][ValidateSet('phase-1', 'baseline')][string]$Target)
    $expectedBranch = 'codex/r17-migration'
    $baseline = '26a765a34e16b167093f5133ff2982a5d07d167a'
    $actualBranch = (& git branch --show-current).Trim()
    if ($actualBranch -ne $expectedBranch) { throw "Phase 2 rollback checkpoint not reached: branch mismatch; expected=$expectedBranch actual=$actualBranch target=$Target" }
    $dirty = @(& git status --porcelain --untracked-files=all)
    if ($dirty.Count) { throw "Phase 2 rollback checkpoint not reached: clean tree required; target=$Target changes=$dirty" }
    $phase2Checkpoint = (& git rev-parse HEAD).Trim()
    $phase2Message = (& git show -s --format=%B $phase2Checkpoint) -join "`n"
    if ([regex]::Matches($phase2Message, '(?m)^R17-Checkpoint: phase-2\r?$').Count -ne 1) { throw 'Phase 2 rollback checkpoint not reached: requires one exact R17-Checkpoint: phase-2 trailer' }
    if ([regex]::Matches($phase2Message, "(?m)^R17-Baseline: $baseline\r?$").Count -ne 1) { throw "Phase 2 rollback checkpoint not reached: requires one exact R17-Baseline: $baseline trailer" }
    $phase1Trailer = [regex]::Matches($phase2Message, '(?m)^R17-Phase-1: ([0-9a-f]{40})\r?$')
    if ($phase1Trailer.Count -ne 1) { throw 'Phase 2 rollback checkpoint not reached: requires one exact R17-Phase-1: <40-hex-sha> trailer' }
    $phase1Checkpoint = $phase1Trailer[0].Groups[1].Value
    $phase2Parents = @(((& git show -s --format=%P $phase2Checkpoint).Trim() -split '\s+') | Where-Object { $_ })
    if ($phase2Parents.Count -ne 1 -or $phase2Parents[0] -ne $phase1Checkpoint) { throw "Phase 2 rollback checkpoint not reached: only parent must equal trailer-bound Phase 1; expected=$phase1Checkpoint actual=$($phase2Parents -join ',')" }
    $phase1Parents = @(((& git show -s --format=%P $phase1Checkpoint).Trim() -split '\s+') | Where-Object { $_ })
    if ($phase1Parents.Count -ne 1 -or $phase1Parents[0] -ne $baseline) { throw "Phase 2 rollback checkpoint not reached: Phase 1 only parent must equal reviewed baseline; expected=$baseline actual=$($phase1Parents -join ',')" }
    $phase1Message = (& git show -s --format=%B $phase1Checkpoint) -join "`n"
    if ([regex]::Matches($phase1Message, '(?m)^R17-Checkpoint: phase-1\r?$').Count -ne 1) { throw 'Phase 2 rollback checkpoint not reached: parent lacks one exact R17-Checkpoint: phase-1 trailer' }
    if ([regex]::Matches($phase1Message, "(?m)^R17-Baseline: $baseline\r?$").Count -ne 1) { throw "Phase 2 rollback checkpoint not reached: Phase 1 lacks one exact R17-Baseline: $baseline trailer" }
    $phase1Count = [int]((& git rev-list --count "$baseline..$phase1Checkpoint").Trim())
    $phase2Count = [int]((& git rev-list --count "$phase1Checkpoint..$phase2Checkpoint").Trim())
    $fullCount = [int]((& git rev-list --count "$baseline..$phase2Checkpoint").Trim())
    if ($phase1Count -ne 1 -or $phase2Count -ne 1 -or $fullCount -ne 2) { throw "Phase 2 rollback checkpoint not reached: chain must be exactly two serial commits; phase1_count=$phase1Count phase2_count=$phase2Count full_count=$fullCount" }
    $rollbackDir = 'tmp/r17-acceptance'
    New-Item -ItemType Directory -Force $rollbackDir | Out-Null
    $phase2Patch = "$rollbackDir/phase2-$phase2Checkpoint.rollback.patch"
    $phase1Patch = "$rollbackDir/phase1-$phase1Checkpoint.rollback.patch"
    & git diff --binary --full-index --no-renames --output=$phase2Patch "$phase1Checkpoint..$phase2Checkpoint"
    if ($LASTEXITCODE) { throw 'Phase 2 rollback patch generation failed' }
    if ($Target -eq 'baseline') {
        & git diff --binary --full-index --no-renames --output=$phase1Patch "$baseline..$phase1Checkpoint"
        if ($LASTEXITCODE) { throw 'Phase 1 rollback patch generation failed during full rollback validation' }
    }
    $temporaryIndex = [System.IO.Path]::GetFullPath("$rollbackDir/phase2-$phase2Checkpoint-$Target.index")
    $previousIndex = $env:GIT_INDEX_FILE
    try {
        Remove-Item -LiteralPath $temporaryIndex -Force -ErrorAction SilentlyContinue
        $env:GIT_INDEX_FILE = $temporaryIndex
        & git read-tree $phase2Checkpoint
        if ($LASTEXITCODE) { throw 'Phase 2 temporary index initialization failed' }
        & git apply --cached --reverse --check $phase2Patch
        if ($LASTEXITCODE) { throw "Phase 2 reverse-apply check failed: $phase2Patch" }
        & git apply --cached --reverse $phase2Patch
        if ($LASTEXITCODE) { throw "Phase 2 reverse-apply simulation failed: $phase2Patch" }
        $rolledBackTree = (& git write-tree).Trim()
        $phase1Tree = (& git rev-parse "$phase1Checkpoint`^{tree}").Trim()
        if ($rolledBackTree -ne $phase1Tree) { throw "Phase 2 to Phase 1 tree mismatch: expected=$phase1Tree actual=$rolledBackTree" }
        if ($Target -eq 'baseline') {
            & git apply --cached --reverse --check $phase1Patch
            if ($LASTEXITCODE) { throw "Full rollback Phase 1 reverse-apply check failed: $phase1Patch" }
            & git apply --cached --reverse $phase1Patch
            if ($LASTEXITCODE) { throw "Full rollback Phase 1 reverse-apply simulation failed: $phase1Patch" }
            $rolledBackTree = (& git write-tree).Trim()
            $baselineTree = (& git rev-parse "$baseline`^{tree}").Trim()
            if ($rolledBackTree -ne $baselineTree) { throw "Full rollback baseline tree mismatch: expected=$baselineTree actual=$rolledBackTree" }
        }
    } finally {
        $env:GIT_INDEX_FILE = $previousIndex
        Remove-Item -LiteralPath $temporaryIndex -Force -ErrorAction SilentlyContinue
    }
    Write-Output "Phase 2 rollback checkpoint passed: target=$Target; baseline=$baseline; phase1=$phase1Checkpoint; phase2=$phase2Checkpoint; simulated_tree=$rolledBackTree"
}

# Run these as two separate acceptance commands after loading the helper.
Test-R17Phase2Rollback -Target phase-1
Test-R17Phase2Rollback -Target baseline
```

### Structural Exit And Reviewed Owners

```powershell
$code = @'
import ast, json
from pathlib import Path
import gravity_sdk

root = Path('src/gravity_sdk')
agents = root / 'agents'
snapshot = json.loads(Path('tests/fixtures/public_api_exports.json').read_text(encoding='utf-8'))
actual = {
    'root_py': len(list(root.glob('*.py'))),
    'root_agent_py': len(list(root.glob('agent_*.py'))),
    'package_py': len(list(root.rglob('*.py'))),
    'agents_implementation_py': len([p for p in agents.glob('*.py') if p.name != '__init__.py']),
    'lazy_snapshot': len(snapshot),
    'runtime_exports': len(gravity_sdk._EXPORTS),
    'root_all': len(gravity_sdk.__all__),
}
expected = {'root_py': 495, 'root_agent_py': 1, 'package_py': 642, 'agents_implementation_py': 82, 'lazy_snapshot': 147, 'runtime_exports': 147, 'root_all': 148}
assert actual == expected, f'structural/public counts mismatch: expected={expected}, actual={actual}'
root_agent_files = sorted(p.name for p in root.glob('agent_*.py'))
assert root_agent_files == ['agent_runtime_contracts.py'], f'unexpected root agent files: {root_agent_files}'

paths = {path.stem: path for path in agents.glob('*.py') if path.name != '__init__.py'}
nodes = set(paths); edges = set()
dispositions = json.loads(Path('tests/fixtures/agent_module_reference_dispositions.json').read_text(encoding='utf-8'))
expected_nodes = {row['new_module'].removeprefix('gravity_sdk.agents.') for row in dispositions['scope']['one_to_one_moves']}
assert nodes == expected_nodes, f'agents module set differs from the 82 reviewed move rows: missing={sorted(expected_nodes - nodes)}, extra={sorted(nodes - expected_nodes)}'
for source, path in paths.items():
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'), filename=str(path))):
        targets = []
        if isinstance(node, ast.Import):
            targets = [alias.name.split('.')[2] for alias in node.names if alias.name.startswith('gravity_sdk.agents.') and len(alias.name.split('.')) > 2]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 1 and node.module:
                targets = [node.module.split('.')[0]]
            elif node.level == 1:
                targets = [alias.name for alias in node.names]
            elif node.level == 0 and node.module and node.module.startswith('gravity_sdk.agents.'):
                targets = [node.module.split('.')[2]]
        edges.update((source, target) for target in targets if target in nodes and target != source)
core = set('''analysis batch batch_questions batch_sources business_pulse capabilities catalog composite composite_inventory dashboard discovery_policy discovery_support export handoff host_catalog host_selection input_resolution intent_routing lexical_retrieval material_performance monetization_guard multidim operation_contract output product_inventory report_routing segment semantic_context semantic_derived sources sql_product_discovery table_lineage unavailable unavailable_analysis'''.split())
peripheral = nodes - core
graph_actual = {'implementation_modules': len(nodes), 'core': len(nodes & core), 'peripheral': len(peripheral), 'core_to_peripheral': sum(u in core and v in peripheral for u, v in edges), 'peripheral_to_core': sum(u in peripheral and v in core for u, v in edges)}
graph_expected = {'implementation_modules': 82, 'core': 34, 'peripheral': 48, 'core_to_peripheral': 153, 'peripheral_to_core': 0}
assert graph_actual == graph_expected, f'physical cohort graph mismatch: expected={graph_expected}, actual={graph_actual}'

owner_ledger = json.loads(Path('tests/fixtures/public_api_owner_migrations.json').read_text(encoding='utf-8'))
expected_owners = [
    {'symbol': 'assess_host_product_selection', 'from': '.agent_host_selection', 'to': '.agents.host_selection'},
    {'symbol': 'capabilities_many', 'from': '.agent_batch', 'to': '.agents.batch'},
    {'symbol': 'compile_host_product_selection', 'from': '.agent_host_selection', 'to': '.agents.host_selection'},
    {'symbol': 'host_product_catalog', 'from': '.agent_host_catalog', 'to': '.agents.host_catalog'},
    {'symbol': 'host_product_selection_schema', 'from': '.agent_host_catalog', 'to': '.agents.host_catalog'},
    {'symbol': 'resolve_host_product_selection', 'from': '.agent_host_selection', 'to': '.agents.host_selection'},
]
assert sorted(owner_ledger, key=lambda row: row['symbol']) == expected_owners, f'owner migration ledger must contain exactly the six reviewed rows: {owner_ledger}'
index = json.loads(Path('specs/agent-runtime/index.json').read_text(encoding='utf-8'))
for path in ('src/gravity_sdk/agents/capabilities.py', 'src/gravity_sdk/agents/composite.py', 'src/gravity_sdk/agents/handoff.py'):
    assert path in index['shared_spine'], f'migrated shared-spine path missing: {path}'
for path in ('src/gravity_sdk/agent_capabilities.py', 'src/gravity_sdk/agent_composite.py', 'src/gravity_sdk/agent_handoff.py'):
    assert path not in index['shared_spine'], f'old shared-spine path remains: {path}'
print(json.dumps({'counts': actual, 'graph': graph_actual, 'owner_migrations': len(owner_ledger)}, sort_keys=True))
'@
& ./.venv/Scripts/python.exe -c $code
if ($LASTEXITCODE) { throw 'R17 structural exit or reviewed-owner assertion failed' }
```

### Focused Migration And Concept Deletion

```powershell
$focused = @(
  'tests/test_agent_module_reference_dispositions.py::AgentModuleReferenceDispositionTests::test_current_ledger_satisfies_the_machine_contract',
  'tests/test_agent_module_reference_dispositions.py::AgentModuleReferenceDispositionTests::test_index_and_specification_state_agree',
  'tests/test_agent_module_reference_dispositions.py::AgentModuleReferenceDispositionTests::test_reviewed_fixture_sha256_is_bound',
  'tests/test_agent_module_reference_dispositions.py::AgentModuleReferenceDispositionTests::test_validator_rejects_required_regressions',
  'tests/test_agent_module_migration_characterization.py::AgentModuleMigrationCharacterizationTests::test_agent_deep_paths_are_explicitly_public_or_internal',
  'tests/test_agent_module_migration_characterization.py::AgentModuleMigrationCharacterizationTests::test_eager_detector_scopes_complete_graph_cycles_to_agent_modules',
  'tests/test_agent_module_migration_characterization.py::AgentModuleMigrationCharacterizationTests::test_eager_module_import_graph_has_no_migration_related_component',
  'tests/test_agent_module_migration_characterization.py::AgentModuleMigrationCharacterizationTests::test_root_export_module_collision_guard_detects_an_injected_name',
  'tests/test_agent_module_migration_characterization.py::AgentModuleMigrationCharacterizationTests::test_root_export_module_collision_set_cannot_grow',
  'tests/test_agent_module_migration_characterization.py::AgentModuleMigrationCharacterizationTests::test_root_exports_are_lazy_cached_and_owned_in_an_isolated_process',
  'tests/test_agent_module_migration_characterization.py::AgentModuleMigrationCharacterizationTests::test_shadowed_root_export_resolution_fails_closed_on_module_value',
  'tests/test_agent_module_migration_characterization.py::AgentModuleMigrationCharacterizationTests::test_shadowed_root_exports_are_order_independent_in_isolated_processes',
  'tests/test_public_api_snapshot.py::PublicApiSnapshotTests::test_every_snapshot_symbol_is_reachable_from_the_root_package',
  'tests/test_public_api_snapshot.py::PublicApiSnapshotTests::test_lazy_root_exports_match_public_api_snapshot',
  'tests/test_public_api_snapshot.py::PublicApiSnapshotTests::test_owner_migration_ledger_changes_only_the_declared_owner',
  'tests/test_agent_concept_deletions.py::AgentConceptDeletionTests::test_compact_pagination_has_single_source_consumer',
  'tests/test_agent_concept_deletions.py::AgentConceptDeletionTests::test_metadata_inventory_wrapper_has_no_callers',
  'tests/test_agent_concept_deletions.py::AgentConceptDeletionTests::test_compact_pagination_output_contract_is_locked'
)
& ./.venv/Scripts/python.exe -m pytest -q $focused
if ($LASTEXITCODE) { throw 'R17 focused migration/concept-deletion gate failed' }
```

### Installed Wheel

```powershell
& ./.venv/Scripts/python.exe -m pytest -q 'tests/test_installed_wheel.py::InstalledWheelTests::test_built_wheel_contains_and_imports_every_source_module_and_resource'
if ($LASTEXITCODE) { throw 'R17 isolated installed-wheel gate failed' }
```

### Canonical Consumer Revision And Census

The canonical consumer census is bound to the program's recorded consumer
commit, `work-dashboard@d1915a18278fca8823782a7d13e691a6d5702ad2`.
This makes no ancestry claim about whichever branch the local consumer checkout
currently has; the command reads the exact Git object. Run the same census at
both serial checkpoints.

```powershell
$consumerRoot = Resolve-Path '../work-dashboard'
$consumerRevision = 'd1915a18278fca8823782a7d13e691a6d5702ad2'
& git -C $consumerRoot cat-file -e "$consumerRevision`^{commit}"
if ($LASTEXITCODE) { throw "canonical consumer commit is unavailable: $consumerRevision" }
$legacyPattern = 'gravity_sdk\.agent_[[:alnum:]_]+|src/gravity_sdk/agent_(capabilities|composite|handoff)\.py'
$legacyHits = & git -C $consumerRoot grep -n -E $legacyPattern $consumerRevision -- '*.py' '*.md' '*.json' '*.toml' '*.yaml' '*.yml'
$grepExit = $LASTEXITCODE
if ($grepExit -eq 0) { $legacyHits; throw "canonical consumer still references an R17 legacy path at $consumerRevision" }
if ($grepExit -ne 1) { throw "canonical consumer census failed to execute: git grep exit $grepExit" }
Write-Output "canonical consumer census passed: $consumerRevision; legacy_hits=0"
```

### Complete Collectors

```powershell
& ./.venv/Scripts/python.exe -m pytest -q
if ($LASTEXITCODE) { throw 'complete pytest collector failed' }
```

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s tests
if ($LASTEXITCODE) { throw 'complete unittest collector failed' }
```

### Compiler And Quality

```powershell
& ./.venv/Scripts/python.exe -m gravity_sdk.compiler check
if ($LASTEXITCODE) { throw 'compiler check failed' }
```

```powershell
& ./.venv/Scripts/python.exe -m gravity_sdk.quality check
if ($LASTEXITCODE) { throw 'quality check failed' }
```

### Development Usability And Security

```powershell
$usabilityOutput = 'tmp/r17-acceptance/usability'
& ./.venv/Scripts/python.exe scripts/agent_usability_eval.py run --split development --output-dir $usabilityOutput
if ($LASTEXITCODE) { throw 'development usability evaluation failed' }
```

```powershell
& ./.venv/Scripts/python.exe -m pytest -q tests/test_consumer_output_safety.py
if ($LASTEXITCODE) { throw 'consumer-output security tests failed' }
$result = Get-ChildItem 'tmp/r17-acceptance/usability' -Filter 'result-development-*.json' | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if ($null -eq $result) { throw 'security assertion found no development usability result' }
$code = @'
import json, sys
path = sys.argv[1]
result = json.load(open(path, encoding='utf-8'))
security = result.get('layers', {}).get('security_compliance', {})
assert result.get('security_hard_gate_passed') is True, f'security hard gate did not pass: {path}'
assert security.get('violation_count') == 0, f"security violations must be zero: {security.get('violation_count')}"
assert result.get('layers', {}).get('cost', {}).get('production_http_requests') == 0, 'development evaluation made a production HTTP request'
print(f"security gate passed: violations=0; production_http_requests=0; result={path}")
'@
& ./.venv/Scripts/python.exe -c $code $result.FullName
if ($LASTEXITCODE) { throw 'development security assertion failed' }
```

### CLI Help

```powershell
& ./.venv/Scripts/python.exe -m gravity_sdk --help
if ($LASTEXITCODE) { throw 'gravity CLI help failed' }
```

### Canonical Source Errata Binding

```powershell
& ./.venv/Scripts/python.exe scripts/validate_r17_canonical_source_errata.py
if ($LASTEXITCODE) { throw 'canonical source errata binding assertion failed' }
```

### Diff Integrity

```powershell
& git diff --check
if ($LASTEXITCODE) { throw 'git diff --check failed' }
```

## Final Acceptance And Exit

R17 exits only at the final Phase 2 checkpoint on the single implementation
branch when:

- at immutable delivery baseline
  `125bb84cbb98a575a2ef3c4a577f174027bc908d`, root Python files equalled 495
  and the complete package had 642 Python files; these are delivery evidence,
  not current-tree limits;
- root `agent_*.py` equals the sole retained `agent_runtime_contracts.py`, and
  `agents/` has exactly 82 implementation modules;
- the physical cohort graph has 34 core and 48 peripheral modules, 153 unique
  core-to-peripheral edges, and zero reverse edges; the physical graph check does
  not re-select membership, and every `agents/` module maps to the reviewed
  manifest;
- `agent_pagination.py` and `metadata_inventory()` are absent;
  `compact_pagination` behavior is preserved in `pagination_completeness.py`;
  `metadata_inventory_state()` failure ordering is preserved;
- `gravity_sdk.__all__ == 148`; fixture/runtime owners each equal 147; the
  reviewed owner ledger contains exactly six accepted changes;
- no removed deep-path shim, alias, hook, duplicate, second facade, or package
  initialization side effect exists; R17 adds no facade back-edge, while the
  five acyclic pre-migration edges enumerated in the Machine Contract are
  intentionally retained and locked by the bounded module/symbol-set test;
- every candidate in the rebound audit denominator has a reviewed disposition
  and there is no unresolved consumer; isolated-wheel and canonical-consumer
  censuses match their ledgers;
- shared-spine paths point to `agents/capabilities.py`,
  `agents/composite.py`, and `agents/handoff.py`, while `plan_adapters.py` and
  `__main__.py` remain in place; and
- all five Phase 1 commands passed on the trailer-bound Phase 1 checkpoint;
  both Phase 2 rollback targets and every command from `Structural Exit And
  Reviewed Owners` onward pass on the final checkpoint without substitution.

Technical debt #11 is closed after the delivered `fixed_dev` migration and this
scaffolding retirement: 82 exact physical moves, two concept deletions, no
legacy/v4 classifier or signed-summary dependency, and the preserved migration
risk gates. Closure does not claim the complete Agent domain or zero facade
dependencies. Only one historical line remains in the debt ledger; #2/#3/#7
are unchanged. `main` remains frozen until the complete program is green and
the user gives new explicit approval.

## Canonical Owners

Long-lived owners are the `gravity_sdk/agents/` boundary, stable facade and
lazy map, `pagination_completeness.py`, retained Runtime contracts module,
public API and owner fixtures, boundary and wheel gates, Requirement Index
shared spine, canonical consumer evidence, and technical debt #11. This
Requirement is delivery governance, not a second runtime contract.
