# Skill: deep_product_workflow

| Field | Value |
|---|---|
| Name | `deep_product_workflow` |
| Class | `DeepProductWorkflowSkill` |
| Module | `aise.skills.deep_product_workflow.scripts.deep_product_workflow` |
| Agent | Product Manager (`product_manager`) |
| Description | Run paired Product Designer / Product Reviewer deep workflow and generate versioned docs |

This skill executes the requirements phase as a deep paired workflow:

1. Product Designer expands raw requirements with user memory.
2. Product Designer + Product Reviewer iterate on `system-design.md` for at least 2 rounds.
3. Product Designer + Product Reviewer iterate on `system-requirements.md` for at least 2 rounds.

Outputs are written to project `docs/` and revision history is preserved in both files.
