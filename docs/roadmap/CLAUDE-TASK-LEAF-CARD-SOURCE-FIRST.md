```text
You are working inside the Teacher Progress repo.

Read first:
- docs/roadmap/AI-CONTENT-BANK-HANDOFF.md
- docs/roadmap/LEAF-CONTENT-BANK-SPEC.md
- docs/roadmap/LEAF-CONTENT-READER-ROADMAP.md
- docs/roadmap/AI-COLLABORATION-PROTOCOL.md
- docs/roadmap/AI-WORKLOG.md

Task goal:
Make the leaf lesson modal feel source-first instead of generation-first.

Important context:
- Backend already auto-seeds leaf content from extracted unit content when meaningful content_blocks exist.
- Backend leaf generation now supports additive generation:
  - POST /workflow/classes/{class_id}/units/{unit_id}/leaf-content/{item_id}/generate
  - request body may include:
    - provider
    - regenerate
    - merge_strategy = "fill_missing" or "replace"
- Default desired teacher experience:
  - if extracted content exists, show it clearly
  - primary action should fill missing parts with unit-brain help
  - full replacement should be secondary and explicit

Your scope:
- frontend/src/utils/leafContent.js
- frontend/src/style/components.css

Do not edit:
- backend files
- workflow session logic
- calendar/workflow route logic outside the leaf modal utility

Required UX changes:
1. In the lesson modal, show a small context banner near the top that explains the content origin:
   - if provider/source_payload indicates source-derived content:
     - say it was prepared from extracted unit content
   - if source_payload_json.mode === "hybrid":
     - say extracted content is being supplemented with unit-brain additions
   - if provider is notebooklm/manual only:
     - say this is teacher-edited or AI-generated lesson content

2. Replace the single generate action with clearer source-first actions:
   - primary button:
     - "Fill Missing with Unit Brain"
     - call generate endpoint with:
       - regenerate: true
       - merge_strategy: "fill_missing"
   - secondary button:
     - "Regenerate All"
     - call generate endpoint with:
       - regenerate: true
       - merge_strategy: "replace"
   - if there is no existing content at all, primary button label can remain stronger, e.g. "Generate from Unit Brain", but still use fill_missing

3. Surface a simple completeness summary:
   - count how many lesson sections currently have content
   - show something like:
     - "4 of 9 lesson sections ready"
   - use the existing CONTENT_FIELDS list

4. Keep Rendered / Source modes working exactly as before.

5. Do not break:
   - openLeafContentModal signature
   - summary cache behavior
   - lesson status dots

Implementation notes:
- Keep the code compact.
- Reuse existing modal structure where possible.
- Add only lightweight CSS needed for the new banner / action grouping / summary row.
- Do not add new dependencies.

Validation:
- run npm run build

When done:
- summarize changed files
- summarize the visible UX behavior
```
