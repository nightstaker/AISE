"""Functional Design skill - generates FN (components/services) from AR."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class FunctionalDesignSkill(Skill):
    """Generate Function/Component/Service definitions from Architecture Requirements."""

    @property
    def name(self) -> str:
        return "functional_design"

    @property
    def description(self) -> str:
        return "Generate FN (components/services) from Architecture Requirements with layer organization"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        project_name = context.project_name or input_data.get("project_name", "Untitled")

        # Get ARCHITECTURE_REQUIREMENT artifact
        ar_artifact = store.get_latest(ArtifactType.ARCHITECTURE_REQUIREMENT)
        if not ar_artifact:
            raise ValueError(
                "No ARCHITECTURE_REQUIREMENT artifact found. Please run architecture_requirement_analysis first."
            )

        ars = ar_artifact.content["architecture_requirements"]

        # Group ARs by layer
        layers = self._group_by_layer(ars)

        # Generate FN for each AR
        fn_counter_service = 1
        fn_counter_component = 1
        all_functions = []

        for layer_name, layer_ars in layers.items():
            for ar in layer_ars:
                fn = self._create_function_from_ar(ar, fn_counter_service, fn_counter_component, project_name)
                all_functions.append(fn)

                if fn["type"] == "service":
                    fn_counter_service += 1
                else:
                    fn_counter_component += 1

        # Build layer structure
        architecture_layers = self._build_layer_structure(all_functions)

        # Build traceability matrix
        traceability_matrix = self._build_fn_ar_matrix(all_functions)

        num_components = fn_counter_component - 1
        num_services = fn_counter_service - 1
        functional_design_doc = {
            "project_name": project_name,
            "overview": f"Functional design with {num_components} components and {num_services} services",
            "architecture_layers": architecture_layers,
            "functions": all_functions,
            "traceability_matrix": traceability_matrix,
        }

        return Artifact(
            artifact_type=ArtifactType.FUNCTIONAL_DESIGN,
            content=functional_design_doc,
            producer="architect",
            metadata={"project_name": project_name},
        )

    def _group_by_layer(self, ars: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Group ARs by target layer."""
        layers = {"api": [], "business": [], "data": [], "integration": []}

        for ar in ars:
            target_layer = ar.get("target_layer", "business")
            if target_layer in layers:
                layers[target_layer].append(ar)
            else:
                layers["business"].append(ar)  # Default to business

        return layers

    def _create_function_from_ar(
        self, ar: dict[str, Any], service_counter: int, component_counter: int, project_name: str
    ) -> dict[str, Any]:
        """Create a function definition from an AR."""
        ar_id = ar["id"]
        ar_desc = ar["description"]
        target_layer = ar["target_layer"]
        component_type = ar["component_type"]

        # Generate FN ID
        if component_type == "service":
            fn_id = f"FN-SERVICE-{service_counter:03d}"
        else:
            fn_id = f"FN-COM-{component_counter:03d}"

        # Generate function name from description
        fn_name = self._generate_function_name(ar_desc, component_type)

        # Determine subsystem (service domain) based on AR description
        subsystem = self._determine_subsystem(ar_desc, target_layer)

        # Generate file path
        file_path = self._generate_file_path(target_layer, subsystem, fn_name)

        # Generate interfaces for services
        interfaces = []
        if component_type == "service":
            interfaces = self._generate_interfaces_for_service(ar, fn_name)

        fn = {
            "id": fn_id,
            "type": component_type,
            "name": fn_name,
            "description": ar_desc,
            "layer": target_layer,
            "subsystem": subsystem,
            "source_ars": [ar_id],
            "interfaces": interfaces,
            "dependencies": [],  # Can be enhanced later
            "file_path": file_path,
            "estimated_complexity": ar.get("estimated_complexity", "medium"),
        }

        return fn

    def _generate_function_name(self, description: str, component_type: str) -> str:
        """Generate PascalCase function name from description."""
        # Extract key words from description
        # Remove common prefixes like "API层:", "业务层:", etc.
        clean_desc = description
        for prefix in ["API层:", "业务层:", "数据层:", "集成层:"]:
            clean_desc = clean_desc.replace(prefix, "").strip()

        # Take first few words
        words = clean_desc.split()[:3]

        # Convert to PascalCase
        pascal_words = []
        for word in words:
            # Remove special characters
            clean_word = "".join(c for c in word if c.isalnum() or c.isspace())
            if clean_word:
                pascal_words.append(clean_word.capitalize())

        name = "".join(pascal_words)

        # Add suffix for services
        if component_type == "service":
            if not name.endswith("Service"):
                name += "Service"

        # Ensure valid name
        if not name or not name[0].isalpha():
            name = "GenericService" if component_type == "service" else "GenericComponent"

        return name

    def _determine_subsystem(self, description: str, layer: str) -> str:
        """Determine subsystem (service domain) from AR description."""
        desc_lower = description.lower()

        # Common subsystem keywords
        if any(keyword in desc_lower for keyword in ["auth", "login", "登录", "认证"]):
            return "auth_service"
        elif any(keyword in desc_lower for keyword in ["user", "用户"]):
            return "user_management"
        elif any(keyword in desc_lower for keyword in ["product", "产品"]):
            return "product_service"
        elif any(keyword in desc_lower for keyword in ["order", "订单"]):
            return "order_management"
        elif any(keyword in desc_lower for keyword in ["payment", "支付"]):
            return "payment_service"
        elif any(keyword in desc_lower for keyword in ["database", "数据库", "repository"]):
            return "repositories"
        elif any(keyword in desc_lower for keyword in ["cache", "缓存"]):
            return "cache_service"

        # Default subsystems by layer
        layer_defaults = {
            "api": "api_core",
            "business": "business_core",
            "data": "data_core",
            "integration": "external_services",
        }

        return layer_defaults.get(layer, "common")

    def _generate_file_path(self, layer: str, subsystem: str, function_name: str) -> str:
        """Generate file path following layer/subsystem/component structure."""
        # Convert PascalCase to snake_case for file name
        import re

        snake_case_name = re.sub(r"(?<!^)(?=[A-Z])", "_", function_name).lower()

        return f"src/{layer}_layer/{subsystem}/{snake_case_name}.py"

    def _generate_interfaces_for_service(self, ar: dict[str, Any], service_name: str) -> list[dict[str, Any]]:
        """Generate API interface definitions for a service."""
        interfaces = []

        # Determine HTTP method and path based on AR description
        desc_lower = ar["description"].lower()

        # Extract resource name from service name (remove "Service" suffix)
        resource = service_name.replace("Service", "").lower()

        # Generate basic CRUD interfaces for services
        if ar.get("target_layer") == "api":
            # Create
            if any(keyword in desc_lower for keyword in ["create", "add", "新增", "创建"]):
                interfaces.append(
                    {"method": "POST", "path": f"/api/v1/{resource}", "description": f"Create {resource}"}
                )

            # Read
            if any(keyword in desc_lower for keyword in ["get", "read", "list", "查询", "获取"]):
                interfaces.append({"method": "GET", "path": f"/api/v1/{resource}", "description": f"List {resource}"})
                interfaces.append(
                    {"method": "GET", "path": f"/api/v1/{resource}/{{id}}", "description": f"Get {resource} by ID"}
                )

            # Update
            if any(keyword in desc_lower for keyword in ["update", "modify", "更新", "修改"]):
                interfaces.append(
                    {"method": "PUT", "path": f"/api/v1/{resource}/{{id}}", "description": f"Update {resource}"}
                )

            # Delete
            if any(keyword in desc_lower for keyword in ["delete", "remove", "删除"]):
                interfaces.append(
                    {"method": "DELETE", "path": f"/api/v1/{resource}/{{id}}", "description": f"Delete {resource}"}
                )

            # If no specific operation detected, add basic GET
            if not interfaces:
                interfaces.append(
                    {
                        "method": "POST",
                        "path": f"/api/v1/{resource}/execute",
                        "description": f"Execute {resource} operation",
                    }
                )

        return interfaces

    def _build_layer_structure(self, functions: list[dict[str, Any]]) -> dict[str, Any]:
        """Build hierarchical layer structure."""
        layers = {
            "api_layer": {"services": [], "components": []},
            "business_layer": {"services": [], "components": []},
            "data_layer": {"components": []},
            "integration_layer": {"components": []},
        }

        for fn in functions:
            layer_key = f"{fn['layer']}_layer"
            if layer_key in layers:
                fn_type = fn["type"]
                if fn_type == "service":
                    layers[layer_key]["services"].append(fn["id"])
                else:
                    layers[layer_key]["components"].append(fn["id"])

        return layers

    def _build_fn_ar_matrix(self, functions: list[dict[str, Any]]) -> dict[str, list[str]]:
        """Build traceability matrix mapping AR IDs to FN IDs."""
        matrix = {}

        for fn in functions:
            for ar_id in fn["source_ars"]:
                if ar_id not in matrix:
                    matrix[ar_id] = []
                matrix[ar_id].append(fn["id"])

        return matrix
