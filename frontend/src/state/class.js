/**
 * Class state slice — Teacher Progress App
 */

const CLASS_KEY = 'ta_class_id';

const _state = {
    classes: [],
    selectedId: Number(localStorage.getItem(CLASS_KEY)) || null,
    selectedName: '',
    students: [],
    dashboard: null,
    classTeachers: [],
};

// ---- Getters ----
export const getClasses = () => _state.classes;
export const getSelectedId = () => _state.selectedId;
export const getSelectedName = () => _state.selectedName;
export const getStudents = () => _state.students;
export const getDashboard = () => _state.dashboard;
export const getClassTeachers = () => _state.classTeachers;
export const hasClass = () => Boolean(_state.selectedId);
export const hasStudents = () => _state.students.length > 0;

// ---- Setters ----
export function setClasses(classes) {
    _state.classes = Array.isArray(classes) ? classes : [];
    if (_state.classes.length === 0) {
        _state.selectedId = null;
        _state.selectedName = '';
        localStorage.removeItem(CLASS_KEY);
        return;
    }
    const selected = _state.classes.find(c => c.id === _state.selectedId);
    if (selected) {
        _state.selectedName = selected.name || '';
        return;
    }
    const first = _state.classes[0];
    _state.selectedId = first?.id || null;
    _state.selectedName = first?.name || '';
    if (_state.selectedId) localStorage.setItem(CLASS_KEY, String(_state.selectedId));
    else localStorage.removeItem(CLASS_KEY);
}

export function setSelectedClass(id, name) {
    _state.selectedId = id || null;
    _state.selectedName = name || '';
    if (id) localStorage.setItem(CLASS_KEY, String(id));
    else localStorage.removeItem(CLASS_KEY);
}

export function setStudents(students) {
    _state.students = Array.isArray(students) ? students : [];
}

export function setDashboard(data) {
    _state.dashboard = data || null;
}

export function setClassTeachers(teachers) {
    _state.classTeachers = Array.isArray(teachers) ? teachers : [];
}

export function clearClassState() {
    _state.selectedId = null;
    _state.selectedName = '';
    _state.students = [];
    _state.dashboard = null;
    _state.classTeachers = [];
    localStorage.removeItem(CLASS_KEY);
}
