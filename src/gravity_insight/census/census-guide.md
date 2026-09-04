# Gravity frontend route census guide

This tool inventories API-looking route literals reachable from the current public Gravity
frontend entry, reconciles them with stable Gravity Insight operations, and emits deterministic
JSON plus a scheduling report.

## Safety and scope

`fetch` sends GET requests only to the public entry HTML, conventional static manifest paths,
and same-origin JavaScript candidates. It does not log in, load credentials, call business APIs,
or send writes. The default concurrency is 4, retries are capped at 3 attempts, and every request
uses the `GravityRouteCensus` user agent.

`summary.complete=true` means every recursively discovered same-origin `.js` candidate was
resolved, all deployed Vite hash chunks were downloaded, there are no pending or failed chunk
URLs, and the entry HTML stayed byte-stable during the crawl. Lexical `.js` strings that return
404 and do not match the deployed Vite chunk naming scheme are recorded separately as rejected
non-resource candidates. A hashed chunk returning 404 remains a hard failure.

This proves completeness only for the current public-entry static graph. It does not prove the
existence or absence of modules delivered only after login, tenant/role checks, server feature
flags, or a different entry document. Expanding that boundary requires authorized authenticated
captures for each relevant role, tenant, and flag combination, followed by the same crawl and a
snapshot diff.

It also cannot prove runtime-composed URLs, backend behavior changes behind an unchanged route,
request/response semantic changes without a probe, or whether a route removed from the frontend is
still accepted by the backend. The impact report therefore schedules probes as a separate evidence
source; auth and permission failures are never treated as route drift.

## Reproduce

```powershell
gravity census fetch --require-complete --raw-dir tmp/codex/gi-census-full/final --output tmp/codex/gi-census-full/bundle-snapshot.json --step-output tmp/codex/gi-census-full/census-step-output.json
gravity census parse --snapshot tmp/codex/gi-census-full/bundle-snapshot.json --raw-dir tmp/codex/gi-census-full/final --output tmp/codex/gi-census-full/routes.json
gravity census coverage --routes tmp/codex/gi-census-full/routes.json --require-complete --require-accounted --output tmp/codex/gi-census-full/coverage.json --report tmp/codex/gi-census-full/coverage-report.md
gravity census diff <reviewed-routes.json> <current-routes.json> --output <route-diff.json>
gravity census impact <route-diff.json> --output <operation-impact.json> --overlay-output <health-overlay-candidate.json> --require-complete
```

`fetch` 需联网；文档一致性校对未执行。其余命令可使用已存在的完整 snapshot/raw bundles
离线复验；尖括号参数必须替换为实际文件路径。

`impact` follows `contracts/generated/provenance.json` to each operation source contract, builds a
normalized method/path reverse index, and emits affected operation IDs, family/platform/level
context, priority, suggested actions, and a schedule-only targeted probe plan. It never edits a
contract and never calls a business API. The GitHub Actions workflow uploads this plan for an
authorized runner or reviewer to execute separately.

## Response field candidates

Response consumers can be extracted from a separately captured bundle without replacing the
reviewed route-census artifacts:

```powershell
gravity census fetch --require-complete --max-requests 800 --concurrency 4 --raw-dir tmp/codex/gi-respfields/bundle --output tmp/codex/gi-respfields/bundle-snapshot.json
gravity census parse --snapshot tmp/codex/gi-respfields/bundle-snapshot.json --raw-dir tmp/codex/gi-respfields/bundle --output tmp/codex/gi-respfields/routes.json
gravity census responses --snapshot tmp/codex/gi-respfields/bundle-snapshot.json --routes tmp/codex/gi-respfields/routes.json --raw-dir tmp/codex/gi-respfields/bundle --output src/gravity_insight/census/data/route-response-fields.json
gravity census apply-responses --responses src/gravity_insight/census/data/route-response-fields.json --drafts src/gravity_insight/contracts/drafts
```

The response artifact stores field paths and source locations, never response values or source
snippets. Only consumers lexically bound to the exact route are emitted. Applying the artifact is
fail-closed: new entries are `unknown`, `manual_review`, and `expose=false`; existing probe-derived
candidates win, and `response_projection` is never changed.

## Scheduled cost

The hourly `check-upstream` job performs one successful public HTML GET and allows at most three
attempts for transient network failures. It records the HTML digest, hashed entry URLs, ETag, and
Last-Modified; no JavaScript or business endpoint is fetched in this phase. A changed HTML digest
or entry URL triggers the complete static crawl.

The changed-entry crawl always writes `census-step-output.json`; failures also write a sanitized
`fetch-failure.json`. The closed `failure_class` set is `upstream_capacity`,
`local_governor_capacity`, `request_budget_exhausted`, `transport_failure`, `http_client_error`,
`http_server_error`, `content_incomplete`, and `unclassified`. The last class includes source code,
status class, exception type, and a classification reason. Diagnostics never include URL paths,
userinfo, query values, headers, exception messages, credentials, or response values. HTTP 429 is
`upstream_capacity`; Governor queue/registry/wait saturation is `local_governor_capacity`; 5xx and
transport failures retain their distinct classes even when their observations open the circuit.

The schedule performs at most three one-attempt crawl rounds for `upstream_capacity`, reusing
already downloaded raw bundles. It waits at least the 30-second circuit cooldown, capped at 60
seconds per backoff. Each network attempt independently allows at most two local Governor-capacity
retries with 50/100 ms backoff; pre-network denials are refunded from the upstream request budget.
Non-capacity Governor errors are not retried. Exhausted capacity rounds produce structured evidence
and no route-drift conclusion; all other incomplete results fail closed. The single process Governor
and its shared total capacity remain unchanged, and Census concurrency remains capped at four.

Diff requires both inputs to explicitly prove bundle completeness. Missing completeness is unknown,
not success. An incomplete input produces a withheld marker with empty change sets; impact does not
map operations, update health state, or schedule a probe plan from that marker. A 200 response also
does not prove JS content: empty and HTML bodies are rejected, and completeness still requires
validated JS resources, graph closure, no failures, and stable entry HTML.

The reviewed baseline crawl used 504 request attempts to fetch 375 deployed chunks, reject 122
lexical non-resource candidates, probe public manifests, and verify that the entry HTML remained
stable. This is the observed cost of the current graph, not a fixed budget: the hard request cap is
800 and future bundle graphs can cost more or less.

The reviewed baseline is checked in. A detected change therefore remains visible on later runs
until a human reviews and promotes the new snapshot and any contract updates.

## Current scoring evidence

The scheduled workflow is the producer for current drift evidence. It runs the lightweight entry
check hourly, triggers a complete crawl immediately when that check changes, and also performs one
complete crawl every day at `01:47Z`. The daily crawl keeps an unchanged baseline measurable without
turning every hourly check into a several-hundred-request bundle crawl.

After a complete crawl passes the scoring self-check, the workflow uploads a dedicated
`gravity-census-current-<run-id>` artifact containing a `gravity-census.step-output.v1` receipt,
the current snapshot, and a route diff. Check-only and failed runs cannot publish this artifact;
their always-uploaded `gravity-upstream-<run-id>` artifact remains diagnostic only. A successful
receipt records the snapshot's `observed_at` and `bundle_id`. `census status` accepts the chain only
when the receipt is complete, the diff is complete, both current bundle IDs match, and the diff's
old bundle ID matches the checked-in baseline. Artifacts produced before those two receipt fields
were added are accepted only when a same-directory snapshot has exactly the receipt summary and
supplies the matching bundle ID and `fetched_at`.

`tmp/census-current/` is the local, ignored landing directory. Download a successful run into its
own subdirectory; both `gravity census status --json` and `gravity maturity score --json` discover
it without network access:

```powershell
$repo = gh repo view --json nameWithOwner --jq '.nameWithOwner'
$artifacts = gh api "repos/$repo/actions/artifacts?per_page=100" | ConvertFrom-Json
$artifact = $artifacts.artifacts | Where-Object { $_.name -like 'gravity-census-current-*' } | Sort-Object created_at -Descending | Select-Object -First 1
if ($null -eq $artifact) { throw 'Owner input missing: no complete gravity-census-current artifact is available.' }
gh run download $artifact.workflow_run.id --name $artifact.name --dir "tmp/census-current/$($artifact.id)"
gravity census status --json
gravity maturity score --json
```

An observation is current through 26 hours after `observed_at`, allowing the daily schedule up to
two hours of runner delay. At 26 hours plus one second its measurement resolution is `expired`,
not `not_measured`; artifact retention does not extend freshness. A timestamp more than five
minutes in the future is `invalid`. A complete chain bound to another reviewed baseline is
`not_applicable`, while an absent chain is `not_measured`. All four unavailable states keep the
dimension at `measured=false` and block the gate, but the specific status and reason code remain in
`current.measurement`. Malformed JSON evidence is `invalid`, not absent. Context objects match
exactly, so an unrecognized producer context field cannot be silently ignored. Downloading an
artifact does not rewrite its observation time.

To reproduce the one-time comparison with the previous partial census, retain its routes file and
pass it explicitly:

```powershell
gravity census coverage `
  --baseline-routes tmp/codex/gi-census-full/previous-routes.json `
  --require-complete --require-accounted `
  --output tmp/codex/gi-census-full/coverage-with-baseline.json `
  --report tmp/codex/gi-census-full/coverage-with-baseline.md
```

The default raw asset directory is `tmp/codex/gi-census-full/final/`. Raw bundles are temporary
evidence and are not intended for Git. Canonical generated outputs are:

- `data/bundle-snapshot.json`
- `data/routes.json`
- `data/coverage.json`
- `data/coverage-report.md`
- `data/route-response-fields.json`

## Interpretation

Route method certainty is independent from read/write semantics. `UNKNOWN` is retained when the
target HTTP method is not encoded in static code, especially for media `query_api` proxy targets,
API catalogs, and documentation literals. The outer proxy POST is not assigned to its target.

`covered` requires a stable manifest operation with the same method and normalized path. Path
comparison ignores trailing slashes, case, and dynamic parameter names, but the emitted path keeps
its source form. Manifest reconciliation is operation-oriented and separates routes newly found in
previously unfetched chunks, normalization-only matches, and manifest claims absent from the full
public static graph.

Contract-family and implementation-cost fields are scheduling heuristics. Families require at
least two uncovered promotion reads with either the same level across platforms or multiple levels
on one platform. Cost tiers mean flat list/detail (low), parent-resource dependency (medium), and
complex query/report/proxy or dynamic fields (high). They are not observed delivery estimates.

## Verification

```powershell
python -m unittest discover -s tests -p "test_gravity_census*.py"
python -m tools.common.validate_all
```

The parser sorts all files, occurrences, evidence, and routes before serialization. JSON output
uses sorted keys and a fixed UTF-8/LF encoding, so identical snapshot bytes and raw inputs produce
identical `routes.json` bytes.
