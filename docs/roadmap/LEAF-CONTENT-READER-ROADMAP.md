# Leaf Content Reader and Generation Roadmap

Last updated: 2026-05-19

This file turns the `unit brain -> leaf content bank` idea into a practical implementation roadmap.

## Goal

Move from:
- checklist extraction

to:
- per-leaf teaching content that can be opened, taught, edited, regenerated, and reused

## Phase 1 - Preserve the Right Context

Goal:
- keep the exact started/checked unit branch visible and reusable everywhere

Status:
- mostly in progress / partially implemented

Current direction already built:
- checked item paths
- checked section paths
- grouped teaching flow
- session write-up uses grouped sections
- session headlines now preserve started outline better

What still matters here:
- keep path-aware context available as a stable source for leaf generation

## Phase 2 - Add Leaf Content Storage

Goal:
- create a persisted content record for each last child checklist item

Tasks:
- add backend model/table for leaf content
- add API schema for leaf content read/write
- add provider/source payload storage
- map each record to `checklist_item_id`

Definition of done:
- app can store and retrieve one content record for one leaf item

## Phase 3 - Generate Leaf Content from NotebookLM

Goal:
- ask NotebookLM for one leaf item at a time

Input should include:
- unit title
- item path
- section path
- unit map
- content blocks
- section plan
- source excerpt if useful

Output should normalize into:
- teaching goal
- launch activity
- explanation
- worked example
- practice
- solution
- assessment
- teacher notes

Definition of done:
- one endpoint can generate and save content for one leaf item

## Phase 4 - Build the Leaf Reader

Goal:
- teacher can open a leaf item and teach from it directly

UI requirements:
- rendered mode
- source mode
- save edits
- math rendering
- compact teaching layout

Recommended renderer:
- Markdown renderer
- KaTeX for math

Definition of done:
- teacher can open one leaf item and use it as a teaching card

## Phase 5 - Partial Regeneration

Goal:
- do not regenerate the whole leaf each time

First regeneration actions:
- regenerate activity
- regenerate explanation
- regenerate worked example
- regenerate practice
- regenerate easier version
- regenerate harder version

Definition of done:
- one weak part can be replaced without losing the rest of the leaf

## Phase 6 - Connect to Session Flow

Goal:
- active session can open the relevant leaf items directly from the checklist/teaching flow

UI ideas:
- click leaf item -> open lesson card
- mark done after teaching
- keep session route aligned with leaf content used

Definition of done:
- teacher can move through the session from leaf card to leaf card

## Phase 7 - Reuse in Derived Materials

Goal:
- leaf content becomes the reusable source for other outputs

Derived outputs later:
- session write-up
- textbook pages
- worksheets
- slides
- quizzes
- exams

Definition of done:
- these outputs use saved leaf content first, not only fresh ad-hoc generation

## Recommended Technical Sequence

### First coding sequence
1. backend leaf-content model
2. basic leaf-content API
3. single leaf generator using NotebookLM
4. reader view in frontend
5. source toggle + save
6. one-part regeneration

### After that
1. session integration
2. unit-level batch generation tools
3. textbook/export composition
4. slides and exam generation

## Prompt Strategy

Do not ask NotebookLM:
- "write the whole unit perfectly"

Do ask NotebookLM:
- "given this exact leaf path and the unit context, generate the teaching content for this leaf"

This is more controllable and easier to review.

## PDF Problem This Solves

If the PDF is missing explicit pedagogical labels like:
- activity
- example
- exercise

We still want NotebookLM to infer:
- where a launch activity belongs
- where a worked example belongs
- where practice belongs

That is easier to do accurately per leaf than for the whole unit at once.

## Markdown + LaTeX Rule

Store teaching content as:
- readable Markdown
- LaTeX only where math needs it

Avoid:
- whole-leaf monolithic raw LaTeX documents as the first storage format

## Suggested First Deliverable

The best first concrete feature is:
- one leaf item can be opened
- one button generates its content from NotebookLM
- teacher sees rendered Markdown + LaTeX
- teacher can switch to source mode and edit
- teacher can save the edits

That first deliverable is enough to validate the whole direction.

## Suggested Docs/Contracts for Future Contributors

Any future implementation should preserve these rules:
- NotebookLM generates, app renders
- leaf item is the core teaching object
- progress stays tied to checklist completion
- math source is editable
- regeneration should be granular
