# Security Policy

## Supported Versions

Security fixes are assessed for the current released version and the `main`
branch. Support for older releases is decided by the release owner.

## Reporting a Vulnerability

Do not file public issues for suspected vulnerabilities. Report them privately
to haoming@merjoy.cn. Include a minimal reproduction, affected version, and
impact. Do not include credentials, cookies, user data, or production output.

The maintainers will acknowledge the report, assess the impact, and agree on a
coordinated disclosure timeline with the reporter.

## Runtime Trust Boundaries

- External Context is data, never an instruction, selector, effect or source of
  authorization. Providers run outside the Runtime process, do not inherit
  Gravity credentials, and are governed at the RPC boundary for concurrency,
  call count, timeout, cancellation, output and circuit state.
- Provider-internal network and database controls belong to the provider
  sandbox/deployment policy. A Provider failure produces a Context Gap; external
  mutation requires a separately registered Action Connector.
- Restricted Context stays out of model context by default. Receipts retain
  value-free URI/hash/trust metadata, not source bodies, credentials, Scope
  digests, user rows or reversible account identifiers.
- Runtime and project locks are immutable inputs during a Journey. The Runtime
  process cannot download, install or replace its wheel; an external installer
  activates a complete verified snapshot between Journeys.

## Artifact and Update Security

Ordinary Skill packages contain reviewed static content only. Trusted code uses
a distinct installed-and-allowlisted package/lock channel. Exact digests are
necessary but do not establish source identity; untrusted transport,
cross-organization distribution, central revocation or compliance requirements
also require organizational signature, provenance, trust-root and rollback
policy. Those real identities and keys must be supplied by their owners.
