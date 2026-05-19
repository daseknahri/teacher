/**
 * CalendarView.js - Weekly session timetable with drag scaffold
 * Teacher Progress App - Tailwind v4
 */
import { api, downloadWithAuth } from '../api/client.js';
import { getSelectedId, getStudents } from '../state/class.js';
import { getActiveSession, getCalendar, setCalendar } from '../state/workflow.js';
import { showToast } from '../utils/toast.js';
import { mountRetryCard } from '../utils/retryView.js';
import { fmtDate, fmtTime } from '../utils/format.js';
import { askConfirm } from '../utils/modal.js';
import { navigate } from '../router.js';
import { copyText } from '../utils/password.js';

let _weekStart = _startOfWeek(new Date());
let _selectedSessionId = null;
let _selectedSessionLoading = false;
let _selectedSessionError = null;
let _mutationInFlight = false;
let _calendarPlannedHideDone = false;
let _calendarSessionGuidanceHideImported = false;
let _holidayByDate = new Map();
const _timetableRulesByClass = new Map();
const _timetableExceptionsByClass = new Map();
const WORKFLOW_VIEW_INTENT_KEY = 'workflow_view_intent';
const CALENDAR_VIEW_INTENT_KEY = 'calendar_view_intent';

const _sessionDetailCache = new Map();
const _calendarUnitBlueprintCache = new Map();
const _calendarAssistantArtifactCache = new Map();

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const TIME_SLOTS = [
  { key: '07', label: '07:00 - 08:00', start: 7 * 60, end: 8 * 60 },
  { key: '08', label: '08:00 - 09:00', start: 8 * 60, end: 9 * 60 },
  { key: '09', label: '09:00 - 10:00', start: 9 * 60, end: 10 * 60 },
  { key: '10', label: '10:00 - 11:00', start: 10 * 60, end: 11 * 60 },
  { key: '11', label: '11:00 - 12:00', start: 11 * 60, end: 12 * 60 },
  { key: '12', label: '12:00 - 13:00', start: 12 * 60, end: 13 * 60 },
  { key: '13', label: '13:00 - 14:00', start: 13 * 60, end: 14 * 60 },
  { key: '14', label: '14:00 - 15:00', start: 14 * 60, end: 15 * 60 },
  { key: '15', label: '15:00 - 16:00', start: 15 * 60, end: 16 * 60 },
  { key: '16', label: '16:00 - 17:00', start: 16 * 60, end: 17 * 60 },
  { key: '17', label: '17:00 - 18:00', start: 17 * 60, end: 18 * 60 },
  { key: '18', label: '18:00 - 19:00', start: 18 * 60, end: 19 * 60 },
  { key: '19', label: '19:00 - 20:00', start: 19 * 60, end: 20 * 60 },
];

const PROGRESS_TYPE_LABELS = {
  lesson: 'Lessons',
  activity: 'Activities',
  exercise: 'Exercises',
};
const UNIT_TYPE_OPTIONS = [
  { value: 'chapter', label: 'Chapter' },
  { value: 'exercise_series', label: 'Exercise Series' },
  { value: 'exam', label: 'Exam' },
  { value: 'exam_correction', label: 'Exam Correction' },
];

const CHIP_CLICK_SUPPRESS_MS = 250;
let _suppressChipClickUntil = 0;

function _startOfWeek(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return new Date();
  const day = (date.getDay() + 6) % 7; // Monday=0 ... Sunday=6
  const start = new Date(date.getFullYear(), date.getMonth(), date.getDate(), 0, 0, 0, 0);
  start.setDate(start.getDate() - day);
  return start;
}

function _addDays(value, days) {
  const date = new Date(value);
  date.setDate(date.getDate() + Number(days || 0));
  return date;
}

function _dateKey(value) {
  if (typeof value === 'string') {
    const match = value.trim().match(/^(\d{4}-\d{2}-\d{2})/);
    if (match) return match[1];
  }
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function _dateFromKey(value) {
  const key = _dateKey(value);
  if (!key) return null;
  const parsed = new Date(`${key}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function _academicYearStartKey(reference = null) {
  const refDate = _dateFromKey(reference) || new Date();
  const year = refDate.getMonth() >= 8 ? refDate.getFullYear() : refDate.getFullYear() - 1;
  return _dateKey(new Date(year, 8, 10));
}

function _isoWeekNumber(value) {
  const date = _startOfWeek(value instanceof Date ? value : new Date(value));
  const target = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = target.getUTCDay() || 7;
  target.setUTCDate(target.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
  return Math.ceil((((target - yearStart) / 86400000) + 1) / 7);
}

function _timeToMinutes(value) {
  if (!value) return null;
  const match = String(value).trim().match(/^(\d{2}):(\d{2})/);
  if (!match) return null;
  const h = Number(match[1]);
  const m = Number(match[2]);
  if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
  return (h * 60) + m;
}

function _minutesToPayloadTime(totalMinutes) {
  const safe = Math.max(0, Math.min(Number(totalMinutes || 0), (23 * 60) + 59));
  const hour = String(Math.floor(safe / 60)).padStart(2, '0');
  const minute = String(safe % 60).padStart(2, '0');
  return `${hour}:${minute}:00`;
}

function _sessionSlotKey(session) {
  const startMinutes = _timeToMinutes(session?.start_time);
  if (startMinutes == null) return null;
  const slot = TIME_SLOTS.find(row => startMinutes >= row.start && startMinutes < row.end);
  return slot ? slot.key : null;
}

function _sessionSortValue(session) {
  const minutes = _timeToMinutes(session?.start_time);
  if (minutes == null) return Number.POSITIVE_INFINITY;
  return minutes;
}

function _escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function _escapeHtmlAttr(value) {
  return _escapeHtml(value).replace(/`/g, '&#96;');
}

function _normalizeSectionPathKey(values) {
  return Array.isArray(values)
    ? values.map(value => String(value || '').trim().toLowerCase()).filter(Boolean).join(' > ')
    : '';
}

async function _loadCalendarAssistantArtifacts(classId, unitId, { force = false } = {}) {
  const cacheKey = `${Number(classId || 0)}:${Number(unitId || 0)}`;
  if (!force && _calendarAssistantArtifactCache.has(cacheKey)) {
    return _calendarAssistantArtifactCache.get(cacheKey) || [];
  }
  const rows = await api(`/workflow/classes/${classId}/units/${unitId}/assistant/artifacts`);
  const safeRows = Array.isArray(rows) ? rows : [];
  _calendarAssistantArtifactCache.set(cacheKey, safeRows);
  return safeRows;
}

function _filterCalendarAssistantArtifactsForSection(artifacts, sectionPlan, fallbackTitle = '') {
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

function _sortCalendarAssistantArtifactsForTeaching(items) {
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

function _filterCalendarAssistantArtifactsForPlannedTitles(artifacts, unitMap, plannedTitles) {
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
  return _sortCalendarAssistantArtifactsForTeaching(safeRows.filter(item => {
    const itemTitle = String(item?.section_title || '').trim().toLowerCase();
    if (itemTitle && titleKeys.has(itemTitle)) return true;
    const itemPathKey = _normalizeSectionPathKey(item?.section_path);
    return itemPathKey ? pathKeys.has(itemPathKey) : false;
  }));
}

function _setWorkflowViewIntent(intent) {
  try {
    sessionStorage.setItem(WORKFLOW_VIEW_INTENT_KEY, JSON.stringify({
      ...intent,
      created_at: Date.now(),
    }));
  } catch {
    // Non-fatal. Navigation still works without the shortcut intent.
  }
}

function _setCalendarViewIntent(intent) {
  try {
    sessionStorage.setItem(CALENDAR_VIEW_INTENT_KEY, JSON.stringify({
      ...intent,
      created_at: Date.now(),
    }));
  } catch {
    // Non-fatal. Calendar can still render without the restored context.
  }
}

function _consumeCalendarViewIntent() {
  try {
    const raw = sessionStorage.getItem(CALENDAR_VIEW_INTENT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const ageMs = Date.now() - Number(parsed?.created_at || 0);
    sessionStorage.removeItem(CALENDAR_VIEW_INTENT_KEY);
    if (!parsed || typeof parsed !== 'object' || ageMs > 10 * 60 * 1000) return null;
    return {
      session_id: Number(parsed.session_id || 0) || null,
      session_date: String(parsed.session_date || '').trim(),
      preview_hide_done: Boolean(parsed.preview_hide_done),
    };
  } catch {
    try { sessionStorage.removeItem(CALENDAR_VIEW_INTENT_KEY); } catch {}
    return null;
  }
}

function _buildCalendarWorkflowIntent(selectedEvent, action = '', extra = {}) {
  if (!selectedEvent || selectedEvent.unit_id == null) return null;
  const sessionLabel = selectedEvent.unit_session_number
    ? `Unit Session ${Number(selectedEvent.unit_session_number)}`
    : (String(selectedEvent.unit_title || 'Selected session').trim() || 'Selected session');
  return {
    action: String(action || '').trim().toLowerCase(),
    unit_id: Number(selectedEvent.unit_id),
    unit_session_number: Number(selectedEvent.unit_session_number || 0) || null,
    source: 'calendar',
    session_id: Number(selectedEvent.session_id || 0) || null,
    session_label: sessionLabel,
    session_date: String(selectedEvent.session_date || selectedEvent.date || '').trim(),
    section_title: String(extra?.section_title || '').trim(),
    section_path: Array.isArray(extra?.section_path)
      ? extra.section_path.map(value => String(value || '').trim()).filter(Boolean)
      : [],
    teacher_request: String(extra?.teacher_request || '').trim(),
    assistant_action: String(extra?.assistant_action || '').trim().toLowerCase(),
    preview_hide_done: Boolean(extra?.preview_hide_done),
  };
}

function _buildWorkflowSessionIntent(session, action = '') {
  if (!session || session.unit_id == null) return null;
  const sessionLabel = session.unit_session_number
    ? `Unit Session ${Number(session.unit_session_number)}`
    : (String(session.unit_title || 'Active session').trim() || 'Active session');
  return {
    action: String(action || '').trim().toLowerCase(),
    unit_id: Number(session.unit_id),
    unit_session_number: Number(session.unit_session_number || 0) || null,
    source: 'calendar',
    session_id: Number(session.id || session.session_id || 0) || null,
    session_label: sessionLabel,
    session_date: String(session.session_date || session.date || '').trim(),
    section_title: '',
    section_path: [],
    teacher_request: '',
    assistant_action: '',
    preview_hide_done: false,
  };
}

function _normalizeCalendarWriteupSourcePayload(payload) {
  if (!payload || typeof payload !== 'object') return null;
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
    requestedProvider: payload.requested_provider ? String(payload.requested_provider).trim() : '',
    providerUsed: payload.provider_used ? String(payload.provider_used).trim() : '',
    unitBrainUsed: Boolean(payload.unit_brain_used),
    matchedSections: Array.isArray(payload.matched_section_titles)
      ? payload.matched_section_titles.map(row => String(row || '').trim()).filter(Boolean)
      : [],
    matchedPaths: Array.isArray(payload.matched_section_paths)
      ? payload.matched_section_paths
        .map(path => Array.isArray(path) ? path.map(part => String(part || '').trim()).filter(Boolean).join(' > ') : '')
        .filter(Boolean)
      : [],
    matchedBlocks: Array.isArray(payload.matched_block_titles)
      ? payload.matched_block_titles.map(row => String(row || '').trim()).filter(Boolean)
      : [],
    matchedGuidance: Array.isArray(payload.matched_guidance_titles)
      ? payload.matched_guidance_titles.map(row => String(row || '').trim()).filter(Boolean)
      : [],
    importedAssistantArtifacts,
  };
}

function _renderCalendarWriteupSourcePayload(payload) {
  const normalized = _normalizeCalendarWriteupSourcePayload(payload);
  if (!normalized) return '';
  const rows = [];
  if (normalized.requestedProvider || normalized.providerUsed) {
    rows.push(`
      <div class="flex flex-wrap gap-2 text-[11px] text-slate-500">
        ${normalized.requestedProvider ? `<span>Requested: <strong class="text-slate-600">${_escapeHtml(normalized.requestedProvider)}</strong></span>` : ''}
        ${normalized.providerUsed ? `<span>Used: <strong class="text-slate-600">${_escapeHtml(normalized.providerUsed)}</strong></span>` : ''}
      </div>`);
  }
  rows.push(`<p class="text-[11px] text-slate-500">Unit brain matched: <strong class="text-slate-600">${normalized.unitBrainUsed ? 'Yes' : 'No'}</strong></p>`);
  if (normalized.matchedSections.length) {
    rows.push(`
      <div>
        <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Matched Sections</p>
        <ul class="mt-1 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
          ${normalized.matchedSections.map(row => `<li>${_escapeHtml(row)}</li>`).join('')}
        </ul>
      </div>`);
  }
  if (normalized.matchedPaths.length) {
    rows.push(`
      <div>
        <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Matched Paths</p>
        <ul class="mt-1 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
          ${normalized.matchedPaths.map(row => `<li>${_escapeHtml(row)}</li>`).join('')}
        </ul>
      </div>`);
  }
  if (normalized.matchedBlocks.length) {
    rows.push(`
      <div>
        <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Matched Blocks</p>
        <ul class="mt-1 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
          ${normalized.matchedBlocks.map(row => `<li>${_escapeHtml(row)}</li>`).join('')}
        </ul>
      </div>`);
  }
  if (normalized.matchedGuidance.length) {
    rows.push(`
      <div>
        <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Saved Guidance Used</p>
        <ul class="mt-1 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
          ${normalized.matchedGuidance.map(row => `<li>${_escapeHtml(row)}</li>`).join('')}
        </ul>
      </div>`);
  }
  if (normalized.importedAssistantArtifacts.length) {
    rows.push(`
      <div>
        <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Imported Saved Guidance</p>
        <ul class="mt-1 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
          ${normalized.importedAssistantArtifacts.map(item => `
            <li>
              ${_escapeHtml(item.sectionTitle || 'Saved guidance')}
              ${item.artifactKind ? ` • ${_escapeHtml(_assistantArtifactKindLabel(item.artifactKind))}` : ''}
              ${item.action ? ` • ${_escapeHtml(_assistantActionLabel(item.action))}` : ''}
            </li>
          `).join('')}
        </ul>
      </div>`);
  }
  return rows.length
    ? `<div class="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3 flex flex-col gap-2">${rows.join('')}</div>`
    : '';
}

function _renderCalendarImportedGuidanceSummary(payload) {
  const normalized = _normalizeCalendarWriteupSourcePayload(payload);
  const items = Array.isArray(normalized?.importedAssistantArtifacts) ? normalized.importedAssistantArtifacts : [];
  if (!items.length) return '';
  return `
    <div class="rounded-xl border border-emerald-200 bg-emerald-50 p-3 flex flex-col gap-2">
      <div class="flex items-center justify-between gap-2 flex-wrap">
        <p class="text-[12px] font-semibold text-emerald-800">Imported guidance in this write-up</p>
        <span class="badge badge-green">${items.length} imported</span>
      </div>
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

function _flattenChecklistNodes(nodes, depth = 0, output = []) {
  const rows = Array.isArray(nodes) ? nodes : [];
  rows.forEach(row => {
    if (!row || typeof row !== 'object') return;
    output.push({
      id: Number(row.id || 0),
      title: String(row.title || '').trim(),
      is_completed: Boolean(row.is_completed),
      item_kind: String(row.item_kind || '').trim() || null,
      depth: Number.isFinite(Number(row.depth)) ? Number(row.depth) : Number(depth || 0),
    });
    _flattenChecklistNodes(row.children || [], Number(depth || 0) + 1, output);
  });
  return output;
}

function _getCalendarUnitBlueprintState(unitId) {
  const uid = Number(unitId);
  if (!Number.isFinite(uid) || uid <= 0) {
    return { loading: false, loaded: false, error: null, item: null };
  }
  return _calendarUnitBlueprintCache.get(uid) || { loading: false, loaded: false, error: null, item: null };
}

function _setCalendarUnitBlueprintState(unitId, state) {
  const uid = Number(unitId);
  if (!Number.isFinite(uid) || uid <= 0) {
    return { loading: false, loaded: false, error: null, item: null };
  }
  const next = {
    loading: Boolean(state?.loading),
    loaded: Boolean(state?.loaded),
    error: state?.error ? String(state.error) : null,
    item: state?.item && typeof state.item === 'object' ? { ...state.item } : null,
  };
  _calendarUnitBlueprintCache.set(uid, next);
  return next;
}

async function _loadCalendarUnitBlueprint(classId, unitId, { force = false } = {}) {
  const uid = Number(unitId);
  if (!Number.isFinite(uid) || uid <= 0) {
    return { loading: false, loaded: false, error: null, item: null };
  }
  const existing = _getCalendarUnitBlueprintState(uid);
  if (existing.loading) return existing;
  if (!force && existing.loaded) return existing;

  _setCalendarUnitBlueprintState(uid, {
    loading: true,
    loaded: false,
    error: null,
    item: existing.item,
  });

  try {
    const row = await api(`/workflow/classes/${classId}/units/${uid}/blueprint`);
    return _setCalendarUnitBlueprintState(uid, {
      loading: false,
      loaded: true,
      error: null,
      item: row || null,
    });
  } catch (err) {
    return _setCalendarUnitBlueprintState(uid, {
      loading: false,
      loaded: true,
      error: String(err?.message || 'Failed to load unit AI details.'),
      item: existing.item,
    });
  }
}

function _collectSessionBlueprintNodes(nodes, sessionNumber) {
  const target = Number(sessionNumber || 0);
  if (!Number.isFinite(target) || target <= 0 || !Array.isArray(nodes)) return [];
  const walk = rows => rows.reduce((acc, rawNode) => {
    if (!rawNode || typeof rawNode !== 'object') return acc;
    const childMatches = walk(Array.isArray(rawNode.children) ? rawNode.children : []);
    const ownSession = Number(rawNode.session_number || 0);
    if (ownSession !== target && !childMatches.length) return acc;
    acc.push({
      id: Number(rawNode.id || 0) || null,
      title: String(rawNode.title || '').trim(),
      kind: String(rawNode.kind || '').trim(),
      session_number: ownSession > 0 ? ownSession : null,
      is_completed: Boolean(rawNode.is_completed || rawNode.done),
      children: childMatches,
    });
    return acc;
  }, []);
  return walk(nodes);
}

function _renderCalendarBlueprintTree(nodes, depth = 0, { resumeNodeId = null } = {}) {
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
            <span class="text-[13px] ${node?.is_completed ? 'text-slate-400 line-through' : 'text-slate-700'}">${_escapeHtml(node?.title || '')}</span>
            ${node?.kind ? `<span class="badge badge-gray">${_escapeHtml(String(node.kind))}</span>` : ''}
            ${node?.session_number ? `<span class="badge badge-blue">S${Number(node.session_number)}</span>` : ''}
            ${resumeNodeId != null && Number(node?.id || 0) === Number(resumeNodeId) ? `<span class="badge badge-amber">Resume here</span>` : node?.is_completed ? `<span class="badge badge-green">Done</span>` : ''}
          </div>
          ${_renderCalendarBlueprintTree(node?.children || [], depth + 1, { resumeNodeId })}
        </li>
      `).join('')}
    </ul>`;
}

function _flattenCalendarBlueprintTitles(nodes, output = []) {
  const rows = Array.isArray(nodes) ? nodes : [];
  rows.forEach(node => {
    if (!node || typeof node !== 'object') return;
    const title = String(node.title || '').trim();
    if (title) output.push(title);
    _flattenCalendarBlueprintTitles(node.children || [], output);
  });
  return output;
}

function _flattenCalendarBlueprintNodes(nodes, output = []) {
  const rows = Array.isArray(nodes) ? nodes : [];
  rows.forEach(node => {
    if (!node || typeof node !== 'object') return;
    output.push(node);
    _flattenCalendarBlueprintNodes(node.children || [], output);
  });
  return output;
}

function _buildCalendarPlannedSessionSummary(nodes) {
  const flat = _flattenCalendarBlueprintNodes(nodes, []);
  if (!flat.length) return [];
  const done = flat.filter(node => Boolean(node?.is_completed)).length;
  const remaining = Math.max(0, flat.length - done);
  const coveragePct = Math.round((done / flat.length) * 100);
  const kindCounts = flat.reduce((acc, node) => {
    const kind = String(node?.kind || '').trim().toLowerCase();
    if (!kind || kind === 'other') return acc;
    acc[kind] = Number(acc[kind] || 0) + 1;
    return acc;
  }, {});
  return [
    `${flat.length} planned items`,
    `${done}/${flat.length} done`,
    `${remaining} remaining`,
    `${coveragePct}% covered`,
    kindCounts.activity ? `${kindCounts.activity} activities` : '',
    kindCounts.example ? `${kindCounts.example} examples` : '',
    kindCounts.exercise ? `${kindCounts.exercise} exercises` : '',
    kindCounts.definition ? `${kindCounts.definition} definitions` : '',
    kindCounts.property ? `${kindCounts.property} properties` : '',
  ].filter(Boolean);
}

function _filterCalendarBlueprintTree(nodes, { hideDone = false } = {}) {
  const rows = Array.isArray(nodes) ? nodes : [];
  if (!hideDone) return rows;
  return rows.reduce((acc, node) => {
    if (!node || typeof node !== 'object') return acc;
    const filteredChildren = _filterCalendarBlueprintTree(node.children || [], { hideDone });
    const isDone = Boolean(node.is_completed);
    if (isDone && !filteredChildren.length) return acc;
    acc.push({
      ...node,
      children: filteredChildren,
    });
    return acc;
  }, []);
}

function _renderCalendarSectionPlans(sectionPlans, plannedTitles) {
  const plans = Array.isArray(sectionPlans) ? sectionPlans.filter(Boolean) : [];
  const titleKeys = new Set((Array.isArray(plannedTitles) ? plannedTitles : []).map(value => String(value || '').trim().toLowerCase()).filter(Boolean));
  const matched = plans.filter(plan => {
    const sectionTitle = String(plan?.section_title || '').trim().toLowerCase();
    if (sectionTitle && titleKeys.has(sectionTitle)) return true;
    const delivery = Array.isArray(plan?.delivery_sequence) ? plan.delivery_sequence : [];
    return delivery.some(value => titleKeys.has(String(value || '').trim().toLowerCase()));
  }).slice(0, 4);
  if (!matched.length) {
    return '<p class="text-[12px] text-slate-500 mt-2">No matching section plan found for this unit session yet.</p>';
  }
  return matched.map(plan => `
    <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">
      <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(plan?.section_title || 'Section'))}</p>
      ${Array.isArray(plan?.delivery_sequence) && plan.delivery_sequence.length ? `
        <ol class="mt-2 list-decimal pl-4 text-[12px] text-slate-600 leading-relaxed">
          ${plan.delivery_sequence.map(value => `<li>${_escapeHtml(String(value || ''))}</li>`).join('')}
        </ol>` : ''}
    </div>
  `).join('');
}

function _findCalendarSectionPlanForTitle(sectionPlans, title) {
  const target = String(title || '').trim().toLowerCase();
  if (!target) return null;
  const plans = Array.isArray(sectionPlans) ? sectionPlans.filter(Boolean) : [];
  return plans.find(plan => {
    const sectionTitle = String(plan?.section_title || '').trim().toLowerCase();
    if (sectionTitle && sectionTitle === target) return true;
    const delivery = Array.isArray(plan?.delivery_sequence) ? plan.delivery_sequence : [];
    return delivery.some(value => String(value || '').trim().toLowerCase() === target);
  }) || null;
}

function _findCalendarTeacherPlaybookEntry(unitMap, sectionPlan, fallbackTitle = '') {
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

function _buildCalendarAssistantPrefill(entry, sectionPlan, fallbackTitle = '', preferredAction = '') {
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
    section_title: sectionTitle,
    section_path: sectionPath,
    teacher_request: teacherRequest,
    assistant_action: action || 'explain_section',
  };
}

function _renderCalendarNextFocusActions(sectionPlan, playbookEntry, fallbackTitle = '', { classId = null, unitId = null } = {}) {
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
            class="btn btn-secondary btn-sm btn-calendar-next-focus-action"
            data-assistant-action="${_escapeHtmlAttr(action)}"
          >${_escapeHtml(_teacherActionLabel(action))}</button>`).join('')}
      </div>
      ${classId && unitId ? `<div class="mt-2" data-calendar-next-focus-guidance data-class-id="${_escapeHtmlAttr(String(classId))}" data-unit-id="${_escapeHtmlAttr(String(unitId))}"></div>` : ''}
    </div>
  `;
}

function _teacherActionLabel(action) {
  const normalized = String(action || '').trim().toLowerCase();
  const labels = {
    explain_section: 'Explain section',
    generate_teacher_notes: 'Teacher notes',
    generate_slides: 'Slides',
    create_warmup_variant: 'Warm-up variant',
    simplify_explanation: 'Simplify explanation',
    generate_guided_examples: 'Guided examples',
    generate_easier_practice: 'Easier practice',
    generate_harder_practice: 'Harder practice',
    generate_quick_quiz: 'Quick quiz',
    generate_remediation: 'Remediation',
  };
  return labels[normalized] || normalized.replace(/_/g, ' ');
}

function _renderCalendarTeacherPrep(unitMap, plannedTitles) {
  const playbook = Array.isArray(unitMap?.teacher_playbook) ? unitMap.teacher_playbook.filter(Boolean) : [];
  const materialStudio = unitMap?.material_studio && typeof unitMap.material_studio === 'object' ? unitMap.material_studio : {};
  const titleKeys = new Set((Array.isArray(plannedTitles) ? plannedTitles : []).map(value => String(value || '').trim().toLowerCase()).filter(Boolean));
  const matchedPlaybook = playbook.filter(entry => {
    const sectionTitle = String(entry?.section_title || '').trim().toLowerCase();
    if (sectionTitle && titleKeys.has(sectionTitle)) return true;
    const sectionPath = Array.isArray(entry?.section_path) ? entry.section_path : [];
    return sectionPath.some(value => titleKeys.has(String(value || '').trim().toLowerCase()));
  }).slice(0, 4);
  const unitArtifacts = Array.isArray(materialStudio?.unit_artifacts) ? materialStudio.unit_artifacts.filter(Boolean).slice(0, 4) : [];

  if (!matchedPlaybook.length && !unitArtifacts.length) {
    return '<p class="text-[12px] text-slate-500 mt-2">No teacher prep suggestions saved for this unit yet.</p>';
  }

  return `
    <div class="mt-2 flex flex-col gap-3">
      ${matchedPlaybook.map(entry => `
        <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(entry?.section_title || 'Section'))}</p>
          ${Array.isArray(entry?.available_actions) && entry.available_actions.length ? `
            <div class="mt-2 flex flex-wrap gap-1.5">
              ${entry.available_actions.map(action => `<span class="badge badge-gray">${_escapeHtml(_teacherActionLabel(action))}</span>`).join('')}
            </div>` : ''}
          ${Array.isArray(entry?.suggested_requests) && entry.suggested_requests.length ? `
            <div class="mt-3 flex flex-wrap gap-2">
              ${entry.suggested_requests.slice(0, 4).map(row => `
                <button
                  class="btn btn-ghost btn-sm btn-calendar-prep-request"
                  data-section-title="${_escapeHtmlAttr(String(entry?.section_title || ''))}"
                  data-section-path="${_escapeHtmlAttr(JSON.stringify(Array.isArray(entry?.section_path) ? entry.section_path : []))}"
                  data-teacher-request="${_escapeHtmlAttr(String(row || ''))}"
                  data-assistant-action="${_escapeHtmlAttr(String(Array.isArray(entry?.available_actions) && entry.available_actions.length ? entry.available_actions[0] : 'explain_section'))}"
                >${_escapeHtml(String(row || ''))}</button>`).join('')}
            </div>` : ''}
        </div>
      `).join('')}
      ${unitArtifacts.length ? `
        <div class="rounded-xl border border-slate-200 bg-white p-3">
          <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Helpful unit materials</p>
          <div class="flex flex-wrap gap-2">
            ${unitArtifacts.map(artifact => `<span class="badge badge-blue">${_escapeHtml(String(artifact?.title || artifact?.id || 'Material'))}</span>`).join('')}
          </div>
        </div>` : ''}
    </div>`;
}

function _listToMultiline(values) {
  return Array.isArray(values) ? values.map(value => String(value || '').trim()).filter(Boolean).join('\n') : '';
}

function _multilineToList(value) {
  return String(value || '')
    .split(/\r?\n+/)
    .map(row => row.trim())
    .filter(Boolean);
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

function _summarizeCalendarRemainingGuidanceKinds(items) {
  const counts = new Map();
  (Array.isArray(items) ? items : []).forEach(item => {
    const kind = String(item?.artifact_kind || 'teacher_notes').trim().toLowerCase() || 'teacher_notes';
    counts.set(kind, (counts.get(kind) || 0) + 1);
  });
  return Array.from(counts.entries());
}

function _renderCalendarRemainingGuidanceSummary(items) {
  const normalized = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!normalized.length) return '';
  const kindSummary = _summarizeCalendarRemainingGuidanceKinds(normalized);
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

function _renderCalendarWriteupNextStep(writeup, { isFuture = false, hasUnit = false, remainingGuidanceCount = 0, bestRemainingGuidanceTitle = '', quickGuidanceItems = [] } = {}) {
  if (isFuture) {
    return `
      <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
        <p class="text-[12px] font-semibold text-slate-600">Recommended next step</p>
        <p class="text-[12px] text-slate-500 mt-1">Review the planned flow and prep suggestions now. The textbook write-up becomes available after the session happens.</p>
        ${hasUnit ? `
          <div class="mt-3 flex gap-2 flex-wrap">
            <button id="btn-calendar-next-open-workflow" class="btn btn-primary btn-sm">Open workflow</button>
            <button id="btn-calendar-next-assistant" class="btn btn-secondary btn-sm">Ask This Unit</button>
            <button id="btn-calendar-next-materials" class="btn btn-secondary btn-sm">Material Studio</button>
          </div>` : ''}
      </div>`;
  }
  if (!hasUnit) {
    return `
      <div class="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-3 py-2">
        <p class="text-[12px] font-semibold text-slate-600">Recommended next step</p>
        <p class="text-[12px] text-slate-500 mt-1">This session is outside the workflow unit system, so only attendance and notes are managed here.</p>
      </div>`;
  }
  if (!writeup) {
    return `
      <div class="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-3 py-2">
        <p class="text-[12px] font-semibold text-slate-600">Recommended next step</p>
        <p class="text-[12px] text-slate-500 mt-1">
          ${remainingGuidanceCount > 0
            ? `You already have ${remainingGuidanceCount} matching saved guidance item${remainingGuidanceCount === 1 ? '' : 's'} for this session. Import one first, or generate the write-up after confirming what was really covered in class.`
            : 'Generate the write-up after confirming what was really covered in class.'}
        </p>
        ${remainingGuidanceCount > 0 ? _renderCalendarRemainingGuidanceSummary(quickGuidanceItems) : ''}
        <div class="mt-3 flex gap-2 flex-wrap">
          ${remainingGuidanceCount === 1 ? '<button id="btn-calendar-next-import-best" class="btn btn-primary btn-sm">Import Best Match</button>' : ''}
          ${remainingGuidanceCount > 1 ? `<button id="btn-calendar-next-import-all" class="btn btn-primary btn-sm">Import All Guidance (${remainingGuidanceCount})</button>` : ''}
          <button id="btn-calendar-next-generate" class="btn btn-primary btn-sm">Generate now</button>
          <button id="btn-calendar-next-guidance" class="btn btn-secondary btn-sm">${remainingGuidanceCount === 1 && bestRemainingGuidanceTitle ? 'Choose Other Guidance' : 'Use Saved Guidance'}</button>
        </div>
        ${remainingGuidanceCount > 1 ? _renderCalendarGuidanceKindImportButtons(quickGuidanceItems, 'calendar-next-guidance-kind') : ''}
        ${remainingGuidanceCount > 1 ? _renderCalendarGuidanceQuickPickButtons(quickGuidanceItems, 'calendar-next-guidance') : ''}
      </div>`;
  }
  if (writeup.approved === false) {
    return `
      <div class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
        <p class="text-[12px] font-semibold text-amber-800">Recommended next step</p>
        <p class="text-[12px] text-amber-700 mt-1">
          ${remainingGuidanceCount > 0
            ? 'Review this draft, import any remaining saved guidance you still want, and approve it once it matches the actual lesson.'
            : 'Review this draft, edit it if needed, and approve it once it matches the actual lesson.'}
        </p>
        ${remainingGuidanceCount > 0 ? _renderCalendarRemainingGuidanceSummary(quickGuidanceItems) : ''}
        <div class="mt-3 flex gap-2 flex-wrap">
          <button id="btn-calendar-next-edit" class="btn btn-primary btn-sm">Edit draft</button>
          ${remainingGuidanceCount === 1 ? '<button id="btn-calendar-next-import-best" class="btn btn-secondary btn-sm">Import Best Match</button>' : ''}
          ${remainingGuidanceCount > 1 ? `<button id="btn-calendar-next-import-all" class="btn btn-secondary btn-sm">Import All Guidance (${remainingGuidanceCount})</button>` : ''}
          ${remainingGuidanceCount > 0 ? '<button id="btn-calendar-next-guidance" class="btn btn-secondary btn-sm">Use Saved Guidance</button>' : ''}
          <button id="btn-calendar-next-approve" class="btn btn-secondary btn-sm">Approve now</button>
        </div>
        ${remainingGuidanceCount > 1 ? _renderCalendarGuidanceKindImportButtons(quickGuidanceItems, 'calendar-draft-guidance-kind') : ''}
        ${remainingGuidanceCount > 1 ? _renderCalendarGuidanceQuickPickButtons(quickGuidanceItems, 'calendar-draft-guidance') : ''}
      </div>`;
  }
  return `
    <div class="rounded-xl border border-green-200 bg-green-50 px-3 py-2">
      <p class="text-[12px] font-semibold text-green-800">Recommended next step</p>
      <p class="text-[12px] text-green-700 mt-1">This write-up is approved. You can copy it, download it, or reopen it as a draft if you need changes.</p>
      <div class="mt-3 flex gap-2 flex-wrap">
        <button id="btn-calendar-next-copy" class="btn btn-primary btn-sm">Copy</button>
        <button id="btn-calendar-next-download" class="btn btn-secondary btn-sm">Download</button>
      </div>
    </div>`;
}

function _assistantArtifactKindLabel(kind) {
  const normalized = String(kind || '').trim().toLowerCase();
  const labels = {
    teacher_notes: 'Teacher notes',
    guided_practice: 'Guided practice',
    quick_quiz_draft: 'Quick quiz draft',
  };
  return labels[normalized] || normalized.replace(/_/g, ' ') || 'Saved guidance';
}

function _assistantActionLabel(action) {
  return _teacherActionLabel(action);
}

function _getCalendarImportedAssistantArtifactIds(writeup) {
  const meta = _normalizeCalendarWriteupSourcePayload(writeup?.source_payload);
  return new Set((meta?.importedAssistantArtifacts || []).map(item => Number(item?.artifactId || 0)).filter(Boolean));
}

function _calendarArtifactDownloadFilename(item, fallbackTitle = '') {
  const base = String(item?.title || fallbackTitle || 'saved-guidance')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'saved-guidance';
  return `${base}.md`;
}

function _renderCalendarSavedGuidancePreviewRows(items, fallbackTitle = '') {
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
              <button class="btn btn-ghost btn-sm btn-calendar-preview-guidance-copy" data-artifact-id="${_escapeHtmlAttr(String(item?.id || ''))}">Copy</button>
              <button class="btn btn-secondary btn-sm btn-calendar-preview-guidance-download" data-artifact-id="${_escapeHtmlAttr(String(item?.id || ''))}">Download</button>
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

function _renderCalendarSessionMatchedGuidance(items, { canImport = false, importedIds = new Set(), hideImported = false } = {}) {
  const source = Array.isArray(items) ? items : [];
  const filtered = hideImported ? source.filter(item => !importedIds.has(Number(item?.id || 0))) : source;
  const visible = filtered.slice(0, 4);
  if (!visible.length) {
    if (hideImported && source.length) {
      return '<p class="text-[12px] text-slate-500">All matching saved guidance has already been imported. Use <span class="font-semibold">Show Imported</span> if you want to review it again.</p>';
    }
    return '<p class="text-[12px] text-slate-500">No saved guidance matches this session route yet. Save a good result from Ask This Unit to reuse it here.</p>';
  }
  return `
    <div class="flex flex-col gap-2">
      ${visible.map(item => {
        const artifactId = Number(item?.id || 0);
        const imported = importedIds.has(artifactId);
        return `
        <div class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
          <div class="flex items-center justify-between gap-3 flex-wrap">
            <div class="flex items-center gap-2 flex-wrap">
              <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(String(item?.title || 'Saved guidance'))}</p>
              <span class="badge badge-blue">${_escapeHtml(_assistantArtifactKindLabel(item?.artifact_kind))}</span>
              ${item?.action ? `<span class="badge badge-gray">${_escapeHtml(_assistantActionLabel(item.action))}</span>` : ''}
              ${imported ? '<span class="badge badge-green">Imported</span>' : ''}
            </div>
            <div class="flex items-center gap-2 flex-wrap">
              ${canImport ? `<button class="btn btn-primary btn-sm btn-calendar-session-guidance-import" data-artifact-id="${_escapeHtmlAttr(String(item?.id || ''))}" ${imported ? 'disabled' : ''}>${imported ? 'Already Imported' : 'Use in Write-Up'}</button>` : ''}
              <button class="btn btn-ghost btn-sm btn-calendar-session-guidance-copy" data-artifact-id="${_escapeHtmlAttr(String(item?.id || ''))}">Copy</button>
              <button class="btn btn-secondary btn-sm btn-calendar-session-guidance-download" data-artifact-id="${_escapeHtmlAttr(String(item?.id || ''))}">Download</button>
            </div>
          </div>
          ${item?.content_markdown ? `<p class="text-[12px] text-slate-600 leading-6 mt-2">${_escapeHtml(String(item.content_markdown).split('\n').slice(0, 3).join(' '))}</p>` : ''}
        </div>
      `;}).join('')}
      ${filtered.length > visible.length
        ? `<p class="text-[11px] text-slate-500">Showing ${visible.length} of ${filtered.length} matching saved guidance items${hideImported ? ' still available to import' : ''}.</p>`
        : ''}
    </div>
  `;
}

function _renderCalendarSessionGuidanceSummary(totalCount, importedCount, hideImported = false) {
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

function _renderCalendarGuidanceQuickPickButtons(items, prefix) {
  const visible = Array.isArray(items) ? items.slice(0, 2) : [];
  if (!visible.length) return '';
  return `
    <div class="mt-3 flex flex-wrap gap-2">
      ${visible.map(item => `
        <button
          id="${_escapeHtmlAttr(`${prefix}-${Number(item?.id || 0)}`)}"
          class="btn btn-ghost btn-sm btn-calendar-guidance-quick-pick"
          data-artifact-id="${_escapeHtmlAttr(String(item?.id || ''))}"
        >${_escapeHtml(_assistantArtifactKindLabel(item?.artifact_kind))}: ${_escapeHtml(String(item?.title || 'Saved guidance'))}</button>
      `).join('')}
    </div>
  `;
}

function _renderCalendarGuidanceKindImportButtons(items, prefix) {
  const summary = _summarizeCalendarRemainingGuidanceKinds(items);
  if (summary.length <= 1) return '';
  return `
    <div class="mt-2 flex flex-wrap gap-2">
      ${summary.map(([kind, count]) => `
        <button
          id="${_escapeHtmlAttr(`${prefix}-${kind}`)}"
          class="btn btn-ghost btn-sm btn-calendar-guidance-kind-import"
          data-artifact-kind="${_escapeHtmlAttr(kind)}"
        >Import ${_escapeHtml(_assistantArtifactKindLabel(kind))} (${count})</button>
      `).join('')}
    </div>
  `;
}

async function _hydrateCalendarSavedGuidance(container, { classId, unitId, sectionPlan, fallbackTitle = '' } = {}) {
  if (!container || !classId || !unitId) return;
  container.innerHTML = '<p class="text-[12px] text-amber-700 mt-3">Loading saved guidance…</p>';
  try {
    const artifacts = await _loadCalendarAssistantArtifacts(classId, unitId);
    const matches = _filterCalendarAssistantArtifactsForSection(artifacts, sectionPlan, fallbackTitle);
    container.innerHTML = _renderCalendarSavedGuidancePreviewRows(matches, fallbackTitle);
    container.querySelectorAll('.btn-calendar-preview-guidance-copy').forEach(button => {
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
    container.querySelectorAll('.btn-calendar-preview-guidance-download').forEach(button => {
      button.addEventListener('click', () => {
        const artifactId = Number(button.dataset.artifactId || 0);
        const item = matches.find(row => Number(row?.id || 0) === artifactId);
        if (!item?.content_markdown) return;
        _downloadTextContent(String(item.content_markdown), _calendarArtifactDownloadFilename(item, fallbackTitle));
      });
    });
  } catch (err) {
    container.innerHTML = `<p class="text-[12px] text-red-600 mt-3">${_escapeHtml(String(err?.message || 'Failed to load saved guidance.'))}</p>`;
  }
}

function _openCalendarSessionWriteupModal(writeup) {
  return new Promise(resolve => {
    const item = writeup && typeof writeup === 'object' ? writeup : {};
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-3xl w-[96vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <div class="flex items-start justify-between gap-4">
            <div>
              <h2 class="text-[17px] font-bold text-slate-800">Edit Session Write-Up</h2>
              <p class="text-[12px] text-slate-500 mt-1">Refine the generated textbook content before you rely on it.</p>
            </div>
            <button id="calendar-writeup-close-top" class="btn btn-ghost btn-sm">Close</button>
          </div>
        </div>
        <div class="px-6 py-4 max-h-[72vh] overflow-y-auto flex flex-col gap-4">
          <div class="flex flex-col gap-1">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Title</label>
            <input id="calendar-writeup-title" type="text" value="${_escapeHtml(item.title || '')}" />
          </div>
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Learning Focus</label>
              <textarea id="calendar-writeup-focus" rows="8">${_escapeHtml(_listToMultiline(item.learning_focus))}</textarea>
              <p class="text-[11px] text-slate-500">One line per point.</p>
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Practice Items</label>
              <textarea id="calendar-writeup-practice" rows="8">${_escapeHtml(_listToMultiline(item.practice_items))}</textarea>
              <p class="text-[11px] text-slate-500">One line per exercise or reinforcement task.</p>
            </div>
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Teaching Content</label>
            <textarea id="calendar-writeup-content" rows="10">${_escapeHtml(_listToMultiline(item.teaching_content))}</textarea>
            <p class="text-[11px] text-slate-500">One paragraph per line.</p>
          </div>
          <label class="flex items-center gap-2 text-[13px] text-slate-700">
            <input id="calendar-writeup-approved" type="checkbox" ${item.approved === false ? '' : 'checked'} />
            Mark this write-up as approved
          </label>
        </div>
        <div class="px-6 py-4 border-t border-slate-100 flex items-center justify-end gap-2">
          <button id="calendar-writeup-cancel" class="btn btn-ghost">Cancel</button>
          <button id="calendar-writeup-save" class="btn btn-primary">Save Write-Up</button>
        </div>
      </div>
    `;
    const cleanup = result => {
      overlay.remove();
      resolve(result ?? null);
    };
    overlay.querySelector('#calendar-writeup-close-top')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#calendar-writeup-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#calendar-writeup-save')?.addEventListener('click', () => {
      cleanup({
        title: overlay.querySelector('#calendar-writeup-title')?.value?.trim() || '',
        learning_focus: _multilineToList(overlay.querySelector('#calendar-writeup-focus')?.value || ''),
        practice_items: _multilineToList(overlay.querySelector('#calendar-writeup-practice')?.value || ''),
        teaching_content: _multilineToList(overlay.querySelector('#calendar-writeup-content')?.value || ''),
        approved: Boolean(overlay.querySelector('#calendar-writeup-approved')?.checked),
      });
    });
    overlay.addEventListener('click', event => {
      if (event.target === overlay) cleanup(null);
    });
    document.body.appendChild(overlay);
    overlay.querySelector('#calendar-writeup-title')?.focus();
  });
}

async function _openCalendarSessionGuidanceImportModal({ classId, unitId }) {
  return new Promise(async resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-3xl w-[96vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <div class="flex items-start justify-between gap-4">
            <div>
              <h2 class="text-[17px] font-bold text-slate-800">Use Saved Guidance</h2>
              <p class="text-[12px] text-slate-500 mt-1">Import saved NotebookLM guidance into this session write-up.</p>
            </div>
            <button id="calendar-guidance-close-top" class="btn btn-ghost btn-sm">Close</button>
          </div>
        </div>
        <div class="px-6 py-4 max-h-[72vh] overflow-y-auto">
          <div id="calendar-guidance-list" class="space-y-3">
            <p class="text-[12px] text-slate-500">Loading saved guidance...</p>
          </div>
        </div>
        <div class="px-6 py-4 border-t border-slate-100 flex justify-end">
          <button id="calendar-guidance-close" class="btn btn-ghost">Close</button>
        </div>
      </div>
    `;
    const listNode = overlay.querySelector('#calendar-guidance-list');
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
            <button class="btn btn-primary btn-sm btn-calendar-guidance-import" data-artifact-id="${_escapeHtml(String(item?.id || ''))}">
              Import
            </button>
          </div>
          ${item?.section_title ? `<p class="text-[11px] text-slate-500 mt-2"><span class="font-semibold">Section:</span> ${_escapeHtml(String(item.section_title || ''))}</p>` : ''}
          ${Array.isArray(item?.section_path) && item.section_path.length ? `<p class="text-[11px] text-slate-500 mt-1"><span class="font-semibold">Path:</span> ${_escapeHtml(item.section_path.join(' -> '))}</p>` : ''}
          ${item?.content_markdown ? `<p class="text-[12px] text-slate-700 leading-6 mt-3">${_escapeHtml(String(item.content_markdown).split('\n').slice(0, 4).join(' '))}</p>` : ''}
        </div>
      `).join('');
      listNode.querySelectorAll('.btn-calendar-guidance-import').forEach(button => {
        button.addEventListener('click', () => cleanup(Number(button.dataset.artifactId || 0) || null));
      });
    };
    overlay.addEventListener('click', event => {
      if (event.target === overlay) cleanup(null);
    });
    overlay.querySelector('#calendar-guidance-close-top')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#calendar-guidance-close')?.addEventListener('click', () => cleanup(null));
    document.body.appendChild(overlay);
    try {
      const rows = await api(`/workflow/classes/${classId}/units/${Number(unitId)}/assistant/artifacts`);
      renderRows(rows);
    } catch (err) {
      listNode.innerHTML = `<p class="text-[12px] text-red-600">${_escapeHtml(String(err?.message || 'Failed to load saved guidance.'))}</p>`;
    }
  });
}

function _coerceCalendarEvent(row) {
  const sessionId = Number(row?.session_id ?? row?.id ?? 0);
  if (!sessionId) return null;
  const rawUnitSessionNumber = Number(row?.unit_session_number);
  const unitSessionNumber = Number.isFinite(rawUnitSessionNumber) && rawUnitSessionNumber > 0
    ? Math.floor(rawUnitSessionNumber)
    : null;
  return {
    session_id: sessionId,
    class_id: Number(row?.class_id || 0),
    unit_id: row?.unit_id == null ? null : Number(row.unit_id),
    unit_session_number: unitSessionNumber,
    unit_title: row?.unit_title ? String(row.unit_title) : null,
    unit_type: row?.unit_type ?? null,
    session_date: _dateKey(row?.session_date || row?.date || ''),
    start_time: row?.start_time || null,
    end_time: row?.end_time || null,
    absent_count: Number(row?.absent_count || 0),
    absent_student_ids: Array.isArray(row?.absent_student_ids) ? row.absent_student_ids.map(Number).filter(Number.isFinite) : [],
    checked_items_count: Number(row?.checked_items_count || 0),
    checked_items: Array.isArray(row?.checked_items) ? row.checked_items.map(v => String(v || '').trim()).filter(Boolean) : [],
    note: row?.note == null ? null : String(row.note),
  };
}

function _mergeCalendarData(workflowRows, sessionRows) {
  const mergedById = new Map();

  (sessionRows || []).forEach(row => {
    const normalized = _coerceCalendarEvent(row);
    if (!normalized) return;
    if (!normalized.unit_title) normalized.unit_title = 'Session';
    mergedById.set(normalized.session_id, normalized);
  });

  (workflowRows || []).forEach(row => {
    const normalized = _coerceCalendarEvent(row);
    if (!normalized) return;
    const existing = mergedById.get(normalized.session_id) || null;
    mergedById.set(normalized.session_id, existing ? { ...existing, ...normalized } : normalized);
  });

  return Array.from(mergedById.values()).sort((a, b) => {
    const dateDiff = String(b.session_date || '').localeCompare(String(a.session_date || ''));
    if (dateDiff !== 0) return dateDiff;
    const timeDiff = _sessionSortValue(a) - _sessionSortValue(b);
    if (timeDiff !== 0) return timeDiff;
    return Number(a.session_id) - Number(b.session_id);
  });
}

function _buildWeekDays(weekStart) {
  return Array.from({ length: 7 }, (_, index) => {
    const date = _addDays(weekStart, index);
    const key = _dateKey(date);
    return {
      date,
      key,
      label: WEEKDAY_LABELS[index],
      shortDate: date.toLocaleDateString('fr-MA', { day: '2-digit', month: '2-digit' }),
    };
  });
}

function _yearsForWeek(weekStart) {
  const years = new Set();
  for (let index = 0; index < 7; index += 1) {
    years.add(_addDays(weekStart, index).getFullYear());
  }
  return Array.from(years.values()).filter(Number.isFinite);
}

function _normalizeHolidayRow(row) {
  const dateKey = _dateKey(row?.holiday_date || row?.date || null);
  if (!dateKey) return null;
  return {
    id: Number(row?.id || 0) || null,
    holiday_date: dateKey,
    name: String(row?.name || 'Holiday').trim() || 'Holiday',
    is_blocked: Boolean(row?.is_blocked),
    country_code: String(row?.country_code || 'MA').toUpperCase(),
  };
}

function _buildHolidayMap(rows) {
  const map = new Map();
  (rows || []).forEach(raw => {
    const row = _normalizeHolidayRow(raw);
    if (!row) return;
    const existing = map.get(row.holiday_date);
    if (!existing) {
      map.set(row.holiday_date, row);
      return;
    }
    if (!existing.is_blocked && row.is_blocked) {
      map.set(row.holiday_date, row);
    }
  });
  return map;
}

async function _loadWeekHolidays(weekStart) {
  const years = _yearsForWeek(weekStart);
  if (!years.length) {
    _holidayByDate = new Map();
    return _holidayByDate;
  }
  const responses = await Promise.all(
    years.map(year => api(`/workflow/holidays?year=${year}&country_code=MA`).catch(() => []))
  );
  const allRows = responses.flatMap(rows => (Array.isArray(rows) ? rows : []));
  _holidayByDate = _buildHolidayMap(allRows);
  return _holidayByDate;
}

function _normalizeTimetableRule(row) {
  const id = Number(row?.id || 0);
  const classId = Number(row?.class_id || 0);
  const weekday = Number(row?.weekday || 0);
  const startTime = String(row?.start_time || '').trim();
  const endTime = String(row?.end_time || '').trim();
  const effectiveFrom = _dateKey(row?.effective_from || null);
  const effectiveTo = _dateKey(row?.effective_to || null);
  if (!id || !classId || !weekday || !startTime || !effectiveFrom) return null;
  return {
    id,
    class_id: classId,
    weekday,
    start_time: startTime,
    end_time: endTime || null,
    subject: String(row?.subject || '').trim() || null,
    room: String(row?.room || '').trim() || null,
    group: String(row?.group || '').trim() || null,
    effective_from: effectiveFrom,
    effective_to: effectiveTo || null,
  };
}

function _getClassTimetableRules(classId) {
  const key = Number(classId || 0);
  if (!key) return [];
  const rows = _timetableRulesByClass.get(key);
  return Array.isArray(rows) ? rows : [];
}

function _resolveCalendarExportRange(classId, fallbackFromKey, fallbackToKey) {
  const rules = _getClassTimetableRules(classId);
  const ruleStartKeys = rules
    .map(rule => _dateKey(rule?.effective_from || null))
    .filter(Boolean)
    .sort();

  const events = Array.isArray(getCalendar()) ? getCalendar() : [];
  const eventDateKeys = events
    .map(row => _dateKey(row?.session_date || row?.date || null))
    .filter(Boolean)
    .sort();

  const fromKey = ruleStartKeys[0] || eventDateKeys[0] || _dateKey(fallbackFromKey) || _academicYearStartKey();
  const toKey = eventDateKeys[eventDateKeys.length - 1] || _dateKey(fallbackToKey) || _dateKey(new Date());
  return { fromKey, toKey };
}

function _setClassTimetableRules(classId, rows) {
  const key = Number(classId || 0);
  if (!key) return [];
  const normalized = (Array.isArray(rows) ? rows : [])
    .map(_normalizeTimetableRule)
    .filter(Boolean)
    .sort((a, b) => {
      const weekdayDiff = Number(a.weekday || 0) - Number(b.weekday || 0);
      if (weekdayDiff !== 0) return weekdayDiff;
      const timeDiff = (_timeToMinutes(a.start_time) ?? 0) - (_timeToMinutes(b.start_time) ?? 0);
      if (timeDiff !== 0) return timeDiff;
      return Number(a.id || 0) - Number(b.id || 0);
    });
  _timetableRulesByClass.set(key, normalized);
  return normalized;
}

async function _loadClassTimetableRules(classId) {
  const key = Number(classId || 0);
  if (!key) return [];
  try {
    const rows = await api(`/workflow/classes/${key}/timetable-rules`);
    return _setClassTimetableRules(key, rows);
  } catch {
    return _setClassTimetableRules(key, []);
  }
}

function _normalizeTimetableExceptionRow(row) {
  const id = Number(row?.id || 0);
  const classId = Number(row?.class_id || 0);
  const ruleId = Number(row?.rule_id || 0);
  const exceptionDate = _dateKey(row?.exception_date || null);
  const type = String(row?.exception_type || '').trim().toLowerCase();
  const targetDate = _dateKey(row?.target_date || null) || null;
  const targetStartTime = String(row?.target_start_time || '').trim() || null;
  const targetEndTime = String(row?.target_end_time || '').trim() || null;
  if (!id || !classId || !ruleId || !exceptionDate || !type) return null;
  return {
    id,
    class_id: classId,
    rule_id: ruleId,
    exception_date: exceptionDate,
    exception_type: type,
    target_date: targetDate,
    target_start_time: targetStartTime,
    target_end_time: targetEndTime,
    note: String(row?.note || '').trim() || null,
  };
}

function _getClassTimetableExceptions(classId) {
  const key = Number(classId || 0);
  if (!key) return [];
  const rows = _timetableExceptionsByClass.get(key);
  return Array.isArray(rows) ? rows : [];
}

function _setClassTimetableExceptions(classId, rows) {
  const key = Number(classId || 0);
  if (!key) return [];
  const normalized = (Array.isArray(rows) ? rows : [])
    .map(_normalizeTimetableExceptionRow)
    .filter(Boolean)
    .sort((a, b) => {
      const dateDiff = String(a.exception_date || '').localeCompare(String(b.exception_date || ''));
      if (dateDiff !== 0) return dateDiff;
      const ruleDiff = Number(a.rule_id || 0) - Number(b.rule_id || 0);
      if (ruleDiff !== 0) return ruleDiff;
      return Number(a.id || 0) - Number(b.id || 0);
    });
  _timetableExceptionsByClass.set(key, normalized);
  return normalized;
}

async function _loadClassTimetableExceptions(classId, weekDays = null) {
  const key = Number(classId || 0);
  if (!key) return [];
  const days = Array.isArray(weekDays) ? weekDays : _buildWeekDays(_weekStart);
  const dateFrom = days[0]?.key || _dateKey(_weekStart);
  const dateTo = days[days.length - 1]?.key || dateFrom;
  try {
    const rows = await api(`/workflow/classes/${key}/timetable-exceptions?date_from=${dateFrom}&date_to=${dateTo}`);
    return _setClassTimetableExceptions(key, rows);
  } catch {
    return _setClassTimetableExceptions(key, []);
  }
}

function _weekdayFromDateKey(dayKey) {
  const date = _dateFromKey(dayKey);
  if (!date) return null;
  const day = Number(date.getDay()); // Sunday=0
  return day === 0 ? 7 : day; // Monday=1 ... Sunday=7
}

function _ruleAppliesToDay(rule, dayKey) {
  const day = _dateKey(dayKey);
  if (!day) return false;
  const from = String(rule?.effective_from || '').trim();
  const to = String(rule?.effective_to || '').trim();
  if (!from) return false;
  if (day < from) return false;
  if (to && day > to) return false;
  return true;
}

function _buildPlannedSlotsByCell(weekSchedule, weekDays, rules, exceptions = []) {
  const output = new Map();
  const rows = Array.isArray(rules) ? rules : [];
  if (!rows.length) return output;
  const rulesById = new Map(rows.map(rule => [Number(rule?.id || 0), rule]).filter(([id]) => id > 0));
  const exceptionMap = new Map();
  (Array.isArray(exceptions) ? exceptions : []).forEach(row => {
    const key = `${Number(row?.rule_id || 0)}|${_dateKey(row?.exception_date || null)}`;
    if (!key || key.startsWith('0|')) return;
    exceptionMap.set(key, row);
  });

  const dayByKey = new Map((Array.isArray(weekSchedule) ? weekSchedule : []).map(day => [day.key, day]));
  const days = Array.isArray(weekDays) ? weekDays : [];
  days.forEach(day => {
    const dayKey = String(day?.key || '').trim();
    if (!dayKey) return;
    const weekday = _weekdayFromDateKey(dayKey);
    if (!weekday) return;
    if (weekday === 7) return;

    rows.forEach(rule => {
      if (Number(rule?.weekday || 0) === 7) return;
      if (Number(rule?.weekday || 0) !== weekday) return;
      if (!_ruleAppliesToDay(rule, dayKey)) return;
      const slotKey = _sessionSlotKey({ start_time: rule.start_time });
      if (!slotKey) return;
      const daySchedule = dayByKey.get(dayKey);
      const existingRows = daySchedule?.slots?.get(slotKey) || [];
      const plannedStart = _timeToMinutes(rule.start_time);
      const alreadyCovered = existingRows.some(session => _timeToMinutes(session?.start_time) === plannedStart);
      if (alreadyCovered) return;
      const exception = exceptionMap.get(`${Number(rule.id || 0)}|${dayKey}`) || null;

      const cellKey = `${dayKey}|${slotKey}`;
      if (!output.has(cellKey)) output.set(cellKey, []);
      const list = output.get(cellKey);
      const exceptionType = String(exception?.exception_type || '').toLowerCase();
      const isSkipped = Boolean(exception && (exceptionType === 'cancel' || exceptionType === 'move'));
      list.push({
        id: Number(rule.id || 0),
        dayKey,
        slotKey,
        start_time: rule.start_time,
        end_time: rule.end_time,
        subject: rule.subject,
        room: rule.room,
        group: rule.group,
        skipped: isSkipped,
        exception_id: exception ? Number(exception.id || 0) : null,
        exception_type: exception ? exceptionType || null : null,
        exception_note: exception ? String(exception.note || '').trim() || null : null,
        moved: false,
      });
    });
  });

  (Array.isArray(exceptions) ? exceptions : []).forEach(exception => {
    const exceptionType = String(exception?.exception_type || '').toLowerCase();
    if (exceptionType !== 'move') return;
    const ruleId = Number(exception?.rule_id || 0);
    const rule = rulesById.get(ruleId);
    if (!rule) return;

    const sourceDay = _dateKey(exception?.exception_date || null);
    const targetDay = _dateKey(exception?.target_date || null);
    const targetWeekday = _weekdayFromDateKey(targetDay);
    const targetStartTime = String(exception?.target_start_time || rule.start_time || '').trim();
    const targetEndTime = String(exception?.target_end_time || rule.end_time || '').trim() || null;
    if (!targetDay || !targetStartTime) return;
    if (targetWeekday === 7) return;
    if (!dayByKey.has(targetDay)) return;
    if (!_ruleAppliesToDay(rule, sourceDay)) return;
    if (targetDay === sourceDay && targetStartTime === String(rule.start_time || '').trim() && targetEndTime === (String(rule.end_time || '').trim() || null)) {
      return;
    }

    const slotKey = _sessionSlotKey({ start_time: targetStartTime });
    if (!slotKey) return;
    const daySchedule = dayByKey.get(targetDay);
    const existingRows = daySchedule?.slots?.get(slotKey) || [];
    const movedStart = _timeToMinutes(targetStartTime);
    const alreadyCovered = existingRows.some(session => _timeToMinutes(session?.start_time) === movedStart);
    if (alreadyCovered) return;

    const cellKey = `${targetDay}|${slotKey}`;
    if (!output.has(cellKey)) output.set(cellKey, []);
    const list = output.get(cellKey);
    const exceptionId = Number(exception?.id || 0);
    const duplicateMoved = list.some(row => Boolean(row?.moved) && Number(row?.exception_id || 0) === exceptionId);
    if (duplicateMoved) return;
    list.push({
      id: Number(rule.id || 0),
      dayKey: targetDay,
      slotKey,
      start_time: targetStartTime,
      end_time: targetEndTime,
      subject: rule.subject,
      room: rule.room,
      group: rule.group,
      skipped: false,
      moved: true,
      moved_from_date: sourceDay,
      exception_id: exceptionId || null,
      exception_type: 'move',
      exception_note: String(exception?.note || '').trim() || null,
    });
  });

  output.forEach(list => {
    list.sort((a, b) => {
      const timeDiff = (_timeToMinutes(a.start_time) ?? 0) - (_timeToMinutes(b.start_time) ?? 0);
      if (timeDiff !== 0) return timeDiff;
      return Number(a.id || 0) - Number(b.id || 0);
    });
  });
  return output;
}

function _buildWeekExceptionRows({ weekDays, rules, exceptions, occupiedStartKeys }) {
  const days = Array.isArray(weekDays) ? weekDays : [];
  const dayKeys = new Set(days.map(day => String(day?.key || '').trim()).filter(Boolean));
  const ruleById = new Map((Array.isArray(rules) ? rules : []).map(rule => [Number(rule?.id || 0), rule]));
  const rows = (Array.isArray(exceptions) ? exceptions : [])
    .map(exception => {
      const exceptionType = String(exception?.exception_type || '').toLowerCase();
      if (!['cancel', 'move'].includes(exceptionType)) return null;
      const sourceDate = _dateKey(exception?.exception_date || null);
      const targetDate = _dateKey(exception?.target_date || null);
      const sourceInWeek = sourceDate ? dayKeys.has(sourceDate) : false;
      const targetInWeek = targetDate ? dayKeys.has(targetDate) : false;
      if (!sourceInWeek && !targetInWeek) return null;
      const rule = ruleById.get(Number(exception?.rule_id || 0)) || null;
      const sourceStart = String(rule?.start_time || '').trim() || null;
      const sourceEnd = String(rule?.end_time || '').trim() || null;
      const targetStart = String(exception?.target_start_time || sourceStart || '').trim() || null;
      const targetEnd = String(exception?.target_end_time || sourceEnd || '').trim() || null;
      const subject = String(rule?.subject || '').trim() || 'Planned slot';
      return {
        id: Number(exception?.id || 0),
        rule_id: Number(exception?.rule_id || 0),
        type: exceptionType,
        note: String(exception?.note || '').trim() || null,
        subject,
        source_date: sourceDate,
        source_start: sourceStart,
        source_end: sourceEnd,
        target_date: targetDate,
        target_start: targetStart,
        target_end: targetEnd,
        source_in_week: sourceInWeek,
        target_in_week: targetInWeek,
        has_conflict: exceptionType === 'move'
          ? _hasSessionStartConflict(occupiedStartKeys || new Set(), targetDate, targetStart)
          : false,
      };
    })
    .filter(Boolean)
    .sort((a, b) => {
      const aDate = String(a.target_date || a.source_date || '');
      const bDate = String(b.target_date || b.source_date || '');
      const dateDiff = aDate.localeCompare(bDate);
      if (dateDiff !== 0) return dateDiff;
      const aTime = _timeToMinutes(a.target_start || a.source_start) ?? 0;
      const bTime = _timeToMinutes(b.target_start || b.source_start) ?? 0;
      if (aTime !== bTime) return aTime - bTime;
      return Number(a.id || 0) - Number(b.id || 0);
    });
  return rows;
}

function _buildSessionStartKeys(events) {
  const keys = new Set();
  (Array.isArray(events) ? events : []).forEach(event => {
    const dayKey = _dateKey(event?.session_date || event?.date || null);
    const start = String(event?.start_time || '').trim();
    if (!dayKey || !start) return;
    keys.add(`${dayKey}|${start.slice(0, 5)}`);
  });
  return keys;
}

function _hasSessionStartConflict(occupiedStartKeys, dateKey, startTime) {
  const dayKey = _dateKey(dateKey);
  const start = String(startTime || '').trim();
  if (!dayKey || !start) return false;
  return occupiedStartKeys.has(`${dayKey}|${start.slice(0, 5)}`);
}

function _yearRangeFromDateKeys(dateFromKey, dateToKey) {
  const from = _dateFromKey(dateFromKey);
  const to = _dateFromKey(dateToKey);
  if (!from || !to) return [];
  const min = from <= to ? from : to;
  const max = from <= to ? to : from;
  const years = [];
  for (let year = min.getFullYear(); year <= max.getFullYear(); year += 1) years.push(year);
  return years;
}

async function _loadHolidayMapForRange(dateFromKey, dateToKey) {
  const years = _yearRangeFromDateKeys(dateFromKey, dateToKey);
  if (!years.length) return new Map();
  const responses = await Promise.all(
    years.map(year => api(`/workflow/holidays?year=${year}&country_code=MA`).catch(() => []))
  );
  const allRows = responses.flatMap(rows => (Array.isArray(rows) ? rows : []));
  return _buildHolidayMap(allRows);
}

async function _fetchTimetableExceptionsInRange(classId, dateFromKey, dateToKey) {
  const key = Number(classId || 0);
  if (!key) return [];
  const from = _dateKey(dateFromKey);
  const to = _dateKey(dateToKey);
  if (!from || !to) return [];
  const rows = await api(`/workflow/classes/${key}/timetable-exceptions?date_from=${from}&date_to=${to}`);
  return (Array.isArray(rows) ? rows : [])
    .map(_normalizeTimetableExceptionRow)
    .filter(Boolean);
}

function _buildContentAutofillCandidates({
  dateFromKey,
  dateToKey,
  rules,
  exceptions,
  occupiedStartKeys,
  holidayMap,
}) {
  const output = {
    slots: [],
    blocked_holiday_count: 0,
    already_exists_count: 0,
    duplicate_count: 0,
    skipped_exception_count: 0,
  };
  const from = _dateFromKey(dateFromKey);
  const to = _dateFromKey(dateToKey);
  if (!from || !to) return output;
  const minDate = from <= to ? from : to;
  const maxDate = from <= to ? to : from;
  const minKey = _dateKey(minDate);
  const maxKey = _dateKey(maxDate);
  const rows = Array.isArray(rules) ? rules : [];
  if (!rows.length) return output;

  const rulesById = new Map(rows.map(rule => [Number(rule?.id || 0), rule]).filter(([id]) => id > 0));
  const exceptionByRuleDate = new Map();
  (Array.isArray(exceptions) ? exceptions : []).forEach(row => {
    const ruleId = Number(row?.rule_id || 0);
    const sourceDate = _dateKey(row?.exception_date || null);
    if (!ruleId || !sourceDate) return;
    exceptionByRuleDate.set(`${ruleId}|${sourceDate}`, row);
  });

  const slotByKey = new Map();
  const addCandidate = ({ dayKey, startTime, endTime, rule, movedFromDate = null }) => {
    const slotKey = `${dayKey}|${String(startTime || '').slice(0, 5)}`;
    if (!dayKey || !startTime || slotKey.endsWith('|')) return;
    if (Boolean(holidayMap?.get?.(dayKey)?.is_blocked)) {
      output.blocked_holiday_count += 1;
      return;
    }
    if (_hasSessionStartConflict(occupiedStartKeys || new Set(), dayKey, startTime)) {
      output.already_exists_count += 1;
      return;
    }
    if (slotByKey.has(slotKey)) {
      output.duplicate_count += 1;
      return;
    }
    const startMinutes = _timeToMinutes(startTime);
    if (startMinutes == null) return;
    const parsedEnd = _timeToMinutes(endTime);
    const endMinutes = parsedEnd != null && parsedEnd > startMinutes ? parsedEnd : startMinutes + 60;
    slotByKey.set(slotKey, {
      day_key: dayKey,
      start_time: _minutesToPayloadTime(startMinutes),
      end_time: _minutesToPayloadTime(endMinutes),
      rule_id: Number(rule?.id || 0) || null,
      subject: String(rule?.subject || '').trim() || null,
      room: String(rule?.room || '').trim() || null,
      group: String(rule?.group || '').trim() || null,
      moved_from_date: movedFromDate ? _dateKey(movedFromDate) : null,
    });
  };

  for (let cursor = new Date(minDate); cursor <= maxDate; cursor = _addDays(cursor, 1)) {
    const dayKey = _dateKey(cursor);
    const weekday = _weekdayFromDateKey(dayKey);
    if (!weekday) continue;
    rows.forEach(rule => {
      if (Number(rule?.weekday || 0) !== weekday) return;
      if (!_ruleAppliesToDay(rule, dayKey)) return;
      const exception = exceptionByRuleDate.get(`${Number(rule?.id || 0)}|${dayKey}`) || null;
      const exceptionType = String(exception?.exception_type || '').toLowerCase();
      if (exceptionType === 'cancel' || exceptionType === 'move') {
        output.skipped_exception_count += 1;
        return;
      }
      addCandidate({
        dayKey,
        startTime: String(rule?.start_time || '').trim(),
        endTime: String(rule?.end_time || '').trim(),
        rule,
      });
    });
  }

  (Array.isArray(exceptions) ? exceptions : []).forEach(exception => {
    const exceptionType = String(exception?.exception_type || '').toLowerCase();
    if (exceptionType !== 'move') return;
    const rule = rulesById.get(Number(exception?.rule_id || 0));
    if (!rule) return;
    const sourceDate = _dateKey(exception?.exception_date || null);
    const targetDate = _dateKey(exception?.target_date || null);
    if (!sourceDate || !targetDate) return;
    if (!_ruleAppliesToDay(rule, sourceDate)) return;
    if (targetDate < minKey || targetDate > maxKey) return;
    addCandidate({
      dayKey: targetDate,
      startTime: String(exception?.target_start_time || rule.start_time || '').trim(),
      endTime: String(exception?.target_end_time || rule.end_time || '').trim(),
      rule,
      movedFromDate: sourceDate,
    });
  });

  output.slots = Array.from(slotByKey.values()).sort((a, b) => {
    const dateDiff = String(a.day_key || '').localeCompare(String(b.day_key || ''));
    if (dateDiff !== 0) return dateDiff;
    return (_timeToMinutes(a.start_time) ?? 0) - (_timeToMinutes(b.start_time) ?? 0);
  });
  return output;
}

function _buildWeekAutofillPlan({ plannedSlotsByCell, weekHolidayMap, occupiedStartKeys }) {
  const output = {
    ready: [],
    blocked_holiday_count: 0,
    already_exists_count: 0,
    duplicate_count: 0,
    skipped_exception_count: 0,
  };
  const seenKeys = new Set();
  const cells = plannedSlotsByCell instanceof Map ? plannedSlotsByCell : new Map();

  cells.forEach(rows => {
    (Array.isArray(rows) ? rows : []).forEach(rule => {
      if (rule?.skipped) {
        output.skipped_exception_count += 1;
        return;
      }
      const dayKey = _dateKey(rule?.dayKey || null);
      const startMinutes = _timeToMinutes(rule?.start_time || null);
      if (!dayKey || startMinutes == null) return;
      const key = `${dayKey}|${String(rule?.start_time || '').slice(0, 5)}`;
      if (seenKeys.has(key)) {
        output.duplicate_count += 1;
        return;
      }
      seenKeys.add(key);
      if (Boolean(weekHolidayMap?.get?.(dayKey)?.is_blocked)) {
        output.blocked_holiday_count += 1;
        return;
      }
      if (_hasSessionStartConflict(occupiedStartKeys || new Set(), dayKey, rule?.start_time || null)) {
        output.already_exists_count += 1;
        return;
      }

      let endMinutes = _timeToMinutes(rule?.end_time || null);
      if (endMinutes == null || endMinutes <= startMinutes) endMinutes = startMinutes + 60;
      const subject = String(rule?.subject || '').trim();
      const room = String(rule?.room || '').trim();
      const group = String(rule?.group || '').trim();
      const detailParts = [subject, room ? `room ${room}` : '', group ? `group ${group}` : '']
        .map(part => String(part || '').trim())
        .filter(Boolean);
      output.ready.push({
        session_date: dayKey,
        start_time: _minutesToPayloadTime(startMinutes),
        end_time: _minutesToPayloadTime(endMinutes),
        note: detailParts.length
          ? `Auto-planned from timetable: ${detailParts.join(' â€¢ ')}`
          : 'Auto-planned from timetable',
      });
    });
  });

  output.ready.sort((a, b) => {
    const dateDiff = String(a.session_date || '').localeCompare(String(b.session_date || ''));
    if (dateDiff !== 0) return dateDiff;
    return (_timeToMinutes(a.start_time) ?? 0) - (_timeToMinutes(b.start_time) ?? 0);
  });
  return output;
}

function _buildWeekSchedule(events, weekDays) {
  const weekDayMap = new Map();
  weekDays.forEach(day => {
    const slots = new Map(TIME_SLOTS.map(slot => [slot.key, []]));
    weekDayMap.set(day.key, {
      ...day,
      slots,
      outsideHours: [],
    });
  });

  (events || []).forEach(session => {
    const sessionKey = _dateKey(session?.session_date || session?.date || null);
    if (!sessionKey || !weekDayMap.has(sessionKey)) return;
    const dayRow = weekDayMap.get(sessionKey);
    const slotKey = _sessionSlotKey(session);
    if (slotKey && dayRow.slots.has(slotKey)) {
      dayRow.slots.get(slotKey).push(session);
      return;
    }
    dayRow.outsideHours.push(session);
  });

  weekDayMap.forEach(day => {
    day.slots.forEach(rows => {
      rows.sort((a, b) => {
        const timeDiff = _sessionSortValue(a) - _sessionSortValue(b);
        if (timeDiff !== 0) return timeDiff;
        return Number(a.session_id || 0) - Number(b.session_id || 0);
      });
    });
    day.outsideHours.sort((a, b) => {
      const timeDiff = _sessionSortValue(a) - _sessionSortValue(b);
      if (timeDiff !== 0) return timeDiff;
      return Number(a.session_id || 0) - Number(b.session_id || 0);
    });
  });

  return weekDays.map(day => weekDayMap.get(day.key));
}

function _computeUnitSessionNumbers(events) {
  const rows = Array.isArray(events) ? events : [];
  const persisted = new Map();
  const grouped = new Map();
  rows.forEach(event => {
    const unitId = Number(event?.unit_id || 0);
    const sessionId = Number(event?.session_id || 0);
    if (!unitId || !sessionId) return;
    const persistedNumber = Number(event?.unit_session_number || 0);
    if (Number.isFinite(persistedNumber) && persistedNumber > 0) {
      persisted.set(sessionId, Math.floor(persistedNumber));
      return;
    }
    if (!grouped.has(unitId)) grouped.set(unitId, []);
    grouped.get(unitId).push(event);
  });

  const map = new Map(persisted);
  grouped.forEach(unitRows => {
    const sorted = [...unitRows].sort((a, b) => {
      const dateDiff = String(a?.session_date || '').localeCompare(String(b?.session_date || ''));
      if (dateDiff !== 0) return dateDiff;
      const timeDiff = _sessionSortValue(a) - _sessionSortValue(b);
      if (timeDiff !== 0) return timeDiff;
      return Number(a?.session_id || 0) - Number(b?.session_id || 0);
    });
    sorted.forEach((row, idx) => {
      const sid = Number(row.session_id);
      if (!sid || map.has(sid)) return;
      map.set(sid, idx + 1);
    });
  });
  return map;
}

function _splitNumberedCalendarRows(value) {
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

function _groupProgressItems(progressItems) {
  const groups = new Map();
  (progressItems || []).forEach(item => {
    const typeKey = String(item?.item_type || 'lesson').toLowerCase();
    const label = PROGRESS_TYPE_LABELS[typeKey] || 'Other';
    if (!groups.has(label)) groups.set(label, []);
    const heading = String(item?.heading || '').trim();
    const content = String(item?.content || '').trim();
    let text = '';
    if (content) {
      text = heading && heading.toLowerCase() !== label.toLowerCase()
        ? `${heading}: ${content}`
        : content;
    } else {
      text = heading;
    }
    if (!text) return;
    const rows = _splitNumberedCalendarRows(text);
    if (!rows.length) {
      groups.get(label).push(text);
      return;
    }
    rows.forEach(row => groups.get(label).push(row));
  });
  return Array.from(groups.entries()).map(([label, items]) => ({ label, items }));
}

function _findSelectedEvent(events) {
  if (!_selectedSessionId) return null;
  const sid = Number(_selectedSessionId);
  return (events || []).find(row => Number(row.session_id) === sid) || null;
}

function _absentRowsFromDetail(detail, selectedEvent, studentsById) {
  const attendance = Array.isArray(detail?.attendance) ? detail.attendance : [];
  const absentRows = attendance.filter(row => String(row.status || '').toLowerCase() === 'absent');
  if (absentRows.length) {
    return absentRows.map(row => ({
      id: Number(row.student_id),
      name: String(row.full_name || studentsById.get(Number(row.student_id))?.full_name || 'Student'),
      code: String(row.student_code || studentsById.get(Number(row.student_id))?.student_code || ''),
    }));
  }

  const ids = Array.isArray(selectedEvent?.absent_student_ids) ? selectedEvent.absent_student_ids : [];
  return ids.map(rawId => {
    const id = Number(rawId);
    const student = studentsById.get(id);
    return {
      id,
      name: student?.full_name || `Student #${id}`,
      code: student?.student_code || '',
    };
  });
}

function _headlineBlocksFromDetail(detail, selectedEvent) {
  const progressItems = Array.isArray(detail?.progress_items) ? detail.progress_items : [];
  const grouped = _groupProgressItems(progressItems);
  if (grouped.length) return grouped;

  const checkedItems = Array.isArray(selectedEvent?.checked_items) ? selectedEvent.checked_items : [];
  if (!checkedItems.length) return [];
  const splitCheckedItems = checkedItems
    .flatMap(value => {
      const text = String(value || '').trim();
      if (!text) return [];
      const rows = _splitNumberedCalendarRows(text);
      return rows.length ? rows : [text];
    });
  if (!splitCheckedItems.length) return [];
  return [{ label: 'Checklist', items: splitCheckedItems }];
}

function _resolveSessionDurationMinutes(session) {
  const start = _timeToMinutes(session?.start_time);
  const end = _timeToMinutes(session?.end_time);
  if (start == null || end == null || end <= start) return 60;
  return end - start;
}

function _isPastWorkflowSession(session, todayKey = _dateKey(new Date())) {
  if (!session || session.unit_id == null) return false;
  const sessionDateKey = _dateKey(session.session_date || session.date || null);
  if (!sessionDateKey || !todayKey) return false;
  return sessionDateKey < todayKey;
}

async function _reloadCalendarData(classId) {
  const [workflowRows, sessionRows] = await Promise.all([
    api(`/workflow/classes/${classId}/calendar`).catch(() => []),
    api(`/classes/${classId}/sessions`).catch(() => []),
  ]);
  const merged = _mergeCalendarData(workflowRows, sessionRows);
  setCalendar(merged);
  return merged;
}

async function _selectSession(sessionId, el, classId) {
  const sid = Number(sessionId);
  if (!sid) return;

  _selectedSessionId = sid;
  _selectedSessionError = null;
  _calendarPlannedHideDone = false;

  if (_sessionDetailCache.has(sid)) {
    _selectedSessionLoading = false;
    _renderCalendar(el, classId);
    return;
  }

  _selectedSessionLoading = true;
  _renderCalendar(el, classId);

  try {
    const detail = await api(`/sessions/${sid}`);
    if (detail && detail.unit_id != null) {
      const blueprintState = await _loadCalendarUnitBlueprint(classId, detail.unit_id);
      detail.unit_blueprint = blueprintState?.item && typeof blueprintState.item === 'object' ? blueprintState.item : null;
      detail.unit_blueprint_error = blueprintState?.error ? String(blueprintState.error) : null;
      try {
        detail.workflow_writeup = await api(`/workflow/classes/${classId}/sessions/${sid}/writeup`);
        detail.workflow_writeup_error = null;
      } catch (writeupErr) {
        detail.workflow_writeup = null;
        detail.workflow_writeup_error = String(writeupErr?.message || 'Failed to load workflow write-up.');
      }
    } else if (detail && typeof detail === 'object') {
      detail.unit_blueprint = null;
      detail.unit_blueprint_error = null;
      detail.workflow_writeup = null;
      detail.workflow_writeup_error = null;
    }
    if (Number(_selectedSessionId) !== sid) return;
    _sessionDetailCache.set(sid, detail);
  } catch (err) {
    if (Number(_selectedSessionId) !== sid) return;
    _selectedSessionError = String(err?.message || 'Failed to load session details.');
  } finally {
    if (Number(_selectedSessionId) !== sid) return;
    _selectedSessionLoading = false;
    _renderCalendar(el, classId);
  }
}

function _openSessionBlockModal({ title, dateKey, startTime, endTime, note = '' }) {
  return new Promise(resolve => {
    const dateInput = _escapeHtml(dateKey || '');
    const startInput = _escapeHtml(String(startTime || '').slice(0, 5));
    const endInput = _escapeHtml(String(endTime || '').slice(0, 5));
    const noteInput = _escapeHtml(String(note || ''));

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-lg w-[95vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">${_escapeHtml(title || 'Session Block')}</h2>
          <p class="text-[12px] text-slate-500 mt-1">Confirm date and time before saving.</p>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Date</label>
              <input id="session-block-date" type="date" value="${dateInput}" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Start</label>
              <input id="session-block-start" type="time" value="${startInput}" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">End</label>
              <input id="session-block-end" type="time" value="${endInput}" />
            </div>
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Note</label>
            <textarea id="session-block-note" rows="3" placeholder="Optional note">${noteInput}</textarea>
          </div>
          <p id="session-block-error" class="text-[12px] text-red-600 hidden"></p>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="session-block-cancel" class="btn btn-ghost">Cancel</button>
          <button id="session-block-save" class="btn btn-primary">Save</button>
        </div>
      </div>`;

    const setError = message => {
      const node = overlay.querySelector('#session-block-error');
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
    overlay.querySelector('#session-block-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#session-block-save')?.addEventListener('click', () => {
      const sessionDate = String(overlay.querySelector('#session-block-date')?.value || '').trim();
      const startValue = String(overlay.querySelector('#session-block-start')?.value || '').trim();
      const endValue = String(overlay.querySelector('#session-block-end')?.value || '').trim();
      const noteValue = String(overlay.querySelector('#session-block-note')?.value || '').trim();

      if (!sessionDate) {
        setError('Date is required.');
        return;
      }
      if (!startValue || !endValue) {
        setError('Start and end time are required.');
        return;
      }
      if (endValue <= startValue) {
        setError('End time must be greater than start time.');
        return;
      }

      cleanup({
        session_date: sessionDate,
        start_time: `${startValue}:00`,
        end_time: `${endValue}:00`,
        note: noteValue,
      });
    });

    document.body.appendChild(overlay);
    overlay.querySelector('#session-block-start')?.focus();
  });
}

function _resolveAbsentStudentIds(detail, selectedEvent) {
  const attendance = Array.isArray(detail?.attendance) ? detail.attendance : [];
  if (attendance.length) {
    return attendance
      .filter(row => String(row?.status || '').toLowerCase() === 'absent')
      .map(row => Number(row?.student_id || 0))
      .filter(id => Number.isFinite(id) && id > 0);
  }
  return (Array.isArray(selectedEvent?.absent_student_ids) ? selectedEvent.absent_student_ids : [])
    .map(value => Number(value))
    .filter(id => Number.isFinite(id) && id > 0);
}

function _openCalendarSlotQuickActionModal({
  dayKey,
  slotIndex,
  activeUnitTitle,
  activeChecklist = [],
  holidayInfo = null,
  students = [],
}) {
  return new Promise(resolve => {
    const slot = TIME_SLOTS[Math.max(0, Math.min(TIME_SLOTS.length - 1, Number(slotIndex) || 0))] || TIME_SLOTS[0];
    const defaultStart = _minutesToPayloadTime(slot.start).slice(0, 5);
    const defaultEnd = _minutesToPayloadTime(slot.end).slice(0, 5);
    const pendingChecklistItems = _flattenChecklistNodes(activeChecklist).filter(
      row => Number(row.id) > 0 && !row.is_completed
    );
    const studentRows = (Array.isArray(students) ? students : [])
      .map(student => ({
        id: Number(student?.id || 0),
        full_name: String(student?.full_name || '').trim(),
        student_code: String(student?.student_code || '').trim(),
      }))
      .filter(student => student.id > 0 && student.full_name)
      .sort((a, b) => a.full_name.localeCompare(b.full_name, undefined, { sensitivity: 'base', numeric: true }));
    const isBlockedHoliday = Boolean(holidayInfo?.is_blocked);
    const holidayName = String(holidayInfo?.name || 'Holiday').trim() || 'Holiday';

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-2xl w-[96vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">Continue Active Unit</h2>
          <p class="text-[12px] text-slate-500 mt-1">Create a session from this timetable slot and update checklist progress.</p>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="rounded-xl border border-blue-100 bg-blue-50 px-3 py-2">
            <p class="text-[12px] text-blue-700">
              Active unit: <span class="font-semibold">${_escapeHtml(activeUnitTitle || 'Active Unit')}</span>
            </p>
          </div>
          ${isBlockedHoliday ? `
          <div class="holiday-warning-card">
            <p class="text-[12px] font-semibold">Blocked holiday: ${_escapeHtml(holidayName)}</p>
            <label class="inline-flex items-center gap-2 text-[12px] mt-1">
              <input id="quick-action-allow-holiday" type="checkbox" />
              <span>Allow workflow session on this holiday</span>
            </label>
            <p class="text-[11px] text-rose-700/80 mt-1">Enable override to continue active unit on this date.</p>
          </div>` : ''}

          <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Date</label>
              <input id="quick-action-date" type="date" value="${_escapeHtml(dayKey || '')}" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Start</label>
              <input id="quick-action-start" type="time" value="${_escapeHtml(defaultStart)}" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">End</label>
              <input id="quick-action-end" type="time" value="${_escapeHtml(defaultEnd)}" />
            </div>
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Session Note</label>
            <textarea id="quick-action-note" rows="2" placeholder="Optional note"></textarea>
          </div>

          <div class="rounded-xl border border-slate-200 p-3 flex flex-col gap-2">
            <p class="text-[12px] font-semibold text-slate-600">Checklist Progress (optional)</p>
            ${pendingChecklistItems.length ? `
            <div class="max-h-[170px] overflow-auto border border-slate-100 rounded-lg bg-slate-50">
              ${pendingChecklistItems.map(item => `
                <label class="flex items-start gap-2 px-2 py-1.5 border-b border-slate-100 last:border-b-0">
                  <input type="checkbox" data-check-item-id="${Number(item.id)}" class="mt-0.5" />
                  <span class="text-[12px] text-slate-700">
                    <span style="padding-left:${Math.max(0, Number(item.depth || 0)) * 10}px; display:inline-block;">
                      ${_escapeHtml(item.title || `Item #${Number(item.id)}`)}
                    </span>
                    ${item.item_kind ? `<span class="text-[10px] text-slate-500 ml-1">(${_escapeHtml(item.item_kind)})</span>` : ''}
                  </span>
                </label>
              `).join('')}
            </div>
            ` : '<p class="text-[12px] text-slate-500">No pending checklist items in this unit.</p>'}
            <p class="text-[11px] text-slate-500">Checked items will be recorded in this session.</p>
          </div>

          <div class="rounded-xl border border-slate-200 p-3 flex flex-col gap-2">
            <p class="text-[12px] font-semibold text-slate-600">Absent Students (optional)</p>
            ${studentRows.length ? `
            <div class="max-h-[170px] overflow-auto border border-slate-100 rounded-lg bg-slate-50">
              ${studentRows.map(student => `
                <label class="flex items-start gap-2 px-2 py-1.5 border-b border-slate-100 last:border-b-0">
                  <input type="checkbox" data-quick-absent-student-id="${student.id}" class="mt-0.5" />
                  <span class="text-[12px] text-slate-700">
                    ${_escapeHtml(student.full_name)}
                    ${student.student_code ? `<span class="text-[10px] text-slate-500 ml-1">(${_escapeHtml(student.student_code)})</span>` : ''}
                  </span>
                </label>
              `).join('')}
            </div>
            ` : '<p class="text-[12px] text-slate-500">No students found for this class.</p>'}
          </div>

          <p id="quick-action-error" class="text-[12px] text-red-600 hidden"></p>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="quick-action-cancel" class="btn btn-ghost">Cancel</button>
          <button id="quick-action-save" class="btn btn-primary">Save</button>
        </div>
      </div>`;

    const setError = message => {
      const node = overlay.querySelector('#quick-action-error');
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
    overlay.querySelector('#quick-action-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#quick-action-save')?.addEventListener('click', () => {
      const sessionDate = String(overlay.querySelector('#quick-action-date')?.value || '').trim();
      const startValue = String(overlay.querySelector('#quick-action-start')?.value || '').trim();
      const endValue = String(overlay.querySelector('#quick-action-end')?.value || '').trim();
      const noteValue = String(overlay.querySelector('#quick-action-note')?.value || '').trim();
      const allowOnHoliday = Boolean(overlay.querySelector('#quick-action-allow-holiday')?.checked);
      const checkedItemIds = Array.from(overlay.querySelectorAll('input[data-check-item-id]:checked'))
        .map(node => Number(node.getAttribute('data-check-item-id') || 0))
        .filter(value => Number.isFinite(value) && value > 0);
      const absentStudentIds = Array.from(overlay.querySelectorAll('input[data-quick-absent-student-id]:checked'))
        .map(node => Number(node.getAttribute('data-quick-absent-student-id') || 0))
        .filter(value => Number.isFinite(value) && value > 0);

      if (!sessionDate) {
        setError('Date is required.');
        return;
      }
      if (!startValue || !endValue) {
        setError('Start and end time are required.');
        return;
      }
      if (endValue <= startValue) {
        setError('End time must be greater than start time.');
        return;
      }
      if (isBlockedHoliday && !allowOnHoliday) {
        setError(`This day is blocked (${holidayName}). Enable holiday override to continue.`);
        return;
      }

      cleanup({
        action: 'continue_unit',
        session: {
          session_date: sessionDate,
          start_time: `${startValue}:00`,
          end_time: `${endValue}:00`,
          note: noteValue,
        },
        checked_item_ids: checkedItemIds,
        absent_student_ids: Array.from(new Set(absentStudentIds)).sort((a, b) => a - b),
        allow_on_holiday: allowOnHoliday,
      });
    });

    document.body.appendChild(overlay);
    overlay.querySelector('#quick-action-date')?.focus();
  });
}

function _openDocumentAutoSetupModal({ defaultStartDate }) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-3xl w-[96vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">Document -> Full Setup</h2>
          <p class="text-[12px] text-slate-500 mt-1">Upload or paste content, choose session count, and auto-create unit sessions with checklist progress.</p>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div class="flex flex-col gap-1 sm:col-span-2">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Unit Title</label>
              <input id="doc-setup-title" type="text" placeholder="Example: Fractions and Operations" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Unit Type</label>
              <select id="doc-setup-type">
                ${UNIT_TYPE_OPTIONS.map(option => `<option value="${option.value}">${_escapeHtml(option.label)}</option>`).join('')}
              </select>
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Sessions Count</label>
              <input id="doc-setup-count" type="number" min="1" max="120" step="1" value="6" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Start From</label>
              <input id="doc-setup-start" type="date" value="${_escapeHtml(defaultStartDate || '')}" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Planned Hours (optional)</label>
              <input id="doc-setup-hours" type="number" min="0" step="0.5" placeholder="Optional" />
            </div>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">PDF Document (optional)</label>
              <input id="doc-setup-file" type="file" accept=".pdf,application/pdf" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Auto Checklist Progress</label>
              <label class="inline-flex items-center gap-2 text-[12px] mt-2">
                <input id="doc-setup-auto-check" type="checkbox" checked />
                <span>Distribute checklist items over created sessions</span>
              </label>
            </div>
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Source Text (recommended if no PDF)</label>
            <textarea id="doc-setup-source" rows="6" placeholder="Paste chapter/series text here."></textarea>
          </div>
          <p id="doc-setup-error" class="text-[12px] text-red-600 hidden"></p>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="doc-setup-cancel" class="btn btn-ghost">Cancel</button>
          <button id="doc-setup-save" class="btn btn-primary">Run Full Setup</button>
        </div>
      </div>
    `;

    const setError = message => {
      const node = overlay.querySelector('#doc-setup-error');
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
    overlay.querySelector('#doc-setup-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#doc-setup-save')?.addEventListener('click', () => {
      const unitTitle = String(overlay.querySelector('#doc-setup-title')?.value || '').trim();
      const unitType = String(overlay.querySelector('#doc-setup-type')?.value || 'chapter').trim();
      const startDate = String(overlay.querySelector('#doc-setup-start')?.value || '').trim();
      const rawCount = Number(overlay.querySelector('#doc-setup-count')?.value || 0);
      const sessionCount = Number.isFinite(rawCount) ? Math.floor(rawCount) : 0;
      const sourceText = String(overlay.querySelector('#doc-setup-source')?.value || '').trim();
      const file = overlay.querySelector('#doc-setup-file')?.files?.[0] || null;
      const autoCheck = Boolean(overlay.querySelector('#doc-setup-auto-check')?.checked);
      const rawHours = String(overlay.querySelector('#doc-setup-hours')?.value || '').trim();

      if (!unitTitle) {
        setError('Unit title is required.');
        return;
      }
      if (!startDate) {
        setError('Start date is required.');
        return;
      }
      if (sessionCount <= 0) {
        setError('Sessions count must be at least 1.');
        return;
      }
      if (sessionCount > 120) {
        setError('Sessions count is too high. Use 120 or less.');
        return;
      }
      if ((unitType === 'chapter' || unitType === 'exercise_series') && !file && !sourceText) {
        setError('For chapter/exercise units, provide a PDF or source text.');
        return;
      }
      let plannedHours = null;
      if (rawHours) {
        const parsedHours = Number(rawHours);
        if (!Number.isFinite(parsedHours) || parsedHours <= 0) {
          setError('Planned hours must be greater than zero.');
          return;
        }
        plannedHours = parsedHours;
      }
      cleanup({
        unit_type: unitType,
        unit_title: unitTitle,
        session_count: sessionCount,
        start_date: startDate,
        planned_hours: plannedHours,
        source_text: sourceText,
        auto_check_items: autoCheck,
        file,
      });
    });

    document.body.appendChild(overlay);
    overlay.querySelector('#doc-setup-title')?.focus();
  });
}

function _openPastSessionSubmitModal({ defaultDate, activeUnitTitle, activeChecklist = [], students = [] }) {
  return new Promise(resolve => {
    const dateValue = _dateKey(defaultDate || new Date());
    const pendingChecklistItems = _flattenChecklistNodes(activeChecklist).filter(
      row => Number(row.id) > 0 && !row.is_completed
    );
    const studentRows = (Array.isArray(students) ? students : [])
      .map(student => ({
        id: Number(student?.id || 0),
        full_name: String(student?.full_name || '').trim(),
        student_code: String(student?.student_code || '').trim(),
      }))
      .filter(student => student.id > 0 && student.full_name)
      .sort((a, b) => a.full_name.localeCompare(b.full_name, undefined, { sensitivity: 'base', numeric: true }));
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-2xl w-[96vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">Submit Past Session</h2>
          <p class="text-[12px] text-slate-500 mt-1">Record a delivered past session for the active unit.</p>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="rounded-xl border border-blue-100 bg-blue-50 px-3 py-2">
            <p class="text-[12px] text-blue-700">
              Active unit: <span class="font-semibold">${_escapeHtml(activeUnitTitle || 'Active Unit')}</span>
            </p>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Date</label>
              <input id="past-session-date" type="date" value="${_escapeHtml(dateValue)}" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Start</label>
              <input id="past-session-start" type="time" value="08:00" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">End</label>
              <input id="past-session-end" type="time" value="09:00" />
            </div>
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Note</label>
            <textarea id="past-session-note" rows="2" placeholder="Optional note"></textarea>
          </div>
          <div class="rounded-xl border border-slate-200 p-3 flex flex-col gap-2">
            <p class="text-[12px] font-semibold text-slate-600">Checklist done in this session (optional)</p>
            ${pendingChecklistItems.length ? `
            <div class="max-h-[180px] overflow-auto border border-slate-100 rounded-lg bg-slate-50">
              ${pendingChecklistItems.map(item => `
                <label class="flex items-start gap-2 px-2 py-1.5 border-b border-slate-100 last:border-b-0">
                  <input type="checkbox" data-past-check-item-id="${Number(item.id)}" class="mt-0.5" />
                  <span class="text-[12px] text-slate-700">
                    <span style="padding-left:${Math.max(0, Number(item.depth || 0)) * 10}px; display:inline-block;">
                      ${_escapeHtml(item.title || `Item #${Number(item.id)}`)}
                    </span>
                    ${item.item_kind ? `<span class="text-[10px] text-slate-500 ml-1">(${_escapeHtml(item.item_kind)})</span>` : ''}
                  </span>
                </label>
              `).join('')}
            </div>
            ` : '<p class="text-[12px] text-slate-500">No pending checklist items left in this unit.</p>'}
          </div>
          <div class="rounded-xl border border-slate-200 p-3 flex flex-col gap-2">
            <p class="text-[12px] font-semibold text-slate-600">Absent Students (optional)</p>
            ${studentRows.length ? `
            <div class="max-h-[180px] overflow-auto border border-slate-100 rounded-lg bg-slate-50">
              ${studentRows.map(student => `
                <label class="flex items-start gap-2 px-2 py-1.5 border-b border-slate-100 last:border-b-0">
                  <input type="checkbox" data-past-absent-student-id="${student.id}" class="mt-0.5" />
                  <span class="text-[12px] text-slate-700">
                    ${_escapeHtml(student.full_name)}
                    ${student.student_code ? `<span class="text-[10px] text-slate-500 ml-1">(${_escapeHtml(student.student_code)})</span>` : ''}
                  </span>
                </label>
              `).join('')}
            </div>
            ` : '<p class="text-[12px] text-slate-500">No students found for this class.</p>'}
          </div>
          <label class="inline-flex items-center gap-2 text-[12px] text-slate-700">
            <input id="past-session-allow-holiday" type="checkbox" />
            <span>Allow holiday override for this session date</span>
          </label>
          <p id="past-session-error" class="text-[12px] text-red-600 hidden"></p>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="past-session-cancel" class="btn btn-ghost">Cancel</button>
          <button id="past-session-save" class="btn btn-primary">Save Session</button>
        </div>
      </div>
    `;

    const setError = message => {
      const node = overlay.querySelector('#past-session-error');
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
    overlay.querySelector('#past-session-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#past-session-save')?.addEventListener('click', () => {
      const sessionDate = String(overlay.querySelector('#past-session-date')?.value || '').trim();
      const startValue = String(overlay.querySelector('#past-session-start')?.value || '').trim();
      const endValue = String(overlay.querySelector('#past-session-end')?.value || '').trim();
      const noteValue = String(overlay.querySelector('#past-session-note')?.value || '').trim();
      const allowOnHoliday = Boolean(overlay.querySelector('#past-session-allow-holiday')?.checked);
      const checkedItemIds = Array.from(overlay.querySelectorAll('input[data-past-check-item-id]:checked'))
        .map(node => Number(node.getAttribute('data-past-check-item-id') || 0))
        .filter(value => Number.isFinite(value) && value > 0);
      const absentStudentIds = Array.from(overlay.querySelectorAll('input[data-past-absent-student-id]:checked'))
        .map(node => Number(node.getAttribute('data-past-absent-student-id') || 0))
        .filter(value => Number.isFinite(value) && value > 0);

      if (!sessionDate) {
        setError('Date is required.');
        return;
      }
      if (!startValue || !endValue) {
        setError('Start and end time are required.');
        return;
      }
      if (endValue <= startValue) {
        setError('End time must be greater than start time.');
        return;
      }

      cleanup({
        session_date: sessionDate,
        start_time: `${startValue}:00`,
        end_time: `${endValue}:00`,
        note: noteValue,
        checked_item_ids: checkedItemIds,
        absent_student_ids: Array.from(new Set(absentStudentIds)).sort((a, b) => a - b),
        allow_on_holiday: allowOnHoliday,
      });
    });

    document.body.appendChild(overlay);
    overlay.querySelector('#past-session-date')?.focus();
  });
}

function _openSessionAttendanceModal({ sessionDateKey, students = [], absentStudentIds = [] }) {
  return new Promise(resolve => {
    const rows = (Array.isArray(students) ? students : [])
      .map(student => ({
        id: Number(student?.id || 0),
        full_name: String(student?.full_name || '').trim(),
        student_code: String(student?.student_code || '').trim(),
      }))
      .filter(student => student.id > 0 && student.full_name)
      .sort((a, b) => a.full_name.localeCompare(b.full_name, undefined, { sensitivity: 'base', numeric: true }));
    const absentSet = new Set(
      (Array.isArray(absentStudentIds) ? absentStudentIds : [])
        .map(value => Number(value))
        .filter(value => Number.isFinite(value) && value > 0)
    );

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-2xl w-[96vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">Edit Attendance</h2>
          <p class="text-[12px] text-slate-500 mt-1">Session date: ${_escapeHtml(fmtDate(sessionDateKey || _dateKey(new Date())))}</p>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <p class="text-[12px] text-slate-600">Check students who were absent.</p>
          <div class="max-h-[360px] overflow-auto border border-slate-100 rounded-lg bg-slate-50">
            ${rows.length ? rows.map(student => `
              <label class="flex items-start gap-2 px-2 py-1.5 border-b border-slate-100 last:border-b-0">
                <input type="checkbox" data-att-student-id="${student.id}" class="mt-0.5" ${absentSet.has(student.id) ? 'checked' : ''} />
                <span class="text-[12px] text-slate-700">
                  ${_escapeHtml(student.full_name)}
                  ${student.student_code ? `<span class="text-[10px] text-slate-500 ml-1">(${_escapeHtml(student.student_code)})</span>` : ''}
                </span>
              </label>
            `).join('') : '<p class="p-3 text-[12px] text-slate-500">No students found for this class.</p>'}
          </div>
          <p id="attendance-edit-error" class="text-[12px] text-red-600 hidden"></p>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="attendance-edit-cancel" class="btn btn-ghost">Cancel</button>
          <button id="attendance-edit-save" class="btn btn-primary">Save Attendance</button>
        </div>
      </div>
    `;

    const setError = message => {
      const node = overlay.querySelector('#attendance-edit-error');
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
    overlay.querySelector('#attendance-edit-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#attendance-edit-save')?.addEventListener('click', () => {
      if (!rows.length) {
        setError('No students available for attendance update.');
        return;
      }
      const absentIds = Array.from(overlay.querySelectorAll('input[data-att-student-id]:checked'))
        .map(node => Number(node.getAttribute('data-att-student-id') || 0))
        .filter(value => Number.isFinite(value) && value > 0);
      cleanup({
        absent_student_ids: Array.from(new Set(absentIds)).sort((a, b) => a - b),
      });
    });

    document.body.appendChild(overlay);
    overlay.querySelector('input[data-att-student-id]')?.focus();
  });
}

async function _createSessionFromQuickAction({ classId, dayKey, slotIndex, el }) {
  if (_mutationInFlight) {
    showToast('Please wait for the current update to finish.', 'info');
    return;
  }

  let workspace = null;
  try {
    workspace = await api(`/workflow/classes/${classId}`);
  } catch {
    workspace = null;
  }
  const activeUnitId = Number(workspace?.active_unit?.id || 0) || null;
  const activeUnitTitle = String(workspace?.active_unit?.title || '').trim();
  const activeUnitChecklist = Array.isArray(workspace?.active_unit?.checklist) ? workspace.active_unit.checklist : [];
  if (!activeUnitId) {
    showToast('Use "Plan Unit From Doc" first to create an active unit.', 'info');
    return;
  }
  const holidayInfo = _holidayByDate.get(dayKey) || null;
  const payload = await _openCalendarSlotQuickActionModal({
    dayKey,
    slotIndex,
    activeUnitTitle,
    activeChecklist: activeUnitChecklist,
    holidayInfo,
    students: getStudents(),
  });
  if (!payload) return;

  if (_mutationInFlight) {
    showToast('Please wait for the current update to finish.', 'info');
    return;
  }
  _mutationInFlight = true;
  try {
    const sessionPayload = payload.session || {};
    if (!activeUnitId) throw new Error('No active unit found. Start a unit first.');
    const slotResult = await api(`/workflow/classes/${classId}/slot-actions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'continue_unit_session',
        ...sessionPayload,
        allow_on_holiday: Boolean(payload.allow_on_holiday),
        unit_id: activeUnitId,
        absent_student_ids: Array.isArray(payload.absent_student_ids) ? payload.absent_student_ids : [],
        checked_item_ids: Array.isArray(payload.checked_item_ids) ? payload.checked_item_ids : [],
      }),
    });
    const sessionId = Number(slotResult?.session?.id || 0) || null;
    const checkedCount = Array.isArray(payload.checked_item_ids) ? payload.checked_item_ids.length : 0;
    const absentCount = Array.isArray(payload.absent_student_ids) ? payload.absent_student_ids.length : 0;
    const messageParts = [];
    if (checkedCount > 0) messageParts.push(`${checkedCount} checked item${checkedCount === 1 ? '' : 's'}`);
    if (absentCount > 0) messageParts.push(`${absentCount} absent`);
    const successMessage = messageParts.length
      ? `Session added to "${activeUnitTitle || 'active unit'}" (${messageParts.join(', ')}).`
      : `Session added to "${activeUnitTitle || 'active unit'}".`;

    _selectedSessionId = sessionId;
    _selectedSessionError = null;
    _selectedSessionLoading = false;
    if (sessionId) _sessionDetailCache.delete(sessionId);
    await _reloadCalendarData(classId);
    _renderCalendar(el, classId);
    showToast(successMessage, 'ok');
    if (sessionId) await _selectSession(sessionId, el, classId);
  } catch (err) {
    showToast(String(err?.message || 'Failed to create session from calendar slot.'), 'error');
  } finally {
    _mutationInFlight = false;
  }
}

async function _submitPastSession({ classId, el, defaultDateKey }) {
  if (_mutationInFlight) {
    showToast('Please wait for the current update to finish.', 'info');
    return;
  }

  let workspace = null;
  try {
    workspace = await api(`/workflow/classes/${classId}`);
  } catch {
    workspace = null;
  }
  const activeUnitId = Number(workspace?.active_unit?.id || 0) || null;
  const activeUnitTitle = String(workspace?.active_unit?.title || '').trim();
  const activeUnitChecklist = Array.isArray(workspace?.active_unit?.checklist) ? workspace.active_unit.checklist : [];
  if (!activeUnitId) {
    showToast('Start a unit first in Workflow, then submit past sessions.', 'warning');
    return;
  }

  const payload = await _openPastSessionSubmitModal({
    defaultDate: defaultDateKey || _dateKey(new Date()),
    activeUnitTitle,
    activeChecklist: activeUnitChecklist,
    students: getStudents(),
  });
  if (!payload) return;

  const todayKey = _dateKey(new Date());
  if (String(payload.session_date || '').trim() > todayKey) {
    showToast('Past session submit only accepts today or earlier dates.', 'warning');
    return;
  }

  _mutationInFlight = true;
  try {
    const slotResult = await api(`/workflow/classes/${classId}/slot-actions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'continue_unit_session',
        session_date: payload.session_date,
        start_time: payload.start_time,
        end_time: payload.end_time,
        note: payload.note || '',
        allow_on_holiday: Boolean(payload.allow_on_holiday),
        unit_id: activeUnitId,
        absent_student_ids: Array.isArray(payload.absent_student_ids) ? payload.absent_student_ids : [],
        checked_item_ids: Array.isArray(payload.checked_item_ids) ? payload.checked_item_ids : [],
      }),
    });

    const sessionId = Number(slotResult?.session?.id || 0) || null;
    _selectedSessionId = sessionId;
    _selectedSessionError = null;
    _selectedSessionLoading = false;
    if (sessionId) _sessionDetailCache.delete(sessionId);
    await _reloadCalendarData(classId);
    _renderCalendar(el, classId);
    const checkedCount = Array.isArray(payload.checked_item_ids) ? payload.checked_item_ids.length : 0;
    const absentCount = Array.isArray(payload.absent_student_ids) ? payload.absent_student_ids.length : 0;
    showToast(
      (checkedCount > 0 || absentCount > 0)
        ? `Past session saved (${checkedCount} checked, ${absentCount} absent).`
        : 'Past session saved.',
      'ok'
    );
    if (sessionId) await _selectSession(sessionId, el, classId);
  } catch (err) {
    showToast(String(err?.message || 'Failed to submit past session.'), 'error');
  } finally {
    _mutationInFlight = false;
  }
}

async function _moveSessionBlock({ classId, session, targetDayKey, targetSlotIndex, el }) {
  if (!session) return;
  if (_isPastWorkflowSession(session)) {
    showToast('Past workflow sessions are locked for move actions.', 'info');
    return;
  }
  const slot = TIME_SLOTS[targetSlotIndex];
  if (!slot) return;

  const duration = _resolveSessionDurationMinutes(session);
  const startMinutes = slot.start;
  const endMinutes = startMinutes + duration;
  const payload = {
    session_date: targetDayKey,
    start_time: _minutesToPayloadTime(startMinutes),
    end_time: _minutesToPayloadTime(endMinutes),
  };

  if (_mutationInFlight) {
    showToast('Please wait for the current update to finish.', 'info');
    return;
  }
  _mutationInFlight = true;
  try {
    await api(`/sessions/${session.session_id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    _selectedSessionId = Number(session.session_id);
    _selectedSessionError = null;
    _selectedSessionLoading = false;
    _sessionDetailCache.delete(Number(session.session_id));
    await _reloadCalendarData(classId);
    _renderCalendar(el, classId);
    showToast('Session block moved.', 'ok');
    await _selectSession(Number(session.session_id), el, classId);
  } catch (err) {
    showToast(String(err?.message || 'Failed to move session block.'), 'error');
  } finally {
    _mutationInFlight = false;
  }
}

async function _editSessionBlock({ classId, session, el }) {
  if (!session) return;
  if (_isPastWorkflowSession(session)) {
    showToast('Past workflow sessions are locked for time edits.', 'info');
    return;
  }
  const startMinutes = _timeToMinutes(session.start_time);
  const endMinutes = _timeToMinutes(session.end_time);
  const fallbackEnd = _minutesToPayloadTime((startMinutes == null ? 8 * 60 : startMinutes + 60));
  const payload = await _openSessionBlockModal({
    title: 'Edit Session Block',
    dateKey: _dateKey(session.session_date || session.date || ''),
    startTime: session.start_time || '08:00:00',
    endTime: session.end_time || (endMinutes == null ? fallbackEnd : _minutesToPayloadTime(endMinutes)),
    note: String(_sessionDetailCache.get(Number(session.session_id))?.session?.note ?? session.note ?? ''),
  });
  if (!payload) return;

  if (_mutationInFlight) {
    showToast('Please wait for the current update to finish.', 'info');
    return;
  }
  _mutationInFlight = true;
  try {
    await api(`/sessions/${session.session_id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    _selectedSessionId = Number(session.session_id);
    _selectedSessionError = null;
    _selectedSessionLoading = false;
    _sessionDetailCache.delete(Number(session.session_id));
    await _reloadCalendarData(classId);
    _renderCalendar(el, classId);
    showToast('Session block updated.', 'ok');
    await _selectSession(Number(session.session_id), el, classId);
  } catch (err) {
    showToast(String(err?.message || 'Failed to update session block.'), 'error');
  } finally {
    _mutationInFlight = false;
  }
}

export async function renderCalendarView() {
  _showChrome();
  const el = document.getElementById('app-content');
  const classId = getSelectedId();
  const pendingCalendarIntent = _consumeCalendarViewIntent();
  if (pendingCalendarIntent?.session_date) {
    const restoreDate = _dateFromKey(pendingCalendarIntent.session_date) || new Date(`${pendingCalendarIntent.session_date}T00:00:00`);
    if (restoreDate && !Number.isNaN(restoreDate.getTime())) {
      _weekStart = _startOfWeek(restoreDate);
    }
  }
  if (pendingCalendarIntent?.session_id) {
    _selectedSessionId = Number(pendingCalendarIntent.session_id);
    _selectedSessionError = null;
    _selectedSessionLoading = false;
    _calendarPlannedHideDone = Boolean(pendingCalendarIntent.preview_hide_done);
  }

  if (!classId) {
    el.innerHTML = `<div class="view-container">
          <div class="empty-state bg-white rounded-3xl border border-slate-200 py-16">
            <div class="text-5xl opacity-30">CAL</div>
            <h2 class="font-semibold text-slate-500">No class selected</h2>
            <p class="text-[13px] text-slate-400 mt-1">Go to Dashboard to setup class, students, and timetable first.</p>
            <button id="btn-go-dashboard-setup" class="btn btn-primary mt-3">Open Dashboard Setup</button>
          </div></div>`;
    el.querySelector('#btn-go-dashboard-setup')?.addEventListener('click', () => {
      try {
        sessionStorage.setItem('class_init_auto_open', '1');
      } catch {
        // ignore storage errors
      }
      navigate('class');
    });
    return;
  }

  el.innerHTML = `<div class="view-container"><div class="skeleton h-96 rounded-2xl animate-pulse"></div></div>`;
  const initialWeekDays = _buildWeekDays(_weekStart);

  try {
    await Promise.all([
      _reloadCalendarData(classId),
      _loadWeekHolidays(_weekStart),
      _loadClassTimetableRules(classId),
      _loadClassTimetableExceptions(classId, initialWeekDays),
    ]);
  } catch {
    setCalendar([]);
    _holidayByDate = new Map();
    _setClassTimetableRules(classId, []);
    _setClassTimetableExceptions(classId, []);
    mountRetryCard(el, {
      title: 'Calendar Unavailable',
      message: 'Unable to load calendar data right now. Retry after checking API connection.',
      buttonId: 'btn-retry-calendar-load',
      onRetry: () => renderCalendarView(),
    });
    showToast('Failed to load calendar data.', 'error');
    return;
  }

  _renderCalendar(el, classId);
  if (pendingCalendarIntent?.session_id) {
    await _selectSession(Number(pendingCalendarIntent.session_id), el, classId);
  }
}

function _renderCalendar(el, classId) {
  const allEvents = Array.isArray(getCalendar()) ? getCalendar() : [];
  const unitSessionNumbers = _computeUnitSessionNumbers(allEvents);
  const weekDays = _buildWeekDays(_weekStart);
  const weekDayKeys = new Set(weekDays.map(day => day.key));
  const weekEvents = allEvents.filter(row => weekDayKeys.has(_dateKey(row?.session_date || row?.date || null)));
  const weekSchedule = _buildWeekSchedule(weekEvents, weekDays);
  const weekHolidayMap = new Map(
    weekDays
      .map(day => [day.key, _holidayByDate.get(day.key)])
      .filter(([, row]) => Boolean(row))
  );
  const classRules = _getClassTimetableRules(classId);
  const classExceptions = _getClassTimetableExceptions(classId);
  const occupiedStartKeys = _buildSessionStartKeys(weekEvents);
  const plannedSlotsByCell = _buildPlannedSlotsByCell(weekSchedule, weekDays, classRules, classExceptions);
  const plannedSlotCount = Array.from(plannedSlotsByCell.values()).reduce(
    (sum, rows) => sum + (Array.isArray(rows) ? rows.filter(row => !row?.skipped).length : 0),
    0
  );
  const skippedPlannedCount = Array.from(plannedSlotsByCell.values()).reduce(
    (sum, rows) => sum + (Array.isArray(rows) ? rows.filter(row => Boolean(row?.skipped)).length : 0),
    0
  );
  const weekExceptionRows = _buildWeekExceptionRows({
    weekDays,
    rules: classRules,
    exceptions: classExceptions,
    occupiedStartKeys,
  });
  const selectedEvent = _findSelectedEvent(weekEvents);
  const selectedSessionNumber = selectedEvent ? unitSessionNumbers.get(Number(selectedEvent.session_id)) || null : null;
  const selectedDetail = selectedEvent ? _sessionDetailCache.get(Number(selectedEvent.session_id)) : null;
  const selectedBlueprint = selectedDetail?.unit_blueprint && typeof selectedDetail.unit_blueprint === 'object'
    ? selectedDetail.unit_blueprint
    : null;
  const selectedBlueprintError = selectedDetail?.unit_blueprint_error ? String(selectedDetail.unit_blueprint_error) : '';
  const selectedWriteup = selectedDetail?.workflow_writeup && typeof selectedDetail.workflow_writeup === 'object'
    ? selectedDetail.workflow_writeup
    : null;
  const selectedWriteupError = selectedDetail?.workflow_writeup_error ? String(selectedDetail.workflow_writeup_error) : '';
  const activeWorkflowSession = getActiveSession();
  const activeWorkflowSessionId = Number(activeWorkflowSession?.id || activeWorkflowSession?.session_id || 0) || null;
  const selectedSessionId = Number(selectedEvent?.session_id || 0) || null;
  const selectedMatchesActiveWorkflow = Boolean(activeWorkflowSessionId && selectedSessionId && activeWorkflowSessionId === selectedSessionId);
  const hasOtherActiveWorkflowSession = Boolean(activeWorkflowSessionId && selectedSessionId && activeWorkflowSessionId !== selectedSessionId);
  const canShortcutToWorkflowTools = selectedEvent?.unit_id != null;
  const selectedBlueprintTree = selectedBlueprint?.blueprint_json && typeof selectedBlueprint.blueprint_json === 'object' && Array.isArray(selectedBlueprint.blueprint_json.items)
    ? selectedBlueprint.blueprint_json.items
    : [];
  const plannedSessionTree = selectedSessionNumber ? _collectSessionBlueprintNodes(selectedBlueprintTree, selectedSessionNumber) : [];
  const plannedSessionTitles = _flattenCalendarBlueprintTitles(plannedSessionTree, []);
  const plannedSessionSummary = _buildCalendarPlannedSessionSummary(plannedSessionTree);
  const plannedSessionFlat = _flattenCalendarBlueprintNodes(plannedSessionTree, []);
  const plannedSessionDoneCount = plannedSessionFlat.filter(node => Boolean(node?.is_completed)).length;
  const plannedSessionRemainingCount = Math.max(0, plannedSessionFlat.length - plannedSessionDoneCount);
  const plannedSessionCoveragePct = plannedSessionFlat.length ? Math.round((plannedSessionDoneCount / plannedSessionFlat.length) * 100) : 0;
  const plannedResumeNodeId = Number(plannedSessionFlat.find(node => !Boolean(node?.is_completed))?.id || 0) || null;
  const plannedResumeNode = plannedResumeNodeId != null
    ? plannedSessionFlat.find(node => Number(node?.id || 0) === plannedResumeNodeId) || null
    : null;
  const plannedSessionStatus = !plannedSessionFlat.length
    ? { label: 'No route saved', className: 'badge-gray', hint: 'No planned checklist route is saved for this session yet.' }
    : plannedSessionDoneCount === 0
      ? { label: 'Not started', className: 'badge-blue', hint: 'This planned route has not been covered yet.' }
      : plannedSessionRemainingCount === 0
        ? { label: 'Fully covered', className: 'badge-green', hint: 'All planned rows for this session are already completed.' }
        : { label: 'Partly covered', className: 'badge-amber', hint: `${plannedSessionRemainingCount} planned row${plannedSessionRemainingCount === 1 ? '' : 's'} still remain.` };
  const visiblePlannedSessionTree = _filterCalendarBlueprintTree(plannedSessionTree, { hideDone: _calendarPlannedHideDone });
  const selectedUnitMap = selectedBlueprint?.unit_map_json && typeof selectedBlueprint.unit_map_json === 'object'
    ? selectedBlueprint.unit_map_json
    : {};
  const selectedSectionPlans = Array.isArray(selectedUnitMap?.section_plans) ? selectedUnitMap.section_plans : [];
  const selectedMatchedGuidance = selectedEvent?.unit_id != null
    ? _filterCalendarAssistantArtifactsForPlannedTitles(_calendarAssistantArtifactCache.get(`${Number(classId || 0)}:${Number(selectedEvent.unit_id || 0)}`) || [], selectedUnitMap, plannedSessionTitles)
    : [];
  const selectedImportedGuidanceIds = _getCalendarImportedAssistantArtifactIds(selectedWriteup);
  const selectedRemainingGuidance = selectedMatchedGuidance.filter(item => !selectedImportedGuidanceIds.has(Number(item?.id || 0)));
  const selectedRemainingGuidanceCount = selectedRemainingGuidance.length;
  const selectedBestRemainingGuidance = selectedRemainingGuidanceCount === 1 ? selectedRemainingGuidance[0] : null;
  const plannedResumeSectionPlan = plannedResumeNode ? _findCalendarSectionPlanForTitle(selectedSectionPlans, plannedResumeNode.title) : null;
  const plannedResumePlaybookEntry = _findCalendarTeacherPlaybookEntry(selectedUnitMap, plannedResumeSectionPlan, plannedResumeNode?.title || '');
  const studentsById = new Map((getStudents() || []).map(student => [Number(student.id), student]));
  const absentRows = selectedEvent ? _absentRowsFromDetail(selectedDetail, selectedEvent, studentsById) : [];
  const headlineBlocks = selectedEvent ? _headlineBlocksFromDetail(selectedDetail, selectedEvent) : [];
  const todayKey = _dateKey(new Date());
  const selectedDateKey = selectedEvent ? _dateKey(selectedEvent.session_date || selectedEvent.date) : '';
  const selectedIsFuture = Boolean(selectedDateKey) && selectedDateKey > todayKey;
  const selectedIsPastWorkflowLocked = Boolean(selectedEvent) && _isPastWorkflowSession(selectedEvent, todayKey);
  const selectedCanConfirm = Boolean(selectedEvent && selectedEvent.unit_id != null && !selectedIsFuture);
  const selectedCanEdit = Boolean(selectedEvent) && !selectedIsPastWorkflowLocked;
  const selectedCanAttendanceEdit = Boolean(selectedEvent) && !selectedIsFuture;
  const selectedConfirmLabel = selectedIsFuture ? 'Future Session' : 'Confirm Session';
  const selectedSessionStateLabel = selectedEvent
    ? selectedIsFuture
      ? 'Upcoming'
      : selectedWriteup
        ? (selectedWriteup.approved === false ? 'Awaiting review' : 'Completed')
        : selectedEvent.unit_id != null
          ? 'Ready to confirm'
          : 'Standalone session'
    : '';
  const selectedSessionStateClass = selectedEvent
    ? selectedIsFuture
      ? 'badge-blue'
      : selectedWriteup
        ? (selectedWriteup.approved === false ? 'badge-amber' : 'badge-green')
        : selectedEvent.unit_id != null
          ? 'badge-amber'
          : 'badge-gray'
    : 'badge-gray';
  const selectedNextStepText = selectedEvent
    ? selectedIsFuture
      ? 'Review the planned teaching flow and prep suggestions before class.'
      : selectedWriteup
        ? (selectedWriteup.approved === false
          ? 'Review the generated write-up, then approve it when it reflects what happened in class.'
          : 'This session is documented. You can still review the write-up or reopen Workflow for unit context.')
        : selectedEvent.unit_id != null
          ? 'Confirm the delivered session to auto-check the checklist and generate the textbook write-up.'
          : 'This session stands outside the workflow unit system, so only note and attendance are tracked here.'
    : '';
  const selectedConfirmTitle = selectedEvent
    ? (selectedCanConfirm
      ? 'Confirm this delivered session and auto-check checklist flow.'
      : (selectedEvent.unit_id == null ? 'Only workflow unit sessions can be confirmed.' : 'Future sessions can be confirmed only on/after the session date.'))
    : '';
  const selectedEditTitle = selectedCanEdit
    ? 'Edit session date/time and note.'
    : 'Past workflow sessions are locked for date/time edits.';
  const selectedAttendanceTitle = selectedCanAttendanceEdit
    ? 'Update absent/present students for this session.'
    : 'Future sessions cannot take attendance yet.';

  const weekStartKey = weekDays[0]?.key || _dateKey(_weekStart);
  const weekEndKey = weekDays[6]?.key || weekStartKey;
  const weekNumber = _isoWeekNumber(_weekStart);
  const weekMonthLabel = weekDays[0]?.date?.toLocaleDateString('fr-MA', { month: 'long', year: 'numeric' }) || '';
  const outsideHoursCount = weekSchedule.reduce((sum, day) => sum + day.outsideHours.length, 0);
  const outsideHoursRows = weekSchedule.flatMap(day => (day.outsideHours || []).map(session => ({
    dayKey: day.key,
    session,
  })));
  const isBlockedHolidayDay = dayKey => Boolean(weekHolidayMap.get(dayKey)?.is_blocked);

  el.innerHTML = `
    <div class="view-container">
      <div class="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 class="text-2xl font-bold text-slate-800 tracking-tight">Weekly Calendar</h1>
          <p class="text-[13px] text-slate-400 mt-0.5">Plan sessions from a document, submit past sessions quickly, and confirm delivered sessions.</p>
        </div>
        <div class="flex items-center gap-2 flex-wrap">
          ${plannedSlotCount > 0 ? `<span class="badge badge-gray">${plannedSlotCount} planned slot${plannedSlotCount !== 1 ? 's' : ''}</span>` : ''}
          ${skippedPlannedCount > 0 ? `<span class="badge badge-amber">${skippedPlannedCount} skipped</span>` : ''}
          <button id="btn-plan-from-doc" class="btn btn-primary !font-semibold" title="Upload a unit document and auto-plan sessions">Plan Unit From Doc</button>
          <button id="btn-submit-past-session" class="btn btn-secondary" title="Quickly record a delivered past session">Submit Past Session</button>
          <button id="btn-export-cal" class="btn btn-ghost btn-sm" title="Export full academic-year calendar as a polished PDF summary">Export PDF</button>
        </div>
      </div>

      <div class="card overflow-hidden">
        <div class="flex items-center justify-between px-5 py-4 border-b border-slate-100 flex-wrap gap-2">
          <div class="cal-week-nav w-full sm:w-auto justify-between sm:justify-start">
            <button id="btn-prev-week" class="btn btn-ghost btn-sm" title="Previous Week">Prev</button>
            <div class="week-label ${weekStartKey === _dateKey(_startOfWeek(new Date())) ? 'is-current-week' : ''}">
              <span class="block text-[10px] uppercase tracking-wide opacity-70">Week ${weekNumber}${weekMonthLabel ? ` â€¢ ${_escapeHtml(weekMonthLabel)}` : ''}</span>
              <span>${fmtDate(weekStartKey)} - ${fmtDate(weekEndKey)}</span>
            </div>
            <button id="btn-next-week" class="btn btn-ghost btn-sm" title="Next Week">Next</button>
          </div>
          <div class="flex items-center gap-2">
            <button id="btn-this-week" class="btn-today ml-2">Today</button>
          </div>
        </div>

        <div class="weekly-grid-wrap">
          <div class="weekly-grid">
            <div class="cal-time-axis flex items-end justify-end pb-1 pr-2">Time</div>
            ${weekSchedule.map(day => `
              <div class="cal-day-header ${day.key === _dateKey(new Date()) ? 'is-today' : ''} ${weekHolidayMap.get(day.key)?.is_blocked ? 'is-holiday' : ''} flex flex-col justify-end pb-1">
                <span class="text-[11px] font-bold uppercase tracking-wider">${day.label}</span>
                <span class="text-[14px] font-semibold">${day.shortDate}</span>
                ${weekHolidayMap.get(day.key)
      ? `<span class="text-[10px] mt-0.5 truncate max-w-[110px] ${weekHolidayMap.get(day.key)?.is_blocked ? 'text-rose-700 font-semibold' : 'text-slate-500'}" title="${_escapeHtml(weekHolidayMap.get(day.key)?.name || '')}">${_escapeHtml(weekHolidayMap.get(day.key)?.name || 'Holiday')}</span>`
      : ''}
              </div>
            `).join('')}

            ${TIME_SLOTS.map((slot, slotIndex) => `
              <div class="week-time-cell cal-time-axis flex items-start justify-end pr-2 pt-1 font-normal opacity-50">${slot.label.split(' - ')[0]}</div>
              ${weekSchedule.map(day => {
    const rows = day.slots.get(slot.key) || [];
    const plannedRows = plannedSlotsByCell.get(`${day.key}|${slot.key}`) || [];
    const holidayInfo = weekHolidayMap.get(day.key) || null;
    const isBlockedHoliday = Boolean(holidayInfo?.is_blocked);
    const maxVisible = window.innerWidth < 640 ? 1 : 2;
    const visibleRows = rows.slice(0, maxVisible);
    const remainingCapacity = Math.max(0, maxVisible - visibleRows.length);
    const visiblePlannedRows = plannedRows.slice(0, remainingCapacity);
    const overflowCount = (rows.length + plannedRows.length) - (visibleRows.length + visiblePlannedRows.length);
    return `
                <div class="cal-slot week-slot-cell p-1 flex flex-col gap-1 ${isBlockedHoliday ? 'is-holiday-blocked' : ''}"
                     data-slot-day="${day.key}"
                     data-slot-index="${slotIndex}">
                  <button class="btn-slot-plus ${isBlockedHoliday ? 'is-disabled' : ''}"
                          data-slot-plus-day="${day.key}"
                          data-slot-plus-index="${slotIndex}"
                          aria-label="${_escapeHtml(`Add session on ${fmtDate(day.key)} at ${slot.label}`)}"
                          title="${isBlockedHoliday ? _escapeHtml(`Blocked holiday: ${holidayInfo?.name || 'Holiday'} (click for override)`) : 'Slot actions'}">+</button>
                  ${isBlockedHoliday ? `<div class="cal-holiday-chip" title="${_escapeHtml(holidayInfo?.name || 'Holiday')}">${_escapeHtml(holidayInfo?.name || 'Holiday')}</div>` : ''}
                  ${visibleRows.map(session => {
      const isSelected = Number(session.session_id) === Number(_selectedSessionId);
      const isGeneric = session.unit_id == null;
      const isPastWorkflowLocked = _isPastWorkflowSession(session, todayKey);
      const canMoveOrResize = !isPastWorkflowLocked;
      const unitSessionNumber = isGeneric ? null : unitSessionNumbers.get(Number(session.session_id)) || null;
      const chipTime = session.end_time
        ? `${fmtTime(session.start_time).slice(0, 5)}-${fmtTime(session.end_time).slice(0, 5)}`
        : fmtTime(session.start_time).slice(0, 5);
      const chipTitle = isPastWorkflowLocked
        ? `${session.unit_title || 'Session'} (locked: past workflow session)`
        : (session.unit_title || 'Session');
      return `
                    <div class="cal-chip group relative flex flex-col items-start gap-1 w-full text-left rounded-xl transition-all hover:scale-[1.02] shadow-sm ${isSelected ? 'chip-selected ring-2 ring-blue-500 ring-offset-1' : ''} ${isGeneric ? 'chip-generic' : 'chip-workflow'}"
                            data-session-id="${session.session_id}"
                            data-session-day="${day.key}"
                            data-session-slot-index="${slotIndex}"
                            data-session-locked="${isPastWorkflowLocked ? '1' : '0'}"
                            role="button"
                            tabindex="0"
                            aria-label="${_escapeHtml(`Open session ${session.unit_title || 'Session'} on ${fmtDate(day.key)} at ${fmtTime(session.start_time)}`)}"
                            draggable="${canMoveOrResize ? 'true' : 'false'}"
                            title="${_escapeHtml(chipTitle)}">
                      <div class="pointer-events-none w-full flex flex-col text-left gap-0.5 overflow-hidden">
                        <div class="flex items-center justify-between gap-1 w-full">
                          <span class="opacity-75 text-[9px] uppercase font-bold tracking-widest whitespace-nowrap" data-time-label="true">${chipTime}</span>
                          ${isGeneric ? '' : `<span class="text-[9px]">${unitSessionNumber ? `S${unitSessionNumber}` : 'WF'}</span>`}
                        </div>
                        <span class="truncate w-full font-bold text-[12px] leading-tight">${_escapeHtml(session.unit_title || 'Session')}</span>
                      </div>
                      <div class="absolute bottom-0 left-0 w-full h-[8px] cursor-ns-resize opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity z-10 ${canMoveOrResize ? '' : 'hidden'}" data-resize-handle="true">
                        <div class="w-6 h-[3px] bg-slate-400/60 rounded-full"></div>
                      </div>
                    </div>
                  `;
    }).join('')}
                  ${visiblePlannedRows.map(rule => {
      const startText = rule.end_time
        ? `${fmtTime(rule.start_time).slice(0, 5)}-${fmtTime(rule.end_time).slice(0, 5)}`
        : fmtTime(rule.start_time).slice(0, 5);
      const title = rule.subject || 'Planned session';
      const metaParts = [rule.room, rule.group].filter(Boolean);
      const metaText = metaParts.join(' â€¢ ');
      const isSkipped = Boolean(rule?.skipped);
      const isMoved = Boolean(rule?.moved);
      const exceptionType = String(rule?.exception_type || '').toLowerCase();
      const skipTitle = isSkipped
        ? `${exceptionType === 'move' ? 'Moved planned slot' : 'Skipped planned slot'}${rule?.exception_note ? `: ${rule.exception_note}` : ''}`
        : (isMoved
          ? `Moved planned slot${rule?.moved_from_date ? ` from ${fmtDate(rule.moved_from_date)}` : ''}`
          : `Planned: ${title}${metaText ? ` (${metaText})` : ''}`);
      const canOpenQuickAction = !isSkipped;
      return `
                    <div class="cal-planned-chip ${isSkipped ? 'is-skipped' : ''} ${isMoved ? 'is-moved' : ''}" title="${_escapeHtml(skipTitle)}">
                      <button class="cal-planned-chip-main"
                              type="button"
                              data-slot-plus-day="${day.key}"
                              data-slot-plus-index="${slotIndex}"
                              ${canOpenQuickAction ? '' : 'disabled'}>
                        <span class="cal-planned-chip-time">${_escapeHtml(startText)}</span>
                        <span class="cal-planned-chip-title">${_escapeHtml(title)}</span>
                        ${metaText ? `<span class="cal-planned-chip-meta">${_escapeHtml(metaText)}</span>` : ''}
                        ${isMoved && rule?.moved_from_date ? `<span class="cal-planned-chip-meta">Moved from ${_escapeHtml(fmtDate(rule.moved_from_date))}</span>` : ''}
                      </button>
                      <span class="text-[10px] text-slate-500 mt-1">${isSkipped ? 'Skipped by calendar rules' : 'Planned from timetable'}</span>
                    </div>
                  `;
    }).join('')}
                  ${overflowCount > 0 ? `<div class="cal-slot-overflow text-center">+${overflowCount} more</div>` : ''}
                </div>
              `;
  }).join('')}
            `).join('')}
          </div>
        </div>

        ${outsideHoursCount > 0 ? `
        <div class="px-5 py-3 border-t border-slate-100 bg-slate-50">
          <p class="text-[12px] text-slate-500">
            ${outsideHoursCount} session${outsideHoursCount !== 1 ? 's are' : ' is'} outside visible grid hours and listed below.
          </p>
          <div class="mt-2 flex flex-wrap gap-2">
            ${outsideHoursRows.map(({ dayKey, session }) => {
      const sessionId = Number(session?.session_id || 0);
      const isSelected = sessionId > 0 && Number(_selectedSessionId) === sessionId;
      const sessionLabel = `${fmtDate(dayKey)} ${fmtTime(session?.start_time)}`;
      const title = _escapeHtml(String(session?.unit_title || 'Session'));
      return `
                <button type="button"
                      class="btn btn-ghost btn-sm ${isSelected ? 'ring-2 ring-blue-500 ring-offset-1' : ''} cal-outside-session"
                      data-session-id="${sessionId}">
                ${_escapeHtml(sessionLabel)} | ${title}
              </button>
            `;
    }).join('')}
          </div>
        </div>` : ''}
      </div>

      <div class="card p-4 mt-4">
        <h3 class="text-[13px] font-semibold text-slate-700">Planning Summary</h3>
        <p class="text-[12px] text-slate-500 mt-2">
          ${plannedSlotCount} planned slot${plannedSlotCount !== 1 ? 's' : ''} in this week.
          ${weekExceptionRows.length > 0 ? `${weekExceptionRows.length} timetable change${weekExceptionRows.length !== 1 ? 's' : ''} applied in background.` : 'No timetable changes this week.'}
        </p>
      </div>

      ${selectedEvent ? `
      <div class="cal-detail-panel mt-4 mb-6 mx-5">
        <div class="flex items-center justify-between border-b border-slate-100 pb-3 mb-4">
          <div>
            <h3 class="detail-title mb-0">
              Session ${fmtDate(selectedEvent.session_date || selectedEvent.date)}${selectedSessionNumber ? ` â€¢ Unit Session ${selectedSessionNumber}` : ''}
            </h3>
            <p class="detail-meta mb-0 mt-0.5">${fmtTime(selectedEvent.start_time)}${selectedEvent.end_time ? ` -> ${fmtTime(selectedEvent.end_time)}` : ''}</p>
          </div>
          <div class="flex items-center gap-2">
            <button id="btn-confirm-selected-session" class="btn btn-success btn-sm" ${selectedCanConfirm ? '' : 'disabled'} title="${_escapeHtml(selectedConfirmTitle)}">${_escapeHtml(selectedConfirmLabel)}</button>
            <button id="btn-edit-selected-session" class="btn btn-ghost btn-sm" ${selectedCanEdit ? '' : 'disabled'} title="${_escapeHtml(selectedEditTitle)}">Edit</button>
            ${selectedMatchesActiveWorkflow
              ? '<button id="btn-open-selected-workflow" class="btn btn-ghost btn-sm">Resume Live Session</button>'
              : selectedEvent.unit_id != null
                ? '<button id="btn-open-selected-workflow" class="btn btn-ghost btn-sm">Open Workflow</button>'
                : ''}
            <button id="btn-close-selected-session" class="btn btn-ghost btn-sm text-slate-400">Close</button>
          </div>
        </div>
        <div class="flex flex-col gap-4">
          <div class="p-3 rounded-xl border border-slate-200 bg-slate-50">
            <p class="text-[13px] font-semibold text-slate-700">${_escapeHtml(selectedEvent.unit_title || 'Session')}</p>
            <div class="flex gap-2 mt-2 flex-wrap">
              <span class="badge ${selectedSessionStateClass}">${_escapeHtml(selectedSessionStateLabel)}</span>
              <span class="badge badge-green">${selectedEvent.checked_items_count ?? 0} items done</span>
              <span class="badge badge-red">${selectedEvent.absent_count ?? 0} absent</span>
              ${selectedMatchesActiveWorkflow ? '<span class="badge badge-amber">Live in Workflow</span>' : ''}
            </div>
            ${selectedNextStepText ? `<p class="text-[12px] text-slate-500 mt-2">${_escapeHtml(selectedNextStepText)}</p>` : ''}
            ${hasOtherActiveWorkflowSession ? `
              <div class="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
                <p class="text-[12px] font-semibold text-amber-800">Another workflow session is currently active</p>
                <p class="text-[12px] text-amber-700 mt-1">
                  ${_escapeHtml(String(activeWorkflowSession?.unit_title || 'Active unit session'))}
                  ${activeWorkflowSession?.unit_session_number ? ` • Unit Session ${Number(activeWorkflowSession.unit_session_number)}` : ''}
                </p>
                <div class="mt-3 flex gap-2 flex-wrap">
                  <button id="btn-open-active-workflow-session" class="btn btn-secondary btn-sm">Resume Active Session</button>
                </div>
              </div>` : ''}
          </div>

          <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div class="p-3 rounded-xl border border-slate-200">
              <div class="flex items-center justify-between gap-2">
                <h4 class="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">Absent Students</h4>
                <button id="btn-edit-selected-attendance" class="btn btn-ghost btn-sm" ${selectedCanAttendanceEdit ? '' : 'disabled'} title="${_escapeHtml(selectedAttendanceTitle)}">Edit Attendance</button>
              </div>
              ${_selectedSessionLoading
        ? '<p class="text-[12px] text-slate-500 mt-2">Loading session attendance...</p>'
        : _selectedSessionError
          ? `<div class="mt-2 flex flex-col gap-2">
               <p class="text-[12px] text-red-600">${_escapeHtml(_selectedSessionError)}</p>
               <button id="btn-retry-session-detail" class="btn btn-ghost btn-sm self-start">Retry details</button>
             </div>`
          : absentRows.length
            ? `<div class="mt-2 flex flex-col gap-1">
                    ${absentRows.map(row => `
                    <div class="text-[13px] text-slate-700">
                      ${_escapeHtml(row.name)}
                      ${row.code ? `<span class="text-[11px] text-slate-400">(${_escapeHtml(row.code)})</span>` : ''}
                    </div>`).join('')}
                 </div>`
            : '<p class="text-[12px] text-slate-500 mt-2">No absent students for this session.</p>'}
            </div>

            <div class="p-3 rounded-xl border border-slate-200">
              <h4 class="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">Headlines Structure</h4>
              ${_selectedSessionLoading
        ? '<p class="text-[12px] text-slate-500 mt-2">Loading session progress...</p>'
        : _selectedSessionError
          ? '<p class="text-[12px] text-slate-500 mt-2">Unable to load detailed progress. Showing available calendar data only.</p>'
          : ''}
              ${headlineBlocks.length
        ? `<div class="mt-2 flex flex-col gap-2">
                   ${headlineBlocks.map(block => `
                   <div>
                     <p class="text-[12px] font-semibold text-slate-600">${_escapeHtml(block.label)}</p>
                     <ul class="mt-1 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
                       ${block.items.map(item => `<li>${_escapeHtml(item)}</li>`).join('')}
                     </ul>
                   </div>`).join('')}
                 </div>`
        : '<p class="text-[12px] text-slate-500 mt-2">No headlines recorded for this session.</p>'}
            </div>
          </div>

          <div class="p-3 rounded-xl border border-slate-200">
            <h4 class="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">Note</h4>
            ${String(selectedDetail?.session?.note || selectedEvent.note || '').trim()
        ? `<p class="mt-2 text-[13px] text-slate-700 whitespace-pre-wrap">${_escapeHtml(String(selectedDetail?.session?.note || selectedEvent.note || '').trim())}</p>`
        : '<p class="text-[12px] text-slate-500 mt-2">No note for this session.</p>'}
          </div>

          <div class="p-3 rounded-xl border border-slate-200">
            <div class="flex items-center justify-between gap-2 flex-wrap">
              <h4 class="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">Planned Teaching Flow</h4>
              ${plannedSessionDoneCount > 0
                ? `<button id="btn-calendar-planned-hide-done-toggle" class="btn btn-ghost btn-sm !text-amber-700">${_calendarPlannedHideDone ? 'Show Completed Rows' : 'Hide Completed Rows'}</button>`
                : ''}
            </div>
            ${_selectedSessionLoading
              ? '<p class="text-[12px] text-slate-500 mt-2">Loading planned unit flow...</p>'
              : selectedEvent.unit_id == null
                ? '<p class="text-[12px] text-slate-500 mt-2">This session is not linked to a workflow unit.</p>'
                : selectedBlueprintError
                  ? `<p class="text-[12px] text-slate-500 mt-2">${_escapeHtml(selectedBlueprintError)}</p>`
                : !selectedSessionNumber
                  ? '<p class="text-[12px] text-slate-500 mt-2">This workflow session has no saved unit-session number yet.</p>'
                    : `
                      <div class="mt-2 flex flex-col gap-3">
                        <p class="text-[12px] text-slate-500">Planned checklist path for unit session ${Number(selectedSessionNumber)}.</p>
                        <div class="flex items-center gap-2 flex-wrap">
                          <span class="badge ${plannedSessionStatus.className}">${_escapeHtml(plannedSessionStatus.label)}</span>
                          ${plannedSessionFlat.length ? `<span class="text-[11px] text-slate-500">${_escapeHtml(plannedSessionStatus.hint)}</span>` : ''}
                        </div>
                        ${plannedSessionSummary.length ? `
                          <div class="flex flex-wrap gap-2">
                            ${plannedSessionSummary.map(label => `<span class="badge badge-gray">${_escapeHtml(label)}</span>`).join('')}
                          </div>` : ''}
                        ${plannedResumeNodeId != null ? '<p class="text-[11px] text-amber-700">The first unfinished planned row is marked below as <span class="font-semibold">Resume here</span>.</p>' : ''}
                        ${_calendarPlannedHideDone && plannedSessionDoneCount > 0 ? '<p class="text-[11px] text-amber-700">Showing only remaining planned rows.</p>' : ''}
                        ${_calendarPlannedHideDone && plannedSessionDoneCount > 0 && !visiblePlannedSessionTree.length
                          ? '<div class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-800">All planned rows for this session are already completed. Use <span class="font-semibold">Show Completed Rows</span> if you want to review them.</div>'
                          : ''}
                        ${_renderCalendarBlueprintTree(visiblePlannedSessionTree, 0, { resumeNodeId: plannedResumeNodeId })}
                        ${plannedResumeNode ? _renderCalendarNextFocusActions(plannedResumeSectionPlan, plannedResumePlaybookEntry, plannedResumeNode.title, { classId, unitId: selectedEvent?.unit_id }) : ''}
                        <div>
                          <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Matched Section Plans</p>
                          ${_renderCalendarSectionPlans(selectedSectionPlans, plannedSessionTitles)}
                        </div>
                      </div>`}
          </div>

          <div class="p-3 rounded-xl border border-slate-200">
            <div class="flex items-center justify-between gap-2 flex-wrap">
              <h4 class="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">Teacher Prep Suggestions</h4>
              ${canShortcutToWorkflowTools
                ? `<div class="flex items-center gap-2 flex-wrap">
                    <button id="btn-open-selected-unit-assistant" class="btn btn-ghost btn-sm">Ask This Unit</button>
                    <button id="btn-open-selected-material-studio" class="btn btn-ghost btn-sm">Material Studio</button>
                    <button id="btn-open-selected-ai-details" class="btn btn-ghost btn-sm">AI Details</button>
                  </div>`
                : ''}
            </div>
            ${_selectedSessionLoading
              ? '<p class="text-[12px] text-slate-500 mt-2">Loading prep suggestions...</p>'
              : selectedEvent.unit_id == null
                ? '<p class="text-[12px] text-slate-500 mt-2">This session is not linked to a workflow unit.</p>'
                : selectedBlueprintError
                  ? `<p class="text-[12px] text-slate-500 mt-2">${_escapeHtml(selectedBlueprintError)}</p>`
                  : _renderCalendarTeacherPrep(selectedUnitMap, plannedSessionTitles)}
          </div>

          <div class="p-3 rounded-xl border border-slate-200">
            <div class="flex items-center justify-between gap-2 flex-wrap">
              <h4 class="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">Textbook Write-Up</h4>
              <div class="flex items-center gap-2 flex-wrap">
                ${selectedWriteup
                  ? `<span class="badge ${selectedWriteup.approved === false ? 'badge-amber' : 'badge-green'}">${selectedWriteup.approved === false ? 'Draft' : 'Approved'}</span>`
                  : ''}
                ${selectedWriteup
                  ? `<button id="btn-copy-selected-writeup" class="btn btn-ghost btn-sm">Copy</button>`
                  : ''}
                ${selectedWriteup
                  ? `<button id="btn-download-selected-writeup" class="btn btn-ghost btn-sm">Download</button>`
                  : ''}
                ${selectedEvent.unit_id != null && !selectedIsFuture
                  ? `<button id="btn-generate-selected-writeup" class="btn btn-ghost btn-sm">${selectedWriteup ? 'Re-generate' : 'Generate'}</button>`
                  : ''}
                ${selectedWriteup
                  ? `<button id="btn-edit-selected-writeup" class="btn btn-ghost btn-sm">Edit</button>`
                  : ''}
                ${selectedEvent.unit_id != null && !selectedIsFuture
                  ? `<button id="btn-import-selected-guidance" class="btn btn-ghost btn-sm">Use Saved Guidance</button>`
                  : ''}
                ${selectedWriteup
                  ? `<button id="btn-toggle-selected-writeup-approval" class="btn btn-ghost btn-sm">${selectedWriteup.approved === false ? 'Approve' : 'Mark Draft'}</button>`
                  : ''}
              </div>
            </div>
            <div class="rounded-xl border border-slate-200 bg-slate-50 p-3 mt-2">
              <div class="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <p class="text-[12px] font-semibold text-slate-700">Saved Guidance For This Session</p>
                  <p class="text-[12px] text-slate-500 mt-1">Reusable unit help that matches this planned session route.</p>
                  ${_renderCalendarSessionGuidanceSummary(selectedMatchedGuidance.length, selectedImportedGuidanceIds.size, _calendarSessionGuidanceHideImported)}
                </div>
                ${selectedImportedGuidanceIds.size > 0
                  ? `<button id="btn-calendar-session-guidance-hide-imported-toggle" class="btn btn-ghost btn-sm">${_calendarSessionGuidanceHideImported ? 'Show Imported' : 'Hide Imported'}</button>`
                  : ''}
              </div>
              <div class="mt-3">
                ${_renderCalendarSessionMatchedGuidance(selectedMatchedGuidance, {
                  canImport: selectedEvent.unit_id != null && !selectedIsFuture,
                  importedIds: selectedImportedGuidanceIds,
                  hideImported: _calendarSessionGuidanceHideImported,
                })}
              </div>
            </div>
            ${_renderCalendarWriteupNextStep(selectedWriteup, {
              isFuture: selectedIsFuture,
              hasUnit: selectedEvent.unit_id != null,
              remainingGuidanceCount: selectedRemainingGuidanceCount,
              bestRemainingGuidanceTitle: String(selectedBestRemainingGuidance?.title || '').trim(),
              quickGuidanceItems: selectedRemainingGuidance,
            })}
            ${_selectedSessionLoading
              ? '<p class="text-[12px] text-slate-500 mt-2">Loading workflow write-up...</p>'
              : selectedWriteup
                ? `
                  <div class="mt-2 flex flex-col gap-3">
                    <p class="text-[13px] font-semibold text-slate-700">${_escapeHtml(selectedWriteup.title || 'Session write-up')}</p>
                    ${_renderCalendarImportedGuidanceSummary(selectedWriteup.source_payload)}
                    ${Array.isArray(selectedWriteup.learning_focus) && selectedWriteup.learning_focus.length ? `
                      <div>
                        <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Learning Focus</p>
                        <ul class="mt-1 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
                          ${selectedWriteup.learning_focus.map(row => `<li>${_escapeHtml(row)}</li>`).join('')}
                        </ul>
                      </div>` : ''}
                    ${Array.isArray(selectedWriteup.teaching_content) && selectedWriteup.teaching_content.length ? `
                      <div class="flex flex-col gap-2">
                        <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Teaching Content</p>
                        ${selectedWriteup.teaching_content.map(row => `<p class="text-[13px] text-slate-700 leading-relaxed">${_escapeHtml(row)}</p>`).join('')}
                      </div>` : ''}
                    ${Array.isArray(selectedWriteup.practice_items) && selectedWriteup.practice_items.length ? `
                      <div>
                        <p class="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Practice</p>
                        <ul class="mt-1 pl-4 list-disc text-[12px] text-slate-600 leading-relaxed">
                          ${selectedWriteup.practice_items.map(row => `<li>${_escapeHtml(row)}</li>`).join('')}
                        </ul>
                      </div>` : ''}
                    ${_renderCalendarWriteupSourcePayload(selectedWriteup.source_payload)}
                  </div>`
                : selectedWriteupError
                  ? `<p class="text-[12px] text-slate-500 mt-2">${_escapeHtml(selectedWriteupError)}</p>`
                  : selectedEvent.unit_id == null
                    ? '<p class="text-[12px] text-slate-500 mt-2">This session is not linked to a workflow unit.</p>'
                    : '<p class="text-[12px] text-slate-500 mt-2">No saved textbook write-up for this session yet.</p>'}
          </div>
        </div>
      </div>` : `
      <div class="card p-5">
        <p class="text-[13px] text-slate-500">Click a session block in the weekly timetable to view absences, structured headlines, and note.</p>
      </div>`}
    </div>`;

  const slotCells = Array.from(el.querySelectorAll('.week-slot-cell[data-slot-day][data-slot-index]'));

  el.querySelectorAll('.btn-slot-plus[data-slot-plus-day][data-slot-plus-index], .cal-planned-chip-main[data-slot-plus-day][data-slot-plus-index]').forEach(btn => {
    btn.addEventListener('click', async event => {
      event.preventDefault();
      event.stopPropagation();
      const dayKey = String(btn.dataset.slotPlusDay || '').trim();
      const slotIndex = Number(btn.dataset.slotPlusIndex);
      if (!dayKey || !Number.isFinite(slotIndex)) return;
      await _createSessionFromQuickAction({
        classId,
        dayKey,
        slotIndex,
        el,
      });
    });
  });

  const moveDragState = {
    sessionId: null,
    sourceDayKey: null,
    sourceSlotIndex: null,
    targetDayKey: null,
    targetSlotIndex: null,
    didDrop: false,
    ghostEl: null,
  };

  const clearDropTargets = () => {
    slotCells.forEach(cell => cell.classList.remove('drag-target-active'));
  };

  slotCells.forEach(cell => {
    cell.addEventListener('dragover', event => {
      if (!moveDragState.sessionId) return;
      const dayKey = String(cell.dataset.slotDay || '').trim();
      if (isBlockedHolidayDay(dayKey)) {
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'none';
        return;
      }
      event.preventDefault();
      moveDragState.targetDayKey = dayKey;
      moveDragState.targetSlotIndex = Number(cell.dataset.slotIndex);
      clearDropTargets();
      cell.classList.add('drag-target-active');
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    });

    cell.addEventListener('drop', event => {
      if (!moveDragState.sessionId) return;
      const dayKey = String(cell.dataset.slotDay || '').trim();
      if (isBlockedHolidayDay(dayKey)) {
        showToast(`Blocked holiday: ${weekHolidayMap.get(dayKey)?.name || 'Holiday'}`, 'warning');
        return;
      }
      event.preventDefault();
      moveDragState.didDrop = true;
    });
  });

  const chips = Array.from(el.querySelectorAll('.cal-chip[data-session-id]'));

  //  Duration Drag Resize 
  const resizeState = {
    active: false,
    sessionId: null,
    originY: null,
    initialDur: null,
    currentDur: null,
    timeLabelEl: null,
    startMins: null,
  };

  chips.forEach(chip => {
    const handle = chip.querySelector('[data-resize-handle]');
    if (!handle) return;

    handle.addEventListener('mousedown', e => {
      if (String(chip.dataset.sessionLocked || '') === '1') {
        showToast('Past workflow sessions are locked for resize.', 'info');
        return;
      }
      e.stopPropagation();
      e.preventDefault();

      const sessionId = Number(chip.dataset.sessionId);
      const session = weekEvents.find(row => Number(row.session_id) === sessionId);
      if (!session) return;

      const startMins = _timeToMinutes(session.start_time);
      if (startMins == null) return;

      resizeState.active = true;
      resizeState.sessionId = sessionId;
      resizeState.originY = e.clientY;
      resizeState.initialDur = _resolveSessionDurationMinutes(session);
      resizeState.currentDur = resizeState.initialDur;
      resizeState.timeLabelEl = chip.querySelector('[data-time-label]');
      resizeState.startMins = startMins;

      chip.classList.add('resizing');
      document.body.style.cursor = 'ns-resize';

      const onMouseMove = moveEvent => {
        if (!resizeState.active) return;
        const dy = moveEvent.clientY - resizeState.originY;
        const intervals = Math.round(dy / 10);
        const newDur = Math.max(15, resizeState.initialDur + (intervals * 15));

        if (newDur !== resizeState.currentDur) {
          resizeState.currentDur = newDur;
          const endMins = resizeState.startMins + newDur;
          const previewEnd = _minutesToPayloadTime(endMins).slice(0, 5);
          if (resizeState.timeLabelEl) {
            resizeState.timeLabelEl.textContent = `${fmtTime(session.start_time)}-${fmtTime(previewEnd)} (${newDur}m)`;
          }
        }
      };

      const onMouseUp = async () => {
        if (!resizeState.active) return;
        resizeState.active = false;
        chip.classList.remove('resizing');
        document.body.style.cursor = '';
        window.removeEventListener('mousemove', onMouseMove);

        if (resizeState.currentDur === resizeState.initialDur) {
          if (resizeState.timeLabelEl) {
            resizeState.timeLabelEl.textContent = `${fmtTime(session.start_time)}${session.end_time ? `-${fmtTime(session.end_time)}` : ''}`;
          }
          return;
        }

        const payload = {
          end_time: _minutesToPayloadTime(resizeState.startMins + resizeState.currentDur)
        };

        if (_mutationInFlight) {
          showToast('Please wait for current update.', 'info');
          return;
        }
        _mutationInFlight = true;

        try {
          await api(`/sessions/${sessionId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          _sessionDetailCache.delete(sessionId);
          await _reloadCalendarData(classId);
          _renderCalendar(el, classId);
          showToast('Duration updated.', 'ok');
          if (Number(_selectedSessionId) === sessionId) {
            await _selectSession(sessionId, el, classId);
          }
        } catch (err) {
          showToast(err.message || 'Failed to resize.', 'error');
          _renderCalendar(el, classId);
        } finally {
          _mutationInFlight = false;
        }
      };

      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp, { once: true });
    });
  });

  chips.forEach(chip => {
    chip.addEventListener('dragstart', event => {
      if (String(chip.dataset.sessionLocked || '') === '1') {
        event.preventDefault();
        showToast('Past workflow sessions are locked for move actions.', 'info');
        return;
      }
      const sessionId = Number(chip.dataset.sessionId);
      const sourceDay = String(chip.dataset.sessionDay || '');
      const sourceSlot = Number(chip.dataset.sessionSlotIndex);
      const session = weekEvents.find(row => Number(row.session_id) === sessionId);
      if (!session || _timeToMinutes(session.start_time) == null) {
        event.preventDefault();
        showToast('Only sessions with a start time can be dragged.', 'warning');
        return;
      }
      moveDragState.sessionId = sessionId;
      moveDragState.sourceDayKey = sourceDay;
      moveDragState.sourceSlotIndex = Number.isFinite(sourceSlot) ? sourceSlot : null;
      moveDragState.targetDayKey = null;
      moveDragState.targetSlotIndex = null;
      moveDragState.didDrop = false;
      _suppressChipClickUntil = Date.now() + CHIP_CLICK_SUPPRESS_MS;
      chip.classList.add('dragging');
      document.body.classList.add('calendar-chip-dragging');
      const ghost = document.createElement('div');
      ghost.className = 'cal-drag-ghost';
      ghost.textContent = String(session.unit_title || 'Session');
      document.body.appendChild(ghost);
      moveDragState.ghostEl = ghost;
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(sessionId));
        event.dataTransfer.setDragImage(ghost, 12, 12);
      }
    });

    chip.addEventListener('dragend', async () => {
      chip.classList.remove('dragging');
      document.body.classList.remove('calendar-chip-dragging');
      const sessionId = moveDragState.sessionId;
      const targetDayKey = moveDragState.targetDayKey;
      const targetSlotIndex = moveDragState.targetSlotIndex;
      const sourceDayKey = moveDragState.sourceDayKey;
      const sourceSlotIndex = moveDragState.sourceSlotIndex;
      const didDrop = moveDragState.didDrop;
      _suppressChipClickUntil = Date.now() + CHIP_CLICK_SUPPRESS_MS;

      moveDragState.sessionId = null;
      moveDragState.sourceDayKey = null;
      moveDragState.sourceSlotIndex = null;
      moveDragState.targetDayKey = null;
      moveDragState.targetSlotIndex = null;
      moveDragState.didDrop = false;
      moveDragState.ghostEl?.remove();
      moveDragState.ghostEl = null;
      clearDropTargets();

      if (!didDrop || !sessionId || !targetDayKey || !Number.isFinite(targetSlotIndex)) return;
      if (targetDayKey === sourceDayKey && Number(targetSlotIndex) === Number(sourceSlotIndex)) return;
      const session = weekEvents.find(row => Number(row.session_id) === Number(sessionId));
      if (!session) return;
      await _moveSessionBlock({
        classId,
        session,
        targetDayKey,
        targetSlotIndex: Number(targetSlotIndex),
        el,
      });
    });
  });

  el.querySelector('#btn-prev-week')?.addEventListener('click', async () => {
    _weekStart = _addDays(_weekStart, -7);
    _selectedSessionId = null;
    _selectedSessionError = null;
    _selectedSessionLoading = false;
    _calendarPlannedHideDone = false;
    const nextWeekDays = _buildWeekDays(_weekStart);
    await Promise.all([
      _loadWeekHolidays(_weekStart).catch(() => {}),
      _loadClassTimetableExceptions(classId, nextWeekDays).catch(() => {}),
    ]);
    _renderCalendar(el, classId);
  });

  el.querySelector('#btn-next-week')?.addEventListener('click', async () => {
    _weekStart = _addDays(_weekStart, 7);
    _selectedSessionId = null;
    _selectedSessionError = null;
    _selectedSessionLoading = false;
    _calendarPlannedHideDone = false;
    const nextWeekDays = _buildWeekDays(_weekStart);
    await Promise.all([
      _loadWeekHolidays(_weekStart).catch(() => {}),
      _loadClassTimetableExceptions(classId, nextWeekDays).catch(() => {}),
    ]);
    _renderCalendar(el, classId);
  });

  el.querySelector('#btn-this-week')?.addEventListener('click', async () => {
    _weekStart = _startOfWeek(new Date());
    _selectedSessionId = null;
    _selectedSessionError = null;
    _selectedSessionLoading = false;
    _calendarPlannedHideDone = false;
    const nextWeekDays = _buildWeekDays(_weekStart);
    await Promise.all([
      _loadWeekHolidays(_weekStart).catch(() => {}),
      _loadClassTimetableExceptions(classId, nextWeekDays).catch(() => {}),
    ]);
    _renderCalendar(el, classId);
  });

  el.querySelector('#btn-close-selected-session')?.addEventListener('click', () => {
    _selectedSessionId = null;
    _selectedSessionError = null;
    _selectedSessionLoading = false;
    _calendarPlannedHideDone = false;
    _renderCalendar(el, classId);
  });

  el.querySelector('#btn-open-selected-workflow')?.addEventListener('click', () => {
    const intent = _buildCalendarWorkflowIntent(selectedEvent, selectedMatchesActiveWorkflow ? 'session' : '', {
      preview_hide_done: _calendarPlannedHideDone,
    });
    if (intent) _setWorkflowViewIntent(intent);
    navigate('workflow');
  });

  el.querySelector('#btn-open-active-workflow-session')?.addEventListener('click', () => {
    const intent = _buildWorkflowSessionIntent(activeWorkflowSession, 'session');
    if (intent) _setWorkflowViewIntent(intent);
    navigate('workflow');
  });

  el.querySelector('#btn-open-selected-unit-assistant')?.addEventListener('click', () => {
    const prefill = _buildCalendarAssistantPrefill(
      plannedResumePlaybookEntry,
      plannedResumeSectionPlan,
      plannedResumeNode?.title || '',
      'explain_section',
    );
    const intent = _buildCalendarWorkflowIntent(selectedEvent, 'assistant', {
      section_title: prefill.section_title,
      section_path: prefill.section_path,
      teacher_request: prefill.teacher_request,
      assistant_action: prefill.assistant_action,
      preview_hide_done: _calendarPlannedHideDone,
    });
    if (!intent) return;
    _setWorkflowViewIntent(intent);
    navigate('workflow');
  });

  el.querySelectorAll('.btn-calendar-next-focus-action').forEach(button => {
    button.addEventListener('click', () => {
      const prefill = _buildCalendarAssistantPrefill(
        plannedResumePlaybookEntry,
        plannedResumeSectionPlan,
        plannedResumeNode?.title || '',
        String(button.dataset.assistantAction || 'explain_section').trim().toLowerCase(),
      );
      const intent = _buildCalendarWorkflowIntent(selectedEvent, 'assistant', {
        section_title: prefill.section_title,
        section_path: prefill.section_path,
        teacher_request: prefill.teacher_request,
        assistant_action: prefill.assistant_action,
        preview_hide_done: _calendarPlannedHideDone,
      });
      if (!intent) return;
      _setWorkflowViewIntent(intent);
      navigate('workflow');
    });
  });
  const calendarPreviewGuidanceWrap = el.querySelector('[data-calendar-next-focus-guidance]');
  if (calendarPreviewGuidanceWrap && plannedResumeNode && selectedEvent?.unit_id) {
    _hydrateCalendarSavedGuidance(calendarPreviewGuidanceWrap, {
      classId,
      unitId: selectedEvent.unit_id,
      sectionPlan: plannedResumeSectionPlan,
      fallbackTitle: plannedResumeNode.title,
    });
  }

  el.querySelectorAll('.btn-calendar-prep-request').forEach(button => {
    button.addEventListener('click', () => {
      let sectionPath = [];
      try {
        const raw = String(button.dataset.sectionPath || '[]').trim();
        const parsed = JSON.parse(raw);
        sectionPath = Array.isArray(parsed) ? parsed.map(value => String(value || '').trim()).filter(Boolean) : [];
      } catch {
        sectionPath = [];
      }
      const intent = _buildCalendarWorkflowIntent(selectedEvent, 'assistant', {
        section_title: String(button.dataset.sectionTitle || '').trim(),
        section_path: sectionPath,
        teacher_request: String(button.dataset.teacherRequest || '').trim(),
        assistant_action: String(button.dataset.assistantAction || 'explain_section').trim().toLowerCase(),
        preview_hide_done: _calendarPlannedHideDone,
      });
      if (!intent) return;
      _setWorkflowViewIntent(intent);
      navigate('workflow');
    });
  });
  el.querySelectorAll('.btn-calendar-session-guidance-copy').forEach(button => {
    button.addEventListener('click', async () => {
      const artifactId = Number(button.dataset.artifactId || 0);
      const item = selectedMatchedGuidance.find(row => Number(row?.id || 0) === artifactId);
      if (!item?.content_markdown) return;
      try {
        await copyText(String(item.content_markdown));
        showToast('Saved guidance copied.', 'ok');
      } catch {
        showToast('Failed to copy saved guidance.', 'error');
      }
    });
  });
  el.querySelectorAll('.btn-calendar-session-guidance-download').forEach(button => {
    button.addEventListener('click', () => {
      const artifactId = Number(button.dataset.artifactId || 0);
      const item = selectedMatchedGuidance.find(row => Number(row?.id || 0) === artifactId);
      if (!item?.content_markdown) return;
      _downloadTextContent(String(item.content_markdown), _calendarArtifactDownloadFilename(item, selectedEvent?.unit_title || 'session-guidance'));
    });
  });
  el.querySelectorAll('.btn-calendar-session-guidance-import').forEach(button => {
    button.addEventListener('click', async () => {
      if (!selectedEvent || selectedEvent.unit_id == null || selectedIsFuture) return;
      const artifactId = Number(button.dataset.artifactId || 0);
      if (!artifactId) return;
      try {
        const updated = await api(`/workflow/classes/${classId}/sessions/${selectedEvent.session_id}/writeup/import-assistant-artifact`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ artifact_id: artifactId }),
        });
        const current = _sessionDetailCache.get(Number(selectedEvent.session_id)) || {};
        _sessionDetailCache.set(Number(selectedEvent.session_id), {
          ...current,
          workflow_writeup: updated || null,
          workflow_writeup_error: null,
        });
        _renderCalendar(el, classId);
        showToast('Saved guidance imported into the session write-up.', 'ok');
      } catch (err) {
        showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
      }
    });
  });

  if (selectedEvent?.unit_id != null && plannedSessionTitles.length) {
    const artifactCacheKey = `${Number(classId || 0)}:${Number(selectedEvent.unit_id || 0)}`;
    if (!_calendarAssistantArtifactCache.has(artifactCacheKey)) {
      _loadCalendarAssistantArtifacts(classId, selectedEvent.unit_id).then(() => {
        if (Number(_selectedSessionId || 0) === Number(selectedEvent.session_id || 0)) {
          _renderCalendar(el, classId);
        }
      }).catch(() => {});
    }
  }

  el.querySelector('#btn-open-selected-material-studio')?.addEventListener('click', () => {
    const intent = _buildCalendarWorkflowIntent(selectedEvent, 'material_studio', {
      preview_hide_done: _calendarPlannedHideDone,
    });
    if (!intent) return;
    _setWorkflowViewIntent(intent);
    navigate('workflow');
  });

  el.querySelector('#btn-open-selected-ai-details')?.addEventListener('click', () => {
    const intent = _buildCalendarWorkflowIntent(selectedEvent, 'ai_details', {
      preview_hide_done: _calendarPlannedHideDone,
    });
    if (!intent) return;
    _setWorkflowViewIntent(intent);
    navigate('workflow');
  });

  el.querySelector('#btn-confirm-selected-session')?.addEventListener('click', async event => {
    if (!selectedEvent) return;
    if (_mutationInFlight) {
      showToast('Please wait for the current update to finish.', 'info');
      return;
    }
    const sessionId = Number(selectedEvent.session_id || 0);
    if (!sessionId) return;
    if (selectedEvent.unit_id == null) {
      showToast('Only workflow unit sessions can be confirmed.', 'warning');
      return;
    }
    if (selectedIsFuture) {
      showToast('Future sessions can be confirmed only on or after session day.', 'info');
      return;
    }

    const confirmed = await askConfirm(
      `Confirm session ${fmtDate(selectedEvent.session_date || selectedEvent.date)} and auto-check its checklist progress?`
    );
    if (!confirmed) return;

    const button = event.currentTarget;
    if (button) button.disabled = true;
    _mutationInFlight = true;
    try {
      const result = await api(`/workflow/classes/${classId}/sessions/${sessionId}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          auto_close_unit: true,
          create_progress_items: true,
          generate_session_writeup: true,
        }),
      });

      await _reloadCalendarData(classId);
      await _loadClassTimetableExceptions(classId, weekDays).catch(() => {});
      _sessionDetailCache.delete(sessionId);
      await _selectSession(sessionId, el, classId);

      const checkedCount = Number(result?.checked_items_count || 0);
      const progressCount = Number(result?.progress_items_created || 0);
      const remainingCount = Math.max(0, Number(result?.remaining_items_count || 0));
      const unitClosed = Boolean(result?.unit_closed);
      const writeupGenerated = Boolean(result?.writeup_generated);

      const parts = [];
      if (checkedCount > 0) parts.push(`${checkedCount} checklist item${checkedCount === 1 ? '' : 's'} checked`);
      if (progressCount > 0) parts.push(`${progressCount} content row${progressCount === 1 ? '' : 's'} added`);
      if (writeupGenerated) parts.push('textbook write-up generated');
      if (remainingCount > 0) parts.push(`${remainingCount} item${remainingCount === 1 ? '' : 's'} remaining`);
      if (!parts.length) parts.push('no new checklist items to confirm');
      const suffix = unitClosed ? ' Unit closed automatically.' : '';
      showToast(`Session confirmed: ${parts.join(', ')}.${suffix}`, unitClosed || checkedCount > 0 ? 'ok' : 'info');
    } catch (err) {
      showToast(String(err?.message || 'Failed to confirm session.'), 'error');
    } finally {
      _mutationInFlight = false;
      if (button) button.disabled = false;
    }
  });

  el.querySelector('#btn-edit-selected-session')?.addEventListener('click', async () => {
    if (!selectedEvent) return;
    if (!selectedCanEdit) {
      showToast('Past workflow sessions are locked for date/time edits.', 'info');
      return;
    }
    await _editSessionBlock({ classId, session: selectedEvent, el });
  });

  el.querySelector('#btn-edit-selected-attendance')?.addEventListener('click', async event => {
    if (!selectedEvent) return;
    if (!selectedCanAttendanceEdit) {
      showToast('Future sessions cannot take attendance yet.', 'info');
      return;
    }
    const sessionId = Number(selectedEvent.session_id || 0);
    if (!sessionId) return;
    const students = (Array.isArray(getStudents()) ? getStudents() : [])
      .map(student => ({
        id: Number(student?.id || 0),
        full_name: String(student?.full_name || '').trim(),
        student_code: String(student?.student_code || '').trim(),
      }))
      .filter(student => student.id > 0 && student.full_name);
    if (!students.length) {
      showToast('No students found for this class.', 'warning');
      return;
    }

    const modalResult = await _openSessionAttendanceModal({
      sessionDateKey: selectedDateKey || _dateKey(selectedEvent.session_date || selectedEvent.date || null),
      students,
      absentStudentIds: _resolveAbsentStudentIds(selectedDetail, selectedEvent),
    });
    if (!modalResult) return;

    if (_mutationInFlight) {
      showToast('Please wait for the current update to finish.', 'info');
      return;
    }
    const button = event.currentTarget;
    if (button) button.disabled = true;
    _mutationInFlight = true;
    try {
      const absentSet = new Set(
        (Array.isArray(modalResult.absent_student_ids) ? modalResult.absent_student_ids : [])
          .map(value => Number(value))
          .filter(value => Number.isFinite(value) && value > 0)
      );
      const existingByStudent = new Map(
        (Array.isArray(selectedDetail?.attendance) ? selectedDetail.attendance : [])
          .map(row => [Number(row?.student_id || 0), row])
      );
      const attendancePayload = students.map(student => {
        const existing = existingByStudent.get(Number(student.id)) || null;
        const existingStatus = String(existing?.status || '').toLowerCase();
        let status = 'present';
        let minutes_late = 0;
        let comment = null;
        if (absentSet.has(student.id)) {
          status = 'absent';
        } else if (existingStatus === 'late' || existingStatus === 'excused') {
          status = existingStatus;
          minutes_late = Number(existing?.minutes_late || 0);
          comment = existing?.comment == null ? null : String(existing.comment);
        }
        return {
          student_id: student.id,
          status,
          minutes_late: Number.isFinite(minutes_late) && minutes_late > 0 ? minutes_late : 0,
          comment,
        };
      });

      await api(`/sessions/${sessionId}/attendance`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(attendancePayload),
      });

      _sessionDetailCache.delete(sessionId);
      await _reloadCalendarData(classId);
      await _selectSession(sessionId, el, classId);
      const absentCount = absentSet.size;
      showToast(
        absentCount > 0
          ? `Attendance saved (${absentCount} absent).`
          : 'Attendance saved (all present).',
        'ok'
      );
    } catch (err) {
      showToast(String(err?.message || 'Failed to update attendance.'), 'error');
    } finally {
      _mutationInFlight = false;
      if (button) button.disabled = false;
    }
  });

  el.querySelector('#btn-generate-selected-writeup')?.addEventListener('click', async event => {
    if (!selectedEvent || selectedEvent.unit_id == null) return;
    if (selectedIsFuture) {
      showToast('Future sessions cannot generate a textbook write-up yet.', 'info');
      return;
    }
    if (_mutationInFlight) {
      showToast('Please wait for the current update to finish.', 'info');
      return;
    }
    const sessionId = Number(selectedEvent.session_id || 0);
    if (!sessionId) return;
    const button = event.currentTarget;
    if (button) button.disabled = true;
    _mutationInFlight = true;
    try {
      await api(`/workflow/classes/${classId}/sessions/${sessionId}/writeup/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ regenerate: true }),
      });
      _sessionDetailCache.delete(sessionId);
      await _selectSession(sessionId, el, classId);
      showToast(selectedWriteup ? 'Textbook write-up re-generated.' : 'Textbook write-up generated.', 'ok');
    } catch (err) {
      showToast(String(err?.message || 'Failed to generate write-up.'), 'error');
    } finally {
      _mutationInFlight = false;
      if (button) button.disabled = false;
    }
  });

  el.querySelector('#btn-toggle-selected-writeup-approval')?.addEventListener('click', async event => {
    if (!selectedEvent || !selectedWriteup) return;
    if (_mutationInFlight) {
      showToast('Please wait for the current update to finish.', 'info');
      return;
    }
    const sessionId = Number(selectedEvent.session_id || 0);
    if (!sessionId) return;
    const nextApproved = selectedWriteup.approved === false;
    const button = event.currentTarget;
    if (button) button.disabled = true;
    _mutationInFlight = true;
    try {
      await api(`/workflow/classes/${classId}/sessions/${sessionId}/writeup`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: nextApproved }),
      });
      _sessionDetailCache.delete(sessionId);
      await _selectSession(sessionId, el, classId);
      showToast(nextApproved ? 'Write-up approved.' : 'Write-up marked as draft.', 'ok');
    } catch (err) {
      showToast(String(err?.message || 'Failed to update write-up status.'), 'error');
    } finally {
      _mutationInFlight = false;
      if (button) button.disabled = false;
    }
  });

  el.querySelector('#btn-edit-selected-writeup')?.addEventListener('click', async () => {
    if (!selectedEvent || !selectedWriteup) return;
    if (_mutationInFlight) {
      showToast('Please wait for the current update to finish.', 'info');
      return;
    }
    const sessionId = Number(selectedEvent.session_id || 0);
    if (!sessionId) return;
    const draft = await _openCalendarSessionWriteupModal(selectedWriteup);
    if (!draft) return;
    _mutationInFlight = true;
    try {
      await api(`/workflow/classes/${classId}/sessions/${sessionId}/writeup`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft),
      });
      _sessionDetailCache.delete(sessionId);
      await _selectSession(sessionId, el, classId);
      showToast('Write-up updated.', 'ok');
    } catch (err) {
      showToast(String(err?.message || 'Failed to update write-up.'), 'error');
    } finally {
      _mutationInFlight = false;
    }
  });

  el.querySelector('#btn-copy-selected-writeup')?.addEventListener('click', async () => {
    if (!selectedEvent || !selectedWriteup) return;
    try {
      await navigator.clipboard.writeText(
        _buildSessionWriteupMarkdown(selectedWriteup, {
          unitTitle: String(selectedEvent.unit_title || '').trim(),
          sessionLabel: selectedSessionNumber ? `Unit Session ${selectedSessionNumber}` : fmtDate(selectedEvent.session_date || selectedEvent.date),
        })
      );
      showToast('Write-up copied.', 'ok');
    } catch {
      showToast('Failed to copy the write-up.', 'error');
    }
  });

  el.querySelector('#btn-download-selected-writeup')?.addEventListener('click', () => {
    if (!selectedEvent || !selectedWriteup) return;
    const unitSlug = String(selectedEvent.unit_title || 'unit').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'unit';
    const sessionSlug = selectedSessionNumber ? `session-${selectedSessionNumber}` : 'session-writeup';
    _downloadTextContent(
      _buildSessionWriteupMarkdown(selectedWriteup, {
        unitTitle: String(selectedEvent.unit_title || '').trim(),
        sessionLabel: selectedSessionNumber ? `Unit Session ${selectedSessionNumber}` : fmtDate(selectedEvent.session_date || selectedEvent.date),
      }),
      `${unitSlug}-${sessionSlug}.md`
    );
  });

  el.querySelector('#btn-calendar-next-generate')?.addEventListener('click', () => {
    el.querySelector('#btn-generate-selected-writeup')?.click();
  });
  el.querySelector('#btn-calendar-next-open-workflow')?.addEventListener('click', () => {
    el.querySelector('#btn-open-selected-workflow')?.click();
  });
  el.querySelector('#btn-calendar-next-assistant')?.addEventListener('click', () => {
    el.querySelector('#btn-open-selected-unit-assistant')?.click();
  });
  el.querySelector('#btn-calendar-next-materials')?.addEventListener('click', () => {
    el.querySelector('#btn-open-selected-material-studio')?.click();
  });
  el.querySelector('#btn-calendar-next-guidance')?.addEventListener('click', () => {
    el.querySelector('#btn-import-selected-guidance')?.click();
  });
  el.querySelector('#btn-calendar-session-guidance-hide-imported-toggle')?.addEventListener('click', () => {
    _calendarSessionGuidanceHideImported = !_calendarSessionGuidanceHideImported;
    _renderCalendar(el, classId);
  });
  el.querySelector('#btn-calendar-next-import-best')?.addEventListener('click', async () => {
    if (!selectedEvent || selectedEvent.unit_id == null || !selectedBestRemainingGuidance) return;
    try {
      const updated = await api(`/workflow/classes/${classId}/sessions/${selectedEvent.session_id}/writeup/import-assistant-artifact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: Number(selectedBestRemainingGuidance.id) }),
      });
      const current = _sessionDetailCache.get(Number(selectedEvent.session_id)) || {};
      _sessionDetailCache.set(Number(selectedEvent.session_id), {
        ...current,
        workflow_writeup: updated || null,
        workflow_writeup_error: null,
      });
      _renderCalendar(el, classId);
      showToast('Best matching saved guidance imported.', 'ok');
    } catch (err) {
      showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
    }
  });
  el.querySelector('#btn-calendar-next-import-all')?.addEventListener('click', async () => {
    if (!selectedEvent || selectedEvent.unit_id == null || !selectedRemainingGuidance.length) return;
    try {
      let updated = null;
      for (const item of selectedRemainingGuidance) {
        updated = await api(`/workflow/classes/${classId}/sessions/${selectedEvent.session_id}/writeup/import-assistant-artifact`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ artifact_id: Number(item.id) }),
        });
      }
      const current = _sessionDetailCache.get(Number(selectedEvent.session_id)) || {};
      _sessionDetailCache.set(Number(selectedEvent.session_id), {
        ...current,
        workflow_writeup: updated || null,
        workflow_writeup_error: null,
      });
      _renderCalendar(el, classId);
      showToast(`${selectedRemainingGuidance.length} saved guidance item${selectedRemainingGuidance.length === 1 ? '' : 's'} imported.`, 'ok');
    } catch (err) {
      showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
    }
  });
  el.querySelectorAll('.btn-calendar-guidance-kind-import').forEach(button => {
    button.addEventListener('click', async () => {
      if (!selectedEvent || selectedEvent.unit_id == null) return;
      const artifactKind = String(button.dataset.artifactKind || '').trim().toLowerCase();
      if (!artifactKind) return;
      const matches = selectedRemainingGuidance.filter(item => String(item?.artifact_kind || '').trim().toLowerCase() === artifactKind);
      if (!matches.length) return;
      try {
        let updated = null;
        for (const item of matches) {
          updated = await api(`/workflow/classes/${classId}/sessions/${selectedEvent.session_id}/writeup/import-assistant-artifact`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ artifact_id: Number(item.id) }),
          });
        }
        const current = _sessionDetailCache.get(Number(selectedEvent.session_id)) || {};
        _sessionDetailCache.set(Number(selectedEvent.session_id), {
          ...current,
          workflow_writeup: updated || null,
          workflow_writeup_error: null,
        });
        _renderCalendar(el, classId);
        showToast(`${matches.length} ${_assistantArtifactKindLabel(artifactKind).toLowerCase()} item${matches.length === 1 ? '' : 's'} imported.`, 'ok');
      } catch (err) {
        showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
      }
    });
  });
  el.querySelectorAll('.btn-calendar-guidance-quick-pick').forEach(button => {
    button.addEventListener('click', async () => {
      if (!selectedEvent || selectedEvent.unit_id == null) return;
      const artifactId = Number(button.dataset.artifactId || 0);
      if (!artifactId) return;
      try {
        const updated = await api(`/workflow/classes/${classId}/sessions/${selectedEvent.session_id}/writeup/import-assistant-artifact`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ artifact_id: artifactId }),
        });
        const current = _sessionDetailCache.get(Number(selectedEvent.session_id)) || {};
        _sessionDetailCache.set(Number(selectedEvent.session_id), {
          ...current,
          workflow_writeup: updated || null,
          workflow_writeup_error: null,
        });
        _renderCalendar(el, classId);
        showToast('Saved guidance imported into the session write-up.', 'ok');
      } catch (err) {
        showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
      }
    });
  });
  el.querySelector('#btn-calendar-next-edit')?.addEventListener('click', () => {
    el.querySelector('#btn-edit-selected-writeup')?.click();
  });
  el.querySelector('#btn-calendar-next-approve')?.addEventListener('click', () => {
    el.querySelector('#btn-toggle-selected-writeup-approval')?.click();
  });
  el.querySelector('#btn-calendar-next-copy')?.addEventListener('click', () => {
    el.querySelector('#btn-copy-selected-writeup')?.click();
  });
  el.querySelector('#btn-calendar-next-download')?.addEventListener('click', () => {
    el.querySelector('#btn-download-selected-writeup')?.click();
  });

  el.querySelector('#btn-import-selected-guidance')?.addEventListener('click', async () => {
    if (!selectedEvent || selectedEvent.unit_id == null) return;
    if (selectedIsFuture) {
      showToast('Future sessions cannot import saved guidance yet.', 'info');
      return;
    }
    if (_mutationInFlight) {
      showToast('Please wait for the current update to finish.', 'info');
      return;
    }
    const sessionId = Number(selectedEvent.session_id || 0);
    if (!sessionId) return;
    const artifactId = await _openCalendarSessionGuidanceImportModal({
      classId,
      unitId: selectedEvent.unit_id,
    });
    if (!artifactId) return;
    _mutationInFlight = true;
    try {
      await api(`/workflow/classes/${classId}/sessions/${sessionId}/writeup/import-assistant-artifact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact_id: artifactId }),
      });
      _sessionDetailCache.delete(sessionId);
      await _selectSession(sessionId, el, classId);
      showToast('Saved guidance imported into the session write-up.', 'ok');
    } catch (err) {
      showToast(String(err?.message || 'Failed to import saved guidance.'), 'error');
    } finally {
      _mutationInFlight = false;
    }
  });

  el.querySelector('#btn-retry-session-detail')?.addEventListener('click', async () => {
    if (!selectedEvent) return;
    await _selectSession(Number(selectedEvent.session_id), el, classId);
  });

  el.querySelector('#btn-calendar-planned-hide-done-toggle')?.addEventListener('click', event => {
    event.preventDefault();
    _calendarPlannedHideDone = !_calendarPlannedHideDone;
    _renderCalendar(el, classId);
  });

  el.querySelectorAll('.cal-chip[data-session-id]').forEach(btn => {
    const openSelectedSession = async (e = null) => {
      if (e?.target?.closest?.('[data-resize-handle]')) return;
      if (Date.now() < _suppressChipClickUntil) return;
      const sessionId = Number(btn.dataset.sessionId);
      await _selectSession(sessionId, el, classId);
    };
    btn.addEventListener('click', async (e) => {
      if (e.target.closest('[data-resize-handle]')) return;
      if (Date.now() < _suppressChipClickUntil) return;
      const sessionId = Number(btn.dataset.sessionId);
      await _selectSession(sessionId, el, classId);
    });
    btn.addEventListener('keydown', async e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      await openSelectedSession();
    });
  });

  el.querySelectorAll('.cal-outside-session[data-session-id]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const sessionId = Number(btn.dataset.sessionId);
      if (!sessionId) return;
      await _selectSession(sessionId, el, classId);
    });
  });

  el.querySelector('#btn-export-cal')?.addEventListener('click', async () => {
    try {
      const { fromKey, toKey } = _resolveCalendarExportRange(classId, weekStartKey, weekEndKey);
      await downloadWithAuth(
        `/workflow/classes/${classId}/calendar/export.pdf?date_from=${encodeURIComponent(fromKey)}&date_to=${encodeURIComponent(toKey)}&ai_enhance=true`,
        `calendar-summary-${fromKey}_to_${toKey}.pdf`,
      );
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  el.querySelector('#btn-plan-from-doc')?.addEventListener('click', async event => {
    event.preventDefault();
    if (_mutationInFlight) {
      showToast('Please wait for the current update to finish.', 'info');
      return;
    }

    let rules = Array.isArray(classRules) ? classRules : [];
    if (!rules.length) rules = await _loadClassTimetableRules(classId);
    if (!rules.length) {
      showToast('No timetable rules available. Configure emploi first from dashboard.', 'warning');
      return;
    }

    let workspace = null;
    try {
      workspace = await api(`/workflow/classes/${classId}`);
    } catch {
      workspace = null;
    }
    const activeUnitId = Number(workspace?.active_unit?.id || 0) || null;
    if (activeUnitId) {
      showToast('An active unit already exists. Close it first before running full setup.', 'warning');
      return;
    }

    const setupInput = await _openDocumentAutoSetupModal({ defaultStartDate: weekStartKey });
    if (!setupInput) return;

    const requestedCount = Math.max(1, Number(setupInput.session_count || 1));
    const confirmMsg = `Create unit "${setupInput.unit_title}" and auto-plan ${requestedCount} session${requestedCount !== 1 ? 's' : ''} from ${fmtDate(setupInput.start_date)}?`;
    const confirmed = await askConfirm(confirmMsg);
    if (!confirmed) return;

    const button = event.currentTarget;
    if (button) button.disabled = true;
    _mutationInFlight = true;
    try {
      const formData = new FormData();
      formData.append('unit_type', String(setupInput.unit_type || 'chapter'));
      formData.append('unit_title', String(setupInput.unit_title || '').trim());
      formData.append('session_count', String(requestedCount));
      formData.append('start_date', String(setupInput.start_date || '').trim());
      formData.append('skip_blocked_holidays', 'true');
      formData.append('auto_check_items', setupInput.auto_check_items ? 'true' : 'false');
      if (setupInput.planned_hours != null) formData.append('planned_hours', String(setupInput.planned_hours));
      if (String(setupInput.source_text || '').trim()) formData.append('source_text', String(setupInput.source_text || '').trim());
      if (setupInput.file) formData.append('file', setupInput.file);

      const result = await api(`/workflow/classes/${classId}/auto-setup-from-doc`, {
        method: 'POST',
        body: formData,
      });
      const createdCount = Number(result?.created_count || 0);
      const failedCount = Number(result?.failed_count || 0);
      const createdSessions = Array.isArray(result?.created_sessions) ? result.created_sessions : [];
      const checkedTotal = createdSessions.reduce((sum, row) => sum + Number(row?.checked_items_count || 0), 0);
      const firstCreatedSessionId = Number(createdSessions[0]?.id || 0) || null;

      _selectedSessionId = firstCreatedSessionId;
      _selectedSessionError = null;
      _selectedSessionLoading = false;
      if (firstCreatedSessionId) _sessionDetailCache.delete(firstCreatedSessionId);

      await _reloadCalendarData(classId);
      await _loadClassTimetableExceptions(classId, weekDays).catch(() => {});
      _renderCalendar(el, classId);
      if (failedCount > 0) {
        showToast(`Setup created ${createdCount} sessions with ${checkedTotal} checklist checks; ${failedCount} not scheduled.`, 'warning');
      } else {
        showToast(`Setup completed: ${createdCount} sessions created, ${checkedTotal} checklist checks.`, 'ok');
      }
      if (firstCreatedSessionId) await _selectSession(firstCreatedSessionId, el, classId);
    } catch (err) {
      showToast(String(err?.message || 'Document full setup failed.'), 'error');
    } finally {
      _mutationInFlight = false;
      if (button) button.disabled = false;
    }
  });

  el.querySelector('#btn-submit-past-session')?.addEventListener('click', async () => {
    await _submitPastSession({
      classId,
      el,
      defaultDateKey: _dateKey(new Date()),
    });
  });

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


