from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import threading
import time
from typing import Any


class McpStdioError(RuntimeError):
    pass


class McpStdioClient:
    def __init__(
        self,
        config,
        *,
        timeout_s: float = 12.0,
        map_platform_root: str | None = None,
        map_platform_write_enabled: bool = False,
    ):
        self.config = config
        self.timeout_s = timeout_s
        self.map_platform_root = map_platform_root or config.map_platform_root
        self.map_platform_write_enabled = map_platform_write_enabled
        self.next_id = 1
        self.process: subprocess.Popen[str] | None = None
        self.stderr_chunks: list[str] = []
        self.stderr_thread: threading.Thread | None = None

    def __enter__(self):
        server_js = Path(self.config.mcp_server_root) / "src" / "server.js"
        if not server_js.exists():
            raise McpStdioError(f"MCP server entrypoint not found: {server_js}")
        env = os.environ.copy()
        env.update({
            "STRATEGY_ROOT": self.config.host_strategy_root,
            "INTACT_WORKSPACE": str(Path(self.config.mcp_server_root) / "data"),
            "MAP_PLATFORM_ROOT": self.map_platform_root,
            "MAP_PLATFORM_WRITE_ENABLED": "true" if self.map_platform_write_enabled else "false",
        })
        self.process = subprocess.Popen(
            ["node", str(server_js)],
            cwd=self.config.mcp_server_root,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        self.stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self.stderr_thread.start()
        self.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "intact-agent-runner", "version": "0.1.0"},
        })
        self.notify("notifications/initialized", {})
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.process:
            return
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.terminate()
            self.process.wait(timeout=2)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass

    def _drain_stderr(self) -> None:
        process = self.process
        if not process or not process.stderr:
            return
        while True:
            chunk = process.stderr.readline()
            if not chunk:
                break
            try:
                self.stderr_chunks.append(chunk.decode("utf-8", errors="replace").strip())
            except Exception:
                self.stderr_chunks.append(str(chunk))
            if len(self.stderr_chunks) > 40:
                self.stderr_chunks = self.stderr_chunks[-40:]

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        request_id = self.next_id
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        response = self._read_response()
        if response.get("id") != request_id:
            raise McpStdioError(f"Unexpected MCP response id: {response.get('id')} expected {request_id}")
        if "error" in response:
            raise McpStdioError(f"MCP {method} failed: {response['error']}")
        return response.get("result")

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def _send(self, message: dict[str, Any]) -> None:
        process = self._process()
        if not process.stdin:
            raise McpStdioError("MCP stdin is closed")
        body = json.dumps(message, separators=(",", ":")).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        process.stdin.write(header + body)
        process.stdin.flush()

    def _read_response(self) -> dict[str, Any]:
        process = self._process()
        if not process.stdout:
            raise McpStdioError("MCP stdout is closed")
        deadline = time.monotonic() + self.timeout_s
        header = self._read_until_double_crlf(process.stdout, deadline)
        length = self._content_length(header)
        body = self._read_exact(process.stdout, length, deadline)
        return json.loads(body.decode("utf-8"))

    def _process(self) -> subprocess.Popen[bytes]:
        if not self.process:
            raise McpStdioError("MCP process is not started")
        if self.process.poll() is not None:
            stderr = "\n".join(self.stderr_chunks[-10:])
            raise McpStdioError(f"MCP process exited with {self.process.returncode}. {stderr}")
        return self.process  # type: ignore[return-value]

    @classmethod
    def _read_until_double_crlf(cls, stream, deadline: float) -> bytes:
        data = bytearray()
        while not data.endswith(b"\r\n\r\n"):
            data.extend(cls._read_exact(stream, 1, deadline))
            if len(data) > 8192:
                raise McpStdioError("MCP response header too large")
        return bytes(data)

    @staticmethod
    def _read_exact(stream, length: int, deadline: float) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpStdioError("Timed out waiting for MCP stdio response")
            ready, _, _ = select.select([stream], [], [], remaining)
            if not ready:
                raise McpStdioError("Timed out waiting for MCP stdio response")
            chunk = os.read(stream.fileno(), length - len(chunks))
            if not chunk:
                raise McpStdioError("MCP response body ended early")
            chunks.extend(chunk)
        return bytes(chunks)

    @staticmethod
    def _content_length(header: bytes) -> int:
        for line in header.decode("ascii", errors="replace").split("\r\n"):
            if line.lower().startswith("content-length:"):
                return int(line.split(":", 1)[1].strip())
        raise McpStdioError("MCP response missing Content-Length")


def tool_text(result: Any) -> str:
    if not isinstance(result, dict):
        return json.dumps(result, indent=2)
    content = result.get("content")
    if not isinstance(content, list):
        return json.dumps(result, indent=2)
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "\n".join(parts)


def tool_json(result: Any) -> Any:
    text = tool_text(result)
    try:
        return json.loads(text)
    except Exception:
        return text
