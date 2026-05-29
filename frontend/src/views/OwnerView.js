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
  const active = _teachers.filter(t => t.is_active !== false);
  const locked = _teachers.filter(t => t.is_active === false);
  const runtimeHealth = _notebooklmStatus?.runtime_health || {};
  const refreshRequired = Boolean(runtimeHealth?.refresh_required);
  const lastSuccessTs = _tsValue(runtimeHealth?.last_success_at);
  const lastFailureTs = _tsValue(runtimeHealth?.last_error_at);
  const showActiveError = Boolean(runtimeHealth?.last_error_message) && (refreshRequired || lastFailureTs > lastSuccessTs);

  el.innerHTML = `
    <div class="view-container">

      <!-- Page header -->
      <div>
        <div class="flex items-center gap-2 text-[12px] text-slate-400 mb-1">Admin</div>
        <h1 class="text-2xl font-bold text-slate-800 tracking-tight">Owner Panel</h1>
      </div>

      <div class="rounded-3xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
        <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div class="max-w-3xl">
            <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">Role Boundary</p>
            <h2 class="mt-1 text-lg font-bold text-slate-800">Owner manages the platform. Teachers manage teaching progress.</h2>
            <p class="mt-2 text-[13px] leading-6 text-slate-500">
              This area is intentionally limited to technical setup, teacher accounts, class assignment, holiday rules, and AI connectivity.
              Teaching workflow, lesson completion, and class progress stay inside the teacher workspace.
            </p>
          </div>
          <div class="grid gap-2 text-[12px] text-slate-600 sm:grid-cols-2 lg:min-w-[320px]">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
              <p class="font-semibold text-slate-800">Owner responsibilities</p>
              <p class="mt-1">Accounts, access, AI setup, calendars, and platform reliability.</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
              <p class="font-semibold text-slate-800">Teacher responsibilities</p>
              <p class="mt-1">Complete sessions, track real progress, and run the class workflow.</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Analytics KPI strip -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        ${_kpi('T', active.length, 'Active Teachers', 'border-l-blue-500')}
        ${_kpi('L', locked.length, 'Locked Accounts', 'border-l-red-400')}
        ${_kpi('C', _allClasses.length, 'Active Classes', 'border-l-green-500')}
        ${_kpi('A', _archivedClasses.length, 'Archived Classes', 'border-l-slate-400')}
      </div>

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
            <p>1. On your own Windows machine, run <span class="font-mono">python -m notebooklm login</span>.</p>
            <p>2. Sign in to the Google account that can access NotebookLM.</p>
            <p>3. Find the generated file <span class="font-mono">%USERPROFILE%\.notebooklm\profiles\default\storage_state.json</span>.</p>
            <p>4. In this panel, click <span class="font-mono">Upload Auth File</span> and upload that file.</p>
            <p>5. Click <span class="font-mono">Refresh Status</span> until this card shows <span class="font-mono">Ready</span>.</p>
            <p>6. Faster refresh option: run <span class="font-mono">python scripts/refresh_notebooklm_auth.py --app-url https://your-app --email owner@school.edu --run-login</span> from the backend folder on your own machine.</p>
            <p>7. Easiest option: click <span class="font-mono">Download Refresh Helper</span>, then double-click the downloaded <span class="font-mono">.cmd</span> file on your Windows machine.</p>
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
      const users = await api('/auth/users');
      _teachers = (users || []).filter(u => u.role === 'teacher');
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
        const users = await api('/auth/users');
        _teachers = (users || []).filter(u => u.role === 'teacher');
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
        const users = await api('/auth/users');
        _teachers = (users || []).filter(u => u.role === 'teacher');
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
        _publishOwnerClassState({ activeClasses: classes || [], archivedClasses: archived || [] });
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

