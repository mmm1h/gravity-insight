# CT03 Deterministic Skill Hub Build

| Field | Value |
| --- | --- |
| Status | `fixed_dev` |
| Canonical input | `skills/library/*.json` |
| Builder | `scripts/generate_skill_library.py` |
| Publication target | GitHub Release `skill-library-v1` |

## Contract

The builder reads the canonical library once and deterministically renders
human docs, unpacked package files, reproducible ZIP archives, `index.json`,
`source.json`, and `build-manifest.json`. ZIP timestamps, ordering, permissions,
and compression are fixed. The generated tree lives under `build/skill-hub/`
and is ignored by Git.

The same output tree is uploaded as one GitHub Release payload. `source.json`
uses `static_https`, and `index.json` archive paths resolve relative to the
release base URL. Building does not publish, push, tag, or make a network call.

## Acceptance

```powershell
D:/git-pjt/_wt_vendor/.venv/Scripts/python.exe scripts/generate_skill_library.py --check
D:/git-pjt/_wt_vendor/.venv/Scripts/python.exe scripts/generate_skill_library.py
```

The check validates registry bindings, namespaces, `zh-CN` defaults, schema
contracts, archive contents, two-pass byte equality, and the absence of tracked
ZIP or legacy generated mirrors.
