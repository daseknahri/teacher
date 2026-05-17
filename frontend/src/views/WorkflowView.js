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

let _activeTab = 0;
let _recentWindow = 'month';
let _selectedUnitType = 'chapter';
let _checklistCollapseUnitId = null;
const _collapsedChecklistIds = new Set();
const _inFlightActions = new Set();
const _sessionProgressCache = new Map();
const _sessionWriteupCache = new Map();
const _unitSessionTimelineCache = new Map();
const _unitBlueprintCache = new Map();
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

function _openUnitBlueprintModal(unit, blueprint) {
  const provider = String(blueprint?.provider || unit?.extraction_source || 'unknown');
  const model = String(blueprint?.model || unit?.extraction_model || '').trim();
  const status = String(blueprint?.status || unit?.extraction_status || '').trim();
  const errorMessage = String(blueprint?.error_message || unit?.extraction_error || '').trim();
  const blueprintJson = blueprint?.blueprint_json && typeof blueprint.blueprint_json === 'object' ? blueprint.blueprint_json : {};
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
          </div>
          ${errorMessage ? `<p class="text-[12px] text-amber-700"><span class="font-semibold">Provider note:</span> ${_escapeHtml(errorMessage)}</p>` : ''}
          <p class="text-[12px] text-slate-600"><span class="font-semibold">Notebook ID:</span> ${_escapeHtml(providerContext?.notebook_id || rawProviderPayload?.notebook_id || 'None')}</p>
          <p class="text-[12px] text-slate-600"><span class="font-semibold">Source IDs:</span> ${sourceIds.length ? _escapeHtml(sourceIds.join(', ')) : _escapeHtml(String(rawProviderPayload?.source_ids || 'None'))}</p>
          ${responseMode ? `<p class="text-[12px] text-slate-600"><span class="font-semibold">Response mode:</span> ${_escapeHtml(responseMode)}</p>` : ''}
          ${selectedVariant ? `<p class="text-[12px] text-slate-600"><span class="font-semibold">Selected variant:</span> ${_escapeHtml(selectedVariant)}</p>` : ''}
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
              <pre class="mt-3 text-[11px] leading-5 whitespace-pre-wrap break-words text-slate-700 font-mono">${_escapeHtml(String(row?.answer || ''))}</pre>
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
    const ws = await api(`/workflow/classes/${classId}`);
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
  const sessionProgressState = session ? _getSessionProgressState(session.id) : _emptySessionProgressState();
  const sessionWriteupState = session ? _getSessionWriteupState(session.id) : _emptySessionWriteupState();
  const closed = getClosedUnits();
  const recentSessions = getRecentSessions();
  const visibleRecentSessions = _filterRecentSessions(recentSessions, _recentWindow);
  const unitTimelineState = unit ? _getUnitTimelineState(unit.id) : _emptyUnitTimelineState();
  const students = getStudents();
  const todayDateValue = _toDateInputValue(new Date());

  // Progress ring
  const checklist = _checklist(unit);
  _syncChecklistCollapseState(unit, checklist);
  const checklistChildrenCount = _buildChecklistChildrenCount(checklist);
  const visibleChecklist = _visibleChecklistRows(checklist, _collapsedChecklistIds);
  const moveMeta = _buildChecklistMoveMeta(checklist);
  const done = checklist.filter(i => Boolean(i?.is_completed || i?.done)).length;
  const total = checklist.length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const r = 36, circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ;
  const extractionSource = String(unit?.extraction_source || '').trim().toLowerCase();
  const extractionStatus = String(unit?.extraction_status || '').trim().toLowerCase();
  const extractionError = String(unit?.extraction_error || '').trim();
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

      <!-- Live session banner -->
      ${session ? `
      <div class="live-banner">
        <div class="live-dot"></div>
        <div class="flex-1">
          <span class="font-semibold text-amber-800">Session in progress${session.unit_session_number ? ` • Unit Session ${session.unit_session_number}` : ''}</span>
          <span class="text-amber-600 ml-2 text-[12px]">Started at ${fmtTime(session.start_time)} | ${fmtDate(session.session_date || session.date)}</span>
        </div>
        <button id="btn-end-session-banner"
          class="btn btn-danger btn-sm">End Session</button>
      </div>` : ''}

      <!-- Tab strip -->
      <div class="card overflow-hidden">
        <div class="flex border-b border-slate-100">
          ${tabs.map((t, i) => `
          <button class="tab-btn flex-1 justify-center ${i === _activeTab ? 'active' : ''} ${t.disabled ? 'disabled-tab' : ''}"
                  data-tab="${i}">${t.label}</button>`).join('')}
        </div>

        <!-- TAB 0: Unit Setup -->
        <div class="${_activeTab === 0 ? 'block' : 'hidden'}">
          <div class="p-5 flex flex-col gap-5">
            ${unit ? `
            <!-- Current unit: progress ring + info -->
            <div class="flex flex-col sm:flex-row gap-5 items-start">
              <div class="flex items-center gap-4 p-4 bg-slate-50 rounded-2xl border border-slate-200 flex-shrink-0">
                <svg width="90" height="90" class="-rotate-90">
                  <circle cx="45" cy="45" r="${r}" stroke-width="8" class="progress-ring-track"/>
                  <circle cx="45" cy="45" r="${r}" stroke-width="8"
                    stroke-dasharray="${circ}" stroke-dashoffset="${offset}"
                    class="progress-ring-fill transition-all duration-500"/>
                </svg>
                <div>
                  <div class="text-3xl font-bold text-slate-800 tracking-tight leading-none">${pct}%</div>
                  <div class="text-[12px] text-slate-400 mt-1">${done}/${total} items done</div>
                </div>
              </div>
              <div class="flex-1 flex flex-col gap-3">
                <div>
                  <h2 class="text-lg font-bold text-slate-800">${unit.title || unit.name || ''}</h2>
                  <p class="text-[12px] text-slate-500 mt-0.5">Created ${fmtDate(unit.created_at || unit.createdAt)}</p>
                  <div class="flex items-center gap-2 flex-wrap mt-1">
                    ${unit.unit_type ? `<span class="badge badge-blue">${unit.unit_type}</span>` : ''}
                    <span class="badge ${extractionBadgeClass}">Extraction ${_escapeHtml(extractionLabel)}</span>
                    ${unit.extraction_model ? `<span class="badge badge-gray">${_escapeHtml(String(unit.extraction_model))}</span>` : ''}
                    ${extractionStatus ? `<span class="badge badge-gray">${_escapeHtml(extractionStatus)}</span>` : ''}
                  </div>
                  ${extractionError ? `<p class="text-[11px] text-amber-700 mt-1">Provider note: ${_escapeHtml(extractionError)}</p>` : ''}
                </div>
                <div class="flex gap-2 flex-wrap mt-auto">
                  ${!session ? `<button id="btn-start-session" class="btn btn-success">Start Session</button>` : ''}
                  ${unit.document_name ? `<button id="btn-download-unit-doc" class="btn btn-secondary btn-sm">Unit PDF</button>` : ''}
                  <button id="btn-view-ai-details" class="btn btn-secondary btn-sm">AI Details</button>
                  <button id="btn-plan-active-unit" class="btn btn-secondary btn-sm">Plan Sessions</button>
                  <button id="btn-add-item-root" class="btn btn-secondary btn-sm">Add Item</button>
                  <button id="btn-close-unit" class="btn btn-ghost btn-sm !text-slate-400">Close Unit</button>
                  <button id="btn-delete-unit" class="btn btn-danger btn-sm btn-delete-unit" data-unit-id="${unit.id}">Delete Unit</button>
                </div>
              </div>
            </div>
            <!-- Checklist tree -->
            ${checklist.length ? `
            <div class="flex flex-col gap-1 checklist-dnd-root" data-checklist-dnd-root>
              <div class="flex items-center justify-between gap-2 mb-1">
                <h4 class="text-[12px] font-semibold text-slate-600">Checklist</h4>
                <div class="flex items-center gap-1">
                  <button id="btn-checklist-expand-all" class="btn btn-ghost btn-sm !text-slate-500" title="Expand all checklist branches">Expand All</button>
                  <button id="btn-checklist-collapse-all" class="btn btn-ghost btn-sm !text-slate-500" title="Collapse all checklist branches">Collapse All</button>
                </div>
              </div>
              <div class="flex items-center gap-2 px-2 py-1.5 bg-blue-50/50 rounded-lg border border-blue-100/50 mb-1">
                <span class="text-[10px] font-bold">INFO</span>
                <p class="text-[11px] text-blue-700 leading-tight">
                  <span class="font-bold">Hold handle to reorder.</span> Drop Top = Before, Middle = Nested Child, Bottom = After.
                </p>
              </div>
              ${visibleChecklist.map(item => {
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
    return `
              <div class="todo-node group checklist-draggable-node ${isDone ? 'done' : ''}"
                   data-item-id="${item.id}" data-dnd-target-id="${item.id}"
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
                ${item.item_kind && item.item_kind !== 'other' ? `<span class="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500 flex-shrink-0">${item.item_kind}</span>` : ''}
                <div class="row-hover-actions flex items-center gap-1 ml-auto flex-wrap">
                  <button class="btn btn-ghost btn-sm !text-slate-500 btn-item-up ${meta.canUp ? '' : 'opacity-40 pointer-events-none'}" data-item-id="${item.id}" title="Move up">Up</button>
                  <button class="btn btn-ghost btn-sm !text-slate-500 btn-item-down ${meta.canDown ? '' : 'opacity-40 pointer-events-none'}" data-item-id="${item.id}" title="Move down">Down</button>
                  <button class="btn btn-ghost btn-sm !text-slate-500 btn-item-indent ${meta.canIndent ? '' : 'opacity-40 pointer-events-none'}" data-item-id="${item.id}" title="Nest under previous">In</button>
                  <button class="btn btn-ghost btn-sm !text-slate-500 btn-item-outdent ${meta.canOutdent ? '' : 'opacity-40 pointer-events-none'}" data-item-id="${item.id}" title="Move one level up">Out</button>
                  <button class="btn btn-ghost btn-sm !text-slate-400 todo-drag-handle transition-all hover:!text-blue-500" data-drag-item-id="${item.id}" draggable="true" title="Drag to reorder / nest">Drag</button>
                  <div class="h-4 w-px bg-slate-200 mx-0.5"></div>
                  <button class="btn btn-ghost btn-sm !text-slate-500 btn-item-add-child" data-item-id="${item.id}" title="Add child">Child</button>
                  <button class="btn btn-ghost btn-sm !text-blue-600 btn-item-edit" data-item-id="${item.id}" data-item-kind="${item.item_kind || 'other'}" data-item-title="${_escapeHtmlAttr(item.title)}" title="Edit item">Edit</button>
                  <button class="btn btn-ghost btn-sm !text-red-600 btn-item-delete" data-item-id="${item.id}" title="Delete item">Delete</button>
                </div>
              </div>`;
  }).join('')}
              <div class="todo-root-dropzone text-[11px] text-slate-500" data-dnd-root-drop>Drop here to move item to root level (end)</div>
            </div>` : '<p class="text-[13px] text-slate-400">No checklist items for this unit.</p>'}
            ` : `
            <!-- No active unit -->
            <div class="text-center py-12 bg-slate-50/50 rounded-2xl border border-dashed border-slate-200">
              <div class="text-xl font-black opacity-30 mb-4">UNIT</div>
              <h3 class="font-bold text-slate-800 mb-2">No active unit</h3>
              <p class="text-[13px] text-slate-500 max-w-[240px] mx-auto">Create a new unit below or upload a PDF to extract a curriculum.</p>
            </div>`}

            <!-- Create unit form -->
            <div class="bg-slate-50 rounded-2xl border border-slate-200 p-4 flex flex-col gap-3">
              <h4 class="text-[13px] font-semibold text-slate-600">New Unit</h4>
              <!-- Unit type selector -->
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
              <input id="unit-name" type="text" placeholder="Unit title (e.g. Chapter 4 - Photosynthesis)" ${unit ? 'disabled' : ''} />
              <input id="unit-planned-hours" type="number" min="0.25" step="0.25" placeholder="Planned hours (optional, > 0)" ${unit ? 'disabled' : ''} />
              <div class="rounded-xl border border-slate-200 bg-white p-3 flex flex-col gap-2">
                <label class="inline-flex items-center gap-2 text-[12px] text-slate-700">
                  <input id="unit-auto-plan-enable" type="checkbox" ${unit ? 'disabled' : ''} />
                  <span class="font-semibold">Auto-create sessions from timetable</span>
                </label>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <div class="flex flex-col gap-1">
                    <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Sessions Count</label>
                    <input id="unit-auto-plan-count" type="number" min="1" max="120" step="1" value="6" disabled />
                  </div>
                  <div class="flex flex-col gap-1">
                    <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Start From</label>
                    <input id="unit-auto-plan-start-date" type="date" value="${_escapeHtml(todayDateValue)}" disabled />
                  </div>
                </div>
                <p class="text-[11px] text-slate-500">Uses class emploi, skips blocked Morocco holidays, and jumps to next valid slots automatically.</p>
              </div>
              <p id="unit-form-error" class="text-[12px] text-red-600 hidden"></p>
              <div class="flex gap-2 flex-wrap sm:flex-nowrap">
                <button id="btn-create-unit" class="btn btn-primary flex-1 sm:flex-none ${unit ? 'opacity-60 cursor-not-allowed' : ''}" ${unit ? 'disabled title="Close the current active unit first."' : ''}> Create Unit</button>
                <label id="pdf-upload-label" class="btn btn-secondary flex-1 sm:flex-none cursor-pointer ${unit ? 'opacity-60 pointer-events-none' : ''}" ${unit ? 'title="Close the current active unit first."' : ''}>
                   Extract from PDF
                  <input id="pdf-upload" type="file" accept=".pdf" class="hidden" ${unit ? 'disabled' : ''} />
                </label>
              </div>
              ${unit
      ? '<p class="text-[12px] text-amber-700">Close the current active unit before creating or extracting a new one.</p>'
      : '<p class="text-[12px] text-slate-500">Create a unit manually or extract one from a PDF.</p>'}
            </div>

            ${recentSessions.length ? `
            <!-- Recent sessions -->
            <div class="flex flex-col gap-2">
              <div class="flex items-center justify-between gap-2 flex-wrap">
                <h4 class="text-[12px] font-semibold text-slate-400 uppercase tracking-wider">Recent Sessions</h4>
                <div class="flex gap-1 flex-wrap">
                  ${RECENT_SESSION_WINDOWS.map(filter => `
                  <button
                    class="btn btn-ghost btn-sm ${_recentWindow === filter.key ? '!bg-slate-200 !text-slate-700' : '!text-slate-500'}"
                    data-recent-window="${filter.key}">${filter.label}</button>
                  `).join('')}
                </div>
              </div>
              ${visibleRecentSessions.length ? visibleRecentSessions.slice(0, 8).map(s => `
              <div class="px-4 py-3 bg-slate-50 rounded-xl border border-slate-200">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-[13px] font-semibold text-slate-700">${fmtDate(s.session_date || s.date)}</span>
                  <span class="text-[12px] text-slate-500">${fmtTime(s.start_time)}${s.end_time ? '  ' + fmtTime(s.end_time) : ' (active)'}</span>
                </div>
                <div class="mt-1 flex items-center gap-2 flex-wrap">
                  ${s.unit_session_number ? `<span class="badge badge-blue">Session ${s.unit_session_number}</span>` : ''}
                  <span class="badge badge-green">${s.checked_items_count ?? 0} done</span>
                  ${Number(s.absent_count || 0) > 0 ? `<span class="badge badge-red">${s.absent_count} absent</span>` : ''}
                </div>
              </div>`).join('') : '<p class="text-[12px] text-slate-500 px-1">No sessions in this date range.</p>'}
            </div>` : ''}

            ${unit ? `
            <!-- Unit session timeline -->
            <div class="flex flex-col gap-2">
              <div class="flex items-center justify-between gap-2 flex-wrap">
                <h4 class="text-[12px] font-semibold text-slate-400 uppercase tracking-wider">Unit Session Timeline</h4>
                <button class="btn btn-ghost btn-sm !text-slate-500" data-unit-timeline-retry="${unit.id}">Refresh</button>
              </div>
              ${unitTimelineState.loading && !unitTimelineState.loaded ? `
                <p class="text-[12px] text-slate-500 px-1">Loading unit sessions...</p>
              ` : ''}
              ${unitTimelineState.error ? `
                <div class="px-3 py-2 bg-red-50 border border-red-200 rounded-xl">
                  <p class="text-[12px] text-red-700">${_escapeHtml(unitTimelineState.error)}</p>
                </div>
              ` : ''}
              ${!unitTimelineState.loading && !unitTimelineState.error && unitTimelineState.sessions.length ? `
                <div class="max-h-[260px] overflow-auto rounded-xl border border-slate-200">
                  ${unitTimelineState.sessions.map(s => `
                  <div class="px-4 py-3 border-b border-slate-100 last:border-b-0 bg-white">
                    <div class="flex items-center gap-2 flex-wrap">
                      ${s.unit_session_number ? `<span class="badge badge-blue">Session ${s.unit_session_number}</span>` : '<span class="badge badge-gray">Session</span>'}
                      <span class="text-[12px] font-semibold text-slate-700">${fmtDate(s.session_date || s.date)}</span>
                      <span class="text-[12px] text-slate-500">${fmtTime(s.start_time)}${s.end_time ? ` - ${fmtTime(s.end_time)}` : ''}</span>
                      <span class="badge ${s.end_time ? 'badge-green' : 'badge-amber'}">${s.end_time ? 'Closed' : 'Open'}</span>
                    </div>
                    <div class="mt-1 flex items-center gap-2 flex-wrap">
                      <span class="badge badge-green">${s.checked_items_count ?? 0} done</span>
                      ${Number(s.absent_count || 0) > 0 ? `<span class="badge badge-red">${s.absent_count} absent</span>` : ''}
                      ${s.note ? `<span class="text-[11px] text-slate-500 truncate max-w-[320px]" title="${_escapeHtmlAttr(s.note)}">${_escapeHtml(s.note)}</span>` : ''}
                    </div>
                  </div>`).join('')}
                </div>
              ` : ''}
              ${!unitTimelineState.loading && !unitTimelineState.error && !unitTimelineState.sessions.length ? `
                <p class="text-[12px] text-slate-500 px-1">No sessions recorded for this unit yet.</p>
              ` : ''}
            </div>` : ''}

            ${closed.length ? `
            <!-- Past units -->
            <div class="flex flex-col gap-2">
              <h4 class="text-[12px] font-semibold text-slate-400 uppercase tracking-wider">Past Units</h4>
              ${closed.map((u, index) => `
              <div class="flex items-center gap-3 px-4 py-3 bg-slate-50 rounded-xl border border-slate-200">
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
            <div class="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <h3 class="font-semibold text-slate-700">Mark Attendance</h3>
                <p class="text-[12px] text-slate-400">Tap to toggle absent / present</p>
              </div>
              <div class="flex gap-2">
                <span class="badge badge-red">${getAbsentIds().size} absent</span>
                <span class="badge badge-green">${students.length - getAbsentIds().size} present</span>
              </div>
            </div>
            ${students.length === 0 ? `
            <div class="empty-state py-12">
              <div class="text-xl font-black opacity-30">ROSTER</div>
              <p class="text-[13px] text-slate-400">No students - import a roster first.</p>
            </div>` : `
            <div class="workflow-attendance-grid">
              ${students.map(s => {
            const absent = getAbsentIds().has(s.id);
            return `
                  <div class="attendance-card group relative ${absent ? 'absent bg-red-50 border-red-200' : 'present bg-green-50 border-green-200'} p-3 rounded-2xl border-2 transition-all hover:scale-[1.02] cursor-pointer"
                       data-sid="${s.id}"
                       role="button"
                       tabindex="0"
                       aria-pressed="${absent ? 'true' : 'false'}"
                       aria-label="${absent ? 'Mark present: ' : 'Mark absent: '}${_escapeHtmlAttr(s.full_name || 'student')}">
                    <div class="text-[20px] mb-1">${absent ? 'ABS' : 'OK'}</div>
                    <div class="text-[10px] font-bold text-slate-400 uppercase tracking-widest">${s.student_code || 'ID'}</div>
                    <div class="text-[13px] font-bold text-slate-800 text-center leading-tight mt-1 line-clamp-2">${s.full_name || 'N/A'}</div>
                  </div>`;
          }).join('')}
            </div>`}
            <div class="flex gap-2">
              ${!session ? `<button id="btn-start-session-att" class="btn btn-success">Start Session (save attendance)</button>` : ''}
              ${session ? `<button id="btn-save-attendance" class="btn btn-primary">Update Attendance</button>` : ''}
            </div>
          </div>
        </div>

        <!-- TAB 2: Session Active -->
        <div class="${_activeTab === 2 ? 'block' : 'hidden'}">
          <div class="p-5 flex flex-col gap-4">
            ${session ? `
            <div class="flex items-center gap-4 p-4 bg-amber-50 rounded-2xl border border-amber-200">
              <div class="text-[12px] font-black tracking-wide">LIVE</div>
              <div>
                <p class="font-semibold text-amber-800">Session Active</p>
                <p class="text-[12px] text-amber-600">Started at ${fmtTime(session.start_time)} | ${fmtDate(session.session_date || session.date)}</p>
              </div>
            </div>
            <div class="flex gap-2 flex-wrap">
              <label class="btn btn-secondary cursor-pointer">
                Extract Session Image
                <input id="session-upload" type="file" accept=".png,.jpg,.jpeg,.webp,.bmp" class="hidden" />
              </label>
              <button id="btn-resume-extraction" class="btn btn-ghost btn-sm">Resume Last Extraction</button>
            </div>
            <div class="bg-slate-50 rounded-2xl border border-slate-200 p-4 flex flex-col gap-3">
              <div class="flex items-center justify-between gap-2 flex-wrap">
                <div>
                  <h4 class="text-[13px] font-semibold text-slate-700">Session Progress</h4>
                  <p class="text-[12px] text-slate-500">Confirmed extraction items saved in this session.</p>
                </div>
                <div class="flex gap-2">
                  ${!sessionProgressState.loaded ? '<button id="btn-load-session-progress" class="btn btn-ghost btn-sm">Load</button>' : ''}
                  <button id="btn-refresh-session-progress" class="btn btn-ghost btn-sm">Refresh</button>
                </div>
              </div>
              ${sessionProgressState.loading
        ? '<p class="text-[12px] text-slate-500">Loading session progress...</p>'
        : sessionProgressState.error
          ? `<p class="text-[12px] text-red-600">${_escapeHtml(sessionProgressState.error)}</p>`
          : sessionProgressState.loaded
            ? sessionProgressState.items.length
              ? `<div class="flex flex-col gap-1">
                ${sessionProgressState.items.map(item => `
                  <div class="session-progress-item-row">
                    <span class="session-progress-type-badge type-${String(item.item_type || 'lesson').toLowerCase()}">${_progressItemTypeLabel(item.item_type)}</span>
                    <span class="session-progress-item-text">${_escapeHtml(_progressItemLabel(item))}</span>
                  </div>
                `).join('')}
              </div>`
              : '<p class="text-[12px] text-slate-500">No confirmed progress items yet. Extract and apply session notes to populate this list.</p>'
            : '<p class="text-[12px] text-slate-500">Load to preview confirmed progress items for this session.</p>'}
            </div>
            <div class="bg-slate-50 rounded-2xl border border-slate-200 p-4 flex flex-col gap-3">
              <div class="flex items-center justify-between gap-2 flex-wrap">
                <div>
                  <h4 class="text-[13px] font-semibold text-slate-700">Session Write-Up</h4>
                  <p class="text-[12px] text-slate-500">Generate and review the textbook text for this session.</p>
                </div>
                <div class="flex gap-2 flex-wrap">
                  <button id="btn-generate-session-writeup" class="btn btn-primary btn-sm">${session?.has_saved_writeup ? 'Re-generate' : 'Generate'}</button>
                  <button id="btn-edit-session-writeup" class="btn btn-ghost btn-sm" ${sessionWriteupState.item ? '' : 'disabled'}>Edit</button>
                </div>
              </div>
              ${sessionWriteupState.loading
        ? '<p class="text-[12px] text-slate-500">Loading session write-up...</p>'
        : sessionWriteupState.error
          ? `<p class="text-[12px] text-red-600">${_escapeHtml(sessionWriteupState.error)}</p>`
          : sessionWriteupState.item
            ? `
              <div class="rounded-xl border border-slate-200 bg-white p-3 flex flex-col gap-3">
                <div class="flex items-center justify-between gap-2 flex-wrap">
                  <p class="text-[13px] font-semibold text-slate-700">${_escapeHtml(sessionWriteupState.item.title || 'Session write-up')}</p>
                  <span class="badge ${sessionWriteupState.item.approved === false ? 'badge-amber' : 'badge-green'}">${sessionWriteupState.item.approved === false ? 'Draft' : 'Approved'}</span>
                </div>
                ${Array.isArray(sessionWriteupState.item.learning_focus) && sessionWriteupState.item.learning_focus.length ? `
                  <div>
                    <p class="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">Learning Focus</p>
                    <ul class="mt-1 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
                      ${sessionWriteupState.item.learning_focus.map(row => `<li>${_escapeHtml(row)}</li>`).join('')}
                    </ul>
                  </div>` : ''}
                ${Array.isArray(sessionWriteupState.item.teaching_content) && sessionWriteupState.item.teaching_content.length ? `
                  <div class="flex flex-col gap-2">
                    <p class="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">Teaching Content</p>
                    ${sessionWriteupState.item.teaching_content.map(row => `<p class="text-[13px] text-slate-700 leading-relaxed">${_escapeHtml(row)}</p>`).join('')}
                  </div>` : ''}
                ${Array.isArray(sessionWriteupState.item.practice_items) && sessionWriteupState.item.practice_items.length ? `
                  <div>
                    <p class="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">Practice</p>
                    <ul class="mt-1 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
                      ${sessionWriteupState.item.practice_items.map(row => `<li>${_escapeHtml(row)}</li>`).join('')}
                    </ul>
                  </div>` : ''}
              </div>`
            : '<p class="text-[12px] text-slate-500">No saved write-up yet. Generate one after checking the completed items.</p>'}
            </div>
            ${checklist.length ? `
            <div class="flex flex-col gap-1">
              <div class="flex items-center justify-between gap-2 mb-1">
                <h4 class="text-[12px] font-semibold text-slate-600">Session Checklist</h4>
                <div class="flex items-center gap-1">
                  <button data-checklist-expand-all class="btn btn-ghost btn-sm !text-slate-500" title="Expand all checklist branches">Expand All</button>
                  <button data-checklist-collapse-all class="btn btn-ghost btn-sm !text-slate-500" title="Collapse all checklist branches">Collapse All</button>
                </div>
              </div>
              ${visibleChecklist.map(item => {
      const itemId = Number(item.id);
      const hasChildren = Number(checklistChildrenCount.get(itemId) || 0) > 0;
      const isCollapsed = hasChildren && _collapsedChecklistIds.has(itemId);
      const depthPad = _checklistDepthPadding(item.depth);
      return `
              <div class="todo-node group ${item.is_completed || item.done ? 'done' : ''}"
                   data-item-id="${item.id}" data-session-id="${session.id}" data-class-id="${classId}"
                   style="padding-left:${depthPad}px"
                   role="button" tabindex="0"
                   aria-pressed="${item.is_completed || item.done ? 'true' : 'false'}"
                   aria-label="Toggle checklist item: ${_escapeHtmlAttr(item.title)}">
                ${hasChildren
      ? `<button class="btn btn-ghost btn-sm !text-slate-500 btn-checklist-toggle" data-item-id="${item.id}" title="${isCollapsed ? 'Expand branch' : 'Collapse branch'}" aria-label="${isCollapsed ? 'Expand branch' : 'Collapse branch'}">${isCollapsed ? '+' : '-'}</button>`
      : '<span class="inline-block w-6 h-6 flex-shrink-0"></span>'}
                <div class="w-[18px] h-[18px] rounded-[4px] border-2 flex-shrink-0 flex items-center justify-center
                     transition-all mt-px text-[10px] cursor-pointer
                     ${item.is_completed || item.done ? 'bg-green-600 border-green-600 text-white' : 'border-slate-300 bg-white hover:border-green-400'}">
                  ${item.is_completed || item.done ? 'Y' : ''}
                </div>
                <span class="todo-title text-[13px] leading-snug flex-1">${item.title}</span>
              </div>`;
    }).join('')}
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
      if (item.is_completed || item.done) {
        showToast('Unchecking is disabled to keep unit progress flow.', 'info');
        return;
      }

      const descendants = _findDescendantItems(items, numericItemId);
      const affected = [item, ...descendants];
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

  /*  checklist check from Unit Setup  */
  el.querySelectorAll('.btn-unit-check').forEach(btn => {
    btn.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      await applyChecklistCheck(btn.dataset.itemId, { showNoSessionWarning: true });
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
        showToast('Session ended.', 'ok');
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
        _openUnitBlueprintModal(unit, state.item);
      } catch (err) {
        _setBusy(button, false);
        showToast(String(err?.message || 'Failed to load AI extraction details.'), 'error');
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

