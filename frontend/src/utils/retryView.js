/**
 * retryView.js
 * Shared helper for rendering consistent API load failure cards with retry.
 */

export function renderRetryCard({
  title = 'Data Unavailable',
  message = 'Unable to load data right now. Retry after checking API connection.',
  buttonId = 'btn-retry-load',
  buttonLabel = 'Retry',
} = {}) {
  return `
    <div class="view-container">
      <div class="card p-6 flex flex-col gap-4" role="alert" aria-live="polite">
        <div>
          <h2 class="text-[17px] font-bold text-slate-800">${title}</h2>
          <p class="text-[13px] text-slate-500 mt-1">${message}</p>
        </div>
        <div>
          <button id="${buttonId}" class="btn btn-primary" aria-label="${buttonLabel}">${buttonLabel}</button>
        </div>
      </div>
    </div>`;
}

export function mountRetryCard(container, options = {}) {
  if (!container) return;
  const {
    buttonId = 'btn-retry-load',
    onRetry = null,
  } = options;
  container.innerHTML = renderRetryCard(options);
  if (typeof onRetry === 'function') {
    container.querySelector(`#${buttonId}`)?.addEventListener('click', onRetry);
  }
}
