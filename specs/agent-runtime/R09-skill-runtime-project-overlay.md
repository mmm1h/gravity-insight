# R09 Superseded Skill Runtime Overview

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `superseded` |
| Replacement | R09A, R09B, R09C |

The original R09 combined Core Skill Runtime, Team Hub binding and External Context binding behind one dependency barrier. It is no longer an executable Requirement.

- [R09A](R09A-core-skill-runtime.md) delivers Built-in Skill Runtime and Project Overlay without remote Hub or external Provider dependencies.
- [R09B](R09B-team-hub-binding.md) adds exact Team Hub lock/CAS binding.
- [R09C](R09C-external-context-binding.md) adds explicitly declared external Context dependencies.

Historical implementation discussion may cite R09, but all new status, Issue, branch and acceptance tracking uses the replacement leaf IDs.
