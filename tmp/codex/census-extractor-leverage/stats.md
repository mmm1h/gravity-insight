# Census extractor leverage statistics

## Proposal and decision rule

Before changing the extractor, quantify both failure classes against the committed Census
snapshot and the 27 non-closed analysis journeys. Implement only if resolving the failures
would remove the current blocker from multiple scheduled journeys. Route adjacency or a
frontend request shape alone does not count as an unlocked journey.

Verdict: **do not change the extractor in this unit**. Both failure classes are real and
widespread, but neither is the current root blocker for any of the 15 completely missing or
12 partially closed journeys.

## Inputs and reproducibility

- Route parameters: `src/gravity_sdk/census/data/route-params.json`, 987 routes.
- Coverage: `src/gravity_sdk/census/data/coverage.json`, 987 accounted routes.
- Snapshot: bundle id
  `eb1d37edb5d1ee1c59d8944dd0b21db09aef097f5c7fb7f7455b8278716424b4`.
- Raw source was read from
  `D:/git-pjt/work-dashboard/tmp/codex/gi-census-full/final` because raw bundles are not
  committed here. All 375 files were checked against the committed snapshot: 375 present,
  375 SHA-256 matches, 0 mismatches. No network request was made.
- The 27 journey blockers were read from `docs/analysis-journeys.md`; current candidate
  blockers were cross-checked against `docs/candidate-capability-matrix.md`.

## `load_alias_has_no_static_call`

The marker occurs in **97 route documents** and accounts for **123 unresolved route
occurrences**. The earlier count of 97 was therefore correct for routes, not occurrences.

| Route prefix | Routes |
| --- | ---: |
| `/turbo_engine/api/v1` | 60 |
| `/turbo_engine/api/v2` | 15 |
| `/report/api/v3` | 9 |
| `/account_center/api/v1` | 7 |
| `/openapi/api/v1` | 2 |
| `/turbo_engine/api/v3` | 2 |
| `/report/api/v1` | 1 |
| `/report/api/v2` | 1 |
| **Total** | **97** |

Coverage classification shows where those 97 routes sit:

| Coverage status | Routes |
| --- | ---: |
| `uncovered_write` | 49 |
| `covered` | 23 |
| `uncovered_read` | 17 |
| `uncovered_auth_or_proxy` | 7 |
| `uncovered_export` | 1 |
| **Total** | **97** |

The 17 uncovered reads are the only plausible product-evidence subset:

| Method | Route | Unresolved occurrences | Existing body fields |
| --- | --- | ---: | ---: |
| GET | `/account_center/api/v1/message/detail/` | 1 | 0 |
| POST | `/report/api/v1/filter_conf/get/` | 1 | 0 |
| POST | `/report/api/v2/custom_get/calc_total/` | 1 | 0 |
| POST | `/report/api/v3/adreport/attribution/` | 3 | 0 |
| POST | `/report/api/v3/coze/workflow/data_analysis/` | 1 | 0 |
| POST | `/report/api/v3/dataanalysis/ai/conversation/list/` | 1 | 0 |
| POST | `/report/api/v3/dataanalysis/ai/message/list/` | 1 | 0 |
| GET | `/turbo_engine/api/v1/asset/material/tools/get_file_params/` | 3 | 0 |
| POST | `/turbo_engine/api/v1/bytedance/event_manager_assets/list/` | 1 | 0 |
| GET | `/turbo_engine/api/v1/bytedance/site/preview/` | 1 | 0 |
| POST | `/turbo_engine/api/v1/kuaishou/batch_options/` | 1 | 2 |
| GET | `/turbo_engine/api/v1/task/adcreate/detail/` | 1 | 0 |
| POST | `/turbo_engine/api/v1/task/advertiser_validate/detail/list/` | 1 | 3 |
| POST | `/turbo_engine/api/v1/task/advertiser_validate/list/` | 1 | 3 |
| POST | `/turbo_engine/api/v1/tencent/asset/monitor/used/` | 1 | 0 |
| POST | `/turbo_engine/api/v2/alipay/batch_options/` | 1 | 2 |
| POST | `/turbo_engine/api/v2/event/conf_event_meta/default_val/list/` | 1 | 2 |

The remaining 80 routes are writes, auth/proxy paths, already-covered routes, or an export.
Several of the 17 reads are also task detail, AI/Web workflows, preview/tool helpers, or
other routes that are not analysis-journey products.

### Complete alias-failure route inventory

| Prefix | Method | Route | Unresolved occurrences |
| --- | --- | --- | ---: |
| `/account_center/api/v1` | POST | `/account_center/api/v1/demo_login/` | 1 |
| `/account_center/api/v1` | GET | `/account_center/api/v1/message/detail/` | 1 |
| `/account_center/api/v1` | POST | `/account_center/api/v1/user_binding/email/` | 1 |
| `/account_center/api/v1` | POST | `/account_center/api/v1/user_binding/phone/` | 1 |
| `/account_center/api/v1` | POST | `/account_center/api/v1/user_login/v2/` | 1 |
| `/account_center/api/v1` | GET | `/account_center/api/v1/user_login/without_passwd` | 1 |
| `/account_center/api/v1` | GET | `/account_center/api/v1/user/list/` | 1 |
| `/openapi/api/v1` | POST | `/openapi/api/v1/open_develop/create/` | 1 |
| `/openapi/api/v1` | POST | `/openapi/api/v1/open_develop/delete/` | 1 |
| `/report/api/v1` | POST | `/report/api/v1/filter_conf/get/` | 1 |
| `/report/api/v2` | POST | `/report/api/v2/custom_get/calc_total/` | 1 |
| `/report/api/v3` | POST | `/report/api/v3/adreport/attribution/` | 3 |
| `/report/api/v3` | POST | `/report/api/v3/confmetric/custom_metric/list/` | 1 |
| `/report/api/v3` | POST | `/report/api/v3/confmetric/metric/list/` | 1 |
| `/report/api/v3` | POST | `/report/api/v3/coze/workflow/data_analysis/` | 1 |
| `/report/api/v3` | POST | `/report/api/v3/dataanalysis/ai/conversation/list/` | 1 |
| `/report/api/v3` | POST | `/report/api/v3/dataanalysis/ai/message/list/` | 1 |
| `/report/api/v3` | GET | `/report/api/v3/dataanalysis/segment/list/` | 3 |
| `/report/api/v3` | POST | `/report/api/v3/dataanalysis/stream/event/list/download/` | 1 |
| `/report/api/v3` | POST | `/report/api/v3/dataanalysis/user/detail/list/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/apple/app/create/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/apple/app/edit/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/asset/directional_package/sync/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/asset/material_tag/tag_category/whole_tree/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/asset/material/album/tree/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/asset/material/batch_update_album_authority/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/asset/material/platform/async/` | 3 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/asset/material/tools/get_file_params/` | 3 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bilibili/asset/text/title/add/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/bytedance/app/list/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/asset/material/upload/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/asset/text/abstract/add/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/asset/text/title_package/add/` | 2 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/asset/text/title_package/edit/` | 2 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/asset/text/title_package/list/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/asset/text/title/add/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/aweme/video/async/` | 2 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/cewebrity_video/async/` | 2 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/custom_audience_push/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/event_manager_assets/async/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/event_manager_assets/list/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/manage/account/list/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/playable_new/async/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/bytedance/site/preview/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/site/update_status/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/bytedance/std/asset/text/title_package/add/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/bytedance/tools/query_api/` | 2 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/honor/manage/account/create/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/huawei/store/account/create/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/kuaishou/asset/title/create/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/kuaishou/audience_package/create/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/kuaishou/audience_package/delete/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/kuaishou/audience_package/edit/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/kuaishou/audience_package/sync/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/kuaishou/batch_options/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/kuaishou/common/post/api/` | 5 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/kuaishou/manage/account/list/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/oppo/advertiser/create/` | 2 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/oppo/advertiser/list/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/oppo/asset/text/title/add/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/oppo/tools/query_api/` | 2 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/oppo/v2/communal/target/add/` | 2 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/oppo/v2/communal/target/update/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/task/adcreate/detail/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/task/advertiser_validate/detail/list/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/task/advertiser_validate/list/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/task/batch/operate/delete/` | 3 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/task/bytedance/upload_material/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/task/media_type/material_push/result_get/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/task/tencnet/upload_material/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/tencent/asset/monitor/used/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/tencent/asset/text/title/add/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/tencent/report/adgroup/filters/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/user/open_app/check/mini_game_token/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/user/open_app/detail/` | 3 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/user/open_app/edit/mini_game_secret/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/user/post_backtrack/list/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/user/postback_mode/list/` | 1 |
| `/turbo_engine/api/v1` | GET | `/turbo_engine/api/v1/user/promoted_object/list/` | 1 |
| `/turbo_engine/api/v1` | POST | `/turbo_engine/api/v1/youdao/advertiser/create/` | 1 |
| `/turbo_engine/api/v2` | POST | `/turbo_engine/api/v2/alipay/batch_options/` | 1 |
| `/turbo_engine/api/v2` | POST | `/turbo_engine/api/v2/datamanageconfig/analysis_dashboard_condition_favourite/default_to_me/` | 2 |
| `/turbo_engine/api/v2` | POST | `/turbo_engine/api/v2/datamanageconfig/analysis_dashboard_condition_favourite/to_use/modify/` | 1 |
| `/turbo_engine/api/v2` | GET | `/turbo_engine/api/v2/datamanageconfig/base_report_metrics/list/` | 2 |
| `/turbo_engine/api/v2` | POST | `/turbo_engine/api/v2/datamanageconfig/kanban/space/share/delete/` | 1 |
| `/turbo_engine/api/v2` | GET | `/turbo_engine/api/v2/datamanageconfig/material_metrics/list/v3/` | 1 |
| `/turbo_engine/api/v2` | GET | `/turbo_engine/api/v2/datamanageconfig/promotion_metrics/list/` | 1 |
| `/turbo_engine/api/v2` | POST | `/turbo_engine/api/v2/datamanageconfig/report/update/` | 1 |
| `/turbo_engine/api/v2` | POST | `/turbo_engine/api/v2/event/conf_event_meta/default_val/list/` | 1 |
| `/turbo_engine/api/v2` | GET | `/turbo_engine/api/v2/event/event_list/` | 1 |
| `/turbo_engine/api/v2` | GET | `/turbo_engine/api/v2/event/event_property_list/` | 1 |
| `/turbo_engine/api/v2` | POST | `/turbo_engine/api/v2/event/event_virtual_prop/opt/` | 1 |
| `/turbo_engine/api/v2` | POST | `/turbo_engine/api/v2/event/property_template/event_delete/` | 1 |
| `/turbo_engine/api/v2` | POST | `/turbo_engine/api/v2/event/property_template/property_delete/` | 1 |
| `/turbo_engine/api/v2` | POST | `/turbo_engine/api/v2/event/user_virtual_prop/opt/` | 1 |
| `/turbo_engine/api/v3` | POST | `/turbo_engine/api/v3/subscribe/create/` | 1 |
| `/turbo_engine/api/v3` | POST | `/turbo_engine/api/v3/subscribe/edit/` | 1 |

## `unresolved_body_expression`

A literal grep of `route-params.json` returns **0**, but a replay of the current extractor's
in-memory shapes over the hash-matched raw snapshot finds **82 call sites across 60 routes**.
This is the complete reason count, not a count of 82 statically inlinable functions: the
reason also covers other runtime expressions. Of the 82 sites, 81 remain body locations and
one is a GET request factory whose frontend `body` key is normalized to the query location.

| Route prefix | Routes |
| --- | ---: |
| `/turbo_engine/api/v1` | 34 |
| `/report/api/v3` | 14 |
| `/turbo_engine/api/v2` | 4 |
| `/account_center/api/v1` | 3 |
| `/turbo_engine/api/v3` | 3 |
| `/apprank/api/v1` | 1 |
| `/report/api/v1` | 1 |
| **Total** | **60** |

| Coverage status | Routes |
| --- | ---: |
| `uncovered_write` | 45 |
| `covered` | 7 |
| `uncovered_export` | 4 |
| `uncovered_auth_or_proxy` | 3 |
| `uncovered_read` | 1 |
| **Total** | **60** |

The sole uncovered read is D35's `POST /report/api/v3/adreport/attribution/`, with two
`Gt(...)` call sites. The other routes are outside the requested read-product leverage or
already covered.

The grep discrepancy is caused by serialization, not by a different snapshot. In
`_field_to_shape`, an unresolved `body` expression produces the reason
`unresolved_body_expression` on an in-memory `_Shape`. `_parse_call_envelope` then collapses
that shape to a location in `_CallShape.unresolved_locations`. `_route_document` serializes
only the count `analysis.unresolved_calls`, while `analysis.unresolved_reasons` is populated
from occurrence-level results such as `load_alias_has_no_static_call`. The body-expression
reason text is therefore absent from JSON. The artifact contains only a lossy proxy: 70
unresolved calls across 38 routes where an unresolved location had no recovered fields;
that proxy cannot reconstruct the full 82 call sites across 60 routes.

## Journey cross-check

### Fifteen completely missing journeys

**Current blockers caused by either extractor failure: 0 of 15.** Every ledger row was
checked rather than inferred from route-prefix similarity.

| Journey | Route intersection | Why it is not unlocked |
| --- | --- | --- |
| Analysis default-value dictionary | Direct: one alias occurrence; the other occurrence already extracts `app_id` and `subject` | Current blockers are server-required semantics and response projection/schema, not missing frontend names. |
| Realtime-event catalogue | None on its target route | Target body is already extracted; semantic error, pagination, and response schema remain. |
| Analysis/report settings | None on its target route | Complete value-independent binding and response projection remain unknown. |
| Own/shared/MasterKey reports and definitions | No blocker-level intersection | Empty parents/items and response privacy/schema remain. |
| Report subscriptions | Only adjacent subscription write/test routes | Read-only semantics, request contract, pagination, and response schema remain. |
| Media reports | No blocker-level intersection | Trusted App/platform binding and a non-empty item remain. |
| Readable App projects | Only adjacent project-create write route | Non-empty item and privacy projection remain. |
| OneLink and public App binding | Only already-covered App-detail/helper routes | Trusted URL/parent binding and non-empty response remain. |
| D28 monetization aggregate | None on its target route | Account/platform binding and a non-empty aggregate remain. |
| D35 attribution aggregate | Three alias occurrences plus two `Gt(...)` call sites | The 16-field frontend builder and omission rules were already recovered manually. Current blocker is successful or explicit-empty server evidence and allowed values. |
| F40 single-user attribution detail | None on its target route; indirectly depends on D35 | Approved identifier source, binding, pagination, response and privacy remain even if D35 advances. |
| F41 current table schema/version | None on its target routes | Non-empty parent, `table_id` type, current-version semantics and privacy remain. |
| D33/D34 non-Bytedance drilldown | Only adjacent account/batch/helper routes | Parent chains are data-blocked and target item/pagination evidence remains. |
| D32 platform-specific assets/creative | Some adjacent asset/tool routes occur in the alias set | The journey is data-blocked at account/advertiser parents and lacks non-empty target samples; helper-route shapes do not close it. |
| Analysis exports | Direct event/material/export routes occur in both sets | Independent privacy approval and file/response schema blockers remain; roadmap treats nine exports as a closed boundary, not an engineering schedule gap. |

Thus two named candidate routes intersect directly (`analysis.default_val.list` and D35),
and two journey groups have adjacent route evidence, but **none** would lose its current
blocker after the proposed extractor work.

### Twelve partially closed journeys

**Current blockers caused by either extractor failure: 0 of 12.**

| Journey | Route intersection | Current blocker unaffected by extraction |
| --- | --- | --- |
| Dashboard detail/member/favourites | Covered favourite/helper alias routes | Unknown reference still costs a third call. |
| D22 dashboard condition replay | Covered query/funnel/scatter body expressions and favourite alias route | Page/chart condition conflict semantics and third-call discovery remain. |
| Saved-analysis replay | Covered analysis execution helpers | Unknown reference still costs a third call. |
| Analysis-template replay | Covered analysis/template helpers | Unknown reference and artifact isolation remain. |
| Segment detail/version/snapshot | Covered segment-list alias and rule-evaluation expression | Unknown reference still costs a third call. |
| Multidimensional report | Covered custom-report expression/helper | Unknown physical vocabulary still costs a third call. |
| Promotion performance | Covered account and metric-catalogue alias routes | Unknown physical metric still costs a third call. |
| Offline analysis metadata discovery | Covered event/property/metric alias routes | Missing local catalogue still requires sync. |
| Table version/change observation | No blocker-level intersection | Missing local catalogue still requires sync; current schema is F41. |
| Material-analysis export | Direct export-expression intersection | Missing Plan surface remains. |
| Legacy arbitrary promotion snapshot | Covered promotion/account helper aliases | Missing Plan and Agent surfaces remain. |
| Stable metadata snapshot | Covered metadata/helper aliases | Missing dedicated CLI, Plan and Agent surfaces remain. |

The intersecting routes are already covered or already have independently extracted
parameters. Better request extraction does not remove any ledger blocker.

## D35 and measurable effect

Because the leverage threshold was not met, no parser change was made. D35 remains exactly:

- 5 route occurrences;
- 2 analyzed calls whose `body:Gt(...)` is unresolved;
- 3 unresolved conditional-callee occurrences;
- `body_parameters=[]`.

No mechanical comparison against the manually recovered 16 fields was performed, because
there is no new extraction result to compare. The repository-wide count of routes with
non-empty `body_parameters` remains **675 -> 675**.

## Change-volume result

- Added `src/` lines: 0.
- Added `tests/` lines: 0.
- Test/source ratio: not applicable (`0/0`); the one-third ceiling is satisfied.
- Census data artifacts regenerated: none.
- Operation contracts and stable operations changed: none.

## Remaining uncertainty

- The 82-call replay is exact for the committed snapshot and current parser, but the raw
  bundle directory is an external sibling-worktree cache. Its identity was mitigated by
  checking every file hash against the committed snapshot.
- Static route-to-journey mapping cannot prove that an unlisted helper route will never be
  useful later. The decision is scoped to the 15 missing and 12 partial journeys' **current**
  blockers, not a claim that the extractor capabilities have no future value.
- The JSON schema currently hides the body-expression reason text. Fixing that observability
  loss alone could be useful in a future Census-maintenance round, but it would not unlock a
  scheduled analysis journey and is outside this unit's leverage threshold.
- The 60/82 expression-reason count is an upper bound for function-inlining opportunities;
  classifying which expressions are pure constructors would itself require the proposed
  static-analysis work. This does not weaken the no-fix decision because only one of the 60
  routes is an uncovered read, and D35's frontend shape is already known.

## Final validation tails

All commands used `./.venv/Scripts/python.exe` where applicable and matched the baseline
counts.

```text
python -m unittest discover -s tests
Ran 742 tests in 41.484s
OK

python -m pytest -q
974 passed, 2489 subtests passed in 48.72s

python -m gravity_sdk.compiler check
check: 185 operations, 11 manifests

python -m gravity_sdk.quality check
PASS gravity-insight-quality: operations=185, provenance=185, operation_literals=57 (ratcheted)

python -m gravity_sdk census coverage --require-accounted
accounted=987, accounting_complete=true, covered=172, unaccounted=0, unclassified=0

git diff --check
exit 0, no output
```
