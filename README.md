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

## Claude Code routine

This task is also registered as an official Claude Code routine:

- `.claude/commands/hourly-data-routine.md` — slash command `/hourly-data-routine`
  that runs the script, commits any new files, and pushes.
- `.claude/hooks/session-start.sh` — installs `requirements.txt` and surfaces
  `AGENT_REPO` / `INSTRUCTION_LABEL` at the start of every web session.
- `.claude/settings.json` — wires the hook into `SessionStart`.

To activate the hourly cadence on Claude Code on the web, open this repo's
**Triggers** page and add a scheduled trigger:

- **Schedule:** `0 * * * *` (hourly)
- **Branch:** `main`
- **Prompt:** `/hourly-data-routine`

The GitHub Actions workflow remains as a redundant fallback so the routine
keeps running even without an active Claude Code trigger.
