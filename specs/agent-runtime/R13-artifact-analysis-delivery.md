# R13 Artifact Transfer And Analysis Delivery

| Field | Value |
| --- | --- |
| Parent directive | `gravity-agent-runtime/v9` via `directive.json` |
| Status | `specified` |
| Track | Delivery plane |
| Dependencies | R02, R12 |
| Parallel group | `delivery` |
| Main integration | Frozen until whole program completion |

## Outcome

Binary/file results transfer through a governed Artifact contract, while analysis findings compile into a target-independent Analysis Artifact that can be rendered or handed to a governed Gravity Dashboard Connector.

## Current Baseline

The repository supports governed exports and strict replay of selected persisted Dashboard charts. It lacks one contract for signed/binary references, atomic file transfer and target-independent visualization/delivery specifications.

## Scope

- Define exact Artifact reference, allowed host/redirect, MIME/magic, size, streaming, output-root, atomic commit and digest rules.
- Define `gravity.analysis-artifact.v1` for sections, metrics, dimensions, filters, visualizations, evidence and claims.
- Implement at least one non-Gravity renderer.
- Implement a bounded Gravity Dashboard Compiler/Connector through R12 Preview/Execute/Readback.
- Bind source result and delivered artifact/dashboard in Receipt evidence.

## Non-goals

- No arbitrary URL fetch, browser automation or raw platform object exposure.
- No Skill/LLM-authored Gravity Web configuration.
- No recreation of favourites, drag/drop, member permissions or a Dashboard UI.

## Machine Contract

Artifact transfer returns path-relative metadata and digest, never signed URL, Cookie or Authorization values. Analysis Artifact references versioned Semantic identities and governed source results; target adapters cannot strengthen claims or completeness.

## Migration And Compatibility

Existing export flows remain valid and may adopt the transfer contract only after parity. Existing Dashboard replay is a read path and is not silently repurposed as creation. New write behavior uses a distinct connector and consumer migration.

## Safety And Operations

Prevent redirect escape, MIME confusion, magic mismatch, path traversal, symlink writes, oversized/decompression content and partial files. Output roots are explicit and resolved before writes. Dashboard actions require confirmation and readback.

## Acceptance

- Attack fixtures fail before final file commit.
- Interrupted downloads leave no visible partial artifact.
- One Analysis Artifact renders through a non-Gravity target.
- Dashboard Preview/Execute/Readback preserves claims and source bindings.
- Public results and Receipts contain no credentials or signed URLs.

## Verification

Redirect/MIME/magic/path/size/stream interruption tests, atomic file tests, deterministic render fixtures, Dashboard connector action tests, Receipt privacy, consumer compatibility and full gates.

## Rollback And Exit

Target adapters can be disabled independently; source Analysis Results remain usable. Failed transfers remove temporary files. Existing exports and Dashboard replay continue unchanged.

## Canonical Owners

Artifact/Analysis Artifact schemas, transfer service, renderers, Dashboard connector, export/delivery guides and Receipt reference.
