/**
 * Leaf Content Modal - Teacher Progress App
 *
 * Opens a modal to read, edit, and generate lesson content for a single
 * checklist leaf item, backed by the /workflow/.../leaf-content/{item_id} API.
 */

import { marked } from 'marked';
import katex from 'katex';
import 'katex/dist/katex.min.css';

import { api } from '../api/client.js';
import { showToast } from './toast.js';

const _summaryCache = new Map(); // key: `${classId}:${unitId}` -> Map<checklist_item_id, summary>

const CONTENT_FIELDS = [
  { key: 'teaching_goal_md', label: 'Teaching Goal' },
  { key: 'launch_activity_md', label: 'Launch Activity' },
  { key: 'explanation_md', label: 'Explanation' },
  { key: 'worked_example_md', label: 'Worked Example' },
  { key: 'practice_md', label: 'Practice' },
  { key: 'solution_md', label: 'Solution' },
  { key: 'assessment_md', label: 'Assessment' },
  { key: 'teacher_notes_md', label: 'Teacher Notes' },
  { key: 'source_excerpt_md', label: 'Source Excerpt' },
];

const SOURCE_SEGMENT_LABELS = {
  activity: 'Activity',
  lesson: 'Lesson',
  definition: 'Definition',
  property: 'Property',
  example: 'Example',
  exercise: 'Exercise',
  evaluation: 'Assessment',
  content: 'Content',
};

function _labelKey(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/[>:\-–—]+/g, ' ')
    .trim();
}

const EMPTY_LEAF_CONTENT = Object.freeze({
  id: null,
  unit_id: null,
  checklist_item_id: null,
  item_path_json: [],
  section_path_json: [],
  provider: 'manual',
  model: null,
  status: 'draft',
  reviewed: false,
  reviewed_at: null,
  teaching_goal_md: null,
  launch_activity_md: null,
  explanation_md: null,
  worked_example_md: null,
  practice_md: null,
  solution_md: null,
  assessment_md: null,
  teacher_notes_md: null,
  source_excerpt_md: null,
  source_payload_json: null,
  raw_provider_response_json: null,
  created_at: null,
  updated_at: null,
});

function _esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _setBusy(btn, busy) {
  if (!btn) return;
  btn.classList.toggle('btn-busy', busy);
  btn.disabled = busy;
}

function _createEmptyLeafContent(item = {}) {
  return {
    ...EMPTY_LEAF_CONTENT,
    checklist_item_id: Number(item?.id || 0) || null,
    item_path_json: Array.isArray(item?.item_path_json)
      ? item.item_path_json.map(value => String(value || '').trim()).filter(Boolean)
      : [],
    section_path_json: Array.isArray(item?.section_path_json)
      ? item.section_path_json.map(value => String(value || '').trim()).filter(Boolean)
      : [],
  };
}

function _countReadySections(content) {
  const draft = content || EMPTY_LEAF_CONTENT;
  return CONTENT_FIELDS.reduce((count, field) => count + (String(draft[field.key] || '').trim() ? 1 : 0), 0);
}

function _normalizeExactSourceSegments(content) {
  const rows = Array.isArray(content?.source_payload_json?.extracted_blocks)
    ? content.source_payload_json.extracted_blocks
    : [];
  return rows
    .map(row => ({
      title: String(row?.title || '').trim(),
      kind: String(row?.kind || '').trim().toLowerCase(),
      phase: String(row?.teaching_phase || '').trim().toLowerCase(),
      contentMd: String(row?.content_md || '').trim(),
      contentSource: String(row?.content_source || '').trim().toLowerCase(),
    }))
    .filter(row => row.contentMd);
}

function _getLeafContentOriginMeta(content) {
  const provider = String(content?.provider || 'manual').trim().toLowerCase();
  const sourceMode = String(content?.source_payload_json?.mode || '').trim().toLowerCase();
  const exactSourceCount = _normalizeExactSourceSegments(content).length;
  if (sourceMode === 'hybrid') {
    const filled = Array.isArray(content?.source_payload_json?.filled_fields) ? content.source_payload_json.filled_fields.length : 0;
    return {
      tone: 'hybrid',
      title: 'Prepared from the unit source and completed with unit-brain help',
      detail: filled > 0
        ? `${filled} missing section${filled > 1 ? 's were' : ' was'} added on top of the extracted lesson content.`
        : 'This lesson keeps the extracted source content and can be improved section by section.',
      sourceDetail: exactSourceCount ? `${exactSourceCount} exact source block${exactSourceCount === 1 ? '' : 's'} preserved from the unit.` : '',
    };
  }
  if (sourceMode === 'source_derived' || provider === 'source_extract') {
    return {
      tone: 'source',
      title: 'Prepared from extracted unit content',
      detail: 'This lesson card is grounded in the PDF structure we already extracted for the unit.',
      sourceDetail: exactSourceCount ? `${exactSourceCount} exact source block${exactSourceCount === 1 ? '' : 's'} preserved from the unit.` : '',
    };
  }
  if (provider === 'notebooklm') {
    return {
      tone: 'brain',
      title: 'Generated with unit-brain support',
      detail: 'This lesson content was generated from the saved unit brain and can be edited freely.',
      sourceDetail: exactSourceCount ? `${exactSourceCount} extracted source block${exactSourceCount === 1 ? '' : 's'} also available below.` : '',
    };
  }
  return {
    tone: 'manual',
    title: 'Teacher-edited lesson content',
    detail: 'This lesson card is stored in the app and can be refined in source mode at any time.',
    sourceDetail: exactSourceCount ? `${exactSourceCount} extracted source block${exactSourceCount === 1 ? '' : 's'} also available below.` : '',
  };
}

/**
 * Render a Markdown + LaTeX string as HTML.
 * Strategy: extract LaTeX spans before Markdown parsing so marked
 * does not alter math tokens, then inject KaTeX HTML back in.
 */
export function renderMarkdownLatex(text) {
  if (!text) return '';

  const parts = [];
  let processed = String(text);

  processed = processed.replace(/\$\$([\s\S]+?)\$\$/g, (_match, latex) => {
    const placeholder = `\x00KATEX_BLOCK_${parts.length}\x00`;
    let html;
    try {
      html = katex.renderToString(latex.trim(), { displayMode: true, throwOnError: false });
    } catch {
      html = `<span class="lcm-math-err">${_esc(latex)}</span>`;
    }
    parts.push({ placeholder, html });
    return placeholder;
  });

  processed = processed.replace(/(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)/g, (_match, latex) => {
    const placeholder = `\x00KATEX_INLINE_${parts.length}\x00`;
    let html;
    try {
      html = katex.renderToString(latex.trim(), { displayMode: false, throwOnError: false });
    } catch {
      html = `<span class="lcm-math-err">${_esc(latex)}</span>`;
    }
    parts.push({ placeholder, html });
    return placeholder;
  });

  processed = processed.replace(/</g, '&lt;').replace(/>/g, '&gt;');
  let html = marked.parse(processed, { gfm: true, breaks: false });

  parts.forEach(({ placeholder, html: katexHtml }) => {
    const escapedPlaceholder = placeholder.replace(/\x00/g, '&#0;');
    html = html.split(placeholder).join(katexHtml);
    html = html.split(escapedPlaceholder).join(katexHtml);
  });

  return html;
}

function _summaryCacheKey(classId, unitId) {
  const cid = Number(classId || 0);
  const uid = Number(unitId || 0);
  return cid > 0 && uid > 0 ? `${cid}:${uid}` : '';
}

function _upsertUnitLeafContentSummary(classId, unitId, leafContent) {
  const cacheKey = _summaryCacheKey(classId, unitId);
  const checklistItemId = Number(leafContent?.checklist_item_id || 0);
  if (!cacheKey || checklistItemId <= 0) return;
  const summaryMap = _summaryCache.get(cacheKey) || new Map();
  summaryMap.set(checklistItemId, {
    id: Number(leafContent?.id || 0) || null,
    checklist_item_id: checklistItemId,
    status: String(leafContent?.status || 'draft').trim() || 'draft',
    reviewed: Boolean(leafContent?.reviewed),
    updated_at: leafContent?.updated_at || new Date().toISOString(),
    provider: String(leafContent?.provider || 'manual').trim() || 'manual',
  });
  _summaryCache.set(cacheKey, summaryMap);
}

export function invalidateUnitLeafContentSummaries(classId, unitId) {
  const cacheKey = _summaryCacheKey(classId, unitId);
  if (!cacheKey) return;
  _summaryCache.delete(cacheKey);
}

export async function openLeafContentModal(classId, unitId, item, options = {}) {
  const itemId = Number(item?.id || 0);
  if (!itemId || !classId || !unitId) return;
  const onChange = typeof options?.onChange === 'function' ? options.onChange : null;

  document.getElementById('leaf-content-modal-overlay')?.remove();

  const itemTitle = String(item?.title || 'Leaf Item');
  const itemPath = Array.isArray(item?.item_path_json) ? item.item_path_json : [];
  const pathBreadcrumb = itemPath.length > 1 ? itemPath.slice(0, -1).join(' > ') : '';

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'leaf-content-modal-overlay';
  overlay.innerHTML = `
    <div class="modal leaf-content-modal">
      <div class="lcm-header">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-[10px] font-bold uppercase tracking-widest text-blue-600">Lesson</span>
            <span id="lcm-status-badge"></span>
          </div>
          <h2 class="text-[15px] font-bold text-slate-800 leading-tight">${_esc(itemTitle)}</h2>
          ${pathBreadcrumb ? `<p class="text-[11px] text-slate-400 mt-0.5">${_esc(pathBreadcrumb)}</p>` : ''}
        </div>
        <div class="flex items-center gap-1 flex-shrink-0">
          <button id="lcm-btn-teach" class="btn btn-sm btn-ghost lcm-mode-btn">Teach</button>
          <button id="lcm-btn-rendered" class="btn btn-sm btn-secondary lcm-mode-btn">Review</button>
          <button id="lcm-btn-source" class="btn btn-sm btn-ghost lcm-mode-btn">Edit</button>
          <button id="lcm-btn-close" class="btn btn-ghost btn-sm !text-slate-400 !text-[18px] !leading-none !px-2" title="Close">x</button>
        </div>
      </div>
      <div id="lcm-body" class="lcm-body">
        <p class="text-[13px] text-slate-400 py-8 text-center">Loading...</p>
      </div>
      <div class="lcm-footer">
        <div class="lcm-footer-actions">
          <button id="lcm-btn-generate" class="btn btn-secondary btn-sm">Generate from Unit Brain</button>
          <button id="lcm-btn-regenerate" class="btn btn-ghost btn-sm" hidden>Regenerate All</button>
        </div>
        <div class="flex items-center gap-2">
          <button id="lcm-btn-save" class="btn btn-primary btn-sm" hidden>Save</button>
          <button id="lcm-btn-close2" class="btn btn-ghost btn-sm">Close</button>
        </div>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  let mode = 'rendered';
  let content = null;
  let teachIndex = 0;

  const modal = overlay.querySelector('.leaf-content-modal');
  const body = overlay.querySelector('#lcm-body');
  const statusBadge = overlay.querySelector('#lcm-status-badge');
  const btnTeach = overlay.querySelector('#lcm-btn-teach');
  const btnRendered = overlay.querySelector('#lcm-btn-rendered');
  const btnSource = overlay.querySelector('#lcm-btn-source');
  const btnGenerate = overlay.querySelector('#lcm-btn-generate');
  const btnRegenerate = overlay.querySelector('#lcm-btn-regenerate');
  const btnSave = overlay.querySelector('#lcm-btn-save');

  function onKey(event) {
    if (mode === 'teach') {
      if (event.key === 'ArrowRight') {
        moveTeachIndex(1);
        return;
      }
      if (event.key === 'ArrowLeft') {
        moveTeachIndex(-1);
        return;
      }
    }
    if (event.key === 'Escape') close();
  }

  function close() {
    document.removeEventListener('keydown', onKey);
    overlay.remove();
  }

  overlay.querySelector('#lcm-btn-close')?.addEventListener('click', close);
  overlay.querySelector('#lcm-btn-close2')?.addEventListener('click', close);
  overlay.addEventListener('click', event => {
    if (event.target === overlay) close();
  });
  document.addEventListener('keydown', onKey);

  function updateStatusBadge() {
    if (!content) {
      statusBadge.innerHTML = '';
      return;
    }
    const status = String(content?.status || 'draft');
    const reviewed = Boolean(content?.reviewed);
    let cls = 'badge badge-gray';
    if (status === 'ok') cls = reviewed ? 'badge badge-green' : 'badge badge-blue';
    else if (status === 'degraded') cls = 'badge badge-amber';
    statusBadge.innerHTML =
      `<span class="${cls}">${_esc(status)}</span>` +
      (reviewed ? ' <span class="badge badge-green">Reviewed</span>' : '');
  }

  function renderRenderedMode() {
    const draft = content || _createEmptyLeafContent(item);
    const origin = _getLeafContentOriginMeta(draft);
    const readyCount = _countReadySections(draft);
    const totalCount = CONTENT_FIELDS.length;
    const mainFields = CONTENT_FIELDS.filter(field => field.key !== 'source_excerpt_md');
    const sections = mainFields.filter(field => draft[field.key]);
    const excerpt = draft.source_excerpt_md;
    const exactSourceSegments = _normalizeExactSourceSegments(draft);

    if (!sections.length && !excerpt && !exactSourceSegments.length) {
      body.innerHTML = `
        <p class="text-[13px] text-slate-400 py-8 text-center">
          No content fields filled in yet.
          Switch to <strong>Source</strong> mode to add content manually, or press <strong>Generate</strong>.
        </p>`;
      return;
    }

    body.innerHTML = `
      <div class="flex flex-col gap-3">
        <div class="lcm-origin-banner lcm-origin-banner--${_esc(origin.tone)}">
          <div class="lcm-origin-copy">
            <p class="lcm-origin-title">${_esc(origin.title)}</p>
            <p class="lcm-origin-detail">${_esc(origin.detail)}</p>
            ${origin.sourceDetail ? `<p class="lcm-origin-detail mt-1">${_esc(origin.sourceDetail)}</p>` : ''}
          </div>
          <div class="lcm-origin-summary">
            <span class="lcm-summary-label">Lesson readiness</span>
            <span class="lcm-summary-value">${readyCount} of ${totalCount} sections ready</span>
          </div>
        </div>
        ${exactSourceSegments.length ? `
          <div class="rounded-2xl border border-blue-100 bg-blue-50/60 px-4 py-4">
            <div class="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <p class="text-[10px] font-bold uppercase tracking-widest text-blue-600 mb-1">Exact Source Content</p>
                <p class="text-[12px] text-slate-600">These blocks are preserved from the extracted unit content so you can teach directly from what was in the document.</p>
              </div>
              <span class="badge badge-blue">${exactSourceSegments.length} block${exactSourceSegments.length === 1 ? '' : 's'}</span>
            </div>
            <div class="mt-3 flex flex-col gap-3">
              ${exactSourceSegments.map(segment => `
                <div class="rounded-2xl border border-blue-100 bg-white px-4 py-4">
                  <div class="flex items-center gap-2 flex-wrap mb-2">
                    <span class="badge badge-blue">${_esc(SOURCE_SEGMENT_LABELS[segment.kind] || 'Source')}</span>
                    ${segment.title ? `<span class="text-[12px] font-semibold text-slate-700">${_esc(segment.title)}</span>` : ''}
                    <span class="text-[10px] text-slate-400 uppercase tracking-wider">${segment.contentSource === 'source_excerpt' ? 'Exact text' : 'Extracted content'}</span>
                  </div>
                  <div class="lcm-prose">${renderMarkdownLatex(segment.contentMd)}</div>
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}
        ${sections.map(field => `
          <div class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
            <p class="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">${_esc(field.label)}</p>
            <div class="lcm-prose">${renderMarkdownLatex(draft[field.key])}</div>
          </div>
        `).join('')}
        ${excerpt ? `
          <details class="rounded-2xl border border-slate-100 bg-slate-50/70 px-4 py-3">
            <summary class="text-[11px] font-semibold text-slate-400 cursor-pointer select-none">Source Excerpt</summary>
            <div class="lcm-prose text-[12px] text-slate-500 mt-3">${renderMarkdownLatex(excerpt)}</div>
          </details>` : ''}
      </div>`;
  }

  function _buildTeachBlocks(draft) {
    const exactSourceSegments = _normalizeExactSourceSegments(draft);
    if (exactSourceSegments.length) {
      return exactSourceSegments.map(segment => ({
        kindLabel: SOURCE_SEGMENT_LABELS[segment.kind] || 'Source',
        title: segment.title || '',
        subtitle: segment.contentSource === 'source_excerpt' ? 'Exact text from PDF' : 'Extracted source content',
        contentMd: segment.contentMd,
      }));
    }
    return CONTENT_FIELDS
      .filter(field => field.key !== 'teacher_notes_md' && field.key !== 'source_excerpt_md')
      .map(field => ({
        kindLabel: field.label,
        title: '',
        subtitle: 'Lesson content',
        contentMd: String(draft?.[field.key] || '').trim(),
      }))
      .filter(block => block.contentMd);
  }

  function renderTeachMode() {
    const draft = content || _createEmptyLeafContent(item);
    const blocks = _buildTeachBlocks(draft);
    if (!blocks.length) {
      body.innerHTML = `
        <div class="lcm-teach-empty">
          <p class="lcm-teach-empty-title">Nothing ready to teach yet</p>
          <p class="lcm-teach-empty-detail">This leaf does not have a readable source block yet. Use <strong>Rendered</strong> or <strong>Source</strong> to prepare it first.</p>
        </div>`;
      return;
    }
    const safeIndex = Math.max(0, Math.min(teachIndex, blocks.length - 1));
    teachIndex = safeIndex;
    const current = blocks[safeIndex];
    const blockTitle = _labelKey(current.title) && _labelKey(current.title) !== _labelKey(itemTitle)
      ? current.title
      : '';
    body.innerHTML = `
      <div class="lcm-teach">
        <div class="lcm-teach-topbar">
          <div class="lcm-teach-meta">
            <span class="lcm-teach-pill">${_esc(current.kindLabel)}</span>
            ${blockTitle ? `<span class="lcm-teach-meta-title">${_esc(blockTitle)}</span>` : ''}
          </div>
          ${blocks.length > 1 ? `<div class="lcm-teach-counter">${safeIndex + 1} / ${blocks.length}</div>` : ''}
        </div>
        <div class="lcm-teach-stage">
          <div class="lcm-teach-stage-head">
            <h3 class="lcm-teach-stage-title">${_esc(itemTitle)}</h3>
            ${pathBreadcrumb ? `<p class="lcm-teach-stage-path">${_esc(pathBreadcrumb)}</p>` : ''}
          </div>
          <div class="lcm-teach-prose">${renderMarkdownLatex(current.contentMd)}</div>
        </div>
        ${blocks.length > 1 ? `
        <div class="lcm-teach-nav">
          <button type="button" class="btn btn-ghost btn-sm" id="lcm-teach-prev" ${safeIndex <= 0 ? 'disabled' : ''}>Previous</button>
          <button type="button" class="btn btn-secondary btn-sm" id="lcm-teach-next" ${safeIndex >= blocks.length - 1 ? 'disabled' : ''}>Next</button>
        </div>` : ''}
      </div>`;
    if (blocks.length > 1) {
      body.querySelector('#lcm-teach-prev')?.addEventListener('click', () => moveTeachIndex(-1));
      body.querySelector('#lcm-teach-next')?.addEventListener('click', () => moveTeachIndex(1));
    }
  }

  function renderSourceMode() {
    const draft = content || _createEmptyLeafContent(item);
    const origin = _getLeafContentOriginMeta(draft);
    const readyCount = _countReadySections(draft);
    const totalCount = CONTENT_FIELDS.length;
    body.innerHTML = `
      <div class="flex flex-col gap-4">
        <div class="lcm-origin-banner lcm-origin-banner--${_esc(origin.tone)}">
          <div class="lcm-origin-copy">
            <p class="lcm-origin-title">${_esc(origin.title)}</p>
            <p class="lcm-origin-detail">${_esc(origin.detail)}</p>
          </div>
          <div class="lcm-origin-summary">
            <span class="lcm-summary-label">Lesson readiness</span>
            <span class="lcm-summary-value">${readyCount} of ${totalCount} sections ready</span>
          </div>
        </div>
        <p class="text-[12px] text-slate-400">
          Edit below. Use Markdown for structure, <code>$...$</code> for inline math,
          <code>$$...$$</code> for block math.
        </p>
        ${CONTENT_FIELDS.map(field => `
          <div class="flex flex-col gap-1.5">
            <label class="text-[11px] font-semibold uppercase tracking-widest text-slate-400">${_esc(field.label)}</label>
            <textarea
              id="lcm-field-${field.key}"
              class="text-[12px] font-mono"
              style="min-height:80px;resize:vertical"
              placeholder="Leave empty if not applicable"
            >${_esc(draft[field.key] || '')}</textarea>
          </div>
        `).join('')}
      </div>`;
  }

  function renderBody() {
    const hasAnyContent = Boolean(content) && _countReadySections(content) > 0;
    const footerActions = overlay.querySelector('.lcm-footer-actions');
    btnGenerate.textContent = hasAnyContent ? 'Fill Missing with Unit Brain' : 'Generate from Unit Brain';
    btnRegenerate.hidden = !hasAnyContent;
    if (footerActions) footerActions.style.display = mode === 'teach' ? 'none' : 'flex';
    if (!content && mode !== 'source') {
      body.innerHTML = `
        <div class="flex flex-col items-center justify-center gap-3 py-12 text-center">
          <p class="text-[13px] text-slate-600 font-medium">No lesson content yet</p>
          <p class="text-[12px] text-slate-400 max-w-[260px]">
            Press <strong>Generate from Unit Brain</strong> to create the first lesson draft for this leaf.
          </p>
        </div>`;
      btnSave.hidden = true;
      return;
    }

    if (mode === 'teach') {
      renderTeachMode();
      btnSave.hidden = true;
    } else if (mode === 'rendered') {
      renderRenderedMode();
      btnSave.hidden = true;
    } else {
      renderSourceMode();
      btnSave.hidden = false;
    }
  }

  function moveTeachIndex(delta) {
    if (mode !== 'teach') return;
    const blockCount = _buildTeachBlocks(content || _createEmptyLeafContent(item)).length;
    if (!blockCount) return;
    teachIndex = Math.max(0, Math.min(blockCount - 1, teachIndex + delta));
    renderTeachMode();
  }

  function setMode(nextMode) {
    mode = nextMode;
    modal?.classList.toggle('leaf-content-modal--teach', mode === 'teach');
    btnTeach.classList.toggle('btn-secondary', mode === 'teach');
    btnTeach.classList.toggle('btn-ghost', mode !== 'teach');
    btnRendered.classList.toggle('btn-secondary', mode === 'rendered');
    btnRendered.classList.toggle('btn-ghost', mode !== 'rendered');
    btnSource.classList.toggle('btn-secondary', mode === 'source');
    btnSource.classList.toggle('btn-ghost', mode !== 'source');
    renderBody();
  }

  btnTeach.addEventListener('click', () => setMode('teach'));
  btnRendered.addEventListener('click', () => setMode('rendered'));
  btnSource.addEventListener('click', () => setMode('source'));

  function collectSourceFields() {
    const fields = {};
    CONTENT_FIELDS.forEach(field => {
      const node = overlay.querySelector(`#lcm-field-${field.key}`);
      fields[field.key] = node ? (node.value.trim() || null) : ((content || EMPTY_LEAF_CONTENT)[field.key] ?? null);
    });
    return fields;
  }

  async function loadContent() {
    body.innerHTML = `<p class="text-[13px] text-slate-400 py-8 text-center">Loading...</p>`;
    try {
      content = await api(`/workflow/classes/${classId}/units/${unitId}/leaf-content/${itemId}`);
    } catch (err) {
      if (err.status === 404) {
        content = null;
      } else {
        showToast(err.message || 'Failed to load leaf content', 'error');
        close();
        return;
      }
    }
    const exactSourceSegments = _normalizeExactSourceSegments(content || {});
    if (exactSourceSegments.length) {
      teachIndex = 0;
      mode = 'teach';
    }
    updateStatusBadge();
    setMode(mode);
  }

  btnGenerate.addEventListener('click', async () => {
    _setBusy(btnGenerate, true);
    _setBusy(btnRegenerate, true);
    try {
      const result = await api(
        `/workflow/classes/${classId}/units/${unitId}/leaf-content/${itemId}/generate`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ regenerate: true, merge_strategy: 'fill_missing' }),
        },
      );
      content = result?.leaf_content ?? null;
      if (content) _upsertUnitLeafContentSummary(classId, unitId, content);
      updateStatusBadge();
      if (_normalizeExactSourceSegments(content || {}).length) teachIndex = 0;
      setMode(_normalizeExactSourceSegments(content || {}).length ? 'teach' : 'rendered');
      onChange?.(content);
      showToast('Missing lesson sections filled', 'ok');
    } catch (err) {
      showToast(err.message || 'Generation failed', 'error');
    } finally {
      _setBusy(btnGenerate, false);
      _setBusy(btnRegenerate, false);
    }
  });

  btnRegenerate.addEventListener('click', async () => {
    _setBusy(btnGenerate, true);
    _setBusy(btnRegenerate, true);
    try {
      const result = await api(
        `/workflow/classes/${classId}/units/${unitId}/leaf-content/${itemId}/generate`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ regenerate: true, merge_strategy: 'replace' }),
        },
      );
      content = result?.leaf_content ?? null;
      if (content) _upsertUnitLeafContentSummary(classId, unitId, content);
      updateStatusBadge();
      if (_normalizeExactSourceSegments(content || {}).length) teachIndex = 0;
      setMode(_normalizeExactSourceSegments(content || {}).length ? 'teach' : 'rendered');
      onChange?.(content);
      showToast('Lesson card regenerated', 'ok');
    } catch (err) {
      showToast(err.message || 'Regeneration failed', 'error');
    } finally {
      _setBusy(btnGenerate, false);
      _setBusy(btnRegenerate, false);
    }
  });

  btnSave.addEventListener('click', async () => {
    if (!content) content = _createEmptyLeafContent(item);
    _setBusy(btnSave, true);
    try {
      const fields = collectSourceFields();
      content = await api(
        `/workflow/classes/${classId}/units/${unitId}/leaf-content/${itemId}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(fields),
        },
      );
      if (content) _upsertUnitLeafContentSummary(classId, unitId, content);
      updateStatusBadge();
      onChange?.(content);
      showToast('Lesson card saved', 'ok');
    } catch (err) {
      showToast(err.message || 'Save failed', 'error');
    } finally {
      _setBusy(btnSave, false);
    }
  });

  await loadContent();
}

export async function fetchUnitLeafContentSummaries(classId, unitId) {
  const cid = Number(classId || 0);
  const uid = Number(unitId || 0);
  const cacheKey = _summaryCacheKey(cid, uid);
  if (!cacheKey) return [];
  if (_summaryCache.has(cacheKey)) return Array.from(_summaryCache.get(cacheKey).values());
  try {
    const rows = await api(`/workflow/classes/${cid}/units/${uid}/leaf-content`);
    const safe = Array.isArray(rows) ? rows : [];
    const byItemId = new Map(safe.map(r => [Number(r.checklist_item_id), r]));
    _summaryCache.set(cacheKey, byItemId);
    return safe;
  } catch {
    return [];
  }
}

export function getLeafSummaryMap(classId, unitId) {
  const cacheKey = _summaryCacheKey(classId, unitId);
  return _summaryCache.get(cacheKey) || new Map();
}

export function renderLeafStatusBadge(itemId, classId, unitId) {
  const summary = getLeafSummaryMap(classId, unitId).get(Number(itemId || 0));
  if (!summary) return '';
  const status = String(summary.status || 'draft');
  const isReady = status === 'ok' || status === 'ready';
  const dotClass = isReady ? 'leaf-status-dot--ready' : 'leaf-status-dot--draft';
  const label = isReady ? 'Lesson content ready' : 'Lesson content draft';
  return `<span class="leaf-status-dot ${dotClass}" title="${label}"></span>`;
}
