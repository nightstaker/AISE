"""Architecture Document Generation skill - generates system-architecture.md and status.md."""

from __future__ import annotations

import os
from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class ArchitectureDocumentGenerationSkill(Skill):
    """Generate system-architecture.md and status.md documentation."""

    @property
    def name(self) -> str:
        return "architecture_document_generation"

    @property
    def description(self) -> str:
        return "Generate complete architecture and status documentation in Markdown format"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        project_name = context.project_name or input_data.get("project_name", "Untitled")
        output_dir = input_data.get("output_dir", ".")

        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Gather all required artifacts
        architecture_requirements = store.get_latest(ArtifactType.ARCHITECTURE_REQUIREMENT)
        functional_design = store.get_latest(ArtifactType.FUNCTIONAL_DESIGN)
        status_tracking = store.get_latest(ArtifactType.STATUS_TRACKING)

        if not all([architecture_requirements, functional_design, status_tracking]):
            raise ValueError("Missing required artifacts. Please run the full pipeline first.")

        # Generate system-architecture.md
        arch_file_path = os.path.join(output_dir, "system-architecture.md")
        self._generate_architecture_doc(arch_file_path, project_name, architecture_requirements, functional_design)

        # Generate status.md
        status_file_path = os.path.join(output_dir, "status.md")
        self._generate_status_doc(status_file_path, status_tracking)

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "generated_files": [arch_file_path, status_file_path],
                "project_name": project_name,
                "output_dir": output_dir,
            },
            producer="architect",
            metadata={"project_name": project_name},
        )

    def _generate_architecture_doc(
        self, file_path: str, project_name: str, ar_artifact: Artifact, fn_artifact: Artifact
    ) -> None:
        """Generate system-architecture.md file."""
        ars = ar_artifact.content.get("architecture_requirements", [])
        fns = fn_artifact.content.get("functions", [])
        arch_layers = fn_artifact.content.get("architecture_layers", {})
        ar_matrix = ar_artifact.content.get("traceability_matrix", {})
        fn_matrix = fn_artifact.content.get("traceability_matrix", {})

        with open(file_path, "w", encoding="utf-8") as f:
            # Header
            f.write("# 系统架构设计文档\n\n")
            f.write(f"**项目名称**: {project_name}\n\n")

            # Section 1: Project Overview
            f.write("## 1. 项目概述\n\n")
            f.write(f"- **架构需求数量**: {len(ars)}\n")
            f.write(f"- **功能组件数量**: {len(fns)}\n")
            f.write("- **架构风格**: 分层架构 (API → Business → Data → Integration)\n\n")

            # Section 2: Architecture Requirements
            f.write("## 2. 架构需求 (AR)\n\n")
            ar_by_layer = {"api": [], "business": [], "data": [], "integration": []}
            for ar in ars:
                layer = ar.get("target_layer", "business")
                ar_by_layer[layer].append(ar)

            layer_configs = [
                ("api", "API层"),
                ("business", "业务层"),
                ("data", "数据层"),
                ("integration", "集成层"),
            ]
            for layer_name, layer_title in layer_configs:
                layer_ars = ar_by_layer.get(layer_name, [])
                if layer_ars:
                    layer_index = ["api", "business", "data", "integration"].index(layer_name) + 1
                    f.write(f"### 2.{layer_index} {layer_title}架构需求\n\n")
                    for ar in layer_ars:
                        ar_id = ar["id"]
                        f.write(f"**{ar_id}**: {ar['description']}\n")
                        f.write(f"- **来源SR**: {ar['source_sr']}\n")
                        f.write(f"- **复杂度**: {ar.get('estimated_complexity', 'medium')}\n")
                        fn_ids = fn_matrix.get(ar_id, [])
                        if fn_ids:
                            f.write(f"- **对应功能**: {', '.join(fn_ids)}\n")
                        f.write("\n")

            # Section 3: Functional Design
            f.write("## 3. 功能设计 (FN)\n\n")

            # Services
            services = [fn for fn in fns if fn["type"] == "service"]
            if services:
                f.write("### 3.1 服务列表\n\n")
                f.write("| FN ID | 名称 | 层级 | 来源AR | 文件路径 |\n")
                f.write("|-------|------|------|--------|----------|\n")
                for svc in services:
                    ars_str = ", ".join(svc.get("source_ars", []))
                    f.write(f"| {svc['id']} | {svc['name']} | {svc['layer']} | {ars_str} | {svc['file_path']} |\n")
                f.write("\n")

            # Components
            components = [fn for fn in fns if fn["type"] == "component"]
            if components:
                f.write("### 3.2 组件列表\n\n")
                f.write("| FN ID | 名称 | 层级 | 来源AR | 文件路径 |\n")
                f.write("|-------|------|------|--------|----------|\n")
                for comp in components:
                    ars_str = ", ".join(comp.get("source_ars", []))
                    f.write(f"| {comp['id']} | {comp['name']} | {comp['layer']} | {ars_str} | {comp['file_path']} |\n")
                f.write("\n")

            # Section 4: Layer Structure
            f.write("## 4. 层次化架构\n\n")
            layer_keys = ["api_layer", "business_layer", "data_layer", "integration_layer"]
            for layer_key in layer_keys:
                if layer_key in arch_layers:
                    layer_index = layer_keys.index(layer_key) + 1
                    layer_title = layer_key.replace("_", " ").title()
                    f.write(f"### 4.{layer_index} {layer_title}\n\n")
                    f.write("```\n")
                    f.write(f"{layer_key}/\n")

                    # Group by subsystem
                    subsystems = {}
                    for fn in fns:
                        if fn["layer"] == layer_key.replace("_layer", ""):
                            subsystem = fn.get("subsystem", "unknown")
                            if subsystem not in subsystems:
                                subsystems[subsystem] = []
                            subsystems[subsystem].append(fn)

                    for subsystem, subsystem_fns in subsystems.items():
                        f.write(f"  ├── {subsystem}/\n")
                        for fn in subsystem_fns:
                            fn_file = fn["file_path"].split("/")[-1]
                            f.write(f"  │   ├── {fn_file} ({fn['id']})\n")

                    f.write("```\n\n")

            # Section 5: API Interfaces
            f.write("## 5. API接口定义\n\n")
            api_services = [fn for fn in fns if fn["type"] == "service" and fn["layer"] == "api"]
            for svc in api_services:
                interfaces = svc.get("interfaces", [])
                if interfaces:
                    f.write(f"### 5.{api_services.index(svc) + 1} {svc['name']}\n\n")
                    f.write(f"**FN ID**: {svc['id']}\n\n")
                    for intf in interfaces:
                        f.write(f"- **{intf['method']} {intf['path']}**\n")
                        f.write(f"  - 描述: {intf['description']}\n\n")

            # Section 6: Traceability Matrix
            f.write("## 6. 追溯矩阵\n\n")
            f.write("### 6.1 SR → AR → FN 映射\n\n")
            f.write("| SR ID | AR IDs | FN IDs |\n")
            f.write("|-------|--------|--------|\n")

            # Build complete traceability
            for sr_id, ar_ids in ar_matrix.items():
                fn_ids_set = set()
                for ar_id in ar_ids:
                    fn_ids_set.update(fn_matrix.get(ar_id, []))
                ar_ids_str = ", ".join(ar_ids)
                fn_ids_str = ", ".join(sorted(fn_ids_set))
                f.write(f"| {sr_id} | {ar_ids_str} | {fn_ids_str} |\n")
            f.write("\n")

    def _generate_status_doc(self, file_path: str, status_artifact: Artifact) -> None:
        """Generate status.md file."""
        project_name = status_artifact.content.get("project_name", "Untitled")
        last_updated = status_artifact.content.get("last_updated", "")
        elements = status_artifact.content.get("elements", {})
        summary = status_artifact.content.get("summary", {})

        with open(file_path, "w", encoding="utf-8") as f:
            # Header
            f.write("# 项目状态跟踪\n\n")
            f.write(f"**项目名称**: {project_name}\n\n")
            f.write(f"**最后更新**: {last_updated}\n\n")
            f.write(f"**整体完成度**: {summary.get('overall_completion', 0):.1f}%\n\n")

            # Section 1: Overview
            f.write("## 1. 状态概览\n\n")
            f.write("| 类型 | 总数 |\n")
            f.write("|------|------|\n")
            f.write(f"| 系统功能(SF) | {summary.get('total_sfs', 0)} |\n")
            f.write(f"| 系统需求(SR) | {summary.get('total_srs', 0)} |\n")
            f.write(f"| 架构需求(AR) | {summary.get('total_ars', 0)} |\n")
            f.write(f"| 功能组件(FN) | {summary.get('total_fns', 0)} |\n\n")

            # Section 2: SF-SR-AR-FN Mapping
            f.write("## 2. SF-SR-AR-FN 映射关系\n\n")

            # Get SFs (top-level elements)
            sfs = {eid: elem for eid, elem in elements.items() if elem["type"] == "system_feature"}

            for sf_id, sf in sorted(sfs.items()):
                status_icon = self._get_status_icon(sf["status"])
                status_str = f"[{sf['status']} {sf['completion_percentage']:.0f}%] {status_icon}"
                f.write(f"### {sf_id}: {sf['description']} {status_str}\n\n")

                # Get children SRs
                for sr_id in sf.get("children", []):
                    if sr_id in elements:
                        sr = elements[sr_id]
                        status_icon = self._get_status_icon(sr["status"])
                        status_str = f"[{sr['status']} {sr['completion_percentage']:.0f}%] {status_icon}"
                        f.write(f"- **{sr_id}**: {sr['description']} {status_str}\n")

                        # Get children ARs
                        for ar_id in sr.get("children", []):
                            if ar_id in elements:
                                ar = elements[ar_id]
                                status_icon = self._get_status_icon(ar["status"])
                                status_str = f"[{ar['status']} {ar['completion_percentage']:.0f}%]"
                                f.write(f"  - **{ar_id}**: {ar['description']} {status_str} {status_icon}\n")

                                # Get children FNs
                                for fn_id in ar.get("children", []):
                                    if fn_id in elements:
                                        fn = elements[fn_id]
                                        status_icon = self._get_status_icon(fn["status"])
                                        desc_short = fn["description"][:60] + "..."
                                        status_str = f"[{fn['status']} {fn['completion_percentage']:.0f}%]"
                                        f.write(f"    - **{fn_id}**: {desc_short} {status_str} {status_icon}\n")

                                        # Implementation details
                                        impl = fn.get("implementation_status", {})
                                        f.write(f"      - {'✓' if impl.get('code_generated') else '✗'} 代码已生成\n")
                                        f.write(f"      - {'✓' if impl.get('tests_written') else '✗'} 测试已编写\n")
                                        f.write(f"      - {'✓' if impl.get('tests_passed') else '✗'} 测试已通过\n")
                                        f.write(f"      - {'✓' if impl.get('reviewed') else '✗'} 代码已审查\n")
                f.write("\n")

            # Section 3: Detailed Status Table
            f.write("## 3. 详细状态表\n\n")
            f.write("| 元素ID | 类型 | 描述 | 状态 | 完成度 | 父元素 |\n")
            f.write("|--------|------|------|------|--------|--------|\n")

            for elem_id in sorted(elements.keys()):
                elem = elements[elem_id]
                desc_short = elem["description"][:40] + "..." if len(elem["description"]) > 40 else elem["description"]
                parent = elem.get("parent", "-")
                completion = f"{elem['completion_percentage']:.0f}%"
                f.write(f"| {elem_id} | {elem['type']} | {desc_short} | {elem['status']} | {completion} | {parent} |\n")

    def _get_status_icon(self, status: str) -> str:
        """Get emoji icon for status."""
        icons = {"未开始": "⏸️", "进行中": "🔄", "已完成": "✅"}
        return icons.get(status, "❓")
