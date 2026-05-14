from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile

from .commands import command_summary, run_command


@dataclass
class WorktreeResult:
    ok: bool
    summary: str
    commands: list[str]


class TemporaryWorktree:
    def __init__(self, *, source_root: str, label: str = "map-platform-agent"):
        self.source_root = source_root
        self.label = label
        self.base_dir: str | None = None
        self.path: str | None = None
        self.commands: list[str] = []

    def __enter__(self) -> "TemporaryWorktree":
        self.base_dir = tempfile.mkdtemp(prefix=f"{self.label}-", dir="/tmp")
        self.path = str(Path(self.base_dir) / "worktree")
        result = run_command(
            "git",
            ["worktree", "add", "--detach", self.path, "HEAD"],
            cwd=self.source_root,
            timeout_ms=120000,
        )
        self.commands.append(command_summary(result))
        if not result.ok:
            self._remove_base_dir()
            raise RuntimeError(f"Failed to create temporary worktree.\n{command_summary(result)}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()

    def cleanup(self) -> WorktreeResult:
        if self.path is None and self.base_dir is None:
            return WorktreeResult(ok=True, summary="Temporary worktree already cleaned up.", commands=[])
        commands = []
        ok = True
        if self.path:
            remove = run_command(
                "git",
                ["worktree", "remove", "--force", self.path],
                cwd=self.source_root,
                timeout_ms=120000,
            )
            commands.append(command_summary(remove))
            ok = ok and remove.ok
            self.path = None
        prune = run_command("git", ["worktree", "prune"], cwd=self.source_root, timeout_ms=60000)
        commands.append(command_summary(prune))
        ok = ok and prune.ok
        self._remove_base_dir()
        return WorktreeResult(ok=ok, summary="Temporary worktree cleaned up." if ok else "Temporary worktree cleanup had failures.", commands=commands)

    def _remove_base_dir(self) -> None:
        if self.base_dir and Path(self.base_dir).exists():
            shutil.rmtree(self.base_dir, ignore_errors=True)
        self.base_dir = None


def worktree_diff(worktree_path: str) -> str:
    intent = run_command("git", ["add", "-N", "--", "."], cwd=worktree_path, timeout_ms=60000)
    if not intent.ok:
        raise RuntimeError(f"Failed to make new files visible to git diff.\n{command_summary(intent)}")
    result = run_command("git", ["diff", "--binary"], cwd=worktree_path, timeout_ms=60000)
    if not result.ok:
        raise RuntimeError(f"Failed to generate worktree diff.\n{command_summary(result)}")
    return result.stdout


def worktree_changed_paths(worktree_path: str) -> list[str]:
    result = run_command("git", ["diff", "--name-only"], cwd=worktree_path, timeout_ms=60000)
    if not result.ok:
        raise RuntimeError(f"Failed to list changed paths.\n{command_summary(result)}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def validate_generated_diff(*, source_root: str, diff_text: str) -> dict:
    if not diff_text.strip():
        return {"ok": False, "results": ["No generated diff to validate."]}
    apply_check = run_command(
        "git",
        ["apply", "--check", "--whitespace=nowarn", "-"],
        cwd=source_root,
        input_text=diff_text,
        timeout_ms=60000,
    )
    return {
        "ok": apply_check.ok,
        "results": [
            "Generated diff validation:",
            command_summary(apply_check),
        ],
    }


def apply_verified_diff(*, source_root: str, diff_text: str) -> dict:
    result = run_command(
        "git",
        ["apply", "--whitespace=nowarn", "-"],
        cwd=source_root,
        input_text=diff_text,
        timeout_ms=60000,
    )
    return {"ok": result.ok, "results": [command_summary(result)]}


def run_repo_verification(repo_root: str, target_repo: str) -> dict:
    if target_repo == "map_platform":
        command = ("bash", ["./scripts/verify.sh"], {"PYTHONPYCACHEPREFIX": "/tmp/map_platform_pycache"})
    elif target_repo == "intact-agent-runner":
        command = ("python3", ["test/smoke_test.py"], {})
    else:
        command = ("git", ["diff", "--check"], {})
    result = run_command(command[0], command[1], cwd=repo_root, env=command[2], timeout_ms=300000)
    return {"ok": result.ok, "results": [command_summary(result)]}
