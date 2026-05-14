from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urlparse

from .commands import command_summary, git_status, run_command


SCHEDULE_MINUTES = [0, 20, 40]
MAX_TEXT_BYTES = 80_000


def serve_dashboard(config, *, host: str = "127.0.0.1", port: int = 8791) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_text(render_dashboard_html(), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/status":
                self._send_json(collect_dashboard_state(config))
                return
            if parsed.path == "/api/artifact":
                query = parse_qs(parsed.query)
                path = query.get("path", [""])[0]
                self._send_json(read_artifact(config, path))
                return
            self.send_error(404, "Not Found")

        def log_message(self, format, *args):  # noqa: A002
            return

        def _send_json(self, payload: dict) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, text: str, content_type: str) -> None:
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Dashboard listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def collect_dashboard_state(config) -> dict:
    runs = latest_artifacts(Path(config.mcp_server_root) / "data" / "agent-runs", 24)
    results = latest_artifacts(Path(config.mcp_server_root) / "data" / "map-platform-implementation-results", 24)
    launchd = launchd_status()
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scheduler": {
            "launchd": launchd,
            "nextRun": next_run_label(),
            "lock": lock_status(),
        },
        "repos": {
            "intact-agent-runner": repo_status(config.agent_runner_root),
            "map_platform": repo_status(config.map_platform_root),
            "intact-mcp-server": repo_status(config.mcp_server_root),
        },
        "latestRun": runs[0] if runs else None,
        "latestResult": results[0] if results else None,
        "runs": runs,
        "results": results,
        "logs": {
            "stdout": tail_file(Path(config.agent_runner_root) / "logs" / "map-platform-loop.out.log", 16000),
            "stderr": tail_file(Path(config.agent_runner_root) / "logs" / "map-platform-loop.err.log", 12000),
        },
    }


def latest_artifacts(root: Path, limit: int) -> list[dict]:
    if not root.exists():
        return []
    files = sorted(root.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)[:limit]
    return [artifact_summary(root, path) for path in files]


def artifact_summary(root: Path, path: Path) -> dict:
    text = safe_read(path)
    return {
        "path": str(path),
        "relativePath": str(path.relative_to(root.parent)),
        "name": path.name,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z"),
        "title": first_heading(text),
        "created": metadata_value(text, "Created"),
        "agent": metadata_value(text, "Agent"),
        "product": metadata_value(text, "Product"),
        "automation": metadata_value(text, "Automation"),
        "status": metadata_value(text, "Status") or status_from_text(text),
        "summary": section_text(text, "Summary", 900),
        "blockers": bullet_section(text, "Blockers", 8),
        "verification": bullet_section(text, "Verification", 8),
    }


def read_artifact(config, requested_path: str) -> dict:
    roots = [
        Path(config.mcp_server_root) / "data" / "agent-runs",
        Path(config.mcp_server_root) / "data" / "map-platform-implementation-results",
    ]
    for root in roots:
        candidate = safe_artifact_path(root, requested_path)
        if candidate and candidate.exists() and candidate.is_file():
            return {"ok": True, "path": str(candidate), "text": safe_read(candidate, MAX_TEXT_BYTES)}
    return {"ok": False, "error": "artifact not found"}


def safe_artifact_path(root: Path, requested_path: str) -> Path | None:
    name = Path(requested_path).name
    if not name.endswith(".md"):
        return None
    candidate = (root / name).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def repo_status(root: str) -> dict:
    result = git_status(root)
    dirty = [
        line for line in result.stdout.splitlines()
        if line and not line.startswith("##")
    ]
    return {
        "root": root,
        "ok": result.ok,
        "clean": result.ok and not dirty,
        "summary": result.stdout.strip() or result.stderr.strip(),
        "command": command_summary(result),
    }


def launchd_status() -> dict:
    uid = run_command("id", ["-u"], timeout_ms=5000)
    if not uid.ok:
        return {"ok": False, "error": command_summary(uid)}
    result = run_command(
        "launchctl",
        ["print", f"gui/{uid.stdout.strip()}/com.intact.map-platform-loop"],
        timeout_ms=10000,
    )
    text = result.stdout or result.stderr
    return {
        "ok": result.ok,
        "state": regex_value(text, r"state = ([^\n]+)"),
        "runs": regex_value(text, r"runs = ([0-9]+)"),
        "lastExitCode": regex_value(text, r"last exit code = ([^\n]+)"),
        "raw": text[-5000:],
    }


def lock_status() -> dict:
    path = Path("/tmp/intact-map-platform-host-runner.lock")
    return {
        "path": str(path),
        "present": path.exists(),
        "type": "directory" if path.is_dir() else "file" if path.exists() else "absent",
    }


def next_run_label(now: datetime | None = None) -> str:
    local_now = now or datetime.now().astimezone()
    minute = local_now.minute
    for target in SCHEDULE_MINUTES:
        if minute < target:
            next_time = local_now.replace(minute=target, second=0, microsecond=0)
            return next_time.strftime("%Y-%m-%d %H:%M:%S %Z")
    next_hour = local_now.replace(hour=(local_now.hour + 1) % 24, minute=0, second=0, microsecond=0)
    return next_hour.strftime("%Y-%m-%d %H:%M:%S %Z")


def tail_file(path: Path, max_chars: int) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False, "text": ""}
    text = safe_read(path, max_chars)
    return {"path": str(path), "exists": True, "text": text}


def safe_read(path: Path, max_chars: int = MAX_TEXT_BYTES) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except TypeError:
        text = path.read_text(encoding="utf-8")
    return text[-max_chars:]


def first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return "Untitled"


def metadata_value(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def status_from_text(text: str) -> str:
    match = re.search(r"^Result:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def section_text(text: str, heading: str, max_chars: int) -> str:
    pattern = rf"^## {re.escape(heading)}\s*$([\s\S]*?)(?=^## |\Z)"
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip()[:max_chars]


def bullet_section(text: str, heading: str, limit: int) -> list[str]:
    section = section_text(text, heading, 4000)
    bullets = []
    for line in section.splitlines():
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif bullets and line.strip() and not line.startswith("#"):
            bullets[-1] = f"{bullets[-1]}\n{line.strip()}"
        if len(bullets) >= limit:
            break
    return bullets


def regex_value(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def render_dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Intact Agent Development</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --ink: #111827;
      --muted: #5b6472;
      --line: #d6dbe3;
      --panel: #ffffff;
      --blue: #1d4ed8;
      --green: #047857;
      --red: #b91c1c;
      --amber: #b45309;
      --violet: #6d28d9;
      --shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
      padding: 22px 28px 16px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { margin: 0; font-size: 22px; letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 15px; letter-spacing: 0; }
    h3 { margin: 0 0 6px; font-size: 14px; letter-spacing: 0; }
    button {
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--ink);
      padding: 8px 12px;
      border-radius: 6px;
      cursor: pointer;
    }
    main { padding: 22px 28px 32px; }
    .grid { display: grid; gap: 16px; }
    .top { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .two { grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr); align-items: start; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 16px;
      min-width: 0;
    }
    .metric { display: flex; flex-direction: column; gap: 6px; min-height: 108px; }
    .metric strong { font-size: 21px; line-height: 1.15; overflow-wrap: anywhere; }
    .muted { color: var(--muted); }
    .ok { color: var(--green); }
    .warn { color: var(--amber); }
    .bad { color: var(--red); }
    .violet { color: var(--violet); }
    .timeline { display: grid; gap: 10px; }
    .run {
      border: 1px solid var(--line);
      border-left: 5px solid var(--blue);
      border-radius: 6px;
      padding: 12px;
      background: #ffffff;
      cursor: pointer;
    }
    .run.failed, .run.completed_with_blockers, .run.partial { border-left-color: var(--amber); }
    .run.blocked, .run.failed-status { border-left-color: var(--red); }
    .run.completed { border-left-color: var(--green); }
    .row { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
    .row > * { min-width: 0; }
    .status {
      white-space: nowrap;
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
    }
    ul { padding-left: 18px; margin: 8px 0 0; }
    pre {
      margin: 0;
      padding: 12px;
      background: #111827;
      color: #e5e7eb;
      border-radius: 6px;
      overflow: auto;
      max-height: 360px;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 12px;
    }
    .tabs { display: flex; gap: 8px; margin-bottom: 10px; }
    .tab.active { border-color: var(--blue); color: var(--blue); }
    dialog {
      border: 1px solid var(--line);
      border-radius: 8px;
      width: min(960px, calc(100vw - 32px));
      max-height: min(820px, calc(100vh - 32px));
      padding: 0;
    }
    dialog::backdrop { background: rgba(15, 23, 42, 0.36); }
    .modal-head {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }
    .modal-body { padding: 16px; }
    @media (max-width: 1100px) {
      .top, .two { grid-template-columns: 1fr; }
      header { position: static; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Intact Agent Development</h1>
      <div class="muted" id="generated">Loading telemetry...</div>
    </div>
    <button id="refresh">Refresh</button>
  </header>
  <main class="grid">
    <section class="grid top" id="metrics"></section>
    <section class="grid two">
      <div class="panel">
        <h2>Run History</h2>
        <div class="timeline" id="runs"></div>
      </div>
      <div class="grid">
        <div class="panel">
          <h2>Repositories</h2>
          <div id="repos" class="grid"></div>
        </div>
        <div class="panel">
          <h2>Latest Result</h2>
          <div id="latestResult"></div>
        </div>
      </div>
    </section>
    <section class="grid two">
      <div class="panel">
        <h2>Scheduler Logs</h2>
        <div class="tabs">
          <button class="tab active" data-log="stdout">stdout</button>
          <button class="tab" data-log="stderr">stderr</button>
        </div>
        <pre id="logText"></pre>
      </div>
      <div class="panel">
        <h2>Result History</h2>
        <div class="timeline" id="results"></div>
      </div>
    </section>
  </main>
  <dialog id="artifactDialog">
    <div class="modal-head">
      <h2 id="artifactTitle">Artifact</h2>
      <button id="closeDialog">Close</button>
    </div>
    <div class="modal-body"><pre id="artifactText"></pre></div>
  </dialog>
  <script>
    let state = null;
    let activeLog = "stdout";

    const statusClass = (value) => {
      const raw = String(value || "").toLowerCase();
      if (raw === "completed" || raw === "passed" || raw === "true") return "ok";
      if (raw.includes("failed") || raw.includes("blocked")) return "bad";
      if (raw.includes("blocker") || raw.includes("partial")) return "warn";
      return "violet";
    };

    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));

    async function load() {
      const response = await fetch("/api/status", { cache: "no-store" });
      state = await response.json();
      render();
    }

    function metric(label, value, detail, cls = "") {
      return `<div class="panel metric"><span class="muted">${esc(label)}</span><strong class="${cls}">${esc(value)}</strong><span>${esc(detail || "")}</span></div>`;
    }

    function render() {
      document.getElementById("generated").textContent = `Generated ${state.generatedAt}`;
      const launchd = state.scheduler.launchd || {};
      const latest = state.latestRun || {};
      const lock = state.scheduler.lock || {};
      document.getElementById("metrics").innerHTML = [
        metric("Scheduler", launchd.state || "unknown", `runs ${launchd.runs || "?"}, exit ${launchd.lastExitCode || "?"}`, launchd.ok ? "ok" : "bad"),
        metric("Next Run", state.scheduler.nextRun || "unknown", "launchd calendar interval"),
        metric("Lock", lock.present ? "present" : "cleared", lock.path, lock.present ? "warn" : "ok"),
        metric("Latest Run", latest.status || "none", latest.agent || latest.name || "", statusClass(latest.status)),
      ].join("");

      document.getElementById("repos").innerHTML = Object.entries(state.repos).map(([name, repo]) =>
        `<div><div class="row"><strong>${esc(name)}</strong><span class="${repo.clean ? "ok" : "bad"}">${repo.clean ? "clean" : "dirty"}</span></div><div class="muted">${esc(repo.summary)}</div></div>`
      ).join("");

      document.getElementById("runs").innerHTML = state.runs.map(runItem).join("");
      document.getElementById("results").innerHTML = state.results.map(runItem).join("");
      document.getElementById("latestResult").innerHTML = state.latestResult ? detailBlock(state.latestResult) : "<span class='muted'>No result recorded.</span>";
      renderLog();
    }

    function detailBlock(item) {
      const blockers = (item.blockers || []).map(x => `<li>${esc(x)}</li>`).join("");
      return `<h3>${esc(item.title || item.name)}</h3><div class="muted">${esc(item.created || item.mtime)}</div><p>${esc(item.summary || "")}</p>${blockers ? `<strong>Blockers</strong><ul>${blockers}</ul>` : ""}`;
    }

    function runItem(item) {
      const status = item.status || "unknown";
      const blockers = (item.blockers || []).slice(0, 2).map(x => `<li>${esc(x)}</li>`).join("");
      return `<div class="run ${esc(status)} ${statusClass(status)}-status" data-path="${esc(item.path)}">
        <div class="row"><h3>${esc(item.title || item.name)}</h3><span class="status ${statusClass(status)}">${esc(status)}</span></div>
        <div class="muted">${esc(item.created || item.mtime)} ${item.agent ? " | " + esc(item.agent) : ""}</div>
        <p>${esc(item.summary || "")}</p>
        ${blockers ? `<ul>${blockers}</ul>` : ""}
      </div>`;
    }

    function renderLog() {
      const payload = state.logs[activeLog] || {};
      document.getElementById("logText").textContent = payload.text || "";
      document.querySelectorAll(".tab").forEach(btn => btn.classList.toggle("active", btn.dataset.log === activeLog));
    }

    async function openArtifact(path) {
      const response = await fetch(`/api/artifact?path=${encodeURIComponent(path)}`, { cache: "no-store" });
      const payload = await response.json();
      document.getElementById("artifactTitle").textContent = path.split("/").pop();
      document.getElementById("artifactText").textContent = payload.text || payload.error || "";
      document.getElementById("artifactDialog").showModal();
    }

    document.getElementById("refresh").addEventListener("click", load);
    document.getElementById("closeDialog").addEventListener("click", () => document.getElementById("artifactDialog").close());
    document.addEventListener("click", event => {
      const run = event.target.closest(".run");
      if (run?.dataset.path) openArtifact(run.dataset.path);
      const tab = event.target.closest(".tab");
      if (tab) { activeLog = tab.dataset.log; renderLog(); }
    });
    load();
    setInterval(load, 20000);
  </script>
</body>
</html>"""
