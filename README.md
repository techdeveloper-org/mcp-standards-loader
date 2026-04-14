# mcp-standards-loader

![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue)
![License MIT](https://img.shields.io/badge/License-MIT-green)
![Part of claude-workflow-engine](https://img.shields.io/badge/Part%20of-claude--workflow--engine-blueviolet)

A FastMCP server that provides dynamic coding standards loading, project and framework detection, and priority-based conflict resolution for Claude Code workflows. Standards are loaded at runtime from up to four sources — custom, team, framework, and language — with higher-priority sources automatically winning any rule conflicts. A built-in 5-minute TTL cache with file-modification-based invalidation and optional `watchdog`-backed hot-reload ensures that changes to your `rules/` or `policies/` directories are picked up without restarting the server.

---

## Table of Contents

- [Features](#features)
- [Tools](#tools)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Integration](#integration)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **Automatic project detection** — identifies language from marker files (`setup.py`, `pom.xml`, `package.json`, `tsconfig.json`, `go.mod`, `Cargo.toml`, `*.csproj`, `Package.swift`, `*.kt`) with no configuration required
- **Framework detection** — resolves the active framework within the detected language: Django, Flask, FastAPI, LangGraph (Python); Spring Boot, Spring, Quarkus, Micronaut (Java); Next.js, React, Angular, Vue, Express, NestJS (JavaScript/TypeScript); SwiftUI or UIKit (Swift)
- **Four-source priority hierarchy** — custom project standards (priority 4) override team globals (priority 3), which override framework built-ins (priority 2), which override language defaults (priority 1)
- **Rule conflict detection and resolution** — scans all loaded standards for key collisions across sources and resolves them deterministically: the highest-priority source wins every conflicting key
- **Hot-reload with file watching** — optional `watchdog` integration starts a background observer that invalidates the cache automatically when any `.md` file in the watched directories is created, modified, or deleted; falls back to TTL-based cache (5 minutes) without `watchdog`
- **Full traceability** — every `load_standards` response includes a `traceability` block listing which sources were checked and how many standards were loaded from each
- **Lightweight summary mode** — `get_active_standards` returns counts and metadata only, without full standard content, for pipeline health checks
- **Standards catalog** — `list_available_standards` enumerates all `.md` files across all sources, filterable by source type, with file size included

---

## Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `detect_project_type` | Detects the primary programming language of a project by checking marker files | `project_path` (str, default `"."`) |
| `detect_framework` | Detects the active framework within a project type by inspecting dependency files and directory structure | `project_path` (str, default `"."`), `project_type` (str, auto-detected if empty) |
| `load_standards` | Runs the full detection + loading pipeline: detect language, detect framework, load all four source tiers, detect conflicts, resolve conflicts, return merged rules with traceability | `project_path` (str, default `"."`) |
| `resolve_standard_conflicts` | Standalone conflict resolution for an arbitrary list of standards objects; useful for offline analysis or testing | `standards_json` (str, JSON array of standard objects with `rules` and `priority` fields) |
| `get_active_standards` | Returns a lightweight summary of currently active standards — counts by source, conflict count, total rule count — without full standard content | `project_path` (str, default `"."`) |
| `list_available_standards` | Enumerates all available `.md` standard files across team, architecture, and policy sources with file size | `source` (str, one of `"all"`, `"team"`, `"framework"`, `"language"`, default `"all"`) |
| `reload_standards` | Invalidates the standards cache and optionally starts a background file watcher; only performs a full reload when file modifications are detected or the cache is stale | `project_path` (str, default `"."`), `start_watcher` (bool, default `True`) |

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/techdeveloper-org/mcp-standards-loader.git
cd mcp-standards-loader
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

For hot-reload support (optional but recommended):

```bash
pip install watchdog
```

### 3. Register in Claude Code

Add the server to your `~/.claude/settings.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "standards-loader": {
      "command": "python",
      "args": ["/absolute/path/to/mcp-standards-loader/server.py"],
      "env": {
        "CLAUDE_STANDARDS_DIR": "/absolute/path/to/your/rules",
        "CLAUDE_PROJECT_ROOT": "/absolute/path/to/your/project"
      }
    }
  }
}
```

Replace the paths with the actual locations on your machine. On Windows, use forward slashes or escaped backslashes in the JSON.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_STANDARDS_DIR` | `rules/` relative to CWD | Path to the project's standards or rules directory. When set, this directory is included as a custom (priority 4) standards source. |
| `CLAUDE_PROJECT_ROOT` | Current working directory | Root of the project to scan for marker files and local `.claude/standards/` directories. |

### Standards Source Directories

The server resolves standards from four locations in priority order:

| Priority | Source | Path |
|----------|--------|------|
| 4 (highest) | Custom — project-local | `<project_root>/.claude/standards/` or `<project_root>/standards/` |
| 3 | Team — global user config | `~/.claude/policies/02-standards-system/` or `~/.claude/standards/` |
| 2 | Framework — engine built-ins | `<engine_root>/scripts/architecture/02-standards-system/` |
| 1 (lowest) | Language / policy | `<engine_root>/policies/02-standards/` |

All sources are scanned for `*.md` files recursively. Files named `README.md` and `CHANGELOG.md` are skipped automatically.

### Cache Behavior

- Cache TTL: 5 minutes
- Invalidation triggers: file modification detected via mtime tracking on any watched `.md` file, or explicit `reload_standards` call
- With `watchdog` installed: cache is invalidated in real time on any create/modify/delete event in the watched directories
- Without `watchdog`: cache freshness is checked by comparing mtime snapshots on each `load_standards` call

---

## Usage Examples

### Example 1: Detect project type and framework before loading standards

```python
import json
import subprocess

# detect_project_type
result = subprocess.run(
    ["python", "server.py"],
    input=json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "detect_project_type",
            "arguments": {"project_path": "/workspace/my-fastapi-service"}
        }
    }),
    capture_output=True, text=True
)
# Returns: {"success": true, "project_type": "python", "project_path": "/workspace/my-fastapi-service"}

# detect_framework
result = subprocess.run(
    ["python", "server.py"],
    input=json.dumps({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "detect_framework",
            "arguments": {
                "project_path": "/workspace/my-fastapi-service",
                "project_type": "python"
            }
        }
    }),
    capture_output=True, text=True
)
# Returns: {"success": true, "project_type": "python", "framework": "fastapi", ...}
```

### Example 2: Load all standards for a project and inspect merged rules

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "load_standards",
    "arguments": {
      "project_path": "/workspace/my-spring-boot-api"
    }
  }
}
```

Response structure:

```json
{
  "success": true,
  "project_type": "java",
  "framework": "spring-boot",
  "standards_loaded": 5,
  "standards_list": [
    {"id": "spring-boot-standards", "source": "framework", "priority": 2, "file": "..."},
    {"id": "java-standards", "source": "language", "priority": 1, "file": "..."},
    {"id": "team-naming-rules", "source": "team", "priority": 3, "file": "..."}
  ],
  "conflicts": [
    {
      "standard1": "java-standards",
      "standard2": "team-naming-rules",
      "conflicting_rules": ["max_line_length"]
    }
  ],
  "conflict_count": 1,
  "merged_rules": {
    "max_line_length": "120",
    "require_javadoc": "true"
  },
  "traceability": {
    "project_type": "java",
    "framework": "spring-boot",
    "sources_checked": [
      {"source": "custom", "priority": 4, "loaded": 0},
      {"source": "team", "priority": 3, "loaded": 1},
      {"source": "framework", "priority": 2, "loaded": 2},
      {"source": "language", "priority": 1, "loaded": 2}
    ]
  },
  "from_cache": false
}
```

### Example 3: Get a lightweight active standards summary for pipeline health checks

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "tools/call",
  "params": {
    "name": "get_active_standards",
    "arguments": {
      "project_path": "/workspace/my-react-app"
    }
  }
}
```

Response:

```json
{
  "success": true,
  "project_type": "javascript",
  "framework": "react",
  "total_loaded": 3,
  "by_source": {
    "custom": 0,
    "team": 1,
    "framework": 1,
    "language": 1
  },
  "conflict_count": 0,
  "rule_count": 14
}
```

### Example 4: Force a hot-reload after editing a standards file

```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "tools/call",
  "params": {
    "name": "reload_standards",
    "arguments": {
      "project_path": "/workspace/my-django-app",
      "start_watcher": true
    }
  }
}
```

Response when changes are detected and `watchdog` is available:

```json
{
  "success": true,
  "reloaded": true,
  "from_cache": false,
  "standards_loaded": 4,
  "project_type": "python",
  "framework": "django",
  "standards_last_loaded_at": "2026-04-14T10:23:45Z",
  "watcher": {
    "status": "started",
    "watching": [
      "/workspace/claude-workflow-engine/policies",
      "/home/user/.claude/policies/02-standards-system"
    ]
  },
  "watched_dirs": ["..."]
}
```

Response when no files have changed and cache is still fresh:

```json
{
  "success": true,
  "reloaded": false,
  "from_cache": true,
  "standards_loaded": 4,
  ...
}
```

---

## Integration

### Role in the Claude Workflow Engine Pipeline

`mcp-standards-loader` operates at **Level 2** of the three-level LangGraph orchestration pipeline. Level 2 is a policy layer — it has no pipeline nodes of its own. Instead, coding standards are loaded as `.md` policies from the `policies/02-standards-system/` directory and made available to the orchestration steps on demand.

```
Level -1  Auto-Fix          (Unicode, encoding, path enforcement)
Level 1   Sync              (session sync, complexity scoring)
Level 2   Standards         <-- mcp-standards-loader serves this layer
Level 3   Execution         (Step 0 orchestration, Steps 8-14: issue, branch, impl, PR, close, docs)
```

The server is invoked primarily during:

- **Step 0 (Task Analysis)** — the orchestration prompt template may request standards context for the detected project and framework before generating the implementation plan
- **Step 10 (Implementation)** — active standards are available to enforcement checks during code generation
- **Step 11 (Code Review)** — merged rules are used as the authoritative source for style and compliance assertions

### Relationship to Other MCP Servers

| Server | Relationship |
|--------|-------------|
| `mcp-policy-enforcement` | Consumes standards loaded by this server to perform per-tool policy checks |
| `mcp-pre-tool-gate` | May call `get_active_standards` to determine which rules apply before a tool is executed |
| `mcp-base` | Shared `base/` package — `MCPResponse` builder, `@mcp_tool_handler` decorator — included as a local copy in this repo |

### Standards File Format

Standard files are Markdown (`.md`). Rules are extracted from lines matching the pattern:

```markdown
- **rule_name**: rule_value
```

For example:

```markdown
## Python Coding Standards

- **max_line_length**: 120
- **require_type_hints**: true
- **docstring_style**: google
- **import_order**: isort
```

Place project-specific standards under `<project_root>/.claude/standards/` or `<project_root>/standards/`. Team-wide standards go under `~/.claude/policies/02-standards-system/` or `~/.claude/standards/`.

---

## Contributing

Contributions are welcome. Please follow the standard fork-and-pull-request workflow:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-change`
3. Commit your changes with a clear message
4. Open a pull request against `main`

All code must be Python 3.8+ compatible, ASCII-safe (cp1252-safe for Windows), and follow PEP 8 conventions. New tools must be decorated with both `@mcp.tool()` and `@mcp_tool_handler` and must return JSON via `to_json()`.

For bugs or feature requests, open a GitHub issue in the [mcp-standards-loader](https://github.com/techdeveloper-org/mcp-standards-loader) repository.

---

## License

MIT License. See [LICENSE](LICENSE) for full terms.

---

**Part of the [Claude Workflow Engine](https://github.com/techdeveloper-org/claude-workflow-engine) ecosystem — 13 MCP servers, 295 tools, LangGraph orchestration.**
