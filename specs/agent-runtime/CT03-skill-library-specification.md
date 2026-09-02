# CT03 Deterministic Skill Hub Build

| Field | Value |
| --- | --- |
| Status | `fixed_dev` |
| Canonical input | `skills/library/*.json` |
| Builder | `scripts/generate_skill_library.py` |
| Publication target | GitHub Release `skill-library-v4` |

## Contract

The builder reads the canonical library once and deterministically renders
human docs, unpacked Runtime package files, reproducible Runtime ZIP archives,
`index.json`, `source.json`, and `build-manifest.json`. Under CT04 the same pass
also renders standard Agent Skill directories, reproducible Agent Skill ZIPs,
and `agent-index.json`. ZIP timestamps, ordering, permissions, and compression
are fixed. The generated tree lives under `build/skill-hub/` and is ignored by
Git. ZIPs referenced by the Runtime and Agent indexes use globally unique flat
asset names so the GitHub Release download base can address them directly. The
unpacked tree is local QA material only.

Publication uploads both indexes, the Agent index schema, `source.json`, the
build receipt, and the flat ZIP assets referenced by the two indexes.
`source.json` uses `static_https`, and both index archive paths resolve relative
to the release base URL. A Source may name a bounded exact redirect-host allowlist;
the Runtime follows at most one HTTPS redirect and retains byte-budget plus digest
verification. Building does not publish, push, tag, or make a network call. The
v2 build receipt keeps the complete local QA file list separate from the exact
flat `release_assets` list.

The earlier `skill-library-v1`, `skill-library-v2`, and `skill-library-v3`
publications remain immutable. The current builder targets v4; it does not
overwrite or delete earlier assets. V4 retains the Runtime-authored AP-cost
reference method on the canonical Hub channel and adds the explicit GitHub Release
CDN redirect boundary; it does not restore a wheel-owned business Skill registry.

## Acceptance

```powershell
D:/git-pjt/_wt_vendor/.venv/Scripts/python.exe scripts/generate_skill_library.py --check
D:/git-pjt/_wt_vendor/.venv/Scripts/python.exe scripts/generate_skill_library.py
```

The check validates registry bindings, namespaces, `zh-CN` defaults, schema
contracts, Runtime and Agent archive contents, two-pass byte equality, and the
absence of tracked ZIP or legacy generated mirrors.
