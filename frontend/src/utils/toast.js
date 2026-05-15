/**
 * Toast notification system — Tailwind v4
 */
let _container = null;

function _getContainer() {
    if (!_container) {
        _container = document.createElement('div');
        _container.id = 'toast-container';
        _container.className = 'fixed bottom-20 right-4 flex flex-col-reverse gap-2 z-[9999] pointer-events-none md:bottom-6';
        document.body.appendChild(_container);
    }
    return _container;
}

const ICONS = { ok: '✓', error: '✕', warning: '⚠', info: 'ℹ' };

/**
 * @param {string} message
 * @param {'ok'|'error'|'warning'|'info'} type
 * @param {number} duration ms
 */
export function showToast(message, type = 'info', duration = 3500) {
    const container = _getContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type} pointer-events-auto`;
    toast.innerHTML = `
      <span class="text-[18px] flex-shrink-0">${ICONS[type] || 'ℹ'}</span>
      <span class="flex-1">${message}</span>
    `;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(12px)';
        toast.style.transition = 'opacity 0.2s, transform 0.2s';
        setTimeout(() => toast.remove(), 220);
    }, duration);
}
