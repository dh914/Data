"""Hourly routine: pull instructions from the Agent repo, process them, and
fetch supplementary data from the web when an instruction asks for it.

An instruction is a GitHub issue on the Agent repo carrying the configured
label (default: ``data-request``). The issue body is parsed as YAML or JSON
and may contain:

- ``fetch``: list of HTTP(S) URLs to download
- ``attachments``: list of paths inside the Agent repo (saved by Agent's
  email routine under ``incoming/``) — each is downloaded via the GitHub
  Contents API, processed (size / sha256 / line count / text preview) and
  written next to the originals under ``data/``.
- ``output``, ``request_id``, ``reply_to``: opaque metadata echoed back to
  Agent so it can email the original sender once results are ready.

Results land under ``data/<timestamp>-<issue#>-<slug>/``. The originating
issue receives a closing comment containing a fenced ```data-result``` JSON
block that Agent's relay script consumes to send the final email reply.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATE_PATH = DATA_DIR / "_state" / "processed.json"

GITHUB_API = "https://api.github.com"
AGENT_REPO = os.environ.get("AGENT_REPO", "dh914/Agent")
INSTRUCTION_LABEL = os.environ.get("INSTRUCTION_LABEL", "data-request")
GH_TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
USER_AGENT = "dh914-data-hourly-routine/1.0"
MAX_FETCH_BYTES = 25 * 1024 * 1024
PREVIEW_BYTES = 512


@dataclass
class Instruction:
    number: int
    title: str
    body: str
    url: str


def gh_request(method: str, path: str, payload: dict | None = None) -> Any:
    url = f"{GITHUB_API}{path}" if path.startswith("/") else path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", USER_AGENT)
    if GH_TOKEN:
        req.add_header("Authorization", f"Bearer {GH_TOKEN}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def fetch_instructions() -> list[Instruction]:
    path = (
        f"/repos/{AGENT_REPO}/issues"
        f"?state=open&labels={INSTRUCTION_LABEL}&per_page=50"
    )
    try:
        issues = gh_request("GET", path) or []
    except urllib.error.HTTPError as exc:
        print(f"[warn] could not list instructions: {exc}", file=sys.stderr)
        return []
    out: list[Instruction] = []
    for issue in issues:
        if "pull_request" in issue:
            continue
        out.append(
            Instruction(
                number=issue["number"],
                title=issue.get("title", ""),
                body=issue.get("body") or "",
                url=issue.get("html_url", ""),
            )
        )
    return out


def parse_instruction(body: str) -> dict:
    fence = re.search(r"```(?:yaml|yml|json)?\s*\n(.*?)```", body, re.S)
    payload = fence.group(1) if fence else body
    try:
        parsed = yaml.safe_load(payload)
    except yaml.YAMLError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    urls = re.findall(r"https?://\S+", body)
    return {"fetch": urls} if urls else {}


def safe_slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug[:80] or fallback


def fetch_url(url: str) -> bytes:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", USER_AGENT)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read(MAX_FETCH_BYTES + 1)


def fetch_repo_file(repo: str, path: str, ref: str | None = None) -> bytes:
    """Download a file from a GitHub repo via the Contents API (works on private repos)."""
    api_path = f"/repos/{repo}/contents/{path.lstrip('/')}"
    if ref:
        api_path = f"{api_path}?ref={ref}"
    data = gh_request("GET", api_path)
    if not isinstance(data, dict):
        raise ValueError(f"unexpected contents response for {path}")
    if data.get("encoding") != "base64" or "content" not in data:
        raise ValueError(f"unsupported encoding for {path}: {data.get('encoding')}")
    return base64.b64decode(data["content"])


def process_attachment(name: str, payload: bytes, out_dir: Path) -> dict:
    """Run a basic processing pass and persist the original + a per-file summary."""
    safe = safe_slug(name.rsplit("/", 1)[-1], "attachment")
    (out_dir / safe).write_bytes(payload)

    sha256 = hashlib.sha256(payload).hexdigest()
    try:
        text = payload.decode("utf-8")
        is_text = True
    except UnicodeDecodeError:
        text = ""
        is_text = False
    line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0) if is_text else None
    preview = text[:PREVIEW_BYTES] if is_text else None

    summary = {
        "name": safe,
        "source_path": name,
        "bytes": len(payload),
        "sha256": sha256,
        "is_text": is_text,
        "line_count": line_count,
        "preview": preview,
    }
    (out_dir / f"{safe}.summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"processed": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))


def process(instruction: Instruction, state: dict) -> dict | None:
    key = str(instruction.number)
    if key in state["processed"]:
        return None

    spec = parse_instruction(instruction.body)
    urls = [u for u in spec.get("fetch", []) if isinstance(u, str)]
    attachments = [a for a in spec.get("attachments", []) if isinstance(a, str)]
    source_repo = spec.get("source_repo") or AGENT_REPO
    source_branch = spec.get("source_branch") or "main"

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = safe_slug(spec.get("output") or instruction.title, f"issue-{instruction.number}")
    out_dir = DATA_DIR / f"{timestamp}-{instruction.number}-{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "instruction": {
            "number": instruction.number,
            "title": instruction.title,
            "url": instruction.url,
        },
        "request_id": spec.get("request_id"),
        "reply_to": spec.get("reply_to"),
        "spec": spec,
        "fetched": [],
        "processed": [],
        "errors": [],
        "output_dir": str(out_dir.relative_to(ROOT)),
    }

    for idx, url in enumerate(urls):
        try:
            payload = fetch_url(url)
        except Exception as exc:
            result["errors"].append({"url": url, "error": str(exc)})
            continue
        if len(payload) > MAX_FETCH_BYTES:
            result["errors"].append({"url": url, "error": "response exceeded size limit"})
            continue
        name = safe_slug(url.rsplit("/", 1)[-1] or f"resource-{idx}", f"resource-{idx}")
        (out_dir / name).write_bytes(payload)
        result["fetched"].append({"url": url, "file": name, "bytes": len(payload)})

    for path in attachments:
        try:
            payload = fetch_repo_file(source_repo, path, source_branch)
        except Exception as exc:
            result["errors"].append({"attachment": path, "error": str(exc)})
            continue
        if len(payload) > MAX_FETCH_BYTES:
            result["errors"].append({"attachment": path, "error": "exceeded size limit"})
            continue
        try:
            summary = process_attachment(path, payload, out_dir)
        except Exception as exc:
            result["errors"].append({"attachment": path, "error": f"process failed: {exc}"})
            continue
        result["processed"].append(summary)

    (out_dir / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    state["processed"][key] = {
        "completed_at": timestamp,
        "output": str(out_dir.relative_to(ROOT)),
        "request_id": spec.get("request_id"),
    }
    return result


def close_instruction(instruction: Instruction, result: dict) -> None:
    """Close the issue with a comment carrying a fenced ``data-result`` JSON block.

    Agent's relay script parses this block to know the work is done and to
    send the processed summary back to the original email sender.
    """
    if not GH_TOKEN:
        return
    body_lines = [
        f"Processed by hourly data routine at {datetime.now(timezone.utc).isoformat()}.",
        (
            f"Fetched {len(result['fetched'])} URL(s); "
            f"processed {len(result['processed'])} attachment(s); "
            f"{len(result['errors'])} error(s)."
        ),
        "",
        "```data-result",
        json.dumps(result, ensure_ascii=False, indent=2),
        "```",
    ]
    try:
        gh_request(
            "POST",
            f"/repos/{AGENT_REPO}/issues/{instruction.number}/comments",
            {"body": "\n".join(body_lines)},
        )
        gh_request(
            "PATCH",
            f"/repos/{AGENT_REPO}/issues/{instruction.number}",
            {"state": "closed"},
        )
    except urllib.error.HTTPError as exc:
        print(f"[warn] could not close instruction #{instruction.number}: {exc}", file=sys.stderr)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    instructions = fetch_instructions()
    print(f"Found {len(instructions)} open instruction(s) on {AGENT_REPO}.")
    processed = 0
    for instruction in instructions:
        result = process(instruction, state)
        if result is None:
            continue
        processed += 1
        close_instruction(instruction, result)
        time.sleep(1)
    save_state(state)
    print(f"Processed {processed} new instruction(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
