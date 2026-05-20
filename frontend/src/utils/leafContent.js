import { marked } from 'marked';
import katex from 'katex';
import 'katex/dist/katex.min.css';

import { api } from '../api/client.js';
import { showToast } from './toast.js';

function _esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

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

function _getTeachBlockDisplayTitle(block, index, sectionTitle = '') {
  const title = String(block?.title || '').trim();
  if (title) {
    const sectionKey = _labelKey(sectionTitle);
    const titleKey = _labelKey(title);
    const trailingNumber = title.match(/(\d+)\s*$/);
    if (sectionKey && titleKey && titleKey.startsWith(sectionKey) && trailingNumber) {
      return `Part ${trailingNumber[1]}`;
    }
    return title;
  }
  const kind = String(block?.kind_label || block?.kindLabel || '').trim();
  if (kind) return `${kind} ${index + 1}`;
  return `Block ${index + 1}`;
}

function _cleanTeachContent(contentMd, { sectionTitle = '', blockTitle = '', pathValues = [] } = {}) {
  const raw = String(contentMd || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
  if (!raw) return '';
  const lines = raw.split('\n');
  const titleKeys = new Set(
    [
      _labelKey(sectionTitle),
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

export async function fetchUnitSections(classId, unitId) {
  const cid = Number(classId || 0);
  const uid = Number(unitId || 0);
  if (!cid || !uid) return [];
  const rows = await api(`/workflow/classes/${cid}/units/${uid}/sections`);
  return Array.isArray(rows) ? rows : [];
}

export async function indexUnitSections(classId, unitId) {
  const cid = Number(classId || 0);
  const uid = Number(unitId || 0);
  if (!cid || !uid) return [];
  const rows = await api(`/workflow/classes/${cid}/units/${uid}/sections/index`, { method: 'POST' });
  return Array.isArray(rows) ? rows : [];
}

export async function prepareUnitSection(classId, unitId, sectionPath) {
  const cid = Number(classId || 0);
  const uid = Number(unitId || 0);
  if (!cid || !uid) return null;
  return api(`/workflow/classes/${cid}/units/${uid}/sections/prepare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ section_path: Array.isArray(sectionPath) ? sectionPath : [] }),
  });
}

export async function openLeafContentModal(classId, unitId, item) {
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
        <div class="text-[12px] text-slate-400">Exact section content</div>
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
          <p class="lcm-teach-empty-title">No section content found</p>
          <p class="lcm-teach-empty-detail">This section does not have usable extracted content yet. We should improve extraction for this section before adding anything else.</p>
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
              sectionTitle,
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
    const message = String(err?.message || 'Failed to open section lesson');
    showToast(message, 'error');
    close();
  }
}
