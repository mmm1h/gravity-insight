# Gravity Insight 代码质量门禁

> 本文由 `python -m gravity_sdk.quality profile --markdown-out docs/governance/GravityInsight代码质量门禁.md` 从当前工作树生成。

## 口径与结论

- runtime/CLI 文件 SLOC 上限 `500`；函数 SLOC 上限 `80`；圈复杂度上限 `15`。
- SLOC 使用 tokenize 统计非空、非纯注释物理行；函数包含装饰器，圈复杂度采用 McCabe-compatible 分支计数。
- 圈复杂度从 1 起计，增加 if/条件表达式、循环及其 else、except/try else、布尔分支、assert、推导式分支和非默认 match case；外层函数不累计嵌套函数。
- operation ID 使用编译器产出的精确 ID 集合做 AST 字符串常量匹配，不使用宽泛正则。
- 文件/函数范围为递归 `src/gravity_sdk` 与顶层运行时 CLI；build-time compiler/prober 和门禁自身不纳入产品代码债务。
- 保留蓝图的 500/80/15：500 足以容纳单个完整引擎，80/15 与常用可评审函数边界一致；本仓存量由 ratchet 承接，无需放松绝对阈值。
- 将蓝图的 dotted-string 正则改为编译 catalog 精确 ID 集合：这样既能抓到两段式 `app.list`，也不会把普通模块名或配置路径误判为 operation。
- 确定性编译：`PASS`；provenance：`150/150`。
- 当前 runtime/CLI SLOC `36529`；全 `src/**/*.py` SLOC `37827`。
- 总债务：文件超额 `8073` SLOC，函数超额 `4868` SLOC，复杂度超额 `2118`，operation 字面量 `77` 个。
- operation 字面量没有永久语义白名单；下表全部是上线时存量 ratchet，目标阈值仍为 0。

## 逐文件债务

| 文件 | 当前 SLOC | 文件超额 | 超长函数数/超额 | 高复杂函数数/超额 | operation 字面量 |
|---|---:|---:|---:|---:|---:|
| `src/gravity_sdk/blob_archive.py` | 95 | 0 | 0/0 | 2/10 | 0 |
| `src/gravity_sdk/blob_headers.py` | 153 | 0 | 2/48 | 2/16 | 0 |
| `src/gravity_sdk/blob_policy.py` | 360 | 0 | 2/6 | 2/40 | 0 |
| `src/gravity_sdk/blob_transfer.py` | 423 | 0 | 4/290 | 4/26 | 0 |
| `src/gravity_sdk/catalog.py` | 715 | 215 | 4/66 | 8/34 | 12 |
| `src/gravity_sdk/census/cli.py` | 228 | 0 | 2/32 | 2/30 | 0 |
| `src/gravity_sdk/census/coverage.py` | 890 | 390 | 4/538 | 8/108 | 0 |
| `src/gravity_sdk/census/diffing.py` | 107 | 0 | 0/0 | 2/18 | 0 |
| `src/gravity_sdk/census/fetcher.py` | 421 | 0 | 2/276 | 2/66 | 0 |
| `src/gravity_sdk/census/impact.py` | 335 | 0 | 2/182 | 2/32 | 0 |
| `src/gravity_sdk/census/params.py` | 1568 | 1068 | 8/402 | 12/136 | 0 |
| `src/gravity_sdk/census/parser.py` | 399 | 0 | 2/38 | 2/28 | 0 |
| `src/gravity_sdk/census/response.py` | 551 | 51 | 2/12 | 6/14 | 0 |
| `src/gravity_sdk/cli.py` | 1272 | 772 | 8/484 | 8/118 | 0 |
| `src/gravity_sdk/client.py` | 1400 | 900 | 4/182 | 10/64 | 10 |
| `src/gravity_sdk/composite.py` | 424 | 0 | 2/28 | 6/22 | 5 |
| `src/gravity_sdk/credentials.py` | 483 | 0 | 0/0 | 6/18 | 0 |
| `src/gravity_sdk/executor.py` | 1482 | 982 | 12/236 | 14/152 | 12 |
| `src/gravity_sdk/governance/stable_privacy.py` | 282 | 0 | 0/0 | 2/34 | 0 |
| `src/gravity_sdk/http_runtime.py` | 681 | 181 | 0/0 | 2/14 | 0 |
| `src/gravity_sdk/models.py` | 1078 | 578 | 4/148 | 10/188 | 0 |
| `src/gravity_sdk/prober/batch.py` | 592 | 92 | 4/490 | 4/144 | 2 |
| `src/gravity_sdk/prober/cli.py` | 314 | 0 | 2/124 | 2/8 | 0 |
| `src/gravity_sdk/prober/draft_probe.py` | 406 | 0 | 2/16 | 0/0 | 0 |
| `src/gravity_sdk/prober/drafts.py` | 1806 | 1306 | 8/802 | 20/330 | 0 |
| `src/gravity_sdk/prober/export_verify.py` | 655 | 155 | 2/44 | 0/0 | 2 |
| `src/gravity_sdk/prober/parameters.py` | 588 | 88 | 2/42 | 6/80 | 14 |
| `src/gravity_sdk/prober/privacy.py` | 423 | 0 | 0/0 | 4/22 | 7 |
| `src/gravity_sdk/prober/promotion.py` | 594 | 94 | 2/42 | 6/98 | 0 |
| `src/gravity_sdk/prober/reprobe.py` | 481 | 0 | 4/134 | 4/26 | 0 |
| `src/gravity_sdk/prober/verdict_probe.py` | 341 | 0 | 0/0 | 2/6 | 0 |
| `src/gravity_sdk/registry.py` | 1146 | 646 | 0/0 | 2/18 | 13 |
| `src/gravity_sdk/sql/__main__.py` | 151 | 0 | 2/76 | 2/32 | 0 |
| `src/gravity_sdk/sql/client.py` | 244 | 0 | 0/0 | 2/16 | 0 |
| `src/gravity_sdk/sql/credentials.py` | 327 | 0 | 0/0 | 2/2 | 0 |
| `src/gravity_sdk/sql/products.py` | 1055 | 555 | 2/74 | 4/96 | 0 |
| `src/gravity_sdk/support/evidence.py` | 404 | 0 | 2/56 | 2/70 | 0 |
| `src/gravity_sdk/transport.py` | 132 | 0 | 0/0 | 2/2 | 0 |

## 超限函数

| 文件::函数 | 行 | SLOC/超额 | 圈复杂度/超额 |
|---|---:|---:|---:|
| `src/gravity_sdk/blob_archive.py::_inspect_zip` | 35 | 56/0 | 20/5 |
| `src/gravity_sdk/blob_archive.py::_inspect_zip` | 35 | 56/0 | 20/5 |
| `src/gravity_sdk/blob_headers.py::_preflight_headers` | 28 | 104/24 | 23/8 |
| `src/gravity_sdk/blob_headers.py::_preflight_headers` | 28 | 104/24 | 23/8 |
| `src/gravity_sdk/blob_policy.py::BlobPolicy.__post_init__` | 41 | 83/3 | 35/20 |
| `src/gravity_sdk/blob_policy.py::BlobPolicy.__post_init__` | 41 | 83/3 | 35/20 |
| `src/gravity_sdk/blob_transfer.py::SafeBlobTransfer.download` | 41 | 190/110 | 25/10 |
| `src/gravity_sdk/blob_transfer.py::SafeBlobTransfer.download` | 41 | 190/110 | 25/10 |
| `src/gravity_sdk/blob_transfer.py::SafeBlobTransfer.upload` | 237 | 115/35 | 18/3 |
| `src/gravity_sdk/blob_transfer.py::SafeBlobTransfer.upload` | 237 | 115/35 | 18/3 |
| `src/gravity_sdk/catalog.py::CapabilityCatalog.search` | 155 | 84/4 | 19/4 |
| `src/gravity_sdk/catalog.py::CapabilityCatalog.search` | 155 | 84/4 | 19/4 |
| `src/gravity_sdk/catalog.py::CapabilityCatalog.describe` | 241 | 109/29 | 19/4 |
| `src/gravity_sdk/catalog.py::CapabilityCatalog.describe` | 241 | 109/29 | 19/4 |
| `src/gravity_sdk/catalog.py::CapabilityCatalog.coverage` | 442 | 32/0 | 19/4 |
| `src/gravity_sdk/catalog.py::CapabilityCatalog.coverage` | 442 | 32/0 | 19/4 |
| `src/gravity_sdk/catalog.py::_infer_target_input` | 703 | 47/0 | 20/5 |
| `src/gravity_sdk/catalog.py::_infer_target_input` | 703 | 47/0 | 20/5 |
| `src/gravity_sdk/census/cli.py::run` | 146 | 96/16 | 30/15 |
| `src/gravity_sdk/census/cli.py::run` | 146 | 96/16 | 30/15 |
| `src/gravity_sdk/census/coverage.py::identify_contract_families` | 340 | 59/0 | 18/3 |
| `src/gravity_sdk/census/coverage.py::identify_contract_families` | 340 | 59/0 | 18/3 |
| `src/gravity_sdk/census/coverage.py::reconcile_stable_operations` | 401 | 68/0 | 17/2 |
| `src/gravity_sdk/census/coverage.py::reconcile_stable_operations` | 401 | 68/0 | 17/2 |
| `src/gravity_sdk/census/coverage.py::build_coverage` | 472 | 265/185 | 60/45 |
| `src/gravity_sdk/census/coverage.py::build_coverage` | 472 | 265/185 | 60/45 |
| `src/gravity_sdk/census/coverage.py::render_report` | 740 | 164/84 | 19/4 |
| `src/gravity_sdk/census/coverage.py::render_report` | 740 | 164/84 | 19/4 |
| `src/gravity_sdk/census/diffing.py::diff_routes` | 14 | 64/0 | 24/9 |
| `src/gravity_sdk/census/diffing.py::diff_routes` | 14 | 64/0 | 24/9 |
| `src/gravity_sdk/census/fetcher.py::StaticFetcher.fetch` | 193 | 218/138 | 48/33 |
| `src/gravity_sdk/census/fetcher.py::StaticFetcher.fetch` | 193 | 218/138 | 48/33 |
| `src/gravity_sdk/census/impact.py::locate_route_impacts` | 139 | 171/91 | 31/16 |
| `src/gravity_sdk/census/impact.py::locate_route_impacts` | 139 | 171/91 | 31/16 |
| `src/gravity_sdk/census/params.py::_tokenize` | 119 | 108/28 | 19/4 |
| `src/gravity_sdk/census/params.py::_tokenize` | 119 | 108/28 | 19/4 |
| `src/gravity_sdk/census/params.py::_infer_expression` | 442 | 200/120 | 49/34 |
| `src/gravity_sdk/census/params.py::_infer_expression` | 442 | 200/120 | 49/34 |
| `src/gravity_sdk/census/params.py::_extract_occurrence` | 1018 | 104/24 | 19/4 |
| `src/gravity_sdk/census/params.py::_extract_occurrence` | 1018 | 104/24 | 19/4 |
| `src/gravity_sdk/census/params.py::_route_document` | 1333 | 73/0 | 21/6 |
| `src/gravity_sdk/census/params.py::_route_document` | 1333 | 73/0 | 21/6 |
| `src/gravity_sdk/census/params.py::_batch_validation` | 1468 | 109/29 | 30/15 |
| `src/gravity_sdk/census/params.py::_batch_validation` | 1468 | 109/29 | 30/15 |
| `src/gravity_sdk/census/params.py::_summary` | 1581 | 44/0 | 20/5 |
| `src/gravity_sdk/census/params.py::_summary` | 1581 | 44/0 | 20/5 |
| `src/gravity_sdk/census/parser.py::build_routes` | 338 | 99/19 | 29/14 |
| `src/gravity_sdk/census/parser.py::build_routes` | 338 | 99/19 | 29/14 |
| `src/gravity_sdk/census/response.py::_binding_alias` | 58 | 23/0 | 16/1 |
| `src/gravity_sdk/census/response.py::_binding_alias` | 58 | 23/0 | 16/1 |
| `src/gravity_sdk/census/response.py::_callback_parameter` | 114 | 36/0 | 17/2 |
| `src/gravity_sdk/census/response.py::_callback_parameter` | 114 | 36/0 | 17/2 |
| `src/gravity_sdk/census/response.py::apply_response_fields_to_drafts` | 508 | 86/6 | 19/4 |
| `src/gravity_sdk/census/response.py::apply_response_fields_to_drafts` | 508 | 86/6 | 19/4 |
| `src/gravity_sdk/cli.py::_redact` | 160 | 66/0 | 22/7 |
| `src/gravity_sdk/cli.py::_redact` | 160 | 66/0 | 22/7 |
| `src/gravity_sdk/cli.py::build_parser` | 303 | 225/145 | 3/0 |
| `src/gravity_sdk/cli.py::build_parser` | 303 | 225/145 | 3/0 |
| `src/gravity_sdk/cli.py::_merge_query_shortcuts` | 612 | 117/37 | 33/18 |
| `src/gravity_sdk/cli.py::_merge_query_shortcuts` | 612 | 117/37 | 33/18 |
| `src/gravity_sdk/cli.py::_analysis` | 760 | 91/11 | 28/13 |
| `src/gravity_sdk/cli.py::_analysis` | 760 | 91/11 | 28/13 |
| `src/gravity_sdk/cli.py::run` | 1028 | 129/49 | 36/21 |
| `src/gravity_sdk/cli.py::run` | 1028 | 129/49 | 36/21 |
| `src/gravity_sdk/client.py::GravityInsightClient.probe_all` | 298 | 64/0 | 18/3 |
| `src/gravity_sdk/client.py::GravityInsightClient.probe_all` | 298 | 64/0 | 18/3 |
| `src/gravity_sdk/client.py::GravityInsightClient._resolve_probe_inputs` | 363 | 49/0 | 27/12 |
| `src/gravity_sdk/client.py::GravityInsightClient._resolve_probe_inputs` | 363 | 49/0 | 27/12 |
| `src/gravity_sdk/client.py::GravityInsightClient._first_probe_order_field` | 622 | 58/0 | 18/3 |
| `src/gravity_sdk/client.py::GravityInsightClient._first_probe_order_field` | 622 | 58/0 | 18/3 |
| `src/gravity_sdk/client.py::GravityInsightClient._read_limited_untracked` | 857 | 158/78 | 24/9 |
| `src/gravity_sdk/client.py::GravityInsightClient._read_limited_untracked` | 857 | 158/78 | 24/9 |
| `src/gravity_sdk/client.py::GravityInsightClient._read_all_untracked` | 1019 | 93/13 | 20/5 |
| `src/gravity_sdk/client.py::GravityInsightClient._read_all_untracked` | 1019 | 93/13 | 20/5 |
| `src/gravity_sdk/composite.py::CompositeService.metadata_snapshot` | 66 | 74/0 | 18/3 |
| `src/gravity_sdk/composite.py::CompositeService.metadata_snapshot` | 66 | 74/0 | 18/3 |
| `src/gravity_sdk/composite.py::CompositeService.promotion_snapshot` | 179 | 94/14 | 19/4 |
| `src/gravity_sdk/composite.py::CompositeService.promotion_snapshot` | 179 | 94/14 | 19/4 |
| `src/gravity_sdk/composite.py::CompositeService._validate_multidim` | 274 | 67/0 | 19/4 |
| `src/gravity_sdk/composite.py::CompositeService._validate_multidim` | 274 | 67/0 | 19/4 |
| `src/gravity_sdk/credentials.py::CredentialProvider._get` | 246 | 48/0 | 19/4 |
| `src/gravity_sdk/credentials.py::CredentialProvider._get` | 246 | 48/0 | 19/4 |
| `src/gravity_sdk/credentials.py::CredentialProvider._credential_from_login` | 408 | 30/0 | 18/3 |
| `src/gravity_sdk/credentials.py::CredentialProvider._credential_from_login` | 408 | 30/0 | 18/3 |
| `src/gravity_sdk/credentials.py::_atomic_update_env` | 452 | 45/0 | 17/2 |
| `src/gravity_sdk/credentials.py::_atomic_update_env` | 452 | 45/0 | 17/2 |
| `src/gravity_sdk/executor.py::ReadExecutor.execute` | 120 | 92/12 | 12/0 |
| `src/gravity_sdk/executor.py::ReadExecutor.execute` | 120 | 92/12 | 12/0 |
| `src/gravity_sdk/executor.py::_project` | 235 | 87/7 | 24/9 |
| `src/gravity_sdk/executor.py::_project` | 235 | 87/7 | 24/9 |
| `src/gravity_sdk/executor.py::_project_analysis_user_event` | 324 | 88/8 | 28/13 |
| `src/gravity_sdk/executor.py::_project_analysis_user_event` | 324 | 88/8 | 28/13 |
| `src/gravity_sdk/executor.py::_project_user_event_timeline` | 416 | 41/0 | 17/2 |
| `src/gravity_sdk/executor.py::_project_user_event_timeline` | 416 | 41/0 | 17/2 |
| `src/gravity_sdk/executor.py::_project_user_event_summary` | 498 | 37/0 | 17/2 |
| `src/gravity_sdk/executor.py::_project_user_event_summary` | 498 | 37/0 | 17/2 |
| `src/gravity_sdk/executor.py::_project_analysis_value` | 656 | 86/6 | 24/9 |
| `src/gravity_sdk/executor.py::_project_analysis_value` | 656 | 86/6 | 24/9 |
| `src/gravity_sdk/executor.py::_project_data_containers` | 858 | 119/39 | 33/18 |
| `src/gravity_sdk/executor.py::_project_data_containers` | 858 | 119/39 | 33/18 |
| `src/gravity_sdk/executor.py::_project_list_rows` | 1093 | 126/46 | 38/23 |
| `src/gravity_sdk/executor.py::_project_list_rows` | 1093 | 126/46 | 38/23 |
| `src/gravity_sdk/governance/stable_privacy.py::operation_exposure_paths` | 110 | 53/0 | 32/17 |
| `src/gravity_sdk/governance/stable_privacy.py::operation_exposure_paths` | 110 | 53/0 | 32/17 |
| `src/gravity_sdk/http_runtime.py::_GravityRequester.request` | 294 | 77/0 | 22/7 |
| `src/gravity_sdk/http_runtime.py::_GravityRequester.request` | 294 | 77/0 | 22/7 |
| `src/gravity_sdk/models.py::InputField.from_value` | 257 | 79/0 | 40/25 |
| `src/gravity_sdk/models.py::InputField.from_value` | 257 | 79/0 | 40/25 |
| `src/gravity_sdk/models.py::InputField.validate` | 336 | 53/0 | 31/16 |
| `src/gravity_sdk/models.py::InputField.validate` | 336 | 53/0 | 31/16 |
| `src/gravity_sdk/models.py::OperationSpec.from_dict` | 746 | 130/50 | 59/44 |
| `src/gravity_sdk/models.py::OperationSpec.from_dict` | 746 | 130/50 | 59/44 |
| `src/gravity_sdk/models.py::OperationSpec.validate_inputs` | 888 | 36/0 | 23/8 |
| `src/gravity_sdk/models.py::OperationSpec.validate_inputs` | 888 | 36/0 | 23/8 |
| `src/gravity_sdk/models.py::OperationSpec.schema` | 942 | 104/24 | 13/0 |
| `src/gravity_sdk/models.py::OperationSpec.schema` | 942 | 104/24 | 13/0 |
| `src/gravity_sdk/models.py::load_operation_manifest` | 1133 | 31/0 | 16/1 |
| `src/gravity_sdk/models.py::load_operation_manifest` | 1133 | 31/0 | 16/1 |
| `src/gravity_sdk/prober/batch.py::run_batch_probes` | 209 | 214/134 | 47/32 |
| `src/gravity_sdk/prober/batch.py::run_batch_probes` | 209 | 214/134 | 47/32 |
| `src/gravity_sdk/prober/batch.py::finalize_batch_report` | 430 | 191/111 | 55/40 |
| `src/gravity_sdk/prober/batch.py::finalize_batch_report` | 430 | 191/111 | 55/40 |
| `src/gravity_sdk/prober/cli.py::run` | 183 | 142/62 | 19/4 |
| `src/gravity_sdk/prober/cli.py::run` | 183 | 142/62 | 19/4 |
| `src/gravity_sdk/prober/draft_probe.py::probe_draft` | 341 | 88/8 | 13/0 |
| `src/gravity_sdk/prober/draft_probe.py::probe_draft` | 341 | 88/8 | 13/0 |
| `src/gravity_sdk/prober/drafts.py::select_routes` | 141 | 37/0 | 21/6 |
| `src/gravity_sdk/prober/drafts.py::select_routes` | 141 | 37/0 | 21/6 |
| `src/gravity_sdk/prober/drafts.py::_domain_from_route` | 208 | 36/0 | 22/7 |
| `src/gravity_sdk/prober/drafts.py::_domain_from_route` | 208 | 36/0 | 22/7 |
| `src/gravity_sdk/prober/drafts.py::_resource_action` | 252 | 72/0 | 40/25 |
| `src/gravity_sdk/prober/drafts.py::_resource_action` | 252 | 72/0 | 40/25 |
| `src/gravity_sdk/prober/drafts.py::structured_blockers` | 567 | 183/103 | 59/44 |
| `src/gravity_sdk/prober/drafts.py::structured_blockers` | 567 | 183/103 | 59/44 |
| `src/gravity_sdk/prober/drafts.py::build_conservative_draft` | 771 | 86/6 | 2/0 |
| `src/gravity_sdk/prober/drafts.py::build_conservative_draft` | 771 | 86/6 | 2/0 |
| `src/gravity_sdk/prober/drafts.py::create_bulk_drafts` | 1065 | 233/153 | 46/31 |
| `src/gravity_sdk/prober/drafts.py::create_bulk_drafts` | 1065 | 233/153 | 46/31 |
| `src/gravity_sdk/prober/drafts.py::classify_mutation_kind.base_kind` | 1347 | 34/0 | 17/2 |
| `src/gravity_sdk/prober/drafts.py::classify_mutation_kind.base_kind` | 1347 | 34/0 | 17/2 |
| `src/gravity_sdk/prober/drafts.py::_mutation_risk` | 1394 | 73/0 | 26/11 |
| `src/gravity_sdk/prober/drafts.py::_mutation_risk` | 1394 | 73/0 | 26/11 |
| `src/gravity_sdk/prober/drafts.py::_auth_proxy_decision` | 1615 | 29/0 | 17/2 |
| `src/gravity_sdk/prober/drafts.py::_auth_proxy_decision` | 1615 | 29/0 | 17/2 |
| `src/gravity_sdk/prober/drafts.py::create_write_registry` | 1678 | 219/139 | 49/34 |
| `src/gravity_sdk/prober/drafts.py::create_write_registry` | 1678 | 219/139 | 49/34 |
| `src/gravity_sdk/prober/drafts.py::_apply_method_evidence` | 1905 | 28/0 | 18/3 |
| `src/gravity_sdk/prober/drafts.py::_apply_method_evidence` | 1905 | 28/0 | 18/3 |
| `src/gravity_sdk/prober/export_verify.py::ExportVerificationRunner._download_and_inspect` | 414 | 102/22 | 11/0 |
| `src/gravity_sdk/prober/export_verify.py::ExportVerificationRunner._download_and_inspect` | 414 | 102/22 | 11/0 |
| `src/gravity_sdk/prober/parameters.py::assemble_source_parameters` | 157 | 69/0 | 23/8 |
| `src/gravity_sdk/prober/parameters.py::assemble_source_parameters` | 157 | 69/0 | 23/8 |
| `src/gravity_sdk/prober/parameters.py::_parent_candidate` | 274 | 45/0 | 30/15 |
| `src/gravity_sdk/prober/parameters.py::_parent_candidate` | 274 | 45/0 | 30/15 |
| `src/gravity_sdk/prober/parameters.py::bind_stable_parent_candidates` | 321 | 101/21 | 32/17 |
| `src/gravity_sdk/prober/parameters.py::bind_stable_parent_candidates` | 321 | 101/21 | 32/17 |
| `src/gravity_sdk/prober/privacy.py::_mapping_projection` | 345 | 60/0 | 24/9 |
| `src/gravity_sdk/prober/privacy.py::_mapping_projection` | 345 | 60/0 | 24/9 |
| `src/gravity_sdk/prober/privacy.py::projection_exposes_path` | 424 | 38/0 | 17/2 |
| `src/gravity_sdk/prober/privacy.py::projection_exposes_path` | 424 | 38/0 | 17/2 |
| `src/gravity_sdk/prober/promotion.py::evaluate_gate` | 58 | 62/0 | 35/20 |
| `src/gravity_sdk/prober/promotion.py::evaluate_gate` | 58 | 62/0 | 35/20 |
| `src/gravity_sdk/prober/promotion.py::_legacy_privacy_evidence_reusable` | 365 | 63/0 | 36/21 |
| `src/gravity_sdk/prober/promotion.py::_legacy_privacy_evidence_reusable` | 365 | 63/0 | 36/21 |
| `src/gravity_sdk/prober/promotion.py::reevaluate_drafts` | 483 | 101/21 | 23/8 |
| `src/gravity_sdk/prober/promotion.py::reevaluate_drafts` | 483 | 101/21 | 23/8 |
| `src/gravity_sdk/prober/reprobe.py::run_parameter_reprobes` | 276 | 134/54 | 25/10 |
| `src/gravity_sdk/prober/reprobe.py::run_parameter_reprobes` | 276 | 134/54 | 25/10 |
| `src/gravity_sdk/prober/reprobe.py::run_scoped_reprobes` | 417 | 93/13 | 18/3 |
| `src/gravity_sdk/prober/reprobe.py::run_scoped_reprobes` | 417 | 93/13 | 18/3 |
| `src/gravity_sdk/prober/verdict_probe.py::_string_profile` | 75 | 30/0 | 18/3 |
| `src/gravity_sdk/prober/verdict_probe.py::_string_profile` | 75 | 30/0 | 18/3 |
| `src/gravity_sdk/registry.py::_request_parts` | 340 | 53/0 | 24/9 |
| `src/gravity_sdk/registry.py::_request_parts` | 340 | 53/0 | 24/9 |
| `src/gravity_sdk/sql/__main__.py::main` | 34 | 118/38 | 31/16 |
| `src/gravity_sdk/sql/__main__.py::main` | 34 | 118/38 | 31/16 |
| `src/gravity_sdk/sql/client.py::_extract_rows` | 262 | 30/0 | 23/8 |
| `src/gravity_sdk/sql/client.py::_extract_rows` | 262 | 30/0 | 23/8 |
| `src/gravity_sdk/sql/credentials.py::self_test` | 320 | 53/0 | 16/1 |
| `src/gravity_sdk/sql/credentials.py::self_test` | 320 | 53/0 | 16/1 |
| `src/gravity_sdk/sql/products.py::summarize_events` | 546 | 53/0 | 22/7 |
| `src/gravity_sdk/sql/products.py::summarize_events` | 546 | 53/0 | 22/7 |
| `src/gravity_sdk/sql/products.py::validate_evidence` | 667 | 117/37 | 56/41 |
| `src/gravity_sdk/sql/products.py::validate_evidence` | 667 | 117/37 | 56/41 |
| `src/gravity_sdk/support/evidence.py::validate_evidence_manifest` | 256 | 108/28 | 50/35 |
| `src/gravity_sdk/support/evidence.py::validate_evidence_manifest` | 256 | 108/28 | 50/35 |
| `src/gravity_sdk/transport.py::Transport.request` | 94 | 52/0 | 16/1 |
| `src/gravity_sdk/transport.py::Transport.request` | 94 | 52/0 | 16/1 |

## operation 字面量分布

| 文件 | 数量 | 不同 ID 数 |
|---|---:|---:|
| `src/gravity_sdk/catalog.py` | 12 | 12 |
| `src/gravity_sdk/client.py` | 10 | 10 |
| `src/gravity_sdk/composite.py` | 5 | 5 |
| `src/gravity_sdk/executor.py` | 12 | 6 |
| `src/gravity_sdk/prober/batch.py` | 2 | 2 |
| `src/gravity_sdk/prober/export_verify.py` | 2 | 1 |
| `src/gravity_sdk/prober/parameters.py` | 14 | 8 |
| `src/gravity_sdk/prober/privacy.py` | 7 | 7 |
| `src/gravity_sdk/registry.py` | 13 | 13 |

## 本轮未设硬门的蓝图指标

runtime 密度暂不设硬门，因为当前低密度存量尚无稳定拆分归因；family override 比例、契约完整度和 census 由并行契约/探测任务演进，当前接入会形成重复或竞态权威；family 测试增长无法仅凭测试名可靠判断同构实例。它们应在各自数据源稳定后接入本门禁，而不是以易误伤的启发式先占位。

## Ratchet

机器基线位于 `src/gravity_sdk/governance/quality-baseline.json`。当前超过 500/80/15/0 的存量按文件或函数身份记录；当前值只能等于或低于基线。下降后门禁要求运行 `python -m gravity_sdk.quality baseline --write` 收紧基线。CI 还会与 PR base 的 baseline 比较，拒绝新增条目或放宽数值。
