"""Call Claude through the local Claude Code CLI (`claude -p`), using the plan you're logged into.

Every call runs in an empty working directory with no project settings, MCP servers or saved
session, and only the tools the caller allows.
"""

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

WORK_DIR = Path(__file__).resolve().parent.parent / "data" / "ai-work"
DEFAULT_TIMEOUT = 240

# Shared ground rules for every writing task.
HONESTY_RULES = """\
Only use facts that appear in the candidate's profile or resume. Never invent employers, titles,
dates, metrics, skills, degrees, awards or links. You may reorder, condense and reword what is
there, and choose which details to emphasise for the job. If the job asks for something the
candidate doesn't have, leave it out rather than implying they have it.
Write in plain, specific language. Avoid filler like "passionate", "leverage", "synergy",
"dynamic", "cutting-edge" or "I am writing to express my interest"."""


class AIError(Exception):
    """A user-facing explanation of why the Claude call failed."""


def claude_path() -> str | None:
    return shutil.which("claude") or next(
        (str(p) for p in [Path.home() / ".local/bin/claude", Path("/opt/homebrew/bin/claude"),
                          Path("/usr/local/bin/claude")] if p.exists()), None)


def ask(prompt: str, *, system: str | None = None, schema: dict | None = None,
        tools: list[str] | None = None, model: str | None = None,
        timeout: int = DEFAULT_TIMEOUT) -> dict | str:
    """Run one prompt. Returns the structured object when `schema` is given, otherwise text.

    `tools` lists the Claude Code tools the call may use (e.g. ["WebFetch"]); none by default.
    """
    exe = claude_path()
    if not exe:
        raise AIError("The Claude Code CLI (`claude`) isn't installed or isn't on your PATH.")
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [exe, "-p", "--output-format", "json", "--no-session-persistence",
           "--strict-mcp-config", "--setting-sources", "", "--tools", ",".join(tools or []) or ""]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    if system:
        cmd += ["--system-prompt", system]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]
    if model:
        cmd += ["--model", model]

    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_ENTRYPOINT")}
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=WORK_DIR,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise AIError(f"Claude didn't answer within {timeout} seconds. Try again.") from exc

    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        detail = (proc.stderr or proc.stdout).strip()[-400:]
        if "login" in detail.lower() or "auth" in detail.lower():
            raise AIError("Claude Code isn't logged in. Run `claude` in a terminal and log in, then try again.")
        raise AIError(f"Claude Code failed (exit {proc.returncode}): {detail or 'no output'}")

    if out.get("is_error") or out.get("subtype") != "success":
        detail = str(out.get("result") or out.get("subtype") or "unknown error")[:400]
        if "limit" in detail.lower():
            raise AIError(f"Your Claude plan's usage limit was reached: {detail}")
        raise AIError(f"Claude returned an error: {detail}")

    log.info("claude call: %.1fs, %s turns", (out.get("duration_ms") or 0) / 1000, out.get("num_turns"))
    if schema:
        result = out.get("structured_output")
        if result is None:
            try:
                result = json.loads(out.get("result") or "")
            except json.JSONDecodeError as exc:
                raise AIError("Claude's answer wasn't in the expected format. Try again.") from exc
        return result
    return out.get("result") or ""
