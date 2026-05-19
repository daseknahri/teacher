# NotebookLM Unit Brain Architecture

Last updated: 2026-05-19

This note captures the target architecture for the next major evolution of the Teacher Progress workflow.

The current app is already good at:
- creating one notebook context per unit
- extracting a checklist
- tracking session progress
- generating write-ups and materials from the saved unit context

The next step is bigger:
- move from `PDF -> checklist` to `unit sources -> unit brain -> leaf content bank -> teacher-facing lesson reader`

This file is written so another coding model or engineer can continue the work without needing the full chat history.

## Core Product Direction

NotebookLM should not be used only as a one-time extractor.

It should become:
- the grounded understanding layer for a unit
- the generation layer for missing or weak teaching content

The app should remain:
- the source of truth for progress
- the place where structured content is stored
- the renderer/editor of the final teaching material

The teacher remains:
- the reviewer
- the real-world teaching decision-maker
- the one who accepts, edits, or regenerates content

## The Right Split

### NotebookLM should do
- read the unit PDF and other source files
- infer the real pedagogical structure of the unit
- extract or generate content for each leaf teaching step
- add missing pedagogical pieces when the source is thin
  - launch activity
  - guided example
  - practice exercise
  - assessment prompt
- regenerate a weak piece on demand

### The app should do
- store the unit structure and content per leaf
- render content in a clean teacher reader
- support markdown + LaTeX viewing/editing
- track progress by checklist leaf items
- connect session work, materials, and write-ups back to the exact leaf path
- support export later to textbook/PDF/slides

### NotebookLM should not do
- own the final UI rendering
- be the long-term editable content store
- be the progress database
- be responsible for exact classroom-reader layout

## Future Unit Pipeline

### 1. Source Pack

Each unit should be allowed to have a growing source pack, not only one PDF.

Example sources:
- main chapter PDF
- exercise sheet
- correction sheet
- teacher notes
- official curriculum guide
- remediation sheet
- prior good examples

NotebookLM notebook remains unit-scoped, not account-global.

### 2. Unit Brain

The notebook reads the whole unit source pack and yields a stable unit understanding.

Important saved artifacts:
- `unit_map_json`
- `content_blocks_json`
- `section_plans`
- `teacher_playbook`

This layer already exists partially in the current app and should be extended, not replaced.

### 3. Leaf Content Bank

Each last child checklist item becomes a real teaching object with stored content.

This is the key next abstraction.

Instead of only:
- a title
- a checkbox

Each leaf item should eventually have:
- explanation
- activity
- example
- exercise
- optional solution
- notes
- optional alternatives/regenerated variants

### 4. Teacher Reader / Editor

Teacher opens one leaf item and gets:
- rendered teaching content
- code/source mode
- quick regenerate actions per part
- mark done / close item

### 5. Derived Outputs

Once leaf content is stored well, the app can derive:
- session write-up
- textbook pages
- worksheets
- slides
- quizzes
- exams

## Why This Direction Solves the Current PDF Limitation

Today, extraction quality depends too much on whether the PDF visibly contains labels like:
- activite
- exemples
- exercices

That is useful but too brittle.

The stronger model is:
- PDF gives factual/content basis
- NotebookLM infers pedagogical role even if labels are missing
- app stores the inferred/generated role per leaf

So a source without an explicit activity can still produce:
- a generated launch activity in the right place

## Math Content Strategy

Math-heavy teaching content should be stored as:
- structured fields
- with Markdown + LaTeX inside them

Not as one giant raw LaTeX document.

Why:
- easier to edit one part
- easier to regenerate one part
- easier to render in app
- easier to export later

Good split:
- prose and lists in Markdown
- formulas and worked steps in LaTeX

## Boundaries to Keep

### Good boundary
- NotebookLM generates structured leaf content
- app renders/stores it

### Bad boundary
- app depends on NotebookLM to render the final classroom view

### Good boundary
- progress tracked by leaf item completion

### Bad boundary
- progress tracked by opaque generated documents only

## Success Criteria

The direction is correct when:
- a weakly structured PDF still produces a useful teaching flow
- missing activity/example/exercise can be generated in-place
- each leaf item can be opened and taught directly
- teacher can edit math source safely
- later exports reuse the same stored leaf content

## Near-Term Principle

We should optimize for:
- `unit understanding that survives across features`

not only:
- `prompt tuning for one extraction call`
