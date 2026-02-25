# Code Implementation Standard Process
- process_id: code_implementation_standard
- name: Feature Implementation Workflow
- work_type: code_implementation
- keywords: code, implementation, develop, test, fix, coding, 开发, 实现
- summary: Standard process for implementing a feature with analysis, coding, testing, and review.

## Global Agent Requirements
### developer_worker
- output_format: code_and_notes
- test_requirement: add_or_update_tests
### qa_worker
- verify: regression_risk

## Steps
### req_analysis: Implementation Task Analysis
- agents: analysis_worker, developer_worker
- description: Clarify task boundaries, affected modules, and validation strategy.
#### Responsibilities
##### developer_worker
- Identify impacted code paths and expected output.
#### Requirements
##### developer_worker
- include: impacted_files_and_test_plan

### coding: Implement and Unit Test
- agents: developer_worker
- description: Implement code changes and validate with tests.
#### Responsibilities
##### developer_worker
- Write code and unit tests.
- Collect execution evidence.
#### Requirements
##### developer_worker
- test_requirement: tests_must_pass
- include: execution_log_summary

### review_and_fix: Review and Iterate
- agents: qa_worker, developer_worker
- description: Review behavior, identify defects, and apply fixes if needed.
#### Responsibilities
##### qa_worker
- Verify correctness and coverage.
##### developer_worker
- Apply fixes based on review feedback.

