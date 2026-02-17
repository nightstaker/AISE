# Skill: version_release

## Overview

| Field | Value |
|-------|-------|
| **Name** | `version_release` |
| **Class** | `VersionReleaseSkill` |
| **Module** | `aise.skills.lead.version_release` |
| **Agent** | Project Manager (`project_manager`) |
| **Description** | Coordinate a project version release and record release notes |

## Purpose

Validates that all required delivery artifacts are present, records a versioned release, and produces a report that includes readiness checks, any blockers, and release metadata. If any required artifact is missing the release is marked `blocked`.

## Input

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | `str` | Yes | Semantic version string, e.g. `"1.2.0"` |
| `release_notes` | `str` | No | Human-readable description of what changed |
| `release_type` | `str` | No | `"major"`, `"minor"`, or `"patch"` (default: `"minor"`) |

### Input Validation

- `version` must be present and non-empty.

## Output

**Artifact Type:** `ArtifactType.PROGRESS_REPORT`

```json
{
  "report_type": "version_release",
  "version": "1.0.0",
  "release_type": "major",
  "release_notes": "Initial release",
  "readiness_checks": {
    "requirements": true,
    "architecture_design": true,
    "source_code": true,
    "unit_tests": true
  },
  "blockers": [],
  "is_ready": true,
  "status": "released",
  "project_name": "MyProject"
}
```

When artifacts are missing:

```json
{
  "is_ready": false,
  "status": "blocked",
  "blockers": ["Missing artifact: source_code", "Missing artifact: unit_tests"]
}
```

## Readiness Checks

The following artifact types must exist in the artifact store for a release to proceed:

| Artifact | Enum |
|----------|------|
| Requirements | `REQUIREMENTS` |
| Architecture Design | `ARCHITECTURE_DESIGN` |
| Source Code | `SOURCE_CODE` |
| Unit Tests | `UNIT_TESTS` |

## Integration

### Depends On
- `requirement_analysis` or `requirement_distribution` — produces `REQUIREMENTS`
- `system_design` — produces `ARCHITECTURE_DESIGN`
- `code_generation` — produces `SOURCE_CODE`
- `unit_test_writing` — produces `UNIT_TESTS`
