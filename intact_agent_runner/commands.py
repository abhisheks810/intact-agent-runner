from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
from typing import Mapping


@dataclass
class CommandResult:
    command: str
    cwd: str | None
    code: int | None
    signal: str | None
    timed_out: bool
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out


def run_command(
    command: str,
    args: list[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    timeout_ms: int = 120000,
) -> CommandResult:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    command_text = " ".join([command, *args])
    try:
        completed = subprocess.run(
            [command, *args],
            cwd=cwd,
            env=merged_env,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout_ms / 1000,
            check=False,
        )
        return CommandResult(
            command=command_text,
            cwd=cwd,
            code=completed.returncode,
            signal=None,
            timed_out=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as error:
        return CommandResult(
            command=command_text,
            cwd=cwd,
            code=None,
            signal="SIGTERM",
            timed_out=True,
            stdout=error.stdout or "",
            stderr=error.stderr or "",
        )


def git_status(repo_root: str) -> CommandResult:
    return run_command("git", ["status", "--short", "--branch"], cwd=repo_root, timeout_ms=30000)


def command_summary(result: CommandResult) -> str:
    parts = [f"$ {result.command}"]
    if result.cwd:
        parts.append(f"cwd: {result.cwd}")
    parts.append(f"exit: {'timeout' if result.timed_out else result.code}")
    if result.stdout.strip():
        parts.append(f"stdout:\n{result.stdout.strip()}")
    if result.stderr.strip():
        parts.append(f"stderr:\n{result.stderr.strip()}")
    return "\n".join(parts)
