/**
 * Promise-based confirm dialog — Tailwind v4
 */
export function askConfirm(message, { title = 'Confirm', confirmLabel = 'Confirm', danger = false } = {}) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal max-w-sm">
          <div class="px-6 py-5 border-b border-slate-100">
            <h2 class="text-[16px] font-bold text-slate-800">${title}</h2>
          </div>
          <div class="px-6 py-5">
            <p class="text-[14px] text-slate-600 leading-relaxed">${message}</p>
          </div>
          <div class="px-6 pb-5 flex gap-3 justify-end">
            <button id="modal-cancel"
              class="btn btn-ghost">Cancel</button>
            <button id="modal-confirm"
              class="btn ${danger ? 'btn-danger' : 'btn-primary'}">${confirmLabel}</button>
          </div>
        </div>`;
    document.body.appendChild(overlay);
    function cleanup(val) {
      overlay.remove();
      resolve(val);
    }
    overlay.querySelector('#modal-cancel').addEventListener('click', () => cleanup(false));
    overlay.querySelector('#modal-confirm').addEventListener('click', () => cleanup(true));
    overlay.addEventListener('click', e => { if (e.target === overlay) cleanup(false); });
    overlay.querySelector('#modal-confirm').focus();
  });
}
