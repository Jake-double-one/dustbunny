"""MCP (Model Context Protocol) for AI agents: Claude, ChatGPT, Grok, Claude Code …

A small, stateless implementation of the "Streamable HTTP" transport: every
request is one JSON-RPC message in a POST, every answer is plain JSON. Only
tools are offered. Off unless MCP_ENABLED; see README "AI agents (MCP)".

Agents can read the report and start a scan. Changing what Dustbunny remembers
(ignoring a folder) needs MCP_ALLOW_CHANGES. Nothing here can touch a folder.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from dustbunny import __version__
from dustbunny.models import Category, FolderResult, ScanReport
from dustbunny.notify import format_size
from dustbunny.service import ScanService

# newest first; an unknown version requested by a client gets the newest
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

INSTRUCTIONS = (
    "Dustbunny lists the folders in the Docker appdata directories of a server and tells which "
    "ones nothing uses anymore (orphaned). Start with get_summary, then list_folders with "
    "category 'orphan', and get_folder for the reasons. Dustbunny only reads: it never deletes "
    "folders, and neither can you through it. If the report is incomplete or uncertain, say so "
    "- orphaned folders may be wrong then."
)

_PARSE_ERROR, _INVALID_REQUEST, _METHOD_NOT_FOUND, _INVALID_PARAMS = -32700, -32600, -32601, -32602


class ToolError(Exception):
    """A tool failed in a way the agent should read (isError result, not a protocol error)."""


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    run: Callable[[dict[str, Any]], Any]
    read_only: bool = True
    title: str = ""

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title or self.name,
            "description": self.description,
            "inputSchema": self.schema,
            "annotations": {
                "readOnlyHint": self.read_only,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        }


@dataclass
class McpServer:
    service: ScanService
    trigger_scan: Callable[[], bool]  # returns True if a new scan was started
    allow_changes: bool = False
    tools: dict[str, Tool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for tool in self._tools():
            self.tools[tool.name] = tool

    # ---- JSON-RPC ----------------------------------------------------------------

    def handle(self, body: bytes) -> dict[str, Any] | None:
        """One JSON-RPC message in, the answer out (``None`` for notifications)."""
        try:
            message = json.loads(body)
        except ValueError:
            return _error(None, _PARSE_ERROR, "Parse error")
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, _INVALID_REQUEST, "Invalid request")
        method = message.get("method")
        if not isinstance(method, str):
            # a response from the client (we never send requests) needs no answer
            return None if "id" in message else _error(None, _INVALID_REQUEST, "Invalid request")
        if "id" not in message:
            return None  # notification, e.g. notifications/initialized
        request_id = message["id"]
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _error(request_id, _INVALID_PARAMS, "params must be an object")
        if method == "initialize":
            return _result(request_id, self._initialize(params))
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/list":
            return _result(request_id, {"tools": [t.describe() for t in self.tools.values()]})
        if method == "tools/call":
            return self._call(request_id, params)
        return _error(request_id, _METHOD_NOT_FOUND, f"Method not found: {method}")

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "dustbunny", "title": "Dustbunny", "version": __version__},
            "instructions": INSTRUCTIONS,
        }

    def _call(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(str(params.get("name")))
        if tool is None:
            return _error(request_id, _INVALID_PARAMS, f"Unknown tool: {params.get('name')}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(request_id, _INVALID_PARAMS, "arguments must be an object")
        try:
            data = tool.run(arguments)
        except ToolError as exc:
            return _result(
                request_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            )
        text = json.dumps(data, ensure_ascii=False, indent=1, default=str)
        return _result(
            request_id,
            {"content": [{"type": "text", "text": text}], "structuredContent": data},
        )

    # ---- tools -------------------------------------------------------------------

    def _tools(self) -> list[Tool]:
        categories = [c.value for c in Category]
        tools = [
            Tool(
                name="get_summary",
                title="Summary",
                description="Overview of the last scan: how many folders per category, how much "
                "space orphaned folders take, whether the result is complete and reliable, "
                "warnings, and when the next scan runs.",
                schema={"type": "object", "properties": {}, "additionalProperties": False},
                run=lambda _args: self._summary(),
            ),
            Tool(
                name="list_folders",
                title="List folders",
                description="Folders of the last scan with category, size and age. Categories: "
                "orphan (nothing uses it), defined-only (only in a stack/compose file), "
                "stopped (only stopped containers), active (a running container), ignored.",
                schema={
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": ["all", *categories]},
                        "query": {
                            "type": "string",
                            "description": "Part of the folder name, path or container name",
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    },
                    "additionalProperties": False,
                },
                run=self._list_folders,
            ),
            Tool(
                name="get_folder",
                title="Folder details",
                description="Everything about one folder: why it has its category, which "
                "containers and stacks use it (and how), size, last change, orphaned since.",
                schema={
                    "type": "object",
                    "properties": {
                        "folder": {
                            "type": "string",
                            "description": "Full path (/opt/appdata/sonarr) or folder name",
                        }
                    },
                    "required": ["folder"],
                    "additionalProperties": False,
                },
                run=lambda args: _folder_detail(self._find(args.get("folder"))),
            ),
            Tool(
                name="start_scan",
                title="Start a scan",
                description="Start a new scan now (it runs in the background; call get_summary "
                "later). Reads only - changes nothing.",
                schema={"type": "object", "properties": {}, "additionalProperties": False},
                run=lambda _args: self._start_scan(),
            ),
        ]
        if self.allow_changes:
            tools.append(
                Tool(
                    name="set_folder_ignored",
                    title="Ignore a folder",
                    description="Ignore a folder in Dustbunny (or stop ignoring it), e.g. when "
                    "the user says it is still needed. Only changes Dustbunny's own list - the "
                    "folder itself is never touched.",
                    schema={
                        "type": "object",
                        "properties": {
                            "folder": {"type": "string", "description": "Full path or name"},
                            "ignored": {"type": "boolean"},
                        },
                        "required": ["folder", "ignored"],
                        "additionalProperties": False,
                    },
                    run=self._set_ignored,
                    read_only=False,
                )
            )
        return tools

    def _report(self) -> ScanReport:
        if self.service.config_error:
            raise ToolError(f"Dustbunny is not set up: {self.service.config_error}")
        if self.service.report is None:
            raise ToolError(
                "No scan has finished yet. Call start_scan, then try again in a minute."
            )
        return self.service.report

    def _summary(self) -> dict[str, Any]:
        report = self._report()
        return {
            "last_scan": report.generated_at.isoformat(),
            "scanning": self.service.scanning,
            "scan_roots": report.roots,
            "complete": report.complete,
            "uncertain": report.uncertain,
            "reliable": report.reliable,
            "folders": report.summary.total,
            "counts": {c.value: n for c, n in report.summary.counts.items()},
            "orphaned_size": format_size(report.summary.orphan_bytes),
            "orphaned_bytes": report.summary.orphan_bytes,
            "total_size": format_size(report.summary.total_bytes),
            "sources": [
                {"name": s.name, "ok": s.ok, "error": s.error, "references": s.reference_count}
                for s in report.sources
            ],
            "warnings": [w.message for w in report.warnings],
        }

    def _list_folders(self, args: dict[str, Any]) -> dict[str, Any]:
        report = self._report()
        category = args.get("category") or "all"
        if category != "all" and category not in {c.value for c in Category}:
            raise ToolError(f"Unknown category {category!r}")
        query = str(args.get("query") or "").strip().lower()
        limit = args.get("limit") or 100
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ToolError("limit must be a number from 1 to 500")
        found = [
            f
            for f in report.folders
            if (category == "all" or f.category.value == category)
            and (not query or query in _haystack(f))
        ]
        return {
            "total": len(found),
            "shown": min(len(found), limit),
            "folders": [_folder_line(f) for f in found[:limit]],
        }

    def _find(self, value: Any) -> FolderResult:
        if not isinstance(value, str) or not value.strip():
            raise ToolError("folder is required: a full path or a folder name")
        value = value.strip().rstrip("/")
        folders = self._report().folders
        by_path = [f for f in folders if f.path == value]
        matches = by_path or [f for f in folders if f.name == value]
        if not matches:
            raise ToolError(f"No folder {value!r} in the last scan. Use list_folders to find it.")
        if len(matches) > 1:
            paths = ", ".join(f.path for f in matches)
            raise ToolError(f"{value!r} exists in several scan roots, use the full path: {paths}")
        return matches[0]

    def _start_scan(self) -> dict[str, Any]:
        if not self.service.ready:
            raise ToolError(f"Dustbunny is not set up: {self.service.config_error}")
        started = self.trigger_scan()
        return {
            "started": started,
            "message": "Scan started. Call get_summary in a minute."
            if started
            else "A scan is already running. Call get_summary in a minute.",
        }

    def _set_ignored(self, args: dict[str, Any]) -> dict[str, Any]:
        folder = self._find(args.get("folder"))
        ignored = args.get("ignored")
        if not isinstance(ignored, bool):
            raise ToolError("ignored must be true or false")
        report = self.service.set_ignored(folder.path, ignored)
        updated = next(f for f in report.folders if f.path == folder.path)
        return _folder_line(updated)


def _haystack(folder: FolderResult) -> str:
    owners = [h.reference.owner or "" for h in [*folder.protected_by, *folder.broad_access]]
    return " ".join([folder.name, folder.path, *owners]).lower()


def _folder_line(folder: FolderResult) -> dict[str, Any]:
    return {
        "path": folder.path,
        "name": folder.name,
        "category": folder.category.value,
        "size": format_size(folder.size_bytes),
        "size_bytes": folder.size_bytes,
        "orphaned_since": folder.first_seen.isoformat() if folder.first_seen else None,
        "last_change": folder.last_modified.isoformat() if folder.last_modified else None,
        "reason": folder.reasons[0].message if folder.reasons else None,
    }


def _folder_detail(folder: FolderResult) -> dict[str, Any]:
    def ref(hit: Any) -> dict[str, Any]:
        r = hit.reference
        return {
            "owner": r.owner,
            "state": r.state.value,
            "kind": r.kind,
            "source": r.source,
            "path": r.path,
            "relation": hit.relation.value,
        }

    return {
        **_folder_line(folder),
        "root": folder.root,
        "reasons": [r.message for r in folder.reasons],
        "used_by": [ref(h) for h in folder.protected_by],
        "mounts_whole_scan_root": [ref(h) for h in folder.broad_access],
        "sources_checked": folder.checked_sources,
        "size_complete": folder.stats_complete,
        "symlink": folder.is_symlink,
        "mountpoint": folder.is_mountpoint,
    }


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def token_matches(given: str | None, expected: str) -> bool:
    return bool(given) and secrets.compare_digest(given.encode(), expected.encode())


def origin_allowed(origin: str | None, host: str | None) -> bool:
    """Requests from a web page must come from the same host (DNS rebinding protection).
    Agents' servers and command line clients send no Origin at all."""
    if not origin:
        return True
    return bool(host) and urlsplit(origin).netloc == host
