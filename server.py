"""
Standards Loader MCP Server - Project type detection + standards loading.

Consolidates standard_selector.py (706), standards_integration.py (620),
standards_schema.py (354), standards-loader.py (~200) = 1,880 LOC into
a single FastMCP server.

Workflow:
1. Detect project type from marker files (setup.py, pom.xml, package.json, etc.)
2. Detect framework within project type (Flask, Spring Boot, React, etc.)
3. Load standards from 4 sources with priority ordering:
   custom(4) > team(3) > framework(2) > language(1)
4. Detect and resolve conflicts (higher priority wins)
5. Return merged rules for pipeline enforcement

Backend: Direct file I/O + glob patterns
Transport: stdio

Tools (6):
  detect_project_type, detect_framework, load_standards,
  resolve_standard_conflicts, get_active_standards, list_available_standards
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Annotated, Optional

# Ensure src/mcp/ is in path for base package imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

# mcp 2.0 renamed FastMCP to MCPServer and moved it to mcp.server.mcpserver.
# Both names are probed so this server runs under either major version; the
# API used below (tool decorator, run(transport=...)) is identical in both.
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp < 2.0
    from mcp.server.fastmcp import FastMCP as MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from base.response import to_json
from base.decorators import mcp_tool_handler

mcp = MCPServer(
    "standards-loader",
    instructions="Project type detection and coding standards loading with conflict resolution"
)

# This repository's directory and the workspace holding it alongside siblings.
_REPO_DIR = Path(__file__).resolve().parent
_WORKSPACE_ROOT = _REPO_DIR.parent


def _env_dir(var_name: str, default: Path) -> Path:
    """Resolve a directory from an environment variable, falling back to a default.

    Args:
        var_name: Environment variable holding an override path.
        default: Path used when the variable is unset or empty.

    Returns:
        The resolved Path, with ~ expanded.
    """
    raw = os.environ.get(var_name)
    if raw:
        return Path(raw).expanduser()
    return default


def _resolve_arch_standards_dir() -> Optional[Path]:
    """Locate the built-in framework/language standards directory.

    Resolution order: CLAUDE_ARCHITECTURE_DIR/02-standards-system, then any
    sibling repository in the workspace exposing
    scripts/architecture/02-standards-system.

    Returns:
        The directory Path, or None when no candidate exists on disk.
    """
    override = os.environ.get("CLAUDE_ARCHITECTURE_DIR")
    if override:
        candidate = Path(override).expanduser() / "02-standards-system"
        return candidate if candidate.is_dir() else None

    try:
        children = sorted(_WORKSPACE_ROOT.iterdir())
    except OSError:
        return None
    for child in children:
        candidate = child / "scripts" / "architecture" / "02-standards-system"
        if candidate.is_dir():
            return candidate
    return None


# Paths. Every location is env-overridable and defaults under the Claude home
# directory, matching the path contract the rest of the fleet uses. The previous
# constants were anchored to this repository's grandparent directory, which has
# not held policies/ or scripts/ since the servers were split into sibling repos.
CLAUDE_HOME = _env_dir("CLAUDE_HOME", Path.home() / ".claude")
POLICIES_DIR = _env_dir("CLAUDE_POLICIES_DIR", CLAUDE_HOME / "policies")
ARCH_STANDARDS_DIR = _resolve_arch_standards_dir()
TEAM_STANDARDS_DIR = POLICIES_DIR / "02-standards-system"
TEAM_STANDARDS_ALT = CLAUDE_HOME / "standards"
# Global rule files. CLAUDE_STANDARDS_DIR is documented in this server's
# CLAUDE.md but was previously never read, so ~/.claude/rules was invisible to
# every load even though it holds the active coding standards.
RULES_DIR = _env_dir("CLAUDE_STANDARDS_DIR", CLAUDE_HOME / "rules")

# Priority constants
PRIORITY_CUSTOM = 4
PRIORITY_TEAM = 3
PRIORITY_FRAMEWORK = 2
PRIORITY_LANGUAGE = 1

# Read-only annotation: every tool here inspects the filesystem and in-process
# cache without mutating any user-visible state.
_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

# Rule extraction pattern, compiled once rather than per standards file.
_RULE_PATTERN = re.compile(r'-\s+\*\*(\w[\w\s-]*)\*\*\s*:\s*(.+)')


def _has_any(root: Path, pattern: str) -> bool:
    """Test whether at least one path under root matches a glob pattern.

    Short-circuits on the first match. The previous form materialized the entire
    recursive match list before slicing it, so a single existence test walked the
    whole project tree.

    Args:
        root: Directory to search.
        pattern: Glob pattern, may be recursive.

    Returns:
        True when at least one match exists.
    """
    try:
        return next(root.glob(pattern), None) is not None
    except OSError:
        return False


# =============================================================================
# TOOL 1: DETECT PROJECT TYPE
# =============================================================================

@mcp.tool(annotations=_READ_ONLY)
@mcp_tool_handler
def detect_project_type(
    project_path: Annotated[str, Field(
        description="Filesystem path to the project root to inspect. Defaults to the current working directory.")] = ".",
) -> str:
    """Detect the primary programming language of a project.

    Checks marker files: setup.py, pom.xml, package.json, tsconfig.json,
    go.mod, Cargo.toml, *.csproj

    Args:
        project_path: Path to project root directory
    """
    try:
        root = Path(project_path).resolve()

        if not root.exists():
            return to_json({"success": False, "error": f"Path not found: {project_path}"})

        # Python
        if any((root / f).exists() for f in ["setup.py", "pyproject.toml", "requirements.txt", "Pipfile"]):
            lang = "python"
        # Java
        elif any((root / f).exists() for f in ["pom.xml", "build.gradle", "build.gradle.kts"]):
            lang = "java"
        # TypeScript (check before JS)
        elif (root / "tsconfig.json").exists():
            lang = "typescript"
        # JavaScript
        elif (root / "package.json").exists():
            lang = "javascript"
        # Go
        elif (root / "go.mod").exists():
            lang = "go"
        # Rust
        elif (root / "Cargo.toml").exists():
            lang = "rust"
        # C#
        elif _has_any(root, "**/*.csproj") or _has_any(root, "**/*.sln"):
            lang = "csharp"
        # Swift
        elif (root / "Package.swift").exists() or _has_any(root, "**/*.xcodeproj"):
            lang = "swift"
        # Kotlin
        elif _has_any(root, "**/*.kt"):
            lang = "kotlin"
        else:
            lang = "unknown"

        return to_json({
            "success": True,
            "project_type": lang,
            "project_path": str(root),
        })
    except Exception as e:
        return to_json({"success": False, "error": str(e)})


# =============================================================================
# TOOL 2: DETECT FRAMEWORK
# =============================================================================

@mcp.tool(annotations=_READ_ONLY)
@mcp_tool_handler
def detect_framework(
    project_path: Annotated[str, Field(
        description="Filesystem path to the project root to inspect. Defaults to the current working directory.")] = ".",
    project_type: Annotated[str, Field(
        description="Detected language to scope framework detection to, e.g. 'python', 'java', 'typescript'. Auto-detected when empty.")] = "",
) -> str:
    """Detect the primary framework within a project type.

    Args:
        project_path: Path to project root
        project_type: Language (auto-detected if empty)
    """
    try:
        root = Path(project_path).resolve()

        if not project_type:
            result = json.loads(detect_project_type(project_path))
            project_type = result.get("project_type", "unknown")

        framework = "unknown"

        if project_type == "python":
            framework = _detect_python_fw(root)
        elif project_type == "java":
            framework = _detect_java_fw(root)
        elif project_type in ("javascript", "typescript"):
            framework = _detect_js_fw(root)
        elif project_type == "swift":
            framework = "swiftui" if _has_any(root, "**/*View.swift") else "uikit"

        return to_json({
            "success": True,
            "project_type": project_type,
            "framework": framework,
            "project_path": str(root),
        })
    except Exception as e:
        return to_json({"success": False, "error": str(e)})


def _detect_python_fw(root: Path) -> str:
    if (root / "manage.py").exists():
        return "django"
    # Check requirements.txt or pyproject.toml for framework hints
    for dep_file in ["requirements.txt", "pyproject.toml", "setup.py"]:
        fp = root / dep_file
        if fp.exists():
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore").lower()
                if "flask" in content:
                    return "flask"
                if "fastapi" in content:
                    return "fastapi"
                if "django" in content:
                    return "django"
                if "langgraph" in content or "langchain" in content:
                    return "langgraph"
            except Exception:
                pass
    return "unknown"


def _detect_java_fw(root: Path) -> str:
    for build_file in ["pom.xml", "build.gradle", "build.gradle.kts"]:
        fp = root / build_file
        if fp.exists():
            try:
                content = fp.read_text(encoding="utf-8", errors="ignore").lower()
                if "spring-boot" in content or "spring boot" in content:
                    return "spring-boot"
                if "spring" in content:
                    return "spring"
                if "quarkus" in content:
                    return "quarkus"
                if "micronaut" in content:
                    return "micronaut"
            except Exception:
                pass
    return "unknown"


def _detect_js_fw(root: Path) -> str:
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if "next" in deps:
                return "nextjs"
            if "react" in deps or "react-dom" in deps:
                return "react"
            if "@angular/core" in deps:
                return "angular"
            if "vue" in deps:
                return "vue"
            if "express" in deps:
                return "express"
            if "nestjs" in deps or "@nestjs/core" in deps:
                return "nestjs"
        except Exception:
            pass
    return "unknown"


# =============================================================================
# TOOL 3: LOAD STANDARDS
# =============================================================================

@mcp.tool(annotations=_READ_ONLY)
@mcp_tool_handler
def load_standards(
    project_path: Annotated[str, Field(
        description="Filesystem path to the project root to inspect. Defaults to the current working directory.")] = ".",
) -> str:
    """Load all applicable standards for a project with full traceability.

    Detection + loading pipeline:
    1. detect_project_type -> detect_framework
    2. Load custom standards (project-local, priority=4)
    3. Load team standards (global, priority=3)
    4. Load framework standards (built-in, priority=2)
    5. Load language standards (built-in, priority=1)
    6. Detect conflicts + resolve (higher priority wins)

    Args:
        project_path: Path to project root
    """
    try:
        root = Path(project_path).resolve()

        # Check cache freshness before full load
        cache_key = str(root)
        if cache_key in _standards_cache:
            cached_data, cached_ts = _standards_cache[cache_key]
            age = time.time() - cached_ts
            if age < _STANDARDS_CACHE_TTL:
                # Check if any watched dir has changed
                dirs_changed = _any_standards_changed()
                if not dirs_changed:
                    return to_json({**cached_data, "from_cache": True})

        # Detect project
        pt_result = json.loads(detect_project_type(str(root)))
        project_type = pt_result.get("project_type", "unknown")

        fw_result = json.loads(detect_framework(str(root), project_type))
        framework = fw_result.get("framework", "unknown")

        all_standards = []
        # Sources are loaded highest priority first and share one dedupe set, so
        # a file reachable from two sources is kept at the higher priority only.
        seen_files = set()
        traceability = {
            "project_type": project_type,
            "framework": framework,
            "sources_checked": [],
        }

        # 1. Custom standards (highest priority)
        custom = _load_from_dirs(
            [root / ".claude" / "standards", root / "standards"],
            "custom", PRIORITY_CUSTOM, seen_files
        )
        all_standards.extend(custom)
        traceability["sources_checked"].append({
            "source": "custom", "priority": PRIORITY_CUSTOM, "loaded": len(custom)
        })

        # 2. Team standards
        team = _load_from_dirs(
            [RULES_DIR, TEAM_STANDARDS_DIR, TEAM_STANDARDS_ALT],
            "team", PRIORITY_TEAM, seen_files
        )
        all_standards.extend(team)
        traceability["sources_checked"].append({
            "source": "team", "priority": PRIORITY_TEAM, "loaded": len(team)
        })

        # 3. Framework standards
        fw_standards = _load_framework_standards(project_type, framework, seen_files)
        all_standards.extend(fw_standards)
        traceability["sources_checked"].append({
            "source": "framework", "priority": PRIORITY_FRAMEWORK, "loaded": len(fw_standards)
        })

        # 4. Language standards
        lang_standards = _load_language_standards(project_type, seen_files)
        all_standards.extend(lang_standards)
        traceability["sources_checked"].append({
            "source": "language", "priority": PRIORITY_LANGUAGE, "loaded": len(lang_standards)
        })

        # 5. Detect conflicts
        conflicts = _detect_conflicts(all_standards)

        # 6. Resolve conflicts (higher priority wins)
        merged_rules = _resolve_conflicts(all_standards)

        result_data = {
            "success": True,
            "project_type": project_type,
            "framework": framework,
            "standards_loaded": len(all_standards),
            "standards_list": [
                {"id": s.get("id", ""), "source": s.get("source", ""),
                 "priority": s.get("priority", 0), "file": s.get("file", "")}
                for s in all_standards
            ],
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "merged_rules": merged_rules,
            "traceability": traceability,
            "standards_last_loaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "from_cache": False,
        }

        # Store in cache and prime the mtime baseline. Without priming, the very
        # first cache lookup has no baseline to compare against, reports every
        # watched directory as changed, and discards the entry it just stored.
        _any_standards_changed()
        _standards_cache[cache_key] = (result_data, time.time())

        return to_json(result_data)
    except Exception as e:
        return to_json({"success": False, "error": str(e)})


def _load_from_dirs(dirs, source, priority, seen=None):
    """Load .md standard files from directories, skipping already-loaded files.

    Sources are loaded highest-priority first, so a file reachable from two
    sources is kept only at the higher priority and is not double-counted in
    standards_loaded or compared against itself in conflict detection.

    Args:
        dirs: Directories to scan recursively.
        source: Source label recorded on each loaded standard.
        priority: Priority value recorded on each loaded standard.
        seen: Mutable set of already-loaded resolved paths, updated in place.

    Returns:
        List of standard dicts loaded from these directories.
    """
    standards = []
    if seen is None:
        seen = set()
    for d in dirs:
        if d is None or not d.exists():
            continue
        for md_file in sorted(d.rglob("*.md")):
            if md_file.name.lower() in ("readme.md", "changelog.md"):
                continue
            key = str(md_file.resolve()).lower()
            if key in seen:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                size_bytes = md_file.stat().st_size
            except OSError:
                continue
            seen.add(key)
            standards.append({
                "id": md_file.stem,
                "source": source,
                "priority": priority,
                "file": str(md_file),
                "content": content[:2000],  # First 2KB for rules extraction
                "size_bytes": size_bytes,
                "rules": _extract_rules(content),
            })
    return standards


def _load_framework_standards(project_type, framework, seen=None):
    """Load built-in framework standards from the architecture directory.

    Args:
        project_type: Detected language.
        framework: Detected framework, or 'unknown' to load nothing.
        seen: Mutable set of already-loaded resolved paths, updated in place.

    Returns:
        List of framework standard dicts.
    """
    standards = []
    if seen is None:
        seen = set()
    if framework == "unknown" or ARCH_STANDARDS_DIR is None:
        return standards
    patterns = [
        f"{project_type}-{framework}-standards.md",
        f"{framework}-standards.md",
        f"{framework}/*.md",
    ]
    for pattern in patterns:
        for md_file in ARCH_STANDARDS_DIR.glob(pattern):
            key = str(md_file.resolve()).lower()
            if key in seen:
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            seen.add(key)
            standards.append({
                "id": md_file.stem,
                "source": "framework",
                "priority": PRIORITY_FRAMEWORK,
                "file": str(md_file),
                "content": content[:2000],
                "rules": _extract_rules(content),
            })
    return standards


def _load_language_standards(project_type, seen=None):
    """Load built-in language standards.

    Scans the architecture standards directory for language-specific files and
    then the policies standards directory. That directory is named
    '02-standards-system'; the previous '02-standards' spelling matched nothing.

    Args:
        project_type: Detected language, or 'unknown' to load nothing.
        seen: Mutable set of already-loaded resolved paths, updated in place.

    Returns:
        List of language standard dicts.
    """
    standards = []
    if seen is None:
        seen = set()
    if project_type == "unknown":
        return standards

    if ARCH_STANDARDS_DIR is not None:
        patterns = [
            f"{project_type}-standards.md",
            "common-standards-policy.md",
        ]
        for pattern in patterns:
            for md_file in ARCH_STANDARDS_DIR.glob(pattern):
                key = str(md_file.resolve()).lower()
                if key in seen:
                    continue
                try:
                    content = md_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                seen.add(key)
                standards.append({
                    "id": md_file.stem,
                    "source": "language",
                    "priority": PRIORITY_LANGUAGE,
                    "file": str(md_file),
                    "content": content[:2000],
                    "rules": _extract_rules(content),
                })

    standards.extend(
        _load_from_dirs([POLICIES_DIR / "02-standards-system"],
                        "language", PRIORITY_LANGUAGE, seen)
    )
    return standards


def _extract_rules(content: str) -> dict:
    """Extract rule-like key-value pairs from markdown content."""
    rules = {}
    # Match patterns like: - **rule_name**: value
    for match in _RULE_PATTERN.finditer(content):
        key = match.group(1).strip().lower().replace(" ", "_").replace("-", "_")
        val = match.group(2).strip()
        rules[key] = val
    return rules


def _detect_conflicts(standards_list):
    """Detect conflicting rules between standards."""
    conflicts = []
    for i, std1 in enumerate(standards_list):
        rules1 = std1.get("rules", {})
        for std2 in standards_list[i + 1:]:
            rules2 = std2.get("rules", {})
            shared_keys = set(rules1.keys()) & set(rules2.keys())
            conflicting = [k for k in shared_keys if rules1[k] != rules2[k]]
            if conflicting:
                conflicts.append({
                    "standard1": std1.get("id", ""),
                    "standard2": std2.get("id", ""),
                    "conflicting_rules": conflicting,
                })
    return conflicts


def _resolve_conflicts(standards_list):
    """Resolve by applying lowest priority first, highest last (wins)."""
    sorted_stds = sorted(standards_list, key=lambda s: s.get("priority", 0))
    merged = {}
    for std in sorted_stds:
        rules = std.get("rules", {})
        for k, v in rules.items():
            merged[k] = v  # Later (higher priority) overwrites earlier
    return merged


# =============================================================================
# TOOL 4: RESOLVE CONFLICTS (standalone)
# =============================================================================

@mcp.tool(annotations=_READ_ONLY)
@mcp_tool_handler
def resolve_standard_conflicts(
    standards_json: Annotated[str, Field(
        description="JSON array string of standard objects, each with a 'rules' object and a numeric 'priority'. Higher priority wins on conflicting rule keys.")],
) -> str:
    """Resolve conflicts in a list of standards (higher priority wins).

    Args:
        standards_json: JSON array of standard objects with 'rules' and 'priority'
    """
    try:
        standards = json.loads(standards_json)
        conflicts = _detect_conflicts(standards)
        merged = _resolve_conflicts(standards)
        return to_json({
            "success": True,
            "conflicts": conflicts,
            "merged_rules": merged,
            "total_rules": len(merged),
        })
    except Exception as e:
        return to_json({"success": False, "error": str(e)})


# =============================================================================
# TOOL 5: GET ACTIVE STANDARDS
# =============================================================================

@mcp.tool(annotations=_READ_ONLY)
@mcp_tool_handler
def get_active_standards(
    project_path: Annotated[str, Field(
        description="Filesystem path to the project root to inspect. Defaults to the current working directory.")] = ".",
) -> str:
    """Get currently active standards summary for a project.

    Returns a lightweight summary without full content.

    Args:
        project_path: Path to project root
    """
    try:
        result = json.loads(load_standards(project_path))
        if not result.get("success"):
            return to_json(result)

        return to_json({
            "success": True,
            "project_type": result["project_type"],
            "framework": result["framework"],
            "total_loaded": result["standards_loaded"],
            "by_source": {
                s["source"]: s["loaded"]
                for s in result.get("traceability", {}).get("sources_checked", [])
            },
            "conflict_count": result["conflict_count"],
            "rule_count": len(result.get("merged_rules", {})),
        })
    except Exception as e:
        return to_json({"success": False, "error": str(e)})


# =============================================================================
# TOOL 6: LIST AVAILABLE STANDARDS
# =============================================================================

@mcp.tool(annotations=_READ_ONLY)
@mcp_tool_handler
def list_available_standards(
    source: Annotated[str, Field(
        description="Source filter: 'all', 'team', 'framework', or 'language'.")] = "all",
) -> str:
    """List all available standard files across all sources.

    Args:
        source: Filter by source - 'all', 'team', 'framework', 'language'
    """
    try:
        standards = []
        seen = set()

        def _collect(dirs, label, priority):
            """Append every non-README .md under dirs, skipping duplicates."""
            for d in dirs:
                if d is None or not d.exists():
                    continue
                for f in sorted(d.rglob("*.md")):
                    if f.name.lower() == "readme.md":
                        continue
                    key = str(f.resolve()).lower()
                    if key in seen:
                        continue
                    try:
                        size_kb = round(f.stat().st_size / 1024, 1)
                    except OSError:
                        continue
                    seen.add(key)
                    standards.append({
                        "id": f.stem, "source": label,
                        "priority": priority, "file": str(f),
                        "size_kb": size_kb,
                    })

        # Team standards, including the global rules directory.
        if source in ("all", "team"):
            _collect([RULES_DIR, TEAM_STANDARDS_DIR, TEAM_STANDARDS_ALT],
                     "team", PRIORITY_TEAM)

        # Architecture standards. ARCH_STANDARDS_DIR is None when no
        # architecture directory exists in this installation.
        if source in ("all", "framework", "language"):
            _collect([ARCH_STANDARDS_DIR], "architecture", PRIORITY_FRAMEWORK)

        # Policy standards. The directory is '02-standards-system'; the
        # previous '02-standards' spelling matched nothing on disk.
        if source in ("all", "language"):
            _collect([POLICIES_DIR / "02-standards-system"],
                     "policy", PRIORITY_LANGUAGE)

        return to_json({
            "success": True,
            "standards": standards,
            "count": len(standards),
            "source_filter": source,
            "searched_dirs": {
                "rules": str(RULES_DIR),
                "team": str(TEAM_STANDARDS_DIR),
                "team_alt": str(TEAM_STANDARDS_ALT),
                "architecture": str(ARCH_STANDARDS_DIR) if ARCH_STANDARDS_DIR else None,
                "policies": str(POLICIES_DIR / "02-standards-system"),
            },
        })
    except Exception as e:
        return to_json({"success": False, "error": str(e)})


# =============================================================================
# TOOL 7: RELOAD STANDARDS (invalidate cache on file changes)
# =============================================================================

# Standards cache with TTL and file modification tracking
_standards_cache = {}   # {cache_key: (data, timestamp)}
_cache_timestamp = 0
_CACHE_TTL = 300  # 5 minutes default
_STANDARDS_CACHE_TTL = 300  # 5 minutes
_standards_mtimes = {}  # {watched_dir: {file_path: last_mtime}}
_file_watcher_active = False


def _check_standards_changed(standards_dir) -> bool:
    """Check whether any .md file under a watched directory changed since last call.

    Mtimes are tracked per watched directory. A single flat map shared across
    directories made every call after the first report a change: scanning
    directory B replaced directory A's recorded mtimes, so A's files looked new
    on the next pass and B's looked deleted. That kept dirs_changed permanently
    true and disabled the standards cache entirely.

    Args:
        standards_dir: Directory to scan recursively for .md files.

    Returns:
        True when a file under this directory is new, modified, or deleted
        relative to the previous call for this same directory.
    """
    key = str(Path(standards_dir))
    previous = _standards_mtimes.get(key, {})
    current = {}

    try:
        for md_file in Path(standards_dir).rglob("*.md"):
            try:
                current[str(md_file)] = md_file.stat().st_mtime
            except OSError:
                continue
    except OSError:
        pass

    changed = current != previous
    _standards_mtimes[key] = current
    return changed


def _any_standards_changed() -> bool:
    """Report whether any watched standards directory changed since the last check.

    Every watched directory is scanned before the results are reduced. A
    short-circuiting any() would skip the remaining directories once one
    reported a change, leaving their mtime baselines stale and making them
    report a spurious change on the following call.

    Returns:
        True when at least one watched directory changed.
    """
    return any([_check_standards_changed(d) for d in _get_watched_dirs()])


def _get_watched_dirs():
    """Get the list of existing directories to watch for standards changes.

    Returns:
        List of Paths that currently exist on disk. Unresolved or missing
        directories are skipped so the watcher never schedules a dead path.
    """
    dirs = []
    for d in [RULES_DIR, POLICIES_DIR, ARCH_STANDARDS_DIR,
              TEAM_STANDARDS_DIR, TEAM_STANDARDS_ALT]:
        if d is not None and d.exists() and d not in dirs:
            dirs.append(d)
    return dirs


def _invalidate_cache():
    """Invalidate the standards cache and mtime tracking."""
    global _standards_cache, _cache_timestamp, _standards_mtimes
    _standards_cache = {}
    _cache_timestamp = 0
    _standards_mtimes = {}


def _start_file_watcher():
    """Start watching standards directories for changes (if watchdog available)."""
    global _file_watcher_active
    if _file_watcher_active:
        return {"status": "already_running"}

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class StandardsChangeHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.src_path.endswith(".md"):
                    _invalidate_cache()

            def on_created(self, event):
                if event.src_path.endswith(".md"):
                    _invalidate_cache()

            def on_deleted(self, event):
                if event.src_path.endswith(".md"):
                    _invalidate_cache()

        observer = Observer()
        handler = StandardsChangeHandler()

        watched = []
        for watch_dir in _get_watched_dirs():
            observer.schedule(handler, str(watch_dir), recursive=True)
            watched.append(str(watch_dir))

        observer.daemon = True
        observer.start()
        _file_watcher_active = True

        return {"status": "started", "watching": watched}
    except ImportError:
        return {"status": "watchdog_not_installed", "fallback": "TTL-based cache (5 min)"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}


@mcp.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False,
    idempotentHint=True, openWorldHint=False))
@mcp_tool_handler
def reload_standards(
    project_path: Annotated[str, Field(
        description="Filesystem path to the project root to inspect. Defaults to the current working directory.")] = ".",
    start_watcher: Annotated[bool, Field(
        description="Start a background watchdog observer that invalidates the cache when a standards .md file changes. Requires the watchdog package; falls back to TTL-based caching when unavailable.")] = True,
) -> str:
    """Reload standards by invalidating cache and optionally starting file watcher.

    Invalidates the cached standards so next load_standards call fetches fresh data.
    Can also start a background file watcher (requires watchdog) that auto-invalidates
    cache when .md files in policies/ or standards/ directories change.

    Args:
        project_path: Path to project root
        start_watcher: If True, start file watcher for auto-reload
    """
    try:
        # Check if any files actually changed before doing full reload
        dirs_changed = _any_standards_changed()

        # If no changes and cache is fresh, return cached result
        cache_key = str(Path(project_path).resolve())
        if not dirs_changed and cache_key in _standards_cache:
            cached_data, cached_ts = _standards_cache[cache_key]
            age = time.time() - cached_ts
            if age < _STANDARDS_CACHE_TTL:
                return to_json({
                    "success": True,
                    "reloaded": False,
                    "from_cache": True,
                    "standards_loaded": cached_data.get("standards_loaded", 0),
                    "project_type": cached_data.get("project_type", "unknown"),
                    "framework": cached_data.get("framework", "unknown"),
                    "standards_last_loaded_at": cached_data.get("standards_last_loaded_at", ""),
                    "watcher": {},
                    "watched_dirs": [str(d) for d in _get_watched_dirs()],
                })

        # Changes detected or cache stale - do full reload
        _invalidate_cache()

        watcher_status = {}
        if start_watcher:
            watcher_status = _start_file_watcher()

        # Reload standards immediately
        result = json.loads(load_standards(project_path))

        return to_json({
            "success": True,
            "reloaded": True,
            "from_cache": False,
            "standards_loaded": result.get("standards_loaded", 0),
            "project_type": result.get("project_type", "unknown"),
            "framework": result.get("framework", "unknown"),
            "standards_last_loaded_at": result.get("standards_last_loaded_at", ""),
            "watcher": watcher_status,
            "watched_dirs": [str(d) for d in _get_watched_dirs()],
        })
    except Exception as e:
        return to_json({"success": False, "error": str(e)})


if __name__ == "__main__":
    mcp.run(transport="stdio")
