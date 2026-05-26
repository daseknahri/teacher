/**
 * ExamView.js  Exam results, stats, student drilldown
 * Teacher Progress App  Tailwind v4
 */
import { api, downloadWithAuth } from '../api/client.js';
import {
  getExams, getSelectedExamId, getResults, getSelectedExam,
  setExams, setSelectedExamId, setResults,
} from '../state/exam.js';
import { getSelectedId } from '../state/class.js';
import { showToast } from '../utils/toast.js';
import { askConfirm } from '../utils/modal.js';
import { mountRetryCard } from '../utils/retryView.js';
import { fmtDate, fmtScore, fmtPct } from '../utils/format.js';
import { navigate } from '../router.js';

let _sortKey = 'full_name';
let _sortAsc = true;
let _filterQ = '';
let _showArchived = false;

export async function renderExamView() {
  _showChrome();
  const el = document.getElementById('app-content');
  const classId = getSelectedId();

  if (!classId) {
    el.innerHTML = `<div class="view-container">
          <div class="empty-state bg-white rounded-3xl border border-slate-200 py-16 text-center">
            <div class="text-3xl font-black opacity-30 mb-4">EXAM</div>
            <h2 class="font-semibold text-slate-500">No class selected</h2>
            <p class="text-[13px] text-slate-400">Select a class from the dropdown first.</p>
          </div></div>`;
    return;
  }

  el.innerHTML = `<div class="view-container"><div class="skeleton h-96 rounded-2xl animate-pulse"></div></div>`;

  try {
    const exams = await api(`/classes/${classId}/exams`);
    setExams(exams || []);
    const selectedId = getSelectedExamId();
    const selectedExists = selectedId && (exams || []).some(e => e.id === selectedId);
    if (!selectedExists) {
      setSelectedExamId(exams?.[0]?.id || null);
    }
    const examId = getSelectedExamId();
    if (examId) {
      const results = await api(`/exams/${examId}/results`);
      setResults(results || []);
    }
  } catch {
    mountRetryCard(el, {
      title: 'Exams View Unavailable',
      message: 'Unable to load exam data right now. Retry after checking API connection.',
      buttonId: 'btn-retry-exam-load',
      onRetry: () => renderExamView(),
    });
    showToast('Failed to load exams data.', 'error');
    return;
  }

  _renderExam(el, classId);
}

function _renderExam(el, classId) {
  const exams = getExams();
  const examId = getSelectedExamId();
  const exam = getSelectedExam();
  const results = getResults();
  const examWorkflowActive = exam?.linked_exam_workflow_status === 'active';
  const correctionWorkflowActive = exam?.linked_correction_workflow_status === 'active';
  const examWorkflowLabel = examWorkflowActive
    ? 'Open Supervision Workflow'
    : exam?.linked_exam_workflow_unit_id
      ? 'Reopen Supervision Workflow'
      : 'Supervision Workflow';
  const correctionWorkflowLabel = correctionWorkflowActive
    ? 'Open Correction Workflow'
    : exam?.linked_correction_workflow_unit_id
      ? 'Reopen Correction Workflow'
      : 'Correction Workflow';

  // Stats
  const scores = results.map(r => r.score).filter(s => s != null);
  const avg = scores.length ? (scores.reduce((a, b) => a + b, 0) / scores.length) : null;
  const top = scores.length ? Math.max(...scores) : null;
  const min = scores.length ? Math.min(...scores) : null;
  const pass = exam ? scores.filter(s => s >= 10).length : null;

  // Sort
  let sorted = [...results];
  sorted.sort((a, b) => {
    let va = a[_sortKey], vb = b[_sortKey];
    if (va == null && vb == null) return 0;
    if (va == null) return _sortAsc ? 1 : -1;
    if (vb == null) return _sortAsc ? -1 : 1;
    if (typeof va === 'string') va = va.toLowerCase();
    if (typeof vb === 'string') vb = vb.toLowerCase();
    if (va === vb) return 0;
    return _sortAsc ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
  });
  if (_filterQ) {
    sorted = sorted.filter(r => (r.full_name || '').toLowerCase().includes(_filterQ) ||
      (r.student_code || '').toLowerCase().includes(_filterQ));
  }

  el.innerHTML = `
    <div class="view-container">

      <!-- Header -->
      <div class="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div class="flex items-center gap-2 text-[12px] text-slate-400 mb-1"> Exams</div>
          <h1 class="text-2xl font-bold text-slate-800 tracking-tight">${exam?.title || 'Select an exam'}</h1>
          ${exam ? `<p class="text-[13px] text-slate-400 mt-0.5">${fmtDate(exam.exam_date)} | Max ${exam.max_score ?? 20} pts</p>` : ''}
          ${exam ? `
            <div class="mt-2 flex flex-wrap gap-2">
              ${exam.linked_exam_workflow_unit_id ? `<span class="badge ${examWorkflowActive ? 'badge-green' : 'badge-gray'}">${_escapeHtml(examWorkflowActive ? 'Supervision workflow active' : 'Supervision workflow linked')}</span>` : ''}
              ${exam.linked_correction_workflow_unit_id ? `<span class="badge ${correctionWorkflowActive ? 'badge-green' : 'badge-gray'}">${_escapeHtml(correctionWorkflowActive ? 'Correction workflow active' : 'Correction workflow linked')}</span>` : ''}
            </div>` : ''}
        </div>
        <div class="flex gap-2 flex-wrap">
          ${examId ? `
            <button id="btn-download-template" class="btn btn-ghost btn-sm" title="Download student mark template"> Template</button>
            <button id="btn-import-results" class="btn btn-secondary"> Import</button>
            <button id="btn-export-results" class="btn btn-secondary"> Export</button>
            ${exam && !exam.is_archived ? `
              <button id="btn-create-exam-workflow" class="btn btn-ghost btn-sm" title="Create, reopen, or open the supervision workflow for this exam">${examWorkflowLabel}</button>
              <button id="btn-create-correction-workflow" class="btn btn-ghost btn-sm" title="Create, reopen, or open the workflow unit for this exam correction">${correctionWorkflowLabel}</button>
            ` : ''}
          ` : ''}
          ${exam && !exam.is_archived ? `
            <button id="btn-edit-exam" class="btn btn-ghost btn-sm" title="Edit exam"> Edit</button>
            <button id="btn-archive-exam" class="btn btn-ghost btn-sm !text-slate-400 hover:!text-red-600"> Archive</button>
          ` : ''}
          ${exam?.is_archived ? `<button id="btn-restore-exam" class="btn btn-secondary btn-sm"> Restore</button>` : ''}
        </div>
      </div>

      <!-- Exam pill tabs -->
      ${exams.length ? `
      <div class="flex items-center gap-2 flex-wrap overflow-x-auto pb-1">
        <div class="flex gap-2 flex-wrap flex-1">
          ${(_showArchived ? exams : exams.filter(e => !e.is_archived)).map(e => `
          <button class="pill ${e.id === examId ? 'active' : ''} ${e.is_archived ? 'opacity-60 line-through' : ''}"
                  data-exam-id="${e.id}">${e.title}</button>`).join('')}
        </div>
        ${exams.some(e => e.is_archived) ? `
        <button id="btn-toggle-archived" class="btn btn-ghost btn-sm !text-[11px] flex-shrink-0">
          ${_showArchived ? 'Hide archived' : 'Show archived'}
        </button>` : ''}
      </div>` : `
      <div class="notice-banner">
         No exams yet. Create an exam below to get started.
      </div>`}

      ${examId ? `
      <!-- Stats bar -->
      <div class="stat-strip p-4 sm:p-5 flex flex-wrap gap-5 sm:gap-8 bg-white border border-slate-200/80 rounded-2xl shadow-sm mb-2">
        <div class="flex flex-col gap-1">
          <span class="text-[28px] font-extrabold text-slate-800 leading-none tracking-tight">${avg != null ? fmtScore(avg) : '--'}</span>
          <span class="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Class Avg</span>
        </div>
        <div class="hidden sm:block w-px bg-slate-100 self-stretch"></div>
        <div class="flex flex-col gap-1">
          <span class="text-[28px] font-extrabold text-green-600 leading-none tracking-tight">${top != null ? fmtScore(top) : '--'}</span>
          <span class="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Top</span>
        </div>
        <div class="hidden sm:block w-px bg-slate-100 self-stretch"></div>
        <div class="flex flex-col gap-1">
          <span class="text-[28px] font-extrabold text-red-500 leading-none tracking-tight">${min != null ? fmtScore(min) : '--'}</span>
          <span class="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Min</span>
        </div>
        <div class="hidden sm:block w-px bg-slate-100 self-stretch"></div>
        <div class="flex flex-col gap-1">
          <span class="text-[28px] font-extrabold text-slate-800 leading-none tracking-tight">${pass != null ? pass : '--'}</span>
          <span class="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Passed</span>
        </div>
        <div class="ml-auto flex items-end">
          <div class="relative w-full sm:w-48">
            <span class="absolute left-3 top-1/2 -translate-y-1/2 text-[10px] opacity-50">Find</span>
            <input id="result-filter" type="text" placeholder="Filter..."
              class="!pl-8 !h-9 border-slate-200/80 shadow-sm" value="${_filterQ}" aria-label="Filter exam results by student name or code" />
          </div>
        </div>
      </div>

      <!-- Results table -->
      <div class="card">
        <div class="overflow-auto">
          <table class="data-table">
            <caption class="sr-only">Exam results for selected exam</caption>
            <thead>
              <tr>
                <th scope="col">#</th> ${_th('Student', 'full_name')} ${_th('Code', 'student_code')}
                ${_th('Score', 'score')} <th scope="col">/ Max</th> ${_th('Note', 'note')}
                <th scope="col">Details</th>
              </tr>
            </thead>
            <tbody>
              ${sorted.map((r, i) => {
    const pct = exam?.max_score ? r.score / exam.max_score : null;
    const colorClass = pct == null ? '' : pct >= 0.8 ? 'text-green-700 font-bold' :
      pct >= 0.5 ? 'text-amber-700 font-semibold' : 'text-red-600 font-semibold';
    return `
                  <tr class="cursor-pointer group" data-student-id="${r.student_id}">
                    <td class="text-slate-400 text-[11px] font-mono">${String(i + 1).padStart(2, '0')}</td>
                    <td>
                      <div class="flex items-center gap-2.5">
                        <div class="w-7 h-7 rounded-full bg-gradient-to-br from-indigo-100 to-purple-200
                                    flex items-center justify-center text-[10px] font-bold text-indigo-700 flex-shrink-0">
                          ${(r.full_name || '?').charAt(0).toUpperCase()}
                        </div>
                        <span class="font-semibold text-slate-800 text-[13px]">${r.full_name || 'N/A'}</span>
                      </div>
                    </td>
                    <td><code class="text-[11px] bg-slate-100/80 text-slate-600 px-2 py-0.5 rounded-md">${r.student_code || 'N/A'}</code></td>
                    <td class="${colorClass} text-[13px]">${r.score != null ? fmtScore(r.score) : 'N/A'}</td>
                    <td class="text-slate-400 text-[12px]">/ ${exam?.max_score ?? 20}</td>
                    <td class="text-slate-500 text-[12px] max-w-[140px] truncate" title="${r.note || ''}">${r.note || 'N/A'}</td>
                    <td>
                      <div class="row-hover-actions flex gap-1.5 flex-wrap">
                        <button class="btn btn-ghost btn-sm btn-icon btn-edit-result bg-slate-100/50 hover:bg-slate-200"
                                    data-student-id="${r.student_id}" data-result-id="${r.id ?? ''}" onclick="event.stopPropagation()" title="Edit result">
                          Edit
                        </button>
                        <button class="btn btn-ghost btn-sm !text-blue-600 btn-detail"
                                    data-student-id="${r.student_id}" onclick="event.stopPropagation()">
                             View
                        </button>
                      </div>
                    </td>
                  </tr>`;
  }).join('')}
              ${sorted.length === 0 ? `
              <tr><td colspan="7" class="text-center py-8 text-slate-400 text-[13px]">
                No results recorded yet.
              </td></tr>` : ''}
            </tbody>
          </table>
        </div>
      </div>` : ''
    }

      <!-- Create exam -->
      <div class="card">
        <div class="card-header">
          <h3 class="font-semibold text-slate-700 text-[14px]"> New Exam</h3>
        </div>
        <div class="card-body">
          <div class="grid sm:grid-cols-3 gap-4">
            <div class="flex flex-col gap-1.5 sm:col-span-1">
              <label class="text-[11px] font-bold text-slate-400 uppercase tracking-widest">Name <span class="text-red-400">*</span></label>
              <input id="new-exam-name" type="text" placeholder="e.g. Mid-term Exam" class="shadow-sm" />
            </div>
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-bold text-slate-400 uppercase tracking-widest">Date <span class="text-red-400">*</span></label>
              <input id="new-exam-date" type="date" value="${new Date().toISOString().split('T')[0]}" class="shadow-sm" />
            </div>
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-bold text-slate-400 uppercase tracking-widest">Max score <span class="text-red-400">*</span></label>
              <input id="new-exam-max" type="number" min="1" placeholder="20" value="20" class="shadow-sm" />
            </div>
          </div>
          <button id="btn-create-exam" class="btn btn-primary mt-4">Create Exam</button>
        </div>
      </div>

    </div > `;

  _bindExamEvents(el, classId);
}

function _th(label, key) {
  const isActive = _sortKey === key;
  const icon = isActive ? (_sortAsc ? '^' : 'v') : '<>';
  const ariaSort = isActive ? (_sortAsc ? 'ascending' : 'descending') : 'none';
  return `<th scope="col" data-sort="${key}" class="${isActive ? 'sorted' : ''}" tabindex="0" role="button" aria-sort="${ariaSort}" aria-label="Sort by ${label}">
    ${label} <span class="sort-icon">${icon}</span>
  </th>`;
}

function _bindExamEvents(el, classId) {
  async function createLinkedWorkflow(unitType, label) {
    const exam = getSelectedExam();
    if (!exam) {
      showToast('Select an exam first.', 'warning');
      return;
    }
    const isOpenOnly = unitType === 'exam'
      ? exam.linked_exam_workflow_status === 'active'
      : exam.linked_correction_workflow_status === 'active';
    if (isOpenOnly) {
      navigate('workflow');
      return;
    }
    try {
      const result = await api(`/workflow/classes/${classId}/exams/${exam.id}/linked-unit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ unit_type: unitType }),
      });
      showToast(
        result?.created
          ? `${label} ready in Workflow.`
          : result?.reopened
            ? `${label} reopened in Workflow.`
            : `${label} already active in Workflow.`,
        'ok'
      );
      navigate('workflow');
    } catch (err) {
      showToast(err.message || `Failed to open ${label.toLowerCase()}.`, 'error');
    }
  }

  // Pill tab switch
  el.querySelectorAll('[data-exam-id]').forEach(btn => {
    btn.addEventListener('click', async () => {
      setSelectedExamId(Number(btn.dataset.examId));
      const results = await api(`/exams/${btn.dataset.examId}/results`).catch(() => []);
      setResults(results || []);
      _renderExam(el, classId);
    });
  });

  // Archived filter toggle
  el.querySelector('#btn-toggle-archived')?.addEventListener('click', () => {
    _showArchived = !_showArchived;
    _renderExam(el, classId);
  });

  // Sort columns
  el.querySelectorAll('[data-sort]').forEach(th => {
    const applySort = () => {
      const key = th.dataset.sort;
      if (_sortKey === key) _sortAsc = !_sortAsc;
      else { _sortKey = key; _sortAsc = true; }
      _renderExam(el, classId);
    };
    th.addEventListener('click', applySort);
    th.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      applySort();
    });
  });

  // Filter
  el.querySelector('#result-filter')?.addEventListener('input', e => {
    _filterQ = e.target.value.toLowerCase();
    _renderExam(el, classId);
  });

  // Create exam
  el.querySelector('#btn-create-exam')?.addEventListener('click', async function () {
    const btn = this;
    const name = document.getElementById('new-exam-name')?.value?.trim();
    const dateVal = document.getElementById('new-exam-date')?.value || new Date().toISOString().split('T')[0];
    const max = Number(document.getElementById('new-exam-max')?.value) || 20;
    if (!name) { showToast('Enter an exam name.', 'warning'); return; }
    btn.classList.add('btn-busy'); btn.disabled = true;
    try {
      const exam = await api(`/classes/${classId}/exams`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: name,
          exam_date: dateVal,
          max_score: max,
        }),
      });
      const exams = await api(`/classes/${classId}/exams`);
      setExams(exams || []);
      setSelectedExamId(exam.id);
      setResults([]);
      _renderExam(el, classId);
      showToast(`Exam "${name}" created!`, 'ok');
    } catch (err) {
      btn.classList.remove('btn-busy'); btn.disabled = false;
      showToast(err.message, 'error');
    }
  });

  // Import results
  el.querySelector('#btn-import-results')?.addEventListener('click', () => {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = '.xlsx,.xls';
    inp.onchange = async () => {
      const file = inp.files[0]; if (!file) return;
      const form = new FormData(); form.append('file', file);
      try {
        const examId = getSelectedExamId();
        if (!examId) {
          showToast('Please select an exam first.', 'warning');
          return;
        }
        const r = await api(`/exams/${examId}/results/import`, { method: 'POST', body: form });
        showToast(`Imported ${r.imported} results.`, 'ok');
        const results = await api(`/exams/${examId}/results`);
        setResults(results || []);
        _renderExam(el, classId);
      } catch (err) { showToast(err.message, 'error'); }
    };
    inp.click();
  });

  // Export results
  el.querySelector('#btn-export-results')?.addEventListener('click', async () => {
    try {
      const examId = getSelectedExamId();
      if (!examId) return;
      // Try CSV first; fall back to xlsx if not available
      await downloadWithAuth(
        `/exams/${examId}/results.csv`,
        `exam-${examId}-results.csv`
      );
    } catch {
      try {
        const examId = getSelectedExamId();
        await downloadWithAuth(`/exams/${examId}/results.xlsx`, `exam-${examId}.xlsx`);
      } catch (err) { showToast(err.message, 'error'); }
    }
  });

  // Download template
  el.querySelector('#btn-download-template')?.addEventListener('click', async () => {
    try {
      const examId = getSelectedExamId();
      if (!examId) return;
      await downloadWithAuth(`/exams/${examId}/template`, `exam-${examId}-template.xlsx`);
    } catch (err) { showToast(err.message || 'Template download failed.', 'error'); }
  });

  el.querySelector('#btn-create-exam-workflow')?.addEventListener('click', async () => {
    await createLinkedWorkflow('exam', 'Exam workflow');
  });

  el.querySelector('#btn-create-correction-workflow')?.addEventListener('click', async () => {
    await createLinkedWorkflow('exam_correction', 'Correction workflow');
  });

  // Edit exam
  el.querySelector('#btn-edit-exam')?.addEventListener('click', async () => {
    const exam = getSelectedExam();
    if (!exam) return;
    const updated = await _editExamModal(exam);
    if (!updated) return;
    try {
      await api(`/exams/${exam.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updated),
      });
      const exams = await api(`/classes/${classId}/exams`);
      setExams(exams || []);
      _renderExam(el, classId);
      showToast('Exam updated.', 'ok');
    } catch (err) { showToast(err.message, 'error'); }
  });

  // Archive/restore exam
  el.querySelector('#btn-archive-exam')?.addEventListener('click', async () => {
    const ok = await askConfirm('Archive this exam?');
    if (!ok) return;
    try {
      await api(`/exams/${examId}/archive`, { method: 'POST' });
      const exams = await api(`/classes/${classId}/exams`);
      setExams(exams || []);
      setSelectedExamId(exams?.[0]?.id || null);
      _renderExam(el, classId);
      showToast('Exam archived.', 'ok');
    } catch (err) { showToast(err.message, 'error'); }
  });
  el.querySelector('#btn-restore-exam')?.addEventListener('click', async () => {
    const examId = getSelectedExamId();
    if (!examId) return;
    try {
      await api(`/exams/${examId}/restore`, { method: 'POST' });
      const exams = await api(`/classes/${classId}/exams`);
      setExams(exams || []);
      setSelectedExamId(examId);
      _renderExam(el, classId);
      showToast('Exam restored!', 'ok');
    } catch (err) { showToast(err.message, 'error'); }
  });

  // Edit result (inline note/score/teacher_comment editor)
  el.querySelectorAll('.btn-edit-result').forEach(btn => {
    btn.addEventListener('click', async () => {
      const sid = Number(btn.dataset.studentId);
      const examId = getSelectedExamId();
      if (!examId || !sid) return;
      const result = getResults().find(r => r.student_id === sid) || {};
      const exam = getSelectedExam();
      const updated = await _editResultModal(result, exam);
      if (!updated) return;
      btn.classList.add('btn-busy'); btn.disabled = true;
      try {
        await api(`/exams/${examId}/results/${sid}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updated),
        });
        const results = await api(`/exams/${examId}/results`);
        setResults(results || []);
        _renderExam(el, classId);
        showToast('Result updated.', 'ok');
      } catch (err) {
        btn.classList.remove('btn-busy'); btn.disabled = false;
        showToast(err.message, 'error');
      }
    });
  });

  // Student detail drilldown
  el.querySelectorAll('.btn-detail').forEach(btn => {
    btn.addEventListener('click', async () => {
      const sid = Number(btn.dataset.studentId);
      try {
        const profile = await api(`/classes/${classId}/students/${sid}/profile`);
        _showStudentModal(_normalizeStudentProfile(profile));
      } catch (err) { showToast(err.message, 'error'); }
    });
  });
}

function _editResultModal(result, exam) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const maxScore = exam?.max_score ?? 20;
    overlay.innerHTML = `
      <div class="modal max-w-lg">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800"> Edit Result</h2>
          <p class="text-[12px] text-slate-400 mt-1">${result.full_name || 'Student'}</p>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="flex flex-col gap-1.5">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Score <span class="text-slate-300">/ ${maxScore}</span></label>
            <input id="edit-result-score" type="number" min="0" max="${maxScore}" step="0.5"
              value="${result.score ?? ''}" placeholder="e.g. 14.5" />
          </div>
          <div class="flex flex-col gap-1.5">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Note</label>
            <input id="edit-result-note" type="text" value="${result.note || ''}" placeholder="Short note..." />
          </div>
          <div class="flex flex-col gap-1.5">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Teacher Comment</label>
            <textarea id="edit-result-comment" rows="3" placeholder="Detailed feedback...">${result.teacher_comment || ''}</textarea>
          </div>
          <p id="edit-result-error" class="text-[12px] text-red-600 hidden"></p>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="edit-result-cancel" class="btn btn-ghost">Cancel</button>
          <button id="edit-result-save" class="btn btn-primary">Save Result</button>
        </div>
      </div>`;
    function cleanup(v) { overlay.remove(); resolve(v); }
    overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(null); });
    overlay.querySelector('#edit-result-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#edit-result-save')?.addEventListener('click', () => {
      const scoreRaw = overlay.querySelector('#edit-result-score')?.value;
      const score = scoreRaw !== '' && scoreRaw != null ? Number(scoreRaw) : null;
      if (score !== null && (isNaN(score) || score < 0)) {
        const err = overlay.querySelector('#edit-result-error');
        if (err) { err.textContent = 'Score must be a valid positive number.'; err.classList.remove('hidden'); }
        return;
      }
      const note = overlay.querySelector('#edit-result-note')?.value?.trim() || null;
      const comment = overlay.querySelector('#edit-result-comment')?.value?.trim() || null;
      cleanup({ score, note, teacher_comment: comment });
    });
    document.body.appendChild(overlay);
    overlay.querySelector('#edit-result-score')?.focus();
  });
}

function _editExamModal(exam) {

  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const dateVal = exam.exam_date ? exam.exam_date.split('T')[0] : '';
    overlay.innerHTML = `
      <div class="modal max-w-lg">
        <div class="px-6 py-5 border-b border-slate-100">
          <h2 class="text-[16px] font-bold text-slate-800"> Edit Exam</h2>
        </div>
        <div class="px-6 py-5 flex flex-col gap-3">
          <div class="flex flex-col gap-1.5">
            <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Title</label>
            <input id="edit-exam-title" type="text" value="${exam.title || ''}" placeholder="Exam title" />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Date</label>
              <input id="edit-exam-date" type="date" value="${dateVal}" />
            </div>
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Max Score</label>
              <input id="edit-exam-max" type="number" min="1" value="${exam.max_score ?? 20}" />
            </div>
          </div>
          <p id="edit-exam-error" class="text-[12px] text-red-600 hidden"></p>
        </div>
        <div class="px-6 pb-5 flex gap-3 justify-end border-t border-slate-100 pt-3">
          <button id="edit-exam-cancel" class="btn btn-ghost">Cancel</button>
          <button id="edit-exam-save" class="btn btn-primary">Save Changes</button>
        </div>
      </div>`;
    function cleanup(v) { overlay.remove(); resolve(v); }
    overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(null); });
    overlay.querySelector('#edit-exam-cancel')?.addEventListener('click', () => cleanup(null));
    overlay.querySelector('#edit-exam-save')?.addEventListener('click', () => {
      const title = overlay.querySelector('#edit-exam-title')?.value?.trim();
      if (!title) {
        const err = overlay.querySelector('#edit-exam-error');
        if (err) { err.textContent = 'Title is required.'; err.classList.remove('hidden'); }
        return;
      }
      const dateInput = overlay.querySelector('#edit-exam-date')?.value || null;
      const maxScore = Number(overlay.querySelector('#edit-exam-max')?.value) || 20;
      cleanup({ title, exam_date: dateInput || undefined, max_score: maxScore });
    });
    document.body.appendChild(overlay);
    overlay.querySelector('#edit-exam-title')?.focus();
  });
}

function _normalizeStudentProfile(payload) {

  const student = payload?.student || {};
  const attendance = payload?.attendance || {};
  const exams = payload?.exams || {};
  const counts = attendance.counts || {};
  const totalRows = Number(attendance.total_rows || 0);
  const presentLike = Number(counts.present || 0) + Number(counts.late || 0) + Number(counts.excused || 0);
  const attendancePct = totalRows > 0 ? (presentLike / totalRows) : null;
  const examHistory = Array.isArray(exams.results)
    ? exams.results.map(item => ({
      exam_name: item.title,
      score: item.score,
      max_score: item.max_score,
    }))
    : [];
  return {
    full_name: student.full_name,
    student_code: student.student_code,
    attendance_pct: attendancePct,
    avg_score: exams.average_score,
    exam_history: examHistory,
  };
}

function _showStudentModal(p) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal max-w-lg">
      <div class="flex items-center justify-between gap-3 px-6 py-5 border-b border-slate-100">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-full bg-blue-100 flex items-center justify-center
                      text-[14px] font-bold text-blue-700">
            ${(p.full_name || '?').charAt(0).toUpperCase()}
          </div>
          <div>
            <h2 class="text-[16px] font-bold text-slate-800">${p.full_name || 'N/A'}</h2>
            <p class="text-[12px] text-slate-400"><code>${p.student_code || 'N/A'}</code></p>
          </div>
        </div>
        <button id="close-modal" class="btn btn-ghost btn-sm !text-slate-400">Close</button>
      </div>
      <div class="p-6 flex flex-col gap-4">
        <div class="grid grid-cols-2 gap-3">
          <div class="bg-slate-50 rounded-xl p-3 border border-slate-200">
            <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Attendance</div>
            <div class="text-[22px] font-bold text-slate-800">${p.attendance_pct != null ? fmtPct(p.attendance_pct) : '---'}</div>
          </div>
          <div class="bg-slate-50 rounded-xl p-3 border border-slate-200">
            <div class="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1">Avg Score</div>
            <div class="text-[22px] font-bold text-slate-800">${p.avg_score != null ? fmtScore(p.avg_score) : '---'}</div>
          </div>
        </div>
        ${p.exam_history?.length ? `
        <div>
          <h4 class="text-[12px] font-semibold text-slate-400 uppercase tracking-wider mb-2">Exam History</h4>
          <div class="flex flex-col gap-1.5">
            ${p.exam_history.map(e => `
            <div class="flex items-center gap-3 px-3 py-2 bg-slate-50 rounded-xl border border-slate-100">
              <span class="flex-1 text-[13px] text-slate-700 font-medium">${e.exam_name}</span>
              <span class="font-bold text-slate-800">${fmtScore(e.score)}</span>
              <span class="text-[11px] text-slate-400">/ ${e.max_score ?? 20}</span>
            </div>`).join('')}
          </div>
        </div>` : ''}
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#close-modal')?.addEventListener('click', () => overlay.remove());
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}

function _escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
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

