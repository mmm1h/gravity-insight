# R17 Compact Agent Interaction Package Migration

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.2` via `directive.json`; canonical architecture source is v9.2 |
| Status | `specified`; M0 characterization and dynamic-audit classification are satisfied under standing delegation with owner review pending; independent ready review remains unresolved |
| Track | Structural migration / technical debt #11 |
| Requirement dependencies | None |
| Parallel group | `structural-migration` |
| Shared-spine integration | Required and serialized |
| Delivery mode | `leaf`; one implementation branch/worktree with two serial commit and rollback checkpoints |
| Measurement baseline | `codex/gov-staged-epic@aa46ddf3343d8fb8ea0162b7806403527a2d79d9` |
| Implementation baseline | `dev@823d69822ab09829b2bab47d8fc70ce6eb710a7b` |
| M0 evidence candidate | `codex/m0-characterization@088d1606127439943cab0b79c8cdbdf516af4839` |
| Implementation Issue | `none`; internal structural debt must not receive a self-created GitHub Issue under `docs/maintainers/issues.md` |
| Implementation branch / worktree | `codex/r17-migration` / `D:/git-pjt/gravity-sdk-r17-migration` |
| Production requests | `0`; structural migration only |
| Main integration | Frozen; adding R17 extends `all_index_requirements_fixed_dev` |

## Outcome

Create a minimal `gravity_sdk/agents/` package by migrating the compact Agent
interaction responsibility set. An independent inventory seeded from
responsibilities rather than filenames, paths, or prefixes retained all 81
previous moves, produced no difference against the ledger move set, and added the internal
`gravity_sdk.relative_date_agent` owner. R17 therefore moves 82 modules one for
one, consolidates the single-caller `agent_pagination` helper into the canonical
`pagination_completeness.py` owner and deletes that module, and leaves the
unreachable `agent_runtime_contracts.py` infrastructure module at the root.

The checked-in independent inventory supports this adjusted 82-move ownership
boundary, including the continued exclusion of `agent_runtime_contracts` and
`find.py`. It does not prove a complete Agent domain or fully pass the canonical
counter-path-dependence test. Under its now-explicit definitions, the facade
SCC, unrestricted facade closure, import-graph minimum-conductance cut, and
fixed-baseline co-change component contain 40, 311, 496, and 626 modules and do
not converge. These independently redone observations differ from the prior
unrecorded 40/308/495/549 run because import alias resolution, the conductance
sweep, and co-change history scope are now defined and locked; no threshold was
tuned to reproduce 81 or 84. R17 remains a bounded structural migration whose
exact ledger, preservation gates, and independent ready review must still be
accepted before implementation.

The root package falls from 578 to 495 Python files. The complete package stays
at 642 Python files because deleting `agent_pagination.py` offsets the new
`agents/__init__.py`. Runtime responses, request volume, privacy, execution
ownership, supported capability, and the actual 148-name `gravity_sdk.__all__`
surface do not change. Removed deep module paths receive no compatibility shim.

R17 is one leaf, one branch/worktree, and one status. Its two implementation
phases are serial commit and rollback checkpoints, not branches or indexed
milestones. A phase cannot independently reach `fixed_dev`, close technical
debt #11, or satisfy R17.

## Ready Prerequisites

`index.json.ready_prerequisites` is the machine authority.

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
   all 909 current tracked sites have dispositions, with zero unclassified sites
   and zero blockers. This is the original 903-site denominator plus six sites: five from the
   expanded 82-module scope and one from merging the anchor and inventory work. Unknown module names and cross-function loaders remain
   real blockers rather than exclusions.
3. **Not satisfied.** An independent reviewer must accept the scope,
   measurement definitions, proposed owner changes, two explicit concept
   deletions, and exact acceptance commands and return a `ready` verdict. This
   specification cannot satisfy that prerequisite itself.

The historical candidate audit also reports 83/83 old-path smoke imports
successful and zero naming collisions. Those facts do not classify any source
site and do not repair the baseline mismatch above.

Machine state shared by this Requirement and `index.md`: `status=specified`;
`dynamic_import_audit_classification.satisfied=true`;
`schema=gravity.agent-module-reference-dispositions.v2`; `candidate_sites=238`;
`classified_sites=238`; `unclassified_sites=0`; `blocking_sites=0`.

`m0_bound_implementation_baseline=113176a381b6d232e95a112d78d1d2f4bc5ac024`;
`m0_bound_artifact_sha256={"tests/agent_migration_characterization.py":"97b3c71842b3904213ec24667ae09f4c821df0384f6667847e3c03f6c9d9d640","tests/fixtures/public_api_exports.json":"d6aa4c9bb939f6e56428192ad432300fe985618fae69492cc9e12820dd43c053","tests/fixtures/public_api_owner_migrations.json":"37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570","tests/test_agent_module_migration_characterization.py":"6e5c0530fbc7b869d896d26cb01ec76649f4bf2a48adeeb0b9968395f4af8ffc","tests/test_installed_wheel.py":"bd8d9cf332354147fd4e11f87ac7d09b48ac7dcf1d4eae164900b0baf7bed117"}`;
`ledger_sha256=9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20`.
`live_checkpoint_sha256=090a2cd212f6a4d01531ec4e4e16238215dff7710e9ebfec7f1f0af0c7fbb2d5`;
`live_checkpoint_tracked_sites=909`.

The required cross-file state gate is
`tests/test_agent_module_reference_dispositions.py::AgentModuleReferenceDispositionTests::test_index_and_specification_state_agree`.
It must load both JSON files as UTF-8 and assert that the R17 Index entry, this
Requirement, and `index.md` all report `specified`, schema v2, 238 candidate and
classified sites, zero unclassified and blocking sites, and a satisfied
dynamic-audit prerequisite; it must also reject any previous-generation site
count or ledger-schema claim in the three R17 state representations.

## Responsibility Inventory And Target Naming Rule

The exact independent membership is the 84 included rows in the signed JSON
block below: the public facade, the 82 one-to-one move owners, and the
pagination consolidation owner. The same artifact records eight rejected
semantic candidates, including the retained
Runtime contracts owner and the independent Find surface. It parses all 642
package modules, locates the facade from its protocol/command/response shape,
and applies docstring responsibility declarations plus direct-consumer
ownership without using a filename, path, or prefix to seed candidates. Only
after classification does it compare the result with the R17 migration ledger.

The artifact schema is
`gravity.r17-independent-responsibility-inventory.v1`; its payload SHA-256 is
`2b2ef88778a029b1ee6bee5bedd664af9058e971d09f80bc53f205848b698381`,
method SHA-256 is
`7e61ac801f39ca94cfc1e970dd58e777c84f88fddbf80c4d8712ecb3cc176cd5`,
member-list SHA-256 is
`1b15fdfcebfa086dc6683eacbab3262f2f224ffe80403c5a0e1ccfce8a085c5d`,
and source-tree SHA-256 is
`d690cf49e61b5c70b0a6bfd1f23be69fbf5795711e383812f7502ea103620b47`.
`tests/test_agent_module_reference_dispositions.py::R17ResponsibilityInventoryTests`
recomputes and locks the source, rows, digests, boundary cases, graph
observations, R17 comparison, and an injected drift failure.

The inventory retained every prior move and added `relative_date_agent`, whose
only source consumer is `agent_handoff`, whose only public symbol is
`fill_agent_relative_dates`, and which is not a root lazy public owner.

Target names apply one rule to all 82 moves: after placing a compact Agent
interaction owner under `gravity_sdk.agents`, remove exactly one redundant
`agent` boundary token adjacent to the responsibility name. A leading
`agent_` becomes no prefix (`agent_sources` -> `agents.sources`); a trailing
`_agent` becomes no suffix (`relative_date_agent` -> `agents.relative_date`).
The target basename must not collide, including case-insensitively, with any
other move target or with an unrelated existing root module. There is no
existing `gravity_sdk.relative_date` or `gravity_sdk.agents.relative_date`
module at the bound baseline.

The original 83-file `agent_*.py` graph remains supporting evidence rather than
the selector. For each prefix candidate `m`, `d(m)` is the shortest path from
`gravity_sdk.agent` through prefix candidates. It reproduces 82 reachable
members: 81 moves plus pagination, while `agent_runtime_contracts` remains
unreachable with 0 compact-cohort and 55 external direct consumers. The
independent inventory separately reproduces that exclusion: its direct
consumers belong to broader Skill, Context, Capability, Receipt, Artifact,
Journey, Operator/Model, and SQL Explorer Runtime layers, with zero compact
Agent-domain direct consumers. `find.py` also remains out because its own
`gravity.find.v1` and CLI surfaces plus mixed Agent/CLI/SQL consumers make the
coupling bidirectional rather than Agent-owned.

The legacy ledger columns below retain `A`, unique direct inbound sources from
the prefix candidates plus facade, `X`, other `src/gravity_sdk` sources, and
`d`. They are evidence, not thresholds, and cover the original prefix cohort;
the separately inventoried `relative_date_agent` row follows the table.

### Baseline Classification Ledger

`move` means one-for-one package migration. `consolidate/delete` is inside the
selected cohort but is not a migrated module. `exclude` means excluded from
this migration because `d` is absent; it does not prove a final domain owner.
`agent_runtime_contracts` is not special-cased by the rule.

| Module | A | X | A:X | d | R17 action |
| --- | ---: | ---: | ---: | ---: | --- |
| `agent_advertiser_profile` | 5 | 1 | 5:1 | 2 | move |
| `agent_analysis` | 3 | 0 | 3:0 | 2 | move |
| `agent_analysis_default_dictionary` | 5 | 0 | 5:0 | 2 | move |
| `agent_analysis_task` | 3 | 0 | 3:0 | 2 | move |
| `agent_app_catalog` | 5 | 0 | 5:0 | 1 | move |
| `agent_app_public_info` | 5 | 0 | 5:0 | 2 | move |
| `agent_attribution_performance` | 5 | 0 | 5:0 | 2 | move |
| `agent_attribution_user_detail` | 3 | 0 | 3:0 | 2 | move |
| `agent_batch` | 1 | 2 | 1:2 | 2 | move |
| `agent_batch_questions` | 1 | 0 | 1:0 | 3 | move |
| `agent_batch_sources` | 5 | 0 | 5:0 | 1 | move |
| `agent_bilibili_account_performance` | 7 | 1 | 7:1 | 2 | move |
| `agent_business_pulse` | 5 | 0 | 5:0 | 2 | move |
| `agent_call_bound` | 1 | 0 | 1:0 | 2 | move |
| `agent_caller_language` | 3 | 0 | 3:0 | 2 | move |
| `agent_capabilities` | 11 | 0 | 11:0 | 1 | move |
| `agent_catalog` | 1 | 1 | 1:1 | 2 | move |
| `agent_catalog_parity` | 1 | 0 | 1:0 | 3 | move |
| `agent_catalog_refresh` | 1 | 0 | 1:0 | 2 | move |
| `agent_client` | 2 | 1 | 2:1 | 1 | move |
| `agent_company_usage` | 4 | 1 | 4:1 | 2 | move |
| `agent_composite` | 1 | 0 | 1:0 | 2 | move |
| `agent_composite_inventory` | 1 | 0 | 1:0 | 2 | move |
| `agent_custom_audience` | 4 | 1 | 4:1 | 2 | move |
| `agent_custom_metric` | 3 | 0 | 3:0 | 3 | move |
| `agent_dashboard` | 4 | 0 | 4:0 | 2 | move |
| `agent_derived_metrics` | 4 | 0 | 4:0 | 2 | move |
| `agent_discovery_policy` | 6 | 0 | 6:0 | 1 | move |
| `agent_discovery_support` | 3 | 1 | 3:1 | 1 | move |
| `agent_export` | 9 | 0 | 9:0 | 1 | move |
| `agent_fixed_snapshots` | 1 | 0 | 1:0 | 3 | move |
| `agent_gap` | 6 | 0 | 6:0 | 3 | move |
| `agent_handoff` | 6 | 0 | 6:0 | 1 | move |
| `agent_host_catalog` | 4 | 0 | 4:0 | 2 | move |
| `agent_host_selection` | 2 | 0 | 2:0 | 1 | move |
| `agent_input_catalogs` | 1 | 0 | 1:0 | 2 | move |
| `agent_input_resolution` | 1 | 1 | 1:1 | 1 | move |
| `agent_intent_routing` | 11 | 0 | 11:0 | 2 | move |
| `agent_intent_text` | 44 | 1 | 44:1 | 2 | move |
| `agent_kanban_mutation` | 3 | 0 | 3:0 | 3 | move |
| `agent_lexical_rescue` | 1 | 0 | 1:0 | 2 | move |
| `agent_lexical_retrieval` | 2 | 0 | 2:0 | 1 | move |
| `agent_material_asset` | 5 | 0 | 5:0 | 2 | move |
| `agent_material_performance` | 4 | 0 | 4:0 | 2 | move |
| `agent_metadata_onboarding` | 2 | 0 | 2:0 | 3 | move |
| `agent_metadata_search` | 3 | 0 | 3:0 | 2 | move |
| `agent_metadata_template` | 3 | 0 | 3:0 | 3 | move |
| `agent_monetization_aggregate` | 5 | 0 | 5:0 | 2 | move |
| `agent_monetization_guard` | 6 | 1 | 6:1 | 1 | move |
| `agent_multidim` | 5 | 0 | 5:0 | 2 | move |
| `agent_mutation_cards` | 1 | 0 | 1:0 | 2 | move |
| `agent_operation_contract` | 2 | 0 | 2:0 | 2 | move |
| `agent_order_directory` | 7 | 0 | 7:0 | 2 | move |
| `agent_order_trace` | 6 | 0 | 6:0 | 2 | move |
| `agent_output` | 1 | 0 | 1:0 | 1 | move |
| `agent_pagination` | 1 | 0 | 1:0 | 2 | consolidate/delete |
| `agent_product_inventory` | 3 | 1 | 3:1 | 2 | move |
| `agent_promotion_performance` | 6 | 0 | 6:0 | 2 | move |
| `agent_realtime_event` | 3 | 0 | 3:0 | 3 | move |
| `agent_realtime_event_catalog` | 5 | 0 | 5:0 | 2 | move |
| `agent_report_directory` | 3 | 1 | 3:1 | 2 | move |
| `agent_report_mutation` | 3 | 0 | 3:0 | 3 | move |
| `agent_report_routing` | 2 | 0 | 2:0 | 2 | move |
| `agent_runtime_contracts` | 0 | 55 | 0:55 | - | exclude |
| `agent_saved_analysis` | 3 | 0 | 3:0 | 2 | move |
| `agent_saved_analysis_mutation` | 3 | 0 | 3:0 | 3 | move |
| `agent_segment` | 5 | 0 | 5:0 | 2 | move |
| `agent_segment_members` | 4 | 0 | 4:0 | 2 | move |
| `agent_segment_snapshot` | 4 | 0 | 4:0 | 2 | move |
| `agent_semantic_compose` | 3 | 0 | 3:0 | 2 | move |
| `agent_semantic_context` | 4 | 0 | 4:0 | 1 | move |
| `agent_semantic_derived` | 1 | 0 | 1:0 | 2 | move |
| `agent_sources` | 8 | 1 | 8:1 | 1 | move |
| `agent_sql_product_discovery` | 1 | 0 | 1:0 | 2 | move |
| `agent_sql_product_gap` | 3 | 0 | 3:0 | 2 | move |
| `agent_table_lineage` | 5 | 0 | 5:0 | 2 | move |
| `agent_title_package` | 5 | 1 | 5:1 | 2 | move |
| `agent_unavailable` | 6 | 0 | 6:0 | 2 | move |
| `agent_unavailable_analysis` | 1 | 0 | 1:0 | 3 | move |
| `agent_unavailable_promotion` | 1 | 0 | 1:0 | 3 | move |
| `agent_unavailable_report` | 1 | 0 | 1:0 | 3 | move |
| `agent_user_journey` | 4 | 0 | 4:0 | 2 | move |
| `agent_vocabulary` | 3 | 1 | 3:1 | 2 | move |

The independent inventory adds `relative_date_agent` as a move with one direct
compact-Agent source consumer (`agent_handoff`) and zero other source consumers;
its target is `gravity_sdk.agents.relative_date`.

The ledger contains 82 `move`, one `consolidate/delete`, and one `exclude`
decision. The original facade-reachable prefix cohort still has 82 modules: 81
moves plus pagination. Adding the responsibility-inventoried relative-date
owner yields 341 internal facade/scope edges. The 82 move rows have 335
scope/facade inbound edges and 17 scope-external inbound edges. Those 17
consumer edges change target path but not ownership; the excluded contracts
module instead has 0 compact-Agent and 55 broader-Runtime inbound consumers.
This supports the bounded 82-move scope but is not proof of a complete domain.

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
such caller returns R17 to `specified` instead of gaining a shim.

These are the only consolidation/deletion actions. The remaining 48 peripheral
modules move one for one; no recognizer is merged or generalized into a
data-driven registry.

## Excluded Infrastructure

`agent_runtime_contracts.py` stays at
`src/gravity_sdk/agent_runtime_contracts.py` as R17's terminal location. It is
not copied, aliased, or re-exported from `agents/`. Its prefix and possible
future ownership under a Runtime/contracts layer are separate boundary
questions with no approved target. A rename or move requires a separate
structural decision covering its 55 non-Agent consumers.

## Internal Implementation Plan

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

### Boundary Classifier And Edges

This is the normative measurement definition. It prints the summary followed
by all 83 `module A X d` rows.

```powershell
$code = @'
import ast, json
from collections import deque
from pathlib import Path
root=Path('src/gravity_sdk'); inventory={}; info={}
for path in sorted(root.rglob('*.py')):
    parts=list(path.relative_to(root).with_suffix('').parts); package=parts[-1]=='__init__'
    if package: parts.pop()
    name='gravity_sdk'+(('.'+'.'.join(parts)) if parts else '')
    inventory[name]=path; info[path]=(name,package)
modules=set(inventory)
owners={name:value[0].lstrip('.') for name,value in json.loads(Path('tests/fixtures/public_api_exports.json').read_text(encoding='utf-8')).items()}
def existing(name):
    parts=name.split('.')
    for size in range(len(parts),0,-1):
        candidate='.'.join(parts[:size])
        if candidate in modules: return candidate
    return None
def base(source,package,level,module):
    if level==0: return module or ''
    parts=(source if package else source.rpartition('.')[0]).split('.')
    if level>1: parts=parts[:-(level-1)]
    if module: parts.extend(module.split('.'))
    return '.'.join(parts)
edges=set()
for path,(source,package) in info.items():
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'),filename=str(path))):
        if isinstance(node,ast.Import):
            for alias in node.names:
                target=existing(alias.name)
                if target and target!=source: edges.add((source,target))
        elif isinstance(node,ast.ImportFrom):
            resolved=base(source,package,node.level,node.module)
            if node.module:
                target=existing(resolved)
                if target and target!=source: edges.add((source,target))
            else:
                for alias in node.names:
                    target=existing(resolved+'.'+alias.name)
                    if not target and resolved=='gravity_sdk' and alias.name in owners:
                        target=existing('gravity_sdk.'+owners[alias.name])
                    if target and target!=source: edges.add((source,target))
candidates={'gravity_sdk.'+path.stem for path in root.glob('agent_*.py')}
facade='gravity_sdk.agent'; allowed=candidates|{facade}
adj={source:{target for left,target in edges if left==source and target in candidates} for source in allowed}
distance={facade:0}; queue=deque([facade])
while queue:
    source=queue.popleft()
    for target in adj[source]:
        if target not in distance:
            distance[target]=distance[source]+1; queue.append(target)
selected=set(distance)-{facade}; excluded=candidates-selected; cohesive=selected|{facade}
core={'gravity_sdk.'+name for name in '''agent_analysis agent_batch agent_batch_questions agent_batch_sources agent_business_pulse agent_capabilities agent_catalog agent_composite agent_composite_inventory agent_dashboard agent_discovery_policy agent_discovery_support agent_export agent_handoff agent_host_catalog agent_host_selection agent_input_resolution agent_intent_routing agent_lexical_retrieval agent_material_performance agent_monetization_guard agent_multidim agent_operation_contract agent_output agent_product_inventory agent_report_routing agent_segment agent_semantic_context agent_semantic_derived agent_sources agent_sql_product_discovery agent_table_lineage agent_unavailable agent_unavailable_analysis'''.split()}
pagination={'gravity_sdk.agent_pagination'}; peripheral=selected-core; moved=selected-pagination
print(json.dumps({'candidates':len(candidates),'selected':len(selected),'excluded':sorted(excluded),'cohort_internal_edges':sum(u in cohesive and v in cohesive for u,v in edges),'moved':len(moved),'core':len(core),'peripheral_cohort':len(peripheral),'moved_peripheral':len(peripheral-pagination),'core_to_peripheral':sum(u in core and v in peripheral for u,v in edges),'peripheral_to_core':sum(u in peripheral and v in core for u,v in edges),'core_to_moved_peripheral':sum(u in core and v in peripheral-pagination for u,v in edges),'moved_peripheral_to_core':sum(u in peripheral-pagination and v in core for u,v in edges)},sort_keys=True))
for target in sorted(candidates):
    agent_in=sum(source in allowed for source,value in edges if value==target)
    external_in=sum(source not in allowed for source,value in edges if value==target)
    print(target.removeprefix('gravity_sdk.'),agent_in,external_in,distance.get(target))
'@
& ./.venv/Scripts/python.exe -c $code
```

Measured summary: `candidates=83`, `selected=82`, `cohort_internal_edges=340`,
`excluded=["gravity_sdk.agent_runtime_contracts"]`, `moved=81`, `core=34`,
`peripheral_cohort=48`, `moved_peripheral=47`,
`core_to_peripheral=153`, `peripheral_to_core=0`,
`core_to_moved_peripheral=152`, `moved_peripheral_to_core=0`.

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

| Metric | Baseline | Final exit |
| --- | ---: | ---: |
| Root Python files | 578 | 495 |
| Root `agent_*.py` | 83 | 1 |
| Complete-package Python files | 642 | 642 |
| `agents/` implementation modules | 0 | 82 |
| Lazy fixture / runtime owners | 147 / 147 | 147 / 147 |
| Root `__all__` | 148 | 148 |

The sole final root `agent_*.py` must be `agent_runtime_contracts.py`.

Exactly six lazy owners point to the move set. Proposed changes remain the two
host catalog/selection schema names to `.agents.host_catalog`, the three host
selection functions to `.agents.host_selection`, and `capabilities_many` to
`.agents.batch`. They remain proposals until independent ready review.

### Concept-Deletion Census

```powershell
rg -n "compact_pagination|agent_pagination" src/gravity_sdk tests scripts
rg -n "metadata_inventory" src/gravity_sdk tests scripts
```

The first command finds one definition/export and exactly one import plus one
call in `agent_sources.py`. The second finds no import or call of
`agent_batch_sources.metadata_inventory()`; other hits are its definition,
`metadata_inventory_state`, `_metadata_inventory`, or dataclass-field access.
Before `ready`, independent review must bind AST-based test IDs that distinguish
the wrapper from same-spelled fields; these text commands are census evidence,
not approval.

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

## Write Scope

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
- Execute the 13 governance-document rewrites and one source selector-data
  rewrite the disposition ledger records, all at the core checkpoint because
  all of them name the three agent spine files: three in `AGENTS.md`, four in
  `specs/agent-runtime/architecture-source.md`, three in
  `specs/agent-runtime/index.json`, three in `specs/agent-runtime/index.md`,
  and the single `_EXPORTS` selector-data rewrite in
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
- No R17 state transition, implementation authorization, approval claim, or
  closure of technical debt #11 from this `specified` document.

## Machine Contract

- The 82 `move` rows map one for one; `agent_pagination` is deleted after
  consolidation; `agent_runtime_contracts.py` remains at its root path;
  `gravity_sdk.agent` remains the stable facade.
- `gravity_sdk.agents.__init__` imports no business module and exposes no
  parallel facade. Internal modules do not import `gravity_sdk` or
  `gravity_sdk.agent` as a facade back-edge.
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
$baseline = '823d69822ab09829b2bab47d8fc70ce6eb710a7b'
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
    $baseline = '823d69822ab09829b2bab47d8fc70ce6eb710a7b'
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

- root Python files equal 495; root `agent_*.py` equals the sole retained
  `agent_runtime_contracts.py`; `agents/` has exactly 82 implementation modules;
  the complete package has 642 Python files;
- the physical cohort graph has 34 core and 48 peripheral modules, 153 unique
  core-to-peripheral edges, and zero reverse edges; no `agents/` module falls
  outside the selected facade-reachable cohort;
- `agent_pagination.py` and `metadata_inventory()` are absent;
  `compact_pagination` behavior is preserved in `pagination_completeness.py`;
  `metadata_inventory_state()` failure ordering is preserved;
- `gravity_sdk.__all__ == 148`; fixture/runtime owners each equal 147; the
  reviewed owner ledger contains exactly six proposed changes;
- no removed deep-path shim, alias, hook, duplicate, second facade, package
  initialization side effect, or facade back-edge exists;
- every candidate in the rebound audit denominator has a reviewed disposition
  and there is no unresolved consumer; isolated-wheel and canonical-consumer
  censuses match their ledgers;
- shared-spine paths point to `agents/capabilities.py`,
  `agents/composite.py`, and `agents/handoff.py`, while `plan_adapters.py` and
  `__main__.py` remain in place; and
- all five Phase 1 commands passed on the trailer-bound Phase 1 checkpoint;
  both Phase 2 rollback targets and every command from `Structural Exit And
  Reviewed Owners` onward pass on the final checkpoint without substitution.

Technical debt #11 closes only when this leaf reaches `fixed_dev`. Closure is
an 83-module compact-Agent transformation with 82 physical moves
and two explicit concept deletions, not proof of the complete Agent domain, a
prefix rename, or an empty package. `main` remains frozen until the complete
program is green and the user gives new explicit approval.

## Signed Independent Responsibility Inventory

<!-- R17_INDEPENDENT_INVENTORY_JSON_START -->
```json
{
  "analysis_baseline": "dev@f2e8eec1f3c0567e20ab8c0be6465cc4e2c52e59",
  "boundary_cases": [
    {
      "cli_commands": [],
      "direct_consumer_count": 55,
      "direct_imports_to_members": [],
      "direct_member_consumers": [],
      "direct_other_consumer_count": 55,
      "in_unrestricted_facade_closure": true,
      "label": "broader_runtime_contracts_owner",
      "module": "agent_runtime_contracts",
      "primary_schemas": [],
      "selected": false
    },
    {
      "cli_commands": [
        "describe",
        "find",
        "list",
        "operations",
        "schema",
        "search"
      ],
      "direct_consumer_count": 10,
      "direct_imports_to_members": [
        "agent_discovery_support",
        "agent_vocabulary"
      ],
      "direct_member_consumers": [
        "agent_analysis",
        "agent_batch_sources",
        "agent_capabilities",
        "agent_discovery_support",
        "agent_segment",
        "agent_semantic_context",
        "agent_sources"
      ],
      "direct_other_consumer_count": 3,
      "in_unrestricted_facade_closure": true,
      "label": "independent_find_surface",
      "module": "find",
      "primary_schemas": [
        "gravity.find.v1"
      ],
      "selected": false
    }
  ],
  "conclusion": {
    "boundary": "inconsistent_but_adjustable",
    "complete_agent_domain_proven": false,
    "graph_methods_converged": false,
    "r17_82_moves_supported": true
  },
  "decisions": [
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "092defcbb5348b14d621fe6c517eabd1665929f6e46bf7584a7a4ab1c0f69725",
      "include": true,
      "module": "agent",
      "other_consumer_count": 3,
      "other_consumers_sha256": "485e05de661953981febbbbae8074ea855ad60611d2931c601b8a154808dc27b",
      "r17_disposition": "retain_public_facade",
      "reason": "unique_semantic_facade",
      "role_markers": [],
      "source_sha256": "015242ea0be705bd47651b645e5dd3465fb1fd24b8769ce45fb6e2550c0013fa"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "e2ac2614c2adb8e3fcb0409134f64ff3faa9e775543ae84099ebdc5e8b3416c2",
      "include": true,
      "module": "agent_advertiser_profile",
      "other_consumer_count": 1,
      "other_consumers_sha256": "38953d75af75523d98765adfb7e527b0489777f51b9b95e6a9f75d254694cd7a",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "44234ae97545619e9040ba25ffd41e6c904e0cb139dba903cb8cc8732ae5fc35"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "ae09fd5c2bb10b0e14cbb037897ca4ffa0cc9e6f726e4d3557f3a4a4299f4368",
      "include": true,
      "module": "agent_analysis",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role",
        "intent_boundary"
      ],
      "source_sha256": "a9c91c2fbac36b719a518a2fce2ca32dd123a61075448807b2fb1cf49a0cd5fa"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "8f55f7377822664ee04ee85dee39ed1e1b9af60c321c47be624239cc4b7e9408",
      "include": true,
      "module": "agent_analysis_default_dictionary",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "d65c266fdaae37b2c8c1db317425452281631a529435ab90219fd305b7400ef7"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "bb0069fc8e02b7a4874d4f24f2a279a2e2655c81907367752b38bd73f6975020",
      "include": true,
      "module": "agent_analysis_task",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "adc407df3497fa10c15a79b00d34569f45ddd0c3435418b346ad4506b6c094fe"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "3a1a7c71a80e179f81b7b29eef9d0323e4bfc901cda3752f3ffd12f42b43f175",
      "include": true,
      "module": "agent_app_catalog",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "natural_language_boundary"
      ],
      "source_sha256": "4edaa81fc895ce6e0494cfa625a2a1dde316649de36fa3372f13ad1b50e54fde"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "0da97c5224d4a490a0c3f452ae922da452663e99a0539cb5ae4e9328c5222fc0",
      "include": true,
      "module": "agent_app_public_info",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "c615d201789876ac2288a407c8082493703ee13a65989ef382c808437abd3081"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "8f55f7377822664ee04ee85dee39ed1e1b9af60c321c47be624239cc4b7e9408",
      "include": true,
      "module": "agent_attribution_performance",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "1a31a9619d3243d6c4f81d29f74d31f49326e9efdc52e18dbde2cb1097c93ac7"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "89a33ae6387c3ad75592a36290a295b0d5ca7c53eccac56c6aaefbdde7963d5a",
      "include": true,
      "module": "agent_attribution_user_detail",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "eb04ee03d31ba2df84cbfd7b314197e0245b747b4b3da319c402738105d9e6cb"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "ebc6beeffe92880e87d194837ada74d1be60f6c71ce083ea2d1a2630c43c704f",
      "include": true,
      "module": "agent_batch",
      "other_consumer_count": 2,
      "other_consumers_sha256": "c34335ff9c44b736777837e509d12c9797506606294e554db4b32f453e0cf073",
      "r17_disposition": "move",
      "reason": "declared_agent_protocol_surface",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "c7c2bba34087c0753e4d73cf43bb71615e16fd2eef969cbdac36f2756cde344a"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "5588552af73c18d655c12a1141f120c6daa2a15e1361a60d11752d26dc56b0f1",
      "include": true,
      "module": "agent_batch_questions",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "c8a3ceb3d18c8aa0e6c180a24aa772df422a4091e3560ed0e6d8376c2618b076"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "f7ba7886eb2095235a65ca3e7e8393f33edb2c1791408314a15151ae81cc0378",
      "include": true,
      "module": "agent_batch_sources",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "be79716d21b402930f9009cc6970002ce992912f3a2757f203bf2281dec11974"
    },
    {
      "compact_consumer_count": 7,
      "compact_consumers_sha256": "3059b7a3e64ec1309fad02eff0f1cc3710089994d9eafa1ac54cae3b897282de",
      "include": true,
      "module": "agent_bilibili_account_performance",
      "other_consumer_count": 1,
      "other_consumers_sha256": "d036b0ec84e07237ca00904c90c634934b1f6a21efe70ef8b25157a240966e95",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "198a4e281c4967097ca5e0289c8bed6c6cf0fb8a967a3dd62ba96b0ced2d76da"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "23aaacaef3228e51a04aed3f8efd684e91dd83a3311d297324f8b1f5ca9ffb6c",
      "include": true,
      "module": "agent_business_pulse",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "e9a5902046cb92db40e9b8ff86de85bfca7041411cbf2f2fac471e685f0e1a3a"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "89b6f04c9bf400fb9c7339b232412c2c584de4d0744c9856b86f79b92bc204ff",
      "include": true,
      "module": "agent_call_bound",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "declared_agent_protocol_surface",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "740256e99d4e2e08ac6a02fcdbdd1a1c5e313b957b82765390e995ab45b05f35"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "810e5c9edb2891dcb5214bc697e9c7f1ab228efd52d76adce6b67e93c1b15a08",
      "include": true,
      "module": "agent_caller_language",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "caller_language"
      ],
      "source_sha256": "de43dd91b36728cd7fe7067fc83ef970ebcf92c403935220549b19cab2095193"
    },
    {
      "compact_consumer_count": 11,
      "compact_consumers_sha256": "d29fa9beebbdffc92a88b8da885bfab1b5189d09918ab99c9b3a68c56d4ae67e",
      "include": true,
      "module": "agent_capabilities",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "dfeca2239f43c13b9d9f1945dd37d2b718565df2b3a904735fbf97904dc2c8bc"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "e0206117becaded7e8fe2972dbafee8082add6d8c47f2057ab5facdcf90b1f6c",
      "include": true,
      "module": "agent_catalog",
      "other_consumer_count": 1,
      "other_consumers_sha256": "23fba4c6c05f53a8134d0bb9799d106907c7ff3af0fbaf7406a3057481bb194b",
      "r17_disposition": "move",
      "reason": "declared_agent_protocol_surface",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "1b0e384f1fb0e68446ae42c3f2ec89060cef46800d7c8f13929c57cdea86710c"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "ca255e7c39412d8e5ac86c827c7bf7ec76279ccaaa374b6bfd5ae74d582b6a54",
      "include": true,
      "module": "agent_catalog_parity",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "d14a18184df98a6b5e90e7a03c840d5050509f31d0037419438b1626781f7350"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "ebc6beeffe92880e87d194837ada74d1be60f6c71ce083ea2d1a2630c43c704f",
      "include": true,
      "module": "agent_catalog_refresh",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "8f36812f15cfad5516e69a1cdbdd12f6572023a6e4eed4e0d9898913d193b8f5"
    },
    {
      "compact_consumer_count": 2,
      "compact_consumers_sha256": "eea6ba160b78a9f711c4e8f815d7002290d9d771f221d405001bf259203cf9e0",
      "include": true,
      "module": "agent_client",
      "other_consumer_count": 1,
      "other_consumers_sha256": "68d63f703013288a3ad53a2a89d2da578b800118d89be96f9f90e5dddabe190e",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "lazy_discovery_client"
      ],
      "source_sha256": "79f0bd93fefc97a94964dc2f0816ebf4580dacb1a1db5a3704b786f161b27dcf"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "ee406c3351254940bf092a4c0f34d3f1886d3f6823a57b30a6661d733836b193",
      "include": true,
      "module": "agent_company_usage",
      "other_consumer_count": 1,
      "other_consumers_sha256": "5f8f001483c7b10ab717d0accba350cbf15777cbc57504a22e2ec0d57ea6707d",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "227b2be038af373ebb1e788ad429519478d2e4c430acd97aedbe6df8f913f2b2"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "89e35d1240f370bd43473b0f660e7ef9d10ec2cde3be7915e0c0df3c6bec6e39",
      "include": true,
      "module": "agent_composite",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "6b29091148c8ac2388ea5f8aa01b86796b5521a7b6d5b963cb3484c71e43836b"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "89e35d1240f370bd43473b0f660e7ef9d10ec2cde3be7915e0c0df3c6bec6e39",
      "include": true,
      "module": "agent_composite_inventory",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "c8b4fd37fc918183dda886a6a2ade764e401d3ba9927b8d50f6827349e0e1db9"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "ee406c3351254940bf092a4c0f34d3f1886d3f6823a57b30a6661d733836b193",
      "include": true,
      "module": "agent_custom_audience",
      "other_consumer_count": 1,
      "other_consumers_sha256": "6fe97a1e3f78350b2d37efa73da42cac86934b0d5031aeed97d30c26c2080afc",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "deaa9156e5529b53d568de6e3542918801104c3054dfcb46501cf98c716ff22f"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "6572ac382f0adb0a269109ecefbb230e1bb17a6e9c02c61e152bad5cfdc93758",
      "include": true,
      "module": "agent_custom_metric",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "6760af8687fe433cb03302281dc4f08facefd359137eecf767b64d31eca98faa"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "75d4e3742b5d55c497be0359d84105bd3c351a02b9472bee858dd8fc5dcf6681",
      "include": true,
      "module": "agent_dashboard",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "68a7551cb9ec94f1e174a140b41ce3ced7e2190fdfe5cf1fa2730f5d0c621f0a"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "27af71ebff9fc9ca4f56d11226f4ee1c89771f54049ac8283bf14556e7eccf47",
      "include": true,
      "module": "agent_derived_metrics",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "98973244706e56f102bfbff9053ac8457b47bea722f84ba4cfbec665eec924a7"
    },
    {
      "compact_consumer_count": 6,
      "compact_consumers_sha256": "cb964add4e6ac54d64f6cd9b8d0f1835daf389bfd6750f576fa7475866cdde5c",
      "include": true,
      "module": "agent_discovery_policy",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "71bbcf60296283cb7836cd12b5502b570d88f4c0b1325aedeb14815d89f03776"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "9f605d2e547bf9d180563359eef1af8d70fcf29c2ac38fc04e14fa9f277e51d2",
      "include": true,
      "module": "agent_discovery_support",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "eb0f36c4f74cb9757b4ac45feff67dccff9ce1d4a11efeed32d1352364d6a488"
    },
    {
      "compact_consumer_count": 9,
      "compact_consumers_sha256": "9a16189a2c4e9acc0cc559052677091f4e38acb86b540bea855ef336894c9fb7",
      "include": true,
      "module": "agent_export",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "f5ea9bcdb2dd6d604e0c02fb55644e66182f24aea9e07219c233eda3bb6205dd"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "df6420f1096a3c02c0e4b858618fe7ed0e8b2dc49fb9bf0ef0a4d4fd745ea01c",
      "include": true,
      "module": "agent_fixed_snapshots",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "natural_language_boundary"
      ],
      "source_sha256": "35e1d844bd33e3b0758134ad4e85e98d8f945c59ac44ccd799960124e8144955"
    },
    {
      "compact_consumer_count": 6,
      "compact_consumers_sha256": "fd65a41aa4f8dd12876395f03142cf904f64a675caaf11eacef3713dcde8481e",
      "include": true,
      "module": "agent_gap",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "14c16c806e9b274afecbfaf6e47e2f5d13134f9f13b51495749f677aa3167da9"
    },
    {
      "compact_consumer_count": 6,
      "compact_consumers_sha256": "678f3d3f2fb1dc7e8c1b3cb45893c23e61289d94cbd9625e78f0d171cd2eb4af",
      "include": true,
      "module": "agent_handoff",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "0031b38d3ac498946885c7744cec6dd87edfd670e2baf5bcaf79dc15de37d11d"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "7bd9122ef4dc246638353923776e352490b8e98b1e3288e5efd607f15b3b95b1",
      "include": true,
      "module": "agent_host_catalog",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "332fa744af61690aa72aff2ffb126f9472664643c994c8fb1258e676dd44442d"
    },
    {
      "compact_consumer_count": 2,
      "compact_consumers_sha256": "8388958631004eabb55226e5f9881cc23f5cde68307abe1a0c3b64802de280d0",
      "include": true,
      "module": "agent_host_selection",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "host_product_selection"
      ],
      "source_sha256": "bfa0de7a77b33c312f9a5af0c1a9c4859ee631f49c50c04d509f5dd4ec949e6d"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "ebc6beeffe92880e87d194837ada74d1be60f6c71ce083ea2d1a2630c43c704f",
      "include": true,
      "module": "agent_input_catalogs",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "declared_agent_protocol_surface",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "3ecce6e4ea62e1d32fa3bf4cdafcd60f59b2d76fe35d51df49040bcd92809202"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "cdcbd969b8b04e5a0596e345a85adb92801941adf23aa1fe3db6fc63a685404b",
      "include": true,
      "module": "agent_input_resolution",
      "other_consumer_count": 1,
      "other_consumers_sha256": "f7ca30740108f99252441e6e43668c1b5a59cbec2068d9fe3841b5dd83f01e42",
      "r17_disposition": "move",
      "reason": "declared_agent_protocol_surface",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "810d3627309ae2cebb5ef487ec49c27df5da9083c0d644dfd881a917fca9eae7"
    },
    {
      "compact_consumer_count": 11,
      "compact_consumers_sha256": "99908e09aacba9aa5c43d0bc214098a9f77675ef6e4aa4c8b6ad5bdf72d1ba67",
      "include": true,
      "module": "agent_intent_routing",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "9acd24b37af2c287de392e0cdea311383b13d788034d425410b0ebd811dc0d6b"
    },
    {
      "compact_consumer_count": 44,
      "compact_consumers_sha256": "1b8eb7098484cd0edbc13e1b26010e2e5b5f14b51e40354d996861b0a27fb3cb",
      "include": true,
      "module": "agent_intent_text",
      "other_consumer_count": 1,
      "other_consumers_sha256": "e3f82810e5b747dccf963244a70a706269bd4d6ad564ae7cdd6bf1aad7ee95b1",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "intent_boundary"
      ],
      "source_sha256": "54a259e4a5d01ebb63ffae1315c08c99edc5808cbde3c537e51d89f5ffa95cea"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "6572ac382f0adb0a269109ecefbb230e1bb17a6e9c02c61e152bad5cfdc93758",
      "include": true,
      "module": "agent_kanban_mutation",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "85838124789d41b23a7f230841b2274fa0d36f96c58590a51ddf37431f7ae4ce"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "72d270fb6ecd7a9de8da2eec1f5ceb3d45a181d5d5f9bea68ceabbb8b03aa45d",
      "include": true,
      "module": "agent_lexical_rescue",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "lexical_retrieval"
      ],
      "source_sha256": "4e2f13a187d40b085bec1e99c15a851c759d6e8634f2badc54469cfe787b8d46"
    },
    {
      "compact_consumer_count": 2,
      "compact_consumers_sha256": "caea4baf7b2f824e15ecfe78ea2e9b9d402f57684197c24cab6e7c075333d54f",
      "include": true,
      "module": "agent_lexical_retrieval",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "171bc35b5635a3aa48120be7cc4c5a36cade59e7fb71734c2179f1c36ea87775"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "6eac1333bcbe6eb7ba6277f55e4ada9cde0a03e0049fd21cd0d7bb491a19b1d9",
      "include": true,
      "module": "agent_material_asset",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "092985f3acf3b85ca812e4fc9b13e563d58f915e82a128ce84c30cb7b7bd0c79"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "75d4e3742b5d55c497be0359d84105bd3c351a02b9472bee858dd8fc5dcf6681",
      "include": true,
      "module": "agent_material_performance",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "4a321a495d6b1843f964c1218dc3b7bca2ec1b57b4ff63043fb6dc897060e5b1"
    },
    {
      "compact_consumer_count": 2,
      "compact_consumers_sha256": "e24f59d9fa6c6ddfcf89ba847bdb27ee1ce1d48afa86ba4c0ed6ab7091951237",
      "include": true,
      "module": "agent_metadata_onboarding",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "b284fd600dafb0665bd9bb77d390d32f29321eccbe8eb61c31b3400c17769a31"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "d44321919b0f17d181f78597f53160b505f215c37cfda8180388dcc39f690df6",
      "include": true,
      "module": "agent_metadata_search",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "e50e9ade521b8bf94836b4d5c79f226cd1ea24aa4a680e8bbb47ce4d0b932da6"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "6572ac382f0adb0a269109ecefbb230e1bb17a6e9c02c61e152bad5cfdc93758",
      "include": true,
      "module": "agent_metadata_template",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "829d614c430838a62b20ee39567889de5e650a141e3a6c50a5382ff74bc164bb"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "0da97c5224d4a490a0c3f452ae922da452663e99a0539cb5ae4e9328c5222fc0",
      "include": true,
      "module": "agent_monetization_aggregate",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "be354490165749a81cc1e539fc03f132459d2441e3bce962de0edbdc22ef922b"
    },
    {
      "compact_consumer_count": 6,
      "compact_consumers_sha256": "d8730c9472ac27687b4c132e149d71deec84045ba941cea2a3a5c84164c28b8a",
      "include": true,
      "module": "agent_monetization_guard",
      "other_consumer_count": 1,
      "other_consumers_sha256": "fbe967f64ded9d5c9989e2392b68529a6f1ae72feb7ff04da4d27f05f9349f8a",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "8934818d5606ff39de58874c1f00572f3f89a85a6e559639045082549eb581ab"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "5c9ae828bb50b980d8f9c13d3a9addf3f40230921d0c7e91ab784c91c6046561",
      "include": true,
      "module": "agent_multidim",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "8ad92d79ff24afe6bf0b24b8ccb02feb90e56e520426043aa6d563738e73dbb2"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "89e35d1240f370bd43473b0f660e7ef9d10ec2cde3be7915e0c0df3c6bec6e39",
      "include": true,
      "module": "agent_mutation_cards",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "73fa18ff52900402564ab09d12cd183b3f67cb2dd4b7737b9fad24d3676689a5"
    },
    {
      "compact_consumer_count": 2,
      "compact_consumers_sha256": "aa5d5f340126785bd1e239eeef85918a48fd81a82de07fa6f0b80b3167102011",
      "include": true,
      "module": "agent_operation_contract",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "4d05e1fef832bff838af6dcece9be6a58ebeadc95983a88e1ff9f91cda5cc3ea"
    },
    {
      "compact_consumer_count": 7,
      "compact_consumers_sha256": "36b526b343e417d9a465d3d4552f262fef199fba51b3f63fb9f3c213b861a84e",
      "include": true,
      "module": "agent_order_directory",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "d6d120dbb6dd4d3188d79aab5792789982b98dd9416e28217a08c1de1949389c"
    },
    {
      "compact_consumer_count": 6,
      "compact_consumers_sha256": "d565351905a07d2c75e4a74638a97716c46a17f45736a1c1449b9413400e67b6",
      "include": true,
      "module": "agent_order_trace",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "40d3820fbd084f8eea3fc1403a4ac75e902ab0c3fe83d31cc50e2b22b1aa9692"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "cdcbd969b8b04e5a0596e345a85adb92801941adf23aa1fe3db6fc63a685404b",
      "include": true,
      "module": "agent_output",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "7f23a5a69ec51d6d7c6f051c96bcdd38098a4189664fa3bd05bebcb46c22c4d3"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "a73ff7757b1355a2215f1e290629de5d994a616477eab2d9cf65cae3e351642e",
      "include": true,
      "module": "agent_pagination",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "consolidate_delete",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role",
        "agent_facing"
      ],
      "source_sha256": "1c3cb183d321d68ce565389dee2ac5dd8195f0504efa2d6837ed5cb809f5caa1"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "b7c5bd460c77fa505ca58054a1f0d4b88287ba8450883f21c7b0f46299c24726",
      "include": true,
      "module": "agent_product_inventory",
      "other_consumer_count": 1,
      "other_consumers_sha256": "0ceab08832c9527cf2b5792dc0ddf555acbdefbd092752d103afaf422eab4af0",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "ace6e684b45f084037647ec3dbb24f517c44d35d945c58289b4b8b9a5ac625ac"
    },
    {
      "compact_consumer_count": 6,
      "compact_consumers_sha256": "d565351905a07d2c75e4a74638a97716c46a17f45736a1c1449b9413400e67b6",
      "include": true,
      "module": "agent_promotion_performance",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "799851aabdf6507666a31cde4970c7fb7cf9236bb7e1f32241c9f15b32477ac2"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "6572ac382f0adb0a269109ecefbb230e1bb17a6e9c02c61e152bad5cfdc93758",
      "include": true,
      "module": "agent_realtime_event",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "b7d3b3f226e68318889711e469f6d751c35b3024773110c9f15bccb029a40a99"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "8f55f7377822664ee04ee85dee39ed1e1b9af60c321c47be624239cc4b7e9408",
      "include": true,
      "module": "agent_realtime_event_catalog",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "f3f8aae411b6239acee84b14a67efe79d2693b92f40f31ab3b01f73e9725390e"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "038f5f23b191dd6e6b1937c4fdaa1de25b808bd7511cc6511e58f1b9c502ee7b",
      "include": true,
      "module": "agent_report_directory",
      "other_consumer_count": 1,
      "other_consumers_sha256": "5f8f001483c7b10ab717d0accba350cbf15777cbc57504a22e2ec0d57ea6707d",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "1858694c86ff4a4db2b9eb67cef1a8b2b1f9cbc14c62b2e82a66504a120865ac"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "6572ac382f0adb0a269109ecefbb230e1bb17a6e9c02c61e152bad5cfdc93758",
      "include": true,
      "module": "agent_report_mutation",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "c143ed2204cfa7d8d7e086a906f2ebeb2e47b73b5bf1f349ab0e3e601ff60586"
    },
    {
      "compact_consumer_count": 2,
      "compact_consumers_sha256": "86295669e8524a73c89a4c1dadeb0887ea3b5ca4e6cc8d0276bdadafacc640c7",
      "include": true,
      "module": "agent_report_routing",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "9dd331a86174cbdfa6088d07de2cc1d50ca203fb65852fb5b554b8e725f0b800"
    },
    {
      "compact_consumer_count": 0,
      "compact_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "include": false,
      "module": "agent_runtime_contracts",
      "other_consumer_count": 55,
      "other_consumers_sha256": "8158fdbf5e420e2157f80418ecfeff7d766540717004510a70878f10e457768c",
      "r17_disposition": "not_a_member",
      "reason": "broader_runtime_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "fff45cd14343a17e6747d23817cbb7559cd3027dbad18a36b3ce712b2ee44e49"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "89a33ae6387c3ad75592a36290a295b0d5ca7c53eccac56c6aaefbdde7963d5a",
      "include": true,
      "module": "agent_saved_analysis",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "c67b3ffcd945db00e4174dcdaee3fdd5ed7ba4a8830cb42eb5d7b40885318a0e"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "6572ac382f0adb0a269109ecefbb230e1bb17a6e9c02c61e152bad5cfdc93758",
      "include": true,
      "module": "agent_saved_analysis_mutation",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "a5dd9247bf3d14f58fdb33ff871d752509f529a0be4305bf01729016def70a9a"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "74a567dd2ea610e782e5ee932dc8f331821b98bde39c57ea6a0acc4b81ceb538",
      "include": true,
      "module": "agent_segment",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role",
        "intent_boundary"
      ],
      "source_sha256": "4f32ee4892231565f8c4a6daf3cbae82040c8b4356d64f501b295d5944b98b80"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "75d4e3742b5d55c497be0359d84105bd3c351a02b9472bee858dd8fc5dcf6681",
      "include": true,
      "module": "agent_segment_members",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role",
        "natural_language_boundary"
      ],
      "source_sha256": "dabe96d62cd5aedc0355c831b77f4d006778330453475a9a461c7245067482b8"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "75d4e3742b5d55c497be0359d84105bd3c351a02b9472bee858dd8fc5dcf6681",
      "include": true,
      "module": "agent_segment_snapshot",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "584d5d49fffc784cfc4c3faff82320ec99a5ec44d4780ff9ed81623893ad0edb"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "89a33ae6387c3ad75592a36290a295b0d5ca7c53eccac56c6aaefbdde7963d5a",
      "include": true,
      "module": "agent_semantic_compose",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "a3fbc91d3e40b32b0e4f96513508261094fafe025d65eebd03935d3a1a7afd1f"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "42a237f6ecc03f166032604c106abeafcf7afd11423ebf3664a46d1e0f064ee0",
      "include": true,
      "module": "agent_semantic_context",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "04f7ccf27c66190d70674149b23f15109354dfcdc37b4bf16a925d87cc260013"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "e3de14f2cd89ec895a2df4246ef72e3fd7acac88983743964148cb0e76ebdcd0",
      "include": true,
      "module": "agent_semantic_derived",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "semantic_gap_support"
      ],
      "source_sha256": "7e31fb34cf22c0ce1571e6ff7be452ed2f9de993c3f1c856475d6f8752839369"
    },
    {
      "compact_consumer_count": 8,
      "compact_consumers_sha256": "a0a9d1e57ca19b4c49c6682594d4fd177431e8b35c8a444a61d24bcc83bd7a86",
      "include": true,
      "module": "agent_sources",
      "other_consumer_count": 1,
      "other_consumers_sha256": "a2a7ca0413cb371fb9eda4681c3620444ce3845e8b048e4e56ccc8a5fd3093e1",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "779b5bc9d4ff3a8facf898ae78fd5f07f18b164fd5d96d06ec9d5221f3f0c05e"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "72d270fb6ecd7a9de8da2eec1f5ceb3d45a181d5d5f9bea68ceabbb8b03aa45d",
      "include": true,
      "module": "agent_sql_product_discovery",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "catalog_aware_discovery"
      ],
      "source_sha256": "f5ed6652ff8e3b20d6bbc95513d80af4b288cd520a5fe912e88bb9f31a67c552"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "71df9adc8798bba39437f332ba3f842d18284436b668b4a6e50b2d2ca2520c5c",
      "include": true,
      "module": "agent_sql_product_gap",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "natural_language_boundary"
      ],
      "source_sha256": "72a907a5fa94dde286de8faee1d353ed5257748fc5032cd6554a2cdeaee05903"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "70fc2780c3721fb7a30b0a7274438ea117f0217bd8d7c45e2f5f4323543b3f41",
      "include": true,
      "module": "agent_table_lineage",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "eafb287e1ef2f259c9d33eb42b453211796d48e619a85d57859baf753b317c6d"
    },
    {
      "compact_consumer_count": 5,
      "compact_consumers_sha256": "8f55f7377822664ee04ee85dee39ed1e1b9af60c321c47be624239cc4b7e9408",
      "include": true,
      "module": "agent_title_package",
      "other_consumer_count": 1,
      "other_consumers_sha256": "d30c2798bcfd9806b7d6c66d75ecb59e0ec43db16f9d51ce28cbcfe44f100f72",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "f3af565b6c8971b478cbce7a9c0621b5087d42e702bcb4fb4d649354b8d973bd"
    },
    {
      "compact_consumer_count": 6,
      "compact_consumers_sha256": "e2bfc78a7257575447a4074a04118ed338273810371556515a6b8b0ce603a0a6",
      "include": true,
      "module": "agent_unavailable",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "unavailable_journey"
      ],
      "source_sha256": "8c00953b46ad9fbdea0f08796fa06c4290a49e024f631d416ca36137f0c81176"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "55fcce5e9a1c8190408ca0b2164a319cb98e2f00ec6e318b2833cc194f2581b9",
      "include": true,
      "module": "agent_unavailable_analysis",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "natural_language_boundary",
        "unavailable_journey"
      ],
      "source_sha256": "66786bc5b684aafe03acf7a6a46f7801544df2c4f8e4c3892f3512c24511ef38"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "55fcce5e9a1c8190408ca0b2164a319cb98e2f00ec6e318b2833cc194f2581b9",
      "include": true,
      "module": "agent_unavailable_promotion",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "natural_language_boundary",
        "unavailable_journey"
      ],
      "source_sha256": "11f62806c5929d000368dbd9a90848a31a116ccdda427cfee63ebe361660d50a"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "55fcce5e9a1c8190408ca0b2164a319cb98e2f00ec6e318b2833cc194f2581b9",
      "include": true,
      "module": "agent_unavailable_report",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "natural_language_boundary",
        "unavailable_journey"
      ],
      "source_sha256": "b77099c4a0c47ca96e7dfb87d9bc711b9cda09573e749a83b2d86c250424d0e3"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "623579b3afab0a4a9500c4265e360a79d2282cdcc1655e9d21793bdff317c901",
      "include": true,
      "module": "agent_user_journey",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "311f8c3ca6253980863908e4760d90d3fb293b79e21730df51b9e9c7e0e739a3"
    },
    {
      "compact_consumer_count": 4,
      "compact_consumers_sha256": "394ca5c7d918dd215c647e4b06297ea447d3283e86d1b0dc1db87683c8abf3ee",
      "include": true,
      "module": "agent_vocabulary",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "c4ba9fa3fb9be333a898238f27250b9259970a634e257d8b7c9481321fde4421"
    },
    {
      "compact_consumer_count": 0,
      "compact_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "include": false,
      "module": "analysis_context",
      "other_consumer_count": 3,
      "other_consumers_sha256": "818eb71d098be0910da90076b80b8489a688ad3004c5705da41d10b6a4c97eaf",
      "r17_disposition": "not_a_member",
      "reason": "independent_primary_protocol",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "f76d096a2326a3adb07d2525f9710df51638b62977a035f822612319a8027893"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "22361efece3d1a71da4fa6a9387ffc3e317393d2620ed277c82273850f712f77",
      "include": false,
      "module": "business_pulse",
      "other_consumer_count": 3,
      "other_consumers_sha256": "7bef39abe792cf4bd3600c5c79e976d092d278a60ed5e4c1651e7c38f446cc17",
      "r17_disposition": "not_a_member",
      "reason": "independent_primary_protocol",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "e1bcad3f8ecdd7391e30d4d34f62c6ff88a48e2e39b744629c8b4090fe9e9259"
    },
    {
      "compact_consumer_count": 3,
      "compact_consumers_sha256": "e2601ad2c9fe1554014b2c3ca7b792117023e68b85843f107be4381dbd5fef9b",
      "include": false,
      "module": "domains",
      "other_consumer_count": 30,
      "other_consumers_sha256": "996707a486dacfba9d384ac8cd7184da649c75d8e970f5f0e69a3dd99e434167",
      "r17_disposition": "not_a_member",
      "reason": "broader_runtime_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "b8e6130d0765876582bb9085b85afb13b468df4e04ec5f08a510ca20893f9a20"
    },
    {
      "compact_consumer_count": 7,
      "compact_consumers_sha256": "5fd2ed71c1defde60d4301b598b198211b2a09c8a5d04614a3f23874adfd446d",
      "include": false,
      "module": "find",
      "other_consumer_count": 3,
      "other_consumers_sha256": "78549922b4098a4760eba625cb1013ac65c67598db82795e01bc2b7858755b35",
      "r17_disposition": "not_a_member",
      "reason": "independent_primary_protocol",
      "role_markers": [
        "agent_role",
        "agent_facing"
      ],
      "source_sha256": "f964df7c2d032b174a94c609d115afca9728b9df49cda84107d12da3d0ed7e19"
    },
    {
      "compact_consumer_count": 2,
      "compact_consumers_sha256": "10a9acc9db7944656a0ba70b0668965593278af5f2de10cc7008e1bac46187ff",
      "include": false,
      "module": "find_input",
      "other_consumer_count": 7,
      "other_consumers_sha256": "807746801ee28d33c43e1876640b1e9bcc84612a1ae37518175e0a386074eeb8",
      "r17_disposition": "not_a_member",
      "reason": "broader_runtime_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "ce0833110ec52ac613dc14260dfde95dc013477175252bfcef85378c83409b7e"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "cdb80b516bf48dd56d9b4770bd950c4a751d8c7a071d3fa76c37a37580a6a1ac",
      "include": false,
      "module": "multidim_product",
      "other_consumer_count": 6,
      "other_consumers_sha256": "99b7543dd1ef775f345aee9d04246367ddf2ae92a8aafa4c4da5e51946643045",
      "r17_disposition": "not_a_member",
      "reason": "broader_runtime_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "031c2639dd4eaf3821c49a1f651719af0a010545556e6ac7996f0f784193f3c2"
    },
    {
      "compact_consumer_count": 1,
      "compact_consumers_sha256": "89b6f04c9bf400fb9c7339b232412c2c584de4d0744c9856b86f79b92bc204ff",
      "include": true,
      "module": "relative_date_agent",
      "other_consumer_count": 0,
      "other_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "r17_disposition": "move",
      "reason": "compact_consumer_owned",
      "role_markers": [
        "agent_role"
      ],
      "source_sha256": "4539e664097865983221c101c75a744c8e57e0282856dc3303d7a81828769963"
    },
    {
      "compact_consumer_count": 0,
      "compact_consumers_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      "include": false,
      "module": "resolver",
      "other_consumer_count": 3,
      "other_consumers_sha256": "352c94e6605315fd1e38f38c83dcc7a91e51ee66104096acbb8448d763538a09",
      "r17_disposition": "not_a_member",
      "reason": "independent_primary_protocol",
      "role_markers": [
        "intent_boundary"
      ],
      "source_sha256": "39861e2c41af738ea93334d6d3b508dea5799c2a6ab7b3f7655b8eb5b4c6bf97"
    }
  ],
  "graph_observations": [
    {
      "member_count": 40,
      "members_sha256": "68884ce71b5392d25e434d5fb0a09b35c97857d58bd30ebddaf187fcfaddfffe",
      "name": "facade_scc"
    },
    {
      "member_count": 311,
      "members_sha256": "3558e70b7ea29239eea7a55575ee1f5859188a6a505a0a1f93ea2b6fbba04f4f",
      "name": "unrestricted_facade_closure"
    },
    {
      "conductance": 0.17425083240843509,
      "damping": 0.85,
      "member_count": 496,
      "members_sha256": "e286e549a5b373b60242bbeae5a2a8bfb25877978ee734f403d5b4e59eb2d6b0",
      "name": "import_graph_minimum_conductance",
      "pagerank_iterations": 127,
      "tolerance": 1e-14
    },
    {
      "baseline": "f2e8eec1f3c0567e20ab8c0be6465cc4e2c52e59",
      "member_count": 626,
      "members_sha256": "eca93e2830db84bd47b102505bd6d101ef4df4ced6347df1cd87e3488c2bd0a8",
      "name": "cochange_component"
    }
  ],
  "members": [
    "agent",
    "agent_advertiser_profile",
    "agent_analysis",
    "agent_analysis_default_dictionary",
    "agent_analysis_task",
    "agent_app_catalog",
    "agent_app_public_info",
    "agent_attribution_performance",
    "agent_attribution_user_detail",
    "agent_batch",
    "agent_batch_questions",
    "agent_batch_sources",
    "agent_bilibili_account_performance",
    "agent_business_pulse",
    "agent_call_bound",
    "agent_caller_language",
    "agent_capabilities",
    "agent_catalog",
    "agent_catalog_parity",
    "agent_catalog_refresh",
    "agent_client",
    "agent_company_usage",
    "agent_composite",
    "agent_composite_inventory",
    "agent_custom_audience",
    "agent_custom_metric",
    "agent_dashboard",
    "agent_derived_metrics",
    "agent_discovery_policy",
    "agent_discovery_support",
    "agent_export",
    "agent_fixed_snapshots",
    "agent_gap",
    "agent_handoff",
    "agent_host_catalog",
    "agent_host_selection",
    "agent_input_catalogs",
    "agent_input_resolution",
    "agent_intent_routing",
    "agent_intent_text",
    "agent_kanban_mutation",
    "agent_lexical_rescue",
    "agent_lexical_retrieval",
    "agent_material_asset",
    "agent_material_performance",
    "agent_metadata_onboarding",
    "agent_metadata_search",
    "agent_metadata_template",
    "agent_monetization_aggregate",
    "agent_monetization_guard",
    "agent_multidim",
    "agent_mutation_cards",
    "agent_operation_contract",
    "agent_order_directory",
    "agent_order_trace",
    "agent_output",
    "agent_pagination",
    "agent_product_inventory",
    "agent_promotion_performance",
    "agent_realtime_event",
    "agent_realtime_event_catalog",
    "agent_report_directory",
    "agent_report_mutation",
    "agent_report_routing",
    "agent_saved_analysis",
    "agent_saved_analysis_mutation",
    "agent_segment",
    "agent_segment_members",
    "agent_segment_snapshot",
    "agent_semantic_compose",
    "agent_semantic_context",
    "agent_semantic_derived",
    "agent_sources",
    "agent_sql_product_discovery",
    "agent_sql_product_gap",
    "agent_table_lineage",
    "agent_title_package",
    "agent_unavailable",
    "agent_unavailable_analysis",
    "agent_unavailable_promotion",
    "agent_unavailable_report",
    "agent_user_journey",
    "agent_vocabulary",
    "relative_date_agent"
  ],
  "members_sha256": "1b15fdfcebfa086dc6683eacbab3262f2f224ffe80403c5a0e1ccfce8a085c5d",
  "method": {
    "candidate_universe": "Parse every Python module in the package; module names and paths label results but never filter candidates.",
    "dependency_scope": "Build an AST import graph from every lexical depth and take the facade's unrestricted directed closure.",
    "graph_methods": {
      "cochange": "fixed-baseline all-history connected component",
      "facade_scc": "directed mutual reachability",
      "import_conductance": "degree-normalized personalized PageRank; damping 0.85; tolerance 1e-14; deterministic minimum-conductance sweep",
      "unrestricted_closure": "directed static-import reachability"
    },
    "ownership_decision": "Include the facade; reject a non-Agent primary schema; otherwise include an Agent protocol surface or a marked owner with at least one marked consumer and no more other than marked direct consumers.",
    "post_selection_comparison": "Load the R17 move ledger only after classification and compute differences.",
    "responsibility_declaration": "Match module docstrings against the closed role-marker regex list.",
    "role_markers": [
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "agent_role",
        "regex": "\\bagent\\b"
      },
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "natural_language_boundary",
        "regex": "natural-language"
      },
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "caller_language",
        "regex": "caller-language"
      },
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "agent_facing",
        "regex": "agent-facing"
      },
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "host_product_selection",
        "regex": "product-selection"
      },
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "intent_boundary",
        "regex": "\\bintent\\b"
      },
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "lexical_retrieval",
        "regex": "\\blexical\\b"
      },
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "semantic_gap_support",
        "regex": "semantic gaps?"
      },
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "unavailable_journey",
        "regex": "unavailable .*journey"
      },
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "catalog_aware_discovery",
        "regex": "catalog-aware discovery"
      },
      {
        "flags": [
          "IGNORECASE"
        ],
        "id": "lazy_discovery_client",
        "regex": "lazy client boundary"
      }
    ],
    "semantic_facade": "Select the unique non-package owner of gravity.agent.v1 that defines the three facade callables, registers the agent command, and emits the three response-shape keys."
  },
  "method_sha256": "7e61ac801f39ca94cfc1e970dd58e777c84f88fddbf80c4d8712ecb3cc176cd5",
  "module_namespace": "gravity_sdk",
  "payload_sha256": "2b2ef88778a029b1ee6bee5bedd664af9058e971d09f80bc53f205848b698381",
  "r17_comparison": {
    "action_normalized_members_equal_moves": true,
    "action_normalized_members_not_moves": [],
    "independent_members_not_moves": [
      "agent",
      "agent_pagination"
    ],
    "ledger_sha256": "9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20",
    "move_count": 82,
    "moves_not_action_normalized_members": [],
    "moves_not_independent_members": []
  },
  "schema_version": "gravity.r17-independent-responsibility-inventory.v1",
  "selector_summary": {
    "member_count": 84,
    "rejected_role_candidate_count": 8,
    "role_candidate_count": 92,
    "semantic_facade": "agent",
    "unrestricted_closure_count": 311
  },
  "source_snapshot": {
    "implementation_module_count": 636,
    "package_module_count": 642,
    "tree_sha256": "d690cf49e61b5c70b0a6bfd1f23be69fbf5795711e383812f7502ea103620b47"
  }
}
```
<!-- R17_INDEPENDENT_INVENTORY_JSON_END -->

## Canonical Owners

Long-lived owners are the `gravity_sdk/agents/` boundary, stable facade and
lazy map, `pagination_completeness.py`, retained Runtime contracts module,
public API and owner fixtures, boundary and wheel gates, Requirement Index
shared spine, canonical consumer evidence, and technical debt #11. This
Requirement is delivery governance, not a second runtime contract.
