# Repository migration

The standalone repository was extracted from
[`mmm1h/work-dashboard`](https://github.com/mmm1h/work-dashboard) at source
commit `0300d0dedc45225e04e7c482f8495dfbe991cf33` on 2026-08-10.

The extraction consolidates the former locations below:

| Former location | New location |
| --- | --- |
| `src/work_dashboard/gravity_insight` | `src/gravity_sdk` |
| `tools/gravity_insight` | `src/gravity_sdk` |
| `tools/gravity` | `src/gravity_sdk/sql` |
| `tools/gravity_census` | `src/gravity_sdk/census` |
| Gravity-specific governance gates | `src/gravity_sdk/governance` |
| Gravity probe and verification evidence | `evidence` |

The source commit is the immutable provenance anchor for pre-split history.
Subsequent SDK development is owned exclusively by this repository.

Work-dashboard-specific campaign consumers were not made part of the SDK API.
They were retired during the split because they coupled SDK transport to one
repository's topic paths and frozen report assets. Business SQL remains owned
by its calling product repository; this SDK owns authentication, policy,
transport, contracts, probing, census, and Evidence publication.
