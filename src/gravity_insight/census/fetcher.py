from __future__ import annotations

import json
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

from .io import sha256_bytes, stable_bundle_id, write_json


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


class _FetchError(RuntimeError):
    def __init__(self, message: str, *, url: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code


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
    parsed = urlsplit(url)
    relative = parsed.path.lstrip("/") or default_name
    path = Path("raw") / parsed.netloc / relative
    if parsed.query:
        path = path.with_name(path.name + ".q-" + sha256_bytes(parsed.query.encode())[:12])
    return path


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
    parsed = urlsplit(url)
    return parsed.path.startswith("/assets/") and bool(
        _VITE_CHUNK_NAME.fullmatch(Path(parsed.path).name)
    )


def _manifest_assets(value: Any) -> Iterable[str]:
    if isinstance(value, str) and value.split("?", 1)[0].endswith(".js"):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _manifest_assets(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _manifest_assets(nested)


def _entry_build_info(html_text: str) -> dict[str, Any]:
    match = _BUILD_INFO.search(html_text)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(1))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {"raw": match.group(1)}


class StaticFetcher:
    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        max_attempts: int = 3,
        max_requests: int = 800,
        concurrency: int = 4,
        timeout: float = 45.0,
    ) -> None:
        if not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        if not 1 <= concurrency <= 4:
            raise ValueError("concurrency must be between 1 and 4")
        self.max_attempts = max_attempts
        self.max_requests = max_requests
        self.concurrency = concurrency
        self.timeout = timeout
        self.attempts = 0
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

    def _get(self, url: str) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            if not self._reserve_attempt():
                raise _FetchError("request budget exhausted", url=url)
            try:
                response = perform_http_request(
                    self._session().get,
                    url,
                    kind=PRODUCTION_HTTP_KIND,
                    timeout=self.timeout,
                    allow_redirects=True,
                    http_receipt={
                        **request_receipt_context(
                            operation_id="census_fetch",
                            method="GET",
                            path=urlsplit(url).path,
                            effect="read",
                        ),
                        "attempt": attempt + 1,
                        "retry": attempt > 0,
                    },
                    receipt_root=STATE_ROOT,
                )
                if 400 <= response.status_code < 500:
                    raise _FetchError(
                        f"GET returned non-retryable HTTP {response.status_code}: {url}",
                        url=url,
                        status_code=response.status_code,
                    )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < self.max_attempts and self.attempts < self.max_requests:
                    time.sleep(0.25 * (2**attempt))
        raise _FetchError(
            f"GET failed after {self.max_attempts} attempts: {url}: {last_error}", url=url
        )

    def _fetch_js(self, url: str, raw_dir: Path) -> dict[str, Any]:
        requested_local = _local_relative(url, default_name="bundle.js")
        requested_target = raw_dir / requested_local
        reused = requested_target.is_file()
        if reused:
            content = requested_target.read_bytes()
            final_url = url
            local_path = requested_local
            text = content.decode("utf-8", errors="replace")
        else:
            response = self._get(url)
            content = response.content
            final_url = str(response.url)
            local_path = _local_relative(final_url, default_name="bundle.js")
            target = raw_dir / local_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            text = content.decode(response.encoding or "utf-8", errors="replace")
        return {
            "requested_url": url,
            "url": final_url,
            "local_path": local_path.as_posix(),
            "sha256": sha256_bytes(content),
            "size": len(content),
            "text": text,
            "reused": reused,
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
            raise RuntimeError("HTML contains no module entry script")
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
            except (RuntimeError, requests.JSONDecodeError, ValueError) as exc:
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
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
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
                            {"url": url, "status_code": exc.status_code, "error": str(exc)}
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
        while queue:
            batch: list[str] = []
            while queue and len(batch) < self.concurrency:
                url = queue.popleft()
                if url not in fetched:
                    batch.append(url)
            if not batch:
                continue
            for result in self._fetch_batch(batch, raw_dir, fetched, failures, rejected):
                url = result["requested_url"]
                final_url = result["url"]
                text = result.pop("text")
                signals["vite_map_deps"] |= "__vite__mapDeps" in text
                signals["webpack_chunk_loader"] |= any(
                    signal in text for signal in ("__webpack_require__.u", ".miniCssF=", "webpackChunk")
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
            failures.append({"url": site_url, "error": "entry HTML changed while static graph was being fetched"})
        except RuntimeError as exc:
            failures.append({"url": site_url, "error": f"final entry verification failed: {exc}"})
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
            reason = f"{len(pending)} recursively discovered JS URLs remain pending: " + "; ".join(pending)
        else:
            reason = f"{len(failures)} static resource failures: " + "; ".join(
                f"{item['url']} ({item['error']})" for item in failures
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
    build_info: dict[str, Any] = {}
    match = _BUILD_INFO.search(text)
    if match:
        try:
            value = json.loads(match.group(1))
            if isinstance(value, dict):
                build_info = value
        except json.JSONDecodeError:
            pass
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
