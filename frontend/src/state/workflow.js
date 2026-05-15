/**
 * Workflow state slice — Teacher Progress App
 */

const _state = {
    activeUnit: null,   // WorkflowUnitOut | null
    closedUnits: [],
    activeSession: null,   // WorkflowSessionOut | null
    recentSessions: [],
    calendar: [],
    checklist: [],     // flat list derived from activeUnit for rendering
    absentIds: new Set(),  // student IDs marked absent in current/upcoming session
};

// ---- Getters ----
export const getActiveUnit = () => _state.activeUnit;
export const getClosedUnits = () => _state.closedUnits;
export const getActiveSession = () => _state.activeSession;
export const getRecentSessions = () => _state.recentSessions;
export const getCalendar = () => _state.calendar;
export const getAbsentIds = () => _state.absentIds;
export const hasActiveUnit = () => Boolean(_state.activeUnit);
export const hasActiveSession = () => Boolean(_state.activeSession);

// ---- Setters ----
export function setWorkspace({ active_unit, closed_units, active_session, recent_sessions }) {
    _state.activeUnit = active_unit || null;
    _state.closedUnits = closed_units || [];
    _state.activeSession = active_session || null;
    _state.recentSessions = recent_sessions || [];
}

export function setCalendar(events) {
    _state.calendar = Array.isArray(events) ? events : [];
}

export function setActiveSession(session) {
    _state.activeSession = session || null;
}

export function setActiveUnit(unit) {
    _state.activeUnit = unit || null;
}

export function toggleAbsent(studentId) {
    if (_state.absentIds.has(studentId)) _state.absentIds.delete(studentId);
    else _state.absentIds.add(studentId);
}

export function setAbsentIds(ids) {
    _state.absentIds = new Set(Array.isArray(ids) ? ids : []);
}

export function clearAbsentIds() {
    _state.absentIds = new Set();
}

export function clearWorkflowState() {
    _state.activeUnit = null;
    _state.closedUnits = [];
    _state.activeSession = null;
    _state.recentSessions = [];
    _state.calendar = [];
    _state.absentIds = new Set();
}
