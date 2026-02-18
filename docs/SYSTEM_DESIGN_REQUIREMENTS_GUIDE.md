# System Design & Requirements Analysis Guide

## Overview

The Product Manager agent now includes enhanced capabilities for systematic system feature and requirement analysis. This guide explains how to use the new skills to generate structured system design and requirements documentation.

## New Skills

### 1. System Feature Analysis (`system_feature_analysis`)

**Purpose**: Analyze raw requirements and produce a structured list of System Features (SF).

**Input**:
- `raw_requirements`: String or list of raw requirement descriptions from the requester
- `project_name`: (Optional) Name of the project

**Output**: Artifact of type `SYSTEM_DESIGN` containing:
- External system features (user-facing)
- Internal DFX (Design for Excellence) features (performance, security, scalability, etc.)
- All features with SF-XXX format IDs (3-digit numbering)
- Features categorized by type and functional area

**Example**:
```python
artifact = pm_agent.execute_skill(
    "system_feature_analysis",
    {
        "raw_requirements": """User login
        Performance must be under 200ms
        System must be secure""",
        "project_name": "My Project"
    }
)
```

### 2. System Requirement Analysis (`system_requirement_analysis`)

**Purpose**: Generate detailed System Requirements (SR) from System Features (SF) with full traceability.

**Input**:
- Reads from artifact store: `SYSTEM_DESIGN` artifact
- `project_name`: (Optional) Name of the project

**Output**: Artifact of type `SYSTEM_REQUIREMENTS` containing:
- System requirements with SR-XXXX format IDs (4-digit numbering)
- Each SR linked to its source SF(s)
- Coverage analysis ensuring all SFs are covered
- Traceability matrix (SF → SR mapping)
- Verification methods for each requirement

**Example**:
```python
# Must run system_feature_analysis first
artifact = pm_agent.execute_skill("system_requirement_analysis", {})
```

### 3. Document Generation (`document_generation`)

**Purpose**: Generate markdown documentation files from system design and requirements artifacts.

**Input**:
- `output_dir`: Directory path where documents will be generated (default: current directory)
- Reads from artifact store: `SYSTEM_DESIGN` and `SYSTEM_REQUIREMENTS` artifacts

**Output**: Two markdown files:
- `system-design.md`: System features organized by type and category
- `system-requirements.md`: System requirements with coverage analysis and traceability

**Example**:
```python
artifact = pm_agent.execute_skill(
    "document_generation",
    {"output_dir": "./docs"}
)
```

## Workflow

The typical workflow for using these skills is:

```
1. System Feature Analysis
   ↓
2. System Requirement Analysis
   ↓
3. Document Generation
```

### Complete Example

```python
from aise.agents.product_manager import ProductManagerAgent
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus

# Initialize
bus = MessageBus()
store = ArtifactStore()
pm_agent = ProductManagerAgent(bus, store)

# Step 1: Analyze system features
sf_artifact = pm_agent.execute_skill(
    "system_feature_analysis",
    {
        "raw_requirements": """
        User authentication and login
        Product catalog browsing
        Performance must be under 200ms
        System must support 10,000 concurrent users
        Security: Data encryption required
        """,
        "project_name": "E-Commerce Platform"
    }
)

# Step 2: Generate system requirements
sr_artifact = pm_agent.execute_skill("system_requirement_analysis", {})

# Step 3: Generate documentation
doc_artifact = pm_agent.execute_skill(
    "document_generation",
    {"output_dir": "."}
)

print(f"Generated files: {doc_artifact.content['generated_files']}")
```

## Output Format

### System Features (SF)

**ID Format**: `SF-XXX` (3-digit numbering, zero-padded)

**Examples**:
- SF-001-User Authentication
- SF-002-Product Catalog
- SF-015-Performance Optimization

**Categories**:
- **External Features**: User Management, Data Management, API/Interface, User Interface, Functional
- **Internal DFX Features**: Performance, Security, Scalability, Reliability, Maintainability, Testability

### System Requirements (SR)

**ID Format**: `SR-XXXX` (4-digit numbering, zero-padded)

**Examples**:
- SR-0001: User authentication with email/password
- SR-0002: Input validation for user credentials
- SR-0015: API response time < 200ms

**Properties**:
- `id`: Unique SR identifier
- `description`: Detailed requirement description
- `source_sfs`: List of SF IDs that this SR derives from
- `type`: `functional` or `non_functional`
- `category`: Feature category
- `priority`: `high`, `medium`, or `low`
- `verification_method`: `unit_test`, `integration_test`, `performance_test`, `security_test`

## Coverage & Traceability

The system ensures:

1. **100% Coverage**: All System Features (SF) must have at least one System Requirement (SR)
2. **Traceability**: Each SR explicitly references its source SF(s)
3. **Verification**: Each SR includes a verification method
4. **Priority Assignment**: Automatic priority assignment based on feature type and category

The coverage report includes:
- Total number of SFs
- Number of covered SFs
- Coverage percentage
- List of uncovered SFs (if any)

The traceability matrix shows:
```
| SF ID  | Associated SR IDs |
|--------|-------------------|
| SF-001 | SR-0001, SR-0002  |
| SF-002 | SR-0003, SR-0004  |
```

## Generated Documents

### system-design.md Structure

1. Project Overview
2. External System Features (grouped by category)
3. Internal DFX System Features (grouped by category)
4. Feature Summary Table

### system-requirements.md Structure

1. Project Overview
2. Requirements Coverage
3. System Requirements (separated into Functional and Non-Functional)
4. Detailed Requirements (grouped by category)
5. Traceability Matrix

## Best Practices

1. **Clear Raw Requirements**: Provide clear, concise requirement descriptions in the raw input
2. **DFX Keywords**: Use keywords like "performance", "security", "scalability" to ensure proper categorization
3. **Verify Coverage**: Always check the coverage percentage to ensure all features are addressed
4. **Review Traceability**: Use the traceability matrix to verify SF→SR mapping
5. **Document Early**: Generate documents early in the design phase for stakeholder review

## Integration with Existing Skills

The new skills integrate seamlessly with existing Product Manager skills:

- `requirement_analysis` → Traditional FR/NFR analysis
- `system_feature_analysis` → **NEW**: SF-based system design
- `system_requirement_analysis` → **NEW**: SR-based requirement specification
- `user_story_writing` → User stories for development
- `product_design` → PRD generation
- `document_generation` → **NEW**: Markdown documentation

You can use both workflows in parallel or choose the approach that best fits your project needs.
