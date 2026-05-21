import asyncio
import json

from config import settings


class ClaudeCliError(Exception):
    pass


async def ask_claude(question: str, model: str | None = None) -> str:
    model = (model or settings.default_model).strip()
    cmd = [
        settings.claude_cli_path,
        "-p",
        "--model", model,
        "--output-format", "json",
        question,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.claude_timeout
        )
    except asyncio.TimeoutError:
        raise ClaudeCliError(f"Claude CLI timed out after {settings.claude_timeout}s")
    except FileNotFoundError:
        raise ClaudeCliError(
            f"Claude CLI not found at '{settings.claude_cli_path}'. "
            "Install it or set CLAUDE_CLI_PATH."
        )

    output = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()

    data: dict | None = None
    if output:
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            data = None

    if proc.returncode != 0:
        detail = (data or {}).get("result") or err or output or "no output"
        raise ClaudeCliError(
            f"Claude CLI exited with code {proc.returncode}: {detail}"
        )

    if not output:
        raise ClaudeCliError("Claude CLI returned empty output")

    if data is None:
        return output

    if data.get("is_error"):
        raise ClaudeCliError(data.get("result") or "Claude CLI reported an error")

    result = data.get("result")
    if isinstance(result, str) and result:
        return result
    return output
