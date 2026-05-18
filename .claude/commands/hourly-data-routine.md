---
description: Hourly data routine — pull instructions from the Agent repo, fetch any web data, commit results.
allowed-tools: Bash, Read, Edit, Write
---

You are running the hourly data routine for this repository. This command is
invoked by a Claude Code scheduled trigger (cron: every hour) and should be
fully autonomous — do not ask the user any questions.

Steps:

1. Verify the working tree is clean and we are on a sensible branch
   (default: `main`). If a stale local change is present, stash it.
2. Run the routine:

   ```
   python scripts/hourly_routine.py
   ```

   The script reads open `data-request` issues from `$AGENT_REPO`
   (default `dh914/Agent`), fetches any URLs declared in each instruction,
   and writes results to `data/<timestamp>-<issue#>-<slug>/`.
3. If `data/` has new files, stage them, create a commit with the message
   `chore(data): hourly routine results <ISO-8601 UTC>`, and push to the
   current branch. Retry the push up to 4 times with exponential backoff
   (2s, 4s, 8s, 16s) on network failure only.
4. If `scripts/hourly_routine.py` exits non-zero, surface the error and
   skip the commit/push step.
5. End the session — no PR, no extra commentary. The commit on the default
   branch is the deliverable.

Environment expected:

- `AGENT_REPO` — owner/name of the Agent repository (default `dh914/Agent`).
- `INSTRUCTION_LABEL` — label that marks instruction issues (default `data-request`).
- `GH_TOKEN` — GitHub token with `issues:write` on `$AGENT_REPO`. In a
  Claude Code on the web session this is provided by the GitHub integration.
