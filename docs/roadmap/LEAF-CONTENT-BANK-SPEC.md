# Leaf Content Bank Specification

Last updated: 2026-05-19

This file defines the proposed data model and content contract for turning each last-child checklist item into a real teaching content record.

## Goal

Every last child checklist item should be teachable directly.

That means the app should eventually store a content record for each leaf item, not only its title and completion state.

## Product Rule

A leaf content record should be:
- structured
- reviewable
- regenerable in parts
- renderable in Markdown + LaTeX
- stable enough to reuse later in textbook/slides/exams

## Recommended Storage Shape

Suggested new concept:
- `workflow_leaf_content`

Suggested ownership:
- one primary content record per checklist leaf
- optional regenerated variants or historical revisions later

## Minimum Fields

Suggested core fields:

- `id`
- `unit_id`
- `checklist_item_id`
- `item_path_json`
- `section_path_json`
- `session_hint_number`
- `provider`
- `model`
- `status`
- `source_payload_json`
- `raw_provider_response_json`
- `reviewed`
- `reviewed_at`
- `reviewed_by_user_id`
- `created_at`
- `updated_at`

## Content Fields

Use Markdown with LaTeX inside the text.

Suggested fields:
- `teaching_goal_md`
- `launch_activity_md`
- `explanation_md`
- `worked_example_md`
- `practice_md`
- `solution_md`
- `assessment_md`
- `teacher_notes_md`

Optional metadata fields:
- `difficulty`
- `estimated_minutes`
- `student_visible`
- `math_topics_json`
- `source_excerpt_md`
- `source_references_json`

## Why Structured Fields Are Better Than One Big Blob

Bad option:
- one big raw LaTeX document per leaf

Problems:
- hard to regenerate only one part
- hard to edit safely
- hard to reuse in multiple outputs
- hard to display selectively in UI

Better option:
- separate fields for activity, explanation, example, practice, solution
- each field can contain Markdown + LaTeX

This supports:
- partial regeneration
- partial approval
- clean UI rendering
- later recomposition into other assets

## Rendering Format

### Store
- Markdown text
- inline LaTeX: `$...$`
- block LaTeX: `$$...$$`

### Render in app
- Markdown renderer
- KaTeX for math rendering

### Edit in app
- visual mode
- source mode
- teacher can switch between both

## Suggested Provider Contract

NotebookLM should be asked to return a structured object for one leaf item.

Suggested logical output shape:

```json
{
  "leaf_title": "...",
  "item_path": ["chapter", "section", "leaf"],
  "section_path": ["chapter", "section"],
  "teaching_goal_md": "...",
  "launch_activity_md": "...",
  "explanation_md": "...",
  "worked_example_md": "...",
  "practice_md": "...",
  "solution_md": "...",
  "assessment_md": "...",
  "teacher_notes_md": "...",
  "source_excerpt_md": "..."
}
```

This is not final API code. It is the shape the app should aim to normalize into.

## Regeneration Rules

The app should support regenerating one part at a time.

Examples:
- regenerate launch activity
- regenerate worked example
- regenerate easier practice
- regenerate harder practice
- rewrite explanation more simply

This is safer than regenerating the entire leaf content each time.

## Review Rules

Teacher should be able to:
- accept whole leaf content
- edit source directly
- regenerate one part
- keep an older version if the new one is worse

So the long-term model should allow versions or at least a history trail.

## Relationship to Existing Models

This should connect to existing app concepts:
- `WorkflowChecklistItem`
- `WorkflowUnitBlueprint`
- `content_blocks_json`
- `teacher_playbook`
- `WorkflowSessionWriteup`

The leaf bank should become the preferred source for:
- session lesson reader
- write-up guidance
- future textbook generation
- future slide generation

## Non-Goals for First Version

Do not try to solve all of these at once:
- full version history UI
- perfect symbolic math verification
- giant multi-source merge UI
- final textbook compositor

First version should focus on:
- one leaf content record
- structured Markdown + LaTeX fields
- render mode + source mode
- regenerate one field at a time

## First Useful UX

Inside a leaf item, the teacher should be able to:
1. open the leaf
2. read rendered math/content
3. switch to source view
4. edit the text or formula
5. save
6. regenerate one block if weak
7. mark the checklist item done after teaching

That is the smallest version that already creates strong value.
