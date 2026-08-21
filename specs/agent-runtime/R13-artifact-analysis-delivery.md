# R13 Superseded Artifact And Delivery Overview

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9.1` via `directive.json` |
| Status | `superseded` |
| Replacement | R13A, R13B, R13C |

The original R13 coupled binary transfer, target-independent analysis rendering and Gravity Dashboard mutation. It is no longer an executable Requirement.

- [R13A](R13A-artifact-transfer.md) closes governed binary transfer through the real materials fetch path and depends only on R02.
- [R13B](R13B-analysis-artifact-renderer.md) consumes R09A Analysis Result and provides a non-Gravity renderer.
- [R13C](R13C-dashboard-connector.md) adds the governed Gravity Dashboard target after R12 and R13B.

Historical implementation discussion may cite R13, but all new status, Issue, branch and acceptance tracking uses the replacement leaf IDs.
