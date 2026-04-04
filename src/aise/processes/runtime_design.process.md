# Runtime Design Standard Process
- process_id: runtime_design_standard
- name: Agent Runtime Design Workflow
- work_type: runtime_design
- keywords: runtime, design, architecture, agent runtime, 设计, 架构
- summary: Standard process for designing an Agent Runtime with process compliance, architecture, execution model, and documentation output.

## Global Agent Requirements
### architecture_worker
- output_format: markdown
- traceability: include requirement-to-design mapping
### documentation_worker
- output_format: markdown
- style: concise_and_structured

## Steps
### req_analysis: Requirement Analysis
- agents: analysis_worker, master_agent
- description: Extract scope, constraints, assumptions, and acceptance criteria.
#### Responsibilities
##### analysis_worker
- Parse user intent and explicit constraints.
- Identify missing assumptions and risks.
##### master_agent
- Select proper process and draft plan skeleton.
#### Requirements
##### analysis_worker
- output_format: json_summary
- include: constraints_and_risks

### architecture_design: Core Runtime Architecture Design
- agents: architecture_worker, master_agent
- description: Define core components, data models, scheduling, memory, and recovery.
#### Responsibilities
##### architecture_worker
- Produce architecture modules and interfaces.
- Define task plan and execution data models.
##### master_agent
- Enforce process compliance and step dependencies.
#### Requirements
##### architecture_worker
- output_format: markdown
- include: task_plan_json_model

### document_finalize: Documentation Finalization
- agents: documentation_worker
- description: Consolidate results into a structured deliverable.
#### Responsibilities
##### documentation_worker
- Produce final markdown document and implementation notes.
#### Requirements
##### documentation_worker
- include: sectioned_output

