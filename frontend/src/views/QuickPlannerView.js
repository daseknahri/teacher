/*
 * QuickPlannerView.js - Detached planning shortcut window
 * Additive feature: no changes to existing workflow screens.
 */
import { api } from '../api/client.js';
import { getClasses, getSelectedId } from '../state/class.js';
import { showToast } from '../utils/toast.js';
import { navigate } from '../router.js';

const UNIT_TYPE_OPTIONS = [
  { value: 'chapter', label: 'Chapter' },
  { value: 'exercise_series', label: 'Exercise Series' },
  { value: 'exam', label: 'Exam' },
];
const MAX_PREVIEW_ROWS = 260;

function _showChrome() {
  document.getElementById('sidebar')?.classList.remove('hidden');
  document.getElementById('topbar')?.classList.remove('hidden');
  document.getElementById('bottom-tabs')?.classList.remove('hidden');
}

function _escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
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
  const date = new Date(`${key}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

function _addDays(value, days) {
  const date = new Date(value);
  date.setDate(date.getDate() + Number(days || 0));
  return date;
}

function _weekdayIso(value) {
  const date = value instanceof Date ? value : new Date(value);
  const day = date.getDay();
  return day === 0 ? 7 : day;
}

function _toMinutes(value) {
  const match = String(value || '').trim().match(/^(\d{2}):(\d{2})/);
  if (!match) return Number.POSITIVE_INFINITY;
  return (Number(match[1]) * 60) + Number(match[2]);
}

function _normalizeSessionCount(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.min(120, Math.floor(parsed)));
}

function _normalizeHorizonDays(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 365;
  return Math.max(30, Math.min(730, Math.floor(parsed)));
}

function _deriveTitleFromFileName(fileName) {
  const raw = String(fileName || '').trim();
  if (!raw) return '';
  return raw
    .replace(/\.[^.]+$/, '')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function _isRuleActiveOnDate(rule, dateValue) {
  const dayKey = _dateKey(dateValue);
  if (!dayKey) return false;
  const fromKey = _dateKey(rule?.effective_from);
  const toKey = _dateKey(rule?.effective_to);
  if (fromKey && dayKey < fromKey) return false;
  if (toKey && dayKey > toKey) return false;
  return true;
}

async function _resolveStartDateKey(classId, rawValue) {
  const explicit = _dateKey(rawValue);
  if (explicit) return explicit;
  const sessions = await api(`/classes/${classId}/sessions`).catch(() => []);
  let latest = '';
  (Array.isArray(sessions) ? sessions : []).forEach(row => {
    const key = _dateKey(row?.session_date);
    if (key && key > latest) latest = key;
  });
  return latest || _dateKey(new Date());
}

async function _loadBlockedHolidaySet(startDateKey, horizonDays) {
  const startDate = _dateFromKey(startDateKey);
  if (!startDate) return new Set();
  const endDate = _addDays(startDate, Math.max(0, Number(horizonDays || 1) - 1));
  const yearStart = startDate.getFullYear();
  const yearEnd = endDate.getFullYear();
  const years = [];
  for (let year = yearStart; year <= yearEnd; year += 1) years.push(year);

  const responses = await Promise.all(
    years.map(year => api(`/workflow/holidays?year=${year}&country_code=MA`).catch(() => []))
  );
  const blocked = new Set();
  responses.flat().forEach(row => {
    const dayKey = _dateKey(row?.holiday_date);
    if (dayKey && Boolean(row?.is_blocked)) blocked.add(dayKey);
  });
  return blocked;
}

function _buildTimeline({ rules, blockedHolidaySet, startDateKey, horizonDays }) {
  const startDate = _dateFromKey(startDateKey);
  if (!startDate) return { slots: [], skippedHolidaySlots: 0, endDateKey: '' };

  const totalDays = Math.max(1, Number(horizonDays || 1));
  const slots = [];
  let skippedHolidaySlots = 0;

  for (let offset = 0; offset < totalDays; offset += 1) {
    const currentDate = _addDays(startDate, offset);
    const currentKey = _dateKey(currentDate);
    const weekday = _weekdayIso(currentDate);
    if (weekday === 7) continue;
    const dayRules = (rules || []).filter(rule => Number(rule?.weekday) === weekday && _isRuleActiveOnDate(rule, currentDate));
    if (!dayRules.length) continue;

    if (blockedHolidaySet.has(currentKey)) {
      skippedHolidaySlots += dayRules.length;
      continue;
    }

    dayRules.forEach(rule => {
      slots.push({
        session_date: currentKey,
        start_time: String(rule?.start_time || '').trim() || null,
        end_time: String(rule?.end_time || '').trim() || null,
        subject: String(rule?.subject || '').trim() || null,
        room: String(rule?.room || '').trim() || null,
        group_name: String(rule?.group_name || '').trim() || null,
      });
    });
  }

  slots.sort((a, b) => {
    const dateDiff = String(a.session_date).localeCompare(String(b.session_date));
    if (dateDiff !== 0) return dateDiff;
    return _toMinutes(a.start_time) - _toMinutes(b.start_time);
  });

  const endDateKey = _dateKey(_addDays(startDate, totalDays - 1));
  return { slots, skippedHolidaySlots, endDateKey };
}

function _allocateUnits({ slots, units }) {
  const rows = [];
  const unitSummary = [];
  let cursor = 0;
  let totalPending = 0;

  (units || []).forEach((unit, unitIndex) => {
    const wanted = _normalizeSessionCount(unit?.session_count);
    const available = Math.max(0, slots.length - cursor);
    const assigned = Math.max(0, Math.min(wanted, available));
    const pending = Math.max(0, wanted - assigned);
    totalPending += pending;

    for (let idx = 0; idx < assigned; idx += 1) {
      const slot = slots[cursor + idx];
      rows.push({
        unit_index: unitIndex + 1,
        unit_type: unit.unit_type,
        unit_title: unit.unit_title,
        unit_session_number: idx + 1,
        session_date: slot.session_date,
        start_time: slot.start_time,
        end_time: slot.end_time,
        subject: slot.subject,
        room: slot.room,
        group_name: slot.group_name,
      });
    }
    cursor += assigned;

    unitSummary.push({
      unit_index: unitIndex + 1,
      unit_type: unit.unit_type,
      unit_title: unit.unit_title,
      requested: wanted,
      planned: assigned,
      pending,
    });
  });

  return {
    rows,
    unitSummary,
    totalPending,
    usedSlots: cursor,
    remainingSlots: Math.max(0, slots.length - cursor),
  };
}

function _unitRowMarkup(index, row = {}) {
  const type = String(row.unit_type || 'chapter');
  const title = String(row.unit_title || '');
  const count = _normalizeSessionCount(row.session_count || 6) || 6;
  const sourceText = String(row.source_text || '');
  return `
    <div class="qp-unit-row grid grid-cols-1 md:grid-cols-12 gap-2 p-2 rounded-xl border border-slate-200 bg-white" data-row-index="${index}">
      <div class="md:col-span-3">
        <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Type</label>
        <select class="qp-unit-type mt-1">
          ${UNIT_TYPE_OPTIONS.map(option => `<option value="${option.value}" ${option.value === type ? 'selected' : ''}>${option.label}</option>`).join('')}
        </select>
      </div>
      <div class="md:col-span-6">
        <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Unit Title (optional if PDF)</label>
        <input class="qp-unit-title mt-1" type="text" value="${_escapeHtml(title)}" placeholder="e.g. Chapter 4 - Integrals" />
      </div>
      <div class="md:col-span-2">
        <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Sessions</label>
        <input class="qp-unit-count mt-1" type="number" min="1" max="120" step="1" value="${count}" />
      </div>
      <div class="md:col-span-1 flex items-end">
        <button class="btn btn-ghost btn-sm qp-remove-row w-full" title="Remove row">X</button>
      </div>

      <div class="md:col-span-4">
        <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Unit PDF (optional)</label>
        <input class="qp-unit-file mt-1" type="file" accept=".pdf,application/pdf" />
      </div>
      <div class="md:col-span-8">
        <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Source Text (optional, recommended)</label>
        <textarea class="qp-unit-source mt-1" rows="2" placeholder="Paste chapter/series content for this unit">${_escapeHtml(sourceText)}</textarea>
      </div>
      <div class="md:col-span-12">
        <label class="inline-flex items-center gap-2 text-[12px] text-slate-700">
          <input class="qp-unit-auto-check" type="checkbox" checked disabled />
          <span>Auto-distribute checklist content across this unit sessions (always enabled)</span>
        </label>
      </div>
    </div>`;
}

function _collectUnitRows(rootEl) {
  const rows = [];
  rootEl.querySelectorAll('.qp-unit-row').forEach(rowEl => {
    const unitType = String(rowEl.querySelector('.qp-unit-type')?.value || 'chapter').trim();
    const unitTitle = String(rowEl.querySelector('.qp-unit-title')?.value || '').trim();
    const sessionCount = _normalizeSessionCount(rowEl.querySelector('.qp-unit-count')?.value || 0);
    const docFileName = String(rowEl.querySelector('.qp-unit-file')?.files?.[0]?.name || '').trim();
    const resolvedTitle = unitTitle || _deriveTitleFromFileName(docFileName);
    if (!resolvedTitle || sessionCount <= 0) return;
    rows.push({ unit_type: unitType, unit_title: resolvedTitle, session_count: sessionCount });
  });
  return rows;
}

function _renderPreview(rootEl, payload) {
  const summaryRows = (payload?.unitSummary || []).map(row => `
    <tr>
      <td>${row.unit_index}</td>
      <td>${_escapeHtml(row.unit_type)}</td>
      <td>${_escapeHtml(row.unit_title)}</td>
      <td>${row.requested}</td>
      <td>${row.planned}</td>
      <td>${row.pending}</td>
    </tr>
  `).join('');

  const timelineRows = (payload?.rows || []).slice(0, MAX_PREVIEW_ROWS).map((row, idx) => `
    <tr>
      <td>${idx + 1}</td>
      <td>${row.unit_index}</td>
      <td>${_escapeHtml(row.unit_title)}</td>
      <td>${row.unit_session_number}</td>
      <td>${_escapeHtml(row.session_date)}</td>
      <td>${_escapeHtml(String(row.start_time || '').slice(0, 5) || '-')}</td>
      <td>${_escapeHtml(String(row.end_time || '').slice(0, 5) || '-')}</td>
      <td>${_escapeHtml(row.subject || '-')}</td>
    </tr>
  `).join('');

  rootEl.innerHTML = `
    <div class="card">
      <div class="card-header">
        <h3 class="font-semibold text-slate-700 text-[14px]">Plan Summary</h3>
      </div>
      <div class="card-body flex flex-col gap-3">
        <div class="grid grid-cols-2 md:grid-cols-4 gap-2 text-[12px]">
          <div class="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2"><p class="text-slate-400">Start</p><p class="font-semibold text-slate-700">${_escapeHtml(payload.startDateKey)}</p></div>
          <div class="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2"><p class="text-slate-400">Window End</p><p class="font-semibold text-slate-700">${_escapeHtml(payload.endDateKey)}</p></div>
          <div class="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2"><p class="text-slate-400">Slots Used</p><p class="font-semibold text-slate-700">${payload.usedSlots}/${payload.totalSlots}</p></div>
          <div class="rounded-lg bg-slate-50 border border-slate-200 px-3 py-2"><p class="text-slate-400">Pending</p><p class="font-semibold text-slate-700">${payload.totalPending}</p></div>
        </div>
        <p class="text-[11px] text-slate-500">Blocked holiday slots skipped: ${payload.skippedHolidaySlots}. Remaining free slots in window: ${payload.remainingSlots}.</p>
        <div class="overflow-auto">
          <table class="data-table text-[12px]">
            <thead><tr><th>#</th><th>Type</th><th>Unit</th><th>Requested</th><th>Planned</th><th>Pending</th></tr></thead>
            <tbody>${summaryRows || '<tr><td colspan="6">No units to plan.</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <h3 class="font-semibold text-slate-700 text-[14px]">Timeline Preview</h3>
      </div>
      <div class="card-body">
        <div class="overflow-auto max-h-[360px]">
          <table class="data-table text-[12px]">
            <thead><tr><th>#</th><th>Unit</th><th>Title</th><th>S#</th><th>Date</th><th>Start</th><th>End</th><th>Subject</th></tr></thead>
            <tbody>${timelineRows || '<tr><td colspan="8">No timeline rows generated.</td></tr>'}</tbody>
          </table>
        </div>
        ${(payload.rows || []).length > MAX_PREVIEW_ROWS
          ? `<p class="text-[11px] text-slate-500 mt-2">Showing first ${MAX_PREVIEW_ROWS} rows out of ${(payload.rows || []).length} planned sessions.</p>`
          : ''}
      </div>
    </div>
  `;
}

export async function renderQuickPlannerView() {
  _showChrome();
  const el = document.getElementById('app-content');
  const classId = getSelectedId();
  const className = (getClasses() || []).find(row => Number(row?.id) === Number(classId))?.name || 'Selected class';

  if (!classId) {
    el.innerHTML = `
      <div class="view-container">
        <div class="empty-state bg-white rounded-3xl border border-slate-200 py-20">
          <div class="text-3xl font-black opacity-40">QUICK</div>
          <h2 class="text-lg font-semibold text-slate-600">No class selected</h2>
          <p class="text-[13px] text-slate-400 max-w-sm">Select a class first, then open this shortcut window again.</p>
          <button id="btn-go-class" class="btn btn-primary mt-3">Go To Dashboard</button>
        </div>
      </div>`;
    el.querySelector('#btn-go-class')?.addEventListener('click', () => navigate('class'));
    return;
  }

  const todayKey = _dateKey(new Date());
  el.innerHTML = `
    <div class="view-container flex flex-col gap-4">
      <div class="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 class="text-2xl font-bold text-slate-800 tracking-tight">Quick Planner Window</h1>
          <p class="text-[13px] text-slate-500 mt-1">Class: <span class="font-semibold text-slate-700">${_escapeHtml(className)}</span> | Shortcut planner that does not change existing workflow screens.</p>
        </div>
        <button id="btn-open-detached" class="btn btn-secondary">Open Detached Window</button>
      </div>

      <div class="card">
        <div class="card-header"><h3 class="font-semibold text-slate-700 text-[14px]">Planning Inputs</h3></div>
        <div class="card-body flex flex-col gap-3">
          <div class="grid grid-cols-1 md:grid-cols-3 gap-2">
            <div>
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Start Date (optional)</label>
              <input id="qp-start-date" class="mt-1" type="date" value="" placeholder="Auto" />
              <p class="text-[11px] text-slate-500 mt-1">Leave empty to start from latest class session date.</p>
            </div>
            <div>
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Planning Window (days)</label>
              <input id="qp-horizon-days" class="mt-1" type="number" min="30" max="730" step="1" value="365" />
              <p class="text-[11px] text-slate-500 mt-1">Full-year default is 365 days.</p>
            </div>
            <div>
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Resolved Start</label>
              <input id="qp-resolved-start" class="mt-1 !bg-slate-50" type="text" value="${_escapeHtml(todayKey)}" readonly />
              <p class="text-[11px] text-slate-500 mt-1">Calculated after preview/apply.</p>
            </div>
          </div>

          <div class="flex items-center justify-between gap-2 flex-wrap">
            <h4 class="text-[12px] font-semibold text-slate-500 uppercase tracking-wider">Units Queue</h4>
            <button id="qp-add-row" class="btn btn-ghost btn-sm">Add Unit Row</button>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50/60 p-2">
            <div id="qp-unit-rows" class="flex flex-col gap-2 max-h-[52vh] overflow-auto pr-1"></div>
          </div>

          <div class="flex gap-2 flex-wrap pt-1">
            <button id="qp-preview" class="btn btn-primary">Preview Year Timeline</button>
            <button id="qp-apply-first" class="btn btn-secondary">Create Full Queue Sessions</button>
          </div>
          <p class="text-[11px] text-slate-500">Forms are standardized per unit row. Queue area scrolls to stay on screen. Apply creates units in order (one-by-one) using each row's PDF/source, then auto-closes each unit.</p>
        </div>
      </div>

      <div id="qp-preview-output" class="flex flex-col gap-3"></div>
    </div>
  `;

  const rowsEl = el.querySelector('#qp-unit-rows');
  const addRow = (seed = {}) => {
    const index = rowsEl.querySelectorAll('.qp-unit-row').length;
    rowsEl.insertAdjacentHTML('beforeend', _unitRowMarkup(index, seed));
    _bindRowActions();
  };

  const _bindRowActions = () => {
    rowsEl.querySelectorAll('.qp-remove-row').forEach(btn => {
      btn.onclick = event => {
        event.preventDefault();
        const row = btn.closest('.qp-unit-row');
        row?.remove();
      };
    });
  };

  addRow({ unit_type: 'chapter', unit_title: '', session_count: 6 });

  el.querySelector('#qp-add-row')?.addEventListener('click', event => {
    event.preventDefault();
    addRow({ unit_type: 'chapter', unit_title: '', session_count: 6 });
  });

  el.querySelector('#btn-open-detached')?.addEventListener('click', () => {
    const target = `${window.location.pathname}${window.location.search}#quick-planner`;
    window.open(target, 'teacher_quick_planner', 'width=1380,height=920');
  });

  el.querySelector('#qp-preview')?.addEventListener('click', async () => {
    const previewBtn = el.querySelector('#qp-preview');
    previewBtn.disabled = true;
    try {
      const units = _collectUnitRows(el);
      if (!units.length) {
        showToast('Add at least one unit row with title and session count.', 'warning');
        return;
      }

      const horizonDays = _normalizeHorizonDays(el.querySelector('#qp-horizon-days')?.value || 365);
      const rawStart = String(el.querySelector('#qp-start-date')?.value || '').trim();
      const resolvedStartDate = await _resolveStartDateKey(classId, rawStart);
      const resolvedStartEl = el.querySelector('#qp-resolved-start');
      if (resolvedStartEl) resolvedStartEl.value = resolvedStartDate;

      const rules = await api(`/workflow/classes/${classId}/timetable-rules`).catch(() => []);
      if (!Array.isArray(rules) || !rules.length) {
        showToast('No timetable rules found. Import emploi first.', 'warning');
        return;
      }

      const blockedHolidaySet = await _loadBlockedHolidaySet(resolvedStartDate, horizonDays);
      const timeline = _buildTimeline({
        rules,
        blockedHolidaySet,
        startDateKey: resolvedStartDate,
        horizonDays,
      });
      const allocation = _allocateUnits({ slots: timeline.slots, units });

      _renderPreview(el.querySelector('#qp-preview-output'), {
        startDateKey: resolvedStartDate,
        endDateKey: timeline.endDateKey,
        totalSlots: timeline.slots.length,
        skippedHolidaySlots: timeline.skippedHolidaySlots,
        rows: allocation.rows,
        unitSummary: allocation.unitSummary,
        totalPending: allocation.totalPending,
        usedSlots: allocation.usedSlots,
        remainingSlots: allocation.remainingSlots,
      });

      if (allocation.totalPending > 0) {
        showToast(`Preview generated: ${allocation.rows.length} sessions planned, ${allocation.totalPending} pending.`, 'warning');
      } else {
        showToast(`Preview generated: ${allocation.rows.length} sessions planned.`, 'ok');
      }
    } catch (err) {
      showToast(String(err?.message || 'Failed to generate plan preview.'), 'error');
    } finally {
      previewBtn.disabled = false;
    }
  });

  el.querySelector('#qp-apply-first')?.addEventListener('click', async () => {
    const applyBtn = el.querySelector('#qp-apply-first');
    applyBtn.disabled = true;
    try {
      const rowElements = Array.from(rowsEl.querySelectorAll('.qp-unit-row'));
      if (!rowElements.length) {
        showToast('No unit rows available to apply.', 'warning');
        return;
      }

      const queue = [];
      for (let idx = 0; idx < rowElements.length; idx += 1) {
        const rowEl = rowElements[idx];
        const unitType = String(rowEl.querySelector('.qp-unit-type')?.value || 'chapter').trim();
        const unitTitle = String(rowEl.querySelector('.qp-unit-title')?.value || '').trim();
        const sessionCount = _normalizeSessionCount(rowEl.querySelector('.qp-unit-count')?.value || 0);
        const sourceText = String(rowEl.querySelector('.qp-unit-source')?.value || '').trim();
        const docFile = rowEl.querySelector('.qp-unit-file')?.files?.[0] || null;
        const derivedTitle = unitTitle || _deriveTitleFromFileName(docFile?.name || '');
        const effectiveTitle = derivedTitle || `Unit ${idx + 1}`;
        const rowLabel = `row ${idx + 1}`;

        if (sessionCount <= 0) {
          showToast(`Fill sessions count for ${rowLabel}.`, 'warning');
          return;
        }
        if (!derivedTitle && !docFile && !sourceText) {
          showToast(`Provide title or PDF/source text for ${rowLabel}.`, 'warning');
          return;
        }
        if ((unitType === 'chapter' || unitType === 'exercise_series') && !docFile && !sourceText) {
          showToast(`Upload PDF or source text for ${rowLabel} (${effectiveTitle}).`, 'warning');
          return;
        }

        queue.push({
          rowEl,
          unit_type: unitType,
          unit_title: effectiveTitle,
          session_count: sessionCount,
          source_text: sourceText,
          file: docFile,
        });
      }

      const workspace = await api(`/workflow/classes/${classId}`).catch(() => null);
      if (workspace?.active_unit) {
        showToast('Close the current active unit before applying full queue.', 'warning');
        return;
      }

      const rawStart = String(el.querySelector('#qp-start-date')?.value || '').trim();
      const resolvedStartDate = await _resolveStartDateKey(classId, rawStart);
      const resolvedStartEl = el.querySelector('#qp-resolved-start');
      if (resolvedStartEl) resolvedStartEl.value = resolvedStartDate;

      const horizonDays = _normalizeHorizonDays(el.querySelector('#qp-horizon-days')?.value || 365);
      let totalUnitsCreated = 0;
      let totalSessionsCreated = 0;
      let totalPending = 0;
      const warnings = [];

      for (let idx = 0; idx < queue.length; idx += 1) {
        const item = queue[idx];
        const maxSearchDays = Math.min(730, Math.max(120, Math.min(horizonDays, item.session_count * 21)));
        const setupForm = new FormData();
        setupForm.append('unit_type', String(item.unit_type));
        setupForm.append('unit_title', String(item.unit_title));
        setupForm.append('session_count', String(item.session_count));
        setupForm.append('start_date', String(resolvedStartDate));
        setupForm.append('skip_blocked_holidays', 'true');
        setupForm.append('max_search_days', String(maxSearchDays));
        setupForm.append('auto_check_items', 'true');
        if (item.source_text) {
          setupForm.append('source_text', item.source_text);
        }
        if (item.file) {
          setupForm.append('file', item.file);
        }

        const setupResult = await api(`/workflow/classes/${classId}/auto-setup-from-doc`, {
          method: 'POST',
          body: setupForm,
        });

        const createdCount = Number(setupResult?.created_count || 0);
        const failedCount = Number(setupResult?.failed_count || 0);
        const unitId = Number(setupResult?.target_unit_id || 0);
        totalUnitsCreated += 1;
        totalSessionsCreated += createdCount;
        totalPending += failedCount;

        if (unitId > 0) {
          try {
            await api(`/workflow/classes/${classId}/units/${unitId}/close`, { method: 'POST' });
          } catch (closeErr) {
            const closeMessage = String(closeErr?.message || '').toLowerCase();
            if (!(Number(closeErr?.status) === 409 && closeMessage.includes('already closed'))) {
              warnings.push(`Unit "${item.unit_title}" created but close failed.`);
            }
          }
        }

        item.rowEl.remove();
      }

      if (!rowsEl.querySelector('.qp-unit-row')) {
        addRow({ unit_type: 'chapter', unit_title: '', session_count: 6 });
      }

      if (warnings.length || totalPending > 0) {
        const warningText = warnings.length ? ` ${warnings[0]}` : '';
        showToast(`Created ${totalUnitsCreated} units and ${totalSessionsCreated} sessions, ${totalPending} pending.${warningText}`, 'warning');
      } else {
        showToast(`Created ${totalUnitsCreated} units and ${totalSessionsCreated} complete sessions.`, 'ok');
      }
    } catch (err) {
      showToast(String(err?.message || 'Failed to apply full queue plan.'), 'error');
    } finally {
      applyBtn.disabled = false;
    }
  });
}

