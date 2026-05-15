/**
 * Hash Router — Teacher Progress App
 * Maps URL hash (#login, #class, #workflow, #calendar, #exams, #owner)
 * to view render functions.
 */

const _routes = {};
let _fallback = null;
let _current = null;

/**
 * Register a route.
 * @param {string} hash - e.g. 'login', 'class', 'workflow'
 * @param {() => void} handler - function that renders the view into #app-content
 */
export function route(hash, handler) {
    _routes[hash] = handler;
}

export function fallback(handler) {
    _fallback = handler;
}

export function navigate(hash) {
    window.location.hash = hash.startsWith('#') ? hash : `#${hash}`;
}

export function currentRoute() {
    return _current;
}

function dispatch() {
    const hash = window.location.hash.replace(/^#\/?/, '') || 'login';
    _current = hash;

    const handler = _routes[hash] || _fallback;
    if (handler) handler(hash);
}

export function initRouter() {
    window.addEventListener('hashchange', dispatch);
    dispatch();
}
