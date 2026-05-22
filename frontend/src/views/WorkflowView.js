/**
 * WorkflowView.js  Unit setup, attendance grid, session management
 * Teacher Progress App  Tailwind v4  FIXED API paths
 *
 * Real API paths (from backend routers):
 *   GET    /workflow/classes/{id}                        workspace
 *   POST   /workflow/classes/{id}/units/start            multipart/form-data: unit_type, title, [file]
 *   POST   /workflow/classes/{id}/units/{uid}/close      close unit
 *   POST   /workflow/classes/{id}/units/{uid}/reopen     reopen closed unit
 *   DELETE /workflow/classes/{id}/units/{uid}            delete unit and linked sessions
 *   POST   /workflow/classes/{id}/sessions/start         JSON: {absent_student_ids:[]}
 *   POST   /workflow/classes/{id}/sessions/{sid}/end     JSON: {session_date,start_time,end_time,absent_student_ids,note}
 *   POST   /workflow/classes/{id}/sessions/{sid}/items/{iid}/toggle   JSON: {checked:bool}
 */
import { api, downloadWithAuth } from '../api/client.js';
import {
  getActiveUnit, getActiveSession, getClosedUnits, getRecentSessions,
  setActiveUnit, setActiveSession, setCalendar, setWorkspace,
  getAbsentIds, toggleAbsent,
} from '../state/workflow.js';
import { getSelectedId, getStudents } from '../state/class.js';
import { showToast } from '../utils/toast.js';
import { askConfirm } from '../utils/modal.js';
import { mountRetryCard } from '../utils/retryView.js';
import { fmtDate, fmtTime } from '../utils/format.js';
import { copyText } from '../utils/password.js';

let _activeTab = 0;
let _recentWindow = 'month';
let _selectedUnitType = 'chapter';
let _checklistCollapseUnitId = null;
const WORKFLOW_VIEW_INTENT_KEY = 'workflow_view_intent';
const CALENDAR_VIEW_INTENT_KEY = 'calendar_view_intent';
let _workflowEntryContext = null;
let _workflowPreviewScrollKey = null;
let _workflowPreviewFocusOnly = true;
let _workflowPreviewHideDone = false;
let _sessionGuidanceHideImported = false;
let _sessionGuidanceKindFilter = 'all';
let _sessionGuidanceCollapseImported = false;
let _sessionGuidanceStateSessionId = null;
let _workflowCollapsePlannedRoute = false;
let _workflowCollapseSessionProgress = false;
let _workflowCollapseSessionWriteup = false;
const _collapsedChecklistIds = new Set();
const _inFlightActions = new Set();
const _sessionProgressCache = new Map();
const _sessionWriteupCache = new Map();
const _unitSessionTimelineCache = new Map();
const _unitBlueprintCache = new Map();
const _unitAssistantArtifactCache = new Map();
const CHECKLIST_KINDS = ['chapter', 'section', 'subsection', 'property', 'definition', 'example', 'exercise', 'supervision', 'correction', 'other'];
const RECENT_SESSION_WINDOWS = [
  { key: 'today', label: 'Today' },
  { key: 'week', label: 'Week' },
  { key: 'month', label: 'Month' },
  { key: 'all', label: 'All' },
];
const EXTRACTION_APPLY_MODES = [
  { key: 'replace', label: 'Replace Existing Progress', hint: 'Delete current session progress and apply this review.' },
  { key: 'append', label: 'Append To Existing Progress', hint: 'Keep existing progress and add reviewed rows at the end.' },
];
const UNIT_TYPES = [
  { key: 'chapter', icon: 'CH', label: 'Chapter' },
  { key: 'exercise_series', icon: 'EX', label: 'Exercises' },
  { key: 'exam', icon: 'TE', label: 'Exam' },
  { key: 'exam_correction', icon: 'CR', label: 'Correction' },
];

function _consumeWorkflowViewIntent(expectedUnitId) {
  try {
    const raw = sessionStorage.getItem(WORKFLOW_VIEW_INTENT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const ageMs = Date.now() - Number(parsed?.created_at || 0);
    if (!parsed || typeof parsed !== 'object' || ageMs > 5 * 60 * 1000) {
      sessionStorage.removeItem(WORKFLOW_VIEW_INTENT_KEY);
      return null;
    }
    const intentUnitId = Number(parsed.unit_id || 0);
    if (!Number.isFinite(intentUnitId) || intentUnitId <= 0 || Number(intentUnitId) !== Number(expectedUnitId || 0)) {
      return null;
    }
    sessionStorage.removeItem(WORKFLOW_VIEW_INTENT_KEY);
    return {
      action: String(parsed.action || '').trim().toLowerCase(),
      unit_id: intentUnitId,
      unit_session_number: Number(parsed.unit_session_number || 0) || null,
      source: String(parsed.source || '').trim().toLowerCase(),
      session_id: Number(parsed.session_id || 0) || null,
      session_label: String(parsed.session_label || '').trim(),
      session_date: String(parsed.session_date || '').trim(),
      section_title: String(parsed.section_title || '').trim(),
      section_path: Array.isArray(parsed.section_path)
        ? parsed.section_path.map(value => String(value || '').trim()).filter(Boolean)
        : [],
      teacher_request: String(parsed.teacher_request || '').trim(),
      assistant_action: String(parsed.assistant_action || '').trim().toLowerCase(),
      preview_hide_done: Boolean(parsed.preview_hide_done),
    };
  } catch {
    try { sessionStorage.removeItem(WORKFLOW_VIEW_INTENT_KEY); } catch {}
    return null;
  }
}

function _peekWorkflowViewIntent() {
  try {
    const raw = sessionStorage.getItem(WORKFLOW_VIEW_INTENT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const ageMs = Date.now() - Number(parsed?.created_at || 0);
    if (!parsed || typeof parsed !== 'object' || ageMs > 5 * 60 * 1000) {
      sessionStorage.removeItem(WORKFLOW_VIEW_INTENT_KEY);
      return null;
    }
    const intentUnitId = Number(parsed.unit_id || 0);
    if (!Number.isFinite(intentUnitId) || intentUnitId <= 0) return null;
    return {
      action: String(parsed.action || '').trim().toLowerCase(),
      unit_id: intentUnitId,
      unit_session_number: Number(parsed.unit_session_number || 0) || null,
      source: String(parsed.source || '').trim().toLowerCase(),
      session_id: Number(parsed.session_id || 0) || null,
      session_label: String(parsed.session_label || '').trim(),
      session_date: String(parsed.session_date || '').trim(),
      section_title: String(parsed.section_title || '').trim(),
      section_path: Array.isArray(parsed.section_path)
        ? parsed.section_path.map(value => String(value || '').trim()).filter(Boolean)
        : [],
      teacher_request: String(parsed.teacher_request || '').trim(),
      assistant_action: String(parsed.assistant_action || '').trim().toLowerCase(),
      preview_hide_done: Boolean(parsed.preview_hide_done),
    };
  } catch {
    try { sessionStorage.removeItem(WORKFLOW_VIEW_INTENT_KEY); } catch {}
    return null;
  }
}

function _setCalendarViewIntent(intent) {
  try {
    sessionStorage.setItem(CALENDAR_VIEW_INTENT_KEY, JSON.stringify({
      ...intent,
      created_at: Date.now(),
    }));
  } catch {
    // Non-fatal. Navigation can still proceed without restored calendar context.
  }
}
const UNIT_ASSISTANT_ACTION_LABELS = {
  explain_section: 'Explain Section',
  generate_teacher_notes: 'Teacher Notes',
  generate_slides: 'Slide Outline',
  create_warmup_variant: 'Warm-up Variant',
  simplify_explanation: 'Simplify Explanation',
  generate_guided_examples: 'Guided Examples',
  generate_easier_practice: 'Easier Practice',
  generate_harder_practice: 'Harder Practice',
  generate_quick_quiz: 'Quick Quiz',
  generate_remediation: 'Remediation Support',
};

//    busy state helpers   
function _setBusy(btn, busy) {
  if (!btn) return;
  if (busy) {
    btn.classList.add('btn-busy');
    btn.disabled = true;
  } else {
    btn.classList.remove('btn-busy');
    btn.disabled = false;
  }
}
function _setLabelBusy(label, busy) {
  if (!label) return;
  if (busy) {
    label.classList.add('label-btn-busy');
    const inp = label.querySelector('input');
    if (inp) inp.disabled = true;
  } else {
    label.classList.remove('label-btn-busy');
    const inp = label.querySelector('input');
    if (inp) inp.disabled = false;
  }
}

function _coerceExtractionMode(value) {
  const mode = String(value || 'replace').trim().toLowerCase();
  return EXTRACTION_APPLY_MODES.some(row => row.key === mode) ? mode : 'replace';
}

function _emptySessionProgressState() {
  return { loading: false, loaded: false, error: null, items: [] };
}

function _emptySessionWriteupState() {
  return { loading: false, loaded: false, error: null, item: null };
}

function _getSessionProgressState(sessionId) {
  const sid = Number(sessionId);
  if (!Number.isFinite(sid) || sid <= 0) return _emptySessionProgressState();
  return _sessionProgressCache.get(sid) || _emptySessionProgressState();
}

function _getSessionWriteupState(sessionId) {
  const sid = Number(sessionId);
  if (!Number.isFinite(sid) || sid <= 0) return _emptySessionWriteupState();
  return _sessionWriteupCache.get(sid) || _emptySessionWriteupState();
}

function _setSessionProgressState(sessionId, state) {
  const sid = Number(sessionId);
  if (!Number.isFinite(sid) || sid <= 0) return _emptySessionProgressState();
  const next = {
    loading: Boolean(state?.loading),
    loaded: Boolean(state?.loaded),
    error: state?.error ? String(state.error) : null,
    items: Array.isArray(state?.items) ? state.items : [],
  };
  _sessionProgressCache.set(sid, next);
  return next;
}

function _setSessionWriteupState(sessionId, state) {
  const sid = Number(sessionId);
  if (!Number.isFinite(sid) || sid <= 0) return _emptySessionWriteupState();
  const next = {
    loading: Boolean(state?.loading),
    loaded: Boolean(state?.loaded),
    error: state?.error ? String(state.error) : null,
    item: state?.item && typeof state.item === 'object' ? { ...state.item } : null,
  };
  _sessionWriteupCache.set(sid, next);
  return next;
}

function _normalizeSectionPathKey(values) {
  return Array.isArray(values)
    ? values.map(value => String(value || '').trim().toLowerCase()).filter(Boolean).join(' > ')
    : '';
}

async function _loadUnitAssistantArtifacts(classId, unitId, { force = false } = {}) {
  const cacheKey = `${Number(classId || 0)}:${Number(unitId || 0)}`;
  if (!force && _unitAssistantArtifactCache.has(cacheKey)) {
    return _unitAssistantArtifactCache.get(cacheKey) || [];
  }
  const rows = await api(`/workflow/classes/${classId}/units/${unitId}/assistant/artifacts`);
  const safeRows = Array.isArray(rows) ? rows : [];
  _unitAssistantArtifactCache.set(cacheKey, safeRows);
  return safeRows;
}

function _filterAssistantArtifactsForSection(artifacts, sectionPlan, fallbackTitle = '') {
  const safeRows = Array.isArray(artifacts) ? artifacts : [];
  const targetTitle = String(sectionPlan?.section_title || fallbackTitle || '').trim().toLowerCase();
  const targetPathKey = _normalizeSectionPathKey(sectionPlan?.section_path);
  return safeRows.filter(item => {
    const itemTitle = String(item?.section_title || '').trim().toLowerCase();
    if (targetTitle && itemTitle === targetTitle) return true;
    const itemPathKey = _normalizeSectionPathKey(item?.section_path);
    return Boolean(targetPathKey) && itemPathKey === targetPathKey;
  });
}

function _sortAssistantArtifactsForTeaching(items) {
  const kindRank = {
    teacher_notes: 0,
    guided_practice: 1,
    quick_quiz_draft: 2,
  };
  const safeRows = Array.isArray(items) ? [...items] : [];
  return safeRows.sort((a, b) => {
    const aKind = String(a?.artifact_kind || '').trim().toLowerCase();
    const bKind = String(b?.artifact_kind || '').trim().toLowerCase();
    const kindDiff = Number(kindRank[aKind] ?? 99) - Number(kindRank[bKind] ?? 99);
    if (kindDiff !== 0) return kindDiff;
    const aUpdated = Date.parse(String(a?.updated_at || a?.created_at || '')) || 0;
    const bUpdated = Date.parse(String(b?.updated_at || b?.created_at || '')) || 0;
    if (aUpdated !== bUpdated) return bUpdated - aUpdated;
    return String(a?.title || '').localeCompare(String(b?.title || ''));
  });
}

function _filterAssistantArtifactsForPlannedTitles(artifacts, unitMap, plannedTitles) {
  const safeRows = Array.isArray(artifacts) ? artifacts : [];
  const titleKeys = new Set((Array.isArray(plannedTitles) ? plannedTitles : []).map(value => String(value || '').trim().toLowerCase()).filter(Boolean));
  const pathKeys = new Set();
  const sectionPlans = Array.isArray(unitMap?.section_plans) ? unitMap.section_plans.filter(Boolean) : [];
  sectionPlans.forEach(plan => {
    const sectionTitle = String(plan?.section_title || '').trim().toLowerCase();
    const delivery = Array.isArray(plan?.delivery_sequence) ? plan.delivery_sequence.map(value => String(value || '').trim().toLowerCase()).filter(Boolean) : [];
    const matched = (sectionTitle && titleKeys.has(sectionTitle)) || delivery.some(value => titleKeys.has(value));
    if (matched) {
      const pathKey = _normalizeSectionPathKey(plan?.section_path);
      if (pathKey) pathKeys.add(pathKey);
    }
  });
  return _sortAssistantArtifactsForTeaching(safeRows.filter(item => {
    const itemTitle = String(item?.section_title || '').trim().toLowerCase();
    if (itemTitle && titleKeys.has(itemTitle)) return true;
    const itemPathKey = _normalizeSectionPathKey(item?.section_path);
    return itemPathKey ? pathKeys.has(itemPathKey) : false;
  }));
}

function _filterAssistantArtifactsForRouteContext(artifacts, unitMap, routeTitles, routeSectionPaths = []) {
  const safeRows = Array.isArray(artifacts) ? artifacts : [];
  const titleKeys = new Set((Array.isArray(routeTitles) ? routeTitles : []).map(value => String(value || '').trim().toLowerCase()).filter(Boolean));
  const pathKeys = new Set();
  const sectionPlans = Array.isArray(unitMap?.section_plans) ? unitMap.section_plans.filter(Boolean) : [];
  (Array.isArray(routeSectionPaths) ? routeSectionPaths : []).forEach(path => {
    const key = _normalizeSectionPathKey(path);
    if (key) pathKeys.add(key);
  });
  sectionPlans.forEach(plan => {
    const sectionTitle = String(plan?.section_title || '').trim().toLowerCase();
    const delivery = Array.isArray(plan?.delivery_sequence) ? plan.delivery_sequence.map(value => String(value || '').trim().toLowerCase()).filter(Boolean) : [];
    const matched = (sectionTitle && titleKeys.has(sectionTitle)) || delivery.some(value => titleKeys.has(value));
    if (matched) {
      const pathKey = _normalizeSectionPathKey(plan?.section_path);
      if (pathKey) pathKeys.add(pathKey);
    }
  });
  return _sortAssistantArtifactsForTeaching(safeRows.filter(item => {
    const itemTitle = String(item?.section_title || '').trim().toLowerCase();
    if (itemTitle && titleKeys.has(itemTitle)) return true;
    const itemPathKey = _normalizeSectionPathKey(item?.section_path);
    return itemPathKey ? pathKeys.has(itemPathKey) : false;
  }));
}

function _artifactDownloadFilename(item, fallbackTitle = '') {
  const base = String(item?.title || fallbackTitle || 'saved-guidance')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'saved-guidance';
  return `${base}.md`;
}

function _renderSavedGuidancePreviewRows(items, fallbackTitle = '') {
  const visible = Array.isArray(items) ? items.slice(0, 3) : [];
  if (!visible.length) {
    return '<p class="text-[12px] text-slate-600 mt-3">No saved guidance has been kept for this exact teaching focus yet.</p>';
  }
  return `
    <div class="mt-3 flex flex-col gap-2">
      <p class="text-[11px] font-semibold text-amber-800 uppercase tracking-wider">Saved guidance for this focus</p>
      ${visible.map(item => `
        <div class="rounded-xl border border-amber-200 bg-white px-3 py-3">
          <div class="flex items-center justify-between gap-3 flex-wrap">
            <div class="flex items-center gap-2 flex-wrap">
              <p class="text-[12px] font-semibold text-slate-800">${_escapeHtml(String(item?.title || fallbackTitle || 'Saved guidance'))}</p>
              <span class="badge badge-blue">${_escapeHtml(_assistantArtifactKindLabel(item?.artifact_kind))}</span>
              ${item?.action ? `<span class="badge badge-gray">${_escapeHtml(_assistantActionLabel(item.action))}</span>` : ''}
            </div>
            <div class="flex items-center gap-2">
              <button class="btn btn-ghost btn-sm btn-preview-guidance-copy" data-artifact-id="${_escapeHtml(String(item?.id || ''))}">Copy</button>
              <button class="btn btn-secondary btn-sm btn-preview-guidance-download" data-artifact-id="${_escapeHtml(String(item?.id || ''))}">Download</button>
            </div>
          </div>
          ${item?.content_markdown ? `<p class="text-[12px] text-slate-600 leading-6 mt-2">${_escapeHtml(String(item.content_markdown).split('\n').slice(0, 3).join(' '))}</p>` : ''}
        </div>
      `).join('')}
      ${Array.isArray(items) && items.length > visible.length
        ? `<p class="text-[11px] text-amber-700">Showing ${visible.length} of ${items.length} saved guidance item${items.length === 1 ? '' : 's'} for this focus.</p>`
        : ''}
    </div>
  `;
}

function _renderSessionMatchedGuidance(items, { canImport = false, importedIds = new Set(), hideImported = false, kindFilter = 'all' } = {}) {
  const source = Array.isArray(items) ? items : [];
  const filtered = source.filter(item => {
    const imported = importedIds.has(Number(item?.id || 0));
    if (hideImported && imported) return false;
    const itemKind = String(item?.artifact_kind || 'teacher_notes').trim().toLowerCase() || 'teacher_notes';
    if (kindFilter && kindFilter !== 'all' && itemKind !== kindFilter) return false;
    return true;
  });
  const sorted = filtered.slice().sort((a, b) => {
    const aImported = importedIds.has(Number(a?.id || 0)) ? 1 : 0;
    const bImported = importedIds.has(Number(b?.id || 0)) ? 1 : 0;
    if (aImported !== bImported) return aImported - bImported;
    return 0;
  });
  const visible = sorted.slice(0, 4);
  if (!visible.length) {
    if (hideImported && source.length) {
      return '<p class="text-[12px] text-slate-500">All matching saved guidance has already been imported. Use <span class="font-semibold">Show Imported</span> if you want to review it again.</p>';
    }
    if (kindFilter && kindFilter !== 'all' && source.length) {
      return '<p class="text-[12px] text-slate-500">No matching saved guidance is available for this type filter right now. Switch back to <span class="font-semibold">All</span> to review everything.</p>';
    }
    return '<p class="text-[12px] text-slate-500">No saved guidance matches this session route yet. Save a good result from Ask This Unit to reuse it here.</p>';
  }
  const visibleRemaining = visible.filter(item => !importedIds.has(Number(item?.id || 0)));
  const visibleImported = visible.filter(item => importedIds.has(Number(item?.id || 0)));
  const remainingCount = sorted.filter(item => !importedIds.has(Number(item?.id || 0))).length;
  const importedCount = sorted.filter(item => importedIds.has(Number(item?.id || 0))).length;
  const showGroupedSections = Boolean(visibleRemaining.length && visibleImported.length && !hideImported);
  const renderRows = rows => rows.map(item => {
    const artifactId = Number(item?.id || 0);
    const imported = importedIds.has(artifactId);
    return `
        <div class="rounded-2xl border border-slate-200 bg-white px-3 py-3">
          <div class="flex items-start justify-between gap-3 flex-wrap">
            <div class="min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <p class="text-[12px] font-semibold text-slate-800">${_escapeHtml(String(item?.title || 'Saved guidance'))}</p>
                ${imported ? '<span class="badge badge-green">Imported</span>' : ''}
              </div>
              <p class="mt-1 text-[11px] text-slate-500">${_escapeHtml(_assistantArtifactKindLabel(item?.artifact_kind))}${item?.action ? ` - ${_escapeHtml(_assistantActionLabel(item.action))}` : ''}</p>
            </div>
            <div class="flex items-center gap-2 flex-wrap">
              ${canImport ? `<button class="btn btn-primary btn-sm btn-session-matched-guidance-import" data-artifact-id="${_escapeHtmlAttr(String(item?.id || ''))}" ${imported ? 'disabled' : ''}>${imported ? 'Already Imported' : 'Use in Write-Up'}</button>` : ''}
              <button class="btn btn-ghost btn-sm btn-session-matched-guidance-copy" data-artifact-id="${_escapeHtmlAttr(String(item?.id || ''))}">Copy</button>
              <button class="btn btn-secondary btn-sm btn-session-matched-guidance-download" data-artifact-id="${_escapeHtmlAttr(String(item?.id || ''))}">Download</button>
            </div>
          </div>
          ${item?.content_markdown ? `<p class="text-[12px] text-slate-600 leading-6 mt-2">${_escapeHtml(String(item.content_markdown).split('\n').slice(0, 3).join(' '))}</p>` : ''}
        </div>
      `;
  }).join('');
  return `
    <div class="flex flex-col gap-2">
      ${showGroupedSections ? `<p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Ready to reuse (${remainingCount})</p>` : ''}
      ${renderRows(showGroupedSections ? visibleRemaining : visible)}
      ${showGroupedSections ? `
        <div class="flex items-center justify-between gap-2 pt-1">
          <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Already imported (${importedCount})</p>
          <button id="btn-session-guidance-collapse-imported-toggle" class="btn btn-ghost btn-sm">${_sessionGuidanceCollapseImported ? `Show Imported (${importedCount})` : `Hide Imported (${importedCount})`}</button>
        </div>
        ${_sessionGuidanceCollapseImported ? `<p class="text-[11px] text-slate-500">${importedCount} imported guidance item${importedCount === 1 ? '' : 's'} hidden for a cleaner review.</p>` : renderRows(visibleImported)}
      ` : ''}
      ${sorted.length > visible.length
        ? `<p class="text-[11px] text-slate-500">Showing ${visible.length} of ${sorted.length} matching saved guidance items${hideImported ? ' still available to import' : ''}.</p>`
        : ''}
    </div>
  `;
}

function _renderSessionGuidanceSummary(totalCount, importedCount, hideImported = false) {
  const total = Number(totalCount || 0);
  const imported = Number(importedCount || 0);
  const remaining = Math.max(0, total - imported);
  if (!total) return '';
  return `
    <div class="mt-2 flex flex-wrap gap-2">
      <span class="badge badge-gray">${remaining} remaining</span>
      <span class="badge badge-gray">${imported} imported</span>
      <span class="badge badge-gray">${total} total</span>
      ${hideImported ? '<span class="badge badge-amber">Remaining only</span>' : ''}
    </div>
  `;
}

function _hasSessionGuidanceFilters(hideImported = false, kindFilter = 'all') {
  return Boolean(hideImported) || (String(kindFilter || 'all').trim().toLowerCase() !== 'all');
}

function _renderSessionGuidanceKindFilters(items, activeKind = 'all') {
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) return '';
  const summary = _summarizeRemainingGuidanceKinds(rows);
  if (summary.length <= 1) return '';
  return `
    <div class="mt-2 flex flex-wrap gap-2">
      <button class="btn btn-ghost btn-sm btn-session-guidance-kind-toggle ${activeKind === 'all' ? 'btn-primary' : ''}" data-guidance-kind="all">All</button>
      ${summary.map(([kind, count]) => `
        <button
          class="btn btn-ghost btn-sm btn-session-guidance-kind-toggle ${activeKind === kind ? 'btn-primary' : ''}"
          data-guidance-kind="${_escapeHtmlAttr(kind)}"
        >${_escapeHtml(_assistantArtifactKindLabel(kind))} (${count})</button>
      `).join('')}
    </div>
  `;
}

function _renderGuidanceQuickPickButtons(items, prefix) {
  const visible = Array.isArray(items) ? items.slice(0, 2) : [];
  if (!visible.length) return '';
  return `
    <div class="mt-3 flex flex-wrap gap-2">
      ${visible.map(item => `
        <button
          id="${_escapeHtmlAttr(`${prefix}-${Number(item?.id || 0)}`)}"
          class="btn btn-ghost btn-sm btn-guidance-quick-pick"
          data-artifact-id="${_escapeHtmlAttr(String(item?.id || ''))}"
        >${_escapeHtml(_assistantArtifactKindLabel(item?.artifact_kind))}: ${_escapeHtml(String(item?.title || 'Saved guidance'))}</button>
      `).join('')}
    </div>
  `;
}

function _renderGuidanceKindImportButtons(items, prefix) {
  const summary = _summarizeRemainingGuidanceKinds(items);
  if (summary.length <= 1) return '';
  return `
    <div class="mt-2 flex flex-wrap gap-2">
      ${summary.map(([kind, count]) => `
        <button
          id="${_escapeHtmlAttr(`${prefix}-${kind}`)}"
          class="btn btn-ghost btn-sm btn-guidance-kind-import"
          data-artifact-kind="${_escapeHtmlAttr(kind)}"
        >Import ${_escapeHtml(_assistantArtifactKindLabel(kind))} (${count})</button>
      `).join('')}
    </div>
  `;
}

function _getImportedAssistantArtifactIds(writeup) {
  const meta = _normalizeWriteupSourcePayload(writeup?.source_payload);
  return new Set((meta?.importedAssistantArtifacts || []).map(item => Number(item?.artifactId || 0)).filter(Boolean));
}

async function _hydratePreviewSavedGuidance(container, { classId, unitId, sectionPlan, fallbackTitle = '' } = {}) {
  if (!container || !classId || !unitId) return;
  container.innerHTML = '<p class="text-[12px] text-amber-700 mt-3">Loading saved guidance…</p>';
  try {
    const artifacts = await _loadUnitAssistantArtifacts(classId, unitId);
    const matches = _filterAssistantArtifactsForSection(artifacts, sectionPlan, fallbackTitle);
    container.innerHTML = _renderSavedGuidancePreviewRows(matches, fallbackTitle);
    container.querySelectorAll('.btn-preview-guidance-copy').forEach(button => {
      button.addEventListener('click', async () => {
        const artifactId = Number(button.dataset.artifactId || 0);
        const item = matches.find(row => Number(row?.id || 0) === artifactId);
        if (!item?.content_markdown) return;
        try {
          await copyText(String(item.content_markdown));
          showToast('Saved guidance copied.', 'ok');
        } catch {
          showToast('Failed to copy saved guidance.', 'error');
        }
      });
    });
    container.querySelectorAll('.btn-preview-guidance-download').forEach(button => {
      button.addEventListener('click', () => {
        const artifactId = Number(button.dataset.artifactId || 0);
        const item = matches.find(row => Number(row?.id || 0) === artifactId);
        if (!item?.content_markdown) return;
        _downloadTextContent(String(item.content_markdown), _artifactDownloadFilename(item, fallbackTitle));
      });
    });
  } catch (err) {
    container.innerHTML = `<p class="text-[12px] text-red-600 mt-3">${_escapeHtml(String(err?.message || 'Failed to load saved guidance.'))}</p>`;
  }
}

function _emptyUnitTimelineState() {
  return { loading: false, loaded: false, error: null, sessions: [], signature: '' };
}

function _emptyUnitBlueprintState() {
  return { loading: false, loaded: false, error: null, item: null };
}

function _getUnitTimelineState(unitId) {
  const uid = Number(unitId);
  if (!Number.isFinite(uid) || uid <= 0) return _emptyUnitTimelineState();
  return _unitSessionTimelineCache.get(uid) || _emptyUnitTimelineState();
}

function _buildUnitTimelineSignature(unitId) {
  const uid = Number(unitId);
  if (!Number.isFinite(uid) || uid <= 0) return '';
  const rows = (Array.isArray(getRecentSessions()) ? getRecentSessions() : [])
    .filter(row => Number(row?.unit_id) === uid)
    .map(row => `${Number(row?.id || 0)}:${String(row?.end_time || '')}:${Number(row?.checked_items_count || 0)}:${Number(row?.absent_count || 0)}`)
    .sort();
  return rows.join('|');
}

function _sortUnitTimelineSessions(rows) {
  return rows.sort((a, b) => {
    const aNum = Number(a?.unit_session_number || 0);
    const bNum = Number(b?.unit_session_number || 0);
    if (aNum > 0 && bNum > 0 && aNum !== bNum) return aNum - bNum;
    const aDate = _toLocalDate(a?.session_date || a?.date);
    const bDate = _toLocalDate(b?.session_date || b?.date);
    const aTime = aDate?.getTime() || 0;
    const bTime = bDate?.getTime() || 0;
    if (aTime !== bTime) return aTime - bTime;
    const aStart = _toTimeInputValue(a?.start_time || '99:99');
    const bStart = _toTimeInputValue(b?.start_time || '99:99');
    if (aStart !== bStart) return aStart.localeCompare(bStart);
    return Number(a?.id || 0) - Number(b?.id || 0);
  });
}

function _setUnitTimelineState(unitId, state) {
  const uid = Number(unitId);
  if (!Number.isFinite(uid) || uid <= 0) return _emptyUnitTimelineState();
  const next = {
    loading: Boolean(state?.loading),
    loaded: Boolean(state?.loaded),
    error: state?.error ? String(state.error) : null,
    sessions: _sortUnitTimelineSessions(
      Array.isArray(state?.sessions)
        ? state.sessions.map(row => ({ ...row }))
        : []
    ),
    signature: state?.signature == null ? '' : String(state.signature),
  };
  _unitSessionTimelineCache.set(uid, next);
  return next;
}

function _getUnitBlueprintState(unitId) {
  const uid = Number(unitId);
  if (!Number.isFinite(uid) || uid <= 0) return _emptyUnitBlueprintState();
  return _unitBlueprintCache.get(uid) || _emptyUnitBlueprintState();
}

function _setUnitBlueprintState(unitId, state) {
  const uid = Number(unitId);
  if (!Number.isFinite(uid) || uid <= 0) return _emptyUnitBlueprintState();
  const next = {
    loading: Boolean(state?.loading),
    loaded: Boolean(state?.loaded),
    error: state?.error ? String(state.error) : null,
    item: state?.item && typeof state.item === 'object' ? { ...state.item } : null,
  };
  _unitBlueprintCache.set(uid, next);
  return next;
}

async function _loadUnitBlueprint(classId, unitId, { force = false } = {}) {
  const uid = Number(unitId);
  if (!Number.isFinite(uid) || uid <= 0) return _emptyUnitBlueprintState();
  const existing = _getUnitBlueprintState(uid);
  if (existing.loading) return existing;
  if (!force && existing.loaded) return existing;

  _setUnitBlueprintState(uid, {
    loading: true,
    loaded: false,
    error: null,
    item: existing.item,
  });

  try {
    const row = await api(`/workflow/classes/${classId}/units/${uid}/blueprint`);
    return _setUnitBlueprintState(uid, {
      loading: false,
      loaded: true,
      error: null,
      item: row || null,
    });
  } catch (err) {
    return _setUnitBlueprintState(uid, {
      loading: false,
      loaded: true,
      error: String(err?.message || 'Failed to load AI extraction details.'),
      item: existing.item,
    });
  }
}

async function _loadUnitTimeline(unitId, { force = false } = {}) {
  const uid = Number(unitId);
  if (!Number.isFinite(uid) || uid <= 0) return _emptyUnitTimelineState();
  const existing = _getUnitTimelineState(uid);
  if (existing.loading) return existing;
  if (!force && existing.loaded) return existing;

  _setUnitTimelineState(uid, {
    loading: true,
    loaded: false,
    error: null,
    sessions: existing.sessions,
    signature: existing.signature,
  });

  try {
    const rows = await api(`/workflow/units/${uid}/sessions`);
    return _setUnitTimelineState(uid, {
      loading: false,
      loaded: true,
      error: null,
      sessions: Array.isArray(rows) ? rows : [],
      signature: _buildUnitTimelineSignature(uid),
    });
  } catch (err) {
    return _setUnitTimelineState(uid, {
      loading: false,
      loaded: true,
      error: String(err?.message || 'Failed to load unit sessions.'),
      sessions: existing.sessions,
      signature: existing.signature,
    });
  }
}

function _prettyJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value ?? '');
  }
}

function _renderBlueprintTree(nodes, depth = 0) {
  if (!Array.isArray(nodes) || !nodes.length) {
    return depth === 0
      ? '<p class="text-[12px] text-slate-500">No parsed checklist tree saved for this unit.</p>'
      : '';
  }
  const listClass = depth === 0
    ? 'space-y-1.5'
    : 'space-y-1.5 ml-4 mt-2 border-l border-slate-200 pl-3';
  return `
    <ul class="${listClass}">
      ${nodes.map(node => `
        <li>
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-[13px] text-slate-700">${_escapeHtml(node?.title || '')}</span>
            ${node?.kind ? `<span class="badge badge-gray">${_escapeHtml(String(node.kind))}</span>` : ''}
            ${node?.session_number ? `<span class="badge badge-blue">S${Number(node.session_number)}</span>` : ''}
          </div>
          ${_renderBlueprintTree(node?.children || [], depth + 1)}
        </li>
      `).join('')}
    </ul>`;
}

function _openUnitBlueprintModal(unit, blueprint, classId) {
  const provider = String(blueprint?.provider || unit?.extraction_source || 'unknown');
  const model = String(blueprint?.model || unit?.extraction_model || '').trim();
  const status = String(blueprint?.status || unit?.extraction_status || '').trim();
  const errorMessage = String(blueprint?.error_message || unit?.extraction_error || '').trim();
  const reviewed = blueprint?.reviewed !== false;
  const reviewedAt = blueprint?.reviewed_at || unit?.extraction_reviewed_at || null;
  const blueprintJson = blueprint?.blueprint_json && typeof blueprint.blueprint_json === 'object' ? blueprint.blueprint_json : {};
  const unitMap = blueprint?.unit_map_json && typeof blueprint.unit_map_json === 'object' ? blueprint.unit_map_json : {};
  const contentBlocks = Array.isArray(blueprint?.content_blocks_json) ? blueprint.content_blocks_json.filter(Boolean) : [];
  const rawPackage = blueprint?.raw_provider_response && typeof blueprint.raw_provider_response === 'object'
    ? blueprint.raw_provider_response
    : {};
  const rawProviderPayload = rawPackage?.raw_provider_response && typeof rawPackage.raw_provider_response === 'object'
    ? rawPackage.raw_provider_response
    : {};
  const providerContext = blueprintJson?.provider_context && typeof blueprintJson.provider_context === 'object'
    ? blueprintJson.provider_context
    : {};
  const responses = Array.isArray(rawProviderPayload?.responses) ? rawProviderPayload.responses : [];
  const selectedVariant = String(rawProviderPayload?.selected_variant || '').trim();
  const responseMode = String(rawProviderPayload?.response_mode || '').trim();
  const sourceIds = Array.isArray(providerContext?.source_ids) ? providerContext.source_ids : [];
  const selectedStructureSource = String(rawProviderPayload?.selected_structure_source || unitMap?.selected_outline_source || '').trim();
  const unitMapOutline = Array.isArray(unitMap?.ordered_outline) ? unitMap.ordered_outline : [];
  const sectionPlans = Array.isArray(unitMap?.section_plans) ? unitMap.section_plans.filter(Boolean) : [];
  const teacherPlaybook = Array.isArray(unitMap?.teacher_playbook) ? unitMap.teacher_playbook.filter(Boolean) : [];
  const materialStudio = unitMap?.material_studio && typeof unitMap.material_studio === 'object' ? unitMap.material_studio : {};
  const renderMapList = (title, rows) => {
    const values = Array.isArray(rows) ? rows.filter(Boolean) : [];
    if (!values.length) return '';
    return `
      <div>
        <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1">${_escapeHtml(title)}</p>
        <ul class="list-disc pl-5 text-[12px] text-slate-700 space-y-1">
          ${values.map(value => `<li>${_escapeHtml(String(value || ''))}</li>`).join('')}
        </ul>
      </div>
    `;
  };
  const renderSectionPlans = plans => {
    const values = Array.isArray(plans) ? plans.filter(Boolean) : [];
    if (!values.length) {
      return '<p class="text-[12px] text-slate-500">No reusable section plans were derived from this unit yet.</p>';
    }
    return values.map(plan => `
      <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
        <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(plan?.section_title || 'Section'))}</p>
        ${Array.isArray(plan?.delivery_sequence) && plan.delivery_sequence.length ? `
          <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mt-2 mb-1">Delivery sequence</p>
          <ol class="list-decimal pl-5 text-[12px] text-slate-700 space-y-1">
            ${plan.delivery_sequence.map(value => `<li>${_escapeHtml(String(value || ''))}</li>`).join('')}
          </ol>
        ` : ''}
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4 mt-3">
          ${renderMapList('Activities', plan?.activity_titles)}
          ${renderMapList('Content blocks', plan?.content_titles)}
          ${renderMapList('Examples', plan?.example_titles)}
          ${renderMapList('Exercises', plan?.exercise_titles)}
        </div>
        ${Array.isArray(plan?.blocks) && plan.blocks.length ? `
          <div class="mt-4 border-t border-slate-200 pt-3">
            <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">Saved teaching blocks</p>
            <div class="space-y-2">
              ${plan.blocks.map(block => `
                <div class="rounded-lg border border-slate-200 bg-white px-3 py-2">
                  <div class="flex gap-2 flex-wrap items-center">
                    <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(block?.title || 'Block'))}</p>
                    ${block?.kind ? `<span class="badge badge-gray">${_escapeHtml(String(block.kind))}</span>` : ''}
                  </div>
                  ${block?.teaching_material ? `<p class="text-[12px] text-slate-700 leading-6 mt-2">${_escapeHtml(String(block.teaching_material || ''))}</p>` : ''}
                  ${block?.source_excerpt ? `<p class="text-[11px] text-slate-500 leading-5 mt-2"><span class="font-semibold">Source:</span> ${_escapeHtml(String(block.source_excerpt || ''))}</p>` : ''}
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}
      </div>
    `).join('');
  };
  const renderContentBlocks = rows => {
    const values = Array.isArray(rows) ? rows.filter(Boolean) : [];
    if (!values.length) {
      return '<p class="text-[12px] text-slate-500">No saved content blocks were generated for this unit yet.</p>';
    }
    return values.map(row => `
      <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
        <div class="flex gap-2 flex-wrap items-center">
          <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(row?.title || 'Bloc'))}</p>
          ${row?.kind ? `<span class="badge badge-gray">${_escapeHtml(String(row.kind))}</span>` : ''}
          ${row?.teaching_phase ? `<span class="badge badge-blue">${_escapeHtml(String(row.teaching_phase))}</span>` : ''}
          ${row?.student_visible === false ? '<span class="badge badge-amber">Teacher only</span>' : '<span class="badge badge-green">Student-visible</span>'}
        </div>
        <p class="text-[11px] text-slate-500 mt-1"><span class="font-semibold">Section:</span> ${_escapeHtml(String(row?.section_title || '-'))}</p>
        ${Array.isArray(row?.section_path) && row.section_path.length ? `<p class="text-[11px] text-slate-500 mt-1"><span class="font-semibold">Path:</span> ${_escapeHtml(row.section_path.join(' -> '))}</p>` : ''}
        ${row?.source_excerpt ? `<div class="mt-3">
          <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1">Source excerpt</p>
          <p class="text-[12px] text-slate-700 leading-6">${_escapeHtml(String(row.source_excerpt || ''))}</p>
        </div>` : ''}
        ${row?.teaching_material ? `<div class="mt-3">
          <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1">Teaching material</p>
          <p class="text-[12px] text-slate-700 leading-6">${_escapeHtml(String(row.teaching_material || ''))}</p>
        </div>` : ''}
      </div>
    `).join('');
  };
  const renderTeacherPlaybook = rows => {
    const values = Array.isArray(rows) ? rows.filter(Boolean) : [];
    if (!values.length) {
      return '<p class="text-[12px] text-slate-500">No teacher playbook was derived for this unit yet.</p>';
    }
    return values.map(row => `
      <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
        <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(row?.section_title || 'Section'))}</p>
        ${Array.isArray(row?.section_path) && row.section_path.length ? `<p class="text-[11px] text-slate-500 mt-1"><span class="font-semibold">Path:</span> ${_escapeHtml(row.section_path.join(' -> '))}</p>` : ''}
        ${renderMapList('Available actions', row?.available_actions)}
        ${renderMapList('Suggested requests', row?.suggested_requests)}
      </div>
    `).join('');
  };
  const renderMaterialStudio = studio => {
    const unitArtifacts = Array.isArray(studio?.unit_artifacts) ? studio.unit_artifacts.filter(Boolean) : [];
    const teacherArtifacts = Array.isArray(studio?.teacher_artifacts) ? studio.teacher_artifacts.filter(Boolean) : [];
    if (!unitArtifacts.length && !teacherArtifacts.length) {
      return '<p class="text-[12px] text-slate-500">No NotebookLM material studio plan was derived for this unit yet.</p>';
    }
    return `
      ${unitArtifacts.length ? `
        <div>
          <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">Unit-level artifacts</p>
          <div class="space-y-3">
            ${unitArtifacts.map(row => `
              <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
                <div class="flex items-center gap-2 flex-wrap">
                  <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(row?.title || 'Artifact'))}</p>
                  ${row?.artifact_type ? `<span class="badge badge-blue">${_escapeHtml(String(row.artifact_type))}</span>` : ''}
                  ${row?.notebooklm_method ? `<span class="badge badge-gray">${_escapeHtml(String(row.notebooklm_method))}</span>` : ''}
                </div>
                ${row?.purpose ? `<p class="text-[12px] text-slate-700 mt-2">${_escapeHtml(String(row.purpose || ''))}</p>` : ''}
                ${row?.when_to_use ? `<p class="text-[11px] text-slate-500 mt-2"><span class="font-semibold">When to use:</span> ${_escapeHtml(String(row.when_to_use || ''))}</p>` : ''}
                ${row?.instructions ? `<p class="text-[11px] text-slate-500 mt-2"><span class="font-semibold">Generation instructions:</span> ${_escapeHtml(String(row.instructions || ''))}</p>` : ''}
                ${row?.options && typeof row.options === 'object' && Object.keys(row.options).length ? `
                  <p class="text-[11px] text-slate-500 mt-2"><span class="font-semibold">Options:</span> ${_escapeHtml(Object.entries(row.options).map(([key, value]) => `${key}=${value}`).join(', '))}</p>
                ` : ''}
              </div>
            `).join('')}
          </div>
        </div>
      ` : ''}
      ${teacherArtifacts.length ? `
        <div class="mt-4">
          <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">Section-level teaching paths</p>
          <div class="space-y-3">
            ${teacherArtifacts.map(row => `
              <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
                <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(row?.section_title || 'Section'))}</p>
                ${Array.isArray(row?.section_path) && row.section_path.length ? `<p class="text-[11px] text-slate-500 mt-1"><span class="font-semibold">Path:</span> ${_escapeHtml(row.section_path.join(' -> '))}</p>` : ''}
                ${renderMapList('Best actions', row?.best_actions)}
                ${renderMapList('Suggested requests', row?.suggested_requests)}
                ${row?.recommended_next_step ? `<p class="text-[11px] text-slate-500 mt-2"><span class="font-semibold">Recommended next step:</span> ${_escapeHtml(String(row.recommended_next_step || ''))}</p>` : ''}
              </div>
            `).join('')}
          </div>
        </div>
      ` : ''}
    `;
  };
  const renderSavedGuidanceLibrary = rows => {
    const values = Array.isArray(rows) ? rows.filter(Boolean) : [];
    if (!values.length) {
      return '<p class="text-[12px] text-slate-500">No saved guidance has been kept for this unit yet.</p>';
    }
    return values.map(row => `
      <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
        <div class="flex items-center justify-between gap-3 flex-wrap">
          <div class="flex items-center gap-2 flex-wrap">
            <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(row?.title || 'Saved guidance'))}</p>
            <span class="badge badge-blue">${_escapeHtml(_assistantArtifactKindLabel(row?.artifact_kind))}</span>
            ${row?.action ? `<span class="badge badge-gray">${_escapeHtml(_assistantActionLabel(row.action))}</span>` : ''}
          </div>
          <button class="btn btn-secondary btn-sm btn-blueprint-artifact-download" data-artifact-id="${_escapeHtml(String(row?.id || ''))}">
            Download
          </button>
        </div>
        ${row?.section_title ? `<p class="text-[11px] text-slate-500 mt-2"><span class="font-semibold">Section:</span> ${_escapeHtml(String(row.section_title || ''))}</p>` : ''}
        ${Array.isArray(row?.section_path) && row.section_path.length ? `<p class="text-[11px] text-slate-500 mt-1"><span class="font-semibold">Path:</span> ${_escapeHtml(row.section_path.join(' -> '))}</p>` : '' }
        ${row?.content_markdown ? `<p class="text-[12px] text-slate-700 leading-6 mt-3">${_escapeHtml(String(row.content_markdown).split('\n').slice(0, 4).join(' '))}</p>` : ''}
        <p class="text-[11px] text-slate-500 mt-3"><span class="font-semibold">Updated:</span> ${_escapeHtml(fmtDateTime(row?.updated_at))}</p>
      </div>
    `).join('');
  };

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal max-w-5xl w-[96vw]">
      <div class="px-6 py-5 border-b border-slate-100">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-[17px] font-bold text-slate-800">AI Extraction Details</h2>
            <p class="text-[12px] text-slate-500 mt-1">
              This shows what was saved for this unit when the checklist was generated.
            </p>
          </div>
          <button id="unit-blueprint-close-top" class="btn btn-ghost btn-sm">Close</button>
        </div>
      </div>
      <div class="px-6 py-4 max-h-[78vh] overflow-y-auto flex flex-col gap-4">
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 flex flex-col gap-2">
          <div class="flex gap-2 flex-wrap items-center">
            <span class="badge badge-blue">${_escapeHtml(provider)}</span>
            ${model ? `<span class="badge badge-gray">${_escapeHtml(model)}</span>` : ''}
            ${status ? `<span class="badge ${status === 'degraded' ? 'badge-amber' : 'badge-green'}">${_escapeHtml(status)}</span>` : ''}
            <span class="badge ${reviewed ? 'badge-green' : 'badge-amber'}">${reviewed ? 'Reviewed' : 'Needs review'}</span>
          </div>
          ${errorMessage ? `<p class="text-[12px] text-amber-700"><span class="font-semibold">Provider note:</span> ${_escapeHtml(errorMessage)}</p>` : ''}
          <p class="text-[12px] text-slate-600"><span class="font-semibold">Notebook ID:</span> ${_escapeHtml(providerContext?.notebook_id || rawProviderPayload?.notebook_id || 'None')}</p>
          <p class="text-[12px] text-slate-600"><span class="font-semibold">Source IDs:</span> ${sourceIds.length ? _escapeHtml(sourceIds.join(', ')) : _escapeHtml(String(rawProviderPayload?.source_ids || 'None'))}</p>
          <p class="text-[12px] text-slate-600"><span class="font-semibold">Reviewed at:</span> ${_escapeHtml(reviewedAt ? fmtDateTime(reviewedAt) : '-')}</p>
          ${responseMode ? `<p class="text-[12px] text-slate-600"><span class="font-semibold">Response mode:</span> ${_escapeHtml(responseMode)}</p>` : ''}
          ${selectedVariant ? `<p class="text-[12px] text-slate-600"><span class="font-semibold">Selected variant:</span> ${_escapeHtml(selectedVariant)}</p>` : ''}
          ${selectedStructureSource ? `<p class="text-[12px] text-slate-600"><span class="font-semibold">Selected structure:</span> ${_escapeHtml(selectedStructureSource)}</p>` : ''}
        </div>

        <div class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
          <h3 class="text-[14px] font-semibold text-slate-800 mb-2">Unit map</h3>
          <p class="text-[12px] text-slate-500 mb-3">This is the saved unit understanding layer we can reuse later for checklist quality, teacher help, and future materials.</p>
          <div class="grid gap-4 md:grid-cols-2">
            <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
              <p class="text-[12px] text-slate-600"><span class="font-semibold">Unit title:</span> ${_escapeHtml(String(unitMap?.unit_title || blueprintJson?.unit_title || unit?.title || '-'))}</p>
              <p class="text-[12px] text-slate-600"><span class="font-semibold">Source mode:</span> ${_escapeHtml(String(unitMap?.source_mode || '-'))}</p>
              <p class="text-[12px] text-slate-600"><span class="font-semibold">Future actions:</span> ${Array.isArray(unitMap?.future_actions) && unitMap.future_actions.length ? _escapeHtml(unitMap.future_actions.join(', ')) : '-'}</p>
            </div>
            <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 space-y-3">
              ${renderMapList('Teaching goals', unitMap?.teaching_goals)}
              ${renderMapList('Prerequisites', unitMap?.prerequisites)}
              ${renderMapList('Teacher resources', unitMap?.teacher_resources)}
              ${renderMapList('Activity blocks', unitMap?.activity_blocks)}
              ${renderMapList('Assessment blocks', unitMap?.assessment_blocks)}
              ${renderMapList('Pedagogy notes', unitMap?.pedagogy_notes)}
              ${(!Array.isArray(unitMap?.teaching_goals) || !unitMap.teaching_goals.length)
                && (!Array.isArray(unitMap?.prerequisites) || !unitMap.prerequisites.length)
                && (!Array.isArray(unitMap?.teacher_resources) || !unitMap.teacher_resources.length)
                && (!Array.isArray(unitMap?.activity_blocks) || !unitMap.activity_blocks.length)
                && (!Array.isArray(unitMap?.assessment_blocks) || !unitMap.assessment_blocks.length)
                && (!Array.isArray(unitMap?.pedagogy_notes) || !unitMap.pedagogy_notes.length)
                ? '<p class="text-[12px] text-slate-500">No structured unit map details were saved for this unit yet.</p>'
                : ''}
            </div>
          </div>
          <div class="mt-4">
            <h4 class="text-[13px] font-semibold text-slate-800 mb-2">Ordered unit outline</h4>
            ${unitMapOutline.length ? _renderBlueprintTree(unitMapOutline) : '<p class="text-[12px] text-slate-500">No ordered outline was saved in the unit map.</p>'}
          </div>
          <div class="mt-4">
            <h4 class="text-[13px] font-semibold text-slate-800 mb-2">Derived section plans</h4>
            <p class="text-[12px] text-slate-500 mb-3">These section plans are derived from the saved unit map so we can reuse the same NotebookLM understanding later for write-ups, teaching material, and guided teacher help.</p>
            <div class="space-y-3">
              ${renderSectionPlans(sectionPlans)}
            </div>
          </div>
          <div class="mt-4">
            <h4 class="text-[13px] font-semibold text-slate-800 mb-2">Saved content blocks</h4>
            <p class="text-[12px] text-slate-500 mb-3">This is the ordered teaching material extracted from the unit. Each block keeps a short faithful excerpt and a classroom-ready version we can reuse later for sessions, slides, and richer teacher help.</p>
            <div class="space-y-3">
              ${renderContentBlocks(contentBlocks)}
            </div>
          </div>
          <div class="mt-4">
            <h4 class="text-[13px] font-semibold text-slate-800 mb-2">Teacher playbook</h4>
            <p class="text-[12px] text-slate-500 mb-3">This is the first reusable action layer for the unit. It shows what we can later ask NotebookLM to do for each section: easier practice, harder practice, explanation help, quick quiz, slides, and more.</p>
            <div class="space-y-3">
              ${renderTeacherPlaybook(teacherPlaybook)}
            </div>
          </div>
          <div class="mt-4">
            <h4 class="text-[13px] font-semibold text-slate-800 mb-2">Material studio plan</h4>
            <p class="text-[12px] text-slate-500 mb-3">This is the forward plan for NotebookLM-native content generation from the same unit context: study guides, quizzes, flashcards, slide decks, infographics, and teacher prep outputs.</p>
            <div class="space-y-3">
              ${renderMaterialStudio(materialStudio)}
            </div>
          </div>
          <div class="mt-4">
            <h4 class="text-[13px] font-semibold text-slate-800 mb-2">Saved guidance library</h4>
            <p class="text-[12px] text-slate-500 mb-3">These are the section-level NotebookLM answers the teacher decided to keep for reuse.</p>
            <div id="unit-blueprint-artifacts" class="space-y-3">
              <p class="text-[12px] text-slate-500">Loading saved guidance…</p>
            </div>
          </div>
        </div>

        <div class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
          <h3 class="text-[14px] font-semibold text-slate-800 mb-2">Parsed checklist tree</h3>
          <p class="text-[12px] text-slate-500 mb-3">This is the structured tree the app saved into the unit checklist.</p>
          ${_renderBlueprintTree(blueprintJson?.items || [])}
        </div>

        <div class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
          <h3 class="text-[14px] font-semibold text-slate-800 mb-2">Raw NotebookLM answers</h3>
          <p class="text-[12px] text-slate-500 mb-3">These are the direct answers returned by NotebookLM before the app parsed them.</p>
          ${responses.length ? responses.map(row => `
            <details class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 mb-2" ${String(row?.variant || '') === selectedVariant ? 'open' : ''}>
              <summary class="cursor-pointer text-[12px] font-semibold text-slate-700">
                ${_escapeHtml(String(row?.variant || 'response'))}
                ${row?.conversation_id ? ` • ${_escapeHtml(String(row.conversation_id))}` : ''}
              </summary>
              ${row?.prompt ? `<div class="mt-3">
                <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1">Prompt</p>
                <pre class="text-[11px] leading-5 whitespace-pre-wrap break-words text-slate-700 font-mono bg-white rounded-lg border border-slate-200 px-3 py-2">${_escapeHtml(String(row.prompt || ''))}</pre>
              </div>` : ''}
              <div class="mt-3">
                <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1">Answer</p>
                <pre class="text-[11px] leading-5 whitespace-pre-wrap break-words text-slate-700 font-mono">${_escapeHtml(String(row?.answer || ''))}</pre>
              </div>
            </details>
          `).join('') : '<p class="text-[12px] text-slate-500">No raw NotebookLM responses were saved for this unit.</p>'}
        </div>

        <details class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
          <summary class="cursor-pointer text-[14px] font-semibold text-slate-800">Full saved extraction JSON</summary>
          <pre class="mt-3 text-[11px] leading-5 whitespace-pre-wrap break-words text-slate-700 font-mono">${_escapeHtml(_prettyJson(blueprint || {}))}</pre>
        </details>
      </div>
      <div class="px-6 py-4 border-t border-slate-100 flex justify-end">
        <button id="unit-blueprint-close" class="btn btn-primary">Close</button>
      </div>
    </div>`;

  function cleanup() {
    overlay.remove();
  }

  overlay.addEventListener('click', event => {
    if (event.target === overlay) cleanup();
  });
  overlay.querySelector('#unit-blueprint-close-top')?.addEventListener('click', cleanup);
  overlay.querySelector('#unit-blueprint-close')?.addEventListener('click', cleanup);
  document.body.appendChild(overlay);
  const artifactsNode = overlay.querySelector('#unit-blueprint-artifacts');
  const loadArtifacts = async () => {
    if (!artifactsNode || !classId || !unit?.id) return;
    try {
      const rows = await api(`/workflow/classes/${classId}/units/${unit.id}/assistant/artifacts`);
      artifactsNode.innerHTML = renderSavedGuidanceLibrary(rows);
      artifactsNode.querySelectorAll('.btn-blueprint-artifact-download').forEach(button => {
        button.addEventListener('click', async () => {
          const artifactId = Number(button.dataset.artifactId || 0);
          if (!artifactId) return;
          try {
            await downloadWithAuth(`/workflow/classes/${classId}/units/${unit.id}/assistant/artifacts/${artifactId}/download`, 'guidance.md');
          } catch (err) {
            showToast(String(err?.message || 'Failed to download the saved guidance.'), 'error');
          }
        });
      });
    } catch (err) {
      artifactsNode.innerHTML = `<p class="text-[12px] text-red-600">${_escapeHtml(String(err?.message || 'Failed to load saved guidance.'))}</p>`;
    }
  };
  loadArtifacts();
}

function _buildUnitAssistantSections(blueprint) {
  const unitMap = blueprint?.unit_map_json && typeof blueprint.unit_map_json === 'object' ? blueprint.unit_map_json : {};
  const teacherPlaybook = Array.isArray(unitMap?.teacher_playbook) ? unitMap.teacher_playbook.filter(Boolean) : [];
  const sections = [{
    key: '__whole_unit__',
    section_title: '',
    section_path: [],
    label: 'Whole unit',
    available_actions: ['explain_section', 'generate_teacher_notes', 'generate_slides', 'generate_quick_quiz'],
    suggested_requests: [
      'Give me a clean overview of this unit for teaching.',
      'Suggest the best progression to teach this unit.',
      'Prepare a quick revision quiz for the unit.',
    ],
  }];
  const seen = new Set(['__whole_unit__']);
  teacherPlaybook.forEach((row, index) => {
    const sectionTitle = String(row?.section_title || '').trim();
    const sectionPath = Array.isArray(row?.section_path)
      ? row.section_path.map(value => String(value || '').trim()).filter(Boolean)
      : [];
    const key = (sectionPath.length ? sectionPath.join('||') : sectionTitle || `section-${index}`).toLowerCase();
    if (!key || seen.has(key)) return;
    seen.add(key);
    sections.push({
      key,
      section_title: sectionTitle,
      section_path: sectionPath,
      label: sectionPath.length ? sectionPath.join(' -> ') : sectionTitle || `Section ${index + 1}`,
      available_actions: Array.isArray(row?.available_actions)
        ? row.available_actions.map(value => String(value || '').trim()).filter(Boolean)
        : [],
      suggested_requests: Array.isArray(row?.suggested_requests)
        ? row.suggested_requests.map(value => String(value || '').trim()).filter(Boolean)
        : [],
    });
  });
  return sections;
}

function _assistantActionLabel(value) {
  const key = String(value || '').trim();
  return UNIT_ASSISTANT_ACTION_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, char => char.toUpperCase()) || 'Action';
}

function _renderMaterialMarkdown(markdown) {
  const text = String(markdown || '').trim();
  if (!text) {
    return '<p class="text-[12px] text-slate-500">No generated content yet.</p>';
  }
  const lines = text.split(/\r?\n/);
  const html = [];
  let inList = false;
  const closeList = () => {
    if (inList) {
      html.push('</ul>');
      inList = false;
    }
  };
  lines.forEach(rawLine => {
    const line = String(rawLine || '');
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      return;
    }
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      closeList();
      const level = Math.min(6, headingMatch[1].length);
      const sizes = {
        1: 'text-[20px] font-bold',
        2: 'text-[17px] font-bold',
        3: 'text-[15px] font-semibold',
        4: 'text-[14px] font-semibold',
        5: 'text-[13px] font-semibold',
        6: 'text-[12px] font-semibold',
      };
      html.push(`<h${level} class="${sizes[level]} text-slate-800 mt-3 first:mt-0">${_escapeHtml(headingMatch[2])}</h${level}>`);
      return;
    }
    const bulletMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (bulletMatch) {
      if (!inList) {
        html.push('<ul class="list-disc pl-5 space-y-1.5 text-[13px] text-slate-700">');
        inList = true;
      }
      html.push(`<li>${_escapeHtml(bulletMatch[1])}</li>`);
      return;
    }
    closeList();
    html.push(`<p class="text-[13px] text-slate-700 leading-6">${_escapeHtml(trimmed)}</p>`);
  });
  closeList();
  return html.join('') || `<pre class="whitespace-pre-wrap text-[13px] text-slate-700 leading-6">${_escapeHtml(text)}</pre>`;
}

const SUPPORTED_UNIT_MATERIAL_TYPES = new Set([
  'study_guide',
  'formative_quiz',
  'mastery_quiz_hard',
  'revision_flashcards',
  'presenter_slides',
  'detailed_slides',
  'concept_infographic',
  'teacher_prep_audio',
]);

function _buildUnitMaterialOptions(blueprint) {
  const unitMap = blueprint?.unit_map_json && typeof blueprint.unit_map_json === 'object' ? blueprint.unit_map_json : {};
  const studio = unitMap?.material_studio && typeof unitMap.material_studio === 'object' ? unitMap.material_studio : {};
  const rows = Array.isArray(studio?.unit_artifacts) ? studio.unit_artifacts.filter(Boolean) : [];
  const options = [];
  const seen = new Set();
  rows.forEach((row, index) => {
    const id = String(row?.id || '').trim().toLowerCase();
    if (!id || !SUPPORTED_UNIT_MATERIAL_TYPES.has(id) || seen.has(id)) return;
    seen.add(id);
    options.push({
      id,
      title: String(row?.title || id).trim() || id,
      purpose: String(row?.purpose || '').trim(),
      when_to_use: String(row?.when_to_use || '').trim(),
      artifact_type: String(row?.artifact_type || '').trim(),
      notebooklm_method: String(row?.notebooklm_method || '').trim(),
      options: row?.options && typeof row.options === 'object' ? row.options : {},
    });
  });
  if (!options.length) {
    options.push({
      id: 'study_guide',
      title: 'Study guide',
      purpose: 'Student revision support with key concepts, guided review, and practice prompts.',
      when_to_use: 'After the checklist is reviewed or before revision week.',
      artifact_type: 'report',
      notebooklm_method: 'generate_study_guide',
      options: {},
    });
  }
  return options;
}

function _buildUnitAssistantMarkdown(result, unitTitle) {
  const title = String(result?.title || 'NotebookLM guidance').trim() || 'NotebookLM guidance';
  const action = String(result?.action || '').trim();
  const provider = String(result?.provider || '').trim();
  const sectionTitle = String(result?.section_title || '').trim();
  const sectionPath = Array.isArray(result?.section_path) ? result.section_path.filter(Boolean).map(value => String(value)) : [];
  const answerRows = Array.isArray(result?.answer_rows) ? result.answer_rows.filter(Boolean).map(value => String(value)) : [];
  const followups = Array.isArray(result?.suggested_followups) ? result.suggested_followups.filter(Boolean).map(value => String(value)) : [];
  const lines = [
    `# ${title}`,
    '',
    `- Unit: ${String(unitTitle || 'Unit').trim() || 'Unit'}`,
  ];
  if (sectionTitle) lines.push(`- Section: ${sectionTitle}`);
  if (sectionPath.length) lines.push(`- Path: ${sectionPath.join(' -> ')}`);
  if (action) lines.push(`- Action: ${_assistantActionLabel(action)}`);
  if (provider) lines.push(`- Provider: ${provider}`);
  lines.push('');
  lines.push('## Guidance');
  lines.push('');
  if (answerRows.length) {
    answerRows.forEach(row => lines.push(`- ${row}`));
  } else {
    lines.push('- No structured guidance returned.');
  }
  if (followups.length) {
    lines.push('');
    lines.push('## Suggested follow-ups');
    lines.push('');
    followups.forEach(row => lines.push(`- ${row}`));
  }
  return lines.join('\n').trim();
}

function _downloadTextContent(text, filename) {
  const blob = new Blob([String(text || '')], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename || 'download.md';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function _buildSessionWriteupMarkdown(writeup, { unitTitle = '', sessionLabel = '' } = {}) {
  const item = writeup && typeof writeup === 'object' ? writeup : {};
  const title = String(item.title || 'Session Write-Up').trim() || 'Session Write-Up';
  const learningFocus = Array.isArray(item.learning_focus) ? item.learning_focus.map(row => String(row || '').trim()).filter(Boolean) : [];
  const teachingContent = Array.isArray(item.teaching_content) ? item.teaching_content.map(row => String(row || '').trim()).filter(Boolean) : [];
  const practiceItems = Array.isArray(item.practice_items) ? item.practice_items.map(row => String(row || '').trim()).filter(Boolean) : [];
  const lines = [`# ${title}`, ''];
  if (unitTitle) lines.push(`- Unit: ${unitTitle}`);
  if (sessionLabel) lines.push(`- Session: ${sessionLabel}`);
  lines.push(`- Status: ${item.approved === false ? 'Draft' : 'Approved'}`);
  if (learningFocus.length) {
    lines.push('', '## Learning Focus', '');
    learningFocus.forEach(row => lines.push(`- ${row}`));
  }
  if (teachingContent.length) {
    lines.push('', '## Teaching Content', '');
    teachingContent.forEach(row => lines.push(row, ''));
    if (lines[lines.length - 1] === '') lines.pop();
  }
  if (practiceItems.length) {
    lines.push('', '## Practice', '');
    practiceItems.forEach(row => lines.push(`- ${row}`));
  }
  return lines.join('\n').trim();
}

function _summarizeRemainingGuidanceKinds(items) {
  const counts = new Map();
  (Array.isArray(items) ? items : []).forEach(item => {
    const kind = String(item?.artifact_kind || 'teacher_notes').trim().toLowerCase() || 'teacher_notes';
    counts.set(kind, (counts.get(kind) || 0) + 1);
  });
  return Array.from(counts.entries());
}

function _renderRemainingGuidanceSummary(items) {
  const normalized = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!normalized.length) return '';
  const kindSummary = _summarizeRemainingGuidanceKinds(normalized);
  const previewTitles = normalized
    .slice(0, 3)
    .map(item => String(item?.title || item?.section_title || 'Saved guidance').trim())
    .filter(Boolean);
  return `
    <div class="mt-3 rounded-lg border border-slate-200 bg-white/70 px-3 py-2">
      <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Still available to import</p>
      <div class="mt-2 flex flex-wrap gap-2">
        ${kindSummary.map(([kind, count]) => `<span class="badge badge-slate">${count} ${_escapeHtml(_assistantArtifactKindLabel(kind))}</span>`).join('')}
      </div>
      ${previewTitles.length ? `<p class="mt-2 text-[12px] text-slate-500">Top matches: ${_escapeHtml(previewTitles.join(' • '))}</p>` : ''}
    </div>`;
}

function _renderSessionWriteupNextStep(writeup, { hasSession = true, matchedGuidanceCount = 0, remainingGuidanceCount = 0, bestRemainingGuidanceTitle = '', quickGuidanceItems = [] } = {}) {
  if (!hasSession) return '';
  if (!writeup) {
    return `
      <div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-3">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Recommended next step</p>
        <p class="mt-1 text-[14px] font-semibold text-slate-800">Create the first session record</p>
        <p class="text-[12px] text-slate-600 mt-1">
          ${remainingGuidanceCount > 0
            ? `You already have ${remainingGuidanceCount} matching saved guidance item${remainingGuidanceCount === 1 ? '' : 's'} for this session. Import one first, or generate the write-up from scratch once you have checked what was actually covered in class.`
            : 'Generate the write-up once you have checked what was actually covered in class.'}
        </p>
        ${remainingGuidanceCount > 0 ? _renderRemainingGuidanceSummary(quickGuidanceItems) : ''}
        <div class="mt-3 rounded-xl border border-slate-200 bg-white px-3 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Actions</p>
          <div class="mt-2 flex gap-2 flex-wrap">
          ${remainingGuidanceCount === 1 ? `<button id="btn-session-next-import-best" class="btn btn-primary btn-sm">Import Best Match</button>` : ''}
          ${remainingGuidanceCount > 1 ? `<button id="btn-session-next-import-all" class="btn btn-primary btn-sm">Import All Guidance (${remainingGuidanceCount})</button>` : ''}
          <button id="btn-session-next-generate" class="btn btn-primary btn-sm">Generate now</button>
          <button id="btn-session-next-guidance" class="btn btn-secondary btn-sm">${remainingGuidanceCount === 1 && bestRemainingGuidanceTitle ? `Choose Other Guidance` : 'Use Saved Guidance'}</button>
          </div>
        </div>
        ${remainingGuidanceCount > 1 ? _renderGuidanceKindImportButtons(quickGuidanceItems, 'session-next-guidance-kind') : ''}
        ${remainingGuidanceCount > 1 ? _renderGuidanceQuickPickButtons(quickGuidanceItems, 'session-next-guidance') : ''}
      </div>`;
  }
  if (writeup.approved === false) {
    return `
      <div class="rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-3">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-800">Recommended next step</p>
        <p class="mt-1 text-[14px] font-semibold text-slate-800">Review and finish this draft</p>
        <p class="text-[12px] text-amber-700 mt-1">
          ${remainingGuidanceCount > 0
            ? `Review this draft, edit it if needed, and import any remaining saved guidance you still want before marking it approved.`
            : 'Review this draft, edit it if needed, then mark it approved when it matches the real lesson.'}
        </p>
        ${remainingGuidanceCount > 0 ? _renderRemainingGuidanceSummary(quickGuidanceItems) : ''}
        <div class="mt-3 rounded-xl border border-amber-200 bg-white/80 px-3 py-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-800">Actions</p>
          <div class="mt-2 flex gap-2 flex-wrap">
          <button id="btn-session-next-edit" class="btn btn-primary btn-sm">Edit draft</button>
          ${remainingGuidanceCount === 1 ? '<button id="btn-session-next-import-best" class="btn btn-secondary btn-sm">Import Best Match</button>' : ''}
          ${remainingGuidanceCount > 1 ? `<button id="btn-session-next-import-all" class="btn btn-secondary btn-sm">Import All Guidance (${remainingGuidanceCount})</button>` : ''}
          ${remainingGuidanceCount > 0 ? '<button id="btn-session-next-guidance" class="btn btn-secondary btn-sm">Use Saved Guidance</button>' : ''}
          <button id="btn-session-next-approve" class="btn btn-secondary btn-sm">Approve now</button>
          </div>
        </div>
        ${remainingGuidanceCount > 1 ? _renderGuidanceKindImportButtons(quickGuidanceItems, 'session-draft-guidance-kind') : ''}
        ${remainingGuidanceCount > 1 ? _renderGuidanceQuickPickButtons(quickGuidanceItems, 'session-draft-guidance') : ''}
      </div>`;
  }
  return `
    <div class="rounded-2xl border border-green-200 bg-green-50/80 px-4 py-3">
      <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-green-800">Recommended next step</p>
      <p class="mt-1 text-[14px] font-semibold text-slate-800">Reuse or revise this approved record</p>
      <p class="text-[12px] text-green-700 mt-1">This write-up is approved. Copy it, download it, or mark it draft again if you need to revise it.</p>
      <div class="mt-3 rounded-xl border border-green-200 bg-white/80 px-3 py-3">
        <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-green-800">Actions</p>
        <div class="mt-2 flex gap-2 flex-wrap">
        <button id="btn-session-next-copy" class="btn btn-primary btn-sm">Copy</button>
        <button id="btn-session-next-download" class="btn btn-secondary btn-sm">Download</button>
        </div>
      </div>
    </div>`;
}

function _assistantArtifactKindLabel(value) {
  const key = String(value || '').trim().toLowerCase();
  if (key === 'guided_practice') return 'Guided practice';
  if (key === 'quick_quiz_draft') return 'Quick quiz draft';
  return 'Teacher notes';
}

function _openUnitAssistantModal({ classId, unit, blueprint, initial = {} }) {
  const sections = _buildUnitAssistantSections(blueprint);
  const normalizedInitialPath = Array.isArray(initial?.sectionPath)
    ? initial.sectionPath.map(value => String(value || '').trim()).filter(Boolean)
    : [];
  const normalizedInitialTitle = String(initial?.sectionTitle || '').trim().toLowerCase();
  const normalizedInitialAction = String(initial?.assistantAction || '').trim().toLowerCase();
  const initialTeacherRequest = String(initial?.teacherRequest || '').trim();
  const initialSection = sections.find(section => {
    const sectionTitle = String(section?.section_title || '').trim().toLowerCase();
    if (normalizedInitialTitle && sectionTitle === normalizedInitialTitle) return true;
    const sectionPath = Array.isArray(section?.section_path) ? section.section_path.map(value => String(value || '').trim().toLowerCase()) : [];
    if (normalizedInitialPath.length && sectionPath.length === normalizedInitialPath.length) {
      return sectionPath.every((value, index) => value === String(normalizedInitialPath[index] || '').trim().toLowerCase());
    }
    return false;
  }) || sections[1] || sections[0];
  const initialActions = Array.isArray(initialSection?.available_actions) && initialSection.available_actions.length
    ? initialSection.available_actions
    : ['explain_section'];
  const state = {
    sectionKey: String(initialSection?.key || '__whole_unit__'),
    action: initialActions.includes(normalizedInitialAction) ? normalizedInitialAction : String(initialActions[0] || 'explain_section'),
    teacherRequest: initialTeacherRequest,
    loading: false,
    result: null,
    error: '',
    savedArtifacts: [],
  };

  const getSection = () => sections.find(row => row.key === state.sectionKey) || sections[0];

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal max-w-4xl w-[96vw]">
      <div class="px-6 py-5 border-b border-slate-100">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-[17px] font-bold text-slate-800">Ask This Unit</h2>
            <p class="text-[12px] text-slate-500 mt-1">
              Use the saved NotebookLM unit brain to get practical help for teaching this topic.
            </p>
          </div>
          <button id="unit-assistant-close-top" class="btn btn-ghost btn-sm">Close</button>
        </div>
      </div>
      <div class="px-6 py-4 max-h-[78vh] overflow-y-auto flex flex-col gap-4">
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <div class="grid gap-4 md:grid-cols-2">
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Target section</label>
              <select id="unit-assistant-section"></select>
              <p id="unit-assistant-section-path" class="text-[11px] text-slate-500 mt-1"></p>
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Action</label>
              <select id="unit-assistant-action"></select>
            </div>
          </div>
          <div class="mt-4">
            <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">Suggested requests</p>
            <div id="unit-assistant-suggestions" class="flex flex-wrap gap-2"></div>
          </div>
          <div class="mt-4 flex flex-col gap-1">
            <label class="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Teacher request</label>
            <textarea id="unit-assistant-request" rows="5" placeholder="Example: Give me 4 harder practice tasks for this section, with short teacher notes."></textarea>
            <p class="text-[11px] text-slate-500">We’ll ground this request on the saved unit context, section path, and extracted teaching blocks.</p>
          </div>
          <p id="unit-assistant-error" class="text-[12px] text-red-600 hidden mt-3"></p>
        </div>

        <div id="unit-assistant-result" class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
          <p class="text-[12px] text-slate-500">No guidance generated yet. Pick a section, choose an action, and ask NotebookLM for help.</p>
        </div>
        <div id="unit-assistant-saved" class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
          <p class="text-[12px] text-slate-500">Loading saved guidance…</p>
        </div>
      </div>
      <div class="px-6 py-4 border-t border-slate-100 flex justify-end gap-3">
        <button id="unit-assistant-close" class="btn btn-ghost">Close</button>
        <button id="unit-assistant-submit" class="btn btn-primary">Ask NotebookLM</button>
      </div>
    </div>
  `;

  const sectionSelect = overlay.querySelector('#unit-assistant-section');
  const actionSelect = overlay.querySelector('#unit-assistant-action');
  const requestInput = overlay.querySelector('#unit-assistant-request');
  const suggestionsWrap = overlay.querySelector('#unit-assistant-suggestions');
  const resultWrap = overlay.querySelector('#unit-assistant-result');
  const savedWrap = overlay.querySelector('#unit-assistant-saved');
  const errorNode = overlay.querySelector('#unit-assistant-error');
  const sectionPathNode = overlay.querySelector('#unit-assistant-section-path');
  const submitButton = overlay.querySelector('#unit-assistant-submit');

  const setError = message => {
    const text = String(message || '').trim();
    state.error = text;
    if (!errorNode) return;
    errorNode.textContent = text;
    errorNode.classList.toggle('hidden', !text);
  };

  const renderResult = () => {
    if (!resultWrap) return;
    const result = state.result;
    if (!result) {
      resultWrap.innerHTML = '<p class="text-[12px] text-slate-500">No guidance generated yet. Pick a section, choose an action, and ask NotebookLM for help.</p>';
      return;
    }
    const answerRows = Array.isArray(result?.answer_rows) ? result.answer_rows.filter(Boolean) : [];
    const followups = Array.isArray(result?.suggested_followups) ? result.suggested_followups.filter(Boolean) : [];
    resultWrap.innerHTML = `
      <div class="flex items-center gap-2 flex-wrap">
        <h3 class="text-[15px] font-semibold text-slate-800">${_escapeHtml(String(result?.title || 'NotebookLM guidance'))}</h3>
        ${result?.action ? `<span class="badge badge-blue">${_escapeHtml(_assistantActionLabel(result.action))}</span>` : ''}
        ${result?.provider ? `<span class="badge badge-gray">${_escapeHtml(String(result.provider))}</span>` : ''}
      </div>
      <div class="flex items-center justify-end gap-2 mt-3">
        <button class="btn btn-secondary btn-sm" id="unit-assistant-copy">Copy</button>
        <button class="btn btn-secondary btn-sm" id="unit-assistant-download">Download</button>
        <button class="btn btn-primary btn-sm" id="unit-assistant-save-notes">Save Notes</button>
        <button class="btn btn-secondary btn-sm" id="unit-assistant-save-practice">Save Practice</button>
        <button class="btn btn-secondary btn-sm" id="unit-assistant-save-quiz">Save Quiz Draft</button>
      </div>
      ${answerRows.length ? `
        <ul class="list-disc pl-5 mt-3 text-[13px] text-slate-700 space-y-2">
          ${answerRows.map(row => `<li>${_escapeHtml(String(row || ''))}</li>`).join('')}
        </ul>
      ` : '<p class="text-[12px] text-slate-500 mt-3">NotebookLM did not return structured teaching rows for this request.</p>'}
      ${followups.length ? `
        <div class="mt-4">
          <p class="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">Suggested next requests</p>
          <div class="flex flex-wrap gap-2">
            ${followups.map((row, index) => `<button class="btn btn-ghost btn-sm !text-slate-600 btn-unit-assistant-followup" data-followup-index="${index}">${_escapeHtml(String(row || ''))}</button>`).join('')}
          </div>
        </div>
      ` : ''}
      ${result?.error_message ? `<p class="text-[12px] text-amber-700 mt-4"><span class="font-semibold">Provider note:</span> ${_escapeHtml(String(result.error_message || ''))}</p>` : ''}
    `;
    resultWrap.querySelectorAll('.btn-unit-assistant-followup').forEach(button => {
      button.addEventListener('click', () => {
        const index = Number(button.dataset.followupIndex || -1);
        if (!Number.isFinite(index) || index < 0 || index >= followups.length || !requestInput) return;
        requestInput.value = String(followups[index] || '').trim();
        state.teacherRequest = requestInput.value;
        requestInput.focus();
      });
    });
    resultWrap.querySelector('#unit-assistant-copy')?.addEventListener('click', async () => {
      try {
        await copyText(_buildUnitAssistantMarkdown(result, unit?.title));
        showToast('Guidance copied.', 'ok');
      } catch {
        setError('Failed to copy the guidance.');
      }
    });
    resultWrap.querySelector('#unit-assistant-download')?.addEventListener('click', () => {
      const unitName = String(unit?.title || 'unit').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'unit';
      const sectionName = String(result?.section_title || 'guidance').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'guidance';
      _downloadTextContent(_buildUnitAssistantMarkdown(result, unit?.title), `${unitName}-${sectionName}-guidance.md`);
    });
    const saveArtifact = async artifactKind => {
      try {
        const payload = {
          artifact_kind: artifactKind,
          provider: String(result?.provider || 'notebooklm').trim() || 'notebooklm',
          model: String(result?.model || '').trim() || null,
          section_title: result?.section_title || null,
          section_path: Array.isArray(result?.section_path) && result.section_path.length ? result.section_path : null,
          action: result?.action || null,
          title: result?.title || null,
          answer_rows: Array.isArray(result?.answer_rows) ? result.answer_rows : [],
          suggested_followups: Array.isArray(result?.suggested_followups) ? result.suggested_followups : [],
          source_payload: result?.source_payload && typeof result.source_payload === 'object' ? result.source_payload : null,
          raw_provider_response: result?.raw_provider_response && typeof result.raw_provider_response === 'object' ? result.raw_provider_response : null,
        };
        await api(`/workflow/classes/${classId}/units/${unit.id}/assistant/artifacts`, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        _unitAssistantArtifactCache.delete(`${Number(classId || 0)}:${Number(unit?.id || 0)}`);
        showToast(`${_assistantArtifactKindLabel(artifactKind)} saved.`, 'ok');
        await loadSavedArtifacts();
      } catch (err) {
        setError(String(err?.message || 'Failed to save the guidance.'));
      }
    };
    resultWrap.querySelector('#unit-assistant-save-notes')?.addEventListener('click', () => saveArtifact('teacher_notes'));
    resultWrap.querySelector('#unit-assistant-save-practice')?.addEventListener('click', () => saveArtifact('guided_practice'));
    resultWrap.querySelector('#unit-assistant-save-quiz')?.addEventListener('click', () => saveArtifact('quick_quiz_draft'));
  };

  const renderSavedArtifacts = () => {
    if (!savedWrap) return;
    const section = getSection();
    const sectionKey = String(section?.section_title || '').trim().toLowerCase();
    const filtered = state.savedArtifacts.filter(item => {
      const itemSection = String(item?.section_title || '').trim().toLowerCase();
      if (sectionKey) return itemSection === sectionKey;
      return true;
    });
    if (!filtered.length) {
      savedWrap.innerHTML = '<p class="text-[12px] text-slate-500">No saved guidance yet for this section. Save a good NotebookLM result here to start building your teaching library.</p>';
      return;
    }
    savedWrap.innerHTML = `
      <div class="flex items-center justify-between gap-3 mb-3">
        <div>
          <h3 class="text-[15px] font-semibold text-slate-800">Saved guidance</h3>
          <p class="text-[12px] text-slate-500">Reusable section help you decided to keep.</p>
        </div>
      </div>
      <div class="space-y-3">
        ${filtered.map(item => `
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
            <div class="flex items-center justify-between gap-3 flex-wrap">
              <div class="flex items-center gap-2 flex-wrap">
                <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(item?.title || 'Saved guidance'))}</p>
                <span class="badge badge-blue">${_escapeHtml(_assistantArtifactKindLabel(item?.artifact_kind))}</span>
                ${item?.action ? `<span class="badge badge-gray">${_escapeHtml(_assistantActionLabel(item.action))}</span>` : ''}
              </div>
              <div class="flex items-center gap-2">
                <button class="btn btn-secondary btn-sm btn-unit-assistant-artifact-download" data-artifact-id="${_escapeHtml(String(item?.id || ''))}">
                  Download
                </button>
                <button class="btn btn-ghost btn-sm !text-rose-600 btn-unit-assistant-artifact-delete" data-artifact-id="${_escapeHtml(String(item?.id || ''))}">
                  Delete
                </button>
              </div>
            </div>
            ${item?.content_markdown ? `<p class="text-[12px] text-slate-700 leading-6 mt-3">${_escapeHtml(String(item.content_markdown).split('\n').slice(0, 4).join(' '))}</p>` : ''}
            <p class="text-[11px] text-slate-500 mt-3"><span class="font-semibold">Updated:</span> ${_escapeHtml(fmtDateTime(item?.updated_at))}</p>
          </div>
        `).join('')}
      </div>
    `;
    savedWrap.querySelectorAll('.btn-unit-assistant-artifact-download').forEach(button => {
      button.addEventListener('click', async () => {
        const artifactId = Number(button.dataset.artifactId || 0);
        if (!artifactId) return;
        try {
          await downloadWithAuth(`/workflow/classes/${classId}/units/${unit.id}/assistant/artifacts/${artifactId}/download`, 'guidance.md');
        } catch (err) {
          setError(String(err?.message || 'Failed to download the saved guidance.'));
        }
      });
    });
    savedWrap.querySelectorAll('.btn-unit-assistant-artifact-delete').forEach(button => {
      button.addEventListener('click', async () => {
        const artifactId = Number(button.dataset.artifactId || 0);
        if (!artifactId) return;
        if (!window.confirm('Delete this saved guidance?')) return;
        try {
          await api(`/workflow/classes/${classId}/units/${unit.id}/assistant/artifacts/${artifactId}`, {
            method: 'DELETE',
          });
          _unitAssistantArtifactCache.delete(`${Number(classId || 0)}:${Number(unit?.id || 0)}`);
          state.savedArtifacts = state.savedArtifacts.filter(item => Number(item?.id || 0) !== artifactId);
          renderSavedArtifacts();
          showToast('Saved guidance deleted.', 'ok');
        } catch (err) {
          setError(String(err?.message || 'Failed to delete the saved guidance.'));
        }
      });
    });
  };

  const renderSuggestions = () => {
    if (!suggestionsWrap) return;
    const section = getSection();
    const rows = Array.isArray(section?.suggested_requests) ? section.suggested_requests.filter(Boolean) : [];
    if (requestInput) requestInput.value = state.teacherRequest;
    sectionPathNode.textContent = Array.isArray(section?.section_path) && section.section_path.length
      ? `Path: ${section.section_path.join(' -> ')}`
      : (section?.section_title ? `Section: ${section.section_title}` : 'Whole unit guidance');
    if (!rows.length) {
      suggestionsWrap.innerHTML = '<p class="text-[12px] text-slate-500">No suggested requests yet for this section. You can still write your own request below.</p>';
      return;
    }
    suggestionsWrap.innerHTML = rows.map((row, index) => `
      <button class="btn btn-ghost btn-sm !text-slate-600 btn-unit-assistant-suggestion" data-suggestion-index="${index}">
        ${_escapeHtml(String(row || ''))}
      </button>
    `).join('');
    suggestionsWrap.querySelectorAll('.btn-unit-assistant-suggestion').forEach(button => {
      button.addEventListener('click', () => {
        const index = Number(button.dataset.suggestionIndex || -1);
        if (!Number.isFinite(index) || index < 0 || index >= rows.length || !requestInput) return;
        requestInput.value = String(rows[index] || '').trim();
        state.teacherRequest = requestInput.value;
        requestInput.focus();
      });
    });
  };

  const renderActions = () => {
    if (!actionSelect) return;
    const section = getSection();
    const actions = Array.isArray(section?.available_actions) && section.available_actions.length
      ? section.available_actions
      : ['explain_section'];
    if (!actions.includes(state.action)) {
      state.action = String(actions[0] || 'explain_section');
    }
    actionSelect.innerHTML = actions.map(value => `
      <option value="${_escapeHtmlAttr(String(value || ''))}" ${value === state.action ? 'selected' : ''}>
        ${_escapeHtml(_assistantActionLabel(value))}
      </option>
    `).join('');
  };

  const renderSections = () => {
    if (!sectionSelect) return;
    sectionSelect.innerHTML = sections.map(row => `
      <option value="${_escapeHtmlAttr(String(row.key || ''))}" ${row.key === state.sectionKey ? 'selected' : ''}>
        ${_escapeHtml(String(row.label || 'Section'))}
      </option>
    `).join('');
  };

  const cleanup = () => overlay.remove();

  const loadSavedArtifacts = async () => {
    try {
      const rows = await api(`/workflow/classes/${classId}/units/${unit.id}/assistant/artifacts`);
      state.savedArtifacts = Array.isArray(rows) ? rows : [];
    } catch (err) {
      state.savedArtifacts = [];
      setError(String(err?.message || 'Failed to load saved guidance.'));
    } finally {
      renderSavedArtifacts();
    }
  };

  renderSections();
  renderActions();
  renderSuggestions();
  renderResult();
  renderSavedArtifacts();

  sectionSelect?.addEventListener('change', () => {
    state.sectionKey = String(sectionSelect.value || '__whole_unit__');
    renderActions();
    renderSuggestions();
    renderSavedArtifacts();
  });
  actionSelect?.addEventListener('change', () => {
    state.action = String(actionSelect.value || 'explain_section');
  });
  requestInput?.addEventListener('input', () => {
    state.teacherRequest = String(requestInput.value || '').trim();
  });
  submitButton?.addEventListener('click', async () => {
    const section = getSection();
    setError('');
    state.result = null;
    renderResult();
    _setBusy(submitButton, true);
    try {
      const payload = {
        section_title: section?.section_title || null,
        section_path: Array.isArray(section?.section_path) && section.section_path.length ? section.section_path : null,
        action: state.action || 'explain_section',
        teacher_request: String(requestInput?.value || '').trim() || null,
      };
      const result = await api(`/workflow/classes/${classId}/units/${unit.id}/assistant`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      state.result = result || null;
      renderResult();
      if (String(result?.status || '').trim().toLowerCase() === 'degraded' && result?.error_message) {
        setError(String(result.error_message || 'Failed to generate NotebookLM guidance.'));
      } else {
        showToast('NotebookLM guidance is ready.', 'ok');
      }
    } catch (err) {
      setError(String(err?.message || 'Failed to ask NotebookLM for guidance.'));
    } finally {
      _setBusy(submitButton, false);
    }
  });

  overlay.addEventListener('click', event => {
    if (event.target === overlay) cleanup();
  });
  overlay.querySelector('#unit-assistant-close-top')?.addEventListener('click', cleanup);
  overlay.querySelector('#unit-assistant-close')?.addEventListener('click', cleanup);
  document.body.appendChild(overlay);
  loadSavedArtifacts();
}

async function _openUnitMaterialStudioModal({ classId, unit, blueprint }) {
  const materialOptions = _buildUnitMaterialOptions(blueprint);
  const initialMaterial = materialOptions[0] || { id: 'study_guide', title: 'Study guide' };
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal max-w-4xl w-[96vw]">
      <div class="px-6 py-5 border-b border-slate-100">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h2 class="text-[17px] font-bold text-slate-800">Material Studio</h2>
            <p class="text-[12px] text-slate-500 mt-1">
              Generate teacher-ready material from this unit’s saved NotebookLM context.
            </p>
          </div>
          <button id="unit-material-close-top" class="btn btn-ghost btn-sm">Close</button>
        </div>
      </div>
      <div class="px-6 py-4 max-h-[78vh] overflow-y-auto flex flex-col gap-4">
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
          <p class="text-[12px] text-slate-600"><span class="font-semibold">Unit:</span> ${_escapeHtml(String(unit?.title || 'Unit'))}</p>
          <p class="text-[11px] text-slate-500 mt-1">This uses the same NotebookLM unit brain already saved for checklist extraction, section plans, and guided teacher help.</p>
          <div class="mt-4 flex flex-col gap-1">
            <label class="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Material</label>
            <select id="unit-material-type"></select>
            <p id="unit-material-purpose" class="text-[11px] text-slate-500 mt-1"></p>
            <p id="unit-material-when" class="text-[11px] text-slate-500"></p>
          </div>
          <p id="unit-material-error" class="text-[12px] text-red-600 hidden mt-3"></p>
        </div>
        <div id="unit-material-result" class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
          <p class="text-[12px] text-slate-500">Loading saved material state...</p>
        </div>
      </div>
      <div class="px-6 py-4 border-t border-slate-100 flex justify-end gap-3">
        <button id="unit-material-close" class="btn btn-ghost">Close</button>
        <button id="unit-material-generate" class="btn btn-primary">Generate Material</button>
      </div>
    </div>
  `;
  const errorNode = overlay.querySelector('#unit-material-error');
  const resultNode = overlay.querySelector('#unit-material-result');
  const submitButton = overlay.querySelector('#unit-material-generate');
  const materialSelect = overlay.querySelector('#unit-material-type');
  const purposeNode = overlay.querySelector('#unit-material-purpose');
  const whenNode = overlay.querySelector('#unit-material-when');
  const state = {
    loading: false,
    materialType: String(initialMaterial.id || 'study_guide'),
    itemsByType: {},
    error: '',
  };

  function getSelectedMaterial() {
    return materialOptions.find(row => row.id === state.materialType) || materialOptions[0] || initialMaterial;
  }

  function cleanup() {
    overlay.remove();
  }

  function setError(message) {
    state.error = String(message || '').trim();
    if (state.error) {
      errorNode.textContent = state.error;
      errorNode.classList.remove('hidden');
    } else {
      errorNode.textContent = '';
      errorNode.classList.add('hidden');
    }
  }

  function render() {
    const selectedMaterial = getSelectedMaterial();
    const item = state.itemsByType[state.materialType] || null;
    materialSelect.innerHTML = materialOptions.map(row => `
      <option value="${_escapeHtml(String(row.id))}" ${row.id === state.materialType ? 'selected' : ''}>
        ${_escapeHtml(String(row.title || row.id))}
      </option>
    `).join('');
    purposeNode.textContent = selectedMaterial?.purpose || '';
    whenNode.textContent = selectedMaterial?.when_to_use ? `When to use: ${selectedMaterial.when_to_use}` : '';

    if (state.loading && !item) {
      resultNode.innerHTML = '<p class="text-[12px] text-slate-500">Loading material...</p>';
      return;
    }
    if (!item) {
      resultNode.innerHTML = '<p class="text-[12px] text-slate-500">No saved material has been generated for this unit and selection yet.</p>';
      submitButton.textContent = `Generate ${selectedMaterial?.title || 'Material'}`;
      return;
    }
    submitButton.textContent = `Re-generate ${selectedMaterial?.title || 'Material'}`;
    resultNode.innerHTML = `
      <div class="flex items-center gap-2 flex-wrap mb-4">
        <span class="badge badge-blue">${_escapeHtml(String(item.material_type || 'study_guide'))}</span>
        <span class="badge ${String(item.status || 'ready') === 'ready' ? 'badge-green' : 'badge-amber'}">${_escapeHtml(String(item.status || 'ready'))}</span>
        ${item.provider ? `<span class="badge badge-gray">${_escapeHtml(String(item.provider))}</span>` : ''}
        ${item.model ? `<span class="badge badge-gray">${_escapeHtml(String(item.model))}</span>` : ''}
      </div>
      <div class="flex items-center justify-end mb-4">
        <button id="unit-material-download" class="btn btn-secondary btn-sm" data-material-id="${_escapeHtml(String(item.id || ''))}">
          Download
        </button>
      </div>
      ${item.error_message ? `<p class="text-[12px] text-amber-700 mb-3"><span class="font-semibold">Provider note:</span> ${_escapeHtml(String(item.error_message || ''))}</p>` : ''}
      ${item.file_name ? `
        <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p class="text-[13px] font-semibold text-slate-700">Generated file</p>
          <p class="text-[12px] text-slate-600 mt-2"><span class="font-semibold">File:</span> ${_escapeHtml(String(item.file_name || ''))}</p>
          ${item.file_content_type ? `<p class="text-[12px] text-slate-500 mt-1"><span class="font-semibold">Type:</span> ${_escapeHtml(String(item.file_content_type || ''))}</p>` : ''}
          <p class="text-[12px] text-slate-500 mt-3">This material is saved as a downloadable file artifact. Use the download button to open it in PowerPoint or your preferred presentation tool.</p>
        </div>
      ` : `
        <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
          ${_renderMaterialMarkdown(item.content_markdown)}
        </div>
      `}
      <p class="text-[11px] text-slate-500 mt-3"><span class="font-semibold">Updated:</span> ${_escapeHtml(fmtDateTime(item.updated_at))}</p>
    `;
  }

  async function loadExisting() {
    state.loading = true;
    render();
    setError('');
    try {
      const rows = await api(`/workflow/classes/${classId}/units/${unit.id}/materials`);
      const list = Array.isArray(rows) ? rows : [];
      state.itemsByType = {};
      list.forEach(row => {
        const key = String(row?.material_type || '').trim().toLowerCase();
        if (key) state.itemsByType[key] = row;
      });
    } catch (err) {
      setError(String(err?.message || 'Failed to load unit materials.'));
      state.itemsByType = {};
    } finally {
      state.loading = false;
      render();
    }
  }

  async function generateMaterial() {
    const selectedMaterial = getSelectedMaterial();
    state.loading = true;
    submitButton.disabled = true;
    setError('');
    render();
    try {
      const item = await api(`/workflow/classes/${classId}/units/${unit.id}/materials/generate`, {
        method: 'POST',
        body: JSON.stringify({ material_type: state.materialType }),
      });
      if (item && typeof item === 'object') {
        state.itemsByType[state.materialType] = item;
      }
      showToast(`${selectedMaterial?.title || 'Material'} generated.`, 'ok');
    } catch (err) {
      setError(String(err?.message || 'Failed to generate the material.'));
    } finally {
      state.loading = false;
      submitButton.disabled = false;
      render();
    }
  }

  overlay.addEventListener('click', event => {
    if (event.target === overlay) cleanup();
  });
  resultNode.addEventListener('click', async event => {
    const downloadButton = event.target instanceof Element ? event.target.closest('#unit-material-download') : null;
    if (!downloadButton) return;
    const item = state.itemsByType[state.materialType] || null;
    if (!item?.id) return;
    const selectedMaterial = getSelectedMaterial();
    setError('');
    try {
      downloadButton.setAttribute('disabled', 'disabled');
      await downloadWithAuth(
        `/workflow/classes/${classId}/units/${unit.id}/materials/${item.id}/download`,
        `${selectedMaterial?.id || 'material'}.md`,
      );
    } catch (err) {
      setError(String(err?.message || 'Failed to download the material.'));
    } finally {
      downloadButton.removeAttribute('disabled');
    }
  });
  overlay.querySelector('#unit-material-close-top')?.addEventListener('click', cleanup);
  overlay.querySelector('#unit-material-close')?.addEventListener('click', cleanup);
  materialSelect?.addEventListener('change', event => {
    state.materialType = String(event?.target?.value || initialMaterial.id || 'study_guide').trim().toLowerCase();
    render();
  });
  submitButton.addEventListener('click', generateMaterial);
  document.body.appendChild(overlay);
  await loadExisting();
}

async function _openSessionGuidanceImportModal({ classId, unit }) {
  return new Promise(async resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-3xl w-[96vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <div class="flex items-start justify-between gap-4">
            <div>
              <h2 class="text-[17px] font-bold text-slate-800">Use Saved Guidance</h2>
              <p class="text-[12px] text-slate-500 mt-1">Import a saved NotebookLM answer into this session write-up draft.</p>
            </div>
            <button id="session-guidance-close-top" class="btn btn-ghost btn-sm">Close</button>
          </div>
        </div>
        <div class="px-6 py-4 max-h-[72vh] overflow-y-auto">
          <div id="session-guidance-list" class="space-y-3">
            <p class="text-[12px] text-slate-500">Loading saved guidance…</p>
          </div>
        </div>
        <div class="px-6 py-4 border-t border-slate-100 flex justify-end">
          <button id="session-guidance-close" class="btn btn-ghost">Close</button>
        </div>
      </div>
    `;
    const listNode = overlay.querySelector('#session-guidance-list');
    const cleanup = value => {
      overlay.remove();
      resolve(value ?? null);
    };
    const renderRows = rows => {
      const values = Array.isArray(rows) ? rows.filter(Boolean) : [];
      if (!values.length) {
        listNode.innerHTML = '<p class="text-[12px] text-slate-500">No saved guidance yet for this unit. Save a good result from Ask This Unit first.</p>';
        return;
      }
      listNode.innerHTML = values.map(item => `
        <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-4">
          <div class="flex items-center justify-between gap-3 flex-wrap">
            <div class="flex items-center gap-2 flex-wrap">
              <p class="text-[13px] font-semibold text-slate-700">${_escapeHtml(String(item?.title || 'Saved guidance'))}</p>
              <span class="badge badge-blue">${_escapeHtml(_assistantArtifactKindLabel(item?.artifact_kind))}</span>
              ${item?.action ? `<span class="badge badge-gray">${_escapeHtml(_assistantActionLabel(item.action))}</span>` : ''}
            </div>
            <button class="btn btn-primary btn-sm btn-session-guidance-import" data-artifact-id="${_escapeHtml(String(item?.id || ''))}">
              Import
            </button>
          </div>
          ${item?.section_title ? `<p class="text-[11px] text-slate-500 mt-2"><span class="font-semibold">Section:</span> ${_escapeHtml(String(item.section_title || ''))}</p>` : ''}
          ${Array.isArray(item?.section_path) && item.section_path.length ? `<p class="text-[11px] text-slate-500 mt-1"><span class="font-semibold">Path:</span> ${_escapeHtml(item.section_path.join(' -> '))}</p>` : ''}
          ${item?.content_markdown ? `<p class="text-[12px] text-slate-700 leading-6 mt-3">${_escapeHtml(String(item.content_markdown).split('\n').slice(0, 4).join(' '))}</p>` : ''}
        </div>
      `).join('');
      listNode.querySelectorAll('.btn-session-guidance-import').forEach(button => {
        button.addEventListener('click', () => cleanup(Number(button.dataset.artifactId || 0) || null));
      });
    };
    overlay.addEventListener('click', event => {
      if (event.target === overlay) cleanup(null);
    });
    overlay.querySelector('#session-guidance-close-top')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#session-guidance-close')?.addEventListener('click', () => cleanup(null));
    document.body.appendChild(overlay);
    try {
      const rows = await api(`/workflow/classes/${classId}/units/${unit.id}/assistant/artifacts`);
      renderRows(rows);
    } catch (err) {
      listNode.innerHTML = `<p class="text-[12px] text-red-600">${_escapeHtml(String(err?.message || 'Failed to load saved guidance.'))}</p>`;
    }
  });
}

function _sortSessionProgressItems(rows) {
  return rows.sort((a, b) => {
    const posDiff = Number(a.position || 0) - Number(b.position || 0);
    if (posDiff !== 0) return posDiff;
    return Number(a.id || 0) - Number(b.id || 0);
  });
}

function _splitNumberedProgressRows(value) {
  const raw = String(value || '').trim();
  if (!raw) return [];
  const lines = raw
    .split(/[\r\n]+/)
    .map(line => line.replace(/\s+/g, ' ').trim().replace(/^[;, -]+|[;, -]+$/g, ''))
    .filter(Boolean);
  const output = [];
  lines.forEach(line => {
    const starts = [];
    const pattern = /(^|\s)\d+(?:\.\d+)+(?:[)\].:-])?(?=\s|$)/g;
    let match = pattern.exec(line);
    while (match) {
      starts.push(match.index + (match[1] ? match[1].length : 0));
      match = pattern.exec(line);
    }
    if (starts.length > 1 && starts[0] === 0) {
      starts.forEach((start, idx) => {
        const end = idx + 1 < starts.length ? starts[idx + 1] : line.length;
        const chunk = line.slice(start, end).trim().replace(/^[;, -]+|[;, -]+$/g, '');
        if (chunk) output.push(chunk);
      });
      return;
    }
    output.push(line);
  });
  const deduped = [];
  const seen = new Set();
  output.forEach(row => {
    const text = String(row || '').trim();
    if (!text) return;
    const key = text.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    deduped.push(text);
  });
  return deduped;
}

function _normalizeSessionProgressItems(rows) {
  const list = Array.isArray(rows) ? rows : [];
  const expanded = [];
  list.forEach((row, index) => {
    const baseId = Number(row?.id || 0) || index + 1;
    const itemType = String(row?.item_type || 'lesson').trim().toLowerCase();
    const heading = String(row?.heading || '').trim();
    const content = row?.content == null ? null : String(row.content).trim();
    const basePosition = Number.isFinite(Number(row?.position)) ? Number(row.position) : index + 1;
    const splitSource = content || heading;
    const splitRows = _splitNumberedProgressRows(splitSource);
    if (!splitRows.length) {
      expanded.push({
        id: baseId,
        item_type: itemType,
        heading,
        content,
        position: basePosition,
      });
      return;
    }
    splitRows.forEach((rowText, splitIndex) => {
      const normalizedText = String(rowText || '').trim();
      if (!normalizedText) return;
      expanded.push({
        id: (baseId * 1000) + splitIndex,
        item_type: itemType,
        heading: content ? heading : normalizedText,
        content: content ? normalizedText : null,
        position: basePosition + (splitIndex / 1000),
      });
    });
  });
  return _sortSessionProgressItems(expanded);
}

function _progressItemLabel(row) {
  const itemType = String(row?.item_type || 'lesson').toLowerCase();
  if (itemType === 'lesson') return row.heading || row.content || 'Lesson';
  return row.content || row.heading || (itemType === 'activity' ? 'Activity' : 'Exercise');
}

function _progressItemTypeLabel(value) {
  const key = String(value || '').toLowerCase();
  if (key === 'activity') return 'Activity';
  if (key === 'exercise') return 'Exercise';
  return 'Lesson';
}

async function _loadSessionProgress(sessionId, { force = false } = {}) {
  const sid = Number(sessionId);
  if (!Number.isFinite(sid) || sid <= 0) return _emptySessionProgressState();
  const existing = _getSessionProgressState(sid);
  if (existing.loading) return existing;
  if (!force && existing.loaded) return existing;

  _setSessionProgressState(sid, {
    loading: true,
    loaded: false,
    error: null,
    items: existing.items,
  });

  try {
    const detail = await api(`/sessions/${sid}`);
    const items = _normalizeSessionProgressItems(detail?.progress_items || []);
    return _setSessionProgressState(sid, {
      loading: false,
      loaded: true,
      error: null,
      items,
    });
  } catch (err) {
    return _setSessionProgressState(sid, {
      loading: false,
      loaded: true,
      error: String(err?.message || 'Failed to load session progress.'),
      items: existing.items,
    });
  }
}

function _isClosedSessionConflict(error) {
  const detail = String(error?.message || '').toLowerCase();
  return detail.includes('session is already closed');
}

function _isActiveUnitConflict(error) {
  const detail = String(error?.message || '').toLowerCase();
  return detail.includes('active unit already exists');
}

function _isSessionAlreadyOpenConflict(error) {
  const detail = String(error?.message || '').toLowerCase();
  return detail.includes('already open');
}

function _parsePlannedHoursInput(value) {
  const text = String(value ?? '').trim();
  if (!text) return { ok: true, value: null, error: null };
  const normalized = text.replace(',', '.');
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false, value: null, error: 'Planned hours must be greater than 0.' };
  }
  return { ok: true, value: Number(parsed.toFixed(2)), error: null };
}

function _toDateInputValue(value) {
  if (!value) return '';
  const text = String(value).trim();
  const match = text.match(/^(\d{4}-\d{2}-\d{2})/);
  if (match) return match[1];
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return '';
  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, '0');
  const day = String(parsed.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function _toTimeInputValue(value) {
  if (!value) return '';
  const text = String(value).trim();
  const match = text.match(/^(\d{2}):(\d{2})/);
  if (match) return `${match[1]}:${match[2]}`;
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) return '';
  const hour = String(parsed.getHours()).padStart(2, '0');
  const minute = String(parsed.getMinutes()).padStart(2, '0');
  return `${hour}:${minute}`;
}

function _toPayloadTime(value) {
  const input = _toTimeInputValue(value);
  return input ? `${input}:00` : null;
}

function _resolveSessionAbsentIds(session) {
  const local = Array.from(getAbsentIds() || []);
  const fromLocal = local.map(Number).filter(Number.isFinite);
  if (fromLocal.length) return fromLocal;
  const remote = Array.isArray(session?.absent_student_ids) ? session.absent_student_ids : [];
  return remote.map(Number).filter(Number.isFinite);
}

function _openActiveUnitPlanConfigModal({ unitTitle, defaultStartDate }) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-xl w-[96vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">Plan Sessions From Emploi</h2>
          <p class="text-[12px] text-slate-500 mt-1">Active unit: <span class="font-semibold text-slate-700">${_escapeHtml(unitTitle || 'Unit')}</span></p>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Sessions Count</label>
              <input id="unit-plan-count" type="number" min="1" max="120" step="1" value="6" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Start From</label>
              <input id="unit-plan-start" type="date" value="${_escapeHtml(defaultStartDate || '')}" />
            </div>
          </div>
          <p class="text-[11px] text-slate-500">Blocked Morocco holidays are skipped automatically.</p>
          <p id="unit-plan-config-error" class="text-[12px] text-red-600 hidden"></p>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="unit-plan-config-cancel" class="btn btn-ghost">Cancel</button>
          <button id="unit-plan-config-preview" class="btn btn-primary">Preview</button>
        </div>
      </div>
    `;

    const setError = message => {
      const node = overlay.querySelector('#unit-plan-config-error');
      if (!node) return;
      const text = String(message || '').trim();
      node.textContent = text;
      node.classList.toggle('hidden', !text);
    };
    const cleanup = value => {
      overlay.remove();
      resolve(value);
    };

    overlay.addEventListener('click', event => {
      if (event.target === overlay) cleanup(null);
    });
    overlay.querySelector('#unit-plan-config-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#unit-plan-config-preview')?.addEventListener('click', () => {
      const rawCount = Number(overlay.querySelector('#unit-plan-count')?.value || 0);
      const sessionCount = Number.isFinite(rawCount) ? Math.floor(rawCount) : 0;
      const startDate = String(overlay.querySelector('#unit-plan-start')?.value || '').trim();
      if (sessionCount <= 0 || sessionCount > 120) {
        setError('Sessions count must be between 1 and 120.');
        return;
      }
      if (!startDate) {
        setError('Start date is required.');
        return;
      }
      cleanup({
        session_count: sessionCount,
        start_date: startDate,
      });
    });

    document.body.appendChild(overlay);
    overlay.querySelector('#unit-plan-count')?.focus();
  });
}

function _openActiveUnitPlanPreviewModal({ preview, unitTitle }) {
  return new Promise(resolve => {
    const slots = Array.isArray(preview?.planned_slots) ? preview.planned_slots : [];
    const requestedCount = Number(preview?.requested_count || 0);
    const plannedCount = Number(preview?.planned_count || 0);
    const pendingCount = Number(preview?.failed_count || 0);
    const skippedHoliday = Number(preview?.skipped_holiday_count || 0);
    const skippedExisting = Number(preview?.skipped_existing_count || 0);
    const skippedException = Number(preview?.skipped_exception_count || 0);
    const searchEndDate = preview?.search_end_date ? fmtDate(preview.search_end_date) : null;

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-3xl w-[96vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">Preview Planned Sessions</h2>
          <p class="text-[12px] text-slate-500 mt-1">Unit: <span class="font-semibold text-slate-700">${_escapeHtml(unitTitle || 'Unit')}</span></p>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="badge badge-blue">Requested ${requestedCount}</span>
            <span class="badge badge-green">Planned ${plannedCount}</span>
            ${pendingCount > 0 ? `<span class="badge badge-amber">Pending ${pendingCount}</span>` : ''}
            ${skippedHoliday > 0 ? `<span class="badge badge-red">Holiday ${skippedHoliday}</span>` : ''}
            ${skippedExisting > 0 ? `<span class="badge badge-gray">Existing ${skippedExisting}</span>` : ''}
            ${skippedException > 0 ? `<span class="badge badge-gray">Exception ${skippedException}</span>` : ''}
          </div>
          ${searchEndDate ? `<p class="text-[11px] text-slate-500">Search window ends at ${_escapeHtml(searchEndDate)}.</p>` : ''}
          <div class="max-h-[320px] overflow-auto border border-slate-200 rounded-xl">
            ${slots.length ? slots.map((slot, index) => `
              <div class="px-3 py-2 border-b border-slate-100 last:border-b-0 bg-white">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-[12px] font-semibold text-slate-700">#${index + 1}</span>
                  <span class="text-[12px] text-slate-700">${_escapeHtml(fmtDate(slot.session_date))}</span>
                  <span class="text-[12px] text-slate-500">${_escapeHtml(fmtTime(slot.start_time || '--:--'))}${slot.end_time ? ` - ${_escapeHtml(fmtTime(slot.end_time))}` : ''}</span>
                  ${slot.moved_from_date ? `<span class="badge badge-blue">Moved from ${_escapeHtml(fmtDate(slot.moved_from_date))}</span>` : ''}
                </div>
                <p class="text-[11px] text-slate-500 mt-1">${_escapeHtml(slot.note || 'Auto-planned session')}</p>
              </div>
            `).join('') : '<p class="text-[12px] text-slate-500 px-3 py-3">No planned slots found.</p>'}
          </div>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="unit-plan-preview-cancel" class="btn btn-ghost">Cancel</button>
          <button id="unit-plan-preview-apply" class="btn btn-primary" ${slots.length ? '' : 'disabled'}>Apply</button>
        </div>
      </div>
    `;

    const cleanup = value => {
      overlay.remove();
      resolve(value);
    };
    overlay.addEventListener('click', event => {
      if (event.target === overlay) cleanup(false);
    });
    overlay.querySelector('#unit-plan-preview-cancel')?.addEventListener('click', () => cleanup(false));
    overlay.querySelector('#unit-plan-preview-apply')?.addEventListener('click', () => cleanup(true));

    document.body.appendChild(overlay);
  });
}

async function _withActionLock(lockKey, runner) {
  if (_inFlightActions.has(lockKey)) {
    showToast('Please wait for the current action to finish.', 'info');
    return null;
  }
  _inFlightActions.add(lockKey);
  try {
    return await runner();
  } finally {
    _inFlightActions.delete(lockKey);
  }
}

export async function renderWorkflowView() {
  _showChrome();
  const el = document.getElementById('app-content');
  const classId = getSelectedId();
  const pendingWorkflowIntent = _peekWorkflowViewIntent();

  if (!classId) {
    el.innerHTML = `<div class="view-container">
          <div class="empty-state bg-white rounded-3xl border border-slate-200 py-16">
            <div class="text-xl font-black opacity-30">WF</div>
            <h2 class="font-semibold text-slate-500">No class selected</h2>
            <p class="text-[13px] text-slate-400">Select a class from the dropdown first.</p>
          </div></div>`;
    return;
  }

  el.innerHTML = `<div class="view-container"><div class="skeleton h-96 rounded-2xl animate-pulse"></div></div>`;

  try {
    let ws = await api(`/workflow/classes/${classId}`);
    if (pendingWorkflowIntent?.unit_id) {
      const activeUnitId = Number(ws?.active_unit?.id || 0) || null;
      const targetUnitId = Number(pendingWorkflowIntent.unit_id || 0) || null;
      if (targetUnitId && activeUnitId !== targetUnitId) {
        if (!activeUnitId) {
          const targetClosed = Array.isArray(ws?.closed_units)
            ? ws.closed_units.find(row => Number(row?.id || 0) === targetUnitId)
            : null;
          if (targetClosed) {
            await api(`/workflow/classes/${classId}/units/${targetUnitId}/reopen`, { method: 'POST' });
            ws = await api(`/workflow/classes/${classId}`);
          } else {
            try { sessionStorage.removeItem(WORKFLOW_VIEW_INTENT_KEY); } catch {}
          }
        } else {
          try { sessionStorage.removeItem(WORKFLOW_VIEW_INTENT_KEY); } catch {}
          showToast('Close the current active unit before opening Calendar tools for another workflow unit.', 'info');
        }
      }
    }
    if (pendingWorkflowIntent?.source === 'calendar') {
      const intendedSessionId = Number(pendingWorkflowIntent.session_id || 0) || null;
      const activeSessionId = Number(ws?.active_session?.id || 0) || null;
      _workflowPreviewFocusOnly = pendingWorkflowIntent.action !== 'session';
      _workflowPreviewHideDone = _workflowPreviewFocusOnly ? Boolean(pendingWorkflowIntent.preview_hide_done) : false;
      if (
        pendingWorkflowIntent.action === 'session'
        && activeSessionId
        && (!intendedSessionId || activeSessionId === intendedSessionId)
      ) {
        _activeTab = 2;
      } else {
        _activeTab = 0;
      }
    } else {
      _workflowPreviewFocusOnly = true;
      _workflowPreviewHideDone = false;
    }
    setWorkspace(ws);
    _render(el, classId);
  } catch (err) {
    console.warn('Workspace load failed', err);
    const fallbackMessage = 'Unable to load workflow data right now. Retry after checking API connection.';
    let detailMessage = fallbackMessage;
    const rawMessage = typeof err?.message === 'string' ? err.message.trim() : '';
    if (err?.status === 403) {
      detailMessage = 'You do not have access to this class workflow yet. Ask the owner to confirm class assignment.';
    } else if (err?.status === 404) {
      detailMessage = 'This class workflow is not available yet. Start by creating or assigning a unit.';
    } else if (rawMessage && !/^HTTP\s+\d+$/i.test(rawMessage)) {
      detailMessage = `Workflow data could not be loaded: ${rawMessage}`;
    }
    setWorkspace({
      active_unit: null,
      closed_units: [],
      active_session: null,
      recent_sessions: [],
    });
    mountRetryCard(el, {
      title: 'Workflow Unavailable',
      message: detailMessage,
      buttonId: 'btn-retry-workflow-load',
      onRetry: () => renderWorkflowView(),
    });
    showToast(detailMessage, 'error');
    return;
  }
}

async function _loadSessionWriteup(sessionId, classId, { force = false } = {}) {
  const sid = Number(sessionId);
  if (!Number.isFinite(sid) || sid <= 0) return _emptySessionWriteupState();
  const existing = _getSessionWriteupState(sid);
  if (existing.loading) return existing;
  if (!force && existing.loaded) return existing;

  _setSessionWriteupState(sid, {
    loading: true,
    loaded: false,
    error: null,
    item: existing.item,
  });

  try {
    const row = await api(`/workflow/classes/${classId}/sessions/${sid}/writeup`);
    return _setSessionWriteupState(sid, {
      loading: false,
      loaded: true,
      error: null,
      item: row || null,
    });
  } catch (err) {
    const detail = String(err?.message || '');
    const notFound = detail.toLowerCase().includes('not found');
    return _setSessionWriteupState(sid, {
      loading: false,
      loaded: true,
      error: notFound ? null : detail || 'Failed to load session write-up.',
      item: null,
    });
  }
}

function _multilineToList(value) {
  return String(value || '')
    .split(/\r?\n+/)
    .map(row => row.trim())
    .filter(Boolean);
}

function _listToMultiline(rows) {
  return Array.isArray(rows) ? rows.map(row => String(row || '').trim()).filter(Boolean).join('\n') : '';
}

function _normalizeWriteupSourcePayload(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const matchedSections = Array.isArray(payload.matched_section_titles)
    ? payload.matched_section_titles.map(row => String(row || '').trim()).filter(Boolean)
    : [];
  const checkedPaths = Array.isArray(payload.checked_item_paths)
    ? payload.checked_item_paths
      .map(path => Array.isArray(path) ? path.map(row => String(row || '').trim()).filter(Boolean).join(' > ') : '')
      .filter(Boolean)
    : [];
  const checkedSectionPaths = Array.isArray(payload.checked_section_paths)
    ? payload.checked_section_paths
      .map(path => Array.isArray(path) ? path.map(row => String(row || '').trim()).filter(Boolean).join(' > ') : '')
      .filter(Boolean)
    : [];
  const matchedPaths = Array.isArray(payload.matched_section_paths)
    ? payload.matched_section_paths
      .map(path => Array.isArray(path) ? path.map(row => String(row || '').trim()).filter(Boolean).join(' > ') : '')
      .filter(Boolean)
    : [];
  const matchedBlocks = Array.isArray(payload.matched_block_titles)
    ? payload.matched_block_titles.map(row => String(row || '').trim()).filter(Boolean)
    : [];
  const matchedGuidance = Array.isArray(payload.matched_guidance_titles)
    ? payload.matched_guidance_titles.map(row => String(row || '').trim()).filter(Boolean)
    : [];
  const teachingSections = Array.isArray(payload.teaching_sections)
    ? payload.teaching_sections
      .map(row => {
        if (!row || typeof row !== 'object') return '';
        const sectionTitle = String(row.section_title || '').trim();
        const delivery = Array.isArray(row.delivery_sequence)
          ? row.delivery_sequence.map(value => String(value || '').trim()).filter(Boolean)
          : [];
        if (!sectionTitle) return '';
        return delivery.length
          ? `${sectionTitle}: ${delivery.join(' -> ')}`
          : sectionTitle;
      })
      .filter(Boolean)
    : [];
  const importedAssistantArtifacts = Array.isArray(payload.imported_assistant_artifacts)
    ? payload.imported_assistant_artifacts
      .map(entry => {
        const artifactId = Number(entry?.artifact_id || 0);
        if (!artifactId) return null;
        return {
          artifactId,
          artifactKind: String(entry?.artifact_kind || '').trim().toLowerCase(),
          sectionTitle: String(entry?.section_title || '').trim(),
          action: String(entry?.action || '').trim().toLowerCase(),
        };
      })
      .filter(Boolean)
    : [];
  return {
    requestedProvider: String(payload.requested_provider || '').trim() || null,
    providerUsed: String(payload.provider_used || '').trim() || null,
    unitBrainUsed: Boolean(payload.unit_brain_used),
    checkedPaths,
    checkedSectionPaths,
    matchedSections,
    matchedPaths,
    teachingSections,
    matchedBlocks,
    matchedGuidance,
    importedAssistantArtifacts,
  };
}

function _renderWriteupSourcePayload(payload, { compact = false } = {}) {
  const meta = _normalizeWriteupSourcePayload(payload);
  if (!meta) return '';
  const summaryBadges = [];
  if (meta.requestedProvider) summaryBadges.push(`Requested ${_escapeHtml(meta.requestedProvider)}`);
  if (meta.providerUsed) summaryBadges.push(`Used ${_escapeHtml(meta.providerUsed)}`);
  summaryBadges.push(meta.unitBrainUsed ? 'Unit brain matched' : 'Generic session context');

  const groups = [
    ['Checked route', meta.checkedPaths],
    ['Checked teaching sections', meta.checkedSectionPaths],
    ['Matched sections', meta.matchedSections],
    ['Matched paths', meta.matchedPaths],
    ['Session teaching flow', meta.teachingSections],
    ['Matched blocks', meta.matchedBlocks],
    ['Saved guidance used', meta.matchedGuidance],
  ].filter(([, rows]) => Array.isArray(rows) && rows.length);

  if (!groups.length) return '';

  const grid = `
    <div class="grid grid-cols-1 ${compact ? '' : 'lg:grid-cols-2'} gap-3">
      ${groups.map(([label, rows]) => `
        <div class="rounded-xl border border-slate-200 bg-white px-3 py-3">
          <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">${_escapeHtml(label)}</p>
          <ul class="mt-2 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
            ${rows.map(row => `<li>${_escapeHtml(row)}</li>`).join('')}
          </ul>
        </div>
      `).join('')}
      ${meta.importedAssistantArtifacts.length ? `
        <div class="rounded-xl border border-slate-200 bg-white px-3 py-3">
          <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Imported saved guidance</p>
          <ul class="mt-2 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
            ${meta.importedAssistantArtifacts.map(item => `
              <li>
                ${_escapeHtml(item.sectionTitle || 'Saved guidance')}
                ${item.artifactKind ? ` • ${_escapeHtml(_assistantArtifactKindLabel(item.artifactKind))}` : ''}
                ${item.action ? ` • ${_escapeHtml(_assistantActionLabel(item.action))}` : ''}
              </li>
            `).join('')}
          </ul>
        </div>
      ` : ''}
    </div>
  `;

  return _renderWorkflowDetailDisclosure(
    'AI Context Used',
    'Open this only when you want to audit which saved unit sections and guidance shaped the write-up.',
    grid,
    { badges: summaryBadges },
  );
}

function _renderImportedGuidanceSummary(payload) {
  const meta = _normalizeWriteupSourcePayload(payload);
  const items = Array.isArray(meta?.importedAssistantArtifacts) ? meta.importedAssistantArtifacts : [];
  if (!items.length) return '';
  return `
    <div class="rounded-2xl border border-emerald-200 bg-emerald-50/90 p-3 flex flex-col gap-2">
      <div class="flex items-center justify-between gap-2 flex-wrap">
        <p class="text-[12px] font-semibold text-emerald-800">Imported guidance in this write-up</p>
        <span class="badge badge-green">${items.length} imported</span>
      </div>
      <p class="text-[12px] text-emerald-700">Saved teacher help already merged into this lesson record.</p>
      <div class="flex flex-wrap gap-2">
        ${items.map(item => `
          <span class="badge badge-white border border-emerald-200 !text-emerald-800">
            ${_escapeHtml(item.sectionTitle || 'Saved guidance')}
            ${item.artifactKind ? ` • ${_escapeHtml(_assistantArtifactKindLabel(item.artifactKind))}` : ''}
          </span>
        `).join('')}
      </div>
    </div>
  `;
}

function _renderWorkflowDetailDisclosure(title, hint, body, { badges = [], open = false } = {}) {
  const content = String(body || '').trim();
  if (!content) return '';
  const safeBadges = Array.isArray(badges) ? badges.filter(Boolean) : [];
  return `
    <details class="mt-4 rounded-2xl border border-slate-200 bg-slate-50/80 p-3"${open ? ' open' : ''}>
      <summary class="cursor-pointer list-none select-none">
        <div class="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">${_escapeHtml(title)}</p>
            ${hint ? `<p class="mt-1 text-[12px] text-slate-500">${_escapeHtml(hint)}</p>` : ''}
          </div>
          <div class="flex items-center gap-2 flex-wrap">
            ${safeBadges.map(label => `<span class="badge badge-gray">${_escapeHtml(label)}</span>`).join('')}
            <span class="text-[11px] font-semibold text-slate-400">Show details</span>
          </div>
        </div>
      </summary>
      <div class="mt-3">
        ${content}
      </div>
    </details>
  `;
}

function _collectSessionPlannedNodes(nodes, sessionNumber) {
  const target = Number(sessionNumber || 0);
  if (!Number.isFinite(target) || target <= 0 || !Array.isArray(nodes)) return [];
  const walk = rows => rows.reduce((acc, rawNode) => {
    if (!rawNode || typeof rawNode !== 'object') return acc;
    const childMatches = walk(Array.isArray(rawNode.children) ? rawNode.children : []);
    const ownSession = Number(rawNode.session_number || 0);
    if (ownSession !== target && !childMatches.length) return acc;
    acc.push({
      title: String(rawNode.title || '').trim(),
      kind: String(rawNode.kind || '').trim(),
      session_number: ownSession > 0 ? ownSession : null,
      children: childMatches,
    });
    return acc;
  }, []);
  return walk(nodes);
}

function _flattenSessionPlannedTitles(nodes, output = []) {
  const rows = Array.isArray(nodes) ? nodes : [];
  rows.forEach(node => {
    if (!node || typeof node !== 'object') return;
    const title = String(node.title || '').trim();
    if (title) output.push(title);
    _flattenSessionPlannedTitles(node.children || [], output);
  });
  return output;
}

function _collectSessionPlannedPaths(nodes, lineage = [], output = []) {
  const rows = Array.isArray(nodes) ? nodes : [];
  rows.forEach(node => {
    if (!node || typeof node !== 'object') return;
    const title = String(node.title || '').trim();
    if (!title) return;
    const path = [...lineage, title];
    output.push({
      title,
      kind: String(node.kind || '').trim().toLowerCase(),
      path,
      pathKey: path.map(value => String(value || '').trim().toLowerCase()).filter(Boolean).join('|'),
    });
    _collectSessionPlannedPaths(node.children || [], path, output);
  });
  return output;
}

function _renderSessionPlannedTree(nodes, depth = 0) {
  if (!Array.isArray(nodes) || !nodes.length) {
    return depth === 0
      ? '<p class="text-[12px] text-slate-500">No planned checklist flow saved for this unit session.</p>'
      : '';
  }
  const listClass = depth === 0
    ? 'space-y-1.5'
    : 'space-y-1.5 ml-4 mt-2 border-l border-slate-200 pl-3';
  return `
    <ul class="${listClass}">
      ${nodes.map(node => `
        <li>
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-[13px] text-slate-700">${_escapeHtml(node?.title || '')}</span>
            ${node?.kind ? `<span class="badge badge-gray">${_escapeHtml(String(node.kind))}</span>` : ''}
            ${node?.session_number ? `<span class="badge badge-blue">S${Number(node.session_number)}</span>` : ''}
          </div>
          ${_renderSessionPlannedTree(node?.children || [], depth + 1)}
        </li>
      `).join('')}
    </ul>`;
}

function _renderSessionFallbackRouteRows(rows) {
  const items = Array.isArray(rows) ? rows : [];
  if (!items.length) {
    return '<p class="text-[12px] text-slate-500">No checked checklist items are recorded for this session yet.</p>';
  }
  return `
    <div class="flex flex-col gap-2">
      ${items.map(row => `
        <div class="rounded-xl border border-slate-200 bg-white px-3 py-2" style="margin-left:${Math.max(0, Number(row?.depth || 0)) * 14}px">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-[12px] text-slate-700">${_escapeHtml(String(row?.title || 'Checklist item'))}</span>
            <span class="badge badge-green">Checked</span>
            ${row?.item_kind ? `<span class="badge badge-gray">${_escapeHtml(String(row.item_kind))}</span>` : ''}
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function _normalizeChecklistTeachingPhase(item, sectionPlan = null) {
  const title = String(item?.title || '').trim();
  const titleKey = title.toLowerCase();
  const kind = String(item?.item_kind || '').trim().toLowerCase();
  const plan = sectionPlan && typeof sectionPlan === 'object' ? sectionPlan : null;
  const inPlanBucket = bucket => Array.isArray(plan?.[bucket]) && plan[bucket].some(value => String(value || '').trim().toLowerCase() === titleKey);

  if (inPlanBucket('activity_titles')) return 'activity';
  if (inPlanBucket('example_titles')) return 'example';
  if (inPlanBucket('exercise_titles')) return kind === 'evaluation' ? 'assessment' : 'practice';
  if (inPlanBucket('content_titles')) return 'content';

  if (kind === 'activity') return 'activity';
  if (kind === 'example') return 'example';
  if (kind === 'exercise') return 'practice';
  if (kind === 'evaluation') return 'assessment';
  if (kind === 'definition' || kind === 'property' || kind === 'lesson') return 'content';
  if (kind === 'chapter' || kind === 'section' || kind === 'subsection') return 'section';

  if (/(activit|decouv|decouvr|explor)/.test(titleKey)) return 'activity';
  if (/(exemple|example|modele|model)/.test(titleKey)) return 'example';
  if (/(exercice|exercise|application|entrain|practice|quiz|evaluation|assessment|probleme|problem)/.test(titleKey)) {
    return 'practice';
  }
  return 'content';
}

function _sessionTeachingPhaseLabel(phase) {
  const key = String(phase || '').trim().toLowerCase();
  if (key === 'activity') return 'Launch';
  if (key === 'content') return 'Teach';
  if (key === 'example') return 'Model';
  if (key === 'practice') return 'Practice';
  if (key === 'assessment') return 'Check';
  return 'Other';
}

function _isStructuralChecklistItem(item) {
  const kind = String(item?.item_kind || item?.kind || '').trim().toLowerCase();
  return kind === 'chapter' || kind === 'section' || kind === 'subsection';
}

function _findSectionPlanForChecklistContext(unitMap, context, item = null) {
  const plans = Array.isArray(unitMap?.section_plans) ? unitMap.section_plans.filter(Boolean) : [];
  if (!plans.length) return null;
  const itemTitleKey = String(item?.title || '').trim().toLowerCase();
  const sectionPathKey = String(context?.sectionPathKey || '').trim().toLowerCase();
  const itemPathKey = String(context?.itemPathKey || '').trim().toLowerCase();

  let best = null;
  let bestScore = -1;
  plans.forEach(plan => {
    const sectionTitle = String(plan?.section_title || '').trim();
    const sectionPath = Array.isArray(plan?.section_path) && plan.section_path.length ? plan.section_path : (sectionTitle ? [sectionTitle] : []);
    const planPathKey = sectionPath.map(value => String(value || '').trim().toLowerCase()).filter(Boolean).join('|');
    let score = -1;
    if (sectionPathKey && planPathKey && sectionPathKey === planPathKey) score = 5;
    else if (sectionPathKey && planPathKey && itemPathKey === planPathKey) score = 4;
    else if (itemTitleKey && Array.isArray(plan?.delivery_sequence) && plan.delivery_sequence.some(value => String(value || '').trim().toLowerCase() === itemTitleKey)) score = 3;
    else if (itemTitleKey && String(plan?.section_title || '').trim().toLowerCase() === itemTitleKey) score = 2;
    if (score > bestScore) {
      bestScore = score;
      best = plan;
    }
  });
  return bestScore >= 0 ? best : null;
}

function _buildSessionTeachingChecklistGroups(items, unitMap, allChecklistItems = null) {
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) return [];
  const contextSource = Array.isArray(allChecklistItems) && allChecklistItems.length ? allChecklistItems : rows;
  const contextMap = _buildChecklistContextMap(contextSource);
  const phaseOrder = ['activity', 'content', 'example', 'practice', 'assessment', 'other'];
  const groups = [];
  const groupMap = new Map();

  rows.forEach(row => {
    const itemId = Number(row?.id || 0);
    if (!itemId) return;
    if (_isStructuralChecklistItem(row)) return;
    const context = contextMap.get(itemId) || {
      itemPath: [String(row?.title || '').trim()].filter(Boolean),
      sectionPath: [],
      itemPathKey: String(row?.title || '').trim().toLowerCase(),
      sectionPathKey: '',
    };
    const sectionPlan = _findSectionPlanForChecklistContext(unitMap, context, row);
    const sectionTitle = String(sectionPlan?.section_title || '').trim()
      || (Array.isArray(context.sectionPath) && context.sectionPath.length ? context.sectionPath[context.sectionPath.length - 1] : '')
      || 'Teaching Flow';
    const sectionPath = Array.isArray(sectionPlan?.section_path) && sectionPlan.section_path.length
      ? sectionPlan.section_path
      : (Array.isArray(context.sectionPath) && context.sectionPath.length ? context.sectionPath : [sectionTitle]);
    const groupKey = sectionPath.map(value => String(value || '').trim().toLowerCase()).filter(Boolean).join('|') || sectionTitle.toLowerCase();
    if (!groupMap.has(groupKey)) {
      const phaseBuckets = new Map();
      phaseOrder.forEach(phase => phaseBuckets.set(phase, []));
      const group = {
        key: groupKey,
        title: sectionTitle,
        path: sectionPath,
        plan: sectionPlan,
        rows: [],
        done: 0,
        total: 0,
        phases: phaseBuckets,
      };
      groupMap.set(groupKey, group);
      groups.push(group);
    }
    const group = groupMap.get(groupKey);
    const phase = _normalizeChecklistTeachingPhase(row, sectionPlan);
    const normalizedPhase = phaseOrder.includes(phase) ? phase : 'other';
    group.rows.push(row);
    group.total += 1;
    if (row?.is_completed || row?.done) group.done += 1;
    group.phases.get(normalizedPhase).push({
      row,
      context,
      phase: normalizedPhase,
    });
  });

  return groups;
}

function _renderSessionTeachingChecklistGroups(groups, { hasPlannedRoute = false, classId = null, unitId = null } = {}) {
  const rows = Array.isArray(groups) ? groups : [];
  if (!rows.length) {
    return `<p class="text-[12px] text-slate-500">${hasPlannedRoute ? 'No matched teaching route rows are ready for this session yet.' : 'Start checking checklist rows to build the live teaching flow for this session.'}</p>`;
  }
  const phaseOrder = ['activity', 'content', 'example', 'practice', 'assessment', 'other'];
  return `
    <div class="flex flex-col gap-3">
      ${rows.map(group => {
        const remaining = Math.max(0, Number(group.total || 0) - Number(group.done || 0));
        return `
          <div class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
            <div class="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <p class="text-[13px] font-semibold text-slate-800">${_escapeHtml(group.title)}</p>
                ${Array.isArray(group.path) && group.path.length > 1
                  ? `<p class="mt-1 text-[11px] text-slate-400">${_escapeHtml(group.path.join(' > '))}</p>`
                  : ''}
              </div>
              <div class="flex items-center gap-2 flex-wrap">
                <span class="badge ${remaining === 0 ? 'badge-green' : group.done ? 'badge-amber' : 'badge-blue'}">${group.done}/${group.total} covered</span>
                ${remaining > 0 ? `<span class="badge badge-gray">${remaining} left</span>` : ''}
              </div>
            </div>
            <div class="mt-3 flex flex-col gap-3">
              ${phaseOrder.map(phase => {
                const phaseRows = group.phases.get(phase) || [];
                if (!phaseRows.length) return '';
                return `
                  <div class="rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-3">
                    <div class="flex items-center justify-between gap-2 flex-wrap mb-2">
                      <p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">${_escapeHtml(_sessionTeachingPhaseLabel(phase))}</p>
                      <span class="text-[11px] text-slate-400">${phaseRows.filter(entry => entry?.row?.is_completed || entry?.row?.done).length}/${phaseRows.length}</span>
                    </div>
                    <div class="flex flex-col gap-1.5">
                      ${phaseRows.map(entry => {
                        const item = entry.row || {};
                        const isDone = Boolean(item?.is_completed || item?.done);
                        return `
                          <div class="flex items-stretch gap-1">
                            <button
                              type="button"
                              class="flex-1 text-left rounded-xl border px-3 py-2 transition ${isDone ? 'border-green-200 bg-green-50/80' : 'border-slate-200 bg-white hover:border-blue-200 hover:bg-blue-50/50'}"
                              data-session-flow-check-item-id="${Number(item.id || 0)}"
                              aria-pressed="${isDone ? 'true' : 'false'}"
                            >
                              <div class="flex items-start gap-2">
                                <span class="mt-0.5 inline-flex h-[18px] w-[18px] items-center justify-center rounded-[4px] border-2 text-[10px] ${isDone ? 'border-green-600 bg-green-600 text-white' : 'border-slate-300 bg-white text-transparent'}">${isDone ? 'Y' : 'Y'}</span>
                                <div class="min-w-0 flex-1">
                                  <p class="text-[13px] leading-snug ${isDone ? 'text-slate-500 line-through' : 'text-slate-700'}">${_escapeHtml(String(item.title || 'Checklist item'))}</p>
                                  <div class="mt-1 flex items-center gap-2 flex-wrap">
                                    ${item?.item_kind ? `<span class="badge badge-gray">${_escapeHtml(String(item.item_kind))}</span>` : ''}
                                    ${Array.isArray(entry?.context?.itemPath) && entry.context.itemPath.length > 1
                                      ? `<span class="text-[11px] text-slate-400">${_escapeHtml(entry.context.itemPath.slice(0, -1).join(' > '))}</span>`
                                      : ''}
                                  </div>
                                </div>
                              </div>
                            </button>
                          </div>
                        `;
                      }).join('')}
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function _renderSessionPlaybookPreview(unitMap, plannedTitles, routeSectionPaths = []) {
  const playbook = Array.isArray(unitMap?.teacher_playbook) ? unitMap.teacher_playbook.filter(Boolean) : [];
  const titleKeys = new Set((Array.isArray(plannedTitles) ? plannedTitles : []).map(value => String(value || '').trim().toLowerCase()).filter(Boolean));
  const routePathKeys = new Set((Array.isArray(routeSectionPaths) ? routeSectionPaths : []).map(path => _normalizeSectionPathKey(path)).filter(Boolean));
  const matched = playbook.filter(entry => {
    const sectionTitle = String(entry?.section_title || '').trim().toLowerCase();
    if (sectionTitle && titleKeys.has(sectionTitle)) return true;
    const entryPathKey = _normalizeSectionPathKey(entry?.section_path);
    if (entryPathKey && routePathKeys.has(entryPathKey)) return true;
    const sectionPath = Array.isArray(entry?.section_path) ? entry.section_path : [];
    return sectionPath.some(value => titleKeys.has(String(value || '').trim().toLowerCase()));
  }).slice(0, 3);
  if (!matched.length) {
    return '<p class="text-[12px] text-slate-500">No specific teacher playbook suggestions matched this session yet.</p>';
  }
  return matched.map(entry => `
    <div class="rounded-2xl border border-slate-200 bg-white p-3">
      <div class="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p class="text-[12px] font-semibold text-slate-800">${_escapeHtml(String(entry?.section_title || 'Section'))}</p>
          ${Array.isArray(entry?.available_actions) && entry.available_actions.length
            ? `<p class="mt-1 text-[11px] text-slate-500">Best for: ${_escapeHtml(entry.available_actions.slice(0, 3).map(action => _assistantActionLabel(action)).join(' / '))}</p>`
            : '<p class="mt-1 text-[11px] text-slate-500">NotebookLM can help prepare this teaching focus.</p>'}
        </div>
        ${Array.isArray(entry?.section_path) && entry.section_path.length
          ? `<span class="text-[11px] text-slate-400">${_escapeHtml(entry.section_path.join(' > '))}</span>`
          : ''}
      </div>
      ${Array.isArray(entry?.available_actions) && entry.available_actions.length ? `
        <p class="mt-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Suggested prompts</p>` : ''}
      ${Array.isArray(entry?.suggested_requests) && entry.suggested_requests.length ? `
        <div class="mt-2 flex flex-wrap gap-2">
          ${entry.suggested_requests.slice(0, 3).map(row => `
            <button
              class="btn btn-ghost btn-sm btn-session-playbook-request"
              data-section-title="${_escapeHtmlAttr(String(entry?.section_title || ''))}"
              data-section-path="${_escapeHtmlAttr(JSON.stringify(Array.isArray(entry?.section_path) ? entry.section_path : []))}"
              data-teacher-request="${_escapeHtmlAttr(String(row || ''))}"
              data-assistant-action="${_escapeHtmlAttr(String(Array.isArray(entry?.available_actions) && entry.available_actions.length ? entry.available_actions[0] : 'explain_section'))}"
            >${_escapeHtml(String(row || ''))}</button>`).join('')}
        </div>` : ''}
    </div>
  `).join('');
}

function _findSectionPlanForPlannedTitle(unitMap, title) {
  const target = String(title || '').trim().toLowerCase();
  if (!target) return null;
  const plans = Array.isArray(unitMap?.section_plans) ? unitMap.section_plans.filter(Boolean) : [];
  return plans.find(plan => {
    const sectionTitle = String(plan?.section_title || '').trim().toLowerCase();
    if (sectionTitle && sectionTitle === target) return true;
    const delivery = Array.isArray(plan?.delivery_sequence) ? plan.delivery_sequence : [];
    return delivery.some(value => String(value || '').trim().toLowerCase() === target);
  }) || null;
}

function _findTeacherPlaybookEntryForSection(unitMap, sectionPlan, fallbackTitle = '') {
  const playbook = Array.isArray(unitMap?.teacher_playbook) ? unitMap.teacher_playbook.filter(Boolean) : [];
  const targetTitle = String(sectionPlan?.section_title || fallbackTitle || '').trim().toLowerCase();
  const targetPath = Array.isArray(sectionPlan?.section_path) ? sectionPlan.section_path.map(value => String(value || '').trim().toLowerCase()) : [];
  return playbook.find(entry => {
    const entryTitle = String(entry?.section_title || '').trim().toLowerCase();
    if (targetTitle && entryTitle === targetTitle) return true;
    const entryPath = Array.isArray(entry?.section_path) ? entry.section_path.map(value => String(value || '').trim().toLowerCase()) : [];
    if (targetPath.length && entryPath.length === targetPath.length) {
      return entryPath.every((value, index) => value === targetPath[index]);
    }
    return false;
  }) || null;
}

function _buildAssistantPrefillFromPlaybook(entry, sectionPlan, fallbackTitle = '', preferredAction = '') {
  const availableActions = Array.isArray(entry?.available_actions) ? entry.available_actions.map(value => String(value || '').trim().toLowerCase()).filter(Boolean) : [];
  const suggestedRequests = Array.isArray(entry?.suggested_requests) ? entry.suggested_requests.map(value => String(value || '').trim()).filter(Boolean) : [];
  const normalizedPreferredAction = String(preferredAction || '').trim().toLowerCase();
  const action = (normalizedPreferredAction && availableActions.includes(normalizedPreferredAction))
    ? normalizedPreferredAction
    : String(availableActions[0] || normalizedPreferredAction || 'explain_section').trim().toLowerCase();
  const actionIndex = availableActions.indexOf(action);
  const sectionTitle = String(sectionPlan?.section_title || fallbackTitle || '').trim();
  const sectionPath = Array.isArray(sectionPlan?.section_path) ? sectionPlan.section_path : [];
  const genericRequestByAction = {
    explain_section: `Help me explain ${sectionTitle}.`,
    simplify_explanation: `Simplify the explanation for ${sectionTitle}.`,
    generate_guided_examples: `Create guided examples for ${sectionTitle}.`,
    generate_easier_practice: `Create easier practice for ${sectionTitle}.`,
    generate_harder_practice: `Create harder practice for ${sectionTitle}.`,
    generate_quick_quiz: `Create a quick quiz for ${sectionTitle}.`,
    generate_teacher_notes: `Create teacher notes for ${sectionTitle}.`,
    generate_slides: `Outline slides for ${sectionTitle}.`,
    generate_remediation: `Create remediation support for ${sectionTitle}.`,
  };
  const teacherRequest = (actionIndex >= 0 ? String(suggestedRequests[actionIndex] || '').trim() : '')
    || String(suggestedRequests[0] || '').trim()
    || genericRequestByAction[action]
    || (sectionTitle ? `Help me prepare ${sectionTitle}.` : '');
  return {
    sectionTitle,
    sectionPath,
    teacherRequest,
    assistantAction: action || 'explain_section',
  };
}

function _renderPreviewNextFocusActions(sectionPlan, playbookEntry, fallbackTitle = '', { classId = null, unitId = null } = {}) {
  const sectionTitle = String(sectionPlan?.section_title || fallbackTitle || '').trim();
  if (!sectionTitle) return '';
  const availableActions = Array.isArray(playbookEntry?.available_actions) ? playbookEntry.available_actions.map(value => String(value || '').trim().toLowerCase()).filter(Boolean) : [];
  const actions = (availableActions.length ? availableActions : ['explain_section']).slice(0, 3);
  return `
    <div class="rounded-xl border border-amber-200 bg-amber-50 p-3">
      <p class="text-[12px] font-semibold text-amber-800">Next Teaching Focus</p>
      <p class="text-[12px] text-amber-700 mt-1">${_escapeHtml(sectionTitle)}</p>
      <div class="mt-3 flex flex-wrap gap-2">
        ${actions.map(action => `
          <button
            class="btn btn-secondary btn-sm btn-preview-next-focus-action"
            data-assistant-action="${_escapeHtmlAttr(action)}"
          >${_escapeHtml(_assistantActionLabel(action))}</button>`).join('')}
      </div>
      ${classId && unitId ? `<div class="mt-2" data-preview-saved-guidance data-class-id="${_escapeHtmlAttr(String(classId))}" data-unit-id="${_escapeHtmlAttr(String(unitId))}"></div>` : ''}
    </div>
  `;
}

function _openSessionWriteupModal(writeup) {
  return new Promise(resolve => {
    const item = writeup && typeof writeup === 'object' ? writeup : {};
    const overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-50 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center p-4';
    overlay.innerHTML = `
      <div class="w-full max-w-3xl max-h-[90vh] overflow-auto rounded-3xl bg-white shadow-2xl border border-slate-200 p-5 flex flex-col gap-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h3 class="text-[18px] font-semibold text-slate-800">Session Write-Up</h3>
            <p class="text-[12px] text-slate-500 mt-1">Review and refine the textbook text before export.</p>
          </div>
          <button id="writeup-cancel-top" class="btn btn-ghost btn-sm">Close</button>
        </div>
        <div class="grid grid-cols-1 gap-3">
          <div class="flex flex-col gap-1">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Title</label>
            <input id="writeup-title" type="text" value="${_escapeHtml(item.title || '')}" />
          </div>
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Learning Focus</label>
              <textarea id="writeup-focus" rows="8">${_escapeHtml(_listToMultiline(item.learning_focus))}</textarea>
              <p class="text-[11px] text-slate-500">One line per point.</p>
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Practice Items</label>
              <textarea id="writeup-practice" rows="8">${_escapeHtml(_listToMultiline(item.practice_items))}</textarea>
              <p class="text-[11px] text-slate-500">One line per exercise or reinforcement task.</p>
            </div>
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Teaching Content</label>
            <textarea id="writeup-content" rows="10">${_escapeHtml(_listToMultiline(item.teaching_content))}</textarea>
            <p class="text-[11px] text-slate-500">One paragraph per line.</p>
          </div>
          <label class="flex items-center gap-2 text-[13px] text-slate-700">
            <input id="writeup-approved" type="checkbox" ${item.approved === false ? '' : 'checked'} />
            Mark this write-up as approved
          </label>
        </div>
        <div class="flex items-center justify-end gap-2">
          <button id="writeup-cancel" class="btn btn-ghost">Cancel</button>
          <button id="writeup-save" class="btn btn-primary">Save Write-Up</button>
        </div>
      </div>
    `;

    const cleanup = result => {
      overlay.remove();
      resolve(result);
    };

    overlay.querySelector('#writeup-cancel-top')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#writeup-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#writeup-save')?.addEventListener('click', () => {
      cleanup({
        title: overlay.querySelector('#writeup-title')?.value?.trim() || '',
        learning_focus: _multilineToList(overlay.querySelector('#writeup-focus')?.value || ''),
        practice_items: _multilineToList(overlay.querySelector('#writeup-practice')?.value || ''),
        teaching_content: _multilineToList(overlay.querySelector('#writeup-content')?.value || ''),
        approved: Boolean(overlay.querySelector('#writeup-approved')?.checked),
      });
    });
    overlay.addEventListener('click', event => {
      if (event.target === overlay) cleanup(null);
    });
    document.body.appendChild(overlay);
    overlay.querySelector('#writeup-title')?.focus();
  });
}

async function _refreshWorkflowCalendarSnapshot(classId) {
  try {
    const rows = await api(`/workflow/classes/${classId}/calendar`);
    if (Array.isArray(rows)) setCalendar(rows);
  } catch {
    // Keep workflow actions non-blocking if calendar snapshot refresh fails.
  }
}

function _render(el, classId) {
  const unit = getActiveUnit();
  const session = getActiveSession();
  const currentSessionId = Number(session?.id || 0) || null;
  if (_sessionGuidanceStateSessionId !== currentSessionId) {
    _sessionGuidanceStateSessionId = currentSessionId;
    _sessionGuidanceHideImported = false;
    _sessionGuidanceKindFilter = 'all';
    _sessionGuidanceCollapseImported = false;
    _workflowCollapsePlannedRoute = false;
    _workflowCollapseSessionProgress = false;
    _workflowCollapseSessionWriteup = false;
  }
  const sessionProgressState = session ? _getSessionProgressState(session.id) : _emptySessionProgressState();
  const sessionWriteupState = session ? _getSessionWriteupState(session.id) : _emptySessionWriteupState();
  const closed = getClosedUnits();
  const recentSessions = getRecentSessions();
  const visibleRecentSessions = _filterRecentSessions(recentSessions, _recentWindow);
  const unitTimelineState = unit ? _getUnitTimelineState(unit.id) : _emptyUnitTimelineState();
  const unitBlueprintState = unit ? _getUnitBlueprintState(unit.id) : _emptyUnitBlueprintState();
  const students = getStudents();
  const todayDateValue = _toDateInputValue(new Date());
  const activeBlueprint = unitBlueprintState.item && typeof unitBlueprintState.item === 'object' ? unitBlueprintState.item : null;
  const activeBlueprintTree = activeBlueprint?.blueprint_json && typeof activeBlueprint.blueprint_json === 'object' && Array.isArray(activeBlueprint.blueprint_json.items)
    ? activeBlueprint.blueprint_json.items
    : [];
  const activeUnitMap = activeBlueprint?.unit_map_json && typeof activeBlueprint.unit_map_json === 'object'
    ? activeBlueprint.unit_map_json
    : {};
  const checklist = _checklist(unit);
  const previewSessionNumber = !session && _workflowEntryContext?.source === 'calendar'
    ? Number(_workflowEntryContext.unit_session_number || 0) || null
    : null;
  const previewSessionPlanTree = previewSessionNumber ? _collectSessionPlannedNodes(activeBlueprintTree, previewSessionNumber) : [];
  const previewSessionPlanPaths = _collectSessionPlannedPaths(previewSessionPlanTree, [], []);
  const previewSessionPlanTitles = _flattenSessionPlannedTitles(previewSessionPlanTree, []);
  const previewSessionTitleKeys = new Set(previewSessionPlanTitles.map(value => String(value || '').trim().toLowerCase()).filter(Boolean));
  const activeSessionPlanTree = session?.unit_session_number ? _collectSessionPlannedNodes(activeBlueprintTree, session.unit_session_number) : [];
  const activeSessionPlanPaths = _collectSessionPlannedPaths(activeSessionPlanTree, [], []);
  const activeSessionPlanTitles = _flattenSessionPlannedTitles(activeSessionPlanTree, []);
  const activeSessionCheckedChecklist = session
    ? checklist.filter(item => Number(item?.completed_session_id || 0) === Number(session.id || 0))
    : [];
  const activeSessionCheckedSectionPaths = Array.isArray(session?.checked_section_paths) && session.checked_section_paths.length
    ? session.checked_section_paths.map(path => Array.isArray(path) ? path.map(value => String(value || '').trim()).filter(Boolean) : []).filter(path => path.length)
    : _deriveChecklistSectionPaths(
      checklist,
      activeSessionCheckedChecklist.map(item => Number(item?.id || 0))
    );
  const activeSessionCheckedTitles = activeSessionCheckedChecklist.map(item => String(item?.title || '').trim()).filter(Boolean);
  const activeEffectiveRouteTitles = activeSessionPlanTitles.length ? activeSessionPlanTitles : activeSessionCheckedTitles;
  const activeEffectiveTitleKeys = new Set(activeEffectiveRouteTitles.map(value => String(value || '').trim().toLowerCase()).filter(Boolean));
  const activeChecklistContextMap = _buildChecklistContextMap(checklist);
  const activePlannedPathKeys = new Set(activeSessionPlanPaths.map(row => String(row?.pathKey || '').trim().toLowerCase()).filter(Boolean));
  const activePlannedRowIds = activePlannedPathKeys.size
    ? new Set(checklist
      .filter(item => {
        const itemId = Number(item?.id || 0);
        if (!itemId) return false;
        const context = activeChecklistContextMap.get(itemId) || null;
        const itemPathKey = String(context?.itemPathKey || '').trim().toLowerCase();
        return itemPathKey && activePlannedPathKeys.has(itemPathKey);
      })
      .map(item => Number(item?.id || 0))
      .filter(Boolean))
    : new Set();
  const activeEffectiveChecklist = session
    ? (activePlannedRowIds.size
      ? checklist.filter(item => activePlannedRowIds.has(Number(item?.id || 0)))
      : checklist.filter(item => activeEffectiveTitleKeys.has(String(item?.title || '').trim().toLowerCase())))
    : [];
  const activeFallbackFocusIds = activeSessionCheckedChecklist.length
    ? _collectChecklistFocusIdsByItemIds(checklist, activeSessionCheckedChecklist.map(item => Number(item?.id || 0)))
    : _collectPreviewFocusIds(checklist, activeEffectiveTitleKeys);
  const activeFallbackRouteRows = activeSessionPlanTitles.length
    ? []
    : _visibleChecklistRows(checklist.filter(item => activeFallbackFocusIds.has(Number(item?.id || 0))), new Set());
  const activeTeachingFlowGroups = _buildSessionTeachingChecklistGroups(
    activeSessionPlanTitles.length ? activeEffectiveChecklist : activeFallbackRouteRows,
    activeUnitMap,
    checklist,
  );
  const activeRouteSectionPaths = activeTeachingFlowGroups
    .map(group => Array.isArray(group?.path) ? group.path : [])
    .filter(path => path.length);
  const activeSessionMatchedGuidance = unit?.id
    ? _filterAssistantArtifactsForRouteContext(
      _unitAssistantArtifactCache.get(`${Number(classId || 0)}:${Number(unit.id || 0)}`) || [],
      activeUnitMap,
      activeEffectiveRouteTitles,
      activeRouteSectionPaths.length ? activeRouteSectionPaths : activeSessionCheckedSectionPaths,
    )
    : [];
  const activeSessionImportedGuidanceIds = _getImportedAssistantArtifactIds(sessionWriteupState.item);
  const activeSessionRemainingGuidance = activeSessionMatchedGuidance.filter(item => !activeSessionImportedGuidanceIds.has(Number(item?.id || 0)));
  const activeSessionRemainingGuidanceCount = activeSessionRemainingGuidance.length;
  const activeSessionVisibleRemainingGuidance = activeSessionRemainingGuidance.filter(item => {
    const itemKind = String(item?.artifact_kind || 'teacher_notes').trim().toLowerCase() || 'teacher_notes';
    return _sessionGuidanceKindFilter === 'all' || itemKind === _sessionGuidanceKindFilter;
  });
  const activeSessionVisibleRemainingGuidanceCount = activeSessionVisibleRemainingGuidance.length;
  const activeSessionBestRemainingGuidance = activeSessionRemainingGuidanceCount === 1 ? activeSessionRemainingGuidance[0] : null;

  // Progress ring
  _syncChecklistCollapseState(unit, checklist);
  _ensureChecklistFocusVisible(checklist, previewSessionTitleKeys);
  const checklistChildrenCount = _buildChecklistChildrenCount(checklist);
  const visibleChecklist = _visibleChecklistRows(checklist, _collapsedChecklistIds);
  const previewFocusIds = previewSessionNumber ? _collectPreviewFocusIds(checklist, previewSessionTitleKeys) : new Set();
  const previewMatchedChecklist = previewSessionNumber
    ? checklist.filter(item => previewSessionTitleKeys.has(String(item?.title || '').trim().toLowerCase()))
    : [];
  const previewMatchedDone = previewMatchedChecklist.filter(item => Boolean(item?.is_completed || item?.done)).length;
  const previewMatchedRemaining = Math.max(0, previewMatchedChecklist.length - previewMatchedDone);
  const previewCompletionPct = previewMatchedChecklist.length ? Math.round((previewMatchedDone / previewMatchedChecklist.length) * 100) : 0;
  const previewRouteStatus = !previewMatchedChecklist.length
    ? { label: 'No route saved', className: 'badge-gray', hint: 'No planned checklist route is saved for this session yet.' }
    : previewMatchedDone === 0
      ? { label: 'Not started', className: 'badge-blue', hint: 'This planned route has not been covered yet.' }
      : previewMatchedRemaining === 0
        ? { label: 'Fully covered', className: 'badge-green', hint: 'All planned rows for this session are already completed.' }
        : { label: 'Partly covered', className: 'badge-amber', hint: `${previewMatchedRemaining} planned row${previewMatchedRemaining === 1 ? '' : 's'} still remain.` };
  const previewKindCounts = previewMatchedChecklist.reduce((acc, item) => {
    const kind = String(item?.item_kind || '').trim().toLowerCase();
    if (!kind || kind === 'other') return acc;
    acc[kind] = Number(acc[kind] || 0) + 1;
    return acc;
  }, {});
  const previewSummaryBadges = [
    previewMatchedChecklist.length ? `${previewMatchedChecklist.length} planned items` : '',
    previewMatchedChecklist.length ? `${previewMatchedDone}/${previewMatchedChecklist.length} done` : '',
    previewMatchedChecklist.length ? `${previewMatchedRemaining} remaining` : '',
    previewMatchedChecklist.length ? `${previewCompletionPct}% covered` : '',
    previewKindCounts.activity ? `${previewKindCounts.activity} activities` : '',
    previewKindCounts.example ? `${previewKindCounts.example} examples` : '',
    previewKindCounts.exercise ? `${previewKindCounts.exercise} exercises` : '',
    previewKindCounts.definition ? `${previewKindCounts.definition} definitions` : '',
    previewKindCounts.property ? `${previewKindCounts.property} properties` : '',
  ].filter(Boolean);
  const activeHasPlannedRoute = activeSessionPlanTitles.length > 0;
  const activeMatchedChecklist = activeHasPlannedRoute ? activeEffectiveChecklist : activeFallbackRouteRows;
  const activeMatchedDone = activeMatchedChecklist.filter(item => Boolean(item?.is_completed || item?.done)).length;
  const activeMatchedRemaining = Math.max(0, activeMatchedChecklist.length - activeMatchedDone);
  const activeCompletionPct = activeHasPlannedRoute
    ? (activeMatchedChecklist.length ? Math.round((activeMatchedDone / activeMatchedChecklist.length) * 100) : 0)
    : (activeMatchedChecklist.length ? 100 : 0);
  const activeRouteStatus = activeHasPlannedRoute
    ? (!activeMatchedChecklist.length
    ? { label: 'No route saved', className: 'badge-gray', hint: 'No planned checklist route is saved for this live session yet.' }
    : activeMatchedDone === 0
      ? { label: 'Not started', className: 'badge-blue', hint: 'This planned route has not been covered yet.' }
      : activeMatchedRemaining === 0
      ? { label: 'Fully covered', className: 'badge-green', hint: 'All planned rows for this session are already completed.' }
      : { label: 'Partly covered', className: 'badge-amber', hint: `${activeMatchedRemaining} planned row${activeMatchedRemaining === 1 ? '' : 's'} still remain.` })
    : (activeMatchedChecklist.length
      ? { label: 'Recorded in session', className: 'badge-blue', hint: `${activeMatchedChecklist.length} checked checklist row${activeMatchedChecklist.length === 1 ? '' : 's'} already recorded for this live session.` }
      : { label: 'No route saved', className: 'badge-gray', hint: 'No planned checklist route or checked checklist rows are saved for this live session yet.' });
  const activeKindCounts = activeMatchedChecklist.reduce((acc, item) => {
    const kind = String(item?.item_kind || '').trim().toLowerCase();
    if (!kind || kind === 'other') return acc;
    acc[kind] = Number(acc[kind] || 0) + 1;
    return acc;
  }, {});
  const activeSummaryBadges = [
    activeMatchedChecklist.length ? `${activeMatchedChecklist.length} ${activeHasPlannedRoute ? 'planned' : 'checked'} items` : '',
    activeHasPlannedRoute && activeMatchedChecklist.length ? `${activeMatchedDone}/${activeMatchedChecklist.length} done` : '',
    activeHasPlannedRoute && activeMatchedChecklist.length ? `${activeMatchedRemaining} remaining` : '',
    activeMatchedChecklist.length ? `${activeCompletionPct}% covered` : '',
    activeKindCounts.activity ? `${activeKindCounts.activity} activities` : '',
    activeKindCounts.example ? `${activeKindCounts.example} examples` : '',
    activeKindCounts.exercise ? `${activeKindCounts.exercise} exercises` : '',
    activeKindCounts.definition ? `${activeKindCounts.definition} definitions` : '',
    activeKindCounts.property ? `${activeKindCounts.property} properties` : '',
  ].filter(Boolean);
  const activeSavedProgressCount = Number(sessionProgressState.items?.length || 0);
  const activeFallbackProgressCount = activeSessionCheckedChecklist.length;
  const activeProgressCount = activeSavedProgressCount > 0
    ? activeSavedProgressCount
    : activeFallbackProgressCount;
  const activeWriteupStateLabel = !sessionWriteupState.item
    ? 'Not saved'
    : sessionWriteupState.item.approved === false
      ? 'Draft ready'
      : 'Approved';
  const activeWriteupStateClass = !sessionWriteupState.item
    ? 'badge-gray'
    : sessionWriteupState.item.approved === false
      ? 'badge-amber'
      : 'badge-green';
  const activeSessionNextMoveText = !sessionWriteupState.item
    ? activeSessionRemainingGuidanceCount
      ? 'Import the saved guidance you already prepared, then generate the session write-up once you have checked what was really covered.'
      : 'Check what was really covered in class, then generate the session write-up to capture the lesson clearly.'
    : sessionWriteupState.item.approved === false
      ? activeSessionRemainingGuidanceCount
        ? 'Review the draft, import any remaining saved guidance, then approve it when it matches the lesson.'
        : 'Review the draft write-up and approve it when it matches what happened in class.'
      : 'The write-up is approved. Keep teaching from the planned route and reopen it only if the lesson changes.';
  const activeRouteValueLabel = activeHasPlannedRoute
    ? (activeMatchedChecklist.length ? `${activeMatchedDone}/${activeMatchedChecklist.length}` : '0')
    : `${activeMatchedChecklist.length}`;
  const activeRouteProgressCaption = activeHasPlannedRoute
    ? (activeMatchedChecklist.length
      ? (activeMatchedRemaining === 0
        ? 'All planned rows for this live session are covered'
        : `${activeMatchedRemaining} planned row${activeMatchedRemaining === 1 ? '' : 's'} still remain`)
      : 'No planned checklist route saved for this live session yet')
    : (activeMatchedChecklist.length
      ? `${activeMatchedChecklist.length} checked checklist row${activeMatchedChecklist.length === 1 ? '' : 's'} already captured in this live session`
      : 'No checked checklist rows have been captured in this live session yet');
  const activeGuidanceCaption = activeSessionRemainingGuidanceCount === 0
    ? 'No reusable saved guidance left'
    : activeSessionRemainingGuidanceCount === 1
      ? '1 saved item still reusable'
      : `${activeSessionRemainingGuidanceCount} saved items still reusable`;
  const activeProgressCaption = activeSavedProgressCount > 0
    ? (activeSavedProgressCount === 1
      ? '1 confirmed progress row saved'
      : `${activeSavedProgressCount} confirmed progress rows saved`)
    : activeFallbackProgressCount > 0
      ? `${activeFallbackProgressCount} checked checklist row${activeFallbackProgressCount === 1 ? '' : 's'} already recorded in this session`
      : (sessionProgressState.loaded ? 'No confirmed progress rows or checked checklist rows saved yet' : 'Load to review saved rows');
  const activeWriteupToneClass = !sessionWriteupState.item
    ? 'text-slate-900'
    : sessionWriteupState.item.approved === false
      ? 'text-amber-700'
      : 'text-emerald-700';
  const activeWriteupHeroCaption = !sessionWriteupState.item
    ? 'No lesson summary saved yet'
    : sessionWriteupState.item.approved === false
      ? 'Draft summary is waiting for review'
      : 'Approved lesson summary is ready below';
  const previewBaseChecklist = previewSessionNumber && _workflowPreviewFocusOnly && previewFocusIds.size
    ? visibleChecklist.filter(item => previewFocusIds.has(Number(item?.id || 0)))
    : visibleChecklist;
  const displayChecklist = previewSessionNumber && _workflowPreviewFocusOnly && _workflowPreviewHideDone
    ? previewBaseChecklist.filter(item => {
      const itemId = Number(item?.id || 0);
      const isDone = Boolean(item?.is_completed || item?.done);
      return previewFocusIds.has(itemId) ? !isDone : true;
    })
    : previewBaseChecklist;
  const previewResumeTargetId = previewSessionNumber
    ? Number(
      previewBaseChecklist.find(item => {
        const itemId = Number(item?.id || 0);
        if (!previewFocusIds.has(itemId)) return false;
        return !Boolean(item?.is_completed || item?.done);
      })?.id || 0
    ) || null
    : null;
  const previewResumeItem = previewResumeTargetId != null
    ? previewBaseChecklist.find(item => Number(item?.id || 0) === previewResumeTargetId) || null
    : null;
  const previewResumeSectionPlan = previewResumeItem ? _findSectionPlanForPlannedTitle(activeUnitMap, previewResumeItem.title) : null;
  const previewResumePlaybookEntry = _findTeacherPlaybookEntryForSection(activeUnitMap, previewResumeSectionPlan, previewResumeItem?.title || '');
  const moveMeta = _buildChecklistMoveMeta(checklist);
  const done = checklist.filter(i => Boolean(i?.is_completed || i?.done)).length;
  const total = checklist.length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const r = 36, circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ;
  const extractionSource = String(unit?.extraction_source || '').trim().toLowerCase();
  const extractionStatus = String(unit?.extraction_status || '').trim().toLowerCase();
  const extractionError = String(unit?.extraction_error || '').trim();
  const extractionReviewed = unit ? unit.extraction_reviewed !== false : true;
  const extractionReviewPending = Boolean(unit?.extraction_source) && !extractionReviewed;
  const extractionBadgeClass = extractionSource === 'notebooklm'
    ? 'badge-green'
    : extractionSource === 'openai'
      ? 'badge-blue'
      : extractionSource
        ? 'badge-amber'
        : 'badge-gray';
  const extractionLabel = extractionSource || 'unknown';

  const tabs = [
    { label: 'Unit Setup', disabled: false },
    { label: 'Attendance', disabled: !unit },
    { label: 'Session Active', disabled: !session },
  ];

  el.innerHTML = `
    <div class="view-container">

      ${_workflowEntryContext?.source === 'calendar' ? `
      <div class="mb-4 rounded-2xl border border-blue-200 bg-blue-50 px-4 py-3 flex items-start justify-between gap-3">
        <div>
          <p class="text-[13px] font-semibold text-blue-800">Opened from Calendar</p>
          <p class="text-[12px] text-blue-700 mt-1">
            ${_escapeHtml(_workflowEntryContext.session_label || 'Selected session')}
            ${_workflowEntryContext.session_date ? ` • ${_escapeHtml(fmtDate(_workflowEntryContext.session_date))}` : ''}
          </p>
        </div>
        <div class="flex items-center gap-2 flex-wrap">
          <button id="btn-return-to-calendar" class="btn btn-ghost btn-sm">Back to Calendar</button>
          <button id="btn-dismiss-workflow-entry" class="btn btn-ghost btn-sm">Dismiss</button>
        </div>
      </div>` : ''}

      <!-- Live session banner -->
      ${session ? `
      <div class="live-banner">
        <div class="live-dot"></div>
        <div class="live-banner-copy">
          <span class="live-banner-title">Session in progress${session.unit_session_number ? ` • Unit Session ${session.unit_session_number}` : ''}</span>
          <span class="live-banner-meta">Started at ${fmtTime(session.start_time)} | ${fmtDate(session.session_date || session.date)}</span>
        </div>
        <button id="btn-end-session-banner"
          class="btn btn-danger btn-sm">End Session</button>
      </div>` : ''}

      <!-- Tab strip -->
      <div class="card overflow-hidden">
        <div class="workflow-top-tabs border-b border-slate-100">
          ${tabs.map((t, i) => `
          <button class="tab-btn flex-1 justify-center ${i === _activeTab ? 'active' : ''} ${t.disabled ? 'disabled-tab' : ''}"
                  data-tab="${i}">${t.label}</button>`).join('')}
        </div>

        <!-- TAB 0: Unit Setup -->
        <div class="${_activeTab === 0 ? 'block' : 'hidden'}">
          <div class="p-5 flex flex-col gap-5">
            ${unit ? `
            <!-- Current unit: progress ring + info -->
            <div class="grid grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)] gap-4 items-start">
              <div class="rounded-3xl border border-slate-200 bg-[linear-gradient(180deg,rgba(248,250,252,0.9),rgba(255,255,255,0.98))] p-4 shadow-sm">
                <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Current Unit Progress</p>
                <div class="mt-3 flex items-center gap-4">
                  <svg width="96" height="96" class="-rotate-90 flex-shrink-0">
                    <circle cx="48" cy="48" r="${r}" stroke-width="8" class="progress-ring-track"/>
                    <circle cx="48" cy="48" r="${r}" stroke-width="8"
                      stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
                      class="progress-ring-fill transition-all duration-500"/>
                  </svg>
                  <div class="min-w-0">
                    <div class="text-[34px] font-bold text-slate-800 tracking-tight leading-none">${pct}%</div>
                    <div class="text-[12px] text-slate-400 mt-1">${done}/${total} items done</div>
                    <p class="mt-3 text-[12px] leading-relaxed text-slate-500">The checklist is the live progress record for this unit.</p>
                  </div>
                </div>
              </div>
              <div class="rounded-3xl border border-slate-200 bg-white p-4 shadow-sm flex flex-col gap-4">
                <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div class="min-w-0">
                    <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Current Unit</p>
                    <h2 class="mt-1 text-[24px] font-semibold tracking-tight leading-tight text-slate-800 break-words">${unit.title || unit.name || ''}</h2>
                    <p class="text-[12px] text-slate-500 mt-1">Created ${fmtDate(unit.created_at || unit.createdAt)}</p>
                    <div class="flex items-center gap-2 flex-wrap mt-3">
                      ${unit.unit_type ? `<span class="badge badge-blue">${unit.unit_type}</span>` : ''}
                      <span class="badge ${extractionBadgeClass}">Extraction ${_escapeHtml(extractionLabel)}</span>
                      <span class="badge ${extractionReviewPending ? 'badge-amber' : 'badge-green'}">${extractionReviewPending ? 'Review Pending' : 'Reviewed'}</span>
                    </div>
                  </div>
                  <div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3 lg:max-w-[320px]">
                    <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Focus For Now</p>
                    <p class="mt-2 text-[12px] leading-relaxed text-slate-700">${extractionReviewPending ? 'Approve the extracted checklist once the structure looks right, then continue planning and teaching from it.' : 'The checklist is ready to drive planning and teaching. Keep building one reliable layer at a time.'}</p>
                  </div>
                </div>
                ${extractionError ? `<div class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-[12px] text-amber-800">Provider note: ${_escapeHtml(extractionError)}</div>` : ''}
                ${extractionReviewPending ? `<div class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-[12px] text-amber-800">Review the extracted checklist before you rely on it for teaching.</div>` : ''}
                <div class="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-3 items-start">
                  <div class="rounded-2xl border border-slate-200 bg-slate-50/70 px-4 py-3">
                    <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Main Actions</p>
                    <div class="mt-3 flex gap-2 flex-wrap">
                      ${!session ? `<button id="btn-start-session" class="btn btn-success">Start Session</button>` : ''}
                      ${unit.document_name ? `<button id="btn-download-unit-doc" class="btn btn-secondary btn-sm">Unit PDF</button>` : ''}
                      <button id="btn-toggle-extraction-review" class="btn ${extractionReviewPending ? 'btn-primary' : 'btn-secondary'} btn-sm">${extractionReviewPending ? 'Approve Extraction' : 'Mark Needs Review'}</button>
                      <button id="btn-rerun-ai-extraction" class="btn btn-secondary btn-sm">Re-run AI</button>
                      <button id="btn-plan-active-unit" class="btn btn-secondary btn-sm">Plan Sessions</button>
                      <button id="btn-add-item-root" class="btn btn-secondary btn-sm">Add Item</button>
                    </div>
                  </div>
                  <div class="flex gap-2 flex-wrap lg:justify-end">
                    <button id="btn-close-unit" class="btn btn-ghost btn-sm !text-slate-400">Close Unit</button>
                    <button id="btn-delete-unit" class="btn btn-danger btn-sm btn-delete-unit" data-unit-id="${unit.id}">Delete Unit</button>
                  </div>
                </div>
              </div>
            </div>
            ${previewSessionNumber ? `
            <div class="rounded-3xl border border-blue-200 bg-[linear-gradient(180deg,rgba(239,246,255,0.95),rgba(255,255,255,0.98))] p-4 flex flex-col gap-4 shadow-sm">
              <div class="grid grid-cols-1 xl:grid-cols-[minmax(0,1.1fr)_minmax(260px,0.9fr)] gap-3 items-start">
                <div class="rounded-2xl border border-white/80 bg-white/85 px-4 py-4 shadow-sm">
                  <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Calendar Session Prep</p>
                  <p class="mt-1 text-[18px] font-semibold tracking-tight text-slate-800">${_escapeHtml(_workflowEntryContext?.session_label || `Unit Session ${previewSessionNumber}`)}</p>
                  <p class="mt-1 text-[12px] text-slate-500">${_workflowEntryContext?.session_date ? _escapeHtml(fmtDate(_workflowEntryContext.session_date)) : 'Scheduled from calendar'}</p>
                  <div class="mt-3 flex items-center gap-2 flex-wrap">
                    <span class="badge ${previewRouteStatus.className}">${_escapeHtml(previewRouteStatus.label)}</span>
                    ${previewMatchedChecklist.length ? `<span class="badge badge-gray">${previewMatchedChecklist.length} matched row${previewMatchedChecklist.length === 1 ? '' : 's'}</span>` : ''}
                  </div>
                </div>
                <div class="rounded-2xl border border-white/80 bg-white/90 px-4 py-4 shadow-sm">
                  <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Ready To Do</p>
                  <p class="mt-2 text-[12px] leading-relaxed text-slate-700">${previewMatchedChecklist.length ? _escapeHtml(previewRouteStatus.hint) : 'Review the planned route below, then start this session when you are ready to teach.'}</p>
                  <div class="mt-3 flex gap-2 flex-wrap">
                    ${!session ? `<button id="btn-start-preview-session" class="btn btn-success btn-sm">Start This Session</button>` : ''}
                  </div>
                </div>
              </div>
              <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
                <div class="rounded-2xl border border-slate-200 bg-white p-3">
                  <h4 class="text-[12px] font-semibold text-slate-700">Planned Session Route</h4>
                  <div class="mt-2">
                    ${previewSessionPlanTree.length
                      ? _renderSessionPlannedTree(previewSessionPlanTree)
                      : '<p class="text-[12px] text-slate-500">No planned checklist flow saved for this unit session yet.</p>'}
                  </div>
                </div>
                <div class="rounded-2xl border border-slate-200 bg-white p-3">
                  <h4 class="text-[12px] font-semibold text-slate-700">Teacher Prep Suggestions</h4>
                  <div class="mt-2">
                    ${_renderSessionPlaybookPreview(
                      activeUnitMap,
                      previewSessionPlanTitles,
                      previewSessionPlanPaths
                        .map(row => Array.isArray(row?.path) && row.path.length > 1 ? row.path.slice(0, -1) : [])
                        .filter(path => path.length),
                    )}
                  </div>
                </div>
              </div>
              ${previewResumeItem ? `
                <div>
                  ${_renderPreviewNextFocusActions(previewResumeSectionPlan, previewResumePlaybookEntry, previewResumeItem.title, { classId, unitId: unit?.id })}
                </div>` : ''}
            </div>` : ''}
            <!-- Checklist tree -->
            ${checklist.length ? `
            <div class="flex flex-col gap-2 checklist-dnd-root" data-checklist-dnd-root>
              <div class="flex items-start justify-between gap-3 mb-1 flex-wrap">
                <div class="min-w-0">
                  <h4 class="text-[12px] font-semibold text-slate-600">Checklist</h4>
                  <div class="mt-1 flex items-center gap-2 flex-wrap">
                    ${previewSessionNumber ? `<span class="badge badge-blue">Focused on Session ${previewSessionNumber}</span>` : ''}
                    ${previewSessionNumber && _workflowPreviewFocusOnly ? `<span class="badge badge-green">Planned route only</span>` : ''}
                    ${previewSessionNumber && _workflowPreviewFocusOnly && _workflowPreviewHideDone ? `<span class="badge badge-amber">Remaining only</span>` : ''}
                  </div>
                </div>
                <div class="flex items-center gap-1 flex-wrap">
                  ${previewSessionNumber ? `<button id="btn-checklist-preview-focus-toggle" class="btn btn-ghost btn-sm !text-blue-600" title="Switch between the planned route and the full unit checklist">${_workflowPreviewFocusOnly ? 'Show Full Unit' : 'Show Planned Route Only'}</button>` : ''}
                  ${previewSessionNumber && previewMatchedDone > 0 ? `<button id="btn-checklist-preview-hide-done-toggle" class="btn btn-ghost btn-sm !text-amber-700" title="Hide or show completed rows inside the planned route">${_workflowPreviewHideDone ? 'Show Completed Rows' : 'Hide Completed Rows'}</button>` : ''}
                  <button id="btn-checklist-expand-all" class="btn btn-ghost btn-sm !text-slate-500" title="Expand all checklist branches">Expand All</button>
                  <button id="btn-checklist-collapse-all" class="btn btn-ghost btn-sm !text-slate-500" title="Collapse all checklist branches">Collapse All</button>
                </div>
              </div>
              ${previewSessionNumber ? `
              <div class="rounded-xl border border-blue-100 bg-blue-50/70 px-3 py-2.5 mb-1">
                <div class="flex items-start gap-2">
                  <span class="text-[10px] font-bold text-blue-700 mt-0.5">FOCUS</span>
                  <p class="text-[11px] text-blue-700 leading-tight">
                  ${_workflowPreviewFocusOnly
                    ? `${_workflowPreviewHideDone
                      ? `Showing only the remaining planned route for ${_escapeHtml(_workflowEntryContext?.session_label || `Unit Session ${previewSessionNumber}`)}.`
                      : `Showing only the planned route for ${_escapeHtml(_workflowEntryContext?.session_label || `Unit Session ${previewSessionNumber}`)}.`} Use "Show Full Unit" if you want the complete checklist.`
                    : `Highlighted rows belong to the planned route for ${_escapeHtml(_workflowEntryContext?.session_label || `Unit Session ${previewSessionNumber}`)}.`}
                  </p>
                </div>
              </div>` : ''}
              ${previewSessionNumber && previewSummaryBadges.length ? `
              <div class="flex flex-wrap gap-2 px-1 mb-1">
                ${previewSummaryBadges.map(label => `<span class="badge badge-gray">${_escapeHtml(label)}</span>`).join('')}
              </div>` : ''}
              <div class="rounded-xl border border-blue-100/70 bg-blue-50/40 px-3 py-2 mb-1">
                <p class="text-[11px] text-blue-700 leading-tight">
                  <span class="font-semibold">Reorder:</span> drag a row and drop it before, inside, or after another row.
                </p>
              </div>
              ${previewSessionNumber && _workflowPreviewFocusOnly && _workflowPreviewHideDone && !displayChecklist.length ? `
              <div class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">
                All planned rows for this session are already completed. Use <span class="font-semibold">Show Completed Rows</span> if you want to review them.
              </div>` : ''}
              ${displayChecklist.map(item => {
    const meta = moveMeta.get(item.id) || {};
    const itemId = Number(item.id);
    const isDone = Boolean(item?.is_completed || item?.done);
    const canCheckInSetup = Boolean(session) && !isDone;
    const checkTitle = isDone
      ? 'Already completed'
      : (session ? 'Mark done in active session' : 'Start a session first to check items');
    const hasChildren = Number(checklistChildrenCount.get(itemId) || 0) > 0;
    const isCollapsed = hasChildren && _collapsedChecklistIds.has(itemId);
    const depthPad = _checklistDepthPadding(item.depth);
    const previewMatch = previewSessionTitleKeys.has(String(item?.title || '').trim().toLowerCase());
    const previewResumeTarget = previewResumeTargetId != null && itemId === previewResumeTargetId;
    return `
              <div class="todo-node group checklist-draggable-node ${isDone ? 'done' : ''} ${previewMatch ? '!bg-blue-50/70 !border-blue-200' : ''}"
                   data-item-id="${item.id}" data-dnd-target-id="${item.id}" ${previewMatch ? 'data-preview-match="1"' : ''} ${previewResumeTarget ? 'data-preview-scroll-target="1"' : ''}
                   style="padding-left:${depthPad}px">
                ${hasChildren
      ? `<button class="btn btn-ghost btn-sm !text-slate-500 btn-checklist-toggle" data-item-id="${item.id}" title="${isCollapsed ? 'Expand branch' : 'Collapse branch'}">${isCollapsed ? '+' : '-'}</button>`
      : '<span class="inline-block w-6 h-6 flex-shrink-0"></span>'}
                <button class="w-[18px] h-[18px] rounded-[4px] border-2 flex-shrink-0 flex items-center justify-center
                     transition-all mt-px text-[10px] btn-unit-check
                     ${isDone ? 'bg-green-600 border-green-600 text-white' : 'border-slate-300 bg-white hover:border-green-400'} ${canCheckInSetup ? '' : 'opacity-70'}"
                     data-item-id="${item.id}"
                     title="${checkTitle}"
                     ${canCheckInSetup ? '' : 'disabled'}>
                  ${isDone ? 'Y' : ''}
                </button>
                <span class="todo-title text-[13px] leading-snug flex-1">${item.title}</span>
                ${previewResumeTarget ? `<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 flex-shrink-0">Resume here</span>` : previewMatch ? `<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700 flex-shrink-0">Planned now</span>` : ''}
                ${item.item_kind && item.item_kind !== 'other' ? `<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500 flex-shrink-0">${item.item_kind}</span>` : ''}
                <div class="row-hover-actions flex items-center gap-1 ml-auto flex-wrap rounded-full border border-slate-200 bg-white/90 px-1.5 py-1 shadow-sm">
                  <button class="btn btn-ghost btn-sm !text-slate-500 btn-item-up ${meta.canUp ? '' : 'opacity-40 pointer-events-none'}" data-item-id="${item.id}" title="Move up">↑</button>
                  <button class="btn btn-ghost btn-sm !text-slate-500 btn-item-down ${meta.canDown ? '' : 'opacity-40 pointer-events-none'}" data-item-id="${item.id}" title="Move down">↓</button>
                  <button class="btn btn-ghost btn-sm !text-slate-500 btn-item-indent ${meta.canIndent ? '' : 'opacity-40 pointer-events-none'}" data-item-id="${item.id}" title="Nest under previous">→</button>
                  <button class="btn btn-ghost btn-sm !text-slate-500 btn-item-outdent ${meta.canOutdent ? '' : 'opacity-40 pointer-events-none'}" data-item-id="${item.id}" title="Move one level up">←</button>
                  <button class="btn btn-ghost btn-sm !text-slate-400 todo-drag-handle transition-all hover:!text-blue-500" data-drag-item-id="${item.id}" draggable="true" title="Drag to reorder / nest">⋮⋮</button>
                  <div class="h-4 w-px bg-slate-200 mx-0.5"></div>
                  <button class="btn btn-ghost btn-sm !text-slate-500 btn-item-add-child" data-item-id="${item.id}" title="Add child">+Child</button>
                  <button class="btn btn-ghost btn-sm !text-blue-600 btn-item-edit" data-item-id="${item.id}" data-item-kind="${item.item_kind || 'other'}" data-item-title="${_escapeHtmlAttr(item.title)}" title="Edit item">Edit</button>
                  <button class="btn btn-ghost btn-sm !text-red-600 btn-item-delete" data-item-id="${item.id}" title="Delete item">Delete</button>
                </div>
              </div>`;
  }).join('')}
              <div class="todo-root-dropzone text-[11px] text-slate-500" data-dnd-root-drop>Drop here to move item to root level (end)</div>
            </div>` : '<p class="text-[13px] text-slate-400">No checklist items for this unit.</p>'}
            ` : `
            <!-- No active unit -->
            <div class="rounded-3xl border border-dashed border-slate-200 bg-[linear-gradient(180deg,rgba(248,250,252,0.85),rgba(255,255,255,0.98))] px-5 py-6 flex flex-col gap-4">
              <div class="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
                <div class="min-w-0">
                  <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Start Here</p>
                  <h3 class="mt-1 text-[22px] font-semibold tracking-tight text-slate-800">No active unit</h3>
                  <p class="mt-2 text-[13px] leading-relaxed text-slate-500 max-w-[640px]">Create the next unit below or extract its checklist from a PDF. Once the checklist is right, we build the rest of the workflow on top of it.</p>
                </div>
                <div class="flex flex-wrap gap-2 text-[11px]">
                  <span class="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600">1. Create or extract</span>
                  <span class="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600">2. Review checklist</span>
                  <span class="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600">3. Start teaching</span>
                </div>
              </div>
              <div class="rounded-2xl border border-slate-200 bg-white px-4 py-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p class="text-[12px] font-semibold text-slate-700">Next step</p>
                  <p class="mt-1 text-[12px] text-slate-500">Use the creation panel below to add a unit manually or extract one from PDF.</p>
                </div>
                <span class="text-[18px] text-slate-300 self-end sm:self-auto">↓</span>
              </div>
            </div>`}

            <!-- Create unit form -->
            <div class="bg-[linear-gradient(180deg,rgba(248,250,252,0.96),rgba(255,255,255,0.98))] rounded-3xl border border-slate-200 p-5 flex flex-col gap-4 shadow-sm">
              <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div class="min-w-0">
                  <h4 class="text-[17px] font-semibold tracking-tight text-slate-800">${unit ? 'Create Next Unit Later' : 'Create Next Unit'}</h4>
                  <p class="mt-1 text-[12px] leading-relaxed text-slate-500 max-w-[680px]">
                    ${unit
                      ? 'Finish or close the current unit first. Then this is where the next extracted checklist enters the workflow.'
                      : 'Start the next unit here. You can create it manually or extract its checklist from a PDF, then build the rest one layer at a time.'}
                  </p>
                </div>
                <div class="flex flex-wrap gap-2 text-[11px]">
                  <span class="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600">Checklist first</span>
                  <span class="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600">PDF extraction ready</span>
                  <span class="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600">One layer at a time</span>
                </div>
              </div>

              ${unit
                ? '<div class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-[12px] text-amber-800">A unit is already active. Close or finish it before creating or extracting the next one.</div>'
                : ''}

              <div class="grid grid-cols-1 xl:grid-cols-[1.05fr_0.95fr] gap-4">
                <div class="rounded-2xl border border-slate-200 bg-white p-4 flex flex-col gap-3">
                  <div>
                    <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Basics</p>
                    <p class="mt-1 text-[12px] text-slate-500">Choose the unit type and give it a clear title.</p>
                  </div>
                  <div>
                    <p class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">Unit Type</p>
                    <div class="unit-type-selector">
                      ${UNIT_TYPES.map(t => `
                      <button class="unit-type-btn ${_selectedUnitType === t.key ? 'selected' : ''} ${unit ? 'cursor-not-allowed' : ''}" data-unit-type="${t.key}" ${unit ? 'disabled' : ''}>
                        <span class="unit-type-icon">${t.icon}</span>
                        ${t.label}
                      </button>`).join('')}
                    </div>
                  </div>
                  <div class="grid grid-cols-1 gap-3">
                    <div class="flex flex-col gap-1">
                      <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Unit Title</label>
                      <input id="unit-name" type="text" placeholder="Unit title (e.g. Chapter 4 - Photosynthesis)" ${unit ? 'disabled' : ''} />
                    </div>
                    <div class="flex flex-col gap-1">
                      <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Planned Hours</label>
                      <input id="unit-planned-hours" type="number" min="0.25" step="0.25" placeholder="Optional, > 0" ${unit ? 'disabled' : ''} />
                    </div>
                  </div>
                </div>

                <div class="rounded-2xl border border-slate-200 bg-white p-4 flex flex-col gap-3">
                  <div>
                    <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Planning</p>
                    <p class="mt-1 text-[12px] text-slate-500">Optionally create the first session plan from the timetable.</p>
                  </div>
                  <div class="rounded-xl border border-slate-200 bg-slate-50/70 p-3 flex flex-col gap-3">
                    <label class="inline-flex items-center gap-2 text-[12px] text-slate-700">
                      <input id="unit-auto-plan-enable" type="checkbox" ${unit ? 'disabled' : ''} />
                      <span class="font-semibold">Auto-create sessions from timetable</span>
                    </label>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div class="flex flex-col gap-1">
                        <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Sessions Count</label>
                        <input id="unit-auto-plan-count" type="number" min="1" max="120" step="1" value="6" disabled />
                      </div>
                      <div class="flex flex-col gap-1">
                        <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Start From</label>
                        <input id="unit-auto-plan-start-date" type="date" value="${_escapeHtml(todayDateValue)}" disabled />
                      </div>
                    </div>
                    <p class="text-[11px] text-slate-500">Uses class emploi, skips blocked Morocco holidays, and jumps to the next valid slot automatically.</p>
                  </div>
                </div>
              </div>

              <p id="unit-form-error" class="text-[12px] text-red-600 hidden"></p>

              <div class="rounded-2xl border border-slate-200 bg-white px-4 py-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Create Or Extract</p>
                  <p class="mt-1 text-[12px] text-slate-500">${unit ? 'Unit creation is paused until the current active unit is closed.' : 'Create manually if you already know the structure, or extract the checklist directly from a PDF.'}</p>
                </div>
                <div class="flex gap-2 flex-wrap sm:flex-nowrap">
                  <button id="btn-create-unit" class="btn btn-primary flex-1 sm:flex-none ${unit ? 'opacity-60 cursor-not-allowed' : ''}" ${unit ? 'disabled title="Close the current active unit first."' : ''}>Create Unit</button>
                  <label id="pdf-upload-label" class="btn btn-secondary flex-1 sm:flex-none cursor-pointer ${unit ? 'opacity-60 pointer-events-none' : ''}" ${unit ? 'title="Close the current active unit first."' : ''}>
                    Extract from PDF
                    <input id="pdf-upload" type="file" accept=".pdf" class="hidden" ${unit ? 'disabled' : ''} />
                  </label>
                </div>
              </div>
            </div>

            ${recentSessions.length ? `
            <!-- Recent sessions -->
            <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm flex flex-col gap-3">
              <div class="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Recent Sessions</p>
                  <p class="mt-1 text-[12px] text-slate-500">A quick read of the most recent classroom activity for this class.</p>
                </div>
                <div class="flex gap-1 flex-wrap">
                  ${RECENT_SESSION_WINDOWS.map(filter => `
                  <button
                    class="btn btn-ghost btn-sm ${_recentWindow === filter.key ? '!bg-slate-200 !text-slate-700' : '!text-slate-500'}"
                    data-recent-window="${filter.key}">${filter.label}</button>
                  `).join('')}
                </div>
              </div>
              ${visibleRecentSessions.length ? `
              <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
                ${visibleRecentSessions.slice(0, 8).map(s => `
              <div class="px-4 py-3 bg-slate-50/80 rounded-2xl border border-slate-200">
                <div class="flex items-center justify-between gap-2 flex-wrap">
                  <div class="min-w-0">
                    <p class="text-[13px] font-semibold text-slate-700">${fmtDate(s.session_date || s.date)}</p>
                    <p class="text-[12px] text-slate-500 mt-0.5">${fmtTime(s.start_time)}${s.end_time ? '  ' + fmtTime(s.end_time) : ' (active)'}</p>
                  </div>
                  ${s.unit_session_number ? `<span class="badge badge-blue">Session ${s.unit_session_number}</span>` : '<span class="badge badge-gray">Session</span>'}
                </div>
                <div class="mt-2 flex items-center gap-2 flex-wrap">
                  <span class="badge badge-green">${s.checked_items_count ?? 0} done</span>
                  ${Number(s.absent_count || 0) > 0 ? `<span class="badge badge-red">${s.absent_count} absent</span>` : ''}
                </div>
              </div>`).join('')}
              </div>` : '<div class="rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-3 text-[12px] text-slate-500">No sessions in this date range.</div>'}
            </div>` : ''}

            ${unit ? `
            <!-- Unit session timeline -->
            <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm flex flex-col gap-3">
              <div class="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Unit Session Timeline</p>
                  <p class="mt-1 text-[12px] text-slate-500">The running record of sessions already captured for this unit.</p>
                </div>
                <button class="btn btn-ghost btn-sm !text-slate-500" data-unit-timeline-retry="${unit.id}">Refresh</button>
              </div>
              ${unitTimelineState.loading && !unitTimelineState.loaded ? `
                <div class="rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-3 text-[12px] text-slate-500">Loading unit sessions...</div>
              ` : ''}
              ${unitTimelineState.error ? `
                <div class="px-3 py-2 bg-red-50 border border-red-200 rounded-xl">
                  <p class="text-[12px] text-red-700">${_escapeHtml(unitTimelineState.error)}</p>
                </div>
              ` : ''}
              ${!unitTimelineState.loading && !unitTimelineState.error && unitTimelineState.sessions.length ? `
                <div class="max-h-[260px] overflow-auto rounded-2xl border border-slate-200">
                  ${unitTimelineState.sessions.map(s => `
                  <div class="px-4 py-3 border-b border-slate-100 last:border-b-0 bg-white">
                    <div class="flex items-center justify-between gap-2 flex-wrap">
                      <div class="flex items-center gap-2 flex-wrap">
                      ${s.unit_session_number ? `<span class="badge badge-blue">Session ${s.unit_session_number}</span>` : '<span class="badge badge-gray">Session</span>'}
                      <span class="text-[12px] font-semibold text-slate-700">${fmtDate(s.session_date || s.date)}</span>
                      <span class="text-[12px] text-slate-500">${fmtTime(s.start_time)}${s.end_time ? ` - ${fmtTime(s.end_time)}` : ''}</span>
                      </div>
                      <span class="badge ${s.end_time ? 'badge-green' : 'badge-amber'}">${s.end_time ? 'Closed' : 'Open'}</span>
                    </div>
                    <div class="mt-2 flex items-center gap-2 flex-wrap">
                      <span class="badge badge-green">${s.checked_items_count ?? 0} done</span>
                      ${Number(s.absent_count || 0) > 0 ? `<span class="badge badge-red">${s.absent_count} absent</span>` : ''}
                      ${s.note ? `<span class="text-[11px] text-slate-500 truncate max-w-[320px]" title="${_escapeHtmlAttr(s.note)}">${_escapeHtml(s.note)}</span>` : ''}
                    </div>
                  </div>`).join('')}
                </div>
              ` : ''}
              ${!unitTimelineState.loading && !unitTimelineState.error && !unitTimelineState.sessions.length ? `
                <div class="rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-3 text-[12px] text-slate-500">No sessions recorded for this unit yet.</div>
              ` : ''}
            </div>` : ''}

            ${closed.length ? `
            <!-- Past units -->
            <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm flex flex-col gap-3">
              <div>
                <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Past Units</p>
                <p class="mt-1 text-[12px] text-slate-500">Closed units stay here so you can reopen the latest one or keep old work archived.</p>
              </div>
              ${closed.map((u, index) => `
              <div class="flex items-center gap-3 px-4 py-3 bg-slate-50/80 rounded-2xl border border-slate-200">
                <div class="flex-1 min-w-0">
                  <span class="text-[13px] text-slate-600 font-semibold truncate block">${u.title || u.name}</span>
                  <p class="text-[11px] text-slate-400 mt-0.5">Closed ${fmtDate(u.closed_at || u.closedAt || u.created_at || u.createdAt)}</p>
                  ${u.unit_type ? `<span class="badge badge-gray" style="font-size:10px">${u.unit_type.replace('_', ' ')}</span>` : ''}
                </div>
                ${!unit && index === 0
          ? `<button class="btn btn-secondary btn-sm btn-reopen-unit" data-unit-id="${u.id}">Re-open</button>`
          : ''}
                <button class="btn btn-danger btn-sm btn-delete-unit" data-unit-id="${u.id}">Delete</button>
                <span class="badge badge-gray opacity-50">Archived</span>
              </div>`).join('')}
            </div>` : ''}
          </div>
        </div>

        <!-- TAB 1: Attendance Grid -->
        <div class="${_activeTab === 1 ? 'block' : 'hidden'}">
          <div class="p-5 flex flex-col gap-4">
            <div class="rounded-2xl border border-slate-200 bg-[linear-gradient(180deg,rgba(248,250,252,0.96),rgba(255,255,255,0.98))] p-4 shadow-sm">
              <div class="grid grid-cols-1 xl:grid-cols-[minmax(0,1.2fr)_minmax(260px,0.8fr)] gap-3 items-start">
                <div class="min-w-0 rounded-2xl border border-white/80 bg-white/75 px-4 py-4 shadow-sm">
                  <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Attendance</p>
                  <h3 class="mt-1 text-[22px] font-semibold tracking-tight text-slate-800">Mark Attendance</h3>
                  <p class="mt-2 text-[12px] leading-relaxed text-slate-500">Tap a student to toggle absent or present before you start or update the session.</p>
                  <div class="mt-3 flex gap-2 flex-wrap">
                    <span class="badge badge-red">${getAbsentIds().size} absent</span>
                    <span class="badge badge-green">${students.length - getAbsentIds().size} present</span>
                    <span class="badge badge-gray">${students.length} total</span>
                  </div>
                </div>
                <div class="rounded-2xl border border-white/80 bg-white/90 px-4 py-4 shadow-sm">
                  <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">What To Do</p>
                  <div class="mt-2 flex flex-col gap-2 text-[12px] text-slate-700">
                    <p>1. Mark who is absent.</p>
                    <p>2. Save attendance when it matches the classroom.</p>
                    <p>3. Keep the rest of the workflow simple.</p>
                  </div>
                </div>
              </div>
            </div>
            ${students.length === 0 ? `
            <div class="empty-state py-12">
              <div class="text-xl font-black opacity-30">ROSTER</div>
              <p class="text-[13px] text-slate-400">No students - import a roster first.</p>
            </div>` : `
            <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div class="flex items-center justify-between gap-2 mb-3 flex-wrap">
                <div>
                  <p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Student Grid</p>
                  <p class="mt-1 text-[11px] text-slate-500">Green means present. Red means absent.</p>
                </div>
              </div>
            <div class="workflow-attendance-grid">
              ${students.map(s => {
            const absent = getAbsentIds().has(s.id);
            return `
                  <div class="attendance-card group relative ${absent ? 'absent' : 'present'}"
                       data-sid="${s.id}"
                       role="button"
                       tabindex="0"
                       aria-pressed="${absent ? 'true' : 'false'}"
                       aria-label="${absent ? 'Mark present: ' : 'Mark absent: '}${_escapeHtmlAttr(s.full_name || 'student')}">
                    <div class="attendance-status-icon">${absent ? 'ABS' : 'OK'}</div>
                    <div class="student-code">${s.student_code || 'ID'}</div>
                    <div class="student-name">${s.full_name || 'N/A'}</div>
                  </div>`;
          }).join('')}
            </div>
            </div>`}
            <div class="rounded-2xl border border-slate-200 bg-white px-4 py-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between shadow-sm">
              <div>
                <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Save Attendance</p>
                <p class="mt-1 text-[12px] text-slate-500">${session ? 'Update the live session attendance after reviewing the grid.' : 'Start the session and save the attendance in one step.'}</p>
              </div>
              <div class="flex gap-2 flex-wrap">
              ${!session ? `<button id="btn-start-session-att" class="btn btn-success">Start Session (save attendance)</button>` : ''}
              ${session ? `<button id="btn-save-attendance" class="btn btn-primary">Update Attendance</button>` : ''}
              </div>
            </div>
          </div>
        </div>

        <!-- TAB 2: Session Active -->
        <div class="${_activeTab === 2 ? 'block' : 'hidden'}">
          <div class="p-5 flex flex-col gap-4">
            ${session ? `
            <div class="rounded-2xl border border-amber-200 bg-[linear-gradient(180deg,rgba(255,247,237,0.96),rgba(255,255,255,0.98))] p-4 sm:p-5 shadow-sm">
              <div class="flex flex-col gap-4">
                <div class="grid grid-cols-1 xl:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.65fr)] gap-3 items-start">
                  <div class="min-w-0 rounded-2xl border border-white/80 bg-white/70 px-4 py-4 shadow-sm">
                    <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-700">Session Active</p>
                    <p class="mt-1 text-[26px] font-semibold tracking-tight leading-tight text-slate-900 break-words">${_escapeHtml(unit?.title || session?.unit_title || 'Active session')}</p>
                    <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-slate-500">
                      <span>${_escapeHtml(fmtDate(session.session_date || session.date))}</span>
                      <span class="text-slate-300">&middot;</span>
                      <span>${_escapeHtml(`Started at ${fmtTime(session.start_time)}`)}</span>
                      ${session?.unit_session_number ? `<span class="text-slate-300">&middot;</span><span>Unit Session ${Number(session.unit_session_number)}</span>` : ''}
                    </div>
                    <div class="mt-3 flex gap-2 flex-wrap">
                      <span class="badge badge-amber">Live now</span>
                      <span class="badge badge-gray">${activeSessionCheckedChecklist.length} checked</span>
                    </div>
                  </div>
                  <div class="rounded-2xl border border-white/80 bg-white/90 px-4 py-4 shadow-sm">
                    <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Focus For Now</p>
                    <p class="mt-2 text-[13px] leading-relaxed text-slate-700">The checklist is the main session record. Check only what was really covered.</p>
                    <p class="mt-2 text-[12px] text-slate-500">We will preserve this structure and use it later when we talk to NotebookLM.</p>
                  </div>
                </div>
                <div class="rounded-2xl border border-amber-100 bg-white/92 px-4 py-3 shadow-sm">
                  <div class="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
                    <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-700">Simple Workflow</p>
                    <div class="flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-slate-700">
                      <span>1. Follow the checklist in teaching order.</span>
                      <span>2. Check only what was really taught.</span>
                      <span>3. Add extra AI tools later, one by one.</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            ${checklist.length ? `
            <div class="flex flex-col gap-1">
              <div class="flex items-center justify-between gap-2 mb-1">
                <div>
                  <h4 class="text-[12px] font-semibold text-slate-600">Session Checklist</h4>
                  <p class="text-[11px] text-slate-400 mt-1">This checklist is the main structure we preserve.</p>
                </div>
                <div class="flex items-center gap-1">
                  <button data-checklist-expand-all class="btn btn-ghost btn-sm !text-slate-500" title="Expand all checklist branches">Expand All</button>
                  <button data-checklist-collapse-all class="btn btn-ghost btn-sm !text-slate-500" title="Collapse all checklist branches">Collapse All</button>
                </div>
              </div>
              <div class="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                <div class="flex items-center justify-between gap-2 mb-2 flex-wrap">
                  <div>
                    <p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Teaching Structure</p>
                    <p class="mt-1 text-[11px] text-slate-500">Keep this tree clean. We will reuse it when communicating with NotebookLM.</p>
                  </div>
                </div>
              ${visibleChecklist.map(item => {
      const itemId = Number(item.id);
      const hasChildren = Number(checklistChildrenCount.get(itemId) || 0) > 0;
      const isCollapsed = hasChildren && _collapsedChecklistIds.has(itemId);
      const depthPad = _checklistDepthPadding(item.depth);
      const isStructural = _isStructuralChecklistItem(item) || hasChildren;
      return `
              <div class="todo-node group ${item.is_completed || item.done ? 'done' : ''} ${isStructural ? 'cursor-default' : ''}"
                   data-item-id="${item.id}" data-session-id="${session.id}" data-class-id="${classId}"
                   style="padding-left:${depthPad}px"
                   role="${isStructural ? 'group' : 'button'}" tabindex="${isStructural ? '-1' : '0'}"
                   aria-pressed="${isStructural ? 'false' : (item.is_completed || item.done ? 'true' : 'false')}"
                   aria-label="${isStructural ? _escapeHtmlAttr(`Checklist heading: ${item.title}`) : _escapeHtmlAttr(`Toggle checklist item: ${item.title}`)}">
                ${hasChildren
      ? `<button class="btn btn-ghost btn-sm !text-slate-500 btn-checklist-toggle" data-item-id="${item.id}" title="${isCollapsed ? 'Expand branch' : 'Collapse branch'}" aria-label="${isCollapsed ? 'Expand branch' : 'Collapse branch'}">${isCollapsed ? '+' : '-'}</button>`
      : '<span class="inline-block w-6 h-6 flex-shrink-0"></span>'}
                <div class="w-[17px] h-[17px] rounded-[4px] border-2 flex-shrink-0 flex items-center justify-center
                     transition-all mt-px text-[10px] cursor-pointer
                     ${item.is_completed || item.done ? 'bg-green-600 border-green-600 text-white' : isStructural ? 'border-slate-200 bg-slate-50 text-slate-300' : 'border-slate-300 bg-white hover:border-green-400'}">
                  ${item.is_completed || item.done ? 'Y' : (isStructural ? '·' : '')}
                </div>
                <span class="todo-title text-[12px] leading-snug flex-1">${item.title}</span>
                ${isStructural ? '<span class="text-[10px] text-slate-400 whitespace-nowrap">Auto-completes with child rows</span>' : ''}
                ${hasChildren ? `<button class="btn btn-ghost btn-sm !text-sky-600 btn-checklist-group-complete" data-item-id="${item.id}" title="Mark all unfinished lesson steps under this heading">Check group</button>` : ''}
              </div>`;
    }).join('')}
              </div>
            </div>` : '<p class="text-[13px] text-slate-400">No checklist for this unit.</p>'}
            <button id="btn-end-session"
              class="btn btn-danger self-start mt-2">End Session</button>
            ` : `
            <div class="empty-state py-12">
              <div class="text-xl font-black opacity-30 mb-4">IDLE</div>
              <p class="text-[13px] text-slate-400">No active session. Start one from Unit Setup or Attendance tab.</p>
            </div>`}
          </div>
        </div>
      </div>
    </div>`;

  _bindWorkflowEvents(el, classId);

  const previewScrollKey = previewSessionNumber && unit?.id && !session && _activeTab === 0
    ? `${Number(unit.id)}:${Number(previewSessionNumber)}:${String(_workflowEntryContext?.session_date || '')}`
    : null;
  if (previewScrollKey) {
    if (_workflowPreviewScrollKey !== previewScrollKey) {
      _workflowPreviewScrollKey = previewScrollKey;
      queueMicrotask(() => {
        const target = el.querySelector('[data-preview-scroll-target="1"]') || el.querySelector('[data-preview-match="1"]');
        target?.scrollIntoView({ block: 'center', behavior: 'smooth' });
      });
    }
  } else {
    _workflowPreviewScrollKey = null;
  }
}

/*  flat item list from nested tree  */
function _flatItems(item) {
  const result = [item];
  if (item.children) item.children.forEach(c => result.push(..._flatItems(c)));
  return result;
}
/* also expose on unit */
function _checklist(unit) {
  if (!unit) return [];
  // Backend returns WorkflowUnitOut.checklist; keep fallbacks for legacy payloads.
  const roots = unit.checklist ?? unit.checklist_items ?? unit.children ?? [];
  return Array.isArray(roots) ? roots.flatMap(_flatItems) : [];
}

function _syncChecklistCollapseState(unit, items) {
  const nextUnitId = Number(unit?.id || 0) || null;
  if (_checklistCollapseUnitId !== nextUnitId) {
    _checklistCollapseUnitId = nextUnitId;
    _collapsedChecklistIds.clear();
  }
  const validIds = new Set((items || []).map(row => Number(row.id)).filter(Number.isFinite));
  Array.from(_collapsedChecklistIds).forEach(itemId => {
    if (!validIds.has(itemId)) _collapsedChecklistIds.delete(itemId);
  });
}

function _ensureChecklistFocusVisible(items, titleKeys) {
  if (!Array.isArray(items) || !items.length || !(titleKeys instanceof Set) || !titleKeys.size) return;
  const byId = new Map();
  items.forEach(row => {
    const itemId = Number(row?.id);
    if (!Number.isFinite(itemId) || itemId <= 0) return;
    byId.set(itemId, row);
  });
  items.forEach(row => {
    const titleKey = String(row?.title || '').trim().toLowerCase();
    if (!titleKey || !titleKeys.has(titleKey)) return;
    let currentId = Number(row?.id || 0);
    while (Number.isFinite(currentId) && currentId > 0) {
      _collapsedChecklistIds.delete(currentId);
      const current = byId.get(currentId);
      if (!current || current.parent_item_id == null) break;
      currentId = Number(current.parent_item_id || 0);
    }
  });
}

function _buildChecklistChildrenCount(items) {
  const counts = new Map();
  (items || []).forEach(row => {
    const itemId = Number(row.id);
    if (!Number.isFinite(itemId)) return;
    if (!counts.has(itemId)) counts.set(itemId, 0);
  });
  (items || []).forEach(row => {
    const parentId = row.parent_item_id == null ? null : Number(row.parent_item_id);
    if (parentId == null || !Number.isFinite(parentId)) return;
    counts.set(parentId, Number(counts.get(parentId) || 0) + 1);
  });
  return counts;
}

function _collectPreviewFocusIds(items, titleKeys) {
  const rows = Array.isArray(items) ? items : [];
  const keys = titleKeys instanceof Set ? titleKeys : new Set();
  if (!rows.length || !keys.size) return new Set();
  const byId = new Map();
  rows.forEach(row => {
    const itemId = Number(row?.id);
    if (!Number.isFinite(itemId) || itemId <= 0) return;
    byId.set(itemId, row);
  });
  const focusIds = new Set();
  rows.forEach(row => {
    const itemId = Number(row?.id);
    const titleKey = String(row?.title || '').trim().toLowerCase();
    if (!Number.isFinite(itemId) || itemId <= 0 || !keys.has(titleKey)) return;
    let currentId = itemId;
    while (Number.isFinite(currentId) && currentId > 0 && !focusIds.has(currentId)) {
      focusIds.add(currentId);
      const current = byId.get(currentId);
      if (!current || current.parent_item_id == null) break;
      currentId = Number(current.parent_item_id || 0);
    }
  });
  return focusIds;
}

function _collectChecklistFocusIdsByItemIds(items, itemIds) {
  const rows = Array.isArray(items) ? items : [];
  const selectedIds = new Set((Array.isArray(itemIds) ? itemIds : []).map(value => Number(value)).filter(value => Number.isFinite(value) && value > 0));
  if (!rows.length || !selectedIds.size) return new Set();
  const byId = new Map(rows.map(row => [Number(row?.id || 0), row]).filter(([id]) => id > 0));
  const focusIds = new Set();
  selectedIds.forEach(itemId => {
    let currentId = Number(itemId);
    while (Number.isFinite(currentId) && currentId > 0 && !focusIds.has(currentId)) {
      focusIds.add(currentId);
      const current = byId.get(currentId);
      if (!current || current.parent_item_id == null) break;
      currentId = Number(current.parent_item_id || 0);
    }
  });
  return focusIds;
}

function _buildChecklistContextMap(items) {
  const rows = Array.isArray(items) ? items : [];
  const byId = new Map(rows.map(row => [Number(row?.id || 0), row]).filter(([id]) => id > 0));
  const structuralKinds = new Set(['chapter', 'section', 'subsection']);
  const contextMap = new Map();

  const buildFor = itemId => {
    if (contextMap.has(itemId)) return contextMap.get(itemId);
    let current = byId.get(itemId) || null;
    const visited = new Set();
    const itemPath = [];
    const sectionPath = [];
    while (current && !visited.has(Number(current?.id || 0))) {
      const currentId = Number(current?.id || 0);
      if (!currentId) break;
      visited.add(currentId);
      const title = String(current?.title || '').trim();
      const kind = String(current?.item_kind || '').trim().toLowerCase();
      if (title) {
        itemPath.push(title);
        if (structuralKinds.has(kind)) sectionPath.push(title);
      }
      const parentId = current?.parent_item_id == null ? 0 : Number(current.parent_item_id || 0);
      current = parentId > 0 ? byId.get(parentId) || null : null;
    }
    itemPath.reverse();
    sectionPath.reverse();
    const normalizedSectionPath = sectionPath.length
      ? sectionPath
      : (itemPath.length > 1 ? itemPath.slice(0, -1) : itemPath.slice());
    const context = {
      itemPath,
      sectionPath: normalizedSectionPath,
      itemPathKey: itemPath.map(value => String(value || '').trim().toLowerCase()).filter(Boolean).join('|'),
      sectionPathKey: normalizedSectionPath.map(value => String(value || '').trim().toLowerCase()).filter(Boolean).join('|'),
    };
    contextMap.set(itemId, context);
    return context;
  };

  rows.forEach(row => {
    const itemId = Number(row?.id || 0);
    if (itemId > 0) buildFor(itemId);
  });
  return contextMap;
}

function _deriveChecklistSectionPaths(items, targetIds = []) {
  const rows = Array.isArray(items) ? items : [];
  const selected = new Set((Array.isArray(targetIds) ? targetIds : []).map(value => Number(value)).filter(value => Number.isFinite(value) && value > 0));
  if (!selected.size || !rows.length) return [];
  const contextMap = _buildChecklistContextMap(rows);
  const output = [];
  const seen = new Set();
  selected.forEach(itemId => {
    const context = contextMap.get(Number(itemId)) || null;
    const normalizedSectionPath = Array.isArray(context?.sectionPath) ? context.sectionPath : [];
    const key = normalizedSectionPath.join(' > ').toLowerCase();
    if (!normalizedSectionPath.length || seen.has(key)) return;
    seen.add(key);
    output.push(normalizedSectionPath);
  });
  return output;
}

function _visibleChecklistRows(items, collapsedIds) {
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) return [];
  const byParent = _groupChecklistRowsByParent(rows);
  const visible = [];
  const visit = (parentId) => {
    const siblings = byParent.get(_parentKey(parentId)) || [];
    siblings.forEach(row => {
      const itemId = Number(row.id);
      visible.push(row);
      if (!Number.isFinite(itemId) || collapsedIds.has(itemId)) return;
      visit(itemId);
    });
  };
  visit(null);
  return visible;
}

function _collapseChecklistAllParents(items) {
  _collapsedChecklistIds.clear();
  const childrenCount = _buildChecklistChildrenCount(items);
  childrenCount.forEach((count, itemId) => {
    if (count > 0) _collapsedChecklistIds.add(Number(itemId));
  });
}

function _checklistDepthPadding(depth) {
  const value = Number(depth);
  const safeDepth = Number.isFinite(value) ? Math.max(0, Math.min(value, 8)) : 0;
  return 12 + safeDepth * 18;
}

function _findDescendantItems(items, rootId) {
  const byParent = new Map();
  (items || []).forEach(row => {
    const key = row.parent_item_id == null ? 'root' : String(row.parent_item_id);
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(row);
  });

  const result = [];
  const frontier = [Number(rootId)];
  while (frontier.length) {
    const current = frontier.shift();
    const children = byParent.get(String(current)) || [];
    children.forEach(child => {
      result.push(child);
      frontier.push(Number(child.id));
    });
  }
  return result;
}

function _parentKey(parentId) {
  return parentId == null ? 'root' : String(parentId);
}

function _groupChecklistRowsByParent(rows) {
  const byParent = new Map();
  rows.forEach(row => {
    const key = _parentKey(row.parent_item_id);
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key).push(row);
  });
  byParent.forEach(siblings => {
    siblings.sort((a, b) => {
      const posDiff = Number(a.position || 0) - Number(b.position || 0);
      if (posDiff !== 0) return posDiff;
      return Number(a.id) - Number(b.id);
    });
  });
  return byParent;
}

function _reindexChecklistSiblings(siblings) {
  siblings.forEach((row, index) => {
    row.position = index + 1;
  });
}

function _normalizeChecklistDraft(rows) {
  const byParent = _groupChecklistRowsByParent(rows);
  byParent.forEach(_reindexChecklistSiblings);
  return rows;
}

function _buildChecklistReorderDraft(items) {
  return (items || []).map(item => ({
    id: Number(item.id),
    parent_item_id: item.parent_item_id == null ? null : Number(item.parent_item_id),
    position: Number(item.position || 0),
  }));
}

function _buildChecklistMoveMeta(items) {
  const draft = _buildChecklistReorderDraft(items);
  const byParent = _groupChecklistRowsByParent(draft);
  const meta = new Map();
  byParent.forEach(siblings => {
    siblings.forEach((row, index) => {
      meta.set(row.id, {
        canUp: index > 0,
        canDown: index < siblings.length - 1,
        canIndent: index > 0,
        canOutdent: row.parent_item_id != null,
      });
    });
  });
  return meta;
}

function _toLocalDate(value) {
  if (!value) return null;
  const text = String(value).trim();
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (match) {
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 0, 0, 0, 0);
  }
  const parsed = new Date(text);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function _startOfDay(value) {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate(), 0, 0, 0, 0);
}

function _weekStartMonday(value) {
  const start = _startOfDay(value);
  const dayIndex = (start.getDay() + 6) % 7; // Monday=0 ... Sunday=6
  start.setDate(start.getDate() - dayIndex);
  return start;
}

function _matchesRecentWindow(session, windowKey) {
  if (windowKey === 'all') return true;
  const dateValue = _toLocalDate(session?.session_date || session?.date);
  if (!dateValue) return false;

  const day = _startOfDay(dateValue).getTime();
  const now = new Date();
  const today = _startOfDay(now);

  if (windowKey === 'today') {
    return day === today.getTime();
  }
  if (windowKey === 'week') {
    const weekStart = _weekStartMonday(today);
    const weekEnd = new Date(weekStart);
    weekEnd.setDate(weekEnd.getDate() + 7);
    return day >= weekStart.getTime() && day < weekEnd.getTime();
  }
  if (windowKey === 'month') {
    return (
      dateValue.getFullYear() === now.getFullYear()
      && dateValue.getMonth() === now.getMonth()
    );
  }
  return true;
}

function _filterRecentSessions(sessions, windowKey) {
  const rows = Array.isArray(sessions) ? sessions : [];
  return rows.filter(session => _matchesRecentWindow(session, windowKey));
}

function _moveChecklistItemUp(draft, itemId) {
  const byParent = _groupChecklistRowsByParent(draft);
  const target = draft.find(row => row.id === itemId);
  if (!target) return false;
  const siblings = byParent.get(_parentKey(target.parent_item_id)) || [];
  const index = siblings.findIndex(row => row.id === itemId);
  if (index <= 0) return false;
  [siblings[index - 1], siblings[index]] = [siblings[index], siblings[index - 1]];
  _reindexChecklistSiblings(siblings);
  return true;
}

function _moveChecklistItemDown(draft, itemId) {
  const byParent = _groupChecklistRowsByParent(draft);
  const target = draft.find(row => row.id === itemId);
  if (!target) return false;
  const siblings = byParent.get(_parentKey(target.parent_item_id)) || [];
  const index = siblings.findIndex(row => row.id === itemId);
  if (index < 0 || index >= siblings.length - 1) return false;
  [siblings[index], siblings[index + 1]] = [siblings[index + 1], siblings[index]];
  _reindexChecklistSiblings(siblings);
  return true;
}

function _indentChecklistItem(draft, itemId) {
  const byParent = _groupChecklistRowsByParent(draft);
  const byId = new Map(draft.map(row => [row.id, row]));
  const target = byId.get(itemId);
  if (!target) return false;
  const siblings = byParent.get(_parentKey(target.parent_item_id)) || [];
  const index = siblings.findIndex(row => row.id === itemId);
  if (index <= 0) return false;

  const previousSibling = siblings[index - 1];
  siblings.splice(index, 1);
  _reindexChecklistSiblings(siblings);

  target.parent_item_id = previousSibling.id;
  const newParentKey = _parentKey(previousSibling.id);
  if (!byParent.has(newParentKey)) byParent.set(newParentKey, []);
  const children = byParent.get(newParentKey);
  children.push(target);
  _reindexChecklistSiblings(children);
  return true;
}

function _outdentChecklistItem(draft, itemId) {
  const byParent = _groupChecklistRowsByParent(draft);
  const byId = new Map(draft.map(row => [row.id, row]));
  const target = byId.get(itemId);
  if (!target || target.parent_item_id == null) return false;
  const parent = byId.get(target.parent_item_id);
  if (!parent) return false;

  const currentSiblings = byParent.get(_parentKey(parent.id)) || [];
  const index = currentSiblings.findIndex(row => row.id === itemId);
  if (index < 0) return false;
  currentSiblings.splice(index, 1);
  _reindexChecklistSiblings(currentSiblings);

  const newParentId = parent.parent_item_id == null ? null : parent.parent_item_id;
  const newParentKey = _parentKey(newParentId);
  if (!byParent.has(newParentKey)) byParent.set(newParentKey, []);
  const targetSiblings = byParent.get(newParentKey);
  const parentIndex = targetSiblings.findIndex(row => row.id === parent.id);
  const insertAt = parentIndex >= 0 ? parentIndex + 1 : targetSiblings.length;

  target.parent_item_id = newParentId;
  targetSiblings.splice(insertAt, 0, target);
  _reindexChecklistSiblings(targetSiblings);
  return true;
}

function _checklistDraftSignature(rows) {
  return (rows || [])
    .slice()
    .sort((a, b) => Number(a.id) - Number(b.id))
    .map(row => `${Number(row.id)}:${row.parent_item_id == null ? 'root' : Number(row.parent_item_id)}:${Number(row.position || 0)}`)
    .join('|');
}

function _collectChecklistDescendantIds(rows, rootId) {
  const childrenByParent = new Map();
  (rows || []).forEach(row => {
    const key = _parentKey(row.parent_item_id);
    if (!childrenByParent.has(key)) childrenByParent.set(key, []);
    childrenByParent.get(key).push(Number(row.id));
  });

  const descendants = new Set();
  const frontier = [Number(rootId)];
  while (frontier.length) {
    const parent = frontier.shift();
    const children = childrenByParent.get(String(parent)) || [];
    children.forEach(childId => {
      if (descendants.has(childId)) return;
      descendants.add(childId);
      frontier.push(childId);
    });
  }
  return descendants;
}

function _resolveChecklistDropMode(node, event) {
  const rect = node?.getBoundingClientRect?.();
  if (!rect || !Number.isFinite(rect.height) || rect.height <= 0) return 'after';
  const y = event.clientY - rect.top;
  const topBand = rect.height * 0.28;
  const bottomBand = rect.height * 0.72;
  if (y <= topBand) return 'before';
  if (y >= bottomBand) return 'after';
  return 'inside';
}

function _moveChecklistItemByDrop(draft, dragItemId, targetItemId, mode = 'after') {
  const dragId = Number(dragItemId);
  const normalizedMode = String(mode || 'after').toLowerCase();
  if (!Number.isFinite(dragId) || dragId <= 0) return { ok: false, error: 'Invalid checklist item.' };
  if (!['before', 'after', 'inside', 'root'].includes(normalizedMode)) {
    return { ok: false, error: 'Unsupported drop mode.' };
  }

  const byParent = _groupChecklistRowsByParent(draft);
  const byId = new Map(draft.map(row => [Number(row.id), row]));
  const dragged = byId.get(dragId);
  if (!dragged) return { ok: false, error: 'Checklist item not found.' };

  let target = null;
  let newParentId = null;
  let insertAt = 0;

  if (normalizedMode === 'root') {
    const roots = byParent.get('root') || [];
    newParentId = null;
    insertAt = roots.length;
  } else {
    const targetId = Number(targetItemId);
    if (!Number.isFinite(targetId) || targetId <= 0) return { ok: false, error: 'Drop target is missing.' };
    if (targetId === dragId) return { ok: true, changed: false };

    const descendants = _collectChecklistDescendantIds(draft, dragId);
    if (descendants.has(targetId)) {
      return { ok: false, error: 'Cannot move an item into its own child branch.' };
    }

    target = byId.get(targetId);
    if (!target) return { ok: false, error: 'Drop target is no longer available.' };

    if (normalizedMode === 'inside') {
      newParentId = Number(target.id);
      const children = byParent.get(_parentKey(newParentId)) || [];
      insertAt = children.length;
    } else {
      newParentId = target.parent_item_id == null ? null : Number(target.parent_item_id);
      const siblings = byParent.get(_parentKey(newParentId)) || [];
      const targetIndex = siblings.findIndex(row => Number(row.id) === Number(target.id));
      if (targetIndex < 0) return { ok: false, error: 'Drop target position is invalid.' };
      insertAt = normalizedMode === 'before' ? targetIndex : targetIndex + 1;
    }
  }

  const currentParentId = dragged.parent_item_id == null ? null : Number(dragged.parent_item_id);
  const currentSiblings = byParent.get(_parentKey(currentParentId)) || [];
  const currentIndex = currentSiblings.findIndex(row => Number(row.id) === dragId);
  if (currentIndex < 0) return { ok: false, error: 'Checklist position is invalid.' };

  currentSiblings.splice(currentIndex, 1);
  _reindexChecklistSiblings(currentSiblings);

  const targetKey = _parentKey(newParentId);
  if (!byParent.has(targetKey)) byParent.set(targetKey, []);
  const targetSiblings = byParent.get(targetKey);

  let safeInsertAt = Number.isFinite(insertAt) ? insertAt : targetSiblings.length;
  safeInsertAt = Math.max(0, Math.min(safeInsertAt, targetSiblings.length));
  if (
    (normalizedMode === 'before' || normalizedMode === 'after')
    && newParentId === currentParentId
    && currentSiblings === targetSiblings
    && safeInsertAt > currentIndex
  ) {
    safeInsertAt -= 1;
  }

  dragged.parent_item_id = newParentId;
  targetSiblings.splice(safeInsertAt, 0, dragged);
  _reindexChecklistSiblings(targetSiblings);
  _normalizeChecklistDraft(draft);

  return { ok: true, changed: true };
}

function _bindWorkflowEvents(el, classId) {
  const unitErrorEl = el.querySelector('#unit-form-error');
  const setUnitFormError = (message) => {
    if (!unitErrorEl) return;
    const text = String(message || '').trim();
    unitErrorEl.textContent = text;
    unitErrorEl.classList.toggle('hidden', !text);
  };

  /*  tab switching  */
  el.querySelectorAll('[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.classList.contains('disabled-tab')) return;
      _activeTab = Number(btn.dataset.tab);
      _render(el, classId);
    });
  });

  el.querySelectorAll('[data-recent-window]').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = String(btn.dataset.recentWindow || '');
      if (!RECENT_SESSION_WINDOWS.some(row => row.key === key)) return;
      if (_recentWindow === key) return;
      _recentWindow = key;
      _render(el, classId);
    });
  });

  el.querySelectorAll('[data-unit-timeline-retry]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const unitId = Number(btn.dataset.unitTimelineRetry || 0);
      if (!unitId) return;
      _setBusy(btn, true);
      try {
        await _loadUnitTimeline(unitId, { force: true });
        _render(el, classId);
      } finally {
        _setBusy(btn, false);
      }
    });
  });

  el.querySelectorAll('#btn-checklist-expand-all, [data-checklist-expand-all]').forEach(btn => {
    btn.addEventListener('click', event => {
      event.preventDefault();
      _collapsedChecklistIds.clear();
      _render(el, classId);
    });
  });

  el.querySelectorAll('#btn-checklist-collapse-all, [data-checklist-collapse-all]').forEach(btn => {
    btn.addEventListener('click', event => {
      event.preventDefault();
      const unit = getActiveUnit();
      if (!unit) return;
      _collapseChecklistAllParents(_checklist(unit));
      _render(el, classId);
    });
  });

  el.querySelector('#btn-checklist-preview-focus-toggle')?.addEventListener('click', event => {
    event.preventDefault();
    _workflowPreviewFocusOnly = !_workflowPreviewFocusOnly;
    _render(el, classId);
  });

  el.querySelector('#btn-checklist-preview-hide-done-toggle')?.addEventListener('click', event => {
    event.preventDefault();
    _workflowPreviewHideDone = !_workflowPreviewHideDone;
    _render(el, classId);
  });

  el.querySelectorAll('.btn-checklist-toggle').forEach(btn => {
    btn.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      const itemId = Number(btn.dataset.itemId);
      if (!Number.isFinite(itemId) || itemId <= 0) return;
      if (_collapsedChecklistIds.has(itemId)) _collapsedChecklistIds.delete(itemId);
      else _collapsedChecklistIds.add(itemId);
      _render(el, classId);
    });
  });

  /*  attendance toggle  */
  el.querySelectorAll('[data-sid]').forEach(card => {
    const toggleAttendance = () => {
      toggleAbsent(Number(card.dataset.sid));
      _render(el, classId);
    };
    card.addEventListener('click', toggleAttendance);
    card.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      toggleAttendance();
    });
  });

  async function applyChecklistCheck(itemId, { showNoSessionWarning = false } = {}) {
    await _withActionLock(`workflow:session-mutate:${classId}`, async () => {
      const numericItemId = Number(itemId);
      if (!Number.isFinite(numericItemId) || numericItemId <= 0) return;
      const session = getActiveSession();
      if (!session) {
        if (showNoSessionWarning) showToast('Start a session first, then mark checklist items.', 'warning');
        return;
      }

      const unit = getActiveUnit();
      const items = _checklist(unit);
      const item = items.find(i => Number(i.id) === numericItemId);
      if (!item) return;
      const itemHasChildren = items.some(candidate => Number(candidate?.parent_item_id || 0) === numericItemId);
      if (_isStructuralChecklistItem(item) || itemHasChildren) {
        showToast('Section headings stay open until their child rows are completed. Check the lesson steps under this heading instead.', 'info');
        return;
      }
      if (item.is_completed || item.done) {
        showToast('Unchecking is disabled to keep unit progress flow.', 'info');
        return;
      }

      const affected = [item];
      const previousStates = affected.map(row => ({
        row,
        checked: row.is_completed !== undefined ? Boolean(row.is_completed) : Boolean(row.done),
      }));
      affected.forEach(row => {
        if (row.is_completed !== undefined) row.is_completed = true;
        else row.done = true;
      });
      _render(el, classId);

      try {
        await api(`/workflow/classes/${classId}/sessions/${session.id}/items/${numericItemId}/toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ checked: true }),
        });
        const ws = await api(`/workflow/classes/${classId}`);
        setWorkspace(ws);
        await _refreshWorkflowCalendarSnapshot(classId);
        _render(el, classId);
      } catch (err) {
        previousStates.forEach(({ row, checked }) => {
          if (row.is_completed !== undefined) row.is_completed = checked;
          else row.done = checked;
        });
        _render(el, classId);
        if (_isClosedSessionConflict(err)) {
          const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
          if (ws) {
            setWorkspace(ws);
            _render(el, classId);
          }
          showToast('Session already closed. Workspace refreshed.', 'warning');
          return;
        }
        showToast(err.message || 'Checklist update failed', 'error');
      }
    });
  }

  async function applyChecklistGroupCheck(itemId, triggerBtn = null) {
    await _withActionLock(`workflow:session-mutate:${classId}`, async () => {
      const numericItemId = Number(itemId);
      if (!Number.isFinite(numericItemId) || numericItemId <= 0) return;
      const session = getActiveSession();
      if (!session) {
        showToast('Start a session first, then mark checklist items.', 'warning');
        return;
      }

      const unit = getActiveUnit();
      const items = _checklist(unit);
      const parentItem = items.find(i => Number(i.id) === numericItemId);
      if (!parentItem) return;
      const descendants = _findDescendantItems(items, numericItemId);
      const actionable = descendants.filter(row => {
        const rowId = Number(row?.id || 0);
        if (!rowId) return false;
        const rowHasChildren = items.some(candidate => Number(candidate?.parent_item_id || 0) === rowId);
        if (_isStructuralChecklistItem(row) || rowHasChildren) return false;
        return !(row.is_completed || row.done);
      });
      if (!actionable.length) {
        showToast('Everything under this heading is already marked.', 'info');
        return;
      }

      const ok = await askConfirm(
        `Mark ${actionable.length} lesson step${actionable.length === 1 ? '' : 's'} under "${parentItem.title}" as taught?`,
      );
      if (!ok) return;

      _setBusy(triggerBtn, true);
      try {
        for (const row of actionable) {
          await api(`/workflow/classes/${classId}/sessions/${session.id}/items/${Number(row.id)}/toggle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ checked: true }),
          });
        }
        const ws = await api(`/workflow/classes/${classId}`);
        setWorkspace(ws);
        await _refreshWorkflowCalendarSnapshot(classId);
        _render(el, classId);
        showToast(
          `${actionable.length} lesson step${actionable.length === 1 ? '' : 's'} marked under "${parentItem.title}".`,
          'ok',
        );
      } catch (err) {
        if (_isClosedSessionConflict(err)) {
          const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
          if (ws) {
            setWorkspace(ws);
            _render(el, classId);
          }
          showToast('Session already closed. Workspace refreshed.', 'warning');
          return;
        }
        showToast(err.message || 'Group checklist update failed', 'error');
      } finally {
        _setBusy(triggerBtn, false);
      }
    });
  }

  /*  checklist item check (active session tab)  */
  el.querySelectorAll('[data-item-id][data-session-id]').forEach(node => {
    const checkChecklistItem = async () => {
      await applyChecklistCheck(node.dataset.itemId, { showNoSessionWarning: true });
    };
    node.addEventListener('click', checkChecklistItem);
    node.addEventListener('keydown', async e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      await checkChecklistItem();
    });
  });

  el.querySelectorAll('[data-session-flow-check-item-id]').forEach(node => {
    const checkSessionFlowItem = async event => {
      event?.preventDefault?.();
      await applyChecklistCheck(node.dataset.sessionFlowCheckItemId, { showNoSessionWarning: true });
    };
    node.addEventListener('click', checkSessionFlowItem);
    node.addEventListener('keydown', async e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      await checkSessionFlowItem(e);
    });
  });

  el.querySelectorAll('.btn-checklist-group-complete').forEach(btn => {
    btn.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      await applyChecklistGroupCheck(btn.dataset.itemId, btn);
    });
  });

  /*  checklist check from Unit Setup  */
  el.querySelectorAll('.btn-unit-check').forEach(btn => {
    btn.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      await applyChecklistCheck(btn.dataset.itemId, { showNoSessionWarning: true });
    });
  });

  /*  leaf lesson card  */
  el.querySelectorAll('.btn-leaf-lesson').forEach(btn => {
    btn.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      const itemId = Number(btn.dataset.itemId);
      const unit = getActiveUnit();
      if (!unit || !classId || !itemId) return;
      const checklistRows = _checklist(unit);
      const item = checklistRows.find(i => Number(i.id) === itemId);
      if (!item) return;
      const contextMap = _buildChecklistContextMap(checklistRows);
      const context = contextMap.get(itemId);
      openLeafContentModal(classId, Number(unit.id), {
        ...item,
        item_path_json: Array.isArray(item?.item_path_json) && item.item_path_json.length
          ? item.item_path_json
          : (Array.isArray(context?.itemPath) ? context.itemPath : []),
        section_path_json: Array.isArray(item?.section_path_json) && item.section_path_json.length
          ? item.section_path_json
          : (Array.isArray(context?.sectionPath) ? context.sectionPath : []),
      }, {
        onChange: () => _render(el, classId),
      });
    });
  });

  /* unit type selector toggle */
  el.querySelectorAll('[data-unit-type]').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.disabled) return;
      _selectedUnitType = btn.dataset.unitType || 'chapter';
      el.querySelectorAll('[data-unit-type]').forEach(b => b.classList.toggle('selected', b === btn));
    });
  });

  const unitAutoPlanEnableEl = el.querySelector('#unit-auto-plan-enable');
  const unitAutoPlanCountEl = el.querySelector('#unit-auto-plan-count');
  const unitAutoPlanStartDateEl = el.querySelector('#unit-auto-plan-start-date');
  const syncUnitAutoPlanUi = () => {
    const enabled = Boolean(unitAutoPlanEnableEl?.checked);
    [unitAutoPlanCountEl, unitAutoPlanStartDateEl].forEach(node => {
      if (!node) return;
      node.disabled = !enabled;
      node.classList.toggle('opacity-60', !enabled);
    });
  };
  unitAutoPlanEnableEl?.addEventListener('change', syncUnitAutoPlanUi);
  syncUnitAutoPlanUi();

  const readUnitAutoPlanConfig = () => {
    const enabled = Boolean(unitAutoPlanEnableEl?.checked);
    if (!enabled) {
      return {
        ok: true,
        enabled: false,
        sessionCount: 0,
        startDate: null,
      };
    }
    const rawCount = Number(unitAutoPlanCountEl?.value || 0);
    const sessionCount = Number.isFinite(rawCount) ? Math.floor(rawCount) : 0;
    if (sessionCount <= 0 || sessionCount > 120) {
      return {
        ok: false,
        error: 'Auto-plan sessions count must be between 1 and 120.',
      };
    }
    const startDate = String(unitAutoPlanStartDateEl?.value || '').trim();
    if (!startDate) {
      return {
        ok: false,
        error: 'Auto-plan start date is required.',
      };
    }
    return {
      ok: true,
      enabled: true,
      sessionCount,
      startDate,
    };
  };

  const runUnitAutoPlan = async config => {
    if (!config?.enabled) {
      return {
        createdCount: 0,
        failedCount: 0,
        searchEndDate: null,
      };
    }
    const result = await api(`/workflow/classes/${classId}/auto-plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'plan_unit',
        plan_mode: 'continue_unit',
        start_date: config.startDate,
        session_count: config.sessionCount,
        skip_blocked_holidays: true,
      }),
    });
    return {
      createdCount: Number(result?.created_count || 0),
      failedCount: Number(result?.failed_count || 0),
      searchEndDate: result?.search_end_date ? String(result.search_end_date) : null,
    };
  };

  /*  create unit  (POST /workflow/classes/{id}/units/start  multipart form)  */
  el.querySelector('#btn-create-unit')?.addEventListener('click', async () => {
    await _withActionLock(`workflow:create-unit:${classId}`, async () => {
      setUnitFormError('');
      if (getActiveUnit()) { showToast('Close the active unit first.', 'warning'); return; }
      const title = document.getElementById('unit-name')?.value?.trim();
      if (!title) {
        const message = 'Unit title is required.';
        setUnitFormError(message);
        const titleInput = document.getElementById('unit-name');
        titleInput?.classList.add('input-error');
        showToast(message, 'warning');
        return;
      }
      document.getElementById('unit-name')?.classList.remove('input-error');
      const plannedHoursResult = _parsePlannedHoursInput(document.getElementById('unit-planned-hours')?.value);
      if (!plannedHoursResult.ok) {
        setUnitFormError(plannedHoursResult.error);
        document.getElementById('unit-planned-hours')?.classList.add('input-error');
        showToast(plannedHoursResult.error, 'warning');
        return;
      }
      document.getElementById('unit-planned-hours')?.classList.remove('input-error');
      const autoPlanConfig = readUnitAutoPlanConfig();
      if (!autoPlanConfig.ok) {
        setUnitFormError(autoPlanConfig.error);
        showToast(autoPlanConfig.error, 'warning');
        return;
      }
      const createBtn = el.querySelector('#btn-create-unit');
      _setBusy(createBtn, true);
      try {
        const form = new FormData();
        // use selected unit type; exam/exam_correction don't require source_text
        const unitType = _selectedUnitType || 'chapter';
        form.append('unit_type', unitType);
        if (['chapter', 'exercise_series'].includes(unitType)) {
          form.append('source_text', title);   // let backend build checklist from typed title
        }
        form.append('title', title);
        if (plannedHoursResult.value != null) form.append('planned_hours', String(plannedHoursResult.value));
        const unit = await api(`/workflow/classes/${classId}/units/start`, {
          method: 'POST',
          body: form,
        });
        let autoPlanSummary = null;
        try {
          autoPlanSummary = await runUnitAutoPlan(autoPlanConfig);
        } catch (autoPlanErr) {
          showToast(`Unit created, but auto-plan failed: ${String(autoPlanErr?.message || 'unknown error')}`, 'warning');
        }
        const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
        if (ws) {
          setWorkspace(ws);
        } else {
          setActiveUnit(unit);
        }
        await _refreshWorkflowCalendarSnapshot(classId);
        _activeTab = 0;
        _render(el, classId);
        if (autoPlanSummary?.createdCount > 0 || autoPlanSummary?.failedCount > 0) {
          if (autoPlanSummary.failedCount > 0) {
            const endLabel = autoPlanSummary.searchEndDate ? fmtDate(autoPlanSummary.searchEndDate) : null;
            showToast(
              endLabel
                ? `Unit created. ${autoPlanSummary.createdCount} sessions planned, ${autoPlanSummary.failedCount} pending (searched until ${endLabel}).`
                : `Unit created. ${autoPlanSummary.createdCount} sessions planned, ${autoPlanSummary.failedCount} pending.`,
              'warning'
            );
          } else {
            showToast(`Unit created. ${autoPlanSummary.createdCount} sessions planned from timetable.`, 'ok');
          }
        } else {
          showToast('Unit created!', 'ok');
        }
      } catch (err) {
        if (_isActiveUnitConflict(err)) {
          const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
          if (ws) {
            setWorkspace(ws);
            _activeTab = 0;
            _render(el, classId);
          } else {
            _setBusy(createBtn, false);
          }
          showToast('An active unit already exists. Close it first.', 'warning');
          return;
        }
        _setBusy(createBtn, false);
        showToast(err.message, 'error');
      }
    });
  });

  /*  PDF   unit  */
  el.querySelector('#pdf-upload')?.addEventListener('change', async e => {
    await _withActionLock(`workflow:extract-unit:${classId}`, async () => {
      setUnitFormError('');
      if (getActiveUnit()) { showToast('Close the active unit first.', 'warning'); return; }
      const file = e.target.files[0]; if (!file) return;
      const titleEl = document.getElementById('unit-name');
      const title = titleEl?.value?.trim() || file.name.replace(/\.pdf$/i, '');
      if (!title) {
        const message = 'Unit title is required.';
        setUnitFormError(message);
        document.getElementById('unit-name')?.classList.add('input-error');
        showToast(message, 'warning');
        return;
      }
      document.getElementById('unit-name')?.classList.remove('input-error');
      const plannedHoursResult = _parsePlannedHoursInput(document.getElementById('unit-planned-hours')?.value);
      if (!plannedHoursResult.ok) {
        setUnitFormError(plannedHoursResult.error);
        document.getElementById('unit-planned-hours')?.classList.add('input-error');
        showToast(plannedHoursResult.error, 'warning');
        return;
      }
      document.getElementById('unit-planned-hours')?.classList.remove('input-error');
      const autoPlanConfig = readUnitAutoPlanConfig();
      if (!autoPlanConfig.ok) {
        setUnitFormError(autoPlanConfig.error);
        showToast(autoPlanConfig.error, 'warning');
        return;
      }
      showToast('Extracting from PDF  this may take a moment', 'info');
      const pdfLabel = el.querySelector('#pdf-upload-label');
      _setLabelBusy(pdfLabel, true);
      const form = new FormData();
      // use the currently selected unit type (pdf extract always has a file)
      const unitType = _selectedUnitType || 'chapter';
      form.append('unit_type', unitType);
      form.append('title', title);
      if (plannedHoursResult.value != null) form.append('planned_hours', String(plannedHoursResult.value));
      form.append('file', file);
      try {
        const unit = await api(`/workflow/classes/${classId}/units/start`, {
          method: 'POST',
          body: form,
        });
        let autoPlanSummary = null;
        try {
          autoPlanSummary = await runUnitAutoPlan(autoPlanConfig);
        } catch (autoPlanErr) {
          showToast(`Unit extracted, but auto-plan failed: ${String(autoPlanErr?.message || 'unknown error')}`, 'warning');
        }
        const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
        if (ws) {
          setWorkspace(ws);
        } else {
          setActiveUnit(unit);
        }
        await _refreshWorkflowCalendarSnapshot(classId);
        _activeTab = 0;
        _render(el, classId);
        if (autoPlanSummary?.createdCount > 0 || autoPlanSummary?.failedCount > 0) {
          if (autoPlanSummary.failedCount > 0) {
            const endLabel = autoPlanSummary.searchEndDate ? fmtDate(autoPlanSummary.searchEndDate) : null;
            showToast(
              endLabel
                ? `Unit extracted. ${autoPlanSummary.createdCount} sessions planned, ${autoPlanSummary.failedCount} pending (searched until ${endLabel}).`
                : `Unit extracted. ${autoPlanSummary.createdCount} sessions planned, ${autoPlanSummary.failedCount} pending.`,
              'warning'
            );
          } else {
            showToast(`Unit extracted. ${autoPlanSummary.createdCount} sessions planned from timetable.`, 'ok');
          }
        } else {
          showToast('Unit extracted from PDF!', 'ok');
        }
      } catch (err) {
        if (_isActiveUnitConflict(err)) {
          const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
          if (ws) {
            setWorkspace(ws);
            _activeTab = 0;
            _render(el, classId);
          } else {
            _setLabelBusy(pdfLabel, false);
            e.target.value = '';
          }
          showToast('An active unit already exists. Close it first.', 'warning');
          return;
        }
        _setLabelBusy(pdfLabel, false);
        e.target.value = '';
        showToast(err.message, 'error');
      }
    });
  });

  /*  start session  (POST /workflow/classes/{id}/sessions/start  JSON absent_student_ids) */
  async function startSession(triggerBtn) {
    await _withActionLock(`workflow:start-session:${classId}`, async () => {
      const unit = getActiveUnit();
      if (unit?.extraction_source && unit.extraction_reviewed === false) {
        const proceed = await askConfirm(
          'This extraction is still marked as needing review. Start the session anyway? You can approve the extraction first if the checklist looks correct.'
        );
        if (!proceed) return;
      }
      const absentIds = [...getAbsentIds()];
      _setBusy(triggerBtn, true);
      try {
        const session = await api(`/workflow/classes/${classId}/sessions/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ absent_student_ids: absentIds }),
        });
        setActiveSession(session);
        await _refreshWorkflowCalendarSnapshot(classId);
        _activeTab = 2;
        _render(el, classId);
        showToast('Session started!', 'ok');
      } catch (err) {
        if (_isSessionAlreadyOpenConflict(err)) {
          const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
          if (ws) {
            setWorkspace(ws);
            _activeTab = ws.active_session ? 2 : 0;
            _render(el, classId);
          } else {
            _setBusy(triggerBtn, false);
          }
          showToast('A session is already open. Workspace refreshed.', 'warning');
          return;
        }
        _setBusy(triggerBtn, false);
        showToast(err.message, 'error');
      }
    });
  }
  el.querySelector('#btn-start-session')?.addEventListener('click', function () { startSession(this); });
  el.querySelector('#btn-start-session-att')?.addEventListener('click', function () { startSession(this); });
  el.querySelector('#btn-toggle-extraction-review')?.addEventListener('click', async function () {
    await _withActionLock(`workflow:unit-review:${classId}`, async () => {
      const unit = getActiveUnit();
      if (!unit?.id) return;
      const reviewed = unit.extraction_reviewed === false;
      _setBusy(this, true);
      try {
        const updatedUnit = await api(`/workflow/classes/${classId}/units/${unit.id}/review`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reviewed }),
        });
        const ws = await api(`/workflow/classes/${classId}`);
        if (ws?.active_unit && Number(ws.active_unit.id) === Number(updatedUnit.id)) {
          ws.active_unit = updatedUnit;
        }
        setWorkspace(ws);
        _unitBlueprintCache.delete(Number(unit.id));
        _render(el, classId);
        showToast(reviewed ? 'Extraction approved for teaching.' : 'Extraction marked as needing review.', 'ok');
      } catch (err) {
        _setBusy(this, false);
        showToast(err.message || 'Failed to update extraction review state.', 'error');
      }
    });
  });

  el.querySelector('#btn-plan-active-unit')?.addEventListener('click', async function () {
    await _withActionLock(`workflow:plan-active-unit:${classId}`, async () => {
      const activeUnit = getActiveUnit();
      if (!activeUnit) {
        showToast('No active unit to plan.', 'warning');
        return;
      }

      const config = await _openActiveUnitPlanConfigModal({
        unitTitle: activeUnit.title,
        defaultStartDate: _toDateInputValue(new Date()),
      });
      if (!config) return;

      const planBtn = this;
      _setBusy(planBtn, true);
      try {
        const searchHorizonDays = Math.min(730, Math.max(120, Number(config.session_count || 1) * 21));
        const preview = await api(`/workflow/classes/${classId}/auto-plan`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: 'plan_unit',
            dry_run: true,
            plan_mode: 'continue_unit',
            start_date: config.start_date,
            session_count: Number(config.session_count || 1),
            skip_blocked_holidays: true,
            max_search_days: searchHorizonDays,
          }),
        });
        const plannedCount = Number(preview?.planned_count || 0);
        if (plannedCount <= 0) {
          const searchEndText = preview?.search_end_date ? fmtDate(preview.search_end_date) : null;
          showToast(
            searchEndText
              ? `No valid slots found (searched until ${searchEndText}).`
              : 'No valid slots found in the search window.',
            'warning'
          );
          return;
        }

        _setBusy(planBtn, false);
        const shouldApply = await _openActiveUnitPlanPreviewModal({
          preview,
          unitTitle: activeUnit.title,
        });
        if (!shouldApply) return;

        _setBusy(planBtn, true);
        const result = await api(`/workflow/classes/${classId}/auto-plan`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: 'plan_unit',
            plan_mode: 'continue_unit',
            start_date: config.start_date,
            session_count: Number(config.session_count || 1),
            skip_blocked_holidays: true,
            max_search_days: searchHorizonDays,
          }),
        });
        const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
        if (ws) setWorkspace(ws);
        await _refreshWorkflowCalendarSnapshot(classId);
        _activeTab = 0;
        _render(el, classId);

        const createdCount = Number(result?.created_count || 0);
        const pendingCount = Number(result?.failed_count || 0);
        if (pendingCount > 0) {
          const endText = result?.search_end_date ? fmtDate(result.search_end_date) : null;
          showToast(
            endText
              ? `Created ${createdCount} sessions; ${pendingCount} pending (searched until ${endText}).`
              : `Created ${createdCount} sessions; ${pendingCount} pending in current search window.`,
            'warning'
          );
        } else {
          showToast(`Created ${createdCount} sessions for active unit.`, 'ok');
        }
      } catch (err) {
        showToast(String(err?.message || 'Failed to plan active unit sessions.'), 'error');
      } finally {
        _setBusy(planBtn, false);
      }
    });
  });

  el.querySelector('#btn-download-unit-doc')?.addEventListener('click', async () => {
    const unit = getActiveUnit();
    if (!unit) return;
    try {
      await downloadWithAuth(`/workflow/units/${unit.id}/document`, unit.document_name || `unit-${unit.id}.pdf`);
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  async function persistChecklistReorder(draft, successMessage) {
    const unit = getActiveUnit();
    if (!unit) return;
    await api(`/workflow/classes/${classId}/units/${unit.id}/items/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: draft }),
    });
    const ws = await api(`/workflow/classes/${classId}`);
    setWorkspace(ws);
    _render(el, classId);
    if (successMessage) showToast(successMessage, 'ok');
  }

  async function applyChecklistReorder(itemId, moveFn, successMessage, blockedMessage) {
    await _withActionLock(`workflow:reorder:${classId}:${itemId}`, async () => {
      const unit = getActiveUnit();
      if (!unit) return;
      const draft = _buildChecklistReorderDraft(_checklist(unit));
      const changed = moveFn(draft, itemId);
      if (!changed) {
        if (blockedMessage) showToast(blockedMessage, 'info');
        return;
      }
      _normalizeChecklistDraft(draft);
      try {
        await persistChecklistReorder(draft, successMessage);
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }

  async function applyChecklistDropReorder(dragItemId, targetItemId, mode) {
    await _withActionLock(`workflow:reorder-dnd:${classId}:${dragItemId}`, async () => {
      const unit = getActiveUnit();
      if (!unit) return;
      const draft = _buildChecklistReorderDraft(_checklist(unit));
      _normalizeChecklistDraft(draft);
      const before = _checklistDraftSignature(draft);
      const moved = _moveChecklistItemByDrop(draft, dragItemId, targetItemId, mode);
      if (!moved.ok) {
        showToast(moved.error || 'Unable to move checklist item.', 'warning');
        return;
      }
      if (String(mode || '').toLowerCase() === 'inside' && Number.isFinite(Number(targetItemId))) {
        _collapsedChecklistIds.delete(Number(targetItemId));
      }
      const after = _checklistDraftSignature(draft);
      if (before === after || moved.changed === false) return;
      try {
        await persistChecklistReorder(draft, 'Checklist order updated.');
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  }

  const checklistDndState = {
    dragItemId: null,
    targetItemId: null,
    mode: null,
    didDrop: false,
  };

  const markChecklistDragSource = () => {
    if (!checklistDndState.dragItemId) return;
    const source = el.querySelector(`.checklist-draggable-node[data-dnd-target-id="${checklistDndState.dragItemId}"]`);
    source?.classList.add('drag-source');
  };

  const clearChecklistDndVisuals = () => {
    el.querySelectorAll('.checklist-draggable-node').forEach(node => {
      node.classList.remove('drag-before', 'drag-after', 'drag-inside', 'drag-source');
    });
    el.querySelectorAll('.todo-root-dropzone').forEach(zone => {
      zone.classList.remove('drag-root-active');
    });
  };

  const endChecklistDnd = () => {
    clearChecklistDndVisuals();
    checklistDndState.dragItemId = null;
    checklistDndState.targetItemId = null;
    checklistDndState.mode = null;
    checklistDndState.didDrop = false;
    el.classList.remove('checklist-dnd-active');
  };

  el.querySelectorAll('.todo-drag-handle').forEach(handle => {
    handle.addEventListener('dragstart', event => {
      const dragItemId = Number(handle.dataset.dragItemId);
      if (!dragItemId) {
        event.preventDefault();
        return;
      }
      checklistDndState.dragItemId = dragItemId;
      checklistDndState.targetItemId = null;
      checklistDndState.mode = null;
      checklistDndState.didDrop = false;
      el.classList.add('checklist-dnd-active');
      clearChecklistDndVisuals();
      markChecklistDragSource();
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(dragItemId));
      }
    });

    handle.addEventListener('dragend', async () => {
      const dragItemId = checklistDndState.dragItemId;
      const targetItemId = checklistDndState.targetItemId;
      const mode = checklistDndState.mode;
      const didDrop = checklistDndState.didDrop;
      endChecklistDnd();
      if (!didDrop || !dragItemId || !mode) return;
      await applyChecklistDropReorder(dragItemId, targetItemId, mode);
    });
  });

  el.querySelectorAll('.checklist-draggable-node').forEach(node => {
    node.addEventListener('dragover', event => {
      if (!checklistDndState.dragItemId) return;
      const targetItemId = Number(node.dataset.dndTargetId || node.dataset.itemId);
      if (!targetItemId) return;
      event.preventDefault();
      const mode = _resolveChecklistDropMode(node, event);
      checklistDndState.targetItemId = targetItemId;
      checklistDndState.mode = mode;
      clearChecklistDndVisuals();
      markChecklistDragSource();
      node.classList.add(`drag-${mode}`);
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    });

    node.addEventListener('drop', event => {
      if (!checklistDndState.dragItemId || !checklistDndState.mode) return;
      event.preventDefault();
      event.stopPropagation();
      checklistDndState.didDrop = true;
    });
  });

  el.querySelector('[data-dnd-root-drop]')?.addEventListener('dragover', event => {
    if (!checklistDndState.dragItemId) return;
    event.preventDefault();
    checklistDndState.targetItemId = null;
    checklistDndState.mode = 'root';
    clearChecklistDndVisuals();
    markChecklistDragSource();
    const zone = event.currentTarget;
    zone?.classList?.add('drag-root-active');
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
  });

  el.querySelector('[data-dnd-root-drop]')?.addEventListener('drop', event => {
    if (!checklistDndState.dragItemId) return;
    event.preventDefault();
    event.stopPropagation();
    checklistDndState.didDrop = true;
  });

  el.querySelectorAll('.btn-item-up').forEach(btn => {
    btn.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      const itemId = Number(btn.dataset.itemId);
      if (!itemId) return;
      await applyChecklistReorder(itemId, _moveChecklistItemUp, 'Checklist item moved up.', 'Item is already first in its level.');
    });
  });

  el.querySelectorAll('.btn-item-down').forEach(btn => {
    btn.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      const itemId = Number(btn.dataset.itemId);
      if (!itemId) return;
      await applyChecklistReorder(itemId, _moveChecklistItemDown, 'Checklist item moved down.', 'Item is already last in its level.');
    });
  });

  el.querySelectorAll('.btn-item-indent').forEach(btn => {
    btn.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      const itemId = Number(btn.dataset.itemId);
      if (!itemId) return;
      await applyChecklistReorder(itemId, _indentChecklistItem, 'Checklist item nested under previous sibling.', 'Cannot nest this item.');
    });
  });

  el.querySelectorAll('.btn-item-outdent').forEach(btn => {
    btn.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      const itemId = Number(btn.dataset.itemId);
      if (!itemId) return;
      await applyChecklistReorder(itemId, _outdentChecklistItem, 'Checklist item moved one level up.', 'Item is already at root level.');
    });
  });

  el.querySelector('#btn-add-item-root')?.addEventListener('click', async () => {
    await _withActionLock(`workflow:item-add-root:${classId}`, async () => {
      const unit = getActiveUnit();
      if (!unit) return;
      const values = await _editChecklistItemModal({ title: '', item_kind: 'other', mode: 'create' });
      if (!values) return;
      try {
        await api(`/workflow/classes/${classId}/units/${unit.id}/items`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: values.title, item_kind: values.item_kind, parent_item_id: null }),
        });
        const ws = await api(`/workflow/classes/${classId}`);
        setWorkspace(ws);
        _render(el, classId);
        showToast('Checklist item added.', 'ok');
      } catch (err) {
        showToast(err.message, 'error');
      }
    });
  });

  el.querySelectorAll('.btn-item-add-child').forEach(btn => {
    btn.addEventListener('click', async () => {
      const parentId = Number(btn.dataset.itemId);
      if (!parentId) return;
      await _withActionLock(`workflow:item-add-child:${classId}:${parentId}`, async () => {
        const unit = getActiveUnit();
        if (!unit) return;
        const values = await _editChecklistItemModal({ title: '', item_kind: 'other', mode: 'create' });
        if (!values) return;
        try {
          await api(`/workflow/classes/${classId}/units/${unit.id}/items`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: values.title, item_kind: values.item_kind, parent_item_id: parentId }),
          });
          const ws = await api(`/workflow/classes/${classId}`);
          setWorkspace(ws);
          _render(el, classId);
          showToast('Child checklist item added.', 'ok');
        } catch (err) {
          showToast(err.message, 'error');
        }
      });
    });
  });

  el.querySelectorAll('.btn-item-edit').forEach(btn => {
    btn.addEventListener('click', async () => {
      const itemId = Number(btn.dataset.itemId);
      if (!itemId) return;
      await _withActionLock(`workflow:item-edit:${classId}:${itemId}`, async () => {
        const unit = getActiveUnit();
        if (!unit) return;
        const values = await _editChecklistItemModal({
          title: String(btn.dataset.itemTitle || ''),
          item_kind: String(btn.dataset.itemKind || 'other'),
          mode: 'edit',
        });
        if (!values) return;
        try {
          await api(`/workflow/classes/${classId}/units/${unit.id}/items/${itemId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: values.title, item_kind: values.item_kind }),
          });
          const ws = await api(`/workflow/classes/${classId}`);
          setWorkspace(ws);
          _render(el, classId);
          showToast('Checklist item updated.', 'ok');
        } catch (err) {
          showToast(err.message, 'error');
        }
      });
    });
  });

  el.querySelectorAll('.btn-item-delete').forEach(btn => {
    btn.addEventListener('click', async () => {
      const itemId = Number(btn.dataset.itemId);
      if (!itemId) return;
      await _withActionLock(`workflow:item-delete:${classId}:${itemId}`, async () => {
        const unit = getActiveUnit();
        if (!unit) return;
        const ok = await askConfirm('Delete this checklist item? Child items will also be removed.', { danger: true });
        if (!ok) return;
        try {
          await api(`/workflow/classes/${classId}/units/${unit.id}/items/${itemId}`, { method: 'DELETE' });
          const ws = await api(`/workflow/classes/${classId}`);
          setWorkspace(ws);
          _render(el, classId);
          showToast('Checklist item deleted.', 'ok');
        } catch (err) {
          showToast(err.message, 'error');
        }
      });
    });
  });

  /*  end session  (POST /workflow/classes/{id}/sessions/{sid}/end  JSON payload) */
  async function endSession(triggerBtn) {
    await _withActionLock(`workflow:session-mutate:${classId}`, async () => {
      const session = getActiveSession();
      if (!session) return;
      const previousUnitId = Number(session?.unit_id || getActiveUnit()?.id || 0);
      const payload = await _editWorkflowSessionEndModal(session);
      if (!payload) return;
      payload.absent_student_ids = _resolveSessionAbsentIds(session);
      _setBusy(triggerBtn, true);
      try {
        await api(`/workflow/classes/${classId}/sessions/${session.id}/end`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        setActiveSession(null);
        // Refresh workspace
        const ws = await api(`/workflow/classes/${classId}`);
        setWorkspace(ws);
        await _refreshWorkflowCalendarSnapshot(classId);
        _activeTab = 0;
        _render(el, classId);
        const activeUnitId = Number(ws?.active_unit?.id || 0);
        const unitClosed = previousUnitId > 0 && activeUnitId !== previousUnitId;
        showToast(unitClosed ? 'Session ended. Unit completed and closed.' : 'Session ended.', 'ok');
      } catch (err) {
        _setBusy(triggerBtn, false);
        if (_isClosedSessionConflict(err)) {
          const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
          if (ws) {
            setWorkspace(ws);
            _activeTab = 0;
            _render(el, classId);
          }
          showToast('Session was already closed. Workspace refreshed.', 'warning');
          return;
        }
        showToast(err.message, 'error');
      }
    });
  }
  el.querySelector('#btn-end-session')?.addEventListener('click', function () { endSession(this); });
  el.querySelector('#btn-end-session-banner')?.addEventListener('click', function () { endSession(this); });

  async function loadActiveSessionProgress({ force = false, notify = false } = {}) {
    const session = getActiveSession();
    if (!session) return _emptySessionProgressState();
    const state = await _loadSessionProgress(session.id, { force });
    const latestSession = getActiveSession();
    if (!latestSession || Number(latestSession.id) !== Number(session.id)) return state;
    _render(el, classId);
    if (notify) {
      if (state.error) showToast(state.error, 'error');
      else showToast('Session progress loaded.', 'ok');
    }
    return state;
  }

  async function loadActiveSessionWriteup({ force = false, notify = false } = {}) {
    const session = getActiveSession();
    if (!session) return _emptySessionWriteupState();
    const state = await _loadSessionWriteup(session.id, classId, { force });
    const latestSession = getActiveSession();
    if (!latestSession || Number(latestSession.id) !== Number(session.id)) return state;
    _render(el, classId);
    if (notify) {
      if (state.error) showToast(state.error, 'error');
      else if (state.item) showToast('Session write-up loaded.', 'ok');
      else showToast('No saved write-up for this session yet.', 'info');
    }
    return state;
  }

  el.querySelector('#btn-load-session-progress')?.addEventListener('click', async () => {
    await _withActionLock(`workflow:session-progress:${classId}`, async () => {
      await loadActiveSessionProgress({ force: false, notify: true });
    });
  });
  el.querySelector('#btn-toggle-session-planned-route')?.addEventListener('click', () => {
    _workflowCollapsePlannedRoute = !_workflowCollapsePlannedRoute;
    _render(el, classId);
  });
  el.querySelector('#btn-toggle-session-progress')?.addEventListener('click', () => {
    _workflowCollapseSessionProgress = !_workflowCollapseSessionProgress;
    _render(el, classId);
  });
  el.querySelector('#btn-toggle-session-writeup')?.addEventListener('click', () => {
    _workflowCollapseSessionWriteup = !_workflowCollapseSessionWriteup;
    _render(el, classId);
  });

  el.querySelector('#btn-refresh-session-progress')?.addEventListener('click', async () => {
    await _withActionLock(`workflow:session-progress:${classId}`, async () => {
      await loadActiveSessionProgress({ force: true, notify: true });
    });
  });

  el.querySelector('#btn-generate-session-writeup')?.addEventListener('click', async function () {
    const button = this;
    await _withActionLock(`workflow:session-writeup:${classId}`, async () => {
      const session = getActiveSession();
      if (!session) return;
      _setBusy(button, true);
      try {
        const row = await api(`/workflow/classes/${classId}/sessions/${session.id}/writeup/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ regenerate: true }),
        });
        _setSessionWriteupState(session.id, {
          loading: false,
          loaded: true,
          error: null,
          item: row || null,
        });
        const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
        if (ws) setWorkspace(ws);
        _render(el, classId);
        showToast('Session write-up generated.', 'ok');
      } catch (err) {
        _setBusy(button, false);
        showToast(String(err?.message || 'Failed to generate session write-up.'), 'error');
      }
    });
  });

  el.querySelector('#btn-edit-session-writeup')?.addEventListener('click', async () => {
    await _withActionLock(`workflow:session-writeup-edit:${classId}`, async () => {
      const session = getActiveSession();
      if (!session) return;
      const current = _getSessionWriteupState(session.id);
      const base = current.item || (await loadActiveSessionWriteup({ force: false, notify: false })).item;
      if (!base) {
        showToast('Generate the session write-up first.', 'info');
        return;
      }
      const draft = await _openSessionWriteupModal(base);
      if (!draft) return;
      try {
        const updated = await api(`/workflow/classes/${classId}/sessions/${session.id}/writeup`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(draft),
        });
        _setSessionWriteupState(session.id, {
          loading: false,
          loaded: true,
          error: null,
          item: updated || null,
        });
        const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
        if (ws) setWorkspace(ws);
        _render(el, classId);
        showToast('Session write-up updated.', 'ok');
      } catch (err) {
        showToast(String(err?.message || 'Failed to update session write-up.'), 'error');
      }
    });
  });

  el.querySelector('#btn-import-session-guidance')?.addEventListener('click', async () => {
    await _withActionLock(`workflow:session-writeup-import:${classId}`, async () => {
      const session = getActiveSession();
      const unit = getActiveUnit();
      if (!session || !unit) return;
      const artifactId = await _openSessionGuidanceImportModal({ classId, unit });
      if (!artifactId) return;
      try {
        const updated = await api(`/workflow/classes/${classId}/sessions/${session.id}/writeup/import-assistant-artifact`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ artifact_id: artifactId }),
        });
        _setSessionWriteupState(session.id, {
          loading: false,
          loaded: true,
          error: null,
          item: updated || null,
        });
        const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
        if (ws) setWorkspace(ws);
        _render(el, classId);
        showToast('Saved guidance imported into the session write-up.', 'ok');
      } catch (err) {
        showToast(String(err?.message || 'Failed to import the saved guidance.'), 'error');
      }
    });
  });
  el.querySelectorAll('.btn-session-matched-guidance-copy').forEach(button => {
    button.addEventListener('click', async () => {
      const artifactId = Number(button.dataset.artifactId || 0);
      const item = activeSessionMatchedGuidance.find(row => Number(row?.id || 0) === artifactId);
      if (!item?.content_markdown) return;
      try {
        await copyText(String(item.content_markdown));
        showToast('Saved guidance copied.', 'ok');
      } catch {
        showToast('Failed to copy saved guidance.', 'error');
      }
    });
  });
  el.querySelectorAll('.btn-session-matched-guidance-download').forEach(button => {
    button.addEventListener('click', () => {
      const artifactId = Number(button.dataset.artifactId || 0);
      const item = activeSessionMatchedGuidance.find(row => Number(row?.id || 0) === artifactId);
      if (!item?.content_markdown) return;
      _downloadTextContent(String(item.content_markdown), _artifactDownloadFilename(item, unit?.title || 'session-guidance'));
    });
  });
  el.querySelectorAll('.btn-session-matched-guidance-import').forEach(button => {
    button.addEventListener('click', async () => {
      const session = getActiveSession();
      if (!session || !unit) return;
      const artifactId = Number(button.dataset.artifactId || 0);
      if (!artifactId) return;
      try {
        const updated = await api(`/workflow/classes/${classId}/sessions/${session.id}/writeup/import-assistant-artifact`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ artifact_id: artifactId }),
        });
        _setSessionWriteupState(session.id, {
          loading: false,
          loaded: true,
          error: null,
          item: updated || null,
        });
        _render(el, classId);
        showToast('Saved guidance imported into the session write-up.', 'ok');
      } catch (err) {
        showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
      }
    });
  });

  const currentSessionForArtifacts = getActiveSession();
  const currentUnitForArtifacts = getActiveUnit();
  if (currentSessionForArtifacts && currentUnitForArtifacts?.id) {
    const artifactCacheKey = `${Number(classId || 0)}:${Number(currentUnitForArtifacts.id || 0)}`;
    if (!_unitAssistantArtifactCache.has(artifactCacheKey)) {
      _loadUnitAssistantArtifacts(classId, currentUnitForArtifacts.id).then(() => {
        const latestSession = getActiveSession();
        const latestUnit = getActiveUnit();
        if (latestSession && latestUnit && Number(latestSession.id) === Number(currentSessionForArtifacts.id) && Number(latestUnit.id) === Number(currentUnitForArtifacts.id)) {
          _render(el, classId);
        }
      }).catch(() => {});
    }
  }

  el.querySelector('#btn-copy-session-writeup')?.addEventListener('click', async () => {
    const session = getActiveSession();
    const unit = getActiveUnit();
    if (!session) return;
    const item = _getSessionWriteupState(session.id).item;
    if (!item) return;
    try {
      await navigator.clipboard.writeText(
        _buildSessionWriteupMarkdown(item, {
          unitTitle: String(unit?.title || '').trim(),
          sessionLabel: session?.unit_session_number ? `Unit Session ${session.unit_session_number}` : fmtDate(session.session_date || session.date),
        })
      );
      showToast('Session write-up copied.', 'ok');
    } catch {
      showToast('Failed to copy the session write-up.', 'error');
    }
  });

  el.querySelector('#btn-download-session-writeup')?.addEventListener('click', () => {
    const session = getActiveSession();
    const unit = getActiveUnit();
    if (!session) return;
    const item = _getSessionWriteupState(session.id).item;
    if (!item) return;
    const unitSlug = String(unit?.title || 'unit').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'unit';
    const sessionSlug = session?.unit_session_number ? `session-${session.unit_session_number}` : 'session-writeup';
    _downloadTextContent(
      _buildSessionWriteupMarkdown(item, {
        unitTitle: String(unit?.title || '').trim(),
        sessionLabel: session?.unit_session_number ? `Unit Session ${session.unit_session_number}` : fmtDate(session.session_date || session.date),
      }),
      `${unitSlug}-${sessionSlug}.md`
    );
  });

  el.querySelector('#btn-session-next-generate')?.addEventListener('click', () => {
    el.querySelector('#btn-generate-session-writeup')?.click();
  });
  el.querySelector('#btn-session-next-guidance')?.addEventListener('click', () => {
    el.querySelector('#btn-import-session-guidance')?.click();
  });
  el.querySelector('#btn-session-guidance-hide-imported-toggle')?.addEventListener('click', () => {
    _sessionGuidanceHideImported = !_sessionGuidanceHideImported;
    _render(el, classId);
  });
  el.querySelector('#btn-session-guidance-reset-filters')?.addEventListener('click', () => {
    _sessionGuidanceHideImported = false;
    _sessionGuidanceKindFilter = 'all';
    _sessionGuidanceCollapseImported = false;
    _render(el, classId);
  });
  el.querySelector('#btn-session-guidance-import-remaining')?.addEventListener('click', async () => {
    const session = getActiveSession();
    if (!session || !activeSessionVisibleRemainingGuidance.length) return;
    try {
      let updated = null;
      for (const item of activeSessionVisibleRemainingGuidance) {
        updated = await api(`/workflow/classes/${classId}/sessions/${session.id}/writeup/import-assistant-artifact`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ artifact_id: Number(item.id) }),
        });
      }
      _setSessionWriteupState(session.id, {
        loading: false,
        loaded: true,
        error: null,
        item: updated || null,
      });
      _render(el, classId);
      showToast(`${activeSessionVisibleRemainingGuidance.length} ${_sessionGuidanceKindFilter === 'all' ? 'remaining' : 'visible'} guidance item${activeSessionVisibleRemainingGuidance.length === 1 ? '' : 's'} imported.`, 'ok');
    } catch (err) {
      showToast(String(err?.message || 'Failed to import remaining guidance.'), 'error');
    }
  });
  el.querySelector('#btn-session-guidance-collapse-imported-toggle')?.addEventListener('click', () => {
    _sessionGuidanceCollapseImported = !_sessionGuidanceCollapseImported;
    _render(el, classId);
  });
  el.querySelectorAll('.btn-session-guidance-kind-toggle').forEach(button => {
    button.addEventListener('click', () => {
      _sessionGuidanceKindFilter = String(button.dataset.guidanceKind || 'all').trim().toLowerCase() || 'all';
      _render(el, classId);
    });
  });
  el.querySelector('#btn-session-next-import-best')?.addEventListener('click', async () => {
    const session = getActiveSession();
    if (!session || !activeSessionBestRemainingGuidance) return;
    try {
      const updated = await api(`/workflow/classes/${classId}/sessions/${session.id}/writeup/import-assistant-artifact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: Number(activeSessionBestRemainingGuidance.id) }),
      });
      _setSessionWriteupState(session.id, {
        loading: false,
        loaded: true,
        error: null,
        item: updated || null,
      });
      _render(el, classId);
      showToast('Best matching saved guidance imported.', 'ok');
    } catch (err) {
      showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
    }
  });
  el.querySelector('#btn-session-next-import-all')?.addEventListener('click', async () => {
    const session = getActiveSession();
    if (!session || !activeSessionRemainingGuidance.length) return;
    try {
      let updated = null;
      for (const item of activeSessionRemainingGuidance) {
        updated = await api(`/workflow/classes/${classId}/sessions/${session.id}/writeup/import-assistant-artifact`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ artifact_id: Number(item.id) }),
        });
      }
      _setSessionWriteupState(session.id, {
        loading: false,
        loaded: true,
        error: null,
        item: updated || null,
      });
      _render(el, classId);
      showToast(`${activeSessionRemainingGuidance.length} saved guidance item${activeSessionRemainingGuidance.length === 1 ? '' : 's'} imported.`, 'ok');
    } catch (err) {
      showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
    }
  });
  el.querySelectorAll('.btn-guidance-kind-import').forEach(button => {
    button.addEventListener('click', async () => {
      const session = getActiveSession();
      if (!session) return;
      const artifactKind = String(button.dataset.artifactKind || '').trim().toLowerCase();
      if (!artifactKind) return;
      const matches = activeSessionRemainingGuidance.filter(item => String(item?.artifact_kind || '').trim().toLowerCase() === artifactKind);
      if (!matches.length) return;
      try {
        let updated = null;
        for (const item of matches) {
          updated = await api(`/workflow/classes/${classId}/sessions/${session.id}/writeup/import-assistant-artifact`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ artifact_id: Number(item.id) }),
          });
        }
        _setSessionWriteupState(session.id, {
          loading: false,
          loaded: true,
          error: null,
          item: updated || null,
        });
        _render(el, classId);
        showToast(`${matches.length} ${_assistantArtifactKindLabel(artifactKind).toLowerCase()} item${matches.length === 1 ? '' : 's'} imported.`, 'ok');
      } catch (err) {
        showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
      }
    });
  });
  el.querySelectorAll('.btn-guidance-quick-pick').forEach(button => {
    button.addEventListener('click', async () => {
      const session = getActiveSession();
      if (!session) return;
      const artifactId = Number(button.dataset.artifactId || 0);
      if (!artifactId) return;
      try {
        const updated = await api(`/workflow/classes/${classId}/sessions/${session.id}/writeup/import-assistant-artifact`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ artifact_id: artifactId }),
        });
        _setSessionWriteupState(session.id, {
          loading: false,
          loaded: true,
          error: null,
          item: updated || null,
        });
        _render(el, classId);
        showToast('Saved guidance imported into the session write-up.', 'ok');
      } catch (err) {
        showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
      }
    });
  });
  el.querySelector('#btn-session-next-edit')?.addEventListener('click', () => {
    el.querySelector('#btn-edit-session-writeup')?.click();
  });
  el.querySelector('#btn-session-next-approve')?.addEventListener('click', async () => {
    const session = getActiveSession();
    const item = session ? _getSessionWriteupState(session.id).item : null;
    if (!session || !item) return;
    try {
      const updated = await api(`/workflow/classes/${classId}/sessions/${session.id}/writeup`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: true }),
      });
      _setSessionWriteupState(session.id, {
        loading: false,
        loaded: true,
        error: null,
        item: updated || null,
      });
      const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
      if (ws) setWorkspace(ws);
      _render(el, classId);
      showToast('Write-up approved.', 'ok');
    } catch (err) {
      showToast(String(err?.message || 'Failed to approve session write-up.'), 'error');
    }
  });
  el.querySelector('#btn-session-next-copy')?.addEventListener('click', () => {
    el.querySelector('#btn-copy-session-writeup')?.click();
  });
  el.querySelector('#btn-session-next-download')?.addEventListener('click', () => {
    el.querySelector('#btn-download-session-writeup')?.click();
  });

  const autoLoadSession = getActiveSession();
  if (autoLoadSession) {
    const autoState = _getSessionProgressState(autoLoadSession.id);
    if (!autoState.loaded && !autoState.loading) {
      _loadSessionProgress(autoLoadSession.id, { force: false }).then(() => {
        const latestSession = getActiveSession();
        if (!latestSession || Number(latestSession.id) !== Number(autoLoadSession.id)) return;
        _render(el, classId);
      });
    }
  }

  async function applyExtractionReview(sessionId, draftRows, extractedMeta, { defaultMode = 'replace', successToastPrefix = 'Session extraction' } = {}) {
    if (!Array.isArray(draftRows) || !draftRows.length) {
      showToast('No progress items detected in extraction.', 'warning');
      return false;
    }

    const reviewResult = await _reviewExtractionRows(draftRows, extractedMeta, { defaultMode });
    if (!reviewResult || !Array.isArray(reviewResult.items) || !reviewResult.items.length) return false;

    const mode = _coerceExtractionMode(reviewResult.mode);
    await api(`/sessions/${sessionId}/confirm-extraction`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, items: reviewResult.items }),
    });
    await _loadSessionProgress(sessionId, { force: true });

    const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
    if (ws) {
      setWorkspace(ws);
      _render(el, classId);
    }
    showToast(`${successToastPrefix} ${mode === 'append' ? 'appended' : 'replaced'}.`, 'ok');
    return true;
  }

  el.querySelector('#session-upload')?.addEventListener('change', async e => {
    await _withActionLock(`workflow:session-extract:${classId}`, async () => {
      const session = getActiveSession();
      const file = e.target.files?.[0];
      if (!session || !file) return;

      const form = new FormData();
      form.append('file', file);
      showToast('Extracting session image', 'info');
      // show busy on the label wrapper
      const extractLabel = el.querySelector('#session-upload')?.closest('label');
      _setLabelBusy(extractLabel, true);

      try {
        const extracted = await api(`/sessions/${session.id}/uploads`, {
          method: 'POST',
          body: form,
        });

        const draftRows = _draftExtractionRows(extracted);
        await applyExtractionReview(session.id, draftRows, extracted, {
          defaultMode: 'replace',
          successToastPrefix: 'Session extraction',
        });
      } catch (err) {
        showToast(err.message, 'error');
      } finally {
        _setLabelBusy(extractLabel, false);
        e.target.value = '';
      }
    });
  });

  el.querySelector('#btn-resume-extraction')?.addEventListener('click', async function () {
    const btn = this;
    await _withActionLock(`workflow:session-extract:${classId}`, async () => {
      const session = getActiveSession();
      if (!session) return;
      showToast('Loading latest extraction', 'info');
      _setBusy(btn, true);
      try {
        const latest = await api(`/sessions/${session.id}/uploads/latest`);
        const draftRows = _draftExtractionRows(latest);
        await applyExtractionReview(session.id, draftRows, latest, {
          defaultMode: latest.reviewed ? 'append' : 'replace',
          successToastPrefix: 'Resumed extraction',
        });
      } catch (err) {
        const detail = String(err?.message || '');
        if (detail.toLowerCase().includes('no extraction upload')) {
          showToast('No extraction found yet. Upload a session image first.', 'warning');
        } else {
          showToast(detail || 'Failed to resume extraction.', 'error');
        }
      } finally {
        _setBusy(btn, false);
      }
    });
  });

  /*  update attendance mid-session  */
  el.querySelector('#btn-save-attendance')?.addEventListener('click', async () => {
    await _withActionLock(`workflow:save-attendance:${classId}`, async () => {
      const session = getActiveSession();
      if (!session) { showToast('No active session.', 'warning'); return; }
      const absentIds = _resolveSessionAbsentIds(session);
      const saveBtn = el.querySelector('#btn-save-attendance');
      _setBusy(saveBtn, true);
      try {
        // Update attendance while keeping active session open (no end_time in payload).
        await api(`/workflow/classes/${classId}/sessions/${session.id}/end`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ absent_student_ids: absentIds }),
        });
        const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
        if (ws) {
          setWorkspace(ws);
          _activeTab = ws.active_session ? 2 : 0;
          _render(el, classId);
        }
        showToast('Attendance saved.', 'ok');
      } catch (err) {
        _setBusy(saveBtn, false);
        if (_isClosedSessionConflict(err)) {
          const ws = await api(`/workflow/classes/${classId}`).catch(() => null);
          if (ws) {
            setWorkspace(ws);
            _activeTab = ws.active_session ? 2 : 0;
            _render(el, classId);
          }
          showToast('Session was already closed. Workspace refreshed.', 'warning');
          return;
        }
        showToast(err.message, 'error');
      }
    });
  });

  /*  close unit  (POST /workflow/classes/{id}/units/{uid}/close)  */
  el.querySelector('#btn-close-unit')?.addEventListener('click', async () => {
    await _withActionLock(`workflow:close-unit:${classId}`, async () => {
      const unit = getActiveUnit();
      if (!unit) return;
      const ok = await askConfirm('Close this unit? You can start a new one afterwards.');
      if (!ok) return;
      const closeBtn = el.querySelector('#btn-close-unit');
      _setBusy(closeBtn, true);
      try {
        await api(`/workflow/classes/${classId}/units/${unit.id}/close`, { method: 'POST' });
        const ws = await api(`/workflow/classes/${classId}`);
        setWorkspace(ws);
        _activeTab = 0;
        _render(el, classId);
        showToast('Unit closed!', 'ok');
      } catch (err) {
        _setBusy(closeBtn, false);
        showToast(err.message, 'error');
      }
    });
  });

  el.querySelector('#btn-view-ai-details')?.addEventListener('click', async function () {
    const button = this;
    await _withActionLock(`workflow:unit-blueprint:${classId}`, async () => {
      const unit = getActiveUnit();
      if (!unit?.id) return;
      _setBusy(button, true);
      try {
        const state = await _loadUnitBlueprint(classId, unit.id, { force: true });
        if (state?.error) {
          showToast(state.error, 'error');
          _setBusy(button, false);
          return;
        }
        if (!state?.item) {
          showToast('No AI extraction details are saved for this unit yet.', 'warning');
          _setBusy(button, false);
          return;
        }
        _setBusy(button, false);
        _openUnitBlueprintModal(unit, state.item, classId);
      } catch (err) {
        _setBusy(button, false);
        showToast(String(err?.message || 'Failed to load AI extraction details.'), 'error');
      }
    });
  });

  el.querySelector('#btn-ask-unit-assistant')?.addEventListener('click', async function () {
    const button = this;
    await _withActionLock(`workflow:unit-assistant:${classId}`, async () => {
      const unit = getActiveUnit();
      if (!unit?.id) return;
      _setBusy(button, true);
      try {
        const state = await _loadUnitBlueprint(classId, unit.id, { force: false });
        if (state?.error) {
          showToast(state.error, 'error');
          _setBusy(button, false);
          return;
        }
        if (!state?.item) {
          showToast('No saved unit intelligence is available for this unit yet.', 'warning');
          _setBusy(button, false);
          return;
        }
        _setBusy(button, false);
        _openUnitAssistantModal({ classId, unit, blueprint: state.item });
      } catch (err) {
        _setBusy(button, false);
        showToast(String(err?.message || 'Failed to open unit guidance.'), 'error');
      }
    });
  });

  el.querySelector('#btn-start-preview-session')?.addEventListener('click', () => {
    el.querySelector('#btn-start-session')?.click();
  });

  el.querySelector('#btn-preview-session-assistant')?.addEventListener('click', () => {
    const unit = getActiveUnit();
    if (!unit?.id) {
      el.querySelector('#btn-ask-unit-assistant')?.click();
      return;
    }
    _withActionLock(`workflow:unit-assistant-preview:${classId}`, async () => {
      try {
        const state = await _loadUnitBlueprint(classId, unit.id, { force: false });
        if (state?.error) {
          showToast(state.error, 'error');
          return;
        }
        if (!state?.item) {
          showToast('No saved unit intelligence is available for this unit yet.', 'warning');
          return;
        }
        const fallbackTitle = String(previewResumeItem?.title || '').trim();
        const initialSectionTitle = String(previewResumeSectionPlan?.section_title || fallbackTitle).trim();
        const initialSectionPath = Array.isArray(previewResumeSectionPlan?.section_path) ? previewResumeSectionPlan.section_path : [];
        const suggestedRequest = Array.isArray(previewResumePlaybookEntry?.suggested_requests) && previewResumePlaybookEntry.suggested_requests.length
          ? String(previewResumePlaybookEntry.suggested_requests[0] || '').trim()
          : '';
        const suggestedAction = Array.isArray(previewResumePlaybookEntry?.available_actions) && previewResumePlaybookEntry.available_actions.length
          ? String(previewResumePlaybookEntry.available_actions[0] || '').trim().toLowerCase()
          : 'explain_section';
        const initialTeacherRequest = suggestedRequest || (fallbackTitle
          ? `Help me prepare the next unfinished part of this session: ${fallbackTitle}.`
          : '');
        _openUnitAssistantModal({
          classId,
          unit,
          blueprint: state.item,
          initial: {
            sectionTitle: initialSectionTitle,
            sectionPath: initialSectionPath,
            teacherRequest: initialTeacherRequest,
            assistantAction: suggestedAction,
          },
        });
      } catch (err) {
        showToast(String(err?.message || 'Failed to open unit guidance.'), 'error');
      }
    });
  });

  el.querySelectorAll('.btn-preview-next-focus-action').forEach(button => {
    button.addEventListener('click', async () => {
      const unit = getActiveUnit();
      if (!unit?.id) {
        el.querySelector('#btn-ask-unit-assistant')?.click();
        return;
      }
      await _withActionLock(`workflow:unit-assistant-preview-action:${classId}`, async () => {
        try {
          const state = await _loadUnitBlueprint(classId, unit.id, { force: false });
          if (state?.error) {
            showToast(state.error, 'error');
            return;
          }
          if (!state?.item) {
            showToast('No saved unit intelligence is available for this unit yet.', 'warning');
            return;
          }
          const prefill = _buildAssistantPrefillFromPlaybook(
            previewResumePlaybookEntry,
            previewResumeSectionPlan,
            String(previewResumeItem?.title || '').trim(),
            String(button.dataset.assistantAction || 'explain_section').trim().toLowerCase(),
          );
          _openUnitAssistantModal({
            classId,
            unit,
            blueprint: state.item,
            initial: prefill,
          });
        } catch (err) {
          showToast(String(err?.message || 'Failed to open unit guidance.'), 'error');
        }
      });
    });
  });
  const previewGuidanceWrap = el.querySelector('[data-preview-saved-guidance]');
  if (previewGuidanceWrap && previewResumeItem && unit?.id) {
    _hydratePreviewSavedGuidance(previewGuidanceWrap, {
      classId,
      unitId: unit.id,
      sectionPlan: previewResumeSectionPlan,
      fallbackTitle: previewResumeItem.title,
    });
  }

  el.querySelector('#btn-preview-session-materials')?.addEventListener('click', () => {
    el.querySelector('#btn-open-material-studio')?.click();
  });

  el.querySelector('#btn-preview-session-ai-details')?.addEventListener('click', () => {
    el.querySelector('#btn-view-ai-details')?.click();
  });

  el.querySelectorAll('.btn-session-playbook-request').forEach(button => {
    button.addEventListener('click', async () => {
      await _withActionLock(`workflow:unit-assistant-prefill:${classId}`, async () => {
        const unit = getActiveUnit();
        if (!unit?.id) return;
        try {
          const state = await _loadUnitBlueprint(classId, unit.id, { force: false });
          if (state?.error) {
            showToast(state.error, 'error');
            return;
          }
          if (!state?.item) {
            showToast('No saved unit intelligence is available for this unit yet.', 'warning');
            return;
          }
          let sectionPath = [];
          try {
            const raw = String(button.dataset.sectionPath || '[]').trim();
            const parsed = JSON.parse(raw);
            sectionPath = Array.isArray(parsed) ? parsed.map(value => String(value || '').trim()).filter(Boolean) : [];
          } catch {
            sectionPath = [];
          }
          _openUnitAssistantModal({
            classId,
            unit,
            blueprint: state.item,
            initial: {
              sectionTitle: String(button.dataset.sectionTitle || '').trim(),
              sectionPath,
              teacherRequest: String(button.dataset.teacherRequest || '').trim(),
              assistantAction: String(button.dataset.assistantAction || 'explain_section').trim().toLowerCase(),
            },
          });
        } catch (err) {
          showToast(String(err?.message || 'Failed to open the suggested unit guidance.'), 'error');
        }
      });
    });
  });

  el.querySelector('#btn-open-material-studio')?.addEventListener('click', async function () {
    const button = this;
    await _withActionLock(`workflow:unit-material-studio:${classId}`, async () => {
      const unit = getActiveUnit();
      if (!unit?.id) return;
      _setBusy(button, true);
      try {
        const state = await _loadUnitBlueprint(classId, unit.id, { force: false });
        if (state?.error) {
          showToast(state.error, 'error');
          _setBusy(button, false);
          return;
        }
        if (!state?.item) {
          showToast('No saved unit intelligence is available for this unit yet.', 'warning');
          _setBusy(button, false);
          return;
        }
        _setBusy(button, false);
        await _openUnitMaterialStudioModal({ classId, unit, blueprint: state.item });
      } catch (err) {
        _setBusy(button, false);
        showToast(String(err?.message || 'Failed to open Material Studio.'), 'error');
      }
    });
  });

  const pendingViewIntent = _consumeWorkflowViewIntent(getActiveUnit()?.id);
  if (pendingViewIntent?.action) {
    _workflowEntryContext = pendingViewIntent?.source === 'calendar' ? pendingViewIntent : null;
    if (pendingViewIntent.action === 'session') {
      const activeSession = getActiveSession();
      const intendedSessionId = Number(pendingViewIntent.session_id || 0) || null;
      if (activeSession && (!intendedSessionId || Number(activeSession.id || 0) === intendedSessionId)) {
        _activeTab = 2;
        _render(el, classId);
        return;
      }
    }
    queueMicrotask(async () => {
      const unit = getActiveUnit();
      if (!unit?.id) return;
      try {
        const state = await _loadUnitBlueprint(classId, unit.id, { force: false });
        if (state?.error || !state?.item) {
          showToast(state?.error || 'No saved unit intelligence is available for this unit yet.', 'warning');
          return;
        }
        if (pendingViewIntent.action === 'assistant') {
          _openUnitAssistantModal({
            classId,
            unit,
            blueprint: state.item,
            initial: {
              sectionTitle: pendingViewIntent.section_title,
              sectionPath: pendingViewIntent.section_path,
              teacherRequest: pendingViewIntent.teacher_request,
              assistantAction: pendingViewIntent.assistant_action,
            },
          });
          return;
        }
        if (pendingViewIntent.action === 'material_studio') {
          await _openUnitMaterialStudioModal({ classId, unit, blueprint: state.item });
          return;
        }
        if (pendingViewIntent.action === 'ai_details') {
          _openUnitBlueprintModal(unit, state.item, classId);
        }
      } catch (err) {
        showToast(String(err?.message || 'Failed to open the requested unit tool.'), 'error');
      }
    });
  }

  el.querySelector('#btn-return-to-calendar')?.addEventListener('click', () => {
    if (_workflowEntryContext?.source === 'calendar') {
      _setCalendarViewIntent({
        session_id: _workflowEntryContext.session_id,
        session_date: _workflowEntryContext.session_date,
        preview_hide_done: _workflowPreviewHideDone,
      });
    }
    navigate('calendar');
  });

  el.querySelector('#btn-dismiss-workflow-entry')?.addEventListener('click', () => {
    _workflowEntryContext = null;
    _workflowPreviewFocusOnly = true;
    _workflowPreviewHideDone = false;
    _render(el, classId);
  });

  el.querySelector('#btn-rerun-ai-extraction')?.addEventListener('click', async function () {
    const button = this;
    await _withActionLock(`workflow:unit-reextract:${classId}`, async () => {
      const unit = getActiveUnit();
      if (!unit?.id) return;
      const ok = await askConfirm(
        'Re-run AI extraction for this unit? This will replace the current checklist. For safety, this is only allowed before any unit sessions exist.'
      );
      if (!ok) return;
      _setBusy(button, true);
      try {
        _unitBlueprintCache.delete(Number(unit.id));
        await api(`/workflow/classes/${classId}/units/${unit.id}/reextract`, { method: 'POST' });
        const ws = await api(`/workflow/classes/${classId}`);
        setWorkspace(ws);
        _render(el, classId);
        showToast('AI extraction re-run completed.', 'ok');
      } catch (err) {
        _setBusy(button, false);
        showToast(String(err?.message || 'Failed to re-run AI extraction.'), 'error');
      }
    });
  });

  el.querySelectorAll('.btn-delete-unit').forEach(btn => {
    btn.addEventListener('click', async () => {
      const unitId = Number(btn.dataset.unitId);
      if (!unitId) return;
      await _withActionLock(`workflow:delete-unit:${classId}:${unitId}`, async () => {
        const activeUnit = getActiveUnit();
        const isActive = Number(activeUnit?.id || 0) === unitId;
        const confirmText = isActive
          ? 'Delete this active unit? All linked sessions and checklist progress will be permanently deleted.'
          : 'Delete this unit? All linked sessions and checklist progress will be permanently deleted.';
        const ok = await askConfirm(confirmText, { danger: true });
        if (!ok) return;
        _setBusy(btn, true);
        try {
          const result = await api(`/workflow/classes/${classId}/units/${unitId}`, { method: 'DELETE' });
          const ws = await api(`/workflow/classes/${classId}`);
          setWorkspace(ws);
          _activeTab = 0;
          _render(el, classId);
          const deletedSessions = Number(result?.deleted_sessions_count || 0);
          const sessionLabel = deletedSessions === 1 ? 'session' : 'sessions';
          showToast(`Unit deleted. ${deletedSessions} ${sessionLabel} removed.`, 'ok');
        } catch (err) {
          _setBusy(btn, false);
          showToast(err.message, 'error');
        }
      });
    });
  });

  el.querySelectorAll('.btn-reopen-unit').forEach(btn => {
    btn.addEventListener('click', async () => {
      const unitId = Number(btn.dataset.unitId);
      if (!unitId) return;
      await _withActionLock(`workflow:reopen-unit:${classId}:${unitId}`, async () => {
        if (getActiveUnit()) {
          showToast('Close the current active unit before reopening another one.', 'warning');
          return;
        }
        _setBusy(btn, true);
        try {
          await api(`/workflow/classes/${classId}/units/${unitId}/reopen`, { method: 'POST' });
          const ws = await api(`/workflow/classes/${classId}`);
          setWorkspace(ws);
          _activeTab = 0;
          _render(el, classId);
          showToast('Closed unit reopened.', 'ok');
        } catch (err) {
          _setBusy(btn, false);
          showToast(err.message, 'error');
        }
      });
    });
  });

  const activeUnit = getActiveUnit();
  if (activeUnit?.id) {
    const timelineState = _getUnitTimelineState(activeUnit.id);
    const expectedSignature = _buildUnitTimelineSignature(activeUnit.id);
    const needsRefresh = !timelineState.loaded || timelineState.signature !== expectedSignature;
    if (!timelineState.loading && needsRefresh) {
      _loadUnitTimeline(activeUnit.id, { force: timelineState.loaded }).then(() => {
        const latestUnit = getActiveUnit();
        if (Number(latestUnit?.id || 0) !== Number(activeUnit.id)) return;
        _render(el, classId);
      });
    }
    const blueprintState = _getUnitBlueprintState(activeUnit.id);
    if (!blueprintState.loading && !blueprintState.loaded) {
      _loadUnitBlueprint(classId, activeUnit.id, { force: false }).then(() => {
        const latestUnit = getActiveUnit();
        if (Number(latestUnit?.id || 0) !== Number(activeUnit.id)) return;
        _render(el, classId);
      });
    }
    if (autoLoadSession?.id) {
      const autoWriteupState = _getSessionWriteupState(autoLoadSession.id);
      if ((autoLoadSession.has_saved_writeup || autoWriteupState.item) && !autoWriteupState.loaded && !autoWriteupState.loading) {
        _loadSessionWriteup(autoLoadSession.id, classId, { force: false }).then(() => {
          const latestSession = getActiveSession();
          if (!latestSession || Number(latestSession.id) !== Number(autoLoadSession.id)) return;
          _render(el, classId);
        });
      }
    }
  }
}

function _editChecklistItemModal({ title = '', item_kind = 'other', mode = 'create' } = {}) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-lg">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">${mode === 'edit' ? 'Edit Checklist Item' : 'Add Checklist Item'}</h2>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="flex flex-col gap-1.5">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Title</label>
            <input id="check-item-title" type="text" class="!h-10" value="${_escapeHtmlAttr(String(title || ''))}" placeholder="Checklist item title" />
          </div>
          <div class="flex flex-col gap-1.5">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Kind</label>
            <select id="check-item-kind" class="!h-10">
              ${CHECKLIST_KINDS.map(kind => `<option value="${kind}" ${String(item_kind || 'other') === kind ? 'selected' : ''}>${kind}</option>`).join('')}
            </select>
          </div>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end">
          <button id="check-item-cancel" class="btn btn-ghost">Cancel</button>
          <button id="check-item-save" class="btn btn-primary">${mode === 'edit' ? 'Save' : 'Add'}</button>
        </div>
      </div>`;

    function cleanup(value) {
      overlay.remove();
      resolve(value);
    }

    overlay.addEventListener('click', e => {
      if (e.target === overlay) cleanup(null);
    });
    overlay.querySelector('#check-item-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#check-item-save')?.addEventListener('click', () => {
      const titleValue = String(overlay.querySelector('#check-item-title')?.value || '').trim();
      const kindValue = String(overlay.querySelector('#check-item-kind')?.value || 'other');
      if (!titleValue) {
        showToast('Title is required.', 'warning');
        return;
      }
      cleanup({ title: titleValue, item_kind: kindValue });
    });

    document.body.appendChild(overlay);
    overlay.querySelector('#check-item-title')?.focus();
  });
}

function _editWorkflowSessionEndModal(session) {
  return new Promise(resolve => {
    const dateValue = _toDateInputValue(session?.session_date || session?.date || new Date());
    const startValue = _toTimeInputValue(session?.start_time || '');
    const endValue = _toTimeInputValue(session?.end_time || new Date());
    const noteValue = String(session?.note || '');
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-lg w-[95vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">End Session</h2>
          <p class="text-[12px] text-slate-500 mt-1">Review date/time before closing this session.</p>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Date</label>
              <input id="end-session-date" type="date" value="${_escapeHtmlAttr(dateValue)}" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Start</label>
              <input id="end-session-start" type="time" value="${_escapeHtmlAttr(startValue)}" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">End</label>
              <input id="end-session-end" type="time" value="${_escapeHtmlAttr(endValue)}" />
            </div>
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Note</label>
            <textarea id="end-session-note" rows="3" placeholder="Session note (optional)">${_escapeHtml(noteValue)}</textarea>
          </div>
          <p id="end-session-error" class="text-[12px] text-red-600 hidden"></p>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="end-session-cancel" class="btn btn-ghost">Cancel</button>
          <button id="end-session-save" class="btn btn-danger">End Session</button>
        </div>
      </div>`;

    const errorEl = () => overlay.querySelector('#end-session-error');
    const setError = (message) => {
      const el = errorEl();
      if (!el) return;
      const text = String(message || '').trim();
      el.textContent = text;
      el.classList.toggle('hidden', !text);
    };

    function cleanup(value) {
      overlay.remove();
      resolve(value);
    }

    overlay.addEventListener('click', e => {
      if (e.target === overlay) cleanup(null);
    });
    overlay.querySelector('#end-session-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#end-session-save')?.addEventListener('click', () => {
      const sessionDate = String(overlay.querySelector('#end-session-date')?.value || '').trim();
      const startInput = String(overlay.querySelector('#end-session-start')?.value || '').trim();
      const endInput = String(overlay.querySelector('#end-session-end')?.value || '').trim();
      const noteText = String(overlay.querySelector('#end-session-note')?.value || '').trim();

      if (!endInput) {
        setError('End time is required to close the session.');
        return;
      }
      if (startInput && endInput && endInput < startInput) {
        setError('End time must be greater than or equal to start time.');
        return;
      }

      const payload = {};
      if (sessionDate) payload.session_date = sessionDate;
      if (startInput) payload.start_time = _toPayloadTime(startInput);
      payload.end_time = _toPayloadTime(endInput);
      payload.note = noteText;
      cleanup(payload);
    });

    document.body.appendChild(overlay);
    overlay.querySelector('#end-session-end')?.focus();
  });
}

function _draftExtractionRows(extracted) {
  const sourceItems = Array.isArray(extracted?.items) ? extracted.items : [];
  if (sourceItems.length) {
    return sourceItems
      .map((item, index) => ({
        raw_type: String(item?.item_type || '').trim().toLowerCase(),
        heading: String(item?.heading || '').trim(),
        content: String(item?.content || '').trim(),
        position: Number.isFinite(Number(item?.position)) ? Number(item.position) : index + 1,
        index,
      }))
      .sort((a, b) => {
        const diff = a.position - b.position;
        return diff !== 0 ? diff : a.index - b.index;
      })
      .map(item => {
        const itemType = ['lesson', 'activity', 'exercise'].includes(item.raw_type) ? item.raw_type : 'lesson';
        const text = itemType === 'lesson'
          ? (item.heading || item.content)
          : (item.content || item.heading);
        return { item_type: itemType, text: String(text || '').trim() };
      })
      .filter(row => row.text);
  }

  const rows = [];
  (extracted?.lesson_headings || []).forEach(text => rows.push({ item_type: 'lesson', text: String(text || '').trim() }));
  (extracted?.activities || []).forEach(text => rows.push({ item_type: 'activity', text: String(text || '').trim() }));
  (extracted?.exercises || []).forEach(text => rows.push({ item_type: 'exercise', text: String(text || '').trim() }));
  return rows.filter(row => row.text);
}

function _rowsToConfirmItems(rows) {
  let position = 1;
  const output = [];
  rows.forEach(row => {
    const text = String(row?.text || '').trim();
    const itemType = String(row?.item_type || '').trim();
    if (!text) return;
    if (!['lesson', 'activity', 'exercise'].includes(itemType)) return;
    if (itemType === 'lesson') {
      output.push({ item_type: 'lesson', heading: text, content: null, position: position++ });
      return;
    }
    output.push({
      item_type: itemType,
      heading: itemType === 'activity' ? 'Activity' : 'Exercise',
      content: text,
      position: position++,
    });
  });
  return output;
}

function _reviewExtractionRows(initialRows, extractedMeta, options = {}) {
  return new Promise(resolve => {
    const rows = initialRows.map(row => ({ ...row }));
    let applyMode = _coerceExtractionMode(options.defaultMode);
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-3xl w-[95vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">Review Extraction</h2>
          <p class="text-[12px] text-slate-500 mt-1">
            Provider: ${String(extractedMeta?.provider || 'unknown')}
            ${extractedMeta?.confidence != null ? `    Confidence: ${Math.round(Number(extractedMeta.confidence) * 100)}%` : ''}
            ${extractedMeta?.fallback_reason ? `    Fallback: ${String(extractedMeta.fallback_reason)}` : ''}
          </p>
        </div>
        <div class="px-6 pt-4 pb-1">
          <p class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider mb-2">Apply Mode</p>
          <div class="grid gap-2 sm:grid-cols-2">
            ${EXTRACTION_APPLY_MODES.map(mode => `
            <label class="extraction-mode-card ${applyMode === mode.key ? 'selected' : ''}" data-mode-card="${mode.key}">
              <input
                type="radio"
                name="review-apply-mode"
                value="${mode.key}"
                ${applyMode === mode.key ? 'checked' : ''} />
              <span class="flex flex-col gap-0.5">
                <span class="text-[12px] font-semibold text-slate-700">${mode.label}</span>
                <span class="text-[11px] text-slate-500">${mode.hint}</span>
              </span>
            </label>`).join('')}
          </div>
        </div>
        <div class="px-6 pb-2"><div style="border-top: 1.5px solid var(--border)"></div></div>
        <div class="px-6 pt-4 pb-3">
          <div class="flex gap-2 flex-wrap">
            <button id="add-lesson" class="btn btn-secondary btn-sm">+ Lesson</button>
            <button id="add-activity" class="btn btn-secondary btn-sm">+ Activity</button>
            <button id="add-exercise" class="btn btn-secondary btn-sm">+ Exercise</button>
          </div>
        </div>
        <div id="review-list" class="px-6 pb-4 max-h-[48vh] overflow-y-auto"></div>
        <div class="px-6 pb-5 pt-2 flex gap-3 justify-end border-t border-slate-100">
          <button id="review-cancel" class="btn btn-ghost">Cancel</button>
          <button id="review-apply" class="btn btn-primary">Apply To Session</button>
        </div>
      </div>`;

    const list = overlay.querySelector('#review-list');

    function renderRows() {
      if (!rows.length) {
        list.innerHTML = `<div class="py-6 text-center"><p class="text-[13px] text-slate-500">No items. Add at least one item above to apply.</p></div>`;
        return;
      }
      list.innerHTML = rows.map((row, idx) => {
        return `
        <div class="grid grid-cols-[110px,1fr,auto] gap-2 items-center p-2 rounded-lg border border-slate-200 bg-white mb-1.5 hover:bg-slate-50">
          <select data-type-index="${idx}" class="!h-8 !text-[12px] !border-slate-200">
            <option value="lesson" ${row.item_type === 'lesson' ? 'selected' : ''}>Lesson</option>
            <option value="activity" ${row.item_type === 'activity' ? 'selected' : ''}>Activity</option>
            <option value="exercise" ${row.item_type === 'exercise' ? 'selected' : ''}>Exercise</option>
          </select>
          <input data-text-index="${idx}" value="${_escapeHtml(row.text)}" type="text" class="!h-8 !text-[12px]" placeholder="Enter text..." />
          <div class="flex gap-0.5">
            <button data-action="up" data-index="${idx}" class="btn btn-ghost btn-sm !px-1.5" title="Move up">Up</button>
            <button data-action="down" data-index="${idx}" class="btn btn-ghost btn-sm !px-1.5" title="Move down">Down</button>
            <button data-action="remove" data-index="${idx}" class="btn btn-ghost btn-sm !text-red-500 !px-1.5" title="Remove">Remove</button>
          </div>
        </div>
      `;
      }).join('');
    }

    function cleanup(result) {
      overlay.remove();
      resolve(result);
    }

    overlay.addEventListener('click', e => {
      if (e.target === overlay) cleanup(null);
    });



    overlay.addEventListener('change', e => {
      const target = e.target;
      if (target.matches('input[name="review-apply-mode"]')) {
        applyMode = _coerceExtractionMode(target.value);
        // update selected card styling
        overlay.querySelectorAll('[data-mode-card]').forEach(card => {
          card.classList.toggle('selected', card.dataset.modeCard === applyMode);
        });
        return;
      }
      if (target.matches('[data-type-index]')) {
        const idx = Number(target.dataset.typeIndex);
        if (!Number.isNaN(idx) && rows[idx]) rows[idx].item_type = target.value;
      }
    });

    overlay.addEventListener('input', e => {
      const target = e.target;
      if (target.matches('[data-text-index]')) {
        const idx = Number(target.dataset.textIndex);
        if (!Number.isNaN(idx) && rows[idx]) rows[idx].text = target.value;
      }
    });

    overlay.addEventListener('click', e => {
      const target = e.target;
      if (target.id === 'review-cancel') {
        cleanup(null);
        return;
      }
      if (target.id === 'review-apply') {
        const items = _rowsToConfirmItems(rows);
        if (!items.length) {
          showToast('Add at least one valid item before applying.', 'warning');
          return;
        }
        cleanup({ items, mode: applyMode });
        return;
      }
      if (target.id === 'add-lesson') {
        rows.push({ item_type: 'lesson', text: '' });
        renderRows();
        return;
      }
      if (target.id === 'add-activity') {
        rows.push({ item_type: 'activity', text: '' });
        renderRows();
        return;
      }
      if (target.id === 'add-exercise') {
        rows.push({ item_type: 'exercise', text: '' });
        renderRows();
        return;
      }
      if (!target.matches('[data-action]')) return;
      const action = target.dataset.action;
      const idx = Number(target.dataset.index);
      if (Number.isNaN(idx) || !rows[idx]) return;
      if (action === 'remove') {
        rows.splice(idx, 1);
        renderRows();
        return;
      }
      if (action === 'up' && idx > 0) {
        [rows[idx - 1], rows[idx]] = [rows[idx], rows[idx - 1]];
        renderRows();
        return;
      }
      if (action === 'down' && idx < rows.length - 1) {
        [rows[idx], rows[idx + 1]] = [rows[idx + 1], rows[idx]];
        renderRows();
      }
    });

    document.body.appendChild(overlay);
    renderRows();
  });
}

function _escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function _escapeHtmlAttr(value) {
  return _escapeHtml(value).replaceAll("'", '&#39;');
}

function _showChrome() {
  const topbar = document.getElementById('topbar');
  const sidebar = document.getElementById('sidebar');
  const btabs = document.getElementById('bottom-tabs');
  const main = document.getElementById('app-main');
  const app = document.getElementById('app');
  if (topbar) topbar.style.display = '';
  if (sidebar) sidebar.style.display = '';
  if (btabs) btabs.style.display = '';
  if (main) main.style.cssText = '';
  if (app) app.style.cssText = '';
}

