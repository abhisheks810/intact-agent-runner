from __future__ import annotations

from pathlib import Path


def read_text(file_path: str | Path) -> str:
    return Path(file_path).read_text(encoding="utf-8")


def write_text(file_path: str | Path, content: str) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def list_markdown(root: str | Path) -> list[dict]:
    root_path = Path(root)
    if not root_path.exists():
        return []
    results: list[dict] = []
    for path in root_path.rglob("*.md"):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        stat = path.stat()
        results.append({
            "absolute": str(path),
            "relative": str(path.relative_to(root_path)),
            "mtimeMs": stat.st_mtime * 1000,
        })
    return sorted(results, key=lambda item: item["relative"])


def latest_markdown(root: str | Path, limit: int = 5) -> list[dict]:
    files = list_markdown(root)
    return sorted(files, key=lambda item: item["mtimeMs"], reverse=True)[:limit]
