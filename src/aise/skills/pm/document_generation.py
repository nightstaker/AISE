"""Document generation skill - generates markdown documents from artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class DocumentGenerationSkill(Skill):
    """Generate markdown documentation from system design and requirements artifacts."""

    @property
    def name(self) -> str:
        return "document_generation"

    @property
    def description(self) -> str:
        return "Generate system-design.md and System-Requirements.md from artifacts"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        output_dir = input_data.get("output_dir", ".")

        results = {
            "generated_files": [],
            "errors": [],
        }

        # Generate system-design.md
        system_design = store.get_latest(ArtifactType.SYSTEM_DESIGN)
        if system_design:
            try:
                design_doc = self._generate_system_design_md(system_design.content)
                design_path = Path(output_dir) / "system-design.md"
                design_path.write_text(design_doc, encoding="utf-8")
                results["generated_files"].append(str(design_path))
            except Exception as e:
                results["errors"].append(f"Failed to generate system-design.md: {e}")
        else:
            results["errors"].append("No SYSTEM_DESIGN artifact found")

        # Generate System-Requirements.md
        system_requirements = store.get_latest(ArtifactType.SYSTEM_REQUIREMENTS)
        if system_requirements:
            try:
                req_doc = self._generate_system_requirements_md(system_requirements.content)
                req_path = Path(output_dir) / "System-Requirements.md"
                req_path.write_text(req_doc, encoding="utf-8")
                results["generated_files"].append(str(req_path))
            except Exception as e:
                results["errors"].append(f"Failed to generate System-Requirements.md: {e}")
        else:
            results["errors"].append("No SYSTEM_REQUIREMENTS artifact found")

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content=results,
            producer="product_manager",
            metadata={"output_dir": output_dir},
        )

    def _generate_system_design_md(self, content: dict[str, Any]) -> str:
        """Generate system-design.md content."""
        project_name = content.get("project_name", "Untitled Project")
        overview = content.get("overview", "")
        external_features = content.get("external_features", [])
        internal_features = content.get("internal_dfx_features", [])

        md = f"""# System Design Document

## Project: {project_name}

## 1. Overview

{overview}

## 2. External System Features

This section describes all user-facing and external system features.

"""

        # Group external features by category
        ext_by_category = {}
        for feature in external_features:
            category = feature.get("category", "Uncategorized")
            if category not in ext_by_category:
                ext_by_category[category] = []
            ext_by_category[category].append(feature)

        for category, features in sorted(ext_by_category.items()):
            md += f"### 2.{list(ext_by_category.keys()).index(category) + 1} {category}\n\n"
            for feature in features:
                md += f"**{feature['id']}**: {feature['description']}\n\n"

        md += """## 3. Internal DFX System Features

This section describes all internal Design for Excellence (DFX) features, including
performance, security, scalability, reliability, and maintainability characteristics.

"""

        # Group internal features by category
        int_by_category = {}
        for feature in internal_features:
            category = feature.get("category", "Uncategorized")
            if category not in int_by_category:
                int_by_category[category] = []
            int_by_category[category].append(feature)

        for category, features in sorted(int_by_category.items()):
            md += f"### 3.{list(int_by_category.keys()).index(category) + 1} {category}\n\n"
            for feature in features:
                md += f"**{feature['id']}**: {feature['description']}\n\n"

        md += """## 4. Feature Summary

| SF ID | Description | Type | Category |
|-------|-------------|------|----------|
"""

        all_features = content.get("all_features", [])
        for feature in all_features:
            sf_id = feature["id"]
            desc = feature["description"][:80] + ("..." if len(feature["description"]) > 80 else "")
            feature_type = "External" if feature["type"] == "external" else "Internal DFX"
            category = feature.get("category", "N/A")
            md += f"| {sf_id} | {desc} | {feature_type} | {category} |\n"

        return md

    def _generate_system_requirements_md(self, content: dict[str, Any]) -> str:
        """Generate System-Requirements.md content."""
        project_name = content.get("project_name", "Untitled Project")
        overview = content.get("overview", "")
        requirements = content.get("requirements", [])
        coverage = content.get("coverage_summary", {})
        traceability = content.get("traceability_matrix", {})

        md = f"""# System Requirements Document

## Project: {project_name}

## 1. Overview

{overview}

## 2. Requirements Coverage

- **Total System Features (SF)**: {coverage.get("total_sfs", 0)}
- **Covered System Features**: {coverage.get("covered_sfs", 0)}
- **Coverage Percentage**: {coverage.get("coverage_percentage", 0):.1f}%

"""

        if coverage.get("uncovered_sfs"):
            md += "### Uncovered System Features\n\n"
            md += "The following system features do not have associated requirements:\n\n"
            for sf_id in coverage["uncovered_sfs"]:
                md += f"- {sf_id}\n"
            md += "\n"

        md += """## 3. System Requirements

This section lists all system requirements (SR) with their source system features (SF).

"""

        # Group requirements by type
        functional_reqs = [r for r in requirements if r.get("type") == "functional"]
        non_functional_reqs = [r for r in requirements if r.get("type") == "non_functional"]

        if functional_reqs:
            md += "### 3.1 Functional Requirements\n\n"
            md += "| SR ID | Description | Source SF | Priority | Verification |\n"
            md += "|-------|-------------|-----------|----------|-------------|\n"
            for req in functional_reqs:
                sr_id = req["id"]
                desc = req["description"][:80] + ("..." if len(req["description"]) > 80 else "")
                sources = ", ".join(req.get("source_sfs", []))
                priority = req.get("priority", "N/A")
                verification = req.get("verification_method", "N/A")
                md += f"| {sr_id} | {desc} | {sources} | {priority} | {verification} |\n"
            md += "\n"

        if non_functional_reqs:
            md += "### 3.2 Non-Functional Requirements\n\n"
            md += "| SR ID | Description | Source SF | Priority | Verification |\n"
            md += "|-------|-------------|-----------|----------|-------------|\n"
            for req in non_functional_reqs:
                sr_id = req["id"]
                desc = req["description"][:80] + ("..." if len(req["description"]) > 80 else "")
                sources = ", ".join(req.get("source_sfs", []))
                priority = req.get("priority", "N/A")
                verification = req.get("verification_method", "N/A")
                md += f"| {sr_id} | {desc} | {sources} | {priority} | {verification} |\n"
            md += "\n"

        md += """## 4. Detailed Requirements

"""

        # Group requirements by category for detailed view
        reqs_by_category = {}
        for req in requirements:
            category = req.get("category", "Uncategorized")
            if category not in reqs_by_category:
                reqs_by_category[category] = []
            reqs_by_category[category].append(req)

        for category, reqs in sorted(reqs_by_category.items()):
            md += f"### 4.{list(reqs_by_category.keys()).index(category) + 1} {category}\n\n"
            for req in reqs:
                md += f"**{req['id']}**: {req['description']}\n\n"
                md += f"- **Source System Features**: {', '.join(req.get('source_sfs', []))}\n"
                md += f"- **Type**: {req.get('type', 'N/A')}\n"
                md += f"- **Priority**: {req.get('priority', 'N/A')}\n"
                md += f"- **Verification Method**: {req.get('verification_method', 'N/A')}\n\n"

        md += """## 5. Traceability Matrix

This matrix shows the mapping from System Features (SF) to System Requirements (SR).

| SF ID | Associated SR IDs |
|-------|-------------------|
"""

        for sf_id, sr_ids in sorted(traceability.items()):
            sr_list = ", ".join(sr_ids) if sr_ids else "None"
            md += f"| {sf_id} | {sr_list} |\n"

        return md
