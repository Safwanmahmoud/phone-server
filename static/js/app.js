// Phone Server dashboard. Plain ES module, no build step.

// ---------- icons (trusted constant markup) ----------

const ICONS = {
  phone: '<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/>',
  overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  apps: '<path d="m12 3 9 5-9 5-9-5 9-5Z"/><path d="m3 13 9 5 9-5"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3"/><path d="M13 15h4"/>',
  settings: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  play: '<path d="M7 5v14l11-7L7 5Z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  restart: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  deploy: '<path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 15v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a1 1 0 0 1 1-1h9"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3M14 9l2 2"/>',
  branch: '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="7" r="2"/><path d="M6 7v10M18 9c0 5-6 4-11 8.5"/>',
  logout: '<path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="M10 17l-5-5 5-5"/><path d="M5 12h11"/>',
};

function icon(name, size = 18) {
  return h('span', {
    class: 'icon', 'aria-hidden': 'true',
    html: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ''}</svg>`,
  });
}

// ---------- DOM helpers ----------

const $ = (sel, root = document) => root.querySelector(sel);
const enc = encodeURIComponent;

// Builds elements with text nodes, never innerHTML, so data from the phone can't inject markup.
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v; // only used by icon()
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'value') el.value = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

let fieldSeq = 0;
function field(label, control, hint) {
  if (!control.id) control.id = `f${++fieldSeq}`;
  let hintEl = null;
  if (hint) {
    hintEl = h('span', { class: 'hint', id: `${control.id}-hint` }, hint);
    control.setAttribute('aria-describedby', hintEl.id);
  }
  return h('div', { class: 'field' }, h('label', { class: 'label', for: control.id }, label), control, hintEl);
}
const input = (attrs = {}) => h('input', { type: 'text', autocomplete: 'off', ...attrs });
const textarea = (value, attrs = {}) => h('textarea', { ...attrs, value });

function toast(message, tone = 'ok') {
  const el = h('div', { class: `toast toast-${tone}`, role: tone === 'bad' ? 'alert' : 'status' }, message);
  $('#toasts').append(el);
  setTimeout(() => { el.classList.add('leaving'); setTimeout(() => el.remove(), 260); }, tone === 'bad' ? 6500 : 3200);
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* fall through */ }
  // Plain http (Tailscale addresses) has no clipboard API; the old way still works.
  const ta = h('textarea', { style: 'position:fixed;top:0;left:0;opacity:0', readonly: true, value: text });
  document.body.append(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch { /* ignore */ }
  ta.remove();
  return ok;
}
function copyBtn(text, label = 'Copy') {
  return h('button', {
    type: 'button', class: 'btn btn-sm',
    onclick: async () => {
      const ok = await copyText(text);
      toast(ok ? 'Copied.' : 'Couldn’t copy. Select the text and copy it yourself.', ok ? 'ok' : 'bad');
    },
  }, icon('copy', 15), label);
}
const codeLine = (text) => h('div', { class: 'code-line' }, h('code', {}, text), copyBtn(text));

// ---------- formatting ----------

function fmtBytes(n) {
  if (n == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n < 10 && i ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
}
function fmtDuration(sec) {
  if (sec == null || !isFinite(sec)) return '—';
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), hr = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  if (d) return `${d}d ${hr}h`;
  if (hr) return `${hr}h ${m}m`;
  if (m) return `${m}m`;
  return `${sec}s`;
}
function fmtAgo(ts) {
  if (!ts) return '—';
  const s = Date.now() / 1000 - ts;
  return s < 10 ? 'just now' : `${fmtDuration(s)} ago`;
}
const pct = (f) => `${Math.round(f * 100)}%`;
const now = () => Date.now() / 1000;
function repoLabel(url) {
  const m = String(url).match(/[:/]([^/:]+\/[^/]+?)(?:\.git)?\/?$/);
  return m ? m[1] : url;
}
function repoWebUrl(url) {
  let m = String(url).match(/^git@([\w.-]+):(.+?)(?:\.git)?$/);
  if (m) return `https://${m[1]}/${m[2]}`;
  m = String(url).match(/^https?:\/\/(?:[^@/]+@)?(.+?)(?:\.git)?\/?$/);
  return m ? `https://${m[1]}` : null;
}
function slugFromRepo(url) {
  const m = url.trim().match(/([^/:]+?)(?:\.git)?\/?$/);
  if (!m) return '';
  return m[1].toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^[^a-z]+/, '').replace(/-+$/, '').slice(0, 32);
}

// ---------- status ----------

const PROCESS_STATUS = {
  online: ['ok', 'Running'],
  launching: ['warn', 'Starting'],
  'waiting restart': ['warn', 'Restarting'],
  stopping: ['warn', 'Stopping'],
  stopped: ['muted', 'Stopped'],
  errored: ['bad', 'Crashed'],
};
const DEPLOY_STATUS = {
  queued: ['info', 'Queued'],
  running: ['info', 'Deploying'],
  success: ['ok', 'Deployed'],
  failed: ['bad', 'Failed'],
};
function appStatus(app) {
  if (app.active_deploy) return ['info', 'Deploying'];
  const s = app.process?.status;
  if (s) return PROCESS_STATUS[s] || ['muted', s];
  if (app.last_deploy?.status === 'failed') return ['bad', 'Deploy failed'];
  return ['muted', 'Not running'];
}
const processStatus = (p) => (p ? PROCESS_STATUS[p.status] || ['muted', p.status] : ['bad', 'Missing']);
const badge = ([tone, label]) => h('span', { class: `badge badge-${tone}` }, h('span', { class: 'dot' }), label);
const stat = (label, value) => h('div', { class: 'stat' }, h('span', { class: 'stat-label' }, label), h('span', { class: 'stat-value' }, value));
const isUp = (p) => p?.status === 'online';

// ---------- API ----------

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(path, { method = 'GET', body } = {}) {
  const opts = { method, credentials: 'same-origin', headers: { 'X-Requested-With': 'phone-server' } };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try { res = await fetch(path, opts); } catch {
    throw new ApiError('Can’t reach the phone. Check that it’s on and connected to Tailscale.', 0);
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    showLogin({ configured: true, error: 'Your session ended. Sign in again.' });
    throw new ApiError('Signed out', 401);
  }
  if (!res.ok) throw new ApiError(data?.error || `Request failed (${res.status})`, res.status);
  return data;
}

// Runs fn now and then every `ms` while the tab is visible. Returns a stop function.
function poll(fn, ms) {
  let timer = null, stopped = false, busy = false;
  const tick = async () => {
    if (stopped) return;
    if (!document.hidden && !busy) {
      busy = true;
      try { await fn(); } catch (e) { if (e.status !== 401) console.warn(e); } finally { busy = false; }
    }
    if (!stopped) timer = setTimeout(tick, ms);
  };
  tick();
  return () => { stopped = true; clearTimeout(timer); };
}

// ---------- theme ----------

const THEME_KEY = 'psTheme';
function storedTheme() { try { return localStorage.getItem(THEME_KEY) || 'dark'; } catch { return 'dark'; } }
function applyTheme(choice = storedTheme()) {
  const dark = choice === 'system' ? matchMedia('(prefers-color-scheme: dark)').matches : choice !== 'light';
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  const btn = $('#theme-toggle');
  if (btn) {
    btn.replaceChildren(icon(dark ? 'sun' : 'moon'));
    btn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    btn.title = btn.getAttribute('aria-label');
  }
}
function setTheme(choice) {
  try { localStorage.setItem(THEME_KEY, choice); } catch { /* private mode */ }
  applyTheme(choice);
}
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => storedTheme() === 'system' && applyTheme());

// ---------- routing ----------

let cleanup = null;
function stopRoute() { if (cleanup) { cleanup(); cleanup = null; } }

function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  if (parts[0] === 'apps' && parts[1]) return { view: 'app', name: parts[1], tab: parts[2] || 'logs', dep: parts[3] };
  return { view: VIEWS[parts[0]] ? parts[0] : 'overview' };
}

function render() {
  if ($('#shell').hidden) return;
  stopRoute();
  const route = parseRoute();
  const main = $('#view');
  main.replaceChildren();
  main.hidden = false;
  $('#terminal-host').hidden = true;
  const section = route.view === 'app' ? 'apps' : route.view;
  document.querySelectorAll('.nav-link[data-route]').forEach((a) => {
    const active = a.dataset.route === section;
    a.classList.toggle('active', active);
    if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  });
  cleanup = VIEWS[route.view](main, route) || null;
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', render);

function pageHead(title, sub, ...actions) {
  return h('header', { class: 'page-head' },
    h('div', { class: 'page-title' }, h('h1', {}, title), sub ? h('p', { class: 'page-sub' }, sub) : null),
    actions.length ? h('div', { class: 'actions' }, actions) : null);
}

// ---------- overview ----------

function tile(label, value, { sub, meter, tone, extra, title } = {}) {
  return h('section', { class: 'tile', title },
    h('div', { class: 'tile-label' }, label),
    value != null ? h('div', { class: `tile-value ${tone ? `tone-${tone}` : ''}` }, value) : null,
    sub ? h('div', { class: 'tile-sub' }, sub) : null,
    meter != null ? meterEl(meter, tone) : null,
    extra);
}
function meterEl(frac, tone) {
  const p = Math.max(0, Math.min(1, frac || 0)) * 100;
  return h('div', { class: `meter ${tone ? `tone-${tone}` : ''}`, role: 'meter', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': Math.round(p) },
    h('span', { style: `width:${p}%` }));
}
const level = (v, warn, bad) => (v == null ? null : v >= bad ? 'bad' : v >= warn ? 'warn' : null);

function memoryTile(m) {
  const f = m.total ? m.used / m.total : 0;
  return tile('Memory', pct(f), { sub: `${fmtBytes(m.used)} of ${fmtBytes(m.total)} in use`, meter: f, tone: level(f, 0.85, 0.93) });
}
function storageTile(s) {
  const f = s.total ? s.used / s.total : 0;
  return tile('Storage', pct(f), { sub: `${fmtBytes(s.free)} free of ${fmtBytes(s.total)}`, meter: f, tone: level(f, 0.85, 0.95) });
}
function cpuTile(c) {
  const cores = c.cores || [];
  const avg = cores.length ? cores.reduce((sum, x) => sum + x.cur_mhz / x.max_mhz, 0) / cores.length : null;
  const bars = h('div', { class: 'cores', 'aria-hidden': 'true' },
    cores.map((x) => h('span', { class: 'core' }, h('span', { style: `height:${Math.max(4, (x.cur_mhz / x.max_mhz) * 100)}%` }))));
  const detail = cores.map((x, i) => `Core ${i}: ${x.cur_mhz} of ${x.max_mhz} MHz`).join('\n');
  return tile('CPU clock', avg == null ? '—' : pct(avg), {
    sub: `${c.count} cores, speed vs. max`, extra: bars,
    title: `${detail}\n\nAndroid doesn't let apps read overall CPU load, so this shows how fast each core is running.`,
  });
}
function tempTile(t) {
  const item = (label, v, warn, bad) => h('div', { class: 'mini' },
    h('span', { class: 'mini-label' }, label),
    h('span', { class: `mini-value ${level(v, warn, bad) ? `tone-${level(v, warn, bad)}` : ''}` }, v == null ? '—' : `${Math.round(v)}°`));
  return tile('Temperature', null, {
    extra: h('div', { class: 'minis' }, item('CPU', t.cpu, 65, 80), item('Battery', t.battery, 40, 45), item('Body', t.skin, 40, 45)),
  });
}
function batteryTile(b) {
  if (!b?.available) {
    return tile('Battery', '—', {
      sub: b?.reason === 'package'
        ? 'Run pkg install termux-api and install the Termux:API app to show the level.'
        : 'Install the Termux:API app to show the level.',
    });
  }
  const f = (b.percent ?? 0) / 100;
  const state = b.status === 'FULL' ? 'Full' : b.status === 'CHARGING' ? 'Charging' : 'On battery';
  return tile('Battery', pct(f), { sub: state, meter: f, tone: f < 0.1 ? 'bad' : f < 0.2 ? 'warn' : null });
}
function appsTile(a) {
  return tile('Apps', `${a.running} / ${a.total}`, { sub: a.total ? `running · ${fmtBytes(a.memory)} memory` : 'none deployed yet' });
}

function appRow(app) {
  const p = app.process;
  return h('a', { class: 'row row-link', href: `#/apps/${enc(app.name)}` },
    h('div', { class: 'row-main' },
      h('div', { class: 'row-title' }, app.name),
      h('div', { class: 'row-meta' }, h('span', { class: 'truncate' }, repoLabel(app.repo_url)), h('span', { class: 'sep' }, '·'), app.branch, h('span', { class: 'sep' }, '·'), `port ${app.port}`)),
    h('div', { class: 'row-stats' },
      stat('CPU', isUp(p) ? `${p.cpu}%` : '—'),
      stat('Memory', isUp(p) ? fmtBytes(p.memory) : '—'),
      stat('Uptime', isUp(p) && p.started_at ? fmtDuration(now() - p.started_at) : '—')),
    badge(appStatus(app)));
}
function serviceRow(s) {
  const p = s.process;
  return h('div', { class: 'row' },
    h('div', { class: 'row-main' }, h('div', { class: 'row-title' }, s.label), h('div', { class: 'row-meta mono' }, s.name)),
    h('div', { class: 'row-stats' },
      stat('Memory', isUp(p) ? fmtBytes(p.memory) : '—'),
      stat('Uptime', isUp(p) && p.started_at ? fmtDuration(now() - p.started_at) : '—')),
    badge(processStatus(p)));
}
const pm2Banner = (err) => (err ? h('div', { class: 'banner banner-bad', role: 'alert' }, `PM2 isn’t answering, so app status is unknown. ${err}`) : null);

function viewOverview(main) {
  const sub = h('p', { class: 'page-sub' }, 'Loading…');
  const banner = h('div');
  const tiles = h('div', { class: 'tiles' });
  const appsBox = h('div', { class: 'card rows' });
  const servicesBox = h('div', { class: 'card rows' });
  main.append(
    h('header', { class: 'page-head' }, h('div', { class: 'page-title' }, h('h1', {}, 'Overview'), sub)),
    banner, tiles,
    h('div', { class: 'section-head' }, h('h2', {}, 'Apps'), h('a', { class: 'link', href: '#/apps' }, 'Manage apps')),
    appsBox,
    h('div', { class: 'section-head' }, h('h2', {}, 'Dashboard services')),
    servicesBox,
  );
  return poll(async () => {
    const [sys, data] = await Promise.all([api('/api/system'), api('/api/apps')]);
    const d = sys.device;
    sub.textContent = [d.name, d.android && `Android ${d.android}`, `dashboard up ${fmtDuration(sys.now - sys.dashboard_started_at)}`].filter(Boolean).join(' · ');
    banner.replaceChildren(pm2Banner(data.pm2_error) || '');
    tiles.replaceChildren(memoryTile(sys.memory), storageTile(sys.storage), cpuTile(sys.cpu), tempTile(sys.temperature), batteryTile(sys.battery), appsTile(sys.apps));
    appsBox.replaceChildren(...(data.apps.length
      ? data.apps.map(appRow)
      : [h('div', { class: 'empty-row' }, 'No apps yet. ', h('a', { class: 'link', href: '#/apps' }, 'Deploy your first one'))]));
    servicesBox.replaceChildren(...data.services.map(serviceRow));
  }, 5000);
}

// ---------- apps ----------

function viewApps(main) {
  const banner = h('div');
  const list = h('div');
  main.append(pageHead('Apps', 'Python and Node.js apps deployed from Git and kept running by PM2.',
    h('button', { class: 'btn btn-primary', onclick: openNewApp }, icon('plus'), 'New app')), banner, list);
  return poll(async () => {
    const data = await api('/api/apps');
    banner.replaceChildren(pm2Banner(data.pm2_error) || '');
    if (!data.apps.length) {
      list.replaceChildren(h('div', { class: 'card empty' },
        h('h2', {}, 'No apps yet'),
        h('p', { class: 'muted' }, 'Point the phone at a Git repository. It clones it, installs requirements.txt or package.json, builds it if needed, and keeps the app running.'),
        h('button', { class: 'btn btn-primary', onclick: openNewApp }, icon('plus'), 'New app')));
    } else {
      list.replaceChildren(h('div', { class: 'card rows' }, data.apps.map(appRow)));
    }
  }, 4000);
}

function openNewApp() {
  const dlg = $('#dialog');
  const repo = input({ class: 'mono', required: true, placeholder: 'git@github.com:you/project.git', spellcheck: 'false', autocapitalize: 'off' });
  const name = input({ required: true, placeholder: 'my-api', maxlength: 32, spellcheck: 'false', autocapitalize: 'off' });
  const branch = input({ placeholder: 'Default branch', spellcheck: 'false', autocapitalize: 'off' });
  const cmd = input({ class: 'mono', placeholder: 'Detected automatically', spellcheck: 'false', autocapitalize: 'off' });
  const env = textarea('', { class: 'mono', rows: 4, placeholder: 'DATABASE_URL=postgres://…\nDEBUG=false', spellcheck: 'false' });
  let nameTouched = false;
  name.addEventListener('input', () => { nameTouched = true; });
  repo.addEventListener('input', () => { if (!nameTouched) name.value = slugFromRepo(repo.value); });

  const err = h('p', { class: 'form-error', role: 'alert' });
  const submit = h('button', { class: 'btn btn-primary', type: 'submit' }, 'Create and deploy');
  const form = h('form', {
    class: 'form',
    onsubmit: async (e) => {
      e.preventDefault();
      err.textContent = '';
      submit.disabled = true;
      submit.textContent = 'Checking the repository…';
      try {
        const r = await api('/api/apps', {
          method: 'POST',
          body: { name: name.value.trim(), repo_url: repo.value.trim(), branch: branch.value.trim(), start_cmd: cmd.value.trim(), env_text: env.value },
        });
        dlg.close();
        toast(`Deploying ${r.app.name}…`);
        location.hash = `#/apps/${enc(r.app.name)}/deployments/${r.deployment.id}`;
      } catch (ex) {
        err.textContent = ex.message;
      } finally {
        submit.disabled = false;
        submit.textContent = 'Create and deploy';
      }
    },
  },
    h('div', { class: 'dialog-head' }, h('h2', {}, 'New app'),
      h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Close', onclick: () => dlg.close() }, icon('close'))),
    field('Repository', repo, h('span', {}, 'Private repositories need the phone’s key on GitHub. ',
      h('a', { class: 'link', href: '#/settings', onclick: () => dlg.close() }, 'Set it up'))),
    field('Name', name, 'Lowercase letters, numbers and dashes.'),
    h('div', { class: 'grid-2' },
      field('Branch', branch, 'Optional.'),
      field('Start command', cmd, 'Optional. $PORT is set for you.')),
    field('Environment variables', env, 'Optional. One KEY=value per line.'),
    err,
    h('div', { class: 'form-actions' },
      h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'Cancel'), submit));
  dlg.replaceChildren(form);
  dlg.showModal();
  repo.focus();
}

// ---------- one app ----------

const TABS = { logs: 'Logs', deployments: 'Deployments', settings: 'Settings' };

function viewApp(main, route) {
  const { name, dep } = route;
  const tab = TABS[route.tab] ? route.tab : 'logs';
  const head = h('div');
  const body = h('div');
  let app = null, busy = false, stopped = false;

  const act = async (action) => {
    busy = true; draw();
    try {
      const r = await api(`/api/apps/${enc(name)}/action`, { method: 'POST', body: { action } });
      toast(r.message);
    } catch (e) { toast(e.message, 'bad'); }
    busy = false;
    await load();
  };
  const redeploy = async () => {
    busy = true; draw();
    try {
      const r = await api(`/api/apps/${enc(name)}/deploy`, { method: 'POST' });
      location.hash = `#/apps/${enc(name)}/deployments/${r.deployment.id}`;
    } catch (e) { toast(e.message, 'bad'); busy = false; draw(); }
  };

  function draw() {
    if (!app) return;
    const p = app.process;
    const up = isUp(p);
    const deploying = app.active_deploy;
    const url = `${location.protocol}//${location.hostname}:${app.port}/`;
    const last = app.last_deploy;
    const web = repoWebUrl(app.repo_url);
    const disabled = busy || deploying;
    head.replaceChildren(
      h('header', { class: 'page-head' },
        h('div', { class: 'page-title' },
          h('div', { class: 'title-row' }, h('h1', {}, app.name), badge(appStatus(app))),
          h('p', { class: 'page-sub' },
            web ? h('a', { class: 'link', href: web, target: '_blank', rel: 'noopener' }, repoLabel(app.repo_url)) : repoLabel(app.repo_url),
            h('span', { class: 'sep' }, '·'), icon('branch', 15), app.branch,
            last?.commit_sha ? [h('span', { class: 'sep' }, '·'), h('span', { class: 'mono' }, last.commit_sha.slice(0, 7)),
              h('span', { class: 'truncate' }, last.commit_msg || '')] : null)),
        h('div', { class: 'actions' },
          h('a', { class: `btn ${up ? '' : 'disabled'}`, href: url, target: '_blank', rel: 'noopener', 'aria-disabled': up ? null : 'true' }, icon('external', 16), 'Open'),
          up || p?.status === 'launching'
            ? h('button', { class: 'btn', disabled, onclick: () => act('stop') }, icon('stop', 16), 'Stop')
            : h('button', { class: 'btn', disabled, onclick: () => act('start') }, icon('play', 16), 'Start'),
          h('button', { class: 'btn', disabled, onclick: () => act('restart') }, icon('restart', 16), 'Restart'),
          h('button', { class: 'btn btn-primary', disabled, onclick: redeploy }, icon('deploy', 16), deploying ? 'Deploying…' : 'Redeploy'))),
      pm2Banner(app.pm2_error) || '',
      h('div', { class: 'stat-strip' },
        stat('Port', h('a', { class: 'link mono', href: url, target: '_blank', rel: 'noopener' }, app.port)),
        stat('CPU', up ? `${p.cpu}%` : '—'),
        stat('Memory', up ? fmtBytes(p.memory) : '—'),
        stat('Uptime', up && p.started_at ? fmtDuration(now() - p.started_at) : '—'),
        stat('Restarts', p ? p.restarts : '—'),
        stat('Last deploy', last ? fmtAgo(last.created_at) : '—')));
  }

  async function load() {
    try {
      app = await api(`/api/apps/${enc(name)}`);
      draw();
    } catch (e) {
      if (e.status === 404 && !stopped) {
        stopAll();
        main.replaceChildren(h('div', { class: 'card empty' }, h('h1', {}, 'App not found'),
          h('p', { class: 'muted' }, `There’s no app called ${name}.`),
          h('a', { class: 'btn', href: '#/apps' }, 'Back to apps')));
      } else throw e;
    }
  }

  main.append(
    h('a', { class: 'back', href: '#/apps' }, icon('back', 16), 'Apps'),
    head,
    h('nav', { class: 'tabs', 'aria-label': 'App sections' }, Object.entries(TABS).map(([key, label]) =>
      h('a', { class: `tab ${key === tab ? 'active' : ''}`, href: `#/apps/${enc(name)}/${key}`, 'aria-current': key === tab ? 'page' : null }, label))),
    body);

  const stopHead = poll(load, 4000);
  const stopTab = { logs: logsTab, deployments: deploymentsTab, settings: settingsTab }[tab](body, name, dep);
  function stopAll() { stopped = true; stopHead(); stopTab?.(); }
  return stopAll;
}

function logsTab(body, name) {
  const pre = h('pre', { class: 'log', tabindex: '0', 'data-empty': 'No output yet. Anything the app prints shows up here.' });
  const followBox = h('input', { type: 'checkbox', checked: true });
  let follow = true, offset = null;
  followBox.addEventListener('change', () => { follow = followBox.checked; if (follow) pre.scrollTop = pre.scrollHeight; });
  pre.addEventListener('scroll', () => {
    follow = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 24;
    followBox.checked = follow;
  });
  const clear = async () => {
    if (!confirm('Clear this app’s log file?')) return;
    try { await api(`/api/apps/${enc(name)}/logs`, { method: 'DELETE' }); pre.textContent = ''; offset = 0; toast('Logs cleared.'); }
    catch (e) { toast(e.message, 'bad'); }
  };
  body.append(
    h('div', { class: 'toolbar' },
      h('label', { class: 'check' }, followBox, 'Follow new output'),
      h('span', { class: 'spacer' }),
      h('button', { class: 'btn btn-ghost btn-sm', onclick: clear }, icon('trash', 15), 'Clear')),
    pre);
  return poll(async () => {
    const r = await api(`/api/apps/${enc(name)}/logs${offset == null ? '' : `?offset=${offset}`}`);
    if (r.reset) pre.textContent = '';
    if (r.text) {
      pre.append(r.text);
      if (pre.textContent.length > 500000) pre.textContent = pre.textContent.slice(-350000);
    }
    offset = r.offset;
    if (follow) pre.scrollTop = pre.scrollHeight;
  }, 1500);
}

function deployLog(box, id) {
  const head = h('div', { class: 'dep-log-head' });
  const pre = h('pre', { class: 'log', tabindex: '0', 'data-empty': 'Waiting for output…' });
  box.replaceChildren(head, pre);
  let offset = 0;
  let stop = () => {};
  stop = poll(async () => {
    const r = await api(`/api/deployments/${id}/log?offset=${offset}`);
    const d = r.deployment;
    head.replaceChildren(
      h('h3', {}, `Deploy #${d.id}`), badge(DEPLOY_STATUS[d.status]),
      d.started_at ? h('span', { class: 'muted small' }, d.finished_at ? `took ${fmtDuration(d.finished_at - d.started_at)}` : `running for ${fmtDuration(now() - d.started_at)}`) : '');
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 24;
    if (r.text) pre.append(r.text);
    offset = r.offset;
    if (atBottom) pre.scrollTop = pre.scrollHeight;
    if (r.done) stop();
  }, 1200);
  return () => stop();
}

function deploymentsTab(body, name, depId) {
  const list = h('div', { class: 'card dep-list' });
  const logBox = h('div', { class: 'dep-log' });
  body.append(h('div', { class: 'dep-layout' }, list, logBox));
  let items = [];
  let selected = depId ? Number(depId) : null;
  let stopLog = null;

  const select = (id) => {
    selected = id;
    stopLog?.();
    stopLog = deployLog(logBox, id);
    drawList();
    history.replaceState(null, '', `#/apps/${enc(name)}/deployments/${id}`);
  };
  const trigger = (t) => ({ created: 'First deploy', manual: 'Redeploy', cli: 'Deployed from the terminal' }[t] || t);
  function drawList() {
    list.replaceChildren(...(items.length ? items.map((d) => h('button', {
      class: `dep-item ${d.id === selected ? 'active' : ''}`, type: 'button', onclick: () => select(d.id),
    },
      h('div', { class: 'dep-item-top' }, h('span', { class: 'mono small muted' }, `#${d.id}`), badge(DEPLOY_STATUS[d.status])),
      h('div', { class: 'dep-item-msg truncate' }, d.commit_msg || trigger(d.trigger)),
      h('div', { class: 'dep-item-meta' },
        d.commit_sha ? [h('span', { class: 'mono' }, d.commit_sha.slice(0, 7)), ' · '] : null,
        fmtAgo(d.created_at),
        d.finished_at && d.started_at ? ` · ${fmtDuration(d.finished_at - d.started_at)}` : null)))
      : [h('div', { class: 'empty-row' }, 'No deploys yet.')]));
  }

  if (selected != null) stopLog = deployLog(logBox, selected);
  const stopList = poll(async () => {
    items = (await api(`/api/apps/${enc(name)}/deployments`)).deployments;
    if (selected == null && items[0]) select(items[0].id);
    else drawList();
  }, 3000);
  return () => { stopList(); stopLog?.(); };
}

function settingsTab(body, name) {
  let cancelled = false;
  body.append(h('p', { class: 'muted' }, 'Loading…'));
  api(`/api/apps/${enc(name)}`)
    .then((app) => { if (!cancelled) drawSettings(body, app); })
    .catch((e) => body.replaceChildren(h('p', { class: 'form-error' }, e.message)));
  return () => { cancelled = true; };
}

function drawSettings(body, app) {
  const envText = Object.entries(app.env || {}).map(([k, v]) => `${k}=${v}`).join('\n');
  const f = {
    repo_url: input({ class: 'mono', value: app.repo_url, required: true, spellcheck: 'false', autocapitalize: 'off' }),
    branch: input({ value: app.branch, required: true, spellcheck: 'false', autocapitalize: 'off' }),
    port: input({ type: 'number', value: app.port, min: 1024, max: 65535, required: true }),
    start_cmd: input({ class: 'mono', value: app.start_cmd, placeholder: app.detected_cmd || 'Detected on the next deploy', spellcheck: 'false', autocapitalize: 'off' }),
    env_text: textarea(envText, { class: 'mono', rows: 7, placeholder: 'DATABASE_URL=postgres://…\nDEBUG=false', spellcheck: 'false' }),
  };
  const err = h('p', { class: 'form-error', role: 'alert' });
  const save = h('button', { class: 'btn btn-primary', type: 'submit' }, 'Save');
  const cmdHint = app.detected_cmd
    ? `Leave empty to use the detected command: ${app.detected_cmd}`
    : 'Leave empty to detect it from a Procfile, package.json, main.py or app.py.';

  const form = h('form', {
    class: 'card form',
    onsubmit: async (e) => {
      e.preventDefault();
      err.textContent = '';
      save.disabled = true;
      save.textContent = 'Saving…';
      try {
        const r = await api(`/api/apps/${enc(app.name)}`, {
          method: 'PATCH',
          body: { repo_url: f.repo_url.value, branch: f.branch.value, port: Number(f.port.value), start_cmd: f.start_cmd.value, env_text: f.env_text.value },
        });
        toast(r.message);
      } catch (ex) {
        err.textContent = ex.message;
      } finally {
        save.disabled = false;
        save.textContent = 'Save';
      }
    },
  },
    field('Repository', f.repo_url),
    h('div', { class: 'grid-2' },
      field('Branch', f.branch, 'Changing it takes effect on the next deploy.'),
      field('Port', f.port, 'The app gets this as $PORT and should listen on it.')),
    field('Start command', f.start_cmd, cmdHint),
    field('Environment variables', f.env_text, 'One KEY=value per line. Lines starting with # are ignored. Saving restarts the app.'),
    err,
    h('div', { class: 'form-actions' }, save));

  const danger = h('section', { class: 'card danger' },
    h('div', {}, h('h3', {}, 'Delete this app'),
      h('p', { class: 'muted small' }, 'Stops it and removes its code, environment, logs and deploy history from the phone.')),
    h('button', {
      class: 'btn btn-danger',
      onclick: async () => {
        if (!confirm(`Delete ${app.name}? This can’t be undone.`)) return;
        try {
          await api(`/api/apps/${enc(app.name)}`, { method: 'DELETE' });
          toast(`Deleted ${app.name}.`);
          location.hash = '#/apps';
        } catch (ex) { toast(ex.message, 'bad'); }
      },
    }, icon('trash', 16), 'Delete app'));

  body.replaceChildren(form, danger);
}

// ---------- terminal ----------

// The iframe is created once and kept, so the shell survives switching pages.
function viewTerminal(main) {
  const host = $('#terminal-host');
  if (!host.firstChild) host.append(h('iframe', { class: 'terminal-frame', src: '/terminal/', title: 'Phone terminal' }));
  main.hidden = true;
  host.hidden = false;
  return () => { host.hidden = true; main.hidden = false; };
}

// ---------- settings ----------

function viewSettings(main) {
  const keyCard = h('section', { class: 'card card-pad' }, h('h2', {}, 'GitHub access'), h('p', { class: 'muted' }, 'Loading…'));
  const aboutCard = h('section', { class: 'card card-pad' }, h('h2', {}, 'About'), h('p', { class: 'muted' }, 'Loading…'));

  const themeButtons = h('div', { class: 'segmented', role: 'group', 'aria-label': 'Theme' });
  const drawTheme = () => themeButtons.replaceChildren(...[['dark', 'Dark'], ['light', 'Light'], ['system', 'Match device']].map(([key, label]) =>
    h('button', { type: 'button', 'aria-pressed': String(storedTheme() === key), onclick: () => { setTheme(key); drawTheme(); } }, label)));
  drawTheme();

  const passwordCmd = 'cd ~/phone-server && .venv/bin/python -m server.cli set-password';
  main.append(
    pageHead('Settings'),
    keyCard,
    h('section', { class: 'card card-pad' }, h('h2', {}, 'Appearance'), themeButtons),
    h('section', { class: 'card card-pad' },
      h('h2', {}, 'Account'),
      h('p', { class: 'muted' }, 'To change the dashboard password, run this on the phone (in the Terminal tab works too). Everyone gets signed out.'),
      codeLine(passwordCmd),
      h('div', { class: 'form-actions start' }, h('button', { class: 'btn', onclick: signOut }, icon('logout', 16), 'Sign out'))),
    aboutCard);

  drawKey(keyCard);
  api('/api/about').then((a) => {
    const dl = h('dl', { class: 'kv' });
    for (const [k, v] of [['Phone Server', a.version], ...Object.entries(a.versions), ['Data folder', a.data_dir],
      ['Dashboard port', a.public_port], ['Running since', new Date(a.started_at * 1000).toLocaleString()]]) {
      dl.append(h('dt', {}, k), h('dd', {}, v ?? 'not found'));
    }
    aboutCard.replaceChildren(h('h2', {}, 'About'), dl);
  }).catch((e) => aboutCard.replaceChildren(h('h2', {}, 'About'), h('p', { class: 'form-error' }, e.message)));
}

async function drawKey(card) {
  let r;
  try { r = await api('/api/settings/ssh-key'); } catch (e) {
    card.replaceChildren(h('h2', {}, 'GitHub access'), h('p', { class: 'form-error' }, e.message));
    return;
  }
  const intro = h('p', { class: 'muted' }, 'To deploy private repositories, the phone needs an SSH key that GitHub knows about.');
  if (!r.public_key) {
    const create = h('button', {
      class: 'btn btn-primary',
      onclick: async () => {
        create.disabled = true;
        try { await api('/api/settings/ssh-key', { method: 'POST' }); await drawKey(card); }
        catch (e) { toast(e.message, 'bad'); create.disabled = false; }
      },
    }, icon('key', 16), 'Create a key for this phone');
    card.replaceChildren(h('h2', {}, 'GitHub access'), intro, h('div', { class: 'form-actions start' }, create));
    return;
  }
  const result = h('p', { class: 'small', role: 'status' });
  const test = h('button', {
    class: 'btn',
    onclick: async () => {
      test.disabled = true;
      result.className = 'small muted';
      result.textContent = 'Connecting to GitHub…';
      try {
        const t = await api('/api/settings/github-test', { method: 'POST' });
        result.className = `small ${t.ok ? 'tone-ok' : 'tone-bad'}`;
        result.textContent = t.message;
      } catch (e) {
        result.className = 'small tone-bad';
        result.textContent = e.message;
      } finally { test.disabled = false; }
    },
  }, 'Test connection');
  card.replaceChildren(
    h('h2', {}, 'GitHub access'), intro,
    h('div', { class: 'key-box' }, h('code', {}, r.public_key), copyBtn(r.public_key)),
    h('ol', { class: 'steps' },
      h('li', {}, 'Copy the key above.'),
      h('li', {}, 'Open ', h('a', { class: 'link', href: 'https://github.com/settings/ssh/new', target: '_blank', rel: 'noopener' }, 'GitHub → New SSH key'),
        ', name it something like “Phone server”, and paste it.'),
      h('li', {}, 'Come back here and test the connection.')),
    h('p', { class: 'small muted' }, 'A key on your account can read every repository you can. To allow just one, add it as a deploy key in that repository’s settings instead (a deploy key works for one repository only).'),
    h('div', { class: 'form-actions start' }, test),
    result);
}

// ---------- sign in / out ----------

async function signOut() {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch { /* signed out anyway */ }
  showLogin({ configured: true });
}

function showLogin(status = {}) {
  stopRoute();
  $('#terminal-host').replaceChildren(); // close the shell
  $('#dialog').open && $('#dialog').close();
  $('#shell').hidden = true;
  const root = $('#login');
  root.hidden = false;

  const brand = h('div', { class: 'brand' }, h('span', { class: 'brand-mark' }, icon('phone')), 'Phone Server');
  if (status.configured === false) {
    root.replaceChildren(h('div', { class: 'login-card' }, brand,
      h('p', {}, 'No password is set yet. On the phone, run:'),
      codeLine('cd ~/phone-server && .venv/bin/python -m server.cli set-password'),
      h('p', { class: 'muted small' }, 'Then reload this page.')));
    return;
  }
  const err = h('p', { class: 'form-error', role: 'alert' }, status.error || '');
  const pw = h('input', { type: 'password', autocomplete: 'current-password', required: true });
  const submit = h('button', { class: 'btn btn-primary btn-block', type: 'submit' }, 'Sign in');
  root.replaceChildren(h('form', {
    class: 'login-card',
    onsubmit: async (e) => {
      e.preventDefault();
      err.textContent = '';
      submit.disabled = true;
      submit.textContent = 'Signing in…';
      try {
        await api('/api/auth/login', { method: 'POST', body: { password: pw.value } });
        pw.value = '';
        showShell();
      } catch (ex) {
        err.textContent = ex.message;
        pw.select();
      } finally {
        submit.disabled = false;
        submit.textContent = 'Sign in';
      }
    },
  }, brand, field('Password', pw), err, submit));
  pw.focus();
}

function showShell() {
  $('#login').hidden = true;
  $('#login').replaceChildren();
  $('#shell').hidden = false;
  render();
}

// ---------- start ----------

const VIEWS = { overview: viewOverview, apps: viewApps, app: viewApp, terminal: viewTerminal, settings: viewSettings };

document.querySelectorAll('[data-icon]').forEach((el) => el.append(icon(el.dataset.icon)));
$('#theme-toggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
applyTheme();

(async () => {
  try {
    const s = await api('/api/auth/status');
    if (s.authenticated) showShell(); else showLogin(s);
  } catch (e) {
    showLogin({ configured: true, error: e.message });
  }
})();
