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

function _compactTeachPath(pathValues) {
  const rows = Array.isArray(pathValues)
    ? pathValues.map(value => String(value || '').trim()).filter(Boolean)
    : [];
  if (!rows.length) return '';
  const compact = rows.length > 2 ? rows.slice(-2) : rows;
  return compact.join(' > ');
}

function _getTeachBlockDisplayTitle(block, index, itemTitle = '') {
  const title = String(block?.title || '').trim();
  if (title) {
    const itemKey = _labelKey(itemTitle);
    const titleKey = _labelKey(title);
    const trailingNumber = title.match(/(\d+)\s*$/);
    if (itemKey && titleKey && titleKey.startsWith(itemKey) && trailingNumber) {
      return `Part ${trailingNumber[1]}`;
    }
    return title;
  }
  const kind = String(block?.kindLabel || '').trim();
  if (kind) return `${kind} ${index + 1}`;
  return `Block ${index + 1}`;
}

function _cleanTeachContent(contentMd, { itemTitle = '', blockTitle = '', pathValues = [] } = {}) {
  const raw = String(contentMd || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (!raw) return '';
  const lines = raw.split('\n');
  const titleKeys = new Set(
    [
      _labelKey(itemTitle),
      _labelKey(blockTitle),
      _labelKey((Array.isArray(pathValues) ? pathValues : []).join(' > ')),
      _labelKey(_compactTeachPath(pathValues)),
    ].filter(Boolean)
  );
  while (lines.length) {
    const first = lines[0].trim();
    const firstKey = _labelKey(first);
    if (!firstKey) {
      lines.shift();
      continue;
    }
    if (titleKeys.has(firstKey) || first.includes(' > ')) {
      lines.shift();
      continue;
    }
    break;
  }
  return lines.join('\n').trim() || raw;
}

function _semanticContentKey(text) {
  return String(text || '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .replace(/[*_`>#-]+/g, ' ')
    .replace(/\$+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
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
export function renderMarkdownLatex(text, { preserveLineBreaks = false } = {}) {
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
  let html = marked.parse(processed, { gfm: true, breaks: preserveLineBreaks });

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
  const cid = Number(classId || 0);
  const uid = Number(unitId || 0);
  if (!cid || !uid) return;

  const itemTitle = String(item?.title || '').trim() || 'Section lesson';
  const itemPath = Array.isArray(item?.item_path_json)
    ? item.item_path_json.map(value => String(value || '').trim()).filter(Boolean)
    : [];
  const sectionPath = Array.isArray(item?.section_path_json) && item.section_path_json.length
    ? item.section_path_json.map(value => String(value || '').trim()).filter(Boolean)
    : (itemPath.length > 1 ? itemPath.slice(0, -1) : []);
  if (!sectionPath.length) {
    showToast('This row is missing its section path, so the section lesson cannot open yet.', 'info');
    return;
  }

  document.getElementById('leaf-content-modal-overlay')?.remove();

  const sectionTitle = String(sectionPath[sectionPath.length - 1] || itemTitle || 'Section').trim();
  const sectionBreadcrumb = sectionPath.join(' > ');

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'leaf-content-modal-overlay';
  overlay.innerHTML = `
    <div class="modal leaf-content-modal leaf-content-modal--section">
      <div class="lcm-header">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-[10px] font-bold uppercase tracking-widest text-blue-600">Section</span>
          </div>
          <h2 class="text-[15px] font-bold text-slate-800 leading-tight">${_esc(sectionTitle)}</h2>
          <p class="lcm-header-path text-[11px] text-slate-400 mt-0.5">${_esc(sectionBreadcrumb)}</p>
        </div>
        <button id="lcm-btn-close" class="btn btn-ghost btn-sm !text-slate-400 !text-[18px] !leading-none !px-2" title="Close">x</button>
      </div>
      <div id="lcm-body" class="lcm-body">
        <p class="text-[13px] text-slate-400 py-8 text-center">Loading section content...</p>
      </div>
      <div class="lcm-footer">
        <div class="text-[12px] text-slate-400">Exact extracted section content</div>
        <button id="lcm-btn-close2" class="btn btn-ghost btn-sm">Close</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const body = overlay.querySelector('#lcm-body');
  function onKey(event) {
    if (event.key === 'Escape') close();
  }
  const close = () => {
    document.removeEventListener('keydown', onKey);
    overlay.remove();
  };
  overlay.querySelector('#lcm-btn-close')?.addEventListener('click', close);
  overlay.querySelector('#lcm-btn-close2')?.addEventListener('click', close);
  overlay.addEventListener('click', event => {
    if (event.target === overlay) close();
  });
  document.addEventListener('keydown', onKey);

  try {
    const lesson = await api(`/workflow/classes/${cid}/units/${uid}/section-lesson`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        section_path: sectionPath,
        item_path: itemPath,
        item_title: itemTitle,
      }),
    });
    const blocks = Array.isArray(lesson?.source_blocks) ? lesson.source_blocks : [];
    const excerpt = String(lesson?.source_excerpt_md || '').trim();

    if (!blocks.length && !excerpt) {
      body.innerHTML = `
        <div class="lcm-teach-empty">
          <p class="lcm-teach-empty-title">No extracted section content found</p>
          <p class="lcm-teach-empty-detail">This section does not have a clean extracted source block yet. We should improve extraction for this section before adding more AI on top.</p>
        </div>`;
      return;
    }

    body.innerHTML = `
      <div class="section-lesson-shell">
        ${blocks.length > 1 ? `
          <div class="section-lesson-outline" aria-label="Section outline">
            ${blocks.map((block, index) => {
              const displayTitle = _getTeachBlockDisplayTitle(block, index, sectionTitle);
              return `
                <button type="button" class="section-lesson-outline-item" data-section-block="${index}">
                  <span class="section-lesson-outline-kind">${_esc(block.kind_label || 'Content')}</span>
                  <span class="section-lesson-outline-title">${_esc(displayTitle)}</span>
                </button>
              `;
            }).join('')}
          </div>
        ` : ''}
        <div class="section-lesson-blocks">
          ${blocks.map((block, index) => {
            const displayTitle = _getTeachBlockDisplayTitle(block, index, sectionTitle);
            const cleanedContent = _cleanTeachContent(block.content_md, {
              itemTitle: sectionTitle,
              blockTitle: block.title,
              pathValues: sectionPath,
            });
            const showTitle = _labelKey(displayTitle) !== _labelKey(sectionTitle);
            return `
              <section class="section-lesson-block" id="section-lesson-block-${index}">
                <div class="section-lesson-block-head">
                  <span class="lcm-teach-pill">${_esc(block.kind_label || 'Content')}</span>
                  ${showTitle ? `<h3 class="section-lesson-block-title">${_esc(displayTitle)}</h3>` : ''}
                </div>
                <div class="lcm-teach-prose">${renderMarkdownLatex(cleanedContent, { preserveLineBreaks: true })}</div>
              </section>
            `;
          }).join('')}
          ${!blocks.length && excerpt ? `
            <section class="section-lesson-block">
              <div class="section-lesson-block-head">
                <span class="lcm-teach-pill">Section</span>
              </div>
              <div class="lcm-teach-prose">${renderMarkdownLatex(excerpt, { preserveLineBreaks: true })}</div>
            </section>
          ` : ''}
        </div>
      </div>
    `;

    body.querySelectorAll('[data-section-block]').forEach(node => {
      node.addEventListener('click', () => {
        const index = Number(node.getAttribute('data-section-block'));
        const target = body.querySelector(`#section-lesson-block-${index}`);
        target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  } catch (err) {
    showToast(err.message || 'Failed to open section lesson', 'error');
    close();
  }
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
