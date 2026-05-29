/**
 * ClassView.js  Class overview, students, KPI cards
 * Teacher Progress App  Tailwind v4
 */
import { api, downloadWithAuth } from '../api/client.js';
import {
  getClasses, getSelectedId, getSelectedName,
  getStudents, getDashboard,
  setStudents, setDashboard, setClasses, clearClassState,
} from '../state/class.js';
import { showToast } from '../utils/toast.js';
import { askConfirm } from '../utils/modal.js';
import { mountRetryCard } from '../utils/retryView.js';
import { fmtDate, fmtPct, fmtScore, clamp } from '../utils/format.js';
import { navigate } from '../router.js';
import { notifyClassChange, setSelectedClassAndNotify, updateClassSelector } from '../components/AppShell.js';

const CLASS_INIT_AUTO_OPEN_KEY = 'class_init_auto_open';

export async function renderClassView() {
  _showChrome();
  const el = document.getElementById('app-content');
  const classId = getSelectedId();
  const shouldAutoOpenInit = _consumeAutoOpenClassInitFlag();

  if (!classId) {
    el.innerHTML = `
        <div class="view-container">
          <div class="empty-state bg-white rounded-3xl border border-slate-200 py-20">
            <div class="text-3xl font-black opacity-40">CLASS</div>
            <h2 class="text-lg font-semibold text-slate-500">No class selected</h2>
            <p class="text-[13px] text-slate-400 max-w-xs">
              Select a class from the dropdown above, or create one below.
            </p>
            ${_createClassForm()}
            <button id="btn-open-class-init" class="btn btn-secondary mt-3">Class Setup Wizard</button>
          </div>
        </div>`;
    _bindCreateForm(el);
    if (shouldAutoOpenInit) {
      setTimeout(() => {
        _openAndSubmitClassInitSetup();
      }, 0);
    }
    return;
  }

  // Skeleton loading state
  el.innerHTML = `<div class="view-container">${_skeleton()}</div>`;

  try {
    const [students, dashboard] = await Promise.all([
      api(`/classes/${classId}/students`),
      api(`/classes/${classId}/dashboard`),
    ]);
    setStudents(students || []);
    setDashboard(dashboard);
  } catch {
    mountRetryCard(el, {
      title: 'Class Dashboard Unavailable',
      message: 'Unable to load class data right now. Retry after checking API connection.',
      buttonId: 'btn-retry-class-load',
      onRetry: () => renderClassView(),
    });
    showToast('Failed to load class dashboard.', 'error');
    return;
  }

  const db = getDashboard();
  const students = getStudents();
  const className = getSelectedName() || getClasses().find(c => c.id === classId)?.name || '---';
  const sessionCount = db?.counts?.sessions ?? '---';
  const attendanceRows = Number(db?.counts?.attendance_rows || 0);
  const attendanceTotals = db?.attendance_totals || {};
  const presentLike = Number(attendanceTotals.present || 0) + Number(attendanceTotals.late || 0) + Number(attendanceTotals.excused || 0);
  const avgAttendance = attendanceRows > 0 ? (presentLike / attendanceRows) : null;
  const examScores = (db?.exam_trend || [])
    .map(r => Number(r?.average_score))
    .filter(v => Number.isFinite(v));
  const avgExamScore = examScores.length ? (examScores.reduce((a, b) => a + b, 0) / examScores.length) : null;

  el.innerHTML = `
    <div class="view-container">

      <!-- Page header -->
      <div class="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <div class="flex items-center gap-2 text-[12px] text-slate-400 mb-1">
            Dashboard
          </div>
          <h1 class="text-2xl font-bold text-slate-800 tracking-tight">${className}</h1>
          <p class="text-[13px] text-slate-400 mt-0.5">${students.length} students enrolled</p>
        </div>
        <div class="flex gap-2 flex-wrap">
          <button id="btn-open-class-init-top" class="btn btn-primary">Class Setup</button>
          <button id="btn-export-att"
            class="btn btn-secondary"> Attendance CSV</button>
          <button id="btn-export-grades"
            class="btn btn-secondary"> Grades CSV</button>
          <button id="btn-archive"
            class="btn btn-ghost btn-sm !text-slate-400 hover:!text-red-600"> Archive</button>
        </div>
      </div>

      <!-- KPI Strip -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        ${_kpiCard('STU', students.length, 'Students', 'border-l-blue-500')}
        ${_kpiCard('SES', sessionCount, 'Sessions', 'border-l-indigo-500')}
        ${_kpiCard('ATT', avgAttendance != null ? fmtPct(avgAttendance) : '---', 'Avg Attendance', avgAttendance != null && avgAttendance >= 0.8 ? 'border-l-green-500' : 'border-l-amber-500')}
        ${_kpiCard('AVG', avgExamScore != null ? fmtScore(avgExamScore) : '---', 'Avg Score', 'border-l-purple-500')}
      </div>

      <!-- Attendance trend + Exam trend -->
      ${db && (db.attendance_trend?.length || db.exam_trend?.length) ? `
      <div class="grid md:grid-cols-2 gap-4">
        ${db.attendance_trend?.length ? `
        <div class="card">
          <div class="card-header">
            <h3 class="font-semibold text-slate-700 text-[14px]"> Attendance Trend</h3>
          </div>
          <div class="card-body flex flex-col gap-2">
            ${db.attendance_trend.slice(-6).map(r => `
            <div class="flex items-center gap-3 text-[12px]">
              <span class="w-[72px] text-slate-400 truncate flex-shrink-0">${fmtDate(r.session_date)}</span>
              <div class="trend-bar-wrap">
                <div class="trend-bar green" style="width:${clamp((r.attendance_rate || 0), 2, 100)}%"></div>
              </div>
              <span class="w-10 text-right text-slate-500">${fmtPct(r.attendance_rate)}</span>
            </div>`).join('')}
          </div>
        </div>` : ''}
        ${db.exam_trend?.length ? `
        <div class="card">
          <div class="card-header">
            <h3 class="font-semibold text-slate-700 text-[14px]"> Exam Trend</h3>
          </div>
          <div class="card-body flex flex-col gap-2">
            ${db.exam_trend.slice(-6).map(r => `
            <div class="flex items-center gap-3 text-[12px]">
              <span class="w-[72px] text-slate-400 truncate flex-shrink-0">${r.title || '---'}</span>
              <div class="trend-bar-wrap">
                <div class="trend-bar blue" style="width:${clamp(((r.average_score || 0) / 20) * 100, 2, 100)}%"></div>
              </div>
              <span class="w-10 text-right text-slate-500">${fmtScore(r.average_score)}</span>
            </div>`).join('')}
          </div>
        </div>` : ''}
      </div>` : ''}

      <!-- Extraction Confidence Panel -->
      ${db && db.extraction_metrics ? `
      <div class="card">
        <div class="card-header pb-2">
          <h3 class="font-semibold text-slate-700 text-[14px]"> Extraction Confidence</h3>
          <span class="badge ${db.extraction_metrics.average_confidence >= 0.8 ? 'badge-green' : db.extraction_metrics.average_confidence >= 0.5 ? 'badge-amber' : 'badge-red'} ml-2">
            Avg: ${fmtPct(db.extraction_metrics.average_confidence)}
          </span>
        </div>
        <div class="card-body">
          ${db.extraction_metrics.latest_entries && db.extraction_metrics.latest_entries.length ? `
          <div class="flex flex-col gap-2">
            ${db.extraction_metrics.latest_entries.map(entry => `
            <div class="flex items-center gap-3 text-[12px] p-2 bg-slate-50 rounded-lg border border-slate-100">
              <span class="text-slate-400 w-24 flex-shrink-0">${fmtDate(entry.created_at)}</span>
              <span class="font-medium text-slate-700 truncate flex-1">${_escapeHtml(entry.filename || 'Upload')}</span>
              <span class="text-slate-500 w-12 text-right ${entry.confidence >= 0.8 ? 'text-green-600' : 'text-amber-600'}">${fmtPct(entry.confidence)}</span>
            </div>
            `).join('')}
          </div>
          ` : '<p class="text-[12px] text-slate-400">No recent extractions.</p>'}
        </div>
      </div>
      ` : ''}

      <!-- Students table -->
      <div class="card">
        <div class="card-header">
          <h3 class="font-semibold text-slate-700 text-[14px]"> Students</h3>
          <div class="flex gap-2 items-center">
            <input id="student-filter" type="text" placeholder="Filter..."
              class="!h-8 !text-[12px] !w-32 sm:!w-48" aria-label="Filter students by name or code" />
            <button id="btn-download-student-template" class="btn btn-ghost btn-sm" title="Download student import template"> Template</button>
            <button id="btn-import-students" class="btn btn-secondary btn-sm"> Import</button>
          </div>
        </div>
        <div class="overflow-auto">
          <table class="data-table" id="students-table">
            <caption class="sr-only">Students enrolled in selected class</caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Name</th>
                <th scope="col">Code</th>
                <th scope="col">Attendance</th>
                <th scope="col">Avg Score</th>
              </tr>
            </thead>
            <tbody id="students-body">
              ${_renderStudents(students)}
            </tbody>
          </table>
        </div>
        ${students.length === 0 ? `
        <div class="empty-state py-12">
          <div class="text-2xl font-black opacity-30">CSV</div>
          <p class="text-[13px] text-slate-400">No students yet - import a CSV to get started.</p>
        </div>` : ''}
      </div>

      <!-- Create new class -->
  <div class="card">
    <div class="card-header">
      <h3 class="font-semibold text-slate-700 text-[14px]"> Create New Class</h3>
    </div>
    <div class="card-body flex flex-col gap-3">
      ${_createClassForm()}
      <div class="pt-3 border-t border-slate-100">
        <p class="text-[12px] text-slate-500 mb-2">Initialize class + student list + weekly timetable in one form.</p>
        <button id="btn-open-class-init" class="btn btn-secondary">Class Setup Wizard</button>
      </div>
    </div>
  </div>

    </div > `;

  _bindEvents(el, classId);
  if (shouldAutoOpenInit) {
    setTimeout(() => {
      _openAndSubmitClassInitSetup();
    }, 0);
  }
}

/*  Helpers  */
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

function _kpiCard(icon, value, label, border = 'border-l-slate-300') {
  return `
  <div class="kpi-card border-l-4 ${border}">
    <div class="flex items-center justify-between">
      <span class="text-2xl">${icon}</span>
    </div>
    <div class="text-[28px] font-extrabold text-slate-800 leading-none tracking-tight">${value}</div>
    <div class="text-[10px] font-bold text-slate-400 uppercase tracking-[0.08em]">${label}</div>
  </div>`;
}

function _consumeAutoOpenClassInitFlag() {
  try {
    const raw = sessionStorage.getItem(CLASS_INIT_AUTO_OPEN_KEY);
    if (raw !== '1') return false;
    sessionStorage.removeItem(CLASS_INIT_AUTO_OPEN_KEY);
    return true;
  } catch {
    return false;
  }
}

function _skeleton() {
  return `
  <div class="flex flex-col gap-5 animate-pulse">
    <div class="flex items-center justify-between">
      <div class="flex flex-col gap-2">
        <div class="skeleton h-4 w-24 rounded-lg"></div>
        <div class="skeleton h-8 w-52 rounded-xl"></div>
        <div class="skeleton h-3 w-32 rounded-lg"></div>
      </div>
      <div class="flex gap-2">
        <div class="skeleton h-9 w-28 rounded-xl"></div>
        <div class="skeleton h-9 w-28 rounded-xl"></div>
      </div>
    </div>
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
      ${Array(4).fill('<div class="skeleton h-24 rounded-2xl"></div>').join('')}
    </div>
    <div class="skeleton h-56 rounded-2xl"></div>
    <div class="skeleton h-72 rounded-2xl"></div>
  </div>`;
}

function _renderStudents(students) {
  if (!students.length) return '';
  return students.map((s, i) => `
  <tr>
    <td class="text-slate-400 text-[11px] font-mono">${String(i + 1).padStart(2, '0')}</td>
    <td>
      <div class="flex items-center gap-2.5">
        <div class="w-7 h-7 rounded-full bg-gradient-to-br from-blue-100 to-indigo-200
                    flex items-center justify-center text-[10px] font-bold text-blue-700 flex-shrink-0">
          ${(s.full_name || '?').charAt(0).toUpperCase()}
        </div>
        <span class="font-semibold text-slate-800 text-[13px]">${s.full_name || 'N/A'}</span>
      </div>
    </td>
    <td><code class="text-[11px] bg-slate-100 text-slate-600 px-2 py-0.5 rounded-md">${s.student_code || 'N/A'}</code></td>
    <td>
      ${s.attendance_pct != null ? `
      <div class="flex items-center gap-2">
        <div class="w-20 h-1.5 bg-slate-100 rounded-full overflow-hidden flex-shrink-0">
          <div class="h-full rounded-full transition-all duration-500
               ${s.attendance_pct >= 0.8 ? 'bg-green-500' : s.attendance_pct >= 0.6 ? 'bg-amber-500' : 'bg-red-500'}"
               style="width:${clamp((s.attendance_pct || 0) * 100, 0, 100)}%"></div>
        </div>
        <span class="text-[12px] font-semibold
             ${s.attendance_pct >= 0.8 ? 'text-green-700' : s.attendance_pct >= 0.6 ? 'text-amber-700' : 'text-red-600'}">
          ${fmtPct(s.attendance_pct)}
        </span>
      </div>` : '<span class="text-slate-300 text-[12px]">N/A</span>'}
    </td>
    <td class="font-bold text-[13px]
         ${s.avg_score != null && s.avg_score >= 14 ? 'text-green-700' : s.avg_score != null && s.avg_score >= 10 ? 'text-amber-700' : s.avg_score != null ? 'text-red-600' : ''}">
      ${s.avg_score != null ? fmtScore(s.avg_score) : '<span class="text-slate-300 text-[12px]">N/A</span>'}
    </td>
  </tr>`).join('');
}

function _escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function _createClassForm() {
  return `
  <div class="flex flex-col gap-4">
    <div class="grid sm:grid-cols-3 gap-3">
      <div class="flex flex-col gap-1.5 sm:col-span-1">
        <label class="text-[11px] font-bold text-slate-400 uppercase tracking-widest">Class Name <span class="text-red-400">*</span></label>
        <input id="new-class-name" type="text" placeholder="e.g. Terminale B 2025" />
      </div>
      <div class="flex flex-col gap-1.5">
        <label class="text-[11px] font-bold text-slate-400 uppercase tracking-widest">Subject <span class="font-normal normal-case text-slate-300">(optional)</span></label>
        <input id="new-class-subject" type="text" placeholder="e.g. Mathematics" />
      </div>
      <div class="flex flex-col gap-1.5">
        <label class="text-[11px] font-bold text-slate-400 uppercase tracking-widest">Level <span class="font-normal normal-case text-slate-300">(optional)</span></label>
          <input id="new-class-level" type="text" placeholder="e.g. 3eme" />
        </div>
      </div>
      <button id="btn-create-class" class="btn btn-primary self-start">
         Create Class
      </button>
    </div > `;
}

function _bindCreateForm(el) {
  el.querySelector('#btn-create-class')?.addEventListener('click', _createClass);
  el.querySelector('#new-class-name')?.addEventListener('keydown',
    e => e.key === 'Enter' && _createClass());
  el.querySelector('#btn-open-class-init')?.addEventListener('click', async () => {
    await _openAndSubmitClassInitSetup();
  });
}

async function _createClass() {
  const inp = document.getElementById('new-class-name');
  const name = inp?.value?.trim();
  if (!name) {
    inp?.classList.add('input-error');
    showToast('Class name is required.', 'warning');
    return;
  }
  inp?.classList.remove('input-error');
  const subject = document.getElementById('new-class-subject')?.value?.trim() || null;
  const level = document.getElementById('new-class-level')?.value?.trim() || null;
  const createBtn = document.getElementById('btn-create-class');
  if (createBtn) { createBtn.classList.add('btn-busy'); createBtn.disabled = true; }
  try {
    const payload = { name };
    if (subject) payload.subject = subject;
    if (level) payload.level = level;
    const cls = await api('/classes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const classes = await api('/classes');
    setClasses(classes || []);
    setSelectedClassAndNotify(cls.id, cls.name);
    showToast(`Class "${cls.name}" created!`, 'ok');
    inp.value = '';
    const subjectInp = document.getElementById('new-class-subject');
    const levelInp = document.getElementById('new-class-level');
    if (subjectInp) subjectInp.value = '';
    if (levelInp) levelInp.value = '';
  } catch (err) {
    if (createBtn) { createBtn.classList.remove('btn-busy'); createBtn.disabled = false; }
    showToast(err.message, 'error');
  }
}

function _bindEvents(el, classId) {
  _bindCreateForm(el);
  el.querySelector('#btn-open-class-init-top')?.addEventListener('click', async () => {
    await _openAndSubmitClassInitSetup();
  });

  el.querySelector('#student-filter')?.addEventListener('input', e => {
    const q = e.target.value.toLowerCase();
    document.querySelectorAll('#students-body tr').forEach(row => {
      row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });

  el.querySelector('#btn-export-att')?.addEventListener('click', async () => {
    try {
      await downloadWithAuth(`/classes/${classId}/attendance-export.csv`, 'attendance.csv');
    } catch (err) { showToast(err.message, 'error'); }
  });

  el.querySelector('#btn-export-grades')?.addEventListener('click', async () => {
    try {
      await downloadWithAuth(`/classes/${classId}/reports/official-notes.xlsx`, 'grades.xlsx');
    } catch (err) { showToast(err.message, 'error'); }
  });

  el.querySelector('#btn-archive')?.addEventListener('click', async () => {
    const reason = await _askArchiveReason();
    if (reason === null) return; // cancelled
    try {
      await api(`/classes/${classId}/archive`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: reason ? JSON.stringify({ reason }) : undefined,
      });
      clearClassState();
      const classes = await api('/classes');
      setClasses(classes || []);
      updateClassSelector();
      showToast('Class archived.', 'ok');
      notifyClassChange(getSelectedId());
    } catch (err) { showToast(err.message, 'error'); }
  });

  el.querySelector('#btn-download-student-template')?.addEventListener('click', async () => {
    try {
      const classId2 = getSelectedId();
      if (!classId2) return;
      await downloadWithAuth(`/classes/${classId2}/students/template`, 'students-template.xlsx');
    } catch (err) { showToast(err.message || 'Template download failed.', 'error'); }
  });

  el.querySelector('#btn-import-students')?.addEventListener('click', () => {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = '.xlsx,.xlsm';
    inp.onchange = async () => {
      const file = inp.files[0]; if (!file) return;
      const form = new FormData(); form.append('file', file);
      try {
        const res = await api(`/classes/${classId}/students/import`, { method: 'POST', body: form });
        showToast(`Imported ${res.created || 0} students.`, 'ok');
        notifyClassChange(classId);
      } catch (err) { showToast(err.message || 'Student import failed. Use .xlsx or .xlsm.', 'error'); }
    };
    inp.click();
  });
}

/**
 * Opens a small modal asking for an optional archive reason.
 * Resolves with the reason string (empty string = no reason) or null if cancelled.
 */
function _askArchiveReason() {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal max-w-md">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[15px] font-bold text-slate-800">Archive Class</h2>
          <p class="text-[12px] text-slate-400 mt-1">
            Students will remain on record but no new sessions can be started.
          </p>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="flex flex-col gap-1.5">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Reason <span class="font-normal lowercase">(optional)</span>
            </label>
            <textarea id="archive-reason" rows="3"
              placeholder="e.g. End of academic year, class merged..." class="resize-none"></textarea>
          </div>
        </div>
        <div class="class-init-modal-footer px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="archive-cancel" class="btn btn-ghost">Cancel</button>
          <button id="archive-confirm" class="btn !bg-red-500 hover:!bg-red-600 !text-white">Archive</button>
        </div>
      </div>`;
    function cleanup(v) { overlay.remove(); resolve(v); }
    overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(null); });
    overlay.querySelector('#archive-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#archive-confirm')?.addEventListener('click', () => {
      const reason = overlay.querySelector('#archive-reason')?.value?.trim() || '';
      cleanup(reason);
    });
    document.body.appendChild(overlay);
    overlay.querySelector('#archive-reason')?.focus();
  });
}

function _todayDateKey() {
  const now = new Date();
  const yyyy = String(now.getFullYear());
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

function _parseStudentSeedLines(rawValue) {
  const lines = String(rawValue || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean);
  const output = [];
  for (let idx = 0; idx < lines.length; idx += 1) {
    const line = lines[idx];
    const normalized = line.replace(/\t/g, ',');
    const parts = normalized.split(',').map(part => part.trim()).filter(Boolean);
    let studentCode = null;
    let fullName = '';
    if (parts.length >= 2) {
      studentCode = parts[0];
      fullName = parts.slice(1).join(' ').trim();
    } else {
      fullName = parts[0] || '';
    }
    if (!fullName) {
      throw new Error(`Student line ${idx + 1}: full name is required.`);
    }
    const row = { full_name: fullName };
    if (studentCode) row.student_code = studentCode;
    output.push(row);
  }
  return output;
}

function _openClassInitWizardModal({ selectedClass }) {
  return new Promise(resolve => {
    const hasSelectedClass = Number(selectedClass?.id || 0) > 0;
    const defaultDate = _todayDateKey();
    const initialRows = [
      { weekday: 1, start_time: '08:00', end_time: '09:00', subject: '', room: '', group: '' },
    ];
    let timetableRows = initialRows.slice();

    const weekdayOptions = [
      { value: 1, label: 'Monday' },
      { value: 2, label: 'Tuesday' },
      { value: 3, label: 'Wednesday' },
      { value: 4, label: 'Thursday' },
      { value: 5, label: 'Friday' },
      { value: 6, label: 'Saturday' },
    ];

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal class-init-modal max-w-5xl w-[96vw]">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800">Quick Init Wizard</h2>
          <p class="text-[12px] text-slate-500 mt-1">Initialize class, student roster, and timetable in one submit.</p>
        </div>
        <div class="class-init-modal-body px-6 py-5 flex flex-col gap-4">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div class="rounded-xl border border-slate-200 p-3 flex flex-col gap-2">
              <h3 class="text-[13px] font-semibold text-slate-700">Class</h3>
              ${hasSelectedClass ? `
                <label class="inline-flex items-center gap-2 text-[12px]">
                  <input id="class-init-use-selected" type="checkbox" checked />
                  <span>Use selected class: <span class="font-semibold">${_escapeHtml(selectedClass?.name || '')}</span></span>
                </label>
              ` : ''}
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div class="flex flex-col gap-1">
                  <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Class Name</label>
                  <input id="class-init-name" type="text" value="${_escapeHtml(selectedClass?.name || '')}" placeholder="e.g. 2BAC-A" />
                </div>
                <div class="flex flex-col gap-1">
                  <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Subject</label>
                  <input id="class-init-subject" type="text" value="${_escapeHtml(selectedClass?.subject || '')}" placeholder="Mathematics" />
                </div>
                <div class="flex flex-col gap-1 sm:col-span-2">
                  <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Level</label>
                  <input id="class-init-level" type="text" value="${_escapeHtml(selectedClass?.level || '')}" placeholder="e.g. 2BAC / 3eme" />
                </div>
              </div>
            </div>
            <div class="rounded-xl border border-slate-200 p-3 flex flex-col gap-2">
              <h3 class="text-[13px] font-semibold text-slate-700">Students</h3>
              <div class="flex flex-col gap-1">
                <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Student Mode</label>
                <select id="class-init-student-mode">
                  <option value="append_new">Append New Students</option>
                  <option value="replace_all">Replace All Students</option>
                  <option value="ignore">Ignore Student List</option>
                </select>
              </div>
              <div class="flex flex-col gap-1">
                <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Student List</label>
                <textarea id="class-init-students" rows="5" placeholder="One student per line.&#10;Format: CODE, Full Name&#10;or: Full Name"></textarea>
              </div>
              <p class="text-[11px] text-slate-500">If code is missing, the app auto-generates one.</p>
            </div>
          </div>

          <div class="rounded-xl border border-slate-200 p-3 flex flex-col gap-3">
            <div class="flex items-center justify-between gap-2 flex-wrap">
              <h3 class="text-[13px] font-semibold text-slate-700">Timetable</h3>
              <button id="class-init-add-row" class="btn btn-ghost btn-sm" type="button">Add Slot</button>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-4 gap-2">
              <div class="flex flex-col gap-1">
                <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Timetable Mode</label>
                <select id="class-init-timetable-mode">
                  <option value="replace_future_from_date">Replace Future From Date</option>
                  <option value="append_new_slots">Append New Slots</option>
                  <option value="ignore">Ignore Timetable</option>
                </select>
              </div>
              <div class="flex flex-col gap-1">
                <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Effective From</label>
                <input id="class-init-effective-from" type="date" value="${_escapeHtml(defaultDate)}" />
              </div>
              <div class="flex flex-col gap-1">
                <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Effective To</label>
                <input id="class-init-effective-to" type="date" />
              </div>
            </div>
            <div id="class-init-rows-wrap" class="class-init-rows-wrap border border-slate-200 rounded-xl bg-white"></div>
          </div>

          <p id="class-init-error" class="text-[12px] text-red-600 hidden"></p>
        </div>
        <div class="class-init-modal-footer px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="class-init-cancel" class="btn btn-ghost" type="button">Cancel</button>
          <button id="class-init-save" class="btn btn-primary" type="button">Submit Setup</button>
        </div>
      </div>
    `;

    const rowsWrap = overlay.querySelector('#class-init-rows-wrap');
    const classNameInput = overlay.querySelector('#class-init-name');
    const classSubjectInput = overlay.querySelector('#class-init-subject');
    const classLevelInput = overlay.querySelector('#class-init-level');
    const useSelectedInput = overlay.querySelector('#class-init-use-selected');
    const studentModeInput = overlay.querySelector('#class-init-student-mode');
    const studentsInput = overlay.querySelector('#class-init-students');
    const timetableModeInput = overlay.querySelector('#class-init-timetable-mode');
    const effectiveFromInput = overlay.querySelector('#class-init-effective-from');
    const effectiveToInput = overlay.querySelector('#class-init-effective-to');
    const errorNode = overlay.querySelector('#class-init-error');

    const setError = message => {
      if (!errorNode) return;
      const text = String(message || '').trim();
      errorNode.textContent = text;
      errorNode.classList.toggle('hidden', !text);
    };

    const cleanup = value => {
      overlay.remove();
      resolve(value);
    };

    const syncClassInputs = () => {
      const usingSelected = hasSelectedClass && Boolean(useSelectedInput?.checked);
      if (classNameInput) {
        classNameInput.disabled = usingSelected;
        classNameInput.classList.toggle('opacity-60', usingSelected);
      }
    };

    const syncStudentInputs = () => {
      const mode = String(studentModeInput?.value || 'append_new').trim();
      const disabled = mode === 'ignore';
      if (studentsInput) {
        studentsInput.disabled = disabled;
        studentsInput.classList.toggle('opacity-60', disabled);
      }
    };

    const renderRows = () => {
      if (!rowsWrap) return;
      if (!timetableRows.length) {
        rowsWrap.innerHTML = '<p class="text-[12px] text-slate-500 px-3 py-3">No timetable slots yet.</p>';
        return;
      }
      rowsWrap.innerHTML = `
        ${timetableRows.map((row, idx) => `
          <div class="grid grid-cols-1 sm:grid-cols-7 gap-2 p-2 border-b border-slate-100 last:border-b-0">
            <div class="flex flex-col gap-1">
              <label class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Day</label>
              <select data-row-index="${idx}" data-row-field="weekday">
                ${weekdayOptions.map(option => `<option value="${option.value}" ${Number(row.weekday) === option.value ? 'selected' : ''}>${_escapeHtml(option.label)}</option>`).join('')}
              </select>
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Start</label>
              <input type="time" data-row-index="${idx}" data-row-field="start_time" value="${_escapeHtml(String(row.start_time || ''))}" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">End</label>
              <input type="time" data-row-index="${idx}" data-row-field="end_time" value="${_escapeHtml(String(row.end_time || ''))}" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Subject</label>
              <input type="text" data-row-index="${idx}" data-row-field="subject" value="${_escapeHtml(String(row.subject || ''))}" placeholder="Subject" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Room</label>
              <input type="text" data-row-index="${idx}" data-row-field="room" value="${_escapeHtml(String(row.room || ''))}" placeholder="Room" />
            </div>
            <div class="flex flex-col gap-1">
              <label class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Group</label>
              <input type="text" data-row-index="${idx}" data-row-field="group" value="${_escapeHtml(String(row.group || ''))}" placeholder="Group" />
            </div>
            <div class="flex items-end">
              <button class="btn btn-ghost btn-sm w-full" type="button" data-row-remove="${idx}">Remove</button>
            </div>
          </div>
        `).join('')}
      `;
    };

    rowsWrap?.addEventListener('input', event => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const index = Number(target.getAttribute('data-row-index') || -1);
      const field = String(target.getAttribute('data-row-field') || '').trim();
      if (index < 0 || index >= timetableRows.length || !field) return;
      timetableRows[index] = {
        ...timetableRows[index],
        [field]: target.value,
      };
    });

    rowsWrap?.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const removeIndex = Number(target.getAttribute('data-row-remove') || -1);
      if (removeIndex < 0 || removeIndex >= timetableRows.length) return;
      timetableRows.splice(removeIndex, 1);
      renderRows();
    });

    overlay.querySelector('#class-init-add-row')?.addEventListener('click', () => {
      timetableRows.push({ weekday: 1, start_time: '08:00', end_time: '09:00', subject: '', room: '', group: '' });
      renderRows();
    });

    useSelectedInput?.addEventListener('change', syncClassInputs);
    studentModeInput?.addEventListener('change', syncStudentInputs);

    overlay.querySelector('#class-init-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.addEventListener('click', event => {
      if (event.target === overlay) cleanup(null);
    });

    overlay.querySelector('#class-init-save')?.addEventListener('click', () => {
      try {
        setError('');
        const usingSelected = hasSelectedClass && Boolean(useSelectedInput?.checked);
        const className = String(classNameInput?.value || '').trim();
        const subject = String(classSubjectInput?.value || '').trim();
        const level = String(classLevelInput?.value || '').trim();
        const studentMode = String(studentModeInput?.value || 'append_new').trim();
        const studentRows = studentMode === 'ignore'
          ? []
          : _parseStudentSeedLines(String(studentsInput?.value || ''));
        const timetableMode = String(timetableModeInput?.value || 'replace_future_from_date').trim();
        const effectiveFrom = String(effectiveFromInput?.value || '').trim();
        const effectiveTo = String(effectiveToInput?.value || '').trim();

        if (!usingSelected && !className) {
          throw new Error('Class name is required for new class setup.');
        }
        if (timetableMode !== 'ignore' && !effectiveFrom) {
          throw new Error('Effective From is required when timetable mode is active.');
        }
        if (effectiveFrom && effectiveTo && effectiveTo < effectiveFrom) {
          throw new Error('Effective To must be greater than or equal to Effective From.');
        }

        const normalizedRows = timetableRows
          .map(row => ({
            weekday: Number(row.weekday || 0),
            start_time: String(row.start_time || '').trim(),
            end_time: String(row.end_time || '').trim(),
            subject: String(row.subject || '').trim(),
            room: String(row.room || '').trim(),
            group: String(row.group || '').trim(),
          }))
          .filter(row => row.weekday > 0 && row.start_time && row.end_time);

        if (timetableMode !== 'ignore' && !normalizedRows.length) {
          throw new Error('Add at least one valid timetable row or choose Ignore Timetable.');
        }

        for (let i = 0; i < normalizedRows.length; i += 1) {
          const row = normalizedRows[i];
          if (row.end_time <= row.start_time) {
            throw new Error(`Timetable row ${i + 1}: end time must be greater than start time.`);
          }
        }

        const toSeconds = value => (/^\d{2}:\d{2}$/.test(value) ? `${value}:00` : value);
        cleanup({
          class_id: usingSelected ? Number(selectedClass?.id || 0) : undefined,
          class_name: usingSelected ? undefined : className,
          subject: subject || undefined,
          level: level || undefined,
          student_mode: studentMode,
          students: studentRows,
          timetable_mode: timetableMode,
          effective_from: effectiveFrom || undefined,
          effective_to: effectiveTo || undefined,
          timetable_rows: normalizedRows.map(row => ({
            weekday: row.weekday,
            start_time: toSeconds(row.start_time),
            end_time: toSeconds(row.end_time),
            subject: row.subject || undefined,
            room: row.room || undefined,
            group: row.group || undefined,
          })),
        });
      } catch (err) {
        setError(err.message || 'Invalid setup input.');
      }
    });

    syncClassInputs();
    syncStudentInputs();
    renderRows();
    document.body.appendChild(overlay);
    classNameInput?.focus();
  });
}

async function _openAndSubmitClassInitSetup() {
  const selectedId = getSelectedId();
  const selectedClass = (getClasses() || []).find(row => Number(row.id) === Number(selectedId || 0)) || null;
  const payload = await _openClassInitWizardModal({ selectedClass });
  if (!payload) return;

  try {
    const result = await api('/workflow/class-setup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const classes = await api('/classes');
    setClasses(classes || []);
    setSelectedClassAndNotify(Number(result?.class_id || 0), String(result?.class_name || 'Class'));
    const studentsCreated = Number(result?.students_created || 0);
    const sessionsApplied = Number(result?.timetable_applied_rows || 0);
    showToast(`Setup saved: ${studentsCreated} students + ${sessionsApplied} timetable slots.`, 'ok');
  } catch (err) {
    showToast(err.message || 'Failed to submit class setup.', 'error');
  }
}

