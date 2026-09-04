from __future__ import annotations

import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urljoin, urlsplit

import requests

from gravity_insight.paths import STATE_ROOT
from gravity_insight.receipt import (
    PRODUCTION_HTTP_KIND,
    perform_http_request,
    request_receipt_context,
)
from .io import CensusFetchError as _FetchError, census_entry_build_info, census_local_relative, census_looks_like_vite_chunk, census_manifest_assets, http_status_class, safe_url_host, sha256_bytes, stable_bundle_id, write_json


DEFAULT_SITE = "https://web.gravity-engine.com/"
DEFAULT_USER_AGENT = "GravityRouteCensus/1.0 (+public-static-assets-only)"
MANIFEST_CANDIDATES = ("/.vite/manifest.json", "/manifest.json", "/assets/manifest.json")
_JS_STRINGS = re.compile(
    r"(?P<quote>['\"`])(?P<value>[^'\"`\r\n\s]{1,500}?\.js(?:\?[^'\"`\s]*)?)(?P=quote)"
)
_BUILD_INFO = re.compile(r"window\.BUILD_INFO\s*=\s*(\{.*?\})\s*</script>", re.DOTALL)
_VITE_CHUNK_NAME = re.compile(
    r"^.+-(?=[A-Za-z0-9_-]{8}\.js$)(?=[A-Za-z0-9_-]*[A-Z0-9_])[A-Za-z0-9_-]{8}\.js$"
)


class _EntryHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.module_scripts: list[str] = []
        self.module_preloads: list[str] = []
        self.manifests: list[str] = []
        self.other_scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "script" and values.get("src"):
            if values.get("type", "").lower() == "module":
                self.module_scripts.append(values["src"])
            else:
                self.other_scripts.append(values["src"])
        if tag.lower() == "link" and values.get("href"):
            rel = set(values.get("rel", "").lower().split())
            if "modulepreload" in rel:
                self.module_preloads.append(values["href"])
            if "manifest" in rel:
                self.manifests.append(values["href"])


def _local_relative(url: str, *, default_name: str = "index.html") -> Path:
    return census_local_relative(url, default_name)


def _extract_js_references(text: str, base_url: str) -> list[str]:
    values: set[str] = set()
    for match in _JS_STRINGS.finditer(text):
        raw = match.group("value").replace(r"\/", "/")
        if raw.startswith(("data:", "blob:")) or "${" in raw:
            continue
        candidate = urljoin(base_url, raw)
        parsed = urlsplit(candidate)
        if parsed.scheme in {"http", "https"} and parsed.path.lower().endswith(".js"):
            values.add(candidate)
    return sorted(values)


def _looks_like_vite_chunk(url: str) -> bool:
    return census_looks_like_vite_chunk(url, _VITE_CHUNK_NAME)


def _manifest_assets(value: Any) -> Iterable[str]:
    yield from census_manifest_assets(value)


def _entry_build_info(html_text: str) -> dict[str, Any]:
    return census_entry_build_info(html_text, _BUILD_INFO)


class StaticFetcher:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        max_attempts: int = 3,
        max_requests: int = 800,
        concurrency: int = 4,
        timeout: float = 45.0,
        local_capacity_retries: int = 2,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        if not 1 <= concurrency <= 4:
            raise ValueError("concurrency must be between 1 and 4")
        if not 0 <= local_capacity_retries <= 2:
            raise ValueError("local_capacity_retries must be between 0 and 2")
        self.max_attempts = max_attempts
        self.max_requests = max_requests
        self.concurrency = concurrency
        self.timeout = timeout
        self.local_capacity_retries = local_capacity_retries
        self.attempts = 0
        self.local_capacity_retries_used = 0
        self.user_agent = user_agent
        self._attempt_lock = threading.Lock()
        self._thread_local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": self.user_agent, "Accept": "*/*"})
            self._thread_local.session = session
        return session

    def _reserve_attempt(self) -> bool:
        with self._attempt_lock:
            if self.attempts >= self.max_requests:
                return False
            self.attempts += 1
            return True

    def _record_pre_network_failure(self, error: BaseException) -> None:
        with self._attempt_lock:
            self.attempts -= 1
            error.census_request_attempts = self.attempts
            error.census_request_limit = self.max_requests
            error.census_local_capacity_retries_used = self.local_capacity_retries_used

    def _record_local_capacity_retry(self) -> None:
        with self._attempt_lock:
            self.local_capacity_retries_used += 1

    def _get(self, url: str) -> requests.Response:
        last_error: Exception | None = None
        last_status: int | None = None
        for attempt in range(self.max_attempts):
            if not self._reserve_attempt():
                raise _FetchError(
                    f"request budget exhausted for host={safe_url_host(url)}", url=url,
                    status_class="request_budget_exhausted", request_attempts=self.attempts,
                    request_limit=self.max_requests,
                    local_capacity_retries_used=self.local_capacity_retries_used)
            try:
                response = perform_http_request(
                    self._session().get, url, kind=PRODUCTION_HTTP_KIND,
                    timeout=self.timeout, allow_redirects=True,
                    http_receipt={**request_receipt_context(
                        operation_id="census_fetch", method="GET",
                        path=urlsplit(url).path, effect="read"),
                        "attempt": attempt + 1, "retry": attempt > 0},
                    receipt_root=STATE_ROOT,
                    governor_context={"profile": "census", "attempt_budget": self.max_attempts,
                        "timeout_seconds": self.timeout,
                        "local_capacity_retries": self.local_capacity_retries,
                        "local_capacity_backoff_seconds": 0.05,
                        "local_capacity_retry_observer": self._record_local_capacity_retry,
                        "pre_network_failure": self._record_pre_network_failure})
                last_status = response.status_code
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    raise _FetchError(
                        f"GET returned non-retryable HTTP {response.status_code} "
                        f"for host={safe_url_host(url)}", url=url,
                        status_code=response.status_code, status_class="client_error",
                        request_attempts=self.attempts, request_limit=self.max_requests,
                        local_capacity_retries_used=self.local_capacity_retries_used)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                last_status = status if type(status) is int else last_status
                if attempt + 1 < self.max_attempts and self.attempts < self.max_requests:
                    time.sleep(0.25 * (2**attempt))
        status_class = http_status_class(last_status)
        raise _FetchError(
            f"GET failed after {self.max_attempts} attempts for host={safe_url_host(url)}; "
            f"status_class={status_class}", url=url, status_code=last_status,
            status_class=status_class if status_class != "unknown" else "transport_error",
            exception_type=type(last_error).__name__ if status_class == "unknown" else None,
            request_attempts=self.attempts, request_limit=self.max_requests,
            local_capacity_retries_used=self.local_capacity_retries_used)

    @staticmethod
    def _validate_js_content(
        content: bytes, url: str, content_type: str = ""
    ) -> dict[str, Any]:
        prefix = content[:256].lstrip().lower()
        html = prefix.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))
        if not content or html or "text/html" in content_type.casefold():
            raise _FetchError(
                f"GET did not return complete static JS for host={safe_url_host(url)}",
                url=url, status_class="content_incomplete")
        return {"status": "validated_static_js", "nonempty": True,
                "html_body_rejected": False, "http_200_alone_sufficient": False}

    def _fetch_js(self, url: str, raw_dir: Path) -> dict[str, Any]:
        requested_local = _local_relative(url, default_name="bundle.js")
        requested_target = raw_dir / requested_local
        reused = requested_target.is_file()
        if reused:
            content = requested_target.read_bytes()
            final_url = url
            local_path = requested_local
            text = content.decode("utf-8", errors="replace")
            validation = self._validate_js_content(content, url)
        else:
            response = self._get(url)
            content = response.content
            final_url = str(response.url)
            local_path = _local_relative(final_url, default_name="bundle.js")
            target = raw_dir / local_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            text = content.decode(response.encoding or "utf-8", errors="replace")
            validation = self._validate_js_content(
                content, final_url, str(getattr(response, "headers", {}).get("Content-Type", ""))
            )
        return {
            "requested_url": url,
            "url": final_url,
            "local_path": local_path.as_posix(),
            "sha256": sha256_bytes(content),
            "size": len(content),
            "text": text,
            "reused": reused,
            "content_validation": validation,
        }

    def _entry_seeds(
        self, site_url: str, raw_dir: Path, probe_manifests: bool
    ) -> dict[str, Any]:
        response = self._get(site_url)
        html_bytes = response.content
        html_text = html_bytes.decode(response.encoding or "utf-8", errors="replace")
        html_url = str(response.url)
        html_local = _local_relative(html_url)
        (raw_dir / html_local).parent.mkdir(parents=True, exist_ok=True)
        (raw_dir / html_local).write_bytes(html_bytes)
        parser = _EntryHTMLParser()
        parser.feed(html_text)
        entry_urls = sorted({urljoin(html_url, item) for item in parser.module_scripts})
        preload_urls = sorted({urljoin(html_url, item) for item in parser.module_preloads})
        if not entry_urls:
            raise _FetchError(
                f"entry HTML contains no module script for host={safe_url_host(html_url)}",
                url=html_url,
                status_class="content_incomplete",
                request_attempts=self.attempts,
                request_limit=self.max_requests,
                local_capacity_retries_used=self.local_capacity_retries_used,
            )
        build_info = _entry_build_info(html_text)
        manifest_urls = {urljoin(html_url, item) for item in parser.manifests}
        if probe_manifests:
            manifest_urls.update(urljoin(html_url, item) for item in MANIFEST_CANDIDATES)
        manifest_results: list[dict[str, Any]] = []
        manifest_seed_urls: set[str] = set()
        for manifest_url in sorted(manifest_urls):
            try:
                manifest_response = self._get(manifest_url)
                content_type = manifest_response.headers.get("Content-Type", "")
                parsed = manifest_response.json() if "json" in content_type.lower() else None
                if not isinstance(parsed, (dict, list)):
                    manifest_results.append(
                        {"url": manifest_url, "status": "not_json", "content_type": content_type}
                    )
                    continue
                assets = sorted({urljoin(manifest_url, item) for item in _manifest_assets(parsed)})
                manifest_seed_urls.update(assets)
                manifest_results.append({"url": manifest_url, "status": "parsed", "assets": assets})
            except (_FetchError, requests.JSONDecodeError, ValueError) as exc:
                manifest_results.append({"url": manifest_url, "status": "unavailable", "error": str(exc)})
        return {
            "bytes": html_bytes, "url": html_url, "local": html_local, "parser": parser,
            "entry_urls": entry_urls, "preload_urls": preload_urls, "build_info": build_info,
            "manifest_results": manifest_results, "manifest_seed_urls": sorted(manifest_seed_urls),
        }

    def _fetch_batch(
        self,
        batch: list[str],
        raw_dir: Path,
        fetched: set[str],
        failures: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
        executor: ThreadPoolExecutor,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        futures = {executor.submit(self._fetch_js, url, raw_dir): url for url in batch}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results.append(future.result())
            except _FetchError as exc:
                if exc.status_code == 404 and not _looks_like_vite_chunk(url):
                    rejected.append(
                        {"url": url, "status_code": 404,
                         "reason": "lexical .js candidate is not a deployed Vite hash chunk"}
                    )
                    fetched.add(url)
                else:
                    failures.append(
                        {
                            "url": url,
                            "host": exc.host,
                            "status_class": exc.status_class,
                            "status_code": exc.status_code,
                            "exception_type": exc.exception_type,
                            "error": str(exc),
                        }
                    )
        return sorted(results, key=lambda item: item["requested_url"])

    def _crawl_static_graph(self, seeds: Sequence[str], raw_dir: Path) -> dict[str, Any]:
        queue = deque(seeds)
        discovered = set(queue)
        fetched: set[str] = set()
        allowed_origins = {(urlsplit(url).scheme, urlsplit(url).netloc) for url in seeds}
        external_references: set[str] = set()
        failures: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []
        signals = {"vite_map_deps": False, "webpack_chunk_loader": False}
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            while queue:
                batch: list[str] = []
                while queue and len(batch) < self.concurrency:
                    url = queue.popleft()
                    if url not in fetched:
                        batch.append(url)
                if not batch:
                    continue
                for result in self._fetch_batch(
                    batch, raw_dir, fetched, failures, rejected, executor
                ):
                    url = result["requested_url"]
                    final_url = result["url"]
                    text = result.pop("text")
                    signals["vite_map_deps"] |= "__vite__mapDeps" in text
                    signals["webpack_chunk_loader"] |= any(
                        signal in text for signal in (
                            "__webpack_require__.u", ".miniCssF=", "webpackChunk"
                        )
                    )
                    references = []
                    for reference in _extract_js_references(text, final_url):
                        parsed_reference = urlsplit(reference)
                        if (parsed_reference.scheme, parsed_reference.netloc) in allowed_origins:
                            references.append(reference)
                        else:
                            external_references.add(reference)
                    for reference in references:
                        if reference not in discovered:
                            discovered.add(reference)
                            queue.append(reference)
                    fetched.add(url)
                    result.pop("requested_url")
                    result["references"] = references
                    files.append(result)
                if self.attempts >= self.max_requests and queue:
                    break
        files.sort(key=lambda item: item["url"])
        return {
            "files": files, "discovered": discovered, "fetched": fetched,
            "external_references": external_references, "failures": failures,
            "rejected": rejected, "signals": signals,
        }

    def _entry_remained_stable(
        self, site_url: str, entry: dict[str, Any], failures: list[dict[str, Any]]
    ) -> bool:
        try:
            response = self._get(site_url)
            final_html = response.content
            parser = _EntryHTMLParser()
            parser.feed(final_html.decode(response.encoding or "utf-8", errors="replace"))
            final_entries = sorted(
                {urljoin(str(response.url), item) for item in parser.module_scripts}
            )
            if final_entries == entry["entry_urls"] and sha256_bytes(final_html) == sha256_bytes(entry["bytes"]):
                return True
            failures.append(
                {
                    "url": site_url,
                    "host": safe_url_host(site_url),
                    "status_class": "content_incomplete",
                    "status_code": None,
                    "exception_type": None,
                    "error": "entry HTML changed while static graph was being fetched",
                }
            )
        except _FetchError as exc:
            failures.append(
                {
                    "url": site_url,
                    "host": exc.host,
                    "status_class": exc.status_class,
                    "status_code": exc.status_code,
                    "exception_type": exc.exception_type,
                    "error": "final entry verification failed",
                }
            )
        return False

    def _build_snapshot(
        self, site_url: str, entry: dict[str, Any], crawl: dict[str, Any], started: float
    ) -> dict[str, Any]:
        files = crawl["files"]
        failures = crawl["failures"]
        rejected = crawl["rejected"]
        pending = sorted(crawl["discovered"] - crawl["fetched"])
        complete = not pending and not failures
        if complete:
            complete = self._entry_remained_stable(site_url, entry, failures)
        if complete:
            reason = (
                f"all {len(files)} deployed same-origin Vite JS chunks fetched; "
                f"{len(rejected)} lexical .js candidates resolved as HTTP 404 "
                "non-resources; entry HTML remained stable"
            )
        elif pending:
            hosts = sorted({safe_url_host(url) for url in pending})
            reason = (
                f"{len(pending)} recursively discovered JS URLs remain pending "
                f"across hosts: {', '.join(hosts)}"
            )
        else:
            reason = f"{len(failures)} static resource failures: " + "; ".join(
                f"host={item.get('host', safe_url_host(str(item.get('url', ''))))} "
                f"status_class={item.get('status_class', 'unknown')}"
                for item in failures
            )
        parser = entry["parser"]
        return {
            "schema_version": 1,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "site_url": site_url,
            "html": {"url": entry["url"], "local_path": entry["local"].as_posix(),
                     "sha256": sha256_bytes(entry["bytes"]), "size": len(entry["bytes"])},
            "build_info": entry["build_info"],
            "entry_urls": entry["entry_urls"],
            "modulepreload_urls": entry["preload_urls"],
            "ignored_nonmodule_scripts": sorted(
                {urljoin(entry["url"], item) for item in parser.other_scripts}
            ),
            "manifest_probes": entry["manifest_results"],
            "bundle_id": stable_bundle_id(files),
            "files": files,
            "summary": {
                "bundle_files": len(files), "bundle_bytes": sum(item["size"] for item in files),
                "discovered_js": len(crawl["discovered"]), "pending_js": len(pending),
                "failed_js": len(failures), "rejected_non_resource_candidates": len(rejected),
                "request_attempts": self.attempts, "request_limit": self.max_requests,
                "concurrency": self.concurrency,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "complete": complete, "completeness_reason": reason,
                "local_capacity_retries_used": self.local_capacity_retries_used,
                "local_capacity_retry_limit": self.local_capacity_retries,
            },
            "discovery": {
                "strategies": ["HTML module scripts", "HTML modulepreload links",
                               "linked and conventional Vite/Webpack manifests",
                               "recursive JS string-literal imports and chunk maps"],
                "signals": crawl["signals"], "pending_urls": pending, "failures": failures,
                "rejected_non_resource_candidates": sorted(rejected, key=lambda item: item["url"]),
                "ignored_cross_origin_js": sorted(crawl["external_references"]),
            },
        }

    def fetch(
        self,
        *,
        site_url: str,
        raw_dir: Path,
        snapshot_path: Path,
        probe_manifests: bool = True,
    ) -> dict[str, Any]:
        started = time.monotonic()
        site_url = site_url if site_url.endswith("/") else site_url + "/"
        raw_dir.mkdir(parents=True, exist_ok=True)
        write_json(snapshot_path, {"schema_version": 1, "site_url": site_url, "files": [], "summary": {"complete": False, "completeness_reason": "crawl started without a terminal static graph", "request_attempts": self.attempts, "request_limit": self.max_requests}})
        entry = self._entry_seeds(site_url, raw_dir, probe_manifests)
        seeds = entry["entry_urls"] + entry["preload_urls"] + entry["manifest_seed_urls"]
        snapshot = self._build_snapshot(
            site_url, entry, self._crawl_static_graph(seeds, raw_dir), started
        )
        write_json(snapshot_path, snapshot)
        return snapshot


def check_upstream(
    site_url: str,
    baseline: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    fetcher = StaticFetcher(max_attempts=3, max_requests=3, timeout=timeout)
    response = fetcher._get(site_url)
    text = response.content.decode(response.encoding or "utf-8", errors="replace")
    parser = _EntryHTMLParser()
    parser.feed(text)
    current_entries = sorted({urljoin(str(response.url), item) for item in parser.module_scripts})
    baseline_entries = sorted(str(item) for item in baseline.get("entry_urls", []))
    build_info = _entry_build_info(text)
    return {
        "schema_version": 1,
        "site_url": site_url,
        "request_attempts": fetcher.attempts,
        "baseline_entry_urls": baseline_entries,
        "current_entry_urls": current_entries,
        "entry_changed": current_entries != baseline_entries,
        "baseline_html_sha256": baseline.get("html", {}).get("sha256"),
        "current_html_sha256": sha256_bytes(response.content),
        "html_changed": sha256_bytes(response.content) != baseline.get("html", {}).get("sha256"),
        "upstream_changed": (
            current_entries != baseline_entries
            or sha256_bytes(response.content) != baseline.get("html", {}).get("sha256")
        ),
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "build_info": build_info,
        "note": "No JS was downloaded; hashed entry filenames are the lightweight content-version signal.",
    }
