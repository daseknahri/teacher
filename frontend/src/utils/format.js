/**
 * Formatting utilities — Teacher Progress App
 */

/** Format ISO date string to locale date */
export function fmtDate(iso) {
    if (!iso) return '—';
    try {
        return new Date(iso).toLocaleDateString('fr-MA', { year: 'numeric', month: 'short', day: 'numeric' });
    } catch { return iso; }
}

/** Format time string "HH:MM:SS" → "HH:MM" */
export function fmtTime(t) {
    if (!t) return '—';
    return String(t).slice(0, 5);
}

/** Format a percentage: 0.75 → "75%" or 75 → "75%" */
export function fmtPct(value, decimals = 0) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    const pct = n > 1 ? n : n * 100;
    return `${pct.toFixed(decimals)}%`;
}

/** Format a score safely */
export function fmtScore(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return '—';
    return n % 1 === 0 ? String(n) : n.toFixed(2);
}

/** Get initials from a full name (for avatar) */
export function initials(name) {
    if (!name) return '?';
    return name.trim().split(/\s+/).map(w => w[0]).join('').toUpperCase().slice(0, 2);
}

/** Format duration in minutes to "Xh Ym" */
export function fmtDuration(minutes) {
    const m = Number(minutes) || 0;
    const h = Math.floor(m / 60);
    const rem = m % 60;
    if (h === 0) return `${rem}min`;
    if (rem === 0) return `${h}h`;
    return `${h}h ${rem}min`;
}

/** Format hours-float to "Xh Ym" */
export function fmtHours(hours) {
    return fmtDuration((Number(hours) || 0) * 60);
}

/** clamp a value between min and max */
export function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}
