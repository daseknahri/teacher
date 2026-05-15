/**
 * Auth state slice — Teacher Progress App
 */

const AUTH_KEY = 'ta_token';
const EMAIL_KEY = 'ta_email';

const _state = {
    token: localStorage.getItem(AUTH_KEY) || '',
    email: localStorage.getItem(EMAIL_KEY) || '',
    userId: null,
    role: '',
    name: '',
};

// ---- Getters ----
export const getToken = () => _state.token;
export const getEmail = () => _state.email;
export const getUserId = () => _state.userId;
export const getRole = () => _state.role;
export const getUserName = () => _state.name;
export const isLoggedIn = () => Boolean(_state.token);
export const isOwner = () => _state.role?.toLowerCase() === 'owner';
export const isTeacher = () => _state.role?.toLowerCase() === 'teacher';

// ---- Setters ----
export function setAuth({ token, email, role, userId, name }) {
    _state.token = token || '';
    _state.email = email || _state.email;
    _state.role = role || '';
    _state.userId = userId || null;
    _state.name = name || '';
    localStorage.setItem(AUTH_KEY, _state.token);
    if (email) localStorage.setItem(EMAIL_KEY, email);
}

export function setUserProfile({ role, id, full_name }) {
    _state.role = String(role || '');
    _state.userId = Number(id || 0) || null;
    _state.name = String(full_name || '');
}

export function clearAuth() {
    _state.token = '';
    _state.role = '';
    _state.userId = null;
    _state.name = '';
    localStorage.removeItem(AUTH_KEY);
}
