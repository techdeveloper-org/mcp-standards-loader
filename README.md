# mcp-standards-loader

A FastMCP server providing **Standards Loader** capabilities for Claude Code workflows.

---

## Overview

Project type detection and coding standards loading with conflict resolution. Detects project language/framework automatically, loads standards from 4 priority sources (custom > team > framework > language), resolves conflicts, and caches with file modification tracking.

---

## Tools

| Tool | Description |
|------|-------------|
| `detect_project_type` | Auto-detect project language (Python/Java/TypeScript/Kotlin/etc.) |
| `detect_framework` | Detect active framework (Spring Boot/FastAPI/React/Angular/etc.) |
| `load_standards` | Load ordered standards for detected project/framework combination |
| `resolve_standard_conflicts` | Detect and resolve conflicting rules from multiple standards |
| `get_active_standards` | Return currently loaded standards with their sources |
| `list_available_standards` | List all standards files available in the standards directory |
| `reload_standards` | Force reload of standards cache (after rules/ directory changes) |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/techdeveloper-org/mcp-standards-loader.git
cd mcp-standards-loader
```

### 2. Install dependencies

```bash
pip install mcp fastmcp
```

### 3. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

---

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `CLAUDE_STANDARDS_DIR` | Path to standards/rules directory (default: rules/) |
| `CLAUDE_PROJECT_ROOT` | Root of the project to scan (default: CWD) |

---

## Usage in Claude Code

Add to your `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "standards-loader": {
      "command": "python",
      "args": [
        "/path/to/mcp-standards-loader/server.py"
      ],
      "env": {}
    }
  }
}
```

---

## Benefits

- Zero-config standard detection — no manual flags needed
- Priority ordering prevents team standards from being overridden by defaults
- File-modification-based cache invalidation (no stale standards)
- Conflict resolution surfaces rule clashes before they cause confusion

---

## Requirements

- Python 3.8+
- `mcp fastmcp`
- See `requirements.txt` for pinned versions

---

## Project Context

This MCP server is part of the **Claude Workflow Engine** ecosystem — a LangGraph-based
orchestration pipeline for automating Claude Code development workflows.

Related repos:
- [`claude-workflow-engine`](https://github.com/techdeveloper-org/claude-workflow-engine) — Main pipeline
- [`mcp-base`](https://github.com/techdeveloper-org/mcp-base) — Shared base utilities used by all MCP servers

---

## License

Private — techdeveloper-org
