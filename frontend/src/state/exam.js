/**
 * Exam state slice — Teacher Progress App
 */

const _state = {
    exams: [],
    selectedExamId: null,
    results: [],
    selectedStudentId: null,
    selectedStudentProfile: null,
};

// ---- Getters ----
export const getExams = () => _state.exams;
export const getSelectedExamId = () => _state.selectedExamId;
export const getResults = () => _state.results;
export const getSelectedStudent = () => _state.selectedStudentProfile;
export const getSelectedExam = () => _state.exams.find(e => e.id === _state.selectedExamId) || null;

// ---- Setters ----
export function setExams(exams) {
    _state.exams = Array.isArray(exams) ? exams : [];
}

export function setSelectedExamId(id) {
    _state.selectedExamId = id || null;
}

export function setResults(results) {
    _state.results = Array.isArray(results) ? results : [];
}

export function setSelectedStudent(id, profile) {
    _state.selectedStudentId = id || null;
    _state.selectedStudentProfile = profile || null;
}

export function clearExamState() {
    _state.exams = [];
    _state.selectedExamId = null;
    _state.results = [];
    _state.selectedStudentId = null;
    _state.selectedStudentProfile = null;
}
