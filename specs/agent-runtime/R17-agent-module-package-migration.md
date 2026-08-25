# R17 Agent Domain Package Migration

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.2` via `directive.json`; canonical architecture source is v9.2 |
| Status | `specified`; all machine-readable ready prerequisites are currently unsatisfied |
| Track | Structural migration / technical debt #11 |
| Requirement dependencies | None |
| Parallel group | `structural-migration` |
| Shared-spine integration | Required and serialized |
| Delivery mode | `leaf`; two stacked implementation branches, one Requirement status and one final exit |
| Measurement baseline | `codex/gov-staged-epic@aa46ddf3343d8fb8ea0162b7806403527a2d79d9`; exact implementation baseline remains unbound |
| M0 evidence candidate | `codex/m0-characterization@088d1606127439943cab0b79c8cdbdf516af4839` |
| Implementation Issue / branches / worktrees | Unbound until independent review advances R17 to `ready` |
| Production requests | `0`; structural migration only |
| Main integration | Frozen; adding R17 extends `all_index_requirements_fixed_dev` |

## Outcome

Create a minimal `gravity_sdk/agents/` package for the statically proven Agent
discovery/handoff domain. Of the 83 root `agent_*.py` candidates at the
measurement baseline, 82 are reachable from the stable `gravity_sdk.agent`
facade through candidate-to-candidate import edges. R17 moves 81 of those
modules one for one, consolidates the single-caller `agent_pagination` helper
into the canonical `pagination_completeness.py` owner and deletes that module,
and leaves the unreachable `agent_runtime_contracts.py` infrastructure module
at the root.

The root package falls from 578 to 496 Python files. The complete package stays
at 642 Python files because deleting `agent_pagination.py` offsets the new
`agents/__init__.py`. Runtime responses, request volume, privacy, execution
ownership, supported capability, and the actual 148-name `gravity_sdk.__all__`
surface do not change. Removed deep module paths receive no compatibility shim.

R17 is one leaf and has one status. Its two implementation phases are stacked
branch and rollback boundaries, not indexed milestones. A phase cannot
independently reach `fixed_dev`, close technical debt #11, or satisfy R17.

## Ready Prerequisites

`index.json.ready_prerequisites` is the machine authority.

1. **Satisfied at `dev@3fa8fe6c3247fd5bdbcd9cded32f89b4644e8515`.** The M0
   candidate commit `088d1606127439943cab0b79c8cdbdf516af4839` is an ancestor
   of that baseline. M0 content changed after that commit, so the bound
   artefacts are the baseline copies, not the candidate copies:

   | Artefact | SHA-256 |
   | --- | --- |
   | `tests/agent_migration_characterization.py` | `edad06dacc70c749de8e1c8e87f00cbfc69d5f2e8b52b41f961fc6dee72f3e81` |
   | `tests/test_agent_module_migration_characterization.py` | `a792c4b303f476b44de6e30f4d37bc0c34f4a7f3c72752354eaab4133c3b5468` |
   | `tests/test_installed_wheel.py` | `bd8d9cf332354147fd4e11f87ac7d09b48ac7dcf1d4eae164900b0baf7bed117` |
   | `tests/fixtures/public_api_owner_migrations.json` | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |
   | `tests/fixtures/public_api_exports.json` | `d6aa4c9bb939f6e56428192ad432300fe985618fae69492cc9e12820dd43c053` |

   The eager-graph gate computes real Tarjan SCCs over the full 642-module
   package and rejects only components intersecting the move set; the two
   pre-existing `prober` and `sql` components are therefore tolerated and must
   not be used to widen or narrow the gate.
2. **Satisfied at the same baseline.** All 227 audit sites carry reviewed
   dispositions in `tests/fixtures/agent_module_reference_dispositions.json`
   (SHA-256 `6bd35c5d914e751a048d138e1e6770244a68273761528acaa9be5d4d41716661`,
   schema `gravity.agent-module-reference-dispositions.v1`): 227 unique source
   keys, `unclassified_sites = 0`, `blocker_count = 0`, split
   `213 no_migration_effect / 13 rewrite_reference / 1 rewrite_selector_data`.
   Zero sites reference `agent_pagination` or `agent_runtime_contracts`; the
   ledger validator still forces `no_migration_effect` for any future
   `agent_runtime_contracts` row and `pagination_completeness` for any future
   `agent_pagination` row.
3. **Not satisfied.** An independent reviewer must accept the scope,
   measurement definitions, proposed owner changes, two explicit concept
   deletions, and exact acceptance commands and return a `ready` verdict. This
   specification cannot satisfy that prerequisite itself.

The candidate audit also reports 83/83 old-path smoke imports successful and
zero naming collisions. Those facts do not classify any of the 227 sites.

## Mechanical Boundary Rule

The candidate universe is the 83 files matched by
`src/gravity_sdk/agent_*.py` at the bound baseline. It does not include the
stable `src/gravity_sdk/agent.py` facade.

For each candidate `m`, build a directed source-import graph over every Python
module under `src/gravity_sdk`: parse imports in all scopes with Python `ast`;
resolve relative and absolute imports to the longest existing in-package
module; resolve root lazy exports through
`tests/fixtures/public_api_exports.json`; deduplicate `(source, target)` edges;
then compute `d(m)`, the shortest path from `gravity_sdk.agent` to `m` while
allowing only the facade as the start node and candidates as later nodes.

**Inclusion rule (verbatim): a candidate is in the Agent domain if and only if
`d(m)` is finite.** No filename token, line-count threshold, inbound-ratio
threshold, or allowlist can make an unreachable module part of the domain.

The ledger also records `A`, unique direct inbound sources from the candidates
plus facade, and `X`, unique direct inbound sources from all other
`src/gravity_sdk` modules. `A:X` is evidence, not a threshold: CLI, SDK, Plan
adapters, and root facades are valid consumers of Agent-owned entry points.
`X` is also the exact number of non-Agent-to-`agents` source edges introduced
by moving that target. This rule would select the same facade-rooted subsystem
without the current directory layout and therefore passes the canonical
architecture boundary gate.

### Baseline Classification Ledger

`move` means one-for-one package migration. `consolidate/delete` is inside the
proven domain but is not a migrated module. `exclude` follows only from absent
`d`; `agent_runtime_contracts` is not special-cased by the rule.

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

The ledger contains 81 `move`, one `consolidate/delete`, and one `exclude`
decision. The facade-reachable domain has 82 modules; 81 become implementation
modules under `agents/`. The 81 move rows have 334 Agent-source inbound edges
and 17 non-Agent-source inbound edges in aggregate. Those 17 consumer edges
change target path but do not change ownership; the excluded contracts module
instead has 0 Agent and 55 non-Agent inbound edges.

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
`metadata_inventory_state()` and its failure ordering. The 227-site ledger and
bound consumer census must also find no real dynamic caller; any such caller
returns R17 to `specified` instead of gaining a shim.

These are the only consolidation/deletion actions. The remaining 47 peripheral
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

### Phase 1: Peripheral 47 And Pagination Consolidation

The branch to be bound as `codex/r17-peripheral` starts from the reviewed R17
baseline. It creates a minimal `gravity_sdk/agents/__init__.py`, migrates the
following 47 modules, consolidates `agent_pagination`, and migrates every
classified repository and canonical-consumer reference:

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
agent_user_journey agent_vocabulary
```

Phase 1 acceptance requires 530 root Python files, 35 remaining root
`agent_*.py` files, exactly 47 migrated implementation modules under `agents/`,
no `agent_pagination.py`, an unchanged 642-file complete package, 148 root
`__all__` names, 147 lazy owners, zero unresolved classified references, and
zero migration-universe multi-node SCCs. Its accepted commit becomes the base
of Phase 2 but receives no independent Requirement state.

Rollback restores all 47 root modules, `agent_pagination.py`, its caller, and
every mapped consumer before removing package targets.

### Phase 2: Core 34 And Boundary Lock

The branch to be bound as `codex/r17-core` is stacked on accepted Phase 1. It
moves the frozen 34-module core and deletes only `metadata_inventory()`:

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

The baseline domain split is 34 core plus 48 peripheral modules, including
`agent_pagination`: 153 unique core-to-peripheral edges and zero reverse edges.
The physical move split is 34 core plus 47 peripheral modules; removing the
sole `agent_sources -> agent_pagination` edge gives 152 core-to-moved-peripheral
edges and zero reverse edges.

Phase 2 updates `cli.py`, the facade, lazy owners, remaining consumers, and the
three physical paths in `index.json.shared_spine`. Rollback restores the 34
core files, wrapper, owners, imports, consumers, and shared-spine paths.

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
domain=set(distance)-{facade}; excluded=candidates-domain
core={'gravity_sdk.'+name for name in '''agent_analysis agent_batch agent_batch_questions agent_batch_sources agent_business_pulse agent_capabilities agent_catalog agent_composite agent_composite_inventory agent_dashboard agent_discovery_policy agent_discovery_support agent_export agent_handoff agent_host_catalog agent_host_selection agent_input_resolution agent_intent_routing agent_lexical_retrieval agent_material_performance agent_monetization_guard agent_multidim agent_operation_contract agent_output agent_product_inventory agent_report_routing agent_segment agent_semantic_context agent_semantic_derived agent_sources agent_sql_product_discovery agent_table_lineage agent_unavailable agent_unavailable_analysis'''.split()}
pagination={'gravity_sdk.agent_pagination'}; peripheral=domain-core; moved=domain-pagination
print(json.dumps({'candidates':len(candidates),'domain':len(domain),'excluded':sorted(excluded),'moved':len(moved),'core':len(core),'peripheral_domain':len(peripheral),'moved_peripheral':len(peripheral-pagination),'core_to_peripheral':sum(u in core and v in peripheral for u,v in edges),'peripheral_to_core':sum(u in peripheral and v in core for u,v in edges),'core_to_moved_peripheral':sum(u in core and v in peripheral-pagination for u,v in edges),'moved_peripheral_to_core':sum(u in peripheral-pagination and v in core for u,v in edges)},sort_keys=True))
for target in sorted(candidates):
    agent_in=sum(source in allowed for source,value in edges if value==target)
    external_in=sum(source not in allowed for source,value in edges if value==target)
    print(target.removeprefix('gravity_sdk.'),agent_in,external_in,distance.get(target))
'@
& ./.venv/Scripts/python.exe -c $code
```

Measured summary: `candidates=83`, `domain=82`,
`excluded=["gravity_sdk.agent_runtime_contracts"]`, `moved=81`, `core=34`,
`peripheral_domain=48`, `moved_peripheral=47`,
`core_to_peripheral=153`, `peripheral_to_core=0`,
`core_to_moved_peripheral=152`, `moved_peripheral_to_core=0`.

The final physical edge gate does not depend on old root filenames. Run it on
the combined Phase 2 tree:

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

Final required output is `implementation_modules=81`, `core=34`,
`peripheral=47`, `core_to_peripheral=152`, and `peripheral_to_core=0`.

### File And Public-Surface Counts

```powershell
& ./.venv/Scripts/python.exe -c "import gravity_sdk,json; from pathlib import Path; r=Path('src/gravity_sdk'); a=r/'agents'; s=json.loads(Path('tests/fixtures/public_api_exports.json').read_text(encoding='utf-8')); print(json.dumps({'root_py':len(list(r.glob('*.py'))),'root_agent_py':len(list(r.glob('agent_*.py'))),'package_py':len(list(r.rglob('*.py'))),'agents_implementation_py':len([p for p in a.glob('*.py') if p.name!='__init__.py']) if a.exists() else 0,'lazy_snapshot':len(s),'runtime_exports':len(gravity_sdk._EXPORTS),'root_all':len(gravity_sdk.__all__)},sort_keys=True))"
```

| Metric | Baseline | Final exit |
| --- | ---: | ---: |
| Root Python files | 578 | 496 |
| Root `agent_*.py` | 83 | 1 |
| Complete-package Python files | 642 | 642 |
| `agents/` implementation modules | 0 | 81 |
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

After M0 is in the baseline, reuse its checked-in eager-import visitor and
Tarjan enumeration. The migration universe is root `*.py` plus
`agents/**/*.py`. It has 578 modules and zero multi-node SCCs at baseline and
must have the same values at exit: 81 moves preserve count, deleting
`agent_pagination.py` subtracts one, and `agents/__init__.py` adds one. The
unrelated full-package five-node SQL SCC is comparison-only.

The local dynamic-audit candidate remains 83 modules and 227 manual-review
sites with zero collisions, 83 successful smoke imports, and zero smoke
failures. Before `ready`, the durable UTF-8 ledger must contain 227 unique
source keys, zero unclassified rows, zero blockers, and a bound SHA-256.
Retained-path dispositions remain rows; narrowing the move set does not erase
an audit site.

## Write Scope

- Move exactly the 81 `move` rows to one-for-one
  `src/gravity_sdk/agents/<name-without-agent-prefix>.py` targets and add a
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
- Execute the 14 governance-document rewrites the disposition ledger records,
  all in the core phase because all of them name the three agent spine files:
  three in `AGENTS.md`, four in
  `specs/agent-runtime/architecture-source.md`, three in
  `specs/agent-runtime/index.json`, three in `specs/agent-runtime/index.md`,
  and the single `_EXPORTS` selector-data rewrite in
  `src/gravity_sdk/__init__.py`. `AGENTS.md` edits are in-place replacements and
  must not grow the documentation budget.
- **Rewriting `architecture-source.md` breaks its digest binding.** That file is
  bound by `directive.json.canonical_source.sha256`, and the canonical source
  itself requires revising the source together with the directive digest. The
  core phase must therefore, in one commit: apply the four path rewrites,
  recompute the file SHA-256, write it into
  `directive.json.canonical_source.sha256`, advance `directive.json.version`,
  move the superseded version and digest into `directive.json.supersedes`, and
  update the three in-document version self-references — the `## v9.x 修订摘要`
  heading, the `Directive ID / Version` line, and the reading-order diagram
  line. Acceptance fails if the recomputed digest and the directive value
  differ. No new approval record may be created by this rewrite; it is an
  errata sync, not a re-approval.
- Add or retain characterization, installed-wheel, owner-migration,
  consumer-census, boundary, concept-deletion, and eager-graph gates.
- `agent_runtime_contracts.py`, `plan_adapters.py`, and `__main__.py` do not
  move and are outside implementation scope absent a reviewed revision.

## Non-goals

- No rename or relocation of `agent_runtime_contracts`; no migration of other
  prefix families, `blob_*` pilot, or broad root cleanup.
- No merge of the 47 peripheral recognizers, data-driven recognizer registry,
  layer redesign, second execution path, compatibility alias, or parallel
  facade.
- No `runtime.py` / `to_jsonable()` SCC work. Its disputed graph result and
  cross-execution-core scope require a separate proposal if pursued.
- No response, schema, route, ordering, fingerprint, error, privacy,
  concurrency, request-count, or network behavior change.
- No R17 state transition, implementation authorization, approval claim, or
  closure of technical debt #11 from this `specified` document.

## Machine Contract

- The 81 `move` rows map one for one; `agent_pagination` is deleted after
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
- The installed package contains all 81 migrated modules, the canonical
  pagination helper, and retained contracts module. The 578-module migration
  universe has zero multi-node SCCs.
- All 227 audit candidates are dispositioned before work starts; any later
  unresolved consumer blocks the affected phase and R17.

## Capability, Safety, And Consumer Preservation

M0 freezes root lazy access, cache, unknown-attribute, `dir()`, `__all__`,
installed-wheel imports, deep/string consumer paths, and the eager graph.
Both phases compare representative CLI, SDK, Plan, Agent, happy, empty,
partial, and error outputs; request counts, selection order, fingerprints,
error codes, privacy projection, concurrency, and zero-network failures match
the bound baseline.

Every import, patch target, import string, test, script, generated reference,
and canonical consumer reference in the bound ledger must move or be explicitly
retained. Re-scan `work-dashboard` in both phases. Unknown external deep
importers remain residual risk and never authorize a permanent shim or a claim
of global consumer completeness.

R17 performs no production probe, target request, credential use, mutation,
installation into a user environment, release, or `main` promotion. Shared
spine, public owners, generated artifacts, and coverage artifacts are
serialized through one integrator.

## Final Acceptance And Exit

R17 exits only on the combined Phase 2 tree when:

- root Python files equal 496; root `agent_*.py` equals the sole retained
  `agent_runtime_contracts.py`; `agents/` has exactly 81 implementation modules;
  the complete package has 642 Python files;
- the move graph has 34 core and 47 peripheral modules, 152 unique
  core-to-peripheral edges, and zero reverse edges; no `agents/` module falls
  outside the facade-reachable boundary;
- `agent_pagination.py` and `metadata_inventory()` are absent;
  `compact_pagination` behavior is preserved in `pagination_completeness.py`;
  `metadata_inventory_state()` failure ordering is preserved;
- `gravity_sdk.__all__ == 148`; fixture/runtime owners each equal 147; the
  reviewed owner ledger contains exactly six proposed changes;
- no removed deep-path shim, alias, hook, duplicate, second facade, package
  initialization side effect, or facade back-edge exists;
- all 227 candidates have reviewed dispositions and no unresolved consumer;
  isolated-wheel and canonical-consumer censuses match their ledgers;
- shared-spine paths point to `agents/capabilities.py`,
  `agents/composite.py`, and `agents/handoff.py`, while `plan_adapters.py` and
  `__main__.py` remain in place; and
- focused migration, public API, CLI/SDK/Plan/Agent parity, consumer census,
  isolated-wheel, both complete collectors, compiler, quality, usability,
  security, CLI help, and diff gates pass at commands bound by ready review.

Technical debt #11 closes only when this leaf reaches `fixed_dev`. Closure is
an 82-module proven-domain transformation with 81 physical moves and two
explicit concept deletions, not a prefix rename or empty package. `main`
remains frozen until the complete program is green and the user gives new
explicit approval.

## Canonical Owners

Long-lived owners are the `gravity_sdk/agents/` boundary, stable facade and
lazy map, `pagination_completeness.py`, retained Runtime contracts module,
public API and owner fixtures, boundary and wheel gates, Requirement Index
shared spine, canonical consumer evidence, and technical debt #11. This
Requirement is delivery governance, not a second runtime contract.
