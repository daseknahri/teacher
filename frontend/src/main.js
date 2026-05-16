/**
 * main.js — App Entry Point
 * Teacher Progress App
 *
 * Wires together: CSS, router, auth restoration, app shell, and all views.
 */

// ---- Styles (Tailwind v4 single entry) ----
import './style/app.css';

// ---- App modules ----
import { initRouter, route, fallback, navigate } from './router.js';
import { isLoggedIn, clearAuth, isOwner } from './state/auth.js';
import { setUserProfile } from './state/auth.js';
import { setClasses } from './state/class.js';
import { api } from './api/client.js';

import { renderShell, syncNav, onClassChange, updateClassSelector, refreshShell } from './components/AppShell.js';
import { setStudents, setDashboard, getSelectedId, setSelectedClass } from './state/class.js';
import { setWorkspace } from './state/workflow.js';
import { showToast } from './utils/toast.js';

// ---- Views ----
import { renderLoginView } from './views/LoginView.js';
import { renderClassView } from './views/ClassView.js';
import { renderWorkflowView } from './views/WorkflowView.js';
import { renderCalendarView } from './views/CalendarView.js';
import { renderExamView } from './views/ExamView.js';
import { renderOwnerView } from './views/OwnerView.js';
import { renderQuickPlannerView } from './views/QuickPlannerView.js';

function defaultAppRoute() {
    return isOwner() ? 'owner' : 'class';
}

function authGuard(viewFn) {
    return () => {
        if (!isLoggedIn()) { navigate('login'); return; }
        syncNav();
        viewFn();
    };
}

function teacherGuard(viewFn) {
    return authGuard(() => {
        if (isOwner()) { navigate('owner'); return; }
        viewFn();
    });
}

// ============================================================
// Router definitions
// ============================================================
route('login', () => {
    if (isLoggedIn()) { navigate(defaultAppRoute()); return; }
    renderLoginView();
});

route('class', teacherGuard(renderClassView));
route('workflow', teacherGuard(renderWorkflowView));
route('calendar', teacherGuard(renderCalendarView));
route('exams', teacherGuard(renderExamView));
route('owner', authGuard(() => {
    if (!isOwner()) { navigate('class'); return; }
    renderOwnerView();
}));
route('quick-planner', teacherGuard(renderQuickPlannerView));

fallback(() => {
    if (isLoggedIn()) navigate(defaultAppRoute());
    else navigate('login');
});

// ============================================================
// Bootstrap
// ============================================================
async function boot() {
    // Render the app shell first (sidebar, topbar, bottom tabs)
    renderShell();

    // If we have a stored token, restore session state
    if (isLoggedIn()) {
        try {
            const me = await api('/auth/me');
            setUserProfile(me);
            refreshShell();
            const classes = await api('/classes');
            setClasses(classes || []);
            if (isOwner()) {
                setSelectedClass(null, '');
                setStudents([]);
                setDashboard(null);
                setWorkspace({ active_unit: null, closed_units: [], active_session: null, recent_sessions: [] });
            } else {
                const selectedId = getSelectedId();
                const selectedExists = selectedId && (classes || []).some(c => c.id === selectedId);
                if (!selectedExists) {
                    const first = (classes || [])[0];
                    setSelectedClass(first?.id || null, first?.name || '');
                }
                updateClassSelector();

                // Load selected class data if there's one in localStorage
                const classId = getSelectedId();
                if (classId) {
                    const [students, dashboard, workspace] = await Promise.all([
                        api(`/classes/${classId}/students`).catch(() => []),
                        api(`/classes/${classId}/dashboard`).catch(() => null),
                        api(`/workflow/classes/${classId}`).catch(() => null),
                    ]);
                    setStudents(students || []);
                    setDashboard(dashboard);
                    if (workspace) setWorkspace(workspace);
                }
            }
        } catch {
            // Token invalid/expired — clear and redirect to login
            clearAuth();
            refreshShell();
            navigate('login');
            return;
        }
    }

    // Reload class data when user switches class
    onClassChange(async (classId) => {
        if (isOwner()) {
            setStudents([]);
            setDashboard(null);
            setWorkspace({ active_unit: null, closed_units: [], active_session: null, recent_sessions: [] });
            return;
        }
        if (!classId) {
            setStudents([]);
            setDashboard(null);
            setWorkspace({ active_unit: null, closed_units: [], active_session: null, recent_sessions: [] });
        } else {
            try {
                const [students, dashboard, workspace] = await Promise.all([
                    api(`/classes/${classId}/students`).catch(() => []),
                    api(`/classes/${classId}/dashboard`).catch(() => null),
                    api(`/workflow/classes/${classId}`).catch(() => null),
                ]);
                setStudents(students || []);
                setDashboard(dashboard);
                setWorkspace(workspace || { active_unit: null, closed_units: [], active_session: null, recent_sessions: [] });
            } catch { }
        }
        // Re-render current view with new class context
        const hash = window.location.hash.replace(/^#\/?/, '') || 'class';
        const viewFns = {
            class: renderClassView,
            workflow: renderWorkflowView,
            calendar: renderCalendarView,
            exams: renderExamView,
            'quick-planner': renderQuickPlannerView,
        };
        if (viewFns[hash]) viewFns[hash]();
    });

    // Start routing
    initRouter();
}

boot();

