# Waterfall Software Development Process
- process_id: waterfall_standard_v1
- name: Sequential Waterfall Lifecycle
- work_type: structured_development
- keywords: waterfall, sequential, design-first, documentation, milestone
- summary: A linear and sequential approach to software development where each phase must be completed before the next begins.

## Global Agent Requirements
### architect_agent
- output_format: markdown
- detail_level: high_technical_spec

## Steps
### phase_1_requirement: Requirement Specification
#### step_raw_requirement: Raw Requirement Expansion
- agents: product_designer
- description: Refer to user's memory and related search result from internet, expand the requirement description.
#### step_sys_requirement: Requirement Analysis
- agents: product_designer, product_reviewer
- description: Analysis the expanded requirement and generate full system requirement specification, each system requirement(SR) is a verifiable usecase. The user can test the requirement with treating the system as a black box.

### phase_2_design: Architecture Design
#### step_architecture_design
- agents: architect, architecture_reviewer
- description: Transforming requirements into a complete technical blueprint including ERD, API specs, and system topology.
#### step_subsystem_design
- agents: subsystem_expert, subsystem_reviewer
- description: multiple subsystem expert and reviewer work parallelly, each expert and reviewer work for a subsystem
- Output: 'subsystem-[subsystem-name]-design.md'

### phase_3_implementation: Development
- agents: coder, committer
- description: Full-scale implementation based strictly on the frozen design documents.

### phase_4_verification: Integration & Testing
- agents: qa
- description: Formal testing phase to ensure the entire system meets the initial SRS.