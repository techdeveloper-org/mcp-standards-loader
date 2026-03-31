# mcp-standards-loader — Claude Project Context

**Type:** FastMCP Server
**Transport:** stdio
**Python:** 3.8+

---

## What This Server Does

Project type detection and coding standards loading with conflict resolution. Detects project language/framework automatically, loads standards from 4 priority sources (custom > team > framework > language), resolves conflicts, and caches with file modification tracking.

---

## Entry Point

```
server.py
```

Run via `python server.py` — communicates over stdio using the MCP protocol.

---

## Available Tools

- `detect_project_type` — Auto-detect project language (Python/Java/TypeScript/Kotlin/etc.)
- `detect_framework` — Detect active framework (Spring Boot/FastAPI/React/Angular/etc.)
- `load_standards` — Load ordered standards for detected project/framework combination
- `resolve_standard_conflicts` — Detect and resolve conflicting rules from multiple standards
- `get_active_standards` — Return currently loaded standards with their sources
- `list_available_standards` — List all standards files available in the standards directory
- `reload_standards` — Force reload of standards cache (after rules/ directory changes)

---

## Shared Utilities (in this repo)

- `base/` — Shared MCP infrastructure package (response builder, decorators, persistence, clients)
- `mcp_errors.py` — Structured error response helpers
- `input_validator.py` — Null-byte strip, length limits, prompt injection detection
- `rate_limiter.py` — Token bucket rate limiter (enable via ENABLE_RATE_LIMITING=1)

---

## Environment Variables

- `CLAUDE_STANDARDS_DIR` — Path to standards/rules directory (default: rules/)
- `CLAUDE_PROJECT_ROOT` — Root of the project to scan (default: CWD)

---

## Development

### Running locally

```bash
# Install deps
pip install -r requirements.txt

# Run the MCP server (stdio mode)
python server.py
```

### Testing a tool call manually

```python
import subprocess, json

proc = subprocess.Popen(
    ["python", "server.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
)
# Send MCP initialize + tool call via stdin
```

### File structure

```
mcp-standards-loader/
+-- server.py          # Main FastMCP server (entry point)
+-- base/              # Shared base package (response, decorators, persistence, clients)
+-- mcp_errors.py      # Error helpers
+-- input_validator.py # Input validation
+-- rate_limiter.py    # Rate limiting
+-- requirements.txt
+-- .gitignore
+-- README.md
+-- CLAUDE.md
```

---

## Key Rules

1. Do NOT edit `base/` directly — it is a copy from `mcp-base` repo
2. To update shared utilities, edit in `mcp-base` and re-copy
3. Keep `server.py` as the single entry point
4. All tool handlers must use `@mcp_tool_handler` decorator for consistent error handling
5. All responses must use `success()` / `error()` / `MCPResponse` builder from `base.response`

---

**Last Updated:** 2026-03-31
