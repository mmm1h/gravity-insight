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
gravity census fetch --require-complete --raw-dir tmp/codex/gi-census-full/final --output tmp/codex/gi-census-full/bundle-snapshot.json
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

The changed-entry crawl writes a sanitized `fetch-failure.json` containing a stable code,
`failure_class`, lane host/hashed host key/operation/profile, the three bounded triggering
failures with status class, optional HTTP status or transport exception type, cooldown remaining,
and `next_action`. It never includes URL paths, userinfo, query values, headers, exception messages,
credentials, or response values. `upstream_capacity` is emitted only when every causal failure is
`transport_error`, `rate_limited`, or `server_error`.

The schedule performs at most three one-attempt crawl rounds, reusing already downloaded raw
bundles so outer retries do not multiply the existing three-attempt resource budget. It waits at
least the 30-second circuit cooldown, capped at 60 seconds per backoff. Exhausted capacity rounds
produce a GitHub warning and no route-drift conclusion. Mixed, budget, entry-stability, parsing, or
other completeness failures remain hard failures. The governor threshold remains three actual HTTP
attempts per scope/host/operation/profile lane; increasing it for a large bundle count would let one
capacity-constrained host absorb more traffic without adding evidence.

The reviewed baseline crawl used 504 request attempts to fetch 375 deployed chunks, reject 122
lexical non-resource candidates, probe public manifests, and verify that the entry HTML remained
stable. This is the observed cost of the current graph, not a fixed budget: the hard request cap is
800 and future bundle graphs can cost more or less.

The reviewed baseline is checked in. A detected change therefore remains visible on later runs
until a human reviews and promotes the new snapshot and any contract updates.

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
