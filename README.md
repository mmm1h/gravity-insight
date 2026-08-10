# Gravity SDK

Standalone Python SDK and CLI for governed access to Gravity Insight and
Gravity custom SQL.

It combines four previously separate surfaces:

- typed, manifest-authorized Insight reads and exports;
- fixed-route custom SQL execution, isolated batch reads, and paged export;
- deterministic contract compilation and privacy-aware probing;
- frontend route census and upstream drift detection.

## Install

```powershell
python -m pip install -e .
```

On Windows, if `pip` reports that its `Scripts` directory is not on `PATH`,
add the reported directory to `PATH` or use `python -m gravity_sdk`.

Copy `.env.example` to `.env.gravity.local` and fill only the credentials needed
for your environment. The local environment file is ignored by Git.

## CLI

```powershell
gravity --help
gravity insight capabilities list
gravity insight multidim query --help
gravity sql --dry-run
gravity sql query payment-summary --start 2026-08-01T00:00:00+08:00 --end 2026-08-02T00:00:00+08:00
gravity census --smoke
```

The Python API exposes both clients from one package:

```python
from gravity_sdk import GravityClient, GravityInsightClient

insight = GravityInsightClient.from_env()
sql = GravityClient.from_env()
```

All production transports remain fixed-host and policy constrained. The SDK
does not expose arbitrary URL/method execution, and SQL accepts only the fixed
custom-SQL endpoint.

See [MIGRATION.md](MIGRATION.md) for provenance and
[docs/guides/agent-guide.md](docs/guides/agent-guide.md) for the full command
surface.

## Verify

```powershell
python -m pytest -q
python -m gravity_sdk.compiler check
python -m gravity_sdk.quality check
git diff --check
```
