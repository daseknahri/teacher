/**
 * AppShell.js  Sidebar + Topbar + Bottom Tab Bar
 * Teacher Progress App  Tailwind v4 (Enhanced UI)
 */

import { getUserName, getRole, isOwner } from '../state/auth.js';
import { getClasses, getSelectedId, setSelectedClass } from '../state/class.js';
import { clearAuth } from '../state/auth.js';
import { clearClassState } from '../state/class.js';
import { clearWorkflowState } from '../state/workflow.js';
import { clearExamState } from '../state/exam.js';
import { navigate, currentRoute } from '../router.js';

const TEACHER_NAV_ROUTES = [
  { id: 'class', icon: 'DB', label: 'Dashboard' },
  { id: 'workflow', icon: 'WF', label: 'Workflow' },
  { id: 'calendar', icon: 'CL', label: 'Calendar' },
  { id: 'exams', icon: 'EX', label: 'Exams' },
];

const OWNER_NAV_ROUTES = [
  { id: 'owner', icon: 'AD', label: 'Owner Panel' },
];

const _classChangeListeners = [];
let _shellRendered = false;

export function onClassChange(fn) { _classChangeListeners.push(fn); }

export function notifyClassChange(classId = getSelectedId()) {
  _classChangeListeners.forEach(fn => fn(classId || null));
}

export function setSelectedClassAndNotify(id, name) {
  setSelectedClass(id, name);
  updateClassSelector();
  notifyClassChange(id || null);
}

function _getUserPresentation() {
  const rawName = (getUserName() || '').trim();
  const name = rawName || (isOwner() ? 'Owner' : 'Teacher');
  const role = (getRole() || (isOwner() ? 'owner' : 'teacher')).toLowerCase();
  const roleLabel = role === 'owner' ? 'Owner' : 'Teacher';
  const initials = name.split(/\s+/).map(w => w[0]).join('').toUpperCase().slice(0, 2) || '?';
  return { name, role, roleLabel, initials };
}

function _navMarkup() {
  const navRoutes = isOwner() ? OWNER_NAV_ROUTES : TEACHER_NAV_ROUTES;
  return `
      <p class="text-[9px] font-bold uppercase tracking-[0.14em] text-white/25 px-3 pt-1 pb-2">${isOwner() ? 'Admin' : 'Main'}</p>
      ${navRoutes.map(r => `
        <button data-nav="${r.id}" class="nav-link" onclick="window.location.hash='${r.id}'">
          <span class="w-6 h-6 rounded-lg bg-white/8 flex items-center justify-center text-[12px] font-bold tracking-tight flex-shrink-0">${r.icon}</span>
          <span class="text-[13px]">${r.label}</span>
        </button>`).join('')}
  `;
}

function _sidebarUserMarkup() {
  const { name, roleLabel, initials } = _getUserPresentation();
  return `
      <div class="flex items-center gap-2.5 px-3 py-2.5 rounded-xl bg-white/7 border border-white/6 mb-0.5">
        <div class="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-indigo-500
                    flex items-center justify-center text-[11px] font-extrabold text-white
                    flex-shrink-0 shadow-sm">${initials}</div>
        <div class="flex-1 overflow-hidden">
          <p class="text-[12px] font-semibold text-white truncate leading-tight">${name}</p>
          <p class="text-[10px] text-white/40 uppercase tracking-wider">${roleLabel}</p>
        </div>
      </div>
      <button onclick="__logout()"
        class="nav-link !text-red-300/70 hover:!text-red-200 hover:!bg-red-950/60">
        <span class="w-6 h-6 rounded-lg bg-red-900/30 flex items-center justify-center text-[10px] font-bold flex-shrink-0">OUT</span>
        <span class="text-[13px]">Sign Out</span>
      </button>
  `;
}

function _topbarUserMarkup() {
  const { name, initials } = _getUserPresentation();
  return `
      <div class="w-6 h-6 rounded-full bg-gradient-to-br from-blue-400 to-indigo-500
                  flex items-center justify-center text-[10px] font-extrabold text-white
                  shadow-sm">${initials}</div>
      <span class="text-[12px] font-semibold text-slate-600">${name}</span>
  `;
}

function _applyRouteChrome() {
  const route = currentRoute();
  const isOwnerRoute = route === 'owner';
  const classSection = document.getElementById('topbar-class-section');
  const quickPlanner = document.getElementById('btn-open-quick-planner');
  const topbarTitle = document.getElementById('topbar-context-title');
  const bottomTabs = document.getElementById('bottom-tabs');
  if (classSection) classSection.style.display = isOwnerRoute ? 'none' : '';
  if (quickPlanner) quickPlanner.style.display = isOwnerRoute ? 'none' : '';
  if (bottomTabs) bottomTabs.style.display = isOwnerRoute ? 'none' : '';
  if (topbarTitle) {
    topbarTitle.textContent = isOwnerRoute ? 'Platform Administration' : 'Teaching Workspace';
  }
}

export function refreshShell() {
  if (!_shellRendered) return;
  const nav = document.getElementById('sidebar-nav');
  if (nav) nav.innerHTML = _navMarkup();
  const brandSubtitle = document.getElementById('sidebar-brand-subtitle');
  if (brandSubtitle) brandSubtitle.textContent = isOwner() ? 'Administration' : 'Teaching';
  const sidebarUser = document.getElementById('sidebar-user-card');
  if (sidebarUser) sidebarUser.innerHTML = _sidebarUserMarkup();
  const topbarUser = document.getElementById('topbar-user-card');
  if (topbarUser) topbarUser.innerHTML = _topbarUserMarkup();
  updateClassSelector();
  syncNav();
}

export function updateClassSelector() {
  const sel = document.getElementById('class-selector');
  if (!sel) return;
  const classes = getClasses();
  const cur = getSelectedId();
  sel.innerHTML = classes.length === 0
    ? '<option value="">No classes</option>'
    : classes.map(c =>
      `<option value="${c.id}" ${c.id === cur ? 'selected' : ''}>${c.name}</option>`
    ).join('');
}

export function syncNav() {
  const route = currentRoute();
  document.querySelectorAll('[data-nav]').forEach(el => {
    const r = el.dataset.nav;
    el.classList.toggle('active', r === route);
  });
  _applyRouteChrome();
}

function logout() {
  clearAuth();
  clearClassState();
  clearWorkflowState();
  clearExamState();
  navigate('login');
}

export function renderShell() {
  if (_shellRendered) return;
  _shellRendered = true;

  /*  SIDEBAR  */
  const sidebar = document.createElement('aside');
  sidebar.id = 'sidebar';
  sidebar.className = 'sidebar';
  sidebar.innerHTML = `
    <!-- Logo -->
    <div class="flex items-center gap-3 px-4 py-4 border-b border-white/8">
      <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-400 to-blue-600
                  flex items-center justify-center text-[11px] font-black tracking-tight text-white shadow-lg shadow-blue-900/40
                  flex-shrink-0">TP</div>
      <div>
        <div class="text-[13px] font-bold text-white tracking-tight leading-tight">Teacher Progress</div>
        <div id="sidebar-brand-subtitle" class="text-[10px] text-white/35 uppercase tracking-widest font-semibold">${isOwner() ? 'Administration' : 'Teaching'}</div>
      </div>
    </div>

    <!-- Nav links -->
    <nav id="sidebar-nav" class="flex-1 flex flex-col gap-0.5 px-3 py-3.5 overflow-y-auto">
      ${_navMarkup()}
    </nav>

    <!-- User card + logout -->
    <div id="sidebar-user-card" class="px-3 py-3.5 border-t border-white/8 flex flex-col gap-1">
      ${_sidebarUserMarkup()}
    </div>
  `;

  /*  TOPBAR  */
  const topbar = document.createElement('header');
  topbar.id = 'topbar';
  topbar.className = 'topbar';
  topbar.innerHTML = `
    <!-- Brand (mobile only) -->
    <div class="md:hidden flex items-center gap-2.5 font-bold text-[15px] text-slate-800">
      <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-blue-700
                  flex items-center justify-center text-[10px] font-black text-white tracking-tight shadow-sm">TP</div>
      <span class="tracking-tight">Teacher App</span>
    </div>

    <!-- Class selector -->
    <div id="topbar-class-section" class="flex-1 flex items-center gap-3 min-w-0 ml-2 md:ml-0">
      <label class="hidden sm:block text-[11px] font-bold uppercase tracking-widest
                    text-slate-400 whitespace-nowrap flex-shrink-0">Class</label>
      <div class="relative min-w-[130px] max-w-[260px] flex-shrink-1">
        <select id="class-selector"
          class="!h-9 !rounded-full !bg-slate-50 !border-slate-200/80 !text-[13px]
                 !font-semibold !text-slate-700 !pl-4 !pr-9 w-full cursor-pointer
                 shadow-sm hover:shadow-md transition-shadow">
          <option value="">Select class</option>
        </select>
      </div>
    </div>

    <!-- Right actions -->
    <div class="flex items-center gap-2 ml-auto">
      <div id="topbar-context-title" class="hidden xl:block text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400 mr-1">Teaching Workspace</div>
      <div id="topbar-user-card" class="hidden md:flex items-center gap-2.5 px-3 py-1.5 rounded-full
                  bg-slate-100/80 border border-slate-200/50">
        ${_topbarUserMarkup()}
      </div>
      <button id="btn-open-quick-planner"
        class="btn btn-ghost btn-sm !text-slate-500 hover:!text-blue-700 hover:!bg-blue-50"
        title="Open quick planner window">
        Quick Planner
      </button>
      <button onclick="__logout()"
        class="btn btn-ghost btn-sm !text-slate-400 hover:!text-red-600 hover:!bg-red-50"
        title="Sign out">
        Sign out
      </button>
    </div>
  `;

  /*  BOTTOM TABS  */
  const btabs = document.createElement('nav');
  btabs.id = 'bottom-tabs';
  btabs.className = 'bottom-tabs';
  btabs.innerHTML = TEACHER_NAV_ROUTES.map(r => `
    <button data-nav="${r.id}" class="tab-item" onclick="window.location.hash='${r.id}'">
      <span class="text-[22px] leading-none">${r.icon}</span>
      <span>${r.label}</span>
    </button>`).join('');

  /*  MAIN CONTENT  */
  const main = document.createElement('main');
  main.id = 'app-main';
  main.className = 'main-content';
  const content = document.createElement('div');
  content.id = 'app-content';
  main.appendChild(content);

  /* Mount into #app */
  const app = document.getElementById('app');
  app.className = 'flex min-h-dvh bg-slate-100';
  app.appendChild(sidebar);
  app.appendChild(topbar);
  app.appendChild(btabs);
  app.appendChild(main);

  window.__logout = logout;

  document.getElementById('class-selector').addEventListener('change', e => {
    const id = Number(e.target.value);
    if (!id) {
      setSelectedClassAndNotify(null, '');
      return;
    }
    const classes = getClasses();
    const cls = classes.find(c => c.id === id);
    if (!cls) {
      setSelectedClassAndNotify(null, '');
      return;
    }
    setSelectedClassAndNotify(id, cls.name);
  });

  updateClassSelector();

  document.getElementById('btn-open-quick-planner')?.addEventListener('click', () => {
    const target = `${window.location.pathname}${window.location.search}#quick-planner`;
    window.open(target, 'teacher_quick_planner', 'width=1380,height=920');
  });

  refreshShell();
}

