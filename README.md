# Data

Hourly automation that pulls work instructions from the **Agent** repository,
processes them, and fetches any supplementary data needed from the web.

## How it works

A scheduled workflow (`.github/workflows/hourly-routine.yml`) runs every hour
and invokes `scripts/hourly_routine.py`. The script:

1. Lists open issues on the Agent repo (default `dh914/Agent`) that carry the
   `data-request` label.
2. Parses each issue body as YAML/JSON (a fenced block is allowed) to extract
   a `fetch` list of URLs and an optional `output` slug. Bare URLs in the body
   are also detected as a fallback.
3. Downloads each URL into `data/<timestamp>-<issue#>-<slug>/`, writing a
   `result.json` summary and the original payloads.
4. Comments on the originating issue and closes it.
5. Records the processed issue id in `data/_state/processed.json` so reruns
   skip already-handled work.

New files under `data/` are committed back to this branch on every run.

## Configuration

| Variable | Where | Default | Purpose |
| --- | --- | --- | --- |
| `AGENT_REPO` | repo variable | `dh914/Agent` | source of instructions |
| `INSTRUCTION_LABEL` | repo variable | `data-request` | label that marks an instruction |
| `AGENT_REPO_TOKEN` | repo secret | falls back to `GITHUB_TOKEN` | token with `issues:write` on the Agent repo |

If the Agent repo is private or lives in a different org, set
`AGENT_REPO_TOKEN` to a fine-scoped PAT — the default `GITHUB_TOKEN` only
covers the current repository.

## Instruction format

````markdown
```yaml
output: kospi-snapshot
fetch:
  - https://example.com/data.csv
  - https://example.com/meta.json
```
````

## Manual run

Trigger from the Actions tab via **Run workflow**, or locally:

```bash
pip install -r requirements.txt
AGENT_REPO=dh914/Agent GH_TOKEN=ghp_xxx python scripts/hourly_routine.py
```
