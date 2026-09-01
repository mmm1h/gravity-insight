# CT03 Deterministic Skill Hub Build

| Field | Value |
| --- | --- |
| Status | `fixed_dev` |
| Canonical input | `skills/library/*.json` |
| Builder | `scripts/generate_skill_library.py` |
| Publication target | GitHub Release `skill-library-v1` |

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
to the release base URL. Building does not publish, push, tag, or make a network
call. The v2 build receipt keeps the complete local QA file list separate from
the exact flat `release_assets` list.

## Acceptance

```powershell
D:/git-pjt/_wt_vendor/.venv/Scripts/python.exe scripts/generate_skill_library.py --check
D:/git-pjt/_wt_vendor/.venv/Scripts/python.exe scripts/generate_skill_library.py
```

The check validates registry bindings, namespaces, `zh-CN` defaults, schema
contracts, Runtime and Agent archive contents, two-pass byte equality, and the
absence of tracked ZIP or legacy generated mirrors.
