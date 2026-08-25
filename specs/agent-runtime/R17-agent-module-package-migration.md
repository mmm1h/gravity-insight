# R17 Agent Module Package Migration

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.2` via `directive.json`; canonical architecture source remains v9.1 |
| Status | `specified`; all machine-readable ready prerequisites are currently unsatisfied |
| Track | Structural migration / technical debt #11 |
| Requirement dependencies | None |
| Parallel group | `structural-migration` |
| Shared-spine integration | Required and serialized |
| Delivery mode | `leaf`; two stacked implementation branches, one Requirement status and one final exit |
| Measurement baseline | `codex/gov-staged-epic@eaeff07a2f89e2005d4016e70948489e1efa228c`; exact implementation baseline remains unbound |
| M0 evidence candidate | `codex/m0-characterization@088d1606127439943cab0b79c8cdbdf516af4839` |
| Implementation Issue / branches / worktrees | Unbound until independent review advances R17 to `ready` |
| Production requests | `0`; package-only migration |
| Main integration | Frozen; adding R17 extends `all_index_requirements_fixed_dev` |

## Outcome

Move exactly the 83 root `agent_*.py` implementation modules into a minimal
`gravity_sdk/agents/` domain package while keeping the 527-line
`gravity_sdk.agent` module as the stable facade. The root package falls from
578 to 495 Python files without changing behavior, request volume, privacy,
execution ownership, supported consumers, or the actual 148-name
`gravity_sdk.__all__` surface.

R17 is one leaf and has one status. The two implementation phases below are
stacked branch and rollback boundaries, not indexed milestones. A phase cannot
independently reach `fixed_dev`, close technical debt #11, or satisfy R17. The
fully integrated leaf is the only R17 result that may merge to `dev`.

## Ready Prerequisites

`index.json.ready_prerequisites` is the machine authority. All three entries
currently have `satisfied: false`:

1. The M0 candidate commit
   `088d1606127439943cab0b79c8cdbdf516af4839` must be an ancestor of the
   bound implementation baseline. Review must bind its exact test IDs, fixture
   paths, and digests; a commit on another branch is evidence, not a satisfied
   gate by itself.
2. The local candidate audit at
   `D:/git-pjt/gravity-sdk-dev/tmp/codex/dyn-audit/` contains 227 unclassified
   sites: 11 dynamic imports, 117 non-string patch expressions, 92 bare
   `agent_x` strings, and 7 `__module__` receivers. Before `ready`, all 227
   must have reviewed dispositions under unique source keys in
   `tests/fixtures/agent_module_reference_dispositions.json`; its SHA-256 must
   be bound, and `unclassified_sites` must equal 0.
3. An independent reviewer must accept the scope, measurement definitions,
   proposed owner changes, and exact acceptance commands and return a `ready`
   verdict. This specification cannot satisfy that prerequisite itself.

The candidate audit also reports 83/83 old-path smoke imports successful and
zero naming collisions. Those facts do not classify any of the 227 sites.

## Internal Implementation Plan

### Phase 1: Peripheral 49

The branch to be bound as `codex/r17-peripheral` starts from the reviewed R17
baseline. It creates a minimal `gravity_sdk/agents/__init__.py`, moves the 49
peripheral modules, and migrates every classified repository and canonical
consumer reference for those paths. The accepted Phase 1 commit becomes the
base of Phase 2; it does not independently merge R17 or advance its status.

Phase 1 acceptance requires 529 root Python files, 34 remaining root
`agent_*.py` files, exactly 49 migrated modules under `agents/` excluding
`__init__.py`, no root public owner change, no old-path shim, 148 root
`__all__` names, 147 lazy export owners, zero unresolved classified references,
and the migration-universe eager SCC gate at zero.

Phase 1 rollback restores the 49 root files and every mapped consumer before
removing their package targets. It has no data or external-state rollback.

### Phase 2: Core 34 And Boundary Lock

The branch to be bound as `codex/r17-core` is stacked on the accepted Phase 1
commit. It moves the following frozen 34-module source set:

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

The 49-module peripheral set is the exact complement of this set in the 83
files matched by `src/gravity_sdk/agent_*.py` at the bound baseline. If the
ready-baseline inventory or either set count differs, R17 must return to
`specified` and be revised before implementation.

Phase 2 updates `cli.py`, the root facade and lazy export owners, all remaining
consumers, and the three physical paths in `index.json.shared_spine`. It lands
the permanent structural-invariant tests with the moves. Only the combined
Phase 1 and Phase 2 result is eligible for R17 integration to `dev`.

Phase 2 acceptance requires the final exit conditions below. Its rollback
restores the 34 core root files, root lazy owners, CLI imports, consumers, and
three shared-spine paths, returning the implementation stack to the accepted
Phase 1 commit. If the leaf is abandoned, Phase 1 is then rolled back as well.

## Current Baseline

- `src/gravity_sdk/` contains 578 root Python files, including 83
  `agent_*.py` implementation modules; the complete package contains 642
  Python files. `gravity_sdk.agent` is not in the 83-file move set.
- `tests/fixtures/public_api_exports.json` and the runtime `_EXPORTS` map each
  contain 147 lazy names. `gravity_sdk.__all__` contains 148 names; the sole
  additional name is `__version__`. The 148-name runtime surface is the R17
  public exit metric; the 147-entry fixture remains the owner-map metric.
- Exactly six of the 147 lazy owners point to modules in the move set. Their
  proposed changes are `host_product_catalog` and
  `host_product_selection_schema` from `.agent_host_catalog` to
  `.agents.host_catalog`; `assess_host_product_selection`,
  `compile_host_product_selection`, and `resolve_host_product_selection` from
  `.agent_host_selection` to `.agents.host_selection`; and
  `capabilities_many` from `.agent_batch` to `.agents.batch`.
- Those six changes are measured proposals, not approved changes. The current
  M0 owner-migration ledger is empty. They become permitted implementation
  scope only after independent review advances R17 to `ready`.
- On the frozen 34/49 sets, the graph defined below has 153 unique directed
  edges from core to peripheral and 0 from peripheral to core. Adding the
  non-moving `gravity_sdk.agent` facade to the source set adds exactly two
  facade-to-peripheral edges and produces the obsolete 155 count.
- The migration eager-import universe is root `*.py` plus
  `agents/**/*.py` after that package exists. It currently contains 578
  modules and zero multi-node SCCs. The full recursive package universe has
  642 modules and one existing five-node SCC:
  `gravity_sdk.sql`, `sql.catalog`, `sql.products`, `sql.query`, and
  `sql.verification`. That unrelated SCC is recorded but is not an R17 exit
  gate.

## Reproducible Measurements

Run every command from the repository root with the worktree interpreter and
without `PYTHONPATH`.

### File And Public-Surface Counts

```powershell
& ./.venv/Scripts/python.exe -c "import gravity_sdk,json; from pathlib import Path; r=Path('src/gravity_sdk'); s=json.loads(Path('tests/fixtures/public_api_exports.json').read_text(encoding='utf-8')); print(json.dumps({'root_py':len(list(r.glob('*.py'))),'root_agent_py':len(list(r.glob('agent_*.py'))),'package_py':len(list(r.rglob('*.py'))),'lazy_snapshot':len(s),'runtime_exports':len(gravity_sdk._EXPORTS),'root_all':len(gravity_sdk.__all__),'agent_owner_routes':sum(owner.startswith('.agent_') for owner,_ in gravity_sdk._EXPORTS.values()),'all_minus_snapshot':sorted(set(gravity_sdk.__all__)-set(s))},sort_keys=True))"
```

The measured baseline is `root_py=578`, `root_agent_py=83`,
`package_py=642`, `lazy_snapshot=147`, `runtime_exports=147`,
`root_all=148`, `agent_owner_routes=6`, and
`all_minus_snapshot=["__version__"]`.

### Frozen 34/49 Dependency Edges

This exact script counts unique AST import edges in all scopes. A
`from . import <root export>` edge is resolved through the 147-entry owner
fixture. The source and target sets contain only the 83 moving modules; the
stable `agent.py` facade is excluded.

```powershell
$code = @'
import ast, json
from pathlib import Path
root=Path('src/gravity_sdk'); paths=sorted(root.glob('agent_*.py')); nodes={p.stem for p in paths}
owners={n:v[0].lstrip('.') for n,v in json.loads(Path('tests/fixtures/public_api_exports.json').read_text(encoding='utf-8')).items()}
core=set('''agent_analysis agent_batch agent_batch_questions agent_batch_sources agent_business_pulse agent_capabilities agent_catalog agent_composite agent_composite_inventory agent_dashboard agent_discovery_policy agent_discovery_support agent_export agent_handoff agent_host_catalog agent_host_selection agent_input_resolution agent_intent_routing agent_lexical_retrieval agent_material_performance agent_monetization_guard agent_multidim agent_operation_contract agent_output agent_product_inventory agent_report_routing agent_segment agent_semantic_context agent_semantic_derived agent_sources agent_sql_product_discovery agent_table_lineage agent_unavailable agent_unavailable_analysis'''.split())
peripheral=nodes-core; edges=set()
for path in paths:
    source=path.stem
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'), filename=str(path))):
        targets=[]
        if isinstance(node,ast.Import): targets=[a.name.split('.')[1] for a in node.names if a.name.startswith('gravity_sdk.') and len(a.name.split('.'))>1]
        elif isinstance(node,ast.ImportFrom):
            if node.level==1 and node.module: targets=[node.module.split('.')[0]]
            elif node.level==1: targets=[a.name if a.name in nodes else owners.get(a.name,'') for a in node.names]
            elif node.level==0 and node.module and node.module.startswith('gravity_sdk.'): targets=[node.module.split('.')[1]]
        edges.update((source,target) for target in targets if target in nodes and target!=source)
print(json.dumps({'root_modules':len(list(root.glob('*.py'))),'movable':len(nodes),'core':len(core),'peripheral':len(peripheral),'core_to_peripheral':sum(u in core and v in peripheral for u,v in edges),'peripheral_to_core':sum(u in peripheral and v in core for u,v in edges)},sort_keys=True))
'@
& ./.venv/Scripts/python.exe -c $code
```

The measured result is 578 root modules, 83 moving modules, 34 core modules,
49 peripheral modules, 153 core-to-peripheral edges, and 0 reverse edges.

### Eager SCC Universes

After the M0 candidate is in the baseline, the exact comparison below reuses
its checked-in eager-import visitor and applies Tarjan SCC enumeration to the
migration and complete-package inventories:

```powershell
$code = @'
import ast
from pathlib import Path
from tests.agent_migration_characterization import PACKAGE_ROOT, _EagerImportVisitor, _module_inventory
def full_inventory(root):
    result={}
    for path in root.rglob('*.py'):
        parts=list(path.relative_to(root).with_suffix('').parts); is_package=parts[-1]=='__init__'
        if is_package: parts.pop()
        result[path]=('.'.join((root.name,*parts)),is_package)
    return result
def graph(inventory):
    modules={name for name,_ in inventory.values()}; result={name:set() for name in modules}
    for path,(name,is_package) in inventory.items():
        visitor=_EagerImportVisitor(name,name if is_package else name.rpartition('.')[0],modules)
        visitor.visit(ast.parse(path.read_text(encoding='utf-8'),filename=str(path)))
        result[name].update(visitor.targets)
    return result
def sccs(adjacency):
    index=0; stack=[]; indices={}; low={}; active=set(); result=[]
    def visit(node):
        nonlocal index
        indices[node]=low[node]=index; index+=1; stack.append(node); active.add(node)
        for target in adjacency[node]:
            if target not in indices: visit(target); low[node]=min(low[node],low[target])
            elif target in active: low[node]=min(low[node],indices[target])
        if low[node]==indices[node]:
            component=[]
            while True:
                target=stack.pop(); active.remove(target); component.append(target)
                if target==node: break
            if len(component)>1: result.append(sorted(component))
    for node in sorted(adjacency):
        if node not in indices: visit(node)
    return sorted(result)
for label,inventory in [('migration',_module_inventory(PACKAGE_ROOT)),('full',full_inventory(PACKAGE_ROOT))]:
    components=sccs(graph(inventory)); print(label,len(inventory),len(components),components)
'@
& ./.venv/Scripts/python.exe -c $code
```

The measured baseline is `migration 578 0 []`; the comparison-only full
result is `full 642 1` with the five SQL nodes listed above. The migration
universe is selected because it contains every module R17 moves plus their
root peers while excluding an unrelated pre-existing SCC that R17 does not own.
After `agents/__init__.py` is created the same path rule contains 579 modules;
only its multi-node SCC count, which must remain zero, is an exit metric.

### Dynamic-Audit Candidate

```powershell
& ./.venv/Scripts/python.exe -c "import json; from pathlib import Path; p=Path('D:/git-pjt/gravity-sdk-dev/tmp/codex/dyn-audit'); a=json.loads((p/'dyn_audit_summary.json').read_text(encoding='utf-8')); s=json.loads((p/'dyn_audit_smoke_import.json').read_text(encoding='utf-8')); print({'modules':a['module_count'],'manual_review':a['manual_review_count'],'collisions':a['collision_counts'],'smoke_attempted':s['attempted'],'smoke_failures':len(s['failed']),'smoke_returncode':s['returncode']})"
```

The candidate values are 83 modules, 227 manual-review sites, zero collisions,
83 smoke attempts, zero smoke failures, and return code 0. This reads local,
uncommitted evidence; the ready review must bind a durable classification
ledger and its digest rather than treating the local path as canonical.

After M0 is in the baseline, use the following exact command for the proposed
owner ledger. It is empty at M0 and through Phase 1; final acceptance requires
six rows with the exact symbols and `from`/`to` owners listed above.

```powershell
& ./.venv/Scripts/python.exe -c "import json; from pathlib import Path; rows=json.loads(Path('tests/fixtures/public_api_owner_migrations.json').read_text(encoding='utf-8')); print({'owner_changes':len(rows),'symbols':sorted(row['symbol'] for row in rows)})"
```

The 227-site ledger does not exist yet, so its check cannot truthfully pass at
`specified`. Its schema is fixed as
`gravity.agent-module-reference-dispositions.v1`. Each row must copy the
candidate's `category`, repository-relative `file`, `line`, `column`, `form`,
and `old_value` as its source key, set `reviewed` to true, and use exactly one
of `migrate_reference`, `retain_non_module_text`, `no_migration_effect`, or
`block_r17` as its disposition. Before `ready`, bind the file's SHA-256 and run:

```powershell
& ./.venv/Scripts/python.exe -c "import json; from pathlib import Path; d=json.loads(Path('tests/fixtures/agent_module_reference_dispositions.json').read_text(encoding='utf-8')); rows=d['dispositions']; allowed={'migrate_reference','retain_non_module_text','no_migration_effect','block_r17'}; keys=[(r['category'],r['file'],r['line'],r['column'],r['form'],r['old_value']) for r in rows]; unclassified=sum(r.get('reviewed') is not True or r.get('disposition') not in allowed for r in rows); blockers=sum(r.get('disposition')=='block_r17' for r in rows); print({'schema':d.get('schema_version'),'rows':len(rows),'unique_source_keys':len(set(keys)),'unclassified':unclassified,'blockers':blockers})"
```

The ready values are schema
`gravity.agent-module-reference-dispositions.v1`, 227 rows, 227 unique source
keys, 0 unclassified rows, and 0 blockers.

## Write Scope

- Move exactly `src/gravity_sdk/agent_*.py` to one-for-one
  `src/gravity_sdk/agents/*.py` targets, removing only the redundant filename
  prefix, and add a minimal package initializer.
- Update `src/gravity_sdk/agent.py`, `src/gravity_sdk/__init__.py`, known
  static and classified dynamic consumers, tests, scripts, fixtures, and
  active canonical-consumer references required by those path changes.
- Move `agent_capabilities.py`, `agent_composite.py`, and `agent_handoff.py`
  in the core phase; serialize their integration and update `cli.py` imports
  and the Requirement Index shared-spine paths in the same phase.
- Add or retain characterization, installed-wheel, proposed owner-migration,
  consumer-census, dependency-boundary, and eager-graph gates owned by R17.
- `src/gravity_sdk/plan_adapters.py` and `src/gravity_sdk/__main__.py` do not
  move and are outside scope absent new pre-`ready` evidence and a reviewed
  scope revision.

## Non-goals

- No migration of `plan_*`, `analysis_*`, `metadata_*`, `segment_*`, or
  `sdk_*`; no `blob_*` pilot or broad root cleanup.
- No layer-by-layer contract/core/surface redesign, logic refactor, second
  execution path, old-path compatibility alias, or parallel facade.
- No behavior, schema, route, ordering, fingerprint, error, privacy,
  concurrency, request-count, or network change.
- No R17 state transition, implementation authorization, or closure of
  technical debt #11 from this `specified` document.

## Machine Contract

- Every source `agent_<name>.py` maps to exactly
  `gravity_sdk.agents.<name>`; `gravity_sdk.agent` remains the only root
  `agent*.py` module after completion.
- `gravity_sdk.agents.__init__` imports no business module and exposes no
  parallel facade. Internal modules must not import the package root facade or
  `gravity_sdk.agent`; the allowed direction is from the root facade into the
  package.
- No old root module, `sys.modules` alias, import hook, or duplicate source
  preserves a removed deep path.
- `gravity_sdk.__all__` remains exactly 148 names. The lazy owner fixture and
  runtime `_EXPORTS` remain exactly 147 entries. Only the six proposed owner
  routes listed above may change after the ready review accepts them.
- The installed package contains all 83 migrated modules. The migration
  universe eager multi-node SCC count remains exactly zero.
- The 227 dynamic-audit candidates are fully dispositioned before work starts;
  any later unresolved relevant consumer blocks the affected phase and R17.

## Capability And Consumer Preservation

M0 freezes root lazy access, cache, unknown-attribute, `dir()`, `__all__`,
installed-wheel all-module import, deep and string consumer paths, and the
eager graph before any move. Both phases compare representative CLI, SDK,
Plan, Agent, happy, empty, partial, and error outputs; request counts,
route/selection order, fingerprints, error codes, privacy projection,
concurrency, and zero-network failures must match the bound baseline.

Every repository import, patch target, import string, test, script, generated
reference, and canonical consumer reference in the bound classification ledger
must move with its owner path. Re-scan `work-dashboard` in both phases. Unknown
external deep importers remain a residual risk and never authorize a permanent
shim or a claim of global consumer completeness.

## Safety And Operations

R17 performs no production probe, target request, credential use, mutation,
installation into a user environment, release, or `main` promotion. Package
discovery is proven from an isolated built wheel. Shared-spine wiring, public
owner fixture changes, generated artifacts, and coverage artifacts are
serialized through one integrator.

## Final Acceptance And Exit

R17 exits only when all of the following are true on the combined Phase 2 tree:

- Root `agent_*.py == 0`; root Python files `== 495`; `agents/` contains
  exactly 83 migrated modules excluding its minimal `__init__.py`.
- `gravity_sdk.__all__ == 148`; the lazy owner fixture and runtime `_EXPORTS`
  each contain 147 entries; the reviewed owner ledger contains exactly the six
  proposed changes and no others.
- `gravity_sdk.agent` remains the stable root facade; no removed deep-path
  shim, alias, hook, duplicate source, or second facade exists.
- `agents/` has no back-import through `gravity_sdk` or `gravity_sdk.agent`;
  package initialization remains minimal; the migration-universe eager
  multi-node SCC count equals 0.
- All 227 audit candidates have reviewed dispositions and no unresolved
  relevant consumer remains. The installed wheel and canonical consumer
  census contain every migrated path expected by the bound ledgers.
- The three shared-spine paths point to `agents/capabilities.py`,
  `agents/composite.py`, and `agents/handoff.py`; `plan_adapters.py` and
  `__main__.py` remain in place.
- Focused migration, public API, CLI/SDK/Plan/Agent parity, consumer census,
  isolated-wheel, both complete collectors, compiler, quality, usability,
  security, CLI help, and diff gates pass at the exact commands bound by the
  independent ready review.

Technical debt #11 closes only when this leaf reaches `fixed_dev`. `main`
remains frozen until R17 and every other indexed Requirement are `fixed_dev`,
integrated validation is green, and the user gives new explicit approval.

## Canonical Owners

The long-lived owners are the `gravity_sdk/agents/` package boundary, the
stable root facade and lazy-export map, public API and reviewed owner-migration
fixtures, dependency/import boundary tests, installed-wheel import gate,
Requirement Index shared-spine list, canonical consumer evidence, and
technical debt #11. This Requirement records delivery governance and must not
become a second runtime contract.
