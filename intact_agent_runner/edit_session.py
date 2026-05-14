from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
import subprocess


MAX_FILE_WRITE_CHARS = 20000
MAX_CHANGED_FILES = 6

BLOCKED_PATH_PARTS = {
    ".git",
    ".env",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    "logs",
}

TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".txt",
    ".ts",
    ".tsx",
    ".yml",
    ".yaml",
}


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: dict = field(default_factory=dict)


class EditSession:
    def __init__(
        self,
        *,
        repo_root: str,
        repo_name: str,
        max_changed_files: int = MAX_CHANGED_FILES,
        max_file_write_chars: int = MAX_FILE_WRITE_CHARS,
    ):
        self.repo_root = Path(repo_root).resolve()
        self.repo_name = repo_name
        self.max_changed_files = max_changed_files
        self.max_file_write_chars = max_file_write_chars
        self.read_hashes: dict[str, str | None] = {}
        self.changed_paths: list[str] = []
        self.actions: list[dict] = []

    def record(self, tool: str, ok: bool, output: str, data: dict | None = None) -> ToolResult:
        item = {"tool": tool, "ok": ok, "output": output}
        if data:
            item["data"] = data
        self.actions.append(item)
        return ToolResult(ok=ok, output=output, data=data or {})

    def safe_relative_path(self, raw_path: str) -> str:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError("path is required")
        raw_path = raw_path.strip()
        pure = PurePosixPath(raw_path)
        if pure.is_absolute():
            raise ValueError(f"absolute paths are not allowed: {raw_path}")
        if ".." in pure.parts:
            raise ValueError(f"parent-directory traversal is not allowed: {raw_path}")
        if pure.parts and pure.parts[0] == self.repo_name:
            raise ValueError(f"path must be repo-relative and must not start with `{self.repo_name}/`: {raw_path}")
        if any(part in BLOCKED_PATH_PARTS for part in pure.parts):
            raise ValueError(f"generated, secret, or unsafe path is not allowed: {raw_path}")
        suffix = Path(raw_path).suffix
        if suffix and suffix not in TEXT_SUFFIXES:
            raise ValueError(f"unsupported file type for text edit: {raw_path}")
        return pure.as_posix()

    def absolute_path(self, raw_path: str) -> Path:
        relative = self.safe_relative_path(raw_path)
        absolute = (self.repo_root / relative).resolve()
        root = self.repo_root.resolve()
        if absolute != root and root not in absolute.parents:
            raise ValueError(f"path escapes repository root: {raw_path}")
        return absolute

    def list_files(self, *, limit: int = 220) -> ToolResult:
        files: list[str] = []
        for path in self.repo_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.repo_root)
            if any(part in BLOCKED_PATH_PARTS for part in relative.parts):
                continue
            suffix = path.suffix
            if suffix and suffix not in TEXT_SUFFIXES:
                continue
            files.append(relative.as_posix())
            if len(files) >= limit:
                break
        return self.record("list_files", True, "\n".join(sorted(files)), {"files": sorted(files)})

    def read_file(self, path: str, *, max_chars: int = 12000) -> ToolResult:
        try:
            absolute = self.absolute_path(path)
            if not absolute.exists():
                relative = self.safe_relative_path(path)
                self.read_hashes[relative] = None
                return self.record("read_file", True, f"{relative} does not exist", {"path": relative, "sha256": None})
            content = absolute.read_text(encoding="utf-8")
            digest = sha256(content.encode("utf-8")).hexdigest()
            relative = absolute.relative_to(self.repo_root).as_posix()
            self.read_hashes[relative] = digest
            output = content if len(content) <= max_chars else content[:max_chars].rstrip() + "\n... [truncated]"
            return self.record("read_file", True, output, {"path": relative, "sha256": digest})
        except Exception as error:
            return self.record("read_file", False, str(error))

    def search(self, query: str, *, limit: int = 80) -> ToolResult:
        if not isinstance(query, str) or not query.strip():
            return self.record("search", False, "query is required")
        try:
            completed = subprocess.run(
                ["rg", "-n", "--glob", "!node_modules", "--glob", "!dist", "--glob", "!build", query],
                cwd=self.repo_root,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
        except FileNotFoundError:
            completed = subprocess.run(
                ["grep", "-R", "-n", query, "."],
                cwd=self.repo_root,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
        lines = (completed.stdout or completed.stderr or "").splitlines()[:limit]
        ok = completed.returncode in {0, 1}
        return self.record("search", ok, "\n".join(lines) if lines else "No matches")

    def write_file_full(self, path: str, content: str, expected_sha256: str | None = None) -> ToolResult:
        try:
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            if len(content) > self.max_file_write_chars:
                raise ValueError(f"content exceeds {self.max_file_write_chars} characters")
            absolute = self.absolute_path(path)
            relative = absolute.relative_to(self.repo_root).as_posix()
            current_hash = None
            if absolute.exists():
                current_text = absolute.read_text(encoding="utf-8")
                current_hash = sha256(current_text.encode("utf-8")).hexdigest()
                if relative not in self.read_hashes:
                    raise ValueError(f"existing file must be read before write: {relative}")
                if expected_sha256 != current_hash:
                    raise ValueError(f"stale write rejected for {relative}: expected {expected_sha256}, current {current_hash}")
            elif expected_sha256 not in {None, ""}:
                raise ValueError(f"new file must use null expected_sha256: {relative}")
            prospective = set(self.changed_paths)
            prospective.add(relative)
            if len(prospective) > self.max_changed_files:
                raise ValueError(f"changed file limit exceeded: {self.max_changed_files}")
            absolute.parent.mkdir(parents=True, exist_ok=True)
            absolute.write_text(content, encoding="utf-8")
            if relative not in self.changed_paths:
                self.changed_paths.append(relative)
            new_hash = sha256(content.encode("utf-8")).hexdigest()
            self.read_hashes[relative] = new_hash
            return self.record(
                "write_file_full",
                True,
                f"wrote {relative}",
                {"path": relative, "previous_sha256": current_hash, "sha256": new_hash},
            )
        except Exception as error:
            return self.record("write_file_full", False, str(error))

    def add_file(self, path: str, content: str) -> ToolResult:
        return self.write_file_full(path, content, expected_sha256=None)

    def git_status(self) -> ToolResult:
        return self._run(["git", "status", "--short", "--branch"], tool="git_status")

    def git_diff(self) -> ToolResult:
        return self._run(["git", "diff", "--binary"], tool="git_diff")

    def _run(self, args: list[str], *, tool: str) -> ToolResult:
        completed = subprocess.run(args, cwd=self.repo_root, text=True, capture_output=True, check=False, timeout=60)
        output = (completed.stdout or completed.stderr).strip()
        return self.record(tool, completed.returncode == 0, output, {"exit": completed.returncode})


def changed_paths_are_scoped(changed_paths: list[str], allowed_paths: list[str]) -> bool:
    allowed = {PurePosixPath(path) for path in allowed_paths}
    for path in changed_paths:
        pure = PurePosixPath(path)
        if pure not in allowed:
            return False
    return True
