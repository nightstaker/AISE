---
name: mermaid
description: Validate every Mermaid code fence in a document immediately after writing it and fix any syntax errors before reporting the task complete
---

# Mermaid Validation Skill

## When to Use

Use this skill every time you write (or edit) a document that
contains ````mermaid ... ``` ` fenced code blocks — requirement
documents, architecture documents, design notes, delivery reports,
anything. Mermaid parse errors make a document useless: the blocks
render as an error box in every reader's Markdown viewer.

## Workflow

After `write_file` returns success for a document:

1. **Read the document back**: `read_file(path)`. You need the
   authoritative on-disk bytes, not what you *intended* to write.
2. **Extract every ````mermaid` fence**. Each block starts on a line
   equal to ` ```mermaid ` (optionally with a trailing language tag)
   and ends at the next ` ``` ` line. Keep the original line ranges
   — you'll need them to patch errors.
3. **Validate each block** using the `mmdc` CLI (Mermaid CLI). For
   every block, write it to a temporary `.mmd` file and run:

   ```
   execute_shell(command="mmdc -i <tmp>.mmd -o /tmp/_discard.svg 2>&1 | head -40")
   ```

   - `exit_code == 0`: block is valid.
   - `exit_code != 0`: block has a parse error. The stderr contains
     a line like `Syntax error in text: … at line N`. Read it.
   - `command not found`: mmdc isn't installed. Fall through to the
     self-review checklist below.
4. **Fix every block with a parse error** via `edit_file`. Common
   fixes:
   - Unquoted labels containing spaces or punctuation →
     `A[some label]` needs `A["some label"]` (Mermaid ≥10 requires
     quotes for labels that aren't bare identifiers).
   - Reserved keywords as node IDs (`end`, `class`, `state`) →
     rename the ID.
   - `graph` / `flowchart` without a direction (`LR`, `TD`, `RL`,
     `BT`) → add one.
   - Arrows with the wrong number of dashes → `A --> B` not
     `A -> B`.
   - Unclosed subgraphs → every `subgraph X` needs `end`.
   - C4: missing `title` or missing final `UpdateLayoutConfig(...)` for
     some renderer versions → add a `title` line right after
     `C4Context`/`C4Container`/`C4Component`.
   - Sequence diagrams: `participant` names with spaces must be
     quoted or aliased (`participant U as "End User"`).
5. **Re-validate** the fixed block. Iterate until every block in the
   document parses cleanly or is conclusively shown to be a
   renderer-version issue (noted in the summary, not silenced).
6. Only then respond to the orchestrator.

## If mmdc is unavailable

When `mmdc` returns `command not found`, do a manual self-review
pass over each block against this checklist. Fix anything that
matches:

- [ ] First non-blank line declares a known diagram type
  (`flowchart`, `graph`, `sequenceDiagram`, `classDiagram`,
  `stateDiagram-v2`, `erDiagram`, `C4Context`, `C4Container`,
  `C4Component`, `C4Dynamic`, `C4Deployment`).
- [ ] `flowchart` / `graph` has a direction token on the same line
  (`LR` / `TD` / `RL` / `BT`).
- [ ] Every node label with spaces/punctuation is quoted:
  `A["My Label"]`, `B{"Decision?"}`, `C(("Circle"))`.
- [ ] Every `subgraph` has a matching `end`.
- [ ] Arrows use `-->`, `-.->`, `==>`, `---` (not `->` or `=>`).
- [ ] No reserved word as a node id (`end`, `class`, `state`,
  `subgraph`, `click`).
- [ ] Sequence diagrams quote participant display names that
  contain spaces.
- [ ] C4 diagrams declare `Person`, `System`, `Container`,
  `Component`, `Rel` with the ORDER `(id, "label", "description")`
  — no unquoted descriptions.

Note in your response summary that mmdc was not available and list
which blocks you self-reviewed.

## Do not

- Do NOT delete a broken block — fix it.
- Do NOT replace the diagram with prose ("see diagram below") —
  that defeats the document's purpose.
- Do NOT add a screenshot link or external image — the document
  must render Mermaid inline.
- Do NOT silence the error by renaming the fence to something
  non-mermaid (`text`, `plaintext`, etc.).
