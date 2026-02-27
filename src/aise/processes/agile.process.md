# Agile Iterative Development Process
- process_id: agile_sprint_v1
- name: Iterative Agile Sprint Workflow
- work_type: rapid_iteration
- keywords: agile, sprint, backlog, mvp, feedback, iterative
- summary: An iterative approach focusing on continuous feedback, rapid prototyping, and delivering a Minimum Viable Product (MVP).

## Global Agent Requirements
### product_owner_agent
- focus: user_value_prioritization
### developer_agent
- style: functional_and_modular

## Steps
### sprint_planning: Backlog & Prioritization
- agents: product_owner_agent, master_agent
- description: Breakdown user stories and select items for the current short-term sprint.
#### Responsibilities
##### product_owner_agent
- Define "Definition of Done" (DoD) for each story.
- Prioritize high-value features for the MVP.
##### master_agent
- Allocate tasks based on agent capability and workload.

### sprint_execution: Rapid Prototyping & Coding
- agents: developer_agent, reviewer_agent
- description: Fast-paced development focusing on functional features and immediate code quality.
#### Responsibilities
##### developer_agent
- Implement core logic in small, testable increments.
- Output format: executable_snippets
##### reviewer_agent
- Perform continuous integration checks and quick logic validation.

### sprint_review: Feedback & Demo
- agents: qa_agent, product_owner_agent
- description: Review the increment and collect feedback for the next iteration.
#### Responsibilities
##### qa_agent
- Verify functionality against user stories.
##### product_owner_agent
- Evaluate if the increment meets "User Value" and update the backlog.

### sprint_retrospective: Process Optimization
- agents: master_agent
- description: Analyze the performance of the Multi-Agent system to optimize the next sprint's coordination.
#### Requirements
- include: efficiency_bottleneck_analysis