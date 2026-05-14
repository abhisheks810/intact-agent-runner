from __future__ import annotations

from pathlib import Path

from .files import read_text

MAX_TREE_FILES = 220
MAX_SNIPPET_CHARS = 1800

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
}

KEY_PATH_PREFIXES = (
    "backend/",
    "frontend/src/",
    "custom_router/",
    "router/",
    "geocoder/",
    "scripts/",
    "tests/",
    "docs/",
)

KEY_FILE_NAMES = {
    "README.md",
    "package.json",
    "pyproject.toml",
    "docker-compose.yml",
    "Dockerfile",
}

ROUTE_SNIPPET_PATHS = [
    "backend/main.py",
    "backend/routers/route.py",
    "frontend/src/components/SearchBar.jsx",
    "frontend/src/components/MapView.jsx",
    "custom_router/app.py",
    "tests/test_route_contracts.py",
    "scripts/loop-preflight.sh",
    "scripts/verify.sh",
]


def build_repo_intelligence(config) -> dict:
    map_root = Path(config.map_platform_root)
    return {
        "map_platform": {
            "root": str(map_root),
            "fileTree": repo_file_tree(map_root),
            "routeEndpointMap": route_endpoint_map(map_root),
            "relevantSourceSnippets": source_snippets(map_root, ROUTE_SNIPPET_PATHS),
            "pathPolicy": path_policy("map_platform", map_root),
        }
    }


def repo_file_tree(root: Path) -> list[str]:
    if not root.exists():
        return []
    files: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        rel = relative.as_posix()
        if rel in KEY_FILE_NAMES or rel.startswith(KEY_PATH_PREFIXES) or rel.endswith(".md"):
            files.append(rel)
        if len(files) >= MAX_TREE_FILES:
            break
    return sorted(files)


def route_endpoint_map(root: Path) -> dict:
    main_py = read_optional(root / "backend" / "main.py")
    route_py = read_optional(root / "backend" / "routers" / "route.py")
    search_bar = read_optional(root / "frontend" / "src" / "components" / "SearchBar.jsx")
    custom_router = read_optional(root / "custom_router" / "app.py")

    facts = []
    if "include_router(route.router" in main_py and "prefix=\"/route\"" in main_py:
        facts.append("FastAPI registers backend.routers.route at prefix /route in backend/main.py.")
    if "@router.get(\"\")" in route_py or "@router.get('')" in route_py:
        facts.append("backend/routers/route.py handles GET on the empty router path, so the public backend endpoint is GET /route.")
    if "${API_BASE}/route" in search_bar or "/route?origin=" in search_bar:
        facts.append("frontend/src/components/SearchBar.jsx calls `${API_BASE}/route?origin=...&destination=...` when the user clicks Get Route.")
    if "@app.get(\"/route\")" in custom_router or "@app.get('/route')" in custom_router:
        facts.append("custom_router/app.py exposes GET /route for ROUTER_PROVIDER=intact fallback mode.")

    return {
        "backendRouteEndpoint": "GET /route?origin=lat,lon&destination=lat,lon" if facts else "unknown",
        "frontendCallSite": "frontend/src/components/SearchBar.jsx",
        "backendRegistration": "backend/main.py",
        "backendHandler": "backend/routers/route.py",
        "customRouterHandler": "custom_router/app.py",
        "routeContractTests": "tests/test_route_contracts.py",
        "facts": facts,
    }


def source_snippets(root: Path, relative_paths: list[str]) -> list[dict]:
    snippets: list[dict] = []
    for relative in relative_paths:
        path = root / relative
        if not path.exists() or not path.is_file():
            continue
        text = read_text(path)
        snippets.append({
            "path": relative,
            "text": trim_text(text, MAX_SNIPPET_CHARS),
        })
    return snippets


def path_policy(repo_name: str, root: Path) -> list[str]:
    return [
        "Patch paths must be relative to the selected repository root.",
        "Do not include absolute paths or parent-directory traversal.",
        f"Do not prefix paths with `{repo_name}/`; the diff is already applied inside {root}.",
        "Do not modify .git, node_modules, dist, build outputs, virtualenvs, secrets, or local logs.",
    ]


def read_optional(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return read_text(path)


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n... [truncated]"
