/**
 * API Client — Teacher Progress App
 * Mirrors the existing api() function from index.html with identical contract.
 * All requests go to the backend; in dev Vite proxies /api → localhost:8000.
 */

import { getToken, clearAuth } from '../state/auth.js';

const BASE = import.meta.env.DEV ? '/api' : '';

/**
 * Core fetch wrapper.
 * @param {string} path  - Backend path (e.g. "/classes" → GET /api/classes)
 * @param {RequestInit} options - Standard fetch options
 * @returns {Promise<any>} Parsed JSON response body
 */
export async function api(path, options = {}) {
    const token = getToken();
    const headers = { ...(options.headers || {}) };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(`${BASE}${path}`, { ...options, headers });

    if (response.status === 401) {
        // Token expired or invalid — clear auth and redirect to login
        clearAuth();
        window.location.hash = '#login';
        throw new Error('Session expired. Please log in again.');
    }

    if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        let body = null;
        try {
            body = await response.json();
            detail = body?.detail || body?.message || JSON.stringify(body);
        } catch { }
        const err = new Error(detail);
        err.status = response.status;
        err.body = body;
        if (body && typeof body === 'object') {
            if (body.retry_after != null) err.retry_after = Number(body.retry_after);
            if (body.details && typeof body.details === 'object' && body.details.retry_after != null) {
                err.retry_after = Number(body.details.retry_after);
            }
        }
        throw err;
    }

    if (response.status === 204) return null;
    return response.json();
}

/**
 * Download a file that requires authentication.
 * Creates a temporary object URL and triggers a browser download.
 */
export async function downloadWithAuth(path, filename) {
    const token = getToken();
    const response = await fetch(`${BASE}${path}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new Error(`Download failed: HTTP ${response.status}`);
    const blob = await response.blob();
    const contentType = String(response.headers.get('content-type') || '').toLowerCase();
    const disposition = String(response.headers.get('content-disposition') || '');
    const quotedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i) || disposition.match(/filename=\"?([^\";]+)\"?/i);
    let targetName = filename || 'download';
    if (quotedMatch && quotedMatch[1]) {
        try {
            targetName = decodeURIComponent(String(quotedMatch[1]).trim());
        } catch {
            targetName = String(quotedMatch[1]).trim();
        }
    }
    if (contentType.includes('application/pdf') && !String(targetName).toLowerCase().endsWith('.pdf')) {
        targetName = String(targetName).replace(/\.[^.]+$/, '') || 'download';
        targetName = `${targetName}.pdf`;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = targetName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
