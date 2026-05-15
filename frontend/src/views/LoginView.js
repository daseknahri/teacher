/**
 * LoginView.js  Authentication screen
 * Teacher Progress App  Tailwind v4
 */
import { api } from '../api/client.js';
import { setAuth, setUserProfile } from '../state/auth.js';
import { setClasses } from '../state/class.js';
import { showToast } from '../utils/toast.js';
import { navigate } from '../router.js';
import { generateStrongPassword } from '../utils/password.js';
import { refreshShell } from '../components/AppShell.js';

export function renderLoginView() {
  /*  Hide app chrome  */
  _hideChrome();

  const el = document.getElementById('app-content');
  el.innerHTML = `
    <div class="auth-screen">
      <!-- Decorative blobs -->
      <div class="absolute inset-0 overflow-hidden pointer-events-none">
        <div class="absolute -top-40 -right-32 w-[500px] h-[500px] rounded-full
                    bg-blue-500/10 blur-3xl"></div>
        <div class="absolute -bottom-40 -left-32 w-[500px] h-[500px] rounded-full
                    bg-indigo-500/10 blur-3xl"></div>
      </div>

      <!-- Card -->
      <div class="relative w-full max-w-sm">
        <!-- Logotype -->
        <div class="text-center mb-8">
          <div class="inline-flex items-center justify-center w-16 h-16 rounded-2xl
                      bg-white/10 backdrop-blur text-4xl mb-4 border border-white/20
                      shadow-xl text-[16px] font-black tracking-tight text-white">TP</div>
          <h1 class="text-2xl font-bold text-white tracking-tight">Teacher Progress</h1>
          <p class="text-blue-200/70 text-sm mt-1">Sign in to your account</p>
        </div>

        <!-- Login form card -->
        <div class="bg-white/10 backdrop-blur-xl rounded-3xl border border-white/20
                    shadow-2xl p-7">
          <!-- Error banner -->
          <div id="auth-error"
               role="alert"
               aria-live="assertive"
               class="hidden mb-4 px-4 py-3 bg-red-500/20 border border-red-400/40
                      rounded-xl text-red-200 text-[13px] font-medium flex items-center gap-2">
            <span>Error:</span><span id="auth-error-text"></span>
          </div>

          <!-- Fields -->
          <div class="flex flex-col gap-4">
            <div class="flex flex-col gap-1.5">
              <label class="text-[12px] font-semibold text-blue-100/80 uppercase
                            tracking-wide">Email address</label>
              <input id="auth-email" type="email" placeholder="teacher@school.edu"
                class="!bg-white/10 !border-white/20 !text-white placeholder:!text-white/40
                       focus:!border-blue-400 focus:!bg-white/15" autocomplete="username" />
            </div>
            <div class="flex flex-col gap-1.5">
              <label class="text-[12px] font-semibold text-blue-100/80 uppercase
                            tracking-wide">Password</label>
              <input id="auth-password" type="password" placeholder="Password"
                class="!bg-white/10 !border-white/20 !text-white placeholder:!text-white/40
                       focus:!border-blue-400 focus:!bg-white/15" autocomplete="current-password" />
            </div>
          </div>

          <button id="auth-submit"
            class="btn btn-primary btn-xl mt-5 !bg-blue-500 hover:!bg-blue-400
                   !font-bold !text-base shadow-xl shadow-blue-900/30
                   transition-all duration-200 active:scale-[0.98]">
            Sign in
          </button>
        </div>

        <!-- First-time setup -->
        <details class="mt-5 bg-white/5 border border-white/10 rounded-2xl overflow-hidden">
          <summary class="px-5 py-3 text-[13px] font-medium text-blue-200/60
                          cursor-pointer list-none flex items-center justify-between
                          hover:text-blue-200 transition-colors">
            <span>First time setup - Create owner account</span>
            <span class="text-xs opacity-50" aria-hidden="true">v</span>
          </summary>
          <div class="px-5 pb-5 pt-2 flex flex-col gap-3">
            <p class="text-[12px] text-blue-200/50">
              Run once to bootstrap the system with an owner account.
            </p>
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-semibold text-blue-200/60 uppercase tracking-wide">
                Owner email
              </label>
              <input id="boot-email" type="email" placeholder="owner@school.edu"
                class="!bg-white/10 !border-white/20 !text-white placeholder:!text-white/40" />
            </div>
            <div class="flex flex-col gap-1.5">
              <label class="text-[11px] font-semibold text-blue-200/60 uppercase tracking-wide">
                Password
              </label>
              <div class="flex gap-2">
                <input id="boot-password" type="text" placeholder="Strong password"
                  class="!bg-white/10 !border-white/20 !text-white placeholder:!text-white/40 flex-1" />
                <button id="boot-gen"
                  class="btn btn-ghost btn-sm !text-blue-300 !border-white/20 !border
                         hover:!bg-white/10 whitespace-nowrap flex-shrink-0">
                  Generate
                </button>
              </div>
            </div>
            <button id="boot-submit"
              class="btn !bg-white/15 !text-white hover:!bg-white/25 !border
                     !border-white/20 !font-semibold w-full mt-1">
              Bootstrap Owner
            </button>
          </div>
        </details>
      </div>
    </div>
    `;

  /*  Event binding  */
  const emailEl = document.getElementById('auth-email');
  const pwdEl = document.getElementById('auth-password');
  const submitBtn = document.getElementById('auth-submit');
  const errorEl = document.getElementById('auth-error');
  const errorText = document.getElementById('auth-error-text');

  let _lockoutTimer = null;

  function showError(msg) {
    errorText.textContent = msg;
    errorEl.classList.remove('hidden');
    errorEl.classList.add('flex');
  }
  function clearError() {
    errorEl.classList.add('hidden');
    errorEl.classList.remove('flex');
  }

  function startLockoutCountdown(seconds) {
    if (_lockoutTimer) clearInterval(_lockoutTimer);
    submitBtn.disabled = true;
    let remaining = Math.max(1, Math.ceil(seconds));
    function tick() {
      submitBtn.textContent = `Locked - retry in ${remaining}s`;
      if (remaining <= 0) {
        clearInterval(_lockoutTimer);
        _lockoutTimer = null;
        submitBtn.disabled = false;
        submitBtn.textContent = 'Sign in';
        clearError();
        return;
      }
      remaining--;
    }
    tick();
    _lockoutTimer = setInterval(tick, 1000);
  }

  async function doLogin() {
    clearError();
    if (_lockoutTimer) return; // still locked out
    const email = emailEl.value.trim();
    const pwd = pwdEl.value;
    if (!email || !pwd) { showError('Please fill in both fields.'); return; }
    submitBtn.disabled = true;
    submitBtn.textContent = 'Signing in...';
    try {
      // Backend uses POST /auth/login with JSON body (not OAuth2 form)
      const data = await api('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: pwd }),
      });
      setAuth({ token: data.access_token, email });
      const me = await api('/auth/me');
      setUserProfile(me);
      refreshShell();
      const classes = await api('/classes');
      setClasses(classes || []);
      navigate('class');
    } catch (err) {
      // HTTP 423 = account locked
      if (err.status === 423 || String(err.message).toLowerCase().includes('lock')) {
        const retryAfter = Number(err.retry_after || err.details?.retry_after || 30);
        showError(`Account locked. Too many failed attempts.`);
        startLockoutCountdown(retryAfter);
      } else {
        showError(err.message || 'Login failed.');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Sign in';
      }
    }
  }

  submitBtn.addEventListener('click', doLogin);
  pwdEl.addEventListener('keydown', e => e.key === 'Enter' && doLogin());
  emailEl.addEventListener('keydown', e => e.key === 'Enter' && pwdEl.focus());

  /* Bootstrap owner */
  document.getElementById('boot-gen').addEventListener('click', () => {
    document.getElementById('boot-password').value = generateStrongPassword();
  });
  document.getElementById('boot-submit').addEventListener('click', async () => {
    const email = document.getElementById('boot-email').value.trim();
    const pwd = document.getElementById('boot-password').value.trim();
    if (!email || !pwd) { showError('Fill owner email and password.'); return; }
    try {
      // Backend: POST /auth/bootstrap-owner with {email, full_name, password}
      await api('/auth/bootstrap-owner', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, full_name: 'School Owner', password: pwd }),
      });
      showToast('Owner account created! You can now sign in.', 'ok');
      document.getElementById('auth-email').value = email;
    } catch (err) {
      showError(err.message || 'Bootstrap failed.');
    }
  });
}

function _hideChrome() {
  const topbar = document.getElementById('topbar');
  const sidebar = document.getElementById('sidebar');
  const btabs = document.getElementById('bottom-tabs');
  const main = document.getElementById('app-main');
  const app = document.getElementById('app');
  if (topbar) topbar.style.display = 'none';
  if (sidebar) sidebar.style.display = 'none';
  if (btabs) btabs.style.display = 'none';
  if (main) {
    main.style.cssText = 'padding:0;margin:0;min-height:100dvh;';
  }
  if (app) {
    app.style.cssText = 'display:block;min-height:100dvh;';
  }
}

