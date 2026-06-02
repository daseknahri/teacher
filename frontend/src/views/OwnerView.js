/**
 * OwnerView.js  Admin panel: teachers, analytics, class management
 * Teacher Progress App  Tailwind v4  FIXED API paths
 */
import { api, downloadWithAuth } from '../api/client.js';
import { isOwner } from '../state/auth.js';
import { setClasses } from '../state/class.js';
import { showToast } from '../utils/toast.js';
import { askConfirm } from '../utils/modal.js';
import { mountRetryCard } from '../utils/retryView.js';
import { generateStrongPassword, buildTeacherInviteText, copyText } from '../utils/password.js';
import { navigate } from '../router.js';
import { updateClassSelector } from '../components/AppShell.js';

let _teachers = [];
let _allClasses = [];
let _archivedClasses = [];
let _classTeachers = {}; // map classId  teacher_user_id
let _holidayYear = new Date().getFullYear();
let _ownerHolidays = [];
let _notebooklmStatus = null;
let _notebooklmSmoke = null;
let _ownerOverview = null;
let _selectedOwnerTeacherId = null;
let _ownerTeacherFilter = 'all';
let _ownerTeacherSearch = '';
let _ownerTeacherLimit = 8;
const OWNER_SELECTED_TEACHER_KEY = 'teacher_progress_owner_selected_teacher';

function _loadOwnerSelectedTeacherId() {
  if (_selectedOwnerTeacherId) return _selectedOwnerTeacherId;
  try {
    const stored = Number(localStorage.getItem(OWNER_SELECTED_TEACHER_KEY) || 0);
    if (stored > 0) _selectedOwnerTeacherId = stored;
  } catch {
    // Storage can be unavailable in restricted browser contexts.
  }
  return _selectedOwnerTeacherId;
}

function _setOwnerSelectedTeacherId(value) {
  const tid = Number(value || 0);
  _selectedOwnerTeacherId = tid > 0 ? tid : null;
  try {
    if (_selectedOwnerTeacherId) localStorage.setItem(OWNER_SELECTED_TEACHER_KEY, String(_selectedOwnerTeacherId));
    else localStorage.removeItem(OWNER_SELECTED_TEACHER_KEY);
  } catch {
    // Ignore storage failures; the in-memory selection still works.
  }
}

function _rebuildClassTeacherMap(classes) {
  _classTeachers = {};
  (Array.isArray(classes) ? classes : []).forEach(cls => {
    if (cls?.teacher_user_id) _classTeachers[cls.id] = cls.teacher_user_id;
  });
}

function _publishOwnerClassState({ activeClasses, archivedClasses }) {
  _allClasses = Array.isArray(activeClasses) ? activeClasses.filter(c => !c.is_archived) : [];
  _archivedClasses = Array.isArray(archivedClasses) ? archivedClasses.filter(c => c.is_archived) : [];
  _rebuildClassTeacherMap(_allClasses);
  setClasses(_allClasses);
  updateClassSelector();
}

function _escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function _fmtStatusTs(value) {
  if (!value) return 'Unknown';
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleString();
  } catch {
    return String(value);
  }
}

function _tsValue(value) {
  if (!value) return 0;
  try {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? 0 : d.getTime();
  } catch {
    return 0;
  }
}

export async function renderOwnerView() {
  _showChrome();
  if (!isOwner()) { navigate('class'); return; }
  const el = document.getElementById('app-content');
  el.innerHTML = `<div class="view-container"><div class="skeleton h-96 rounded-2xl animate-pulse"></div></div>`;

  try {
    const [overview, users] = await Promise.all([
      api('/classes/owner-overview'),
      api('/auth/users'),          // GET /auth/users   all users
    ]);
    _ownerOverview = overview || null;
    _teachers = (users || []).filter(u => u.role === 'teacher');
    // Load classes list separately
    const [classes, archived, holidays, notebooklmStatus] = await Promise.all([
      api('/classes'),
      api('/classes?include_archived=true'),
      api(`/workflow/holidays?year=${_holidayYear}&country_code=MA`).catch(() => []),
      api('/ops/notebooklm/status').catch(() => null),
    ]);
    _publishOwnerClassState({ activeClasses: classes || [], archivedClasses: archived || [] });
    _ownerHolidays = Array.isArray(holidays) ? holidays : [];
    _notebooklmStatus = notebooklmStatus || null;
  } catch {
    _ownerOverview = null;
    mountRetryCard(el, {
      title: 'Owner Panel Unavailable',
      message: 'Unable to load owner data right now. Retry after checking API connection.',
      buttonId: 'btn-retry-owner-load',
      onRetry: () => renderOwnerView(),
    });
    showToast('Failed to load owner panel data.', 'error');
    return;
  }

  _renderOwner(el);
}

function _renderOwner(el) {
  _loadOwnerSelectedTeacherId();
  const locked = _teachers.filter(t => t.is_active === false);
  const overviewCounts = _ownerOverview?.counts || {};
  const teacherStats = Array.isArray(_ownerOverview?.teachers) ? _ownerOverview.teachers : [];
  const operationRows = _ownerTeacherRows(teacherStats);
  const attentionRows = _ownerAttentionRows(operationRows);
  const classRows = _ownerClassRows();
  const classAttentionRows = classRows.filter(row => _ownerClassHealth(row).rank <= 5);
  const recentSessionRows = _ownerRecentSessionRows();
  const supervisionBrief = _ownerSupervisionBrief(operationRows, classRows, recentSessionRows);
  const filteredOperationRows = _ownerFilteredTeacherRows(operationRows);
  const visibleOperationRows = filteredOperationRows.slice(0, Math.max(1, Number(_ownerTeacherLimit || 8)));
  const defaultTeacher = operationRows.find(row => row.is_active !== false && _num(row.sessions, 0) > 0)
    || operationRows.find(row => row.is_active !== false && _num(row.assigned_classes, 0) > 0)
    || attentionRows[0]
    || operationRows[0]
    || null;
  const selectedTeacher = operationRows.find(row => Number(row.teacher_id) === Number(_selectedOwnerTeacherId))
    || defaultTeacher;
  const selectedTeacherId = Number(selectedTeacher?.teacher_id || 0);
  const teacherTotal = _num(overviewCounts.teachers, _teachers.length);
  const activeClassTotal = _num(overviewCounts.classes_active, _allClasses.length);
  const studentTotal = _num(overviewCounts.students, 0);
  const sessionTotal = _num(overviewCounts.sessions, 0);
  const examTotal = _num(overviewCounts.exams, 0);
  const runtimeHealth = _notebooklmStatus?.runtime_health || {};
  const refreshRequired = Boolean(runtimeHealth?.refresh_required);
  const lastSuccessTs = _tsValue(runtimeHealth?.last_success_at);
  const lastFailureTs = _tsValue(runtimeHealth?.last_error_at);
  const showActiveError = Boolean(runtimeHealth?.last_error_message) && (refreshRequired || lastFailureTs > lastSuccessTs);

  el.innerHTML = `
    <div class="view-container">

      <div class="rounded-[2rem] border border-slate-200 bg-white px-5 py-5 shadow-sm">
        <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div class="max-w-3xl">
            <div class="flex items-center gap-2 text-[12px] text-slate-400 mb-1">Admin</div>
            <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Supervisor Dashboard</p>
            <h1 class="mt-1 text-2xl font-bold text-slate-900 tracking-tight">Track one teacher clearly, then inspect the whole platform.</h1>
            <p class="mt-2 text-[13px] leading-6 text-slate-500">
              Select a teacher first. The dashboard shows their classes, recent sessions, next visible work, and then keeps platform analytics separate below.
            </p>
          </div>
          <div class="grid grid-cols-2 gap-2 text-[12px] text-slate-600 sm:grid-cols-4 xl:min-w-[560px]">
            ${_ownerQuickSignal('Teachers', teacherTotal, 'blue')}
            ${_ownerQuickSignal('Classes', activeClassTotal, 'green')}
            ${_ownerQuickSignal('Open sessions', _num(overviewCounts.open_sessions, 0), 'amber')}
            ${_ownerQuickSignal('Follow-up', attentionRows.length, attentionRows.length ? 'red' : 'green')}
          </div>
        </div>
      </div>

      ${_ownerTeacherFocusPanel(operationRows, selectedTeacher)}

      ${_ownerTeacherTrackerPanel(selectedTeacher)}

      ${_ownerAnalyticsPanel({
        lockedCount: locked.length,
        teacherTotal,
        activeClassTotal,
        studentTotal,
        sessionTotal,
        examTotal,
        overviewCounts,
        classRows,
        recentSessionRows,
      })}

      <div class="grid gap-4 xl:grid-cols-[1.05fr_.95fr]">
        ${_ownerSupervisorBriefPanel(supervisionBrief)}
        ${_ownerNeedsAttentionPanel(attentionRows, overviewCounts)}
      </div>

      <div class="grid gap-4 xl:grid-cols-[1.2fr_.8fr]">
        ${_ownerTeacherDirectoryPanel({
          operationRows,
          filteredOperationRows,
          visibleOperationRows,
          attentionRows,
          selectedTeacherId,
        })}
        ${_ownerRecentActivityPanel(_ownerTeacherRecentRows(selectedTeacher, recentSessionRows), selectedTeacher)}
      </div>

      ${_ownerClassSupervisionPanel(classRows, classAttentionRows)}

      <div class="card">
        <div class="card-header">
          <h3 class="font-semibold text-slate-700 text-[14px]">AI & NotebookLM Setup</h3>
        </div>
        <div class="card-body flex flex-col gap-3">
          <div class="flex items-center gap-2 flex-wrap">
            ${_notebooklmStatus?.ready
      ? '<span class="badge badge-green">Ready</span>'
      : '<span class="badge badge-amber">Needs Setup</span>'}
            ${refreshRequired
      ? '<span class="badge badge-red">Refresh Required</span>'
      : '<span class="badge badge-gray">Auth Healthy</span>'}
            ${_notebooklmStatus?.installed
      ? '<span class="badge badge-blue">Package Installed</span>'
      : '<span class="badge badge-red">Package Missing</span>'}
            <button id="btn-owner-notebooklm-refresh" class="btn btn-secondary btn-sm">Refresh Status</button>
            <button id="btn-owner-notebooklm-smoke" class="btn btn-secondary btn-sm">Run Smoke Test</button>
            <button id="btn-owner-notebooklm-helper" class="btn btn-secondary btn-sm">Download Refresh Helper</button>
            <button id="btn-owner-notebooklm-clean-temp" class="btn btn-secondary btn-sm">Clean Temp Notebooks</button>
            <button id="btn-owner-notebooklm-upload-auth" class="btn btn-primary btn-sm">Upload Auth File</button>
            <button id="btn-owner-notebooklm-clear-auth" class="btn btn-ghost btn-sm">Clear Auth</button>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3 text-[12px] text-slate-600 flex flex-col gap-2">
            <p><span class="font-semibold text-slate-700">Profile:</span> ${_escapeHtml(_notebooklmStatus?.profile || 'default')}</p>
            <p><span class="font-semibold text-slate-700">Auth file:</span> <span class="font-mono break-all">${_escapeHtml(_notebooklmStatus?.auth_path || 'unknown')}</span></p>
            <p><span class="font-semibold text-slate-700">Auth file found:</span> ${_notebooklmStatus?.auth_file_exists ? 'Yes' : 'No'}</p>
            <p><span class="font-semibold text-slate-700">Auth file valid:</span> ${_notebooklmStatus?.auth_file_valid ? 'Yes' : 'No'}</p>
            <p><span class="font-semibold text-slate-700">Auth last updated:</span> ${_notebooklmStatus?.auth_file_updated_at ? _escapeHtml(String(_notebooklmStatus.auth_file_updated_at)) : 'Unknown'}</p>
            ${_notebooklmStatus?.auth_file_error ? `<p class="text-red-600"><span class="font-semibold">Auth error:</span> ${_escapeHtml(_notebooklmStatus.auth_file_error)}</p>` : ''}
            <p><span class="font-semibold text-slate-700">Cookies detected:</span> ${Number(_notebooklmStatus?.cookies_count || 0)}</p>
            <p><span class="font-semibold text-slate-700">Context file:</span> <span class="font-mono break-all">${_escapeHtml(_notebooklmStatus?.context_path || 'unknown')}</span></p>
            <p><span class="font-semibold text-slate-700">Context last updated:</span> ${_notebooklmStatus?.context_file_updated_at ? _escapeHtml(String(_notebooklmStatus.context_file_updated_at)) : 'Unknown'}</p>
            <p><span class="font-semibold text-slate-700">Saved notebook context:</span> ${_notebooklmStatus?.context_notebook_id ? _escapeHtml(_notebooklmStatus.context_notebook_id) : 'None'}</p>
          </div>
          <div class="rounded-2xl border ${refreshRequired ? 'border-red-200 bg-red-50' : 'border-slate-200 bg-slate-50/80'} px-3 py-3 text-[12px] text-slate-700 flex flex-col gap-1">
            <p class="font-semibold text-slate-800">NotebookLM auth health</p>
            <p><span class="font-semibold">Refresh required:</span> ${refreshRequired ? 'Yes' : 'No'}</p>
            <p><span class="font-semibold">Last success:</span> ${_escapeHtml(_fmtStatusTs(runtimeHealth?.last_success_at))}</p>
            <p><span class="font-semibold">Last success source:</span> ${_escapeHtml(runtimeHealth?.last_success_source || '-')}</p>
            <p><span class="font-semibold">Last failure:</span> ${_escapeHtml(_fmtStatusTs(runtimeHealth?.last_error_at))}</p>
            <p><span class="font-semibold">Last failure source:</span> ${_escapeHtml(runtimeHealth?.last_error_source || '-')}</p>
            <p><span class="font-semibold">Last manual refresh:</span> ${_escapeHtml(_fmtStatusTs(runtimeHealth?.last_manual_refresh_at))}</p>
            ${showActiveError ? `<p class="${refreshRequired ? 'text-red-700' : 'text-amber-700'}"><span class="font-semibold">Current auth issue:</span> ${_escapeHtml(runtimeHealth.last_error_message)}</p>` : ''}
            ${!showActiveError && runtimeHealth?.last_error_message ? `<p class="text-slate-500"><span class="font-semibold">Previous issue:</span> Recovered after ${_escapeHtml(_fmtStatusTs(runtimeHealth?.last_success_at))}.</p>` : ''}
          </div>
          ${_notebooklmSmoke ? `
          <div class="rounded-2xl border ${_notebooklmSmoke?.smoke?.ok ? 'border-green-200 bg-green-50' : 'border-amber-200 bg-amber-50'} px-3 py-3 text-[12px] text-slate-700 flex flex-col gap-1">
            <p class="font-semibold text-slate-800">Live NotebookLM smoke test</p>
            <p><span class="font-semibold">Result:</span> ${_notebooklmSmoke?.smoke?.ok ? 'Success' : 'Failed'}</p>
            <p><span class="font-semibold">Server ready:</span> ${_notebooklmSmoke?.ready ? 'Yes' : 'No'}</p>
            <p><span class="font-semibold">Answer:</span> ${_escapeHtml(_notebooklmSmoke?.smoke?.answer || '-')}</p>
            ${_notebooklmSmoke?.smoke?.error_message ? `<p class="text-amber-700"><span class="font-semibold">Error:</span> ${_escapeHtml(_notebooklmSmoke.smoke.error_message)}</p>` : ''}
          </div>` : ''}
          <div class="rounded-2xl border border-blue-100 bg-blue-50 px-3 py-3 text-[12px] text-slate-700 flex flex-col gap-1">
            <p class="font-semibold text-slate-800">First-time Windows setup</p>
            <p>1. On your own Windows machine, run <span class="font-mono break-all">python -m notebooklm login</span>.</p>
            <p>2. Sign in to the Google account that can access NotebookLM.</p>
            <p>3. Find the generated file <span class="font-mono break-all">%USERPROFILE%\.notebooklm\profiles\default\storage_state.json</span>.</p>
            <p>4. In this panel, click <span class="font-mono break-all">Upload Auth File</span> and upload that file.</p>
            <p>5. Click <span class="font-mono break-all">Refresh Status</span> until this card shows <span class="font-mono break-all">Ready</span>.</p>
            <p>6. Faster refresh option: run <span class="font-mono break-all">python scripts/refresh_notebooklm_auth.py --app-url https://your-app --email owner@school.edu --run-login</span> from the backend folder on your own machine.</p>
            <p>7. Easiest option: click <span class="font-mono break-all">Download Refresh Helper</span>, then double-click the downloaded <span class="font-mono break-all">.cmd</span> file on your Windows machine.</p>
          </div>
        </div>
      </div>

      <!-- Holiday controls -->
      <div class="card">
        <div class="card-header">
          <h3 class="font-semibold text-slate-700 text-[14px]">Academic Calendar Controls</h3>
        </div>
        <div class="card-body flex flex-col gap-3">
          <div class="flex items-end gap-2 flex-wrap">
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Year</label>
              <input id="owner-holiday-year" type="number" min="2000" max="2100" step="1" value="${Number(_holidayYear || new Date().getFullYear())}" class="!w-28" />
            </div>
            <button id="btn-owner-holiday-refresh" class="btn btn-secondary btn-sm">Refresh</button>
            <button id="btn-owner-holiday-seed" class="btn btn-ghost btn-sm">Seed Fixed Holidays</button>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3 flex flex-col gap-2">
            <div class="flex gap-2 flex-wrap">
              <button id="btn-owner-holiday-export" class="btn btn-secondary btn-sm">Download Current Holidays</button>
              <button id="btn-owner-holiday-template" class="btn btn-ghost btn-sm">Download Blank Template</button>
              <button id="btn-owner-holiday-import" class="btn btn-primary btn-sm">Apply Excel To Calendar</button>
            </div>
            <p class="text-[12px] text-slate-500">Download the current holiday rows for the selected year, add or edit what you need in Excel, then apply the file back to the calendar.</p>
            <p class="text-[11px] text-slate-400">Imported rows merge into the standard Morocco calendar for the dates in the file. Accepted columns: <span class="font-mono">holiday</span>, <span class="font-mono">start_date</span>, <span class="font-mono">end_date</span>, <span class="font-mono">is_blocked</span>. A <span class="font-mono">dates</span> column is also accepted.</p>
          </div>
          <p class="text-[12px] text-slate-500">Toggle blocked/unblocked status here. Calendar and planning use these settings automatically.</p>
          <div class="max-h-[240px] overflow-auto border border-slate-200 rounded-xl">
            ${_ownerHolidays.length ? _ownerHolidays.map(row => `
              <div class="px-3 py-2 border-b border-slate-100 last:border-b-0 bg-white flex items-center gap-2">
                <div class="min-w-0 flex-1">
                  <p class="text-[12px] font-semibold text-slate-700">${row.holiday_date ? String(row.holiday_date) : '-'}</p>
                  <p class="text-[12px] text-slate-500 truncate">${row.name || 'Holiday'}</p>
                </div>
                ${row.is_blocked ? '<span class="badge badge-red">Blocked</span>' : '<span class="badge badge-gray">Open</span>'}
                <button class="btn btn-ghost btn-sm btn-owner-holiday-toggle" data-holiday-id="${Number(row.id || 0)}" data-blocked="${row.is_blocked ? '1' : '0'}">${row.is_blocked ? 'Unblock' : 'Block'}</button>
              </div>
            `).join('') : '<p class="text-[12px] text-slate-500 px-3 py-3">No holidays loaded for this year.</p>'}
          </div>
        </div>
      </div>

      <!-- Teacher management -->
      <div class="card">
        <div class="card-header">
          <h3 class="font-semibold text-slate-700 text-[14px]">Teacher Accounts</h3>
        </div>
        <div id="teacher-list" class="divide-y divide-slate-100">
          ${_teachers.length ? _teachers.map(t => _teacherRow(t)).join('') : `
          <div class="empty-state py-12">
            <div class="text-xl font-black opacity-30">TCH</div>
            <p class="text-[13px] text-slate-400">No teachers yet. Create one below.</p>
          </div>`}
        </div>
      </div>

      <!-- Create teacher form -->
      <div class="card">
        <div class="card-header">
          <h3 class="font-semibold text-slate-700 text-[14px]">Create Teacher Account</h3>
        </div>
        <div class="card-body flex flex-col gap-3">
          <div class="grid sm:grid-cols-2 gap-3">
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Full name</label>
              <input id="new-teacher-name" type="text" placeholder="First Last" />
            </div>
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Email</label>
              <input id="new-teacher-email" type="email" placeholder="teacher@school.edu" />
            </div>
          </div>
          <div class="flex flex-col gap-1.5">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Temporary password</label>
            <div class="flex gap-2">
              <input id="new-teacher-pwd" type="text" placeholder="Auto-generated" class="flex-1" />
              <button id="btn-gen-pwd"
                class="btn btn-secondary btn-sm flex-shrink-0">Generate</button>
            </div>
          </div>
          <div class="flex gap-2 flex-wrap mt-1">
            <button id="btn-create-teacher" class="btn btn-primary">Create Teacher</button>
            <button id="btn-copy-invite" class="btn btn-secondary">Copy Invite</button>
          </div>
          <div id="invite-preview" class="hidden p-3 bg-slate-50 rounded-xl border border-slate-200
               text-[12px] text-slate-500 font-mono whitespace-pre-wrap leading-relaxed"></div>
        </div>
      </div>

      <!-- Class-Teacher Assignments -->
      ${_allClasses.length ? `
      <div class="card">
        <div class="card-header">
          <h3 class="font-semibold text-slate-700 text-[14px]">Class Ownership Assignments</h3>
        </div>
        <div class="card-body flex flex-col gap-2">
          ${_allClasses.map(c => {
    const assignedId = _classTeachers[c.id];
    const assigned = assignedId ? _teachers.find(t => t.id === assignedId) : null;
    return `
            <div class="flex items-center gap-3 px-4 py-3 bg-slate-50 rounded-xl border border-slate-100">
              <div class="flex-1 min-w-0">
                <p class="text-[13px] font-semibold text-slate-800 truncate">${c.name}</p>
                ${assigned ? `<p class="text-[12px] text-slate-400">${assigned.full_name}</p>` : `<p class="text-[12px] text-slate-400 italic">Unassigned</p>`}
              </div>
              <select class="!h-8 !text-[12px] !w-44 class-teacher-select" data-class-id="${c.id}">
                <option value="">No teacher</option>
                ${_teachers.map(t => `<option value="${t.id}" ${assignedId === t.id ? 'selected' : ''}>${t.full_name}</option>`).join('')}
              </select>
              <button class="btn btn-secondary btn-sm btn-assign-teacher" data-class-id="${c.id}" title="Save assignment">Save</button>
            </div>`;
  }).join('')}
        </div>
      </div>

      ` : ''}

      <!-- Archived classes restore -->
      ${_archivedClasses.length ? `
      <div class="card">
        <div class="card-header">
          <h3 class="font-semibold text-slate-700 text-[14px]">Archived Classes</h3>
        </div>
        <div class="card-body flex flex-col gap-2">
          ${_archivedClasses.map(c => `
          <div class="flex items-center gap-3 px-4 py-3 bg-slate-50 rounded-xl border border-slate-200">
            <span class="flex-1 text-[13px] text-slate-600 font-medium">${c.name}</span>
            <span class="badge badge-gray">Archived</span>
            <button class="btn btn-secondary btn-sm btn-restore" data-class-id="${c.id}">Restore</button>
          </div>`).join('')}
        </div>
      </div>` : ''}

      <!-- Change Password -->
      <div class="card">
        <div class="card-header">
          <h3 class="font-semibold text-slate-700 text-[14px]">Owner Password</h3>
        </div>
        <div class="card-body flex flex-col gap-3">
          <div class="grid sm:grid-cols-2 gap-3">
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Current Password</label>
              <input id="chg-pwd-current" type="password" placeholder="Current password" autocomplete="current-password" />
            </div>
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">New Password</label>
              <input id="chg-pwd-new" type="password" placeholder="New password (min 8 chars)" autocomplete="new-password" />
            </div>
          </div>
          <p id="chg-pwd-error" class="text-[12px] text-red-600 hidden"></p>
          <button id="btn-change-pwd" class="btn btn-primary self-start">Update Password</button>
        </div>
      </div>

    </div>`;

  _bindOwnerEvents(el);
}

function _teacherRow(t) {
  const isActive = t.is_active !== false;
  const initials = (t.full_name || 'T').charAt(0).toUpperCase();
  return `
    <div class="teacher-row" data-tid="${t.id}">
      <div class="w-9 h-9 rounded-full bg-blue-100 flex items-center justify-center
                  text-[13px] font-bold text-blue-700 flex-shrink-0">${initials}</div>
      <div class="flex-1 min-w-0">
        <p class="text-[13px] font-semibold text-slate-800 truncate">${t.full_name || 'N/A'}</p>
        <p class="text-[12px] text-slate-400 truncate">${t.email}</p>
      </div>
      ${isActive
      ? '<span class="badge badge-green"> Active</span>'
      : '<span class="badge badge-red">Locked</span>'}
      <div class="flex gap-2 flex-wrap">
        <button class="btn btn-ghost btn-sm btn-send-invite" data-tid="${t.id}" title="Send invite email">Invite</button>
        <button class="btn btn-ghost btn-sm btn-reset-pwd" data-tid="${t.id}" title="Reset password">Reset</button>
        ${isActive
      ? `<button class="btn btn-ghost btn-sm !text-amber-600 btn-lock" data-tid="${t.id}">Lock</button>`
      : `<button class="btn btn-secondary btn-sm btn-unlock" data-tid="${t.id}">Unlock</button>`}
        <button class="btn btn-ghost btn-sm !text-red-500 btn-delete" data-tid="${t.id}">Delete</button>
      </div>
    </div>`;
}

function _kpi(icon, value, label, border = 'border-l-slate-300') {
  return `
    <div class="kpi-card border-l-4 ${border}">
      <div class="text-2xl">${icon}</div>
      <div class="text-[26px] font-bold text-slate-800 leading-none tracking-tight mt-1">${value}</div>
      <div class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">${label}</div>
    </div>`;
}

function _num(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function _daysSince(value) {
  if (!value) return null;
  const d = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return null;
  return Math.floor((Date.now() - d.getTime()) / 86400000);
}

function _fmtOwnerDate(value) {
  if (!value) return 'No session yet';
  try {
    const d = new Date(`${String(value).slice(0, 10)}T00:00:00`);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
  } catch {
    return String(value);
  }
}

function _ownerTeacherRows(statsRows) {
  const rows = Array.isArray(statsRows) && statsRows.length
    ? statsRows
    : _teachers.map(t => ({
      teacher_id: t.id,
      full_name: t.full_name,
      email: t.email,
      is_active: t.is_active,
      assigned_classes: 0,
      active_classes: 0,
      students: 0,
      sessions: 0,
      exams: 0,
      last_session_date: null,
      class_names: [],
    }));
  return rows
    .map(row => ({ ...row, _health: _ownerTeacherHealth(row) }))
    .sort((a, b) => {
      if (a._health.rank !== b._health.rank) return a._health.rank - b._health.rank;
      const lastDiff = _tsValue(b.last_session_date) - _tsValue(a.last_session_date);
      if (lastDiff) return lastDiff;
      return String(a.full_name || a.email || '').localeCompare(String(b.full_name || b.email || ''));
    });
}

function _ownerTeacherHealth(row) {
  const assignedClasses = _num(row.assigned_classes, 0);
  const sessions = _num(row.sessions, 0);
  const students = _num(row.students, 0);
  const activeUnits = _num(row.active_units, 0);
  const days = _daysSince(row.last_session_date);
  if (row.is_active === false) {
    return { rank: 0, label: 'Locked', badgeClass: 'badge-red', reason: 'Account is locked and cannot be used.' };
  }
  if (assignedClasses <= 0) {
    return { rank: 1, label: 'No class', badgeClass: 'badge-amber', reason: 'Teacher has no assigned class yet.' };
  }
  if (students <= 0) {
    return { rank: 2, label: 'No roster', badgeClass: 'badge-amber', reason: 'Assigned classes do not have students yet.' };
  }
  if (sessions <= 0) {
    return { rank: 3, label: 'No sessions', badgeClass: 'badge-amber', reason: 'Teacher has classes but no recorded sessions yet.' };
  }
  if (days != null && days > 21) {
    return { rank: 4, label: 'Quiet', badgeClass: 'badge-gray', reason: `Last session was ${days} days ago.` };
  }
  if (activeUnits > 0) {
    return { rank: 5, label: 'Teaching', badgeClass: 'badge-green', reason: 'Active workflow units are in progress.' };
  }
  return { rank: 6, label: 'Active', badgeClass: 'badge-blue', reason: 'Recent activity recorded.' };
}

function _ownerAttentionRows(rows) {
  return (Array.isArray(rows) ? rows : []).filter(row => _ownerTeacherHealth(row).rank <= 4);
}

function _ownerFilteredTeacherRows(rows) {
  const search = String(_ownerTeacherSearch || '').trim().toLowerCase();
  return (Array.isArray(rows) ? rows : []).filter(row => {
    const health = row._health || _ownerTeacherHealth(row);
    if (_ownerTeacherFilter === 'attention' && health.rank > 4) return false;
    if (_ownerTeacherFilter === 'locked' && row.is_active !== false) return false;
    if (_ownerTeacherFilter === 'no_class' && health.rank !== 1) return false;
    if (_ownerTeacherFilter === 'quiet' && health.rank !== 4) return false;
    if (!search) return true;
    const haystack = [
      row.full_name,
      row.email,
      row.class_names,
      (Array.isArray(row.classes) ? row.classes.map(cls => cls?.name) : []),
    ].flat().filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(search);
  });
}

function _ownerFilterButton(filter, label, count) {
  const active = _ownerTeacherFilter === filter;
  return `
    <button class="btn ${active ? 'btn-primary' : 'btn-ghost'} btn-sm btn-owner-teacher-filter"
      data-filter="${_escapeHtml(filter)}">
      ${_escapeHtml(label)} <span class="ml-1 opacity-70">${Number(count || 0)}</span>
    </button>`;
}

function _ownerSupervisionBrief(teacherRows, classRows, recentRows) {
  const teachers = Array.isArray(teacherRows) ? teacherRows : [];
  const classes = Array.isArray(classRows) ? classRows : [];
  const recent = Array.isArray(recentRows) ? recentRows : [];
  const lockedTeachers = teachers.filter(row => row.is_active === false);
  const teachersNoClass = teachers.filter(row => _ownerTeacherHealth(row).rank === 1);
  const teachersNoRoster = teachers.filter(row => _ownerTeacherHealth(row).rank === 2);
  const teachersNoSessions = teachers.filter(row => _ownerTeacherHealth(row).rank === 3);
  const quietTeachers = teachers.filter(row => _ownerTeacherHealth(row).rank === 4);
  const unassignedClasses = classes.filter(row => _ownerClassHealth(row).rank === 0);
  const lockedTeacherClasses = classes.filter(row => _ownerClassHealth(row).rank === 1);
  const noRosterClasses = classes.filter(row => _ownerClassHealth(row).rank === 2);
  const noSessionClasses = classes.filter(row => _ownerClassHealth(row).rank === 3);
  const quietClasses = classes.filter(row => _ownerClassHealth(row).rank === 5);
  const openSessions = recent.filter(row => row.is_open);
  const recentWithoutChecklist = recent.filter(row => _num(row.checked_session_rows, 0) <= 0);
  const priorities = [
    ...lockedTeachers.slice(0, 2).map(row => `Unlock or confirm locked teacher: ${row.full_name || row.email}`),
    ...unassignedClasses.slice(0, 2).map(row => `Assign a teacher to ${row.name}`),
    ...lockedTeacherClasses.slice(0, 2).map(row => `Fix locked teacher assigned to ${row.name}`),
    ...teachersNoClass.slice(0, 2).map(row => `Assign class to ${row.full_name || row.email}`),
    ...openSessions.slice(0, 2).map(row => `Close open session for ${row.class_name}`),
    ...noRosterClasses.slice(0, 2).map(row => `Import roster for ${row.name}`),
  ].slice(0, 5);
  return {
    priorities,
    teacher: {
      locked: lockedTeachers.length,
      noClass: teachersNoClass.length,
      noRoster: teachersNoRoster.length,
      noSessions: teachersNoSessions.length,
      quiet: quietTeachers.length,
    },
    class: {
      unassigned: unassignedClasses.length,
      lockedTeacher: lockedTeacherClasses.length,
      noRoster: noRosterClasses.length,
      noSessions: noSessionClasses.length,
      quiet: quietClasses.length,
    },
    recent: {
      total: recent.length,
      open: openSessions.length,
      withoutChecklist: recentWithoutChecklist.length,
    },
  };
}

function _ownerSupervisorBriefPanel(brief) {
  const priorityRows = Array.isArray(brief?.priorities) ? brief.priorities : [];
  const hasWork = priorityRows.length > 0;
  return `
    <div class="rounded-3xl border ${hasWork ? 'border-amber-200 bg-amber-50/40' : 'border-green-200 bg-green-50/40'} px-5 py-4 shadow-sm">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap">
            <p class="text-[11px] font-semibold uppercase tracking-[0.18em] ${hasWork ? 'text-amber-600' : 'text-green-700'}">Supervisor Brief</p>
            <span class="badge ${hasWork ? 'badge-amber' : 'badge-green'}">${hasWork ? `${priorityRows.length} priority item${priorityRows.length === 1 ? '' : 's'}` : 'No urgent action'}</span>
          </div>
          <h2 class="mt-1 text-lg font-bold text-slate-900">What should be checked first today</h2>
          <div class="mt-3 grid gap-2">
            ${priorityRows.length ? priorityRows.map((item, idx) => `
              <div class="rounded-2xl border border-white/70 bg-white px-3 py-2 text-[13px] text-slate-700">
                <span class="font-bold text-slate-900">${idx + 1}.</span> ${_escapeHtml(item)}
              </div>`).join('') : `
              <div class="rounded-2xl border border-white/70 bg-white px-3 py-2 text-[13px] text-slate-600">
                Teacher accounts, class assignment, recent activity, and core setup signals do not show urgent gaps.
              </div>`}
          </div>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-2 min-w-0 xl:w-[520px] xl:flex-shrink-0">
          <div class="rounded-2xl border border-white/70 bg-white px-3 py-3">
            <p class="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Teachers</p>
            <p class="mt-1 text-[12px] text-slate-600">${_num(brief?.teacher?.locked, 0)} locked</p>
            <p class="text-[12px] text-slate-600">${_num(brief?.teacher?.noClass, 0)} no class</p>
            <p class="text-[12px] text-slate-600">${_num(brief?.teacher?.quiet, 0)} quiet</p>
          </div>
          <div class="rounded-2xl border border-white/70 bg-white px-3 py-3">
            <p class="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Classes</p>
            <p class="mt-1 text-[12px] text-slate-600">${_num(brief?.class?.unassigned, 0)} unassigned</p>
            <p class="text-[12px] text-slate-600">${_num(brief?.class?.noRoster, 0)} no roster</p>
            <p class="text-[12px] text-slate-600">${_num(brief?.class?.lockedTeacher, 0)} locked teacher</p>
          </div>
          <div class="rounded-2xl border border-white/70 bg-white px-3 py-3">
            <p class="text-[11px] uppercase tracking-wider text-slate-400 font-semibold">Sessions</p>
            <p class="mt-1 text-[12px] text-slate-600">${_num(brief?.recent?.total, 0)} recent</p>
            <p class="text-[12px] text-slate-600">${_num(brief?.recent?.open, 0)} open</p>
            <p class="text-[12px] text-slate-600">${_num(brief?.recent?.withoutChecklist, 0)} no checklist</p>
          </div>
          <button id="btn-owner-copy-brief" class="btn btn-secondary btn-sm sm:col-span-3">Copy Supervisor Brief</button>
        </div>
      </div>
    </div>`;
}

function _ownerSupervisorBriefText() {
  const brief = _ownerSupervisionBrief(_ownerTeacherRows(Array.isArray(_ownerOverview?.teachers) ? _ownerOverview.teachers : []), _ownerClassRows(), _ownerRecentSessionRows());
  const lines = ['Supervisor brief'];
  lines.push('');
  if (brief.priorities.length) {
    brief.priorities.forEach((item, idx) => lines.push(`${idx + 1}. ${item}`));
  } else {
    lines.push('No urgent supervisor actions detected.');
  }
  lines.push('');
  lines.push(`Teachers: ${brief.teacher.locked} locked, ${brief.teacher.noClass} no class, ${brief.teacher.quiet} quiet.`);
  lines.push(`Classes: ${brief.class.unassigned} unassigned, ${brief.class.noRoster} no roster, ${brief.class.lockedTeacher} with locked teacher.`);
  lines.push(`Sessions: ${brief.recent.total} recent, ${brief.recent.open} open, ${brief.recent.withoutChecklist} without checked checklist rows.`);
  return lines.join('\n');
}

function _ownerQuickSignal(label, value, tone = 'slate') {
  const toneMap = {
    blue: 'bg-blue-50 border-blue-100 text-blue-800',
    green: 'bg-green-50 border-green-100 text-green-800',
    amber: 'bg-amber-50 border-amber-100 text-amber-800',
    red: 'bg-red-50 border-red-100 text-red-800',
    slate: 'bg-slate-50 border-slate-100 text-slate-800',
  };
  return `
    <div class="rounded-2xl border ${toneMap[tone] || toneMap.slate} px-3 py-3">
      <p class="text-[22px] font-black leading-none">${_escapeHtml(value)}</p>
      <p class="mt-1 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">${_escapeHtml(label)}</p>
    </div>`;
}

function _ownerTeacherSessionRows(row) {
  if (Array.isArray(row?.recent_sessions)) return row.recent_sessions;
  return [];
}

function _ownerTeacherTimetableRows(row) {
  if (Array.isArray(row?.timetable_rules)) return row.timetable_rules;
  return [];
}

function _ownerTeacherRecentRows(row, fallbackRows = []) {
  const ownRows = _ownerTeacherSessionRows(row);
  if (ownRows.length) return ownRows;
  const teacherId = Number(row?.teacher_id || 0);
  if (!teacherId) return Array.isArray(fallbackRows) ? fallbackRows : [];
  return (Array.isArray(fallbackRows) ? fallbackRows : []).filter(item => Number(item.teacher_user_id || 0) === teacherId);
}

function _ownerTeacherFocusPanel(rows, selectedTeacher) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const selectedId = Number(selectedTeacher?.teacher_id || 0);
  const health = selectedTeacher ? (selectedTeacher._health || _ownerTeacherHealth(selectedTeacher)) : null;
  return `
    <div class="rounded-[2rem] border border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-blue-950 px-5 py-5 text-white shadow-sm">
      <div class="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,.9fr)] xl:items-end">
        <div>
          <p class="text-[11px] font-semibold uppercase tracking-[0.2em] text-blue-200/80">Teacher focus</p>
          <h2 class="mt-2 text-2xl font-bold tracking-tight">${_escapeHtml(selectedTeacher?.full_name || selectedTeacher?.email || 'Select a teacher')}</h2>
          <p class="mt-2 max-w-2xl text-[13px] leading-6 text-slate-300">
            This is the supervisor lens. Change the teacher here, then read only this teacher's calendar, sessions, classes, and next move.
          </p>
          <div class="mt-4 flex flex-wrap gap-2">
            ${health ? `<span class="badge ${health.badgeClass}">${_escapeHtml(health.label)}</span>` : '<span class="badge badge-gray">No teacher selected</span>'}
            ${selectedTeacher ? `<span class="rounded-full bg-white/10 px-3 py-1 text-[12px] font-semibold text-white">${_num(selectedTeacher.assigned_classes, 0)} classes</span>` : ''}
            ${selectedTeacher ? `<span class="rounded-full bg-white/10 px-3 py-1 text-[12px] font-semibold text-white">${_num(selectedTeacher.sessions, 0)} sessions</span>` : ''}
            ${selectedTeacher ? `<span class="rounded-full bg-white/10 px-3 py-1 text-[12px] font-semibold text-white">${_num(selectedTeacher.open_sessions, 0)} open</span>` : ''}
          </div>
        </div>
        <div class="rounded-3xl border border-white/10 bg-white/10 p-4 backdrop-blur">
          <label class="text-[10px] font-bold uppercase tracking-[0.18em] text-blue-100">Select teacher to inspect</label>
          <select id="owner-teacher-focus-select" class="mt-2 !h-11 !rounded-2xl !border-white/15 !bg-white !text-[14px] !font-semibold !text-slate-900">
            ${safeRows.length ? safeRows.map(row => `
              <option value="${Number(row.teacher_id || 0)}" ${Number(row.teacher_id || 0) === selectedId ? 'selected' : ''}>
                ${_escapeHtml(row.full_name || row.email || 'Teacher')}
              </option>`).join('') : '<option value="">No teachers</option>'}
          </select>
          <p class="mt-3 text-[12px] leading-5 text-blue-100/80">
            The directory filters below do not change this selection unless you click Inspect or choose a teacher here.
          </p>
        </div>
      </div>
    </div>`;
}

function _ownerLocalDateKey(dateValue) {
  const d = dateValue instanceof Date ? dateValue : new Date(dateValue);
  if (Number.isNaN(d.getTime())) return '';
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function _ownerSessionDateTime(row) {
  const datePart = String(row?.session_date || row?.date || '').trim();
  if (!datePart) return null;
  const timePart = String(row?.start_time || '00:00').slice(0, 5) || '00:00';
  const d = new Date(`${datePart}T${timePart}:00`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function _ownerWeekStart(value = new Date()) {
  const d = value instanceof Date ? new Date(value) : new Date(value);
  if (Number.isNaN(d.getTime())) return new Date();
  d.setHours(0, 0, 0, 0);
  const day = d.getDay() || 7;
  d.setDate(d.getDate() - day + 1);
  return d;
}

function _ownerWeekDays(value = new Date()) {
  const start = _ownerWeekStart(value);
  return Array.from({ length: 7 }, (_, idx) => {
    const d = new Date(start);
    d.setDate(start.getDate() + idx);
    return d;
  });
}

function _ownerRuleWeekdayForDate(dateValue) {
  const d = dateValue instanceof Date ? dateValue : new Date(dateValue);
  if (Number.isNaN(d.getTime())) return null;
  return d.getDay() || 7;
}

function _ownerShortDayLabel(dateValue) {
  try {
    return new Intl.DateTimeFormat(undefined, { weekday: 'short' }).format(dateValue);
  } catch {
    return String(dateValue || '').slice(0, 3);
  }
}

function _ownerShortDateLabel(dateValue) {
  try {
    return new Intl.DateTimeFormat(undefined, { day: '2-digit', month: 'short' }).format(dateValue);
  } catch {
    return _ownerLocalDateKey(dateValue);
  }
}

function _ownerNextTeacherSession(row) {
  const now = new Date();
  const upcoming = _ownerTeacherSessionRows(row)
    .map(session => ({ session, date: _ownerSessionDateTime(session) }))
    .filter(item => item.date && (item.session?.is_open || item.date.getTime() >= now.getTime() - 15 * 60 * 1000))
    .sort((a, b) => a.date.getTime() - b.date.getTime());
  return upcoming[0]?.session || null;
}

function _ownerNextTimetableSlot(row) {
  const rules = _ownerTeacherTimetableRows(row);
  if (!rules.length) return null;
  const now = new Date();
  const candidates = [];
  for (let offset = 0; offset < 14; offset += 1) {
    const d = new Date(now);
    d.setHours(0, 0, 0, 0);
    d.setDate(now.getDate() + offset);
    const dayKey = _ownerLocalDateKey(d);
    const weekday = _ownerRuleWeekdayForDate(d);
    rules.forEach(rule => {
      if (Number(rule.weekday || 0) !== weekday) return;
      if (rule.effective_from && dayKey < String(rule.effective_from)) return;
      if (rule.effective_to && dayKey > String(rule.effective_to)) return;
      const start = String(rule.start_time || '00:00').slice(0, 5);
      const slotDate = new Date(`${dayKey}T${start}:00`);
      if (Number.isNaN(slotDate.getTime()) || slotDate.getTime() < now.getTime() - 15 * 60 * 1000) return;
      candidates.push({ ...rule, session_date: dayKey, _slotDate: slotDate });
    });
  }
  candidates.sort((a, b) => a._slotDate.getTime() - b._slotDate.getTime());
  return candidates[0] || null;
}

function _ownerSessionStatusBadge(row) {
  const when = _ownerSessionDateTime(row);
  const now = Date.now();
  if (when && when.getTime() >= now + 15 * 60 * 1000) return '<span class="badge badge-blue">Planned</span>';
  if (row?.is_open) return '<span class="badge badge-amber">Open / unclosed</span>';
  if (when && when.getTime() >= now - 15 * 60 * 1000) return '<span class="badge badge-blue">Planned</span>';
  return '<span class="badge badge-green">Recorded</span>';
}

function _ownerTeacherNextMove(row) {
  const health = row ? (row._health || _ownerTeacherHealth(row)) : null;
  if (!row) return 'Select a teacher to see the next supervision move.';
  const nextSession = _ownerNextTeacherSession(row);
  const nextSlot = _ownerNextTimetableSlot(row);
  if (row.is_active === false) return 'Account is locked. Unlock only if the teacher should use the platform now.';
  if (_num(row.assigned_classes, 0) <= 0) return 'Assign a class before expecting teaching data.';
  if (_num(row.students, 0) <= 0) return 'Import or verify the student roster before judging classroom activity.';
  if (nextSession) {
    const title = nextSession.unit_title || nextSession.class_name || 'next planned session';
    if (nextSession.is_open && !_ownerSessionIsFuture(nextSession)) {
      return `Close or review ${title} from ${_fmtOwnerDate(nextSession.session_date)} at ${_ownerSessionTimeLabel(nextSession)} before judging the next plan.`;
    }
    return `Review ${title} before ${_fmtOwnerDate(nextSession.session_date)} at ${_ownerSessionTimeLabel(nextSession)}.`;
  }
  if (nextSlot) {
    return `Timetable shows ${nextSlot.class_name} at ${String(nextSlot.start_time).slice(0, 5)}. Ask the teacher to plan or record this session.`;
  }
  return health?.reason || 'No urgent supervisor action.';
}

function _ownerTeacherTrackerPanel(row) {
  if (!row) {
    return `
      <div class="card">
        <div class="card-body">
          <p class="text-[13px] text-slate-500">Create or select a teacher to start the tracker.</p>
        </div>
      </div>`;
  }
  const health = row._health || _ownerTeacherHealth(row);
  const pct = _ownerProgressPct(row);
  const avg = row.average_exam_score == null ? null : Number(row.average_exam_score);
  const avgLabel = avg == null || Number.isNaN(avg) ? '-' : avg.toFixed(avg % 1 === 0 ? 0 : 1);
  const nextSession = _ownerNextTeacherSession(row);
  const nextSlot = nextSession ? null : _ownerNextTimetableSlot(row);
  const sessions = _ownerTeacherSessionRows(row);
  const rules = _ownerTeacherTimetableRows(row);
  const classes = _ownerClassDetailRows(row);
  return `
    <div class="grid gap-4 xl:grid-cols-[.9fr_1.35fr]">
      <div class="card overflow-hidden">
        <div class="card-header bg-slate-50/80">
          <div>
            <h3 class="font-semibold text-slate-800 text-[15px]">Selected Teacher</h3>
            <p class="text-[12px] text-slate-400 mt-1">Clear operational profile for the supervisor.</p>
          </div>
          <span class="badge ${health.badgeClass}">${_escapeHtml(health.label)}</span>
        </div>
        <div class="card-body flex flex-col gap-4">
          <div>
            <p class="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-semibold">Teacher</p>
            <h4 class="mt-1 text-xl font-bold text-slate-900">${_escapeHtml(row.full_name || row.email || 'Teacher')}</h4>
            <p class="mt-1 text-[13px] text-slate-500 break-all">${_escapeHtml(row.email || '')}</p>
          </div>
          <div class="grid grid-cols-2 gap-2">
            ${_ownerSmallStat('Classes', _num(row.assigned_classes, 0), 'blue')}
            ${_ownerSmallStat('Students', _num(row.students, 0), 'slate')}
            ${_ownerSmallStat('Sessions', _num(row.sessions, 0), 'green')}
            ${_ownerSmallStat('Open', _num(row.open_sessions, 0), _num(row.open_sessions, 0) ? 'amber' : 'slate')}
            ${_ownerSmallStat('Progress', pct == null ? '-' : `${pct}%`, pct == null ? 'slate' : 'green')}
            ${_ownerSmallStat('Exam avg', avgLabel, 'slate')}
          </div>
          <div class="rounded-3xl border border-blue-100 bg-blue-50 px-4 py-4">
            <p class="text-[11px] uppercase tracking-[0.18em] text-blue-500 font-bold">Supervisor next move</p>
            <p class="mt-2 text-[14px] leading-6 text-slate-800">${_escapeHtml(_ownerTeacherNextMove(row))}</p>
          </div>
          <div class="grid gap-2">
            <p class="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-semibold">Assigned classes</p>
            ${classes.length ? classes.slice(0, 4).map(cls => `
              <div class="rounded-2xl border border-slate-200 bg-white px-3 py-3">
                <div class="flex items-start justify-between gap-2">
                  <div class="min-w-0">
                    <p class="text-[13px] font-semibold text-slate-800 truncate">${_escapeHtml(cls.name || 'Class')}</p>
                    <p class="mt-1 text-[12px] text-slate-400">${_escapeHtml([cls.level, cls.subject].filter(Boolean).join(' - ') || 'No level/subject')}</p>
                  </div>
                  ${cls.is_archived ? '<span class="badge badge-gray">Archived</span>' : '<span class="badge badge-green">Active</span>'}
                </div>
              </div>`).join('') : '<p class="text-[13px] text-slate-500">No assigned class yet.</p>'}
          </div>
        </div>
      </div>

      <div class="card overflow-hidden">
        <div class="card-header bg-white">
          <div>
            <h3 class="font-semibold text-slate-800 text-[15px]">Teacher Calendar Tracker</h3>
            <p class="text-[12px] text-slate-400 mt-1">Week view for visible sessions and timetable expectations.</p>
          </div>
          <div class="flex gap-2 flex-wrap justify-end">
            <span class="badge badge-blue">${sessions.length} session row${sessions.length === 1 ? '' : 's'}</span>
            <span class="badge badge-gray">${rules.length} timetable slot${rules.length === 1 ? '' : 's'}</span>
          </div>
        </div>
        <div class="card-body flex flex-col gap-4">
          ${_ownerNextSessionCard(nextSession, nextSlot)}
          ${_ownerTeacherCoverageStrip(row, sessions, rules)}
          ${_ownerTeacherWeekGrid(row)}
        </div>
      </div>
    </div>`;
}

function _ownerNextSessionCard(nextSession, nextSlot) {
  if (nextSession) {
    const needsClosure = nextSession.is_open && !_ownerSessionIsFuture(nextSession);
    const label = needsClosure ? 'Session needs closure' : 'Next visible session';
    return `
      <div class="rounded-3xl border border-blue-200 bg-gradient-to-br from-blue-50 to-white px-4 py-4">
        <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p class="text-[11px] uppercase tracking-[0.18em] text-blue-500 font-bold">${_escapeHtml(label)}</p>
            <h4 class="mt-1 text-lg font-bold text-slate-900">${_escapeHtml(nextSession.unit_title || nextSession.class_name || 'Planned session')}</h4>
            <p class="mt-1 text-[13px] text-slate-500">
              ${_escapeHtml(nextSession.class_name || 'Class')} - ${_escapeHtml(_fmtOwnerDate(nextSession.session_date))} - ${_escapeHtml(_ownerSessionTimeLabel(nextSession))}
            </p>
          </div>
          <div class="flex gap-2 flex-wrap">
            ${_ownerSessionStatusBadge(nextSession)}
            ${nextSession.unit_session_number ? `<span class="badge badge-blue">Unit Session ${Number(nextSession.unit_session_number)}</span>` : ''}
            <span class="badge badge-gray">${_num(nextSession.checked_session_rows, 0)} checked</span>
          </div>
        </div>
      </div>`;
  }
  if (nextSlot) {
    return `
      <div class="rounded-3xl border border-amber-200 bg-amber-50 px-4 py-4">
        <p class="text-[11px] uppercase tracking-[0.18em] text-amber-600 font-bold">Next timetable slot</p>
        <h4 class="mt-1 text-lg font-bold text-slate-900">${_escapeHtml(nextSlot.class_name || 'Class slot')}</h4>
        <p class="mt-1 text-[13px] text-slate-600">
          ${_escapeHtml(_fmtOwnerDate(nextSlot.session_date))} - ${_escapeHtml(String(nextSlot.start_time || '').slice(0, 5))}${nextSlot.end_time ? `-${_escapeHtml(String(nextSlot.end_time).slice(0, 5))}` : ''}
        </p>
        <p class="mt-2 text-[12px] text-amber-700">No planned workflow session is visible yet. This is where the supervisor can notice planning gaps.</p>
      </div>`;
  }
  return `
    <div class="rounded-3xl border border-slate-200 bg-slate-50 px-4 py-4">
      <p class="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-bold">Next session</p>
      <h4 class="mt-1 text-lg font-bold text-slate-800">No visible upcoming session</h4>
      <p class="mt-1 text-[13px] text-slate-500">No planned session or timetable slot is available for this teacher in the current data.</p>
    </div>`;
}

function _ownerTeacherCoverageStrip(row, sessions, rules) {
  const safeSessions = Array.isArray(sessions) ? sessions : [];
  const safeRules = Array.isArray(rules) ? rules : [];
  const weekDays = _ownerWeekDays(new Date());
  const weekKeys = new Set(weekDays.map(day => _ownerLocalDateKey(day)));
  const now = Date.now();
  const weekSessions = safeSessions.filter(session => weekKeys.has(String(session.session_date || '')));
  const planned = weekSessions.filter(session => {
    const when = _ownerSessionDateTime(session);
    return when && when.getTime() >= now + 15 * 60 * 1000;
  }).length;
  const unclosed = weekSessions.filter(session => session.is_open && !_ownerSessionIsFuture(session)).length;
  const recorded = Math.max(0, weekSessions.length - planned - unclosed);
  const timetableOnly = weekDays.reduce((sum, day) => {
    const key = _ownerLocalDateKey(day);
    const weekday = _ownerRuleWeekdayForDate(day);
    const hasSession = weekSessions.some(session => String(session.session_date || '') === key);
    if (hasSession) return sum;
    return sum + safeRules.filter(rule => {
      if (Number(rule.weekday || 0) !== weekday) return false;
      if (rule.effective_from && key < String(rule.effective_from)) return false;
      if (rule.effective_to && key > String(rule.effective_to)) return false;
      return true;
    }).length;
  }, 0);
  return `
    <div class="grid grid-cols-2 gap-2 md:grid-cols-4">
      ${_ownerTrackerMini('This week', weekSessions.length, `${recorded} recorded`, 'blue')}
      ${_ownerTrackerMini('Planned', planned, 'future workflow sessions', planned ? 'green' : 'slate')}
      ${_ownerTrackerMini('Timetable only', timetableOnly, 'slots without workflow session', timetableOnly ? 'amber' : 'green')}
      ${_ownerTrackerMini('Unclosed', unclosed, 'needs cleanup if old', unclosed ? 'amber' : 'slate')}
    </div>
    <p class="text-[12px] text-slate-400">
      Tracking ${_num(row?.assigned_classes, 0)} assigned class${_num(row?.assigned_classes, 0) === 1 ? '' : 'es'} for this teacher. Planned means future session; unclosed means a past or current row without an end time.
    </p>`;
}

function _ownerSessionIsFuture(row) {
  const when = _ownerSessionDateTime(row);
  return !!when && when.getTime() >= Date.now() + 15 * 60 * 1000;
}

function _ownerTrackerMini(label, value, hint, tone = 'slate') {
  const toneMap = {
    blue: 'bg-blue-50 border-blue-100 text-blue-800',
    green: 'bg-green-50 border-green-100 text-green-800',
    amber: 'bg-amber-50 border-amber-100 text-amber-800',
    slate: 'bg-slate-50 border-slate-100 text-slate-800',
  };
  return `
    <div class="rounded-2xl border ${toneMap[tone] || toneMap.slate} px-3 py-3">
      <p class="text-[20px] font-black leading-none">${_escapeHtml(value)}</p>
      <p class="mt-1 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-500">${_escapeHtml(label)}</p>
      <p class="mt-1 text-[11px] text-slate-500">${_escapeHtml(hint)}</p>
    </div>`;
}

function _ownerTeacherWeekGrid(row) {
  const sessions = _ownerTeacherSessionRows(row);
  const rules = _ownerTeacherTimetableRows(row);
  const weekDays = _ownerWeekDays(new Date());
  return `
    <div class="grid gap-2 lg:grid-cols-7">
      ${weekDays.map(day => {
        const dayKey = _ownerLocalDateKey(day);
        const weekday = _ownerRuleWeekdayForDate(day);
        const daySessions = sessions
          .filter(session => String(session.session_date || '') === dayKey)
          .sort((a, b) => String(a.start_time || '').localeCompare(String(b.start_time || '')));
        const dayRules = rules
          .filter(rule => Number(rule.weekday || 0) === weekday)
          .filter(rule => (!rule.effective_from || dayKey >= String(rule.effective_from)) && (!rule.effective_to || dayKey <= String(rule.effective_to)))
          .sort((a, b) => String(a.start_time || '').localeCompare(String(b.start_time || '')));
        const isToday = dayKey === _ownerLocalDateKey(new Date());
        return `
          <div class="min-h-[148px] rounded-3xl border ${isToday ? 'border-blue-300 bg-blue-50/50' : 'border-slate-200 bg-slate-50/60'} px-3 py-3">
            <div class="flex items-start justify-between gap-2">
              <div>
                <p class="text-[11px] font-bold uppercase tracking-[0.16em] ${isToday ? 'text-blue-600' : 'text-slate-400'}">${_escapeHtml(_ownerShortDayLabel(day))}</p>
                <p class="mt-0.5 text-[13px] font-semibold text-slate-800">${_escapeHtml(_ownerShortDateLabel(day))}</p>
              </div>
              ${isToday ? '<span class="badge badge-blue">Today</span>' : ''}
            </div>
            <div class="mt-3 flex flex-col gap-2">
              ${daySessions.length ? daySessions.map(session => `
                <div class="rounded-2xl border border-blue-100 bg-white px-2.5 py-2 shadow-[0_1px_0_rgba(15,23,42,0.03)]">
                  <p class="text-[12px] font-semibold text-slate-900">${_escapeHtml(session.class_name || 'Class')}</p>
                  <p class="mt-0.5 text-[11px] text-slate-500">${_escapeHtml(_ownerSessionTimeLabel(session))}</p>
                  ${session.unit_title ? `<p class="mt-1 text-[11px] text-blue-700 line-clamp-2">${_escapeHtml(session.unit_title)}</p>` : ''}
                </div>`).join('') : ''}
              ${!daySessions.length && dayRules.length ? dayRules.slice(0, 3).map(rule => `
                <div class="rounded-2xl border border-dashed border-slate-300 bg-white/70 px-2.5 py-2">
                  <p class="text-[12px] font-semibold text-slate-700">${_escapeHtml(rule.class_name || 'Class')}</p>
                  <p class="mt-0.5 text-[11px] text-slate-400">${_escapeHtml(String(rule.start_time || '').slice(0, 5))}${rule.end_time ? `-${_escapeHtml(String(rule.end_time).slice(0, 5))}` : ''}</p>
                  <p class="mt-1 text-[10px] uppercase tracking-wider text-slate-400">Timetable</p>
                </div>`).join('') : ''}
              ${!daySessions.length && !dayRules.length ? '<p class="rounded-2xl border border-slate-200 bg-white/60 px-2.5 py-2 text-[11px] text-slate-400">No visible slot</p>' : ''}
            </div>
          </div>`;
      }).join('')}
    </div>`;
}

function _ownerAnalyticsPanel({ lockedCount, teacherTotal, activeClassTotal, studentTotal, sessionTotal, examTotal, overviewCounts, classRows, recentSessionRows }) {
  const classes = Array.isArray(classRows) ? classRows : [];
  const recent = Array.isArray(recentSessionRows) ? recentSessionRows : [];
  const unassigned = classes.filter(row => !row.is_archived && !row.teacher_user_id).length;
  const noRoster = classes.filter(row => !row.is_archived && _num(row.students, 0) <= 0).length;
  const openRecent = recent.filter(row => row.is_open).length;
  const checkedRows = _num(overviewCounts?.checked_session_rows, 0);
  const completedRows = _num(overviewCounts?.completed_checklist_items, 0);
  return `
    <div class="card border-blue-100">
      <div class="card-header bg-blue-50/60">
        <div>
          <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-blue-600">Analytics</p>
          <h3 class="mt-1 font-semibold text-slate-800 text-[15px]">Platform Analytics</h3>
          <p class="text-[12px] text-slate-500 mt-1">Separated from teacher tracking so the numbers are easy to scan.</p>
        </div>
        <span class="badge badge-blue">Whole platform</span>
      </div>
      <div class="card-body flex flex-col gap-4">
        <div class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
          ${_kpi('T', teacherTotal, 'Teachers', 'border-l-blue-500')}
          ${_kpi('!', lockedCount, 'Locked', 'border-l-red-400')}
          ${_kpi('C', activeClassTotal, 'Active Classes', 'border-l-green-500')}
          ${_kpi('S', studentTotal, 'Students', 'border-l-cyan-500')}
          ${_kpi('R', sessionTotal, 'Sessions', 'border-l-amber-500')}
          ${_kpi('E', examTotal, 'Exams', 'border-l-indigo-500')}
        </div>
        <div class="grid gap-3 lg:grid-cols-4">
          ${_ownerAnalyticMini('Open sessions', _num(overviewCounts?.open_sessions, 0), 'Sessions not closed yet', _num(overviewCounts?.open_sessions, 0) ? 'amber' : 'green')}
          ${_ownerAnalyticMini('Unassigned classes', unassigned, 'Classes without teacher owner', unassigned ? 'amber' : 'green')}
          ${_ownerAnalyticMini('No roster', noRoster, 'Classes without students', noRoster ? 'amber' : 'green')}
          ${_ownerAnalyticMini('Recent open', openRecent, 'Open in recent activity', openRecent ? 'amber' : 'slate')}
        </div>
        <div class="grid gap-3 lg:grid-cols-2">
          ${_ownerProgressMeter('Checklist completion records', completedRows, Math.max(checkedRows, completedRows, 1), 'Completed unit checklist rows recorded by teachers.')}
          ${_ownerProgressMeter('Session route capture', checkedRows, Math.max(_num(overviewCounts?.sessions, 0), checkedRows, 1), 'Checked route rows captured inside live sessions.')}
        </div>
      </div>
    </div>`;
}

function _ownerAnalyticMini(label, value, hint, tone = 'slate') {
  const toneMap = {
    green: 'bg-green-50 border-green-100 text-green-800',
    amber: 'bg-amber-50 border-amber-100 text-amber-800',
    red: 'bg-red-50 border-red-100 text-red-800',
    slate: 'bg-slate-50 border-slate-100 text-slate-800',
  };
  return `
    <div class="rounded-3xl border ${toneMap[tone] || toneMap.slate} px-4 py-4">
      <p class="text-[24px] font-black leading-none">${_escapeHtml(value)}</p>
      <p class="mt-2 text-[12px] font-bold uppercase tracking-[0.14em] text-slate-500">${_escapeHtml(label)}</p>
      <p class="mt-1 text-[12px] text-slate-500">${_escapeHtml(hint)}</p>
    </div>`;
}

function _ownerProgressMeter(label, value, total, hint) {
  const safeValue = Math.max(0, Number(value || 0));
  const safeTotal = Math.max(1, Number(total || 1));
  const pct = Math.max(0, Math.min(100, Math.round((safeValue / safeTotal) * 100)));
  return `
    <div class="rounded-3xl border border-slate-200 bg-slate-50 px-4 py-4">
      <div class="flex items-center justify-between gap-3">
        <div>
          <p class="text-[13px] font-semibold text-slate-800">${_escapeHtml(label)}</p>
          <p class="mt-1 text-[12px] text-slate-500">${_escapeHtml(hint)}</p>
        </div>
        <span class="text-[18px] font-black text-slate-900">${pct}%</span>
      </div>
      <div class="mt-3 h-2.5 rounded-full bg-white border border-slate-200 overflow-hidden">
        <div class="h-full rounded-full bg-gradient-to-r from-blue-500 to-green-500" style="width:${pct}%"></div>
      </div>
      <p class="mt-2 text-[11px] text-slate-400">${safeValue} of ${safeTotal}</p>
    </div>`;
}

function _ownerNeedsAttentionPanel(attentionRows, overviewCounts) {
  const rows = Array.isArray(attentionRows) ? attentionRows : [];
  return `
    <div class="card">
      <div class="card-header">
        <div>
          <h3 class="font-semibold text-slate-700 text-[14px]">Action Queue</h3>
          <p class="text-[12px] text-slate-400 mt-1">Short list only. This should stay readable.</p>
        </div>
        <span class="badge ${rows.length ? 'badge-amber' : 'badge-green'}">${rows.length ? `${rows.length} teacher${rows.length === 1 ? '' : 's'}` : 'Clear'}</span>
      </div>
      <div class="card-body flex flex-col gap-3">
        <div class="grid grid-cols-2 gap-2">
          ${_ownerSmallStat('Open units', _num(overviewCounts?.active_units, 0), _num(overviewCounts?.active_units, 0) ? 'amber' : 'slate')}
          ${_ownerSmallStat('Open sessions', _num(overviewCounts?.open_sessions, 0), _num(overviewCounts?.open_sessions, 0) ? 'amber' : 'slate')}
        </div>
        <div class="rounded-2xl border border-slate-200 bg-white px-3 py-3">
          ${rows.length ? rows.slice(0, 5).map(row => {
            const health = _ownerTeacherHealth(row);
            return `
              <button class="w-full text-left flex items-start gap-2 py-2 border-b border-slate-100 last:border-b-0 btn-owner-inspect-teacher" data-tid="${Number(row.teacher_id || 0)}">
                <span class="badge ${health.badgeClass} mt-0.5">${_escapeHtml(health.label)}</span>
                <span class="min-w-0 flex-1">
                  <span class="block text-[12px] font-semibold text-slate-800 truncate">${_escapeHtml(row.full_name || row.email || 'Teacher')}</span>
                  <span class="block text-[12px] text-slate-500">${_escapeHtml(health.reason)}</span>
                </span>
              </button>`;
          }).join('') : '<p class="text-[12px] text-slate-500">No urgent follow-up detected.</p>'}
        </div>
      </div>
    </div>`;
}

function _ownerTeacherDirectoryPanel({ operationRows, filteredOperationRows, visibleOperationRows, attentionRows, selectedTeacherId }) {
  const safeRows = Array.isArray(operationRows) ? operationRows : [];
  const filtered = Array.isArray(filteredOperationRows) ? filteredOperationRows : [];
  const visible = Array.isArray(visibleOperationRows) ? visibleOperationRows : [];
  const attention = Array.isArray(attentionRows) ? attentionRows : [];
  return `
    <div class="card">
      <div class="card-header">
        <div>
          <h3 class="font-semibold text-slate-700 text-[14px]">Teacher Directory</h3>
          <p class="text-[12px] text-slate-400 mt-1">Use this list to find a teacher, then inspect them in the tracker above.</p>
        </div>
        <span class="badge ${attention.length ? 'badge-amber' : 'badge-green'}">${attention.length ? `${attention.length} needs follow-up` : 'Healthy'}</span>
      </div>
      <div class="card-body">
        ${safeRows.length ? `
          <div class="mb-3 rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3">
            <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div class="min-w-0 flex-1">
                <label class="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Find teacher or class</label>
                <div class="mt-1 flex gap-2">
                  <input id="owner-teacher-search" type="search" value="${_escapeHtml(_ownerTeacherSearch)}" placeholder="Search teacher, email, or class..." class="!h-9 !text-[13px]" />
                  <button id="btn-owner-apply-teacher-search" class="btn btn-secondary btn-sm flex-shrink-0">Search</button>
                </div>
              </div>
              <div class="flex flex-wrap gap-2">
                ${_ownerFilterButton('all', 'All', safeRows.length)}
                ${_ownerFilterButton('attention', 'Follow-up', attention.length)}
                ${_ownerFilterButton('locked', 'Locked', safeRows.filter(row => row.is_active === false).length)}
                ${_ownerFilterButton('no_class', 'No class', safeRows.filter(row => _ownerTeacherHealth(row).rank === 1).length)}
                ${_ownerFilterButton('quiet', 'Quiet', safeRows.filter(row => _ownerTeacherHealth(row).rank === 4).length)}
              </div>
            </div>
            <div class="mt-3 flex items-center justify-between gap-2 text-[12px] text-slate-500">
              <span>Showing ${visible.length} of ${filtered.length} matching teacher${filtered.length === 1 ? '' : 's'}.</span>
              ${_ownerTeacherSearch || _ownerTeacherFilter !== 'all' ? '<button id="btn-owner-clear-teacher-filter" class="btn btn-ghost btn-sm">Clear filter</button>' : ''}
            </div>
          </div>
          <div class="grid gap-2">
            ${visible.length ? visible.map(row => _ownerTeacherActivityRow(row, selectedTeacherId)).join('') : `
              <div class="rounded-2xl border border-slate-200 bg-white px-4 py-6 text-center">
                <p class="text-[13px] font-semibold text-slate-700">No teachers match this filter.</p>
                <p class="mt-1 text-[12px] text-slate-400">Clear the search or switch back to All.</p>
              </div>`}
          </div>
          ${filtered.length > visible.length ? `
            <div class="mt-3 flex justify-center">
              <button id="btn-owner-teacher-show-more" class="btn btn-secondary btn-sm">Show more teachers</button>
            </div>` : (_ownerTeacherLimit > 8 && filtered.length > 8 ? `
            <div class="mt-3 flex justify-center">
              <button id="btn-owner-teacher-show-less" class="btn btn-ghost btn-sm">Show less</button>
            </div>` : '')}
        ` : `
          <div class="empty-state py-10">
            <div class="text-xl font-black opacity-30">OPS</div>
            <p class="text-[13px] text-slate-400">No teacher activity yet.</p>
          </div>`}
      </div>
    </div>`;
}

function _ownerCompactClasses(row) {
  const names = Array.isArray(row.class_names) ? row.class_names.filter(Boolean) : [];
  if (!names.length) return 'No classes assigned';
  const visible = names.slice(0, 2).join(', ');
  const extra = names.length > 2 ? ` +${names.length - 2}` : '';
  return `${visible}${extra}`;
}

function _ownerProgressPct(row) {
  const total = _num(row.checklist_items, 0);
  const done = _num(row.completed_checklist_items, 0);
  if (total <= 0) return null;
  return Math.round((done / total) * 100);
}

function _ownerTeacherActivityRow(row, selectedTeacherId = 0) {
  const health = row._health || _ownerTeacherHealth(row);
  const pct = _ownerProgressPct(row);
  const avg = row.average_exam_score == null ? null : Number(row.average_exam_score);
  const avgLabel = avg == null || Number.isNaN(avg) ? '-' : avg.toFixed(avg % 1 === 0 ? 0 : 1);
  const selected = Number(row.teacher_id || 0) === Number(selectedTeacherId || 0);
  return `
    <div class="rounded-2xl border ${selected ? 'border-blue-200 bg-blue-50/40' : 'border-slate-200 bg-white'} px-3 py-3 shadow-[0_1px_0_rgba(15,23,42,0.03)]">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap">
            <p class="text-[13px] font-semibold text-slate-800 truncate">${_escapeHtml(row.full_name || row.email || 'Teacher')}</p>
            <span class="badge ${health.badgeClass}">${_escapeHtml(health.label)}</span>
            ${selected ? '<span class="badge badge-blue">Selected</span>' : ''}
          </div>
          <p class="mt-1 text-[12px] text-slate-400 truncate">${_escapeHtml(row.email || '')}</p>
          <p class="mt-1 text-[12px] text-slate-500 truncate">${_escapeHtml(_ownerCompactClasses(row))}</p>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-2 min-w-0 lg:w-[520px] lg:flex-shrink-0">
          <div class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2">
            <p class="text-[13px] font-bold text-slate-800">${_num(row.assigned_classes, 0)}</p>
            <p class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Classes</p>
          </div>
          <div class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2">
            <p class="text-[13px] font-bold text-slate-800">${_num(row.students, 0)}</p>
            <p class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Students</p>
          </div>
          <div class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2">
            <p class="text-[13px] font-bold text-slate-800">${_num(row.sessions, 0)}</p>
            <p class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Sessions</p>
          </div>
          <div class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2">
            <p class="text-[13px] font-bold text-slate-800">${pct == null ? '-' : `${pct}%`}</p>
            <p class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Progress</p>
          </div>
          <div class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2">
            <p class="text-[13px] font-bold text-slate-800">${_num(row.exam_results, 0)}</p>
            <p class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Results</p>
          </div>
          <div class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2">
            <p class="text-[13px] font-bold text-slate-800">${_escapeHtml(avgLabel)}</p>
            <p class="text-[10px] uppercase tracking-wider text-slate-400 font-semibold">Avg</p>
          </div>
        </div>
      </div>
      <div class="mt-2 flex items-center justify-between gap-2 text-[12px] text-slate-500">
        <span>${_escapeHtml(health.reason)}</span>
        <div class="flex items-center gap-2">
          <span class="text-slate-400">Last session: ${_escapeHtml(_fmtOwnerDate(row.last_session_date))}</span>
          <button class="btn btn-ghost btn-sm btn-owner-inspect-teacher" data-tid="${Number(row.teacher_id || 0)}">${selected ? 'Viewing' : 'Inspect'}</button>
        </div>
      </div>
    </div>`;
}

function _ownerClassDetailRows(row) {
  if (Array.isArray(row?.classes) && row.classes.length) return row.classes;
  const names = Array.isArray(row?.class_names) ? row.class_names : [];
  return names.map((name, idx) => ({
    class_id: idx + 1,
    name,
    is_archived: false,
    students: null,
    sessions: null,
    open_sessions: null,
    active_units: null,
    last_session_date: null,
  }));
}

function _ownerSmallStat(label, value, tone = 'slate') {
  const toneMap = {
    blue: 'bg-blue-50 border-blue-100 text-blue-800',
    green: 'bg-green-50 border-green-100 text-green-800',
    amber: 'bg-amber-50 border-amber-100 text-amber-800',
    red: 'bg-red-50 border-red-100 text-red-800',
    slate: 'bg-slate-50 border-slate-100 text-slate-800',
  };
  return `
    <div class="rounded-2xl border ${toneMap[tone] || toneMap.slate} px-3 py-3">
      <p class="text-[20px] font-bold leading-none">${_escapeHtml(value)}</p>
      <p class="mt-1 text-[10px] uppercase tracking-wider text-slate-400 font-semibold">${_escapeHtml(label)}</p>
    </div>`;
}

function _ownerTeacherInspector(row) {
  if (!row) {
    return `
      <div class="card">
        <div class="card-body">
          <p class="text-[13px] text-slate-500">Select a teacher to inspect their class load and follow-up status.</p>
        </div>
      </div>`;
  }
  const health = row._health || _ownerTeacherHealth(row);
  const pct = _ownerProgressPct(row);
  const avg = row.average_exam_score == null ? null : Number(row.average_exam_score);
  const avgLabel = avg == null || Number.isNaN(avg) ? '-' : avg.toFixed(avg % 1 === 0 ? 0 : 1);
  const classes = _ownerClassDetailRows(row);
  const isActive = row.is_active !== false;
  return `
    <div class="card">
      <div class="card-header">
        <div>
          <h3 class="font-semibold text-slate-700 text-[14px]">Teacher Inspector</h3>
          <p class="text-[12px] text-slate-400 mt-1">Use this to decide the next supervisor action for one teacher.</p>
        </div>
        <span class="badge ${health.badgeClass}">${_escapeHtml(health.label)}</span>
      </div>
      <div class="card-body flex flex-col gap-4">
        <div class="rounded-3xl border border-slate-200 bg-gradient-to-br from-white to-slate-50 px-4 py-4">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div class="min-w-0">
              <p class="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-semibold">Selected teacher</p>
              <h4 class="mt-1 text-xl font-bold text-slate-900 truncate">${_escapeHtml(row.full_name || row.email || 'Teacher')}</h4>
              <p class="mt-1 text-[13px] text-slate-500 truncate">${_escapeHtml(row.email || '')}</p>
              <p class="mt-2 text-[13px] text-slate-600">${_escapeHtml(health.reason)}</p>
            </div>
            <div class="flex gap-2 flex-wrap">
              <button class="btn btn-ghost btn-sm btn-send-invite" data-tid="${Number(row.teacher_id || 0)}">Invite</button>
              <button class="btn btn-ghost btn-sm btn-reset-pwd" data-tid="${Number(row.teacher_id || 0)}">Reset password</button>
              ${isActive
      ? `<button class="btn btn-ghost btn-sm !text-amber-600 btn-lock" data-tid="${Number(row.teacher_id || 0)}">Lock</button>`
      : `<button class="btn btn-secondary btn-sm btn-unlock" data-tid="${Number(row.teacher_id || 0)}">Unlock</button>`}
            </div>
          </div>
          <div class="mt-4 grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-2">
            ${_ownerSmallStat('Classes', _num(row.assigned_classes, 0), 'blue')}
            ${_ownerSmallStat('Students', _num(row.students, 0), 'slate')}
            ${_ownerSmallStat('Sessions', _num(row.sessions, 0), 'green')}
            ${_ownerSmallStat('Open', _num(row.open_sessions, 0), _num(row.open_sessions, 0) ? 'amber' : 'slate')}
            ${_ownerSmallStat('Units', _num(row.active_units, 0), 'blue')}
            ${_ownerSmallStat('Progress', pct == null ? '-' : `${pct}%`, pct == null ? 'slate' : 'green')}
            ${_ownerSmallStat('Results', _num(row.exam_results, 0), 'slate')}
            ${_ownerSmallStat('Avg', avgLabel, 'slate')}
          </div>
        </div>

        <div class="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
          <div class="rounded-3xl border border-slate-200 bg-white px-4 py-4">
            <div class="flex items-center justify-between gap-2">
              <div>
                <p class="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-semibold">Assigned classes</p>
                <p class="mt-1 text-[13px] text-slate-500">Class load and latest session signal for this teacher.</p>
              </div>
              <span class="badge badge-gray">${classes.length} class${classes.length === 1 ? '' : 'es'}</span>
            </div>
            <div class="mt-3 grid gap-2">
              ${classes.length ? classes.map(cls => `
                <div class="rounded-2xl border border-slate-100 bg-slate-50 px-3 py-3">
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                      <p class="text-[13px] font-semibold text-slate-800 truncate">${_escapeHtml(cls.name || 'Class')}</p>
                      <p class="mt-1 text-[12px] text-slate-400">${_escapeHtml([cls.level, cls.subject].filter(Boolean).join(' • ') || 'No level/subject')}</p>
                    </div>
                    ${cls.is_archived ? '<span class="badge badge-gray">Archived</span>' : '<span class="badge badge-green">Active</span>'}
                  </div>
                  <div class="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-[12px]">
                    <span class="rounded-xl bg-white border border-slate-100 px-2 py-2"><b>${cls.students == null ? '-' : _num(cls.students, 0)}</b> students</span>
                    <span class="rounded-xl bg-white border border-slate-100 px-2 py-2"><b>${cls.sessions == null ? '-' : _num(cls.sessions, 0)}</b> sessions</span>
                    <span class="rounded-xl bg-white border border-slate-100 px-2 py-2"><b>${cls.active_units == null ? '-' : _num(cls.active_units, 0)}</b> open units</span>
                    <span class="rounded-xl bg-white border border-slate-100 px-2 py-2">${_escapeHtml(_fmtOwnerDate(cls.last_session_date))}</span>
                  </div>
                </div>`).join('') : '<p class="text-[13px] text-slate-500">No class assigned yet.</p>'}
            </div>
          </div>

          <div class="rounded-3xl border border-slate-200 bg-white px-4 py-4">
            <p class="text-[11px] uppercase tracking-[0.18em] text-slate-400 font-semibold">Supervisor next move</p>
            <h4 class="mt-2 text-[15px] font-bold text-slate-800">${_escapeHtml(health.label)}</h4>
            <p class="mt-2 text-[13px] leading-6 text-slate-600">${_escapeHtml(_ownerSupervisorAdvice(row, health))}</p>
            <div class="mt-4 rounded-2xl border border-slate-100 bg-slate-50 px-3 py-3 text-[12px] text-slate-500">
              Last session: <span class="font-semibold text-slate-700">${_escapeHtml(_fmtOwnerDate(row.last_session_date))}</span>
            </div>
          </div>
        </div>
      </div>
    </div>`;
}

function _ownerSupervisorAdvice(row, health) {
  if (health.rank === 0) return 'Unlock only if this teacher should currently use the platform. Otherwise keep the account locked.';
  if (health.rank === 1) return 'Assign at least one class before expecting any teaching workflow data from this teacher.';
  if (health.rank === 2) return 'Import or verify the student roster so attendance and class statistics become meaningful.';
  if (health.rank === 3) return 'Ask the teacher to start recording sessions from the timetable and checklist.';
  if (health.rank === 4) return 'Check whether the teacher is still using the app, or whether sessions are being recorded late.';
  if (_num(row.open_sessions, 0) > 0) return 'There is an open session. Ask the teacher to close it once the class record is complete.';
  return 'No urgent supervisor action. Keep monitoring progress and session consistency.';
}

function _ownerClassRows() {
  const overviewRows = Array.isArray(_ownerOverview?.classes) ? _ownerOverview.classes : [];
  const rows = overviewRows.length ? overviewRows : _allClasses.map(cls => {
    const teacher = _teachers.find(t => Number(t.id) === Number(cls.teacher_user_id));
    return {
      class_id: cls.id,
      name: cls.name,
      subject: cls.subject,
      level: cls.level,
      is_archived: Boolean(cls.is_archived),
      teacher_user_id: cls.teacher_user_id || null,
      teacher_name: teacher?.full_name || null,
      teacher_email: teacher?.email || null,
      teacher_is_active: teacher ? teacher.is_active !== false : null,
      students: 0,
      sessions: 0,
      open_sessions: 0,
      active_units: 0,
      exams: 0,
      last_session_date: null,
    };
  });
  return rows
    .map(row => ({ ...row, _health: _ownerClassHealth(row) }))
    .sort((a, b) => {
      if (a._health.rank !== b._health.rank) return a._health.rank - b._health.rank;
      return String(a.name || '').localeCompare(String(b.name || ''));
    });
}

function _ownerClassHealth(row) {
  const days = _daysSince(row.last_session_date);
  if (row.is_archived) {
    return { rank: 9, label: 'Archived', badgeClass: 'badge-gray', reason: 'Class is archived.' };
  }
  if (!row.teacher_user_id) {
    return { rank: 0, label: 'Unassigned', badgeClass: 'badge-amber', reason: 'No teacher is assigned to this class.' };
  }
  if (row.teacher_is_active === false) {
    return { rank: 1, label: 'Teacher locked', badgeClass: 'badge-red', reason: 'Assigned teacher account is locked.' };
  }
  if (_num(row.students, 0) <= 0) {
    return { rank: 2, label: 'No roster', badgeClass: 'badge-amber', reason: 'Student roster is empty.' };
  }
  if (_num(row.sessions, 0) <= 0) {
    return { rank: 3, label: 'No sessions', badgeClass: 'badge-amber', reason: 'No teaching sessions recorded yet.' };
  }
  if (_num(row.open_sessions, 0) > 0) {
    return { rank: 4, label: 'Open session', badgeClass: 'badge-amber', reason: 'A class session is still open.' };
  }
  if (days != null && days > 21) {
    return { rank: 5, label: 'Quiet', badgeClass: 'badge-gray', reason: `Last session was ${days} days ago.` };
  }
  return { rank: 6, label: 'Active', badgeClass: 'badge-green', reason: 'Class has recent recorded activity.' };
}

function _ownerClassSupervisionPanel(rows, attentionRows) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const safeAttention = Array.isArray(attentionRows) ? attentionRows : [];
  const unassigned = safeRows.filter(row => !row.is_archived && !row.teacher_user_id).length;
  const activeClasses = safeRows.filter(row => !row.is_archived).length;
  return `
    <div class="card">
      <div class="card-header">
        <div>
          <h3 class="font-semibold text-slate-700 text-[14px]">Class Supervision Overview</h3>
          <p class="text-[12px] text-slate-400 mt-1">Spot setup gaps by class before they become teacher-workflow problems.</p>
        </div>
        <span class="badge ${safeAttention.length ? 'badge-amber' : 'badge-green'}">${safeAttention.length ? `${safeAttention.length} need setup` : 'Classes healthy'}</span>
      </div>
      <div class="card-body flex flex-col gap-3">
        <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
          ${_ownerSmallStat('Classes', safeRows.length, 'blue')}
          ${_ownerSmallStat('Active', activeClasses, 'green')}
          ${_ownerSmallStat('Unassigned', unassigned, unassigned ? 'amber' : 'slate')}
          ${_ownerSmallStat('Follow-up', safeAttention.length, safeAttention.length ? 'amber' : 'green')}
        </div>
        ${safeRows.length ? `
          <div class="grid gap-2">
            ${safeRows.slice(0, 10).map(row => _ownerClassSupervisionRow(row)).join('')}
          </div>
          ${safeRows.length > 10 ? `<p class="text-[12px] text-slate-400">Showing 10 of ${safeRows.length} classes. Class assignment controls remain below.</p>` : ''}
        ` : `
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-5 text-center">
            <p class="text-[13px] text-slate-500">No classes exist yet.</p>
          </div>`}
      </div>
    </div>`;
}

function _ownerClassSupervisionRow(row) {
  const health = row._health || _ownerClassHealth(row);
  const teacherLabel = row.teacher_name || 'No teacher assigned';
  return `
    <div class="rounded-2xl border border-slate-200 bg-white px-3 py-3">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div class="min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <p class="text-[13px] font-semibold text-slate-800 truncate">${_escapeHtml(row.name || 'Class')}</p>
            <span class="badge ${health.badgeClass}">${_escapeHtml(health.label)}</span>
          </div>
          <p class="mt-1 text-[12px] text-slate-500 truncate">${_escapeHtml(teacherLabel)}</p>
          <p class="mt-1 text-[12px] text-slate-400">${_escapeHtml([row.level, row.subject].filter(Boolean).join(' • ') || health.reason)}</p>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-5 gap-2 lg:min-w-[520px]">
          <span class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2 text-[12px]"><b>${_num(row.students, 0)}</b> students</span>
          <span class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2 text-[12px]"><b>${_num(row.sessions, 0)}</b> sessions</span>
          <span class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2 text-[12px]"><b>${_num(row.active_units, 0)}</b> units</span>
          <span class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2 text-[12px]"><b>${_num(row.exams, 0)}</b> exams</span>
          <span class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2 text-[12px]">${_escapeHtml(_fmtOwnerDate(row.last_session_date))}</span>
        </div>
      </div>
      <p class="mt-2 text-[12px] text-slate-500">${_escapeHtml(health.reason)}</p>
    </div>`;
}

function _ownerRecentSessionRows() {
  return Array.isArray(_ownerOverview?.recent_sessions) ? _ownerOverview.recent_sessions : [];
}

function _fmtOwnerTimeRange(row) {
  const start = row?.start_time ? String(row.start_time).slice(0, 5) : '';
  const end = row?.end_time ? String(row.end_time).slice(0, 5) : '';
  if (start && end) return `${start}-${end}`;
  if (start) return `${start}-open`;
  return 'No time';
}

function _ownerSessionTimeLabel(row) {
  const start = row?.start_time ? String(row.start_time).slice(0, 5) : '';
  const end = row?.end_time ? String(row.end_time).slice(0, 5) : '';
  if (start && end) return `${start}-${end}`;
  if (!start) return 'No time';
  const when = _ownerSessionDateTime(row);
  if (when && when.getTime() >= Date.now() + 15 * 60 * 1000) return `${start}-planned`;
  return row?.is_open ? `${start}-unclosed` : start;
}

function _ownerRecentActivityPanel(rows, selectedTeacher = null) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const openCount = safeRows.filter(row => row.is_open).length;
  const withChecklist = safeRows.filter(row => _num(row.checked_session_rows, 0) > 0).length;
  const selectedLabel = selectedTeacher?.full_name || selectedTeacher?.email || '';
  return `
    <div class="card">
      <div class="card-header">
        <div>
          <h3 class="font-semibold text-slate-700 text-[14px]">${selectedLabel ? 'Selected Teacher Activity' : 'Recent Teaching Activity'}</h3>
          <p class="text-[12px] text-slate-400 mt-1">${selectedLabel ? `Latest visible sessions for ${_escapeHtml(selectedLabel)}.` : 'Latest recorded classroom sessions across teachers.'}</p>
        </div>
        <span class="badge ${openCount ? 'badge-amber' : 'badge-gray'}">${openCount ? `${openCount} open` : 'No open sessions'}</span>
      </div>
      <div class="card-body flex flex-col gap-3">
        <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
          ${_ownerSmallStat('Recent', safeRows.length, 'blue')}
          ${_ownerSmallStat('Open', openCount, openCount ? 'amber' : 'slate')}
          ${_ownerSmallStat('With checklist', withChecklist, withChecklist ? 'green' : 'slate')}
          ${_ownerSmallStat('Attendance rows', safeRows.reduce((sum, row) => sum + _num(row.attendance_rows, 0), 0), 'slate')}
        </div>
        ${safeRows.length ? `
          <div class="grid gap-2">
            ${safeRows.slice(0, 8).map(row => _ownerRecentActivityRow(row)).join('')}
          </div>
          ${safeRows.length > 8 ? `<p class="text-[12px] text-slate-400">Showing 8 of ${safeRows.length} recent sessions.</p>` : ''}
        ` : `
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-5 text-center">
            <p class="text-[13px] font-semibold text-slate-700">No session activity yet.</p>
            <p class="mt-1 text-[12px] text-slate-400">${selectedLabel ? 'This teacher has no visible sessions in the current overview.' : 'Recent sessions will appear here once teachers start recording work.'}</p>
          </div>`}
      </div>
    </div>`;
}

function _ownerRecentActivityRow(row) {
  const checkedRows = _num(row.checked_session_rows, 0);
  const progressItems = _num(row.progress_items, 0);
  const attendanceRows = _num(row.attendance_rows, 0);
  return `
    <div class="rounded-2xl border border-slate-200 bg-white px-3 py-3">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div class="min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <p class="text-[13px] font-semibold text-slate-800 truncate">${_escapeHtml(row.class_name || 'Class')}</p>
            <span class="badge ${row.is_open ? 'badge-amber' : 'badge-green'}">${row.is_open ? 'Open' : 'Closed'}</span>
            ${row.unit_session_number ? `<span class="badge badge-blue">Session ${Number(row.unit_session_number)}</span>` : ''}
          </div>
          <p class="mt-1 text-[12px] text-slate-500 truncate">${_escapeHtml(row.teacher_name || 'No assigned teacher')}</p>
          <p class="mt-1 text-[12px] text-slate-400">${_escapeHtml(_fmtOwnerDate(row.session_date))} • ${_escapeHtml(_fmtOwnerTimeRange(row))}</p>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 lg:min-w-[460px]">
          <span class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2 text-[12px]"><b>${checkedRows}</b> checked</span>
          <span class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2 text-[12px]"><b>${progressItems}</b> progress</span>
          <span class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2 text-[12px]"><b>${attendanceRows}</b> attendance</span>
          <span class="rounded-xl bg-slate-50 border border-slate-100 px-2 py-2 text-[12px]"><b>${_num(row.absent_rows, 0)}</b> absent</span>
        </div>
      </div>
      ${row.note_preview ? `<p class="mt-2 text-[12px] text-slate-500">${_escapeHtml(row.note_preview)}</p>` : ''}
    </div>`;
}

function _bindOwnerEvents(el) {
  el.querySelector('#btn-gen-pwd')?.addEventListener('click', () => {
    document.getElementById('new-teacher-pwd').value = generateStrongPassword();
    _updateInvitePreview();
  });

  function _updateInvitePreview() {
    const name = document.getElementById('new-teacher-name')?.value?.trim();
    const email = document.getElementById('new-teacher-email')?.value?.trim();
    const pwd = document.getElementById('new-teacher-pwd')?.value?.trim();
    const prev = document.getElementById('invite-preview');
    if (name && email && pwd) {
      prev.classList.remove('hidden');
      prev.textContent = buildTeacherInviteText(name, email, pwd);
    }
  }
  ['new-teacher-name', 'new-teacher-email', 'new-teacher-pwd'].forEach(id => {
    el.querySelector(`#${id}`)?.addEventListener('input', _updateInvitePreview);
  });

  const parseHolidayYear = () => {
    const fallback = new Date().getFullYear();
    const raw = Number(el.querySelector('#owner-holiday-year')?.value || fallback);
    if (!Number.isFinite(raw)) return fallback;
    return Math.max(2000, Math.min(2100, Math.floor(raw)));
  };
  const reloadNotebooklmStatus = async () => {
    _notebooklmStatus = await api('/ops/notebooklm/status').catch(() => null);
    _renderOwner(el);
  };
  const reloadHolidayPanel = async ({ seed = false } = {}) => {
    const year = parseHolidayYear();
    _holidayYear = year;
    if (seed) {
      await api(`/workflow/holidays/seed/morocco/${year}`, { method: 'POST' });
    }
    const rows = await api(`/workflow/holidays?year=${year}&country_code=MA`);
    _ownerHolidays = Array.isArray(rows) ? rows : [];
    _renderOwner(el);
  };
  const reloadOwnerPeople = async () => {
    const [overview, users] = await Promise.all([
      api('/classes/owner-overview'),
      api('/auth/users'),
    ]);
    _ownerOverview = overview || null;
    _teachers = (users || []).filter(u => u.role === 'teacher');
  };

  el.querySelectorAll('.btn-owner-inspect-teacher').forEach(btn => {
    btn.addEventListener('click', () => {
      const tid = Number(btn.dataset.tid || 0);
      if (!tid) return;
      _setOwnerSelectedTeacherId(tid);
      _renderOwner(el);
    });
  });
  el.querySelector('#owner-teacher-focus-select')?.addEventListener('change', (ev) => {
    const tid = Number(ev.target?.value || 0);
    if (!tid) return;
    _setOwnerSelectedTeacherId(tid);
    _renderOwner(el);
  });
  el.querySelector('#owner-teacher-search')?.addEventListener('change', (ev) => {
    _ownerTeacherSearch = String(ev.target?.value || '').trim();
    _ownerTeacherLimit = 8;
    _renderOwner(el);
  });
  el.querySelector('#owner-teacher-search')?.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      _ownerTeacherSearch = String(ev.target?.value || '').trim();
      _ownerTeacherLimit = 8;
      _renderOwner(el);
    }
  });
  el.querySelector('#btn-owner-apply-teacher-search')?.addEventListener('click', () => {
    _ownerTeacherSearch = String(el.querySelector('#owner-teacher-search')?.value || '').trim();
    _ownerTeacherLimit = 8;
    _renderOwner(el);
  });
  el.querySelectorAll('.btn-owner-teacher-filter').forEach(btn => {
    btn.addEventListener('click', () => {
      _ownerTeacherFilter = String(btn.dataset.filter || 'all');
      _ownerTeacherLimit = 8;
      _renderOwner(el);
    });
  });
  el.querySelector('#btn-owner-clear-teacher-filter')?.addEventListener('click', () => {
    _ownerTeacherFilter = 'all';
    _ownerTeacherSearch = '';
    _ownerTeacherLimit = 8;
    _renderOwner(el);
  });
  el.querySelector('#btn-owner-teacher-show-more')?.addEventListener('click', () => {
    _ownerTeacherLimit = Math.min(200, Number(_ownerTeacherLimit || 8) + 8);
    _renderOwner(el);
  });
  el.querySelector('#btn-owner-teacher-show-less')?.addEventListener('click', () => {
    _ownerTeacherLimit = 8;
    _renderOwner(el);
  });
  el.querySelector('#btn-owner-copy-brief')?.addEventListener('click', async () => {
    try {
      await copyText(_ownerSupervisorBriefText());
      showToast('Supervisor brief copied.', 'ok');
    } catch (err) {
      showToast(err.message || 'Could not copy supervisor brief.', 'error');
    }
  });

  el.querySelector('#btn-owner-notebooklm-refresh')?.addEventListener('click', async function () {
    this.classList.add('btn-busy'); this.disabled = true;
    try {
      await reloadNotebooklmStatus();
      showToast(_notebooklmStatus?.ready ? 'NotebookLM is ready.' : 'NotebookLM status refreshed.', 'ok');
    } catch (err) {
      showToast(err.message || 'Failed to refresh NotebookLM status.', 'error');
      this.classList.remove('btn-busy'); this.disabled = false;
    }
  });
  el.querySelector('#btn-owner-notebooklm-smoke')?.addEventListener('click', async function () {
    this.classList.add('btn-busy'); this.disabled = true;
    try {
      _notebooklmSmoke = await api('/ops/notebooklm/smoke-test', { method: 'POST' });
      if (_notebooklmSmoke?.status) _notebooklmStatus = _notebooklmSmoke.status;
      _renderOwner(el);
      showToast(_notebooklmSmoke?.smoke?.ok ? 'NotebookLM smoke test passed.' : 'NotebookLM smoke test failed.', _notebooklmSmoke?.smoke?.ok ? 'ok' : 'warning');
    } catch (err) {
      showToast(err.message || 'Failed to run NotebookLM smoke test.', 'error');
      this.classList.remove('btn-busy'); this.disabled = false;
    }
  });
  el.querySelector('#btn-owner-notebooklm-helper')?.addEventListener('click', async function () {
    this.classList.add('btn-busy'); this.disabled = true;
    try {
      await downloadWithAuth('/ops/notebooklm/refresh-helper.cmd', 'refresh_notebooklm.cmd');
      showToast('NotebookLM refresh helper downloaded.', 'ok');
    } catch (err) {
      showToast(err.message || 'Failed to download NotebookLM refresh helper.', 'error');
    } finally {
      this.classList.remove('btn-busy'); this.disabled = false;
    }
  });
  el.querySelector('#btn-owner-notebooklm-clean-temp')?.addEventListener('click', async function () {
    this.classList.add('btn-busy'); this.disabled = true;
    try {
      const result = await api('/ops/notebooklm/cleanup-temp', { method: 'POST' });
      if (result?.status) _notebooklmStatus = result.status;
      _notebooklmSmoke = null;
      _renderOwner(el);
      const deletedCount = Number(result?.cleanup?.deleted_count || 0);
      showToast(deletedCount > 0 ? `Removed ${deletedCount} temporary NotebookLM notebook${deletedCount === 1 ? '' : 's'}.` : 'No temporary NotebookLM notebooks found.', 'ok');
    } catch (err) {
      showToast(err.message || 'Failed to clean temporary NotebookLM notebooks.', 'error');
      this.classList.remove('btn-busy'); this.disabled = false;
    }
  });
  el.querySelector('#btn-owner-notebooklm-upload-auth')?.addEventListener('click', async function () {
    const btn = this;
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      btn.classList.add('btn-busy'); btn.disabled = true;
      try {
        _notebooklmStatus = await api('/ops/notebooklm/auth/upload', { method: 'POST', body: form });
        _renderOwner(el);
        showToast(_notebooklmStatus?.ready ? 'NotebookLM auth uploaded and ready.' : 'NotebookLM auth uploaded.', 'ok');
      } catch (err) {
        showToast(err.message || 'Failed to upload NotebookLM auth file.', 'error');
        btn.classList.remove('btn-busy'); btn.disabled = false;
      }
    };
    input.click();
  });
  el.querySelector('#btn-owner-notebooklm-clear-auth')?.addEventListener('click', async function () {
    const btn = this;
    const ok = await askConfirm('Clear the saved NotebookLM authentication file from this deployment?');
    if (!ok) return;
    btn.classList.add('btn-busy'); btn.disabled = true;
    try {
      _notebooklmStatus = await api('/ops/notebooklm/auth/clear', { method: 'POST' });
      _renderOwner(el);
      showToast('NotebookLM auth cleared.', 'ok');
    } catch (err) {
      showToast(err.message || 'Failed to clear NotebookLM auth file.', 'error');
      btn.classList.remove('btn-busy'); btn.disabled = false;
    }
  });

  el.querySelector('#btn-owner-holiday-refresh')?.addEventListener('click', async function () {
    this.classList.add('btn-busy'); this.disabled = true;
    try {
      await reloadHolidayPanel();
      showToast('Holidays refreshed.', 'ok');
    } catch (err) {
      showToast(err.message || 'Failed to load holidays.', 'error');
      this.classList.remove('btn-busy'); this.disabled = false;
    }
  });
  el.querySelector('#btn-owner-holiday-seed')?.addEventListener('click', async function () {
    this.classList.add('btn-busy'); this.disabled = true;
    try {
      await reloadHolidayPanel({ seed: true });
      showToast('Fixed Morocco holidays seeded.', 'ok');
    } catch (err) {
      showToast(err.message || 'Failed to seed holidays.', 'error');
      this.classList.remove('btn-busy'); this.disabled = false;
    }
  });
  el.querySelector('#btn-owner-holiday-template')?.addEventListener('click', async function () {
    this.classList.add('btn-busy'); this.disabled = true;
    try {
      await downloadWithAuth('/workflow/holidays/template.xlsx', 'holiday-import-template.xlsx');
    } catch (err) {
      showToast(err.message || 'Failed to download template.', 'error');
    } finally {
      this.classList.remove('btn-busy'); this.disabled = false;
    }
  });
  el.querySelector('#btn-owner-holiday-export')?.addEventListener('click', async function () {
    const year = parseHolidayYear();
    this.classList.add('btn-busy'); this.disabled = true;
    try {
      await downloadWithAuth(`/workflow/holidays/export.xlsx?year=${year}&country_code=MA`, `holidays-${year}.xlsx`);
    } catch (err) {
      showToast(err.message || 'Failed to download current holidays.', 'error');
    } finally {
      this.classList.remove('btn-busy'); this.disabled = false;
    }
  });
  el.querySelector('#btn-owner-holiday-import')?.addEventListener('click', async function () {
    const btn = this;
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.xlsx,.xlsm';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append('file', file);
      btn.classList.add('btn-busy'); btn.disabled = true;
      try {
        const result = await api('/workflow/holidays/import', { method: 'POST', body: form });
        await reloadHolidayPanel();
        const yearsLabel = Array.isArray(result?.years) && result.years.length ? result.years.join(', ') : 'selected years';
        showToast(`Holiday file applied. ${Number(result?.holiday_dates || 0)} dates merged for ${yearsLabel}.`, 'ok');
      } catch (err) {
        showToast(err.message || 'Failed to import holidays.', 'error');
      } finally {
        btn.classList.remove('btn-busy'); btn.disabled = false;
      }
    };
    input.click();
  });
  el.querySelectorAll('.btn-owner-holiday-toggle').forEach(btn => {
    btn.addEventListener('click', async () => {
      const holidayId = Number(btn.dataset.holidayId || 0);
      const blocked = String(btn.dataset.blocked || '') === '1';
      if (!holidayId) return;
      btn.classList.add('btn-busy'); btn.disabled = true;
      try {
        await api(`/workflow/holidays/${holidayId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_blocked: !blocked }),
        });
        await reloadHolidayPanel();
        showToast(!blocked ? 'Holiday blocked.' : 'Holiday unblocked.', 'ok');
      } catch (err) {
        showToast(err.message || 'Failed to update holiday.', 'error');
        btn.classList.remove('btn-busy'); btn.disabled = false;
      }
    });
  });

  el.querySelector('#btn-copy-invite')?.addEventListener('click', () => {
    const text = document.getElementById('invite-preview')?.textContent?.trim();
    if (!text) { showToast('Fill in name, email and password first.', 'warning'); return; }
    copyText(text);
    showToast('Invite text copied!', 'ok');
  });

  // Create teacher  POST /auth/users with role:'teacher'
  el.querySelector('#btn-create-teacher')?.addEventListener('click', async function () {
    const btn = this;
    const name = document.getElementById('new-teacher-name')?.value?.trim();
    const email = document.getElementById('new-teacher-email')?.value?.trim();
    const pwd = document.getElementById('new-teacher-pwd')?.value?.trim();
    if (!name || !email || !pwd) { showToast('Fill in all teacher fields.', 'warning'); return; }
    btn.classList.add('btn-busy'); btn.disabled = true;
    try {
      await api('/auth/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_name: name, email, password: pwd, role: 'teacher' }),
      });
      showToast(`Teacher "${name}" created!`, 'ok');
      await reloadOwnerPeople();
      _renderOwner(el);
    } catch (err) {
      btn.classList.remove('btn-busy'); btn.disabled = false;
      showToast(err.message, 'error');
    }
  });

  // Send invite email  POST /auth/users/{id}/send-invite
  el.querySelectorAll('.btn-send-invite').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tid = Number(btn.dataset.tid);
      const t = _teachers.find(t => t.id === tid);
      const appUrl = window.location.origin;
      btn.classList.add('btn-busy'); btn.disabled = true;
      try {
        await api(`/auth/users/${tid}/send-invite`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ app_url: appUrl }),
        });
        showToast(`Invite email sent to ${t?.email || 'teacher'}!`, 'ok');
      } catch (err) {
        showToast(err.message || 'Failed to send invite email.', 'error');
      } finally {
        btn.classList.remove('btn-busy'); btn.disabled = false;
      }
    });
  });

  // Class-teacher assignment
  el.querySelectorAll('.btn-assign-teacher').forEach(btn => {
    btn.addEventListener('click', async () => {
      const cid = Number(btn.dataset.classId);
      const select = el.querySelector(`.class-teacher-select[data-class-id="${cid}"]`);
      const teacherId = select?.value ? Number(select.value) : null;
      const previousTeacherId = Number(_classTeachers[cid] || 0) || null;
      btn.classList.add('btn-busy'); btn.disabled = true;
      try {
        if (previousTeacherId && previousTeacherId !== teacherId) {
          await api(`/classes/${cid}/assign-teacher/${previousTeacherId}`, {
            method: 'DELETE',
          });
        }
        if (teacherId && teacherId !== previousTeacherId) {
          await api(`/classes/${cid}/assign-teacher/${teacherId}`, {
            method: 'POST',
          });
        }
        if (teacherId) _classTeachers[cid] = teacherId;
        else delete _classTeachers[cid];
        const [classes, archived] = await Promise.all([
          api('/classes'),
          api('/classes?include_archived=true'),
        ]);
        _publishOwnerClassState({ activeClasses: classes || [], archivedClasses: archived || [] });
        _ownerOverview = await api('/classes/owner-overview');
        const tName = teacherId ? (_teachers.find(t => t.id === teacherId)?.full_name || '') : 'none';
        showToast(`Assigned: ${tName || 'unassigned'}.`, 'ok');
      } catch (err) {
        showToast(err.message || 'Assignment failed.', 'error');
      } finally {
        btn.classList.remove('btn-busy'); btn.disabled = false;
      }
    });
  });

  // Reset password  POST /auth/users/{id}/reset-password
  el.querySelectorAll('.btn-reset-pwd').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tid = Number(btn.dataset.tid);
      const pwd = generateStrongPassword();
      const ok = await askConfirm(`Reset password for this teacher?\n\nNew password: ${pwd}\n(Will be copied to clipboard)`);
      if (!ok) return;
      try {
        await api(`/auth/users/${tid}/reset-password`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ new_password: pwd }),
        });
        copyText(pwd);
        showToast('Password reset & copied to clipboard!', 'ok');
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  // Lock  PATCH /auth/users/{id}/status with {is_active: false}
  el.querySelectorAll('.btn-lock').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tid = Number(btn.dataset.tid);
      try {
        await api(`/auth/users/${tid}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_active: false }),
        });
        await reloadOwnerPeople();
        _renderOwner(el);
        showToast('Account locked.', 'ok');
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  // Unlock  PATCH /auth/users/{id}/status with {is_active: true}
  el.querySelectorAll('.btn-unlock').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tid = Number(btn.dataset.tid);
      try {
        await api(`/auth/users/${tid}/status`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_active: true }),
        });
        await reloadOwnerPeople();
        _renderOwner(el);
        showToast('Account unlocked!', 'ok');
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  // Delete
  el.querySelectorAll('.btn-delete').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tid = Number(btn.dataset.tid);
      const ok = await askConfirm('Delete this teacher? This cannot be undone.', { danger: true });
      if (!ok) return;
      try {
        await api(`/auth/users/${tid}`, { method: 'DELETE' });
        const [users, classes, archived] = await Promise.all([
          api('/auth/users'),
          api('/classes'),
          api('/classes?include_archived=true'),
        ]);
        _teachers = (users || []).filter(u => u.role === 'teacher');
        if (Number(_selectedOwnerTeacherId || 0) === tid) _setOwnerSelectedTeacherId(null);
        _publishOwnerClassState({ activeClasses: classes || [], archivedClasses: archived || [] });
        _ownerOverview = await api('/classes/owner-overview');
        _renderOwner(el);
        showToast('Teacher deleted.', 'ok');
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  // Restore archived class
  el.querySelectorAll('.btn-restore').forEach(btn => {
    btn.addEventListener('click', async () => {
      const cid = Number(btn.dataset.classId);
      try {
        await api(`/classes/${cid}/restore`, { method: 'POST' });
        const [classes, archived] = await Promise.all([
          api('/classes'), api('/classes?include_archived=true'),
        ]);
        _publishOwnerClassState({ activeClasses: classes || [], archivedClasses: archived || [] });
        showToast('Class restored!', 'ok');
        _renderOwner(el);
      } catch (err) { showToast(err.message, 'error'); }
    });
  });

  // Change password
  el.querySelector('#btn-change-pwd')?.addEventListener('click', async function () {
    const btn = this;
    const current = el.querySelector('#chg-pwd-current')?.value?.trim();
    const next = el.querySelector('#chg-pwd-new')?.value?.trim();
    const errEl = el.querySelector('#chg-pwd-error');
    const setErr = (msg) => {
      if (!errEl) return;
      errEl.textContent = msg; errEl.classList.toggle('hidden', !msg);
    };
    if (!current) { setErr('Enter your current password.'); return; }
    if (!next || next.length < 8) { setErr('New password must be at least 8 characters.'); return; }
    setErr('');
    btn.classList.add('btn-busy'); btn.disabled = true;
    try {
      await api('/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      showToast('Password updated successfully!', 'ok');
      el.querySelector('#chg-pwd-current').value = '';
      el.querySelector('#chg-pwd-new').value = '';
    } catch (err) {
      setErr(err.message || 'Failed to change password.');
    } finally {
      btn.classList.remove('btn-busy'); btn.disabled = false;
    }
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

