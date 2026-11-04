import './wireframe.css';
import './auth-wireframe.css';
import './app.css';
import { api, session, escapeHtml as e } from './api.js';

const root = document.querySelector('#auth-root');
let rememberedEmail = '';
const screens = ['signin', 'signup'];

function screenName() {
  const parts = location.hash.slice(1).split('/');
  const last = parts.at(-1);
  return screens.includes(last) ? last : 'signin';
}

function render() {
  const screen = screenName();
  const titles = { signin: 'Welcome back.', signup: 'Create your account.' };
  const actions = { signin: 'Sign in', signup: 'Create account' };
  root.innerHTML = `<a class="skip" href="#auth-main">Skip to account access</a><header class="app-header"><a class="logo" href="/">StockGraph<span>.</span></a><span class="brand-caption mono">A CLEARER VIEW OF THE MARKET</span><div class="header-actions"><a class="pill" href="/">Back to website ↗</a></div></header>
  <main id="auth-main"><div class="eyebrow">ACCOUNT ACCESS / STOCKGRAPH</div><div class="auth-heading"><h1>Your perspective.<br>Your workspace<span>.</span></h1><p>Research the connections behind Indian equities, with sources and context close at hand.</p></div>
  <div class="auth-grid"><section class="auth-form-panel"><nav class="auth-tabs" aria-label="Account action"><a href="#signin" ${screen === 'signin' ? 'aria-current="page"' : ''}>Sign in</a><a href="#signup" ${screen === 'signup' ? 'aria-current="page"' : ''}>Sign up</a></nav><span class="eyebrow">${e(screen.toUpperCase())} / ACCOUNT</span><h2>${titles[screen]}</h2>
  <form id="auth-form">${screen === 'signup' ? '<label><span>Full name</span><input name="name" required maxlength="200" autocomplete="name" placeholder="Your name"></label>' : ''}
  <label><span>Email address</span><input name="email" type="email" required maxlength="254" autocomplete="email" value="${e(rememberedEmail)}" placeholder="you@example.com"></label>
  <label><span>Password</span><input name="password" type="password" required ${screen === 'signin' ? '' : 'minlength="12"'} maxlength="1024" autocomplete="${screen === 'signin' ? 'current-password' : 'new-password'}" placeholder="${screen === 'signin' ? 'Your password' : 'At least 12 characters'}"></label>
  <button class="btn blue" type="submit">${actions[screen]} <span>↗</span></button><p id="auth-result" role="status" class="form-result">${screen === 'signin' ? e(sessionStorage.getItem('stockgraph.notice') || '') : ''}</p></form>
  ${screen === 'signup' ? '<a class="text-link" href="#signin">Already have an account? Sign in</a>' : ''}</section>
  <aside class="auth-context"><span class="eyebrow">YOUR RESEARCH WORKSPACE / 01</span><h2>Follow the context.<br>Find the connection<span>.</span></h2><p>Choose the stocks you follow, explore relationships, and keep the evidence in view.</p><div class="state-line"><strong>Built for your research.</strong><br>Your watchlists and active stock selection stay tied to your account.</div><div class="state-line"><strong>Evidence, with perspective.</strong><br>Explore sources, timing and context before drawing your own conclusions.</div></aside></div></main>`;
  const form = root.querySelector('#auth-form');
  const result = root.querySelector('#auth-result');
  if (screen === 'signin') sessionStorage.removeItem('stockgraph.notice');
  const email = form.elements.email;
  email.addEventListener('input', () => { rememberedEmail = email.value; });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    rememberedEmail = values.email;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    result.textContent = 'Please wait…';
    const paths = { signin: '/auth/login', signup: '/auth/signup' };
    try {
      const data = await api(paths[screen], { method: 'POST', body: values });
      if (screen === 'signin') {
        session.set(data.access_token);
        location.assign('/app/');
        return;
      }
      result.textContent = data.detail || 'Account ready. Sign in to continue.';
      if (screen === 'signup') { sessionStorage.setItem('stockgraph.notice', result.textContent); location.hash = '#signin'; }
    } catch (error) { result.textContent = error.message; }
    finally { button.disabled = false; }
  });
}
root.addEventListener('click', (event) => { if (event.target.closest('a.skip')) { event.preventDefault(); const main = root.querySelector('#auth-main'); main.tabIndex = -1; main.focus(); } });
addEventListener('hashchange', render);
render();
