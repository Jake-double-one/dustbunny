(() => {
  'use strict';

  /* ---------- i18n ---------------------------------------------------- */
  const T = {
    de: {
      language: 'Sprache', theme: 'Farbschema',
      themeAuto: 'Auto', themeLight: 'Hell', themeDark: 'Dunkel',
      heroEyebrow: 'Verwaist',
      heroText: (n, root) => n === 1
        ? `in <b>1 Ordner</b> unter ${root}, den nichts mehr benutzt.`
        : `in <b>${n} Ordnern</b> unter ${root}, die nichts mehr benutzt.`,
      clean: 'Keine Staubmäuse. Jeder Ordner wird noch gebraucht. 🐇',
      lastScan: t => `Letzter Scan ${t}.`,
      scan: 'Jetzt scannen', scanning: 'Scan läuft …', demoNoScan: 'Demo – kein Scan',
      railEyebrow: 'Speicher nach Zustand',
      cat: { active: 'Aktiv', stopped: 'Gestoppt', 'defined-only': 'Nur definiert', orphan: 'Verwaist', ignored: 'Ignoriert' },
      all: 'Alle',
      search: 'Ordner, Pfad oder Container suchen',
      noMatch: 'Nichts gefunden. Anderer Filter?',
      demo: '<b>Demo-Daten.</b> Die echte Anbindung kommt mit der API.',
      incomplete: '<b>Ergebnis unvollständig.</b> Mindestens eine Quelle hat nicht geantwortet. Verwaiste Ordner können hier falsch sein, solange das so bleibt.',
      orphanSince: n => (n < 1 ? 'seit heute verwaist' : n === 1 ? 'seit 1 Tag verwaist' : `seit ${n} Tagen verwaist`),
      changed: d => `geändert ${d}`,
      usedBy: (who, st) => `${who} · ${st}`,
      path: 'Pfad', why: 'Warum', refs: 'Wer ihn benutzt', broad: 'Sieht ihn nur über das ganze Verzeichnis',
      checked: 'Geprüft', size: 'Größe', lastChange: 'Letzte Änderung', firstSeen: 'Erstmals verwaist',
      state: { running: 'läuft', stopped: 'gestoppt', defined: 'nur definiert' },
      kind: { bind: 'Mount', 'volume-device': 'Volume', 'raw-text': 'im Dateitext', 'env-file': 'env-Datei', 'project-dir': 'Projektordner', config: 'Config', secret: 'Secret', 'build-context': 'Build', include: 'Include', extends: 'Extends' },
      reason: {
        'used-running': o => `Laufende Container benutzen ihn: ${o}.`,
        'used-stopped': o => `Nur gestoppte Container benutzen ihn: ${o}.`,
        'defined-only': o => `Steht noch in einer Stack- oder Compose-Datei, aber es gibt keinen Container: ${o}.`,
        'no-reference': () => 'Nichts verweist auf diesen Ordner oder etwas darin.',
        'broad-access-only': o => `Nur ${o} sieht ihn, weil das ganze Verzeichnis eingebunden ist. Das zählt nicht als Benutzung.`,
        'unresolved-match': () => 'Passt zu einem Pfad mit unbekannter Variable. Sicherheitshalber als benutzt gewertet.',
        symlink: () => 'Symbolischer Link. Wird nie angefasst.',
        'nested-root': () => 'Ist selbst ein Scan-Verzeichnis.',
        'builtin-ignore': () => 'Systemordner. Wird immer übersprungen.',
        'ignore-rule': () => 'Steht auf deiner Ignorierliste.',
        mountpoint: () => 'Eigener Mountpoint.',
        'stats-incomplete': () => 'Größe unvollständig: Nicht alles war lesbar.',
      },
      footer: 'Dustbunny liest nur. Gelöscht wird nichts, solange du es nicht ausdrücklich einschaltest.',
    },
    en: {
      language: 'Language', theme: 'Colour scheme',
      themeAuto: 'Auto', themeLight: 'Light', themeDark: 'Dark',
      heroEyebrow: 'Orphaned',
      heroText: (n, root) => n === 1
        ? `in <b>1 folder</b> under ${root} that nothing uses anymore.`
        : `in <b>${n} folders</b> under ${root} that nothing uses anymore.`,
      clean: 'No dust bunnies. Every folder is still in use. 🐇',
      lastScan: t => `Last scan ${t}.`,
      scan: 'Scan now', scanning: 'Scanning …', demoNoScan: 'Demo – no scan',
      railEyebrow: 'Storage by state',
      cat: { active: 'Active', stopped: 'Stopped', 'defined-only': 'Defined only', orphan: 'Orphaned', ignored: 'Ignored' },
      all: 'All',
      search: 'Search folder, path or container',
      noMatch: 'Nothing found. Try another filter?',
      demo: '<b>Demo data.</b> Live data arrives with the API.',
      incomplete: '<b>Incomplete result.</b> At least one source did not answer. Orphans may be wrong until it does.',
      orphanSince: n => (n < 1 ? 'orphaned since today' : n === 1 ? 'orphaned for 1 day' : `orphaned for ${n} days`),
      changed: d => `changed ${d}`,
      usedBy: (who, st) => `${who} · ${st}`,
      path: 'Path', why: 'Why', refs: 'Used by', broad: 'Only sees it through the whole directory',
      checked: 'Checked', size: 'Size', lastChange: 'Last change', firstSeen: 'Orphaned since',
      state: { running: 'running', stopped: 'stopped', defined: 'defined only' },
      kind: { bind: 'mount', 'volume-device': 'volume', 'raw-text': 'in file text', 'env-file': 'env file', 'project-dir': 'project dir', config: 'config', secret: 'secret', 'build-context': 'build', include: 'include', extends: 'extends' },
      reason: {
        'used-running': o => `Used by running containers: ${o}.`,
        'used-stopped': o => `Only used by stopped containers: ${o}.`,
        'defined-only': o => `Still in a stack or compose file, but no container exists: ${o}.`,
        'no-reference': () => 'Nothing references this folder or anything inside it.',
        'broad-access-only': o => `Only ${o} sees it, because the whole directory is mounted. That doesn't count as use.`,
        'unresolved-match': () => 'Matches a path with an unknown variable. Counted as used to be safe.',
        symlink: () => 'Symbolic link. Never touched.',
        'nested-root': () => 'Is itself a scan directory.',
        'builtin-ignore': () => 'System folder. Always skipped.',
        'ignore-rule': () => 'On your ignore list.',
        mountpoint: () => 'Separate mount point.',
        'stats-incomplete': () => 'Size incomplete: not everything was readable.',
      },
      footer: 'Dustbunny only reads. Nothing gets deleted unless you explicitly switch it on.',
    },
  };

  const CATS = ['orphan', 'defined-only', 'stopped', 'active', 'ignored'];
  const SEG = { active: 'seg-active', stopped: 'seg-stopped', 'defined-only': 'seg-defined', orphan: 'seg-orphan', ignored: 'seg-ignored' };
  const STATE_RANK = { running: 0, stopped: 1, defined: 2 };

  const store = {
    get(k) { try { return localStorage.getItem('dustbunny.' + k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem('dustbunny.' + k, v); } catch { /* private mode */ } },
  };

  const state = {
    report: null, demo: false,
    filter: 'all', query: '',
    lang: store.get('lang') || ((navigator.language || 'de').toLowerCase().startsWith('de') ? 'de' : 'en'),
    theme: store.get('theme') || 'auto',
  };
  const t = () => T[state.lang];

  /* ---------- helpers ------------------------------------------------- */
  // Builds DOM nodes; text children are always inserted as text, never HTML.
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v; // only for our own i18n strings
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const c of children.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : String(c));
    return el;
  }
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const locale = () => (state.lang === 'de' ? 'de-DE' : 'en-GB');

  function sizeParts(bytes) {
    if (bytes == null) return ['–', ''];
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
    let v = bytes, i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    const nf = new Intl.NumberFormat(locale(), { maximumFractionDigits: i === 0 || v >= 100 ? 0 : 1 });
    return [nf.format(v), units[i]];
  }
  const size = b => sizeParts(b).join(' ').trim();

  function ago(iso) {
    if (!iso) return null;
    const diff = (new Date(iso) - now()) / 1000;
    const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' });
    const steps = [[60, 'second'], [3600, 'minute'], [86400, 'hour'], [86400 * 30, 'day'], [86400 * 365, 'month'], [Infinity, 'year']];
    const div = { second: 1, minute: 60, hour: 3600, day: 86400, month: 86400 * 30, year: 86400 * 365 };
    for (const [limit, unit] of steps) if (Math.abs(diff) < limit) return rtf.format(Math.round(diff / div[unit]), unit);
  }
  const daysSince = iso => Math.floor((now() - new Date(iso)) / 86400000);
  // Demo data has a fixed timestamp; anchor "now" to it so ages stay stable.
  const now = () => (state.demo && state.report ? new Date(state.report.generated_at) : new Date());
  function clock(iso) {
    const d = new Date(iso);
    const time = d.toLocaleTimeString(locale(), { hour: '2-digit', minute: '2-digit' });
    const sameDay = d.toDateString() === now().toDateString();
    return sameDay ? (state.lang === 'de' ? `heute ${time}` : `today ${time}`) : d.toLocaleString(locale(), { dateStyle: 'medium', timeStyle: 'short' });
  }

  function owners(hits, filterState) {
    const names = [];
    for (const hit of hits) {
      if (filterState && hit.reference.state !== filterState) continue;
      const n = hit.reference.owner || hit.reference.origin || hit.reference.path;
      if (!names.includes(n)) names.push(n);
    }
    return names.join(', ');
  }
  function bestState(folder) {
    return folder.protected_by.map(h => h.reference.state).sort((a, b) => STATE_RANK[a] - STATE_RANK[b])[0];
  }
  function reasonText(folder, reason) {
    const fn = t().reason[reason.code];
    if (!fn) return reason.message;
    if (reason.code === 'broad-access-only') return fn(owners(folder.broad_access));
    const st = { 'used-running': 'running', 'used-stopped': 'stopped', 'defined-only': 'defined' }[reason.code];
    return fn(st ? owners(folder.protected_by, st) : '');
  }

  /* ---------- rendering ----------------------------------------------- */
  function render() {
    document.documentElement.lang = state.lang;
    document.documentElement.dataset.theme = state.theme;
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t()[el.dataset.i18n]; });
    document.querySelectorAll('[data-i18n-label]').forEach(el => el.setAttribute('aria-label', t()[el.dataset.i18nLabel]));
    document.querySelectorAll('[data-theme-set]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.themeSet === state.theme)));
    document.querySelectorAll('[data-lang-set]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.langSet === state.lang)));

    const app = document.getElementById('app');
    const r = state.report;
    if (!r) { app.replaceChildren(); return; }
    app.replaceChildren(lede(r), rail(r), stats(r), hints(r), toolbar(r), list(r));
  }

  function lede(r) {
    const orphans = r.summary.counts.orphan || 0;
    const [num, unit] = sizeParts(r.summary.orphan_bytes);
    const roots = esc(r.roots.join(', '));
    const scanBtn = h('button', { class: 'chip chip-main', type: 'button', onclick: e => scan(e.currentTarget) }, t().scan);
    return h('section', { class: 'lede' },
      h('p', { class: 'eyebrow' }, t().heroEyebrow),
      h('div', { class: 'hero' }, orphans ? num : '0', h('small', {}, orphans ? unit : '')),
      h('p', { html: (orphans ? t().heroText(orphans, roots) : esc(t().clean)) + ' ' + esc(t().lastScan(clock(r.generated_at))) }),
      h('div', { class: 'lede-actions' }, scanBtn));
  }

  function rail(r) {
    const total = r.summary.total_bytes || 1;
    const bytes = Object.fromEntries(CATS.map(c => [c, 0]));
    for (const f of r.folders) bytes[f.category] += f.size_bytes || 0;
    const order = ['active', 'stopped', 'defined-only', 'orphan', 'ignored'];
    return h('section', { class: 'card' },
      h('p', { class: 'eyebrow', style: 'margin-bottom:12px' }, t().railEyebrow),
      h('div', { class: 'rail-track', role: 'img', 'aria-label': order.map(c => `${t().cat[c]} ${size(bytes[c])}`).join(', ') },
        order.filter(c => bytes[c] > 0).map(c => h('span', { class: SEG[c], style: `width:${(bytes[c] / total) * 100}%` }))),
      h('ul', { class: 'legend' }, order.map(c => h('li', {},
        h('span', { class: `sw ${SEG[c]}` }), t().cat[c], h('span', { class: 'v mono' }, size(bytes[c]))))));
  }

  function stats(r) {
    const c = r.summary.counts;
    const cell = (label, value, cls) => h('div', { class: 'stat' }, h('dt', {}, label), h('dd', { class: cls }, value));
    return h('dl', { class: 'stats' },
      cell(t().cat.active, c.active || 0),
      cell(t().cat.stopped, c.stopped || 0),
      cell(t().cat['defined-only'], c['defined-only'] || 0),
      cell(t().cat.orphan, c.orphan || 0, c.orphan ? 'gold' : null));
  }

  function hints(r) {
    const items = [];
    if (!r.complete) items.push(h('div', { class: 'hint alert', html: t().incomplete }));
    for (const s of r.sources.filter(s => !s.ok)) items.push(h('div', { class: 'hint alert' }, h('b', {}, s.name), ': ', s.error || ''));
    for (const w of r.warnings) items.push(h('div', { class: 'hint' }, w));
    if (state.demo) items.push(h('div', { class: 'hint', html: t().demo }));
    return h('div', { class: 'hints', hidden: items.length === 0 }, items);
  }

  function toolbar(r) {
    const counts = r.summary.counts;
    const chip = (key, label, n) => h('button', {
      class: 'chip', type: 'button', 'aria-pressed': String(state.filter === key),
      onclick: () => { state.filter = key; render(); },
    }, label, h('span', { class: 'n' }, n));
    const input = h('input', {
      class: 'search', type: 'search', placeholder: t().search, 'aria-label': t().search, value: state.query,
      oninput: e => { state.query = e.target.value; refreshList(); },
    });
    return h('div', { class: 'toolbar' }, input,
      h('div', { class: 'chips', role: 'group' },
        chip('all', t().all, r.summary.total),
        CATS.filter(c => counts[c]).map(c => chip(c, t().cat[c], counts[c]))));
  }

  function refreshList() {
    const old = document.querySelector('.list');
    if (old) old.replaceWith(list(state.report));
  }

  function matches(f) {
    if (state.filter !== 'all' && f.category !== state.filter) return false;
    const q = state.query.trim().toLowerCase();
    if (!q) return true;
    const hay = [f.name, f.path, ...f.protected_by.map(x => x.reference.owner || ''), ...f.broad_access.map(x => x.reference.owner || '')];
    return hay.some(s => s.toLowerCase().includes(q));
  }

  function list(r) {
    const rows = r.folders.filter(matches).map(row);
    return h('div', { class: 'list' }, rows.length ? rows : h('div', { class: 'empty' }, t().noMatch));
  }

  function row(f) {
    let meta;
    if (f.category === 'orphan') {
      meta = [f.first_seen && t().orphanSince(daysSince(f.first_seen)), f.last_modified && t().changed(ago(f.last_modified))].filter(Boolean).join(' · ');
    } else if (f.protected_by.length && f.category !== 'ignored') {
      const st = bestState(f);
      meta = t().usedBy(owners(f.protected_by, st), t().state[st]);
    } else {
      meta = f.reasons[0] ? reasonText(f, f.reasons[0]) : '';
    }
    const chev = h('span', { class: 'chev', 'aria-hidden': 'true', html: '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>' });
    return h('details', { class: 'row', 'data-cat': f.category },
      h('summary', {},
        h('span', { class: `dot ${f.category}`, title: t().cat[f.category], 'aria-label': t().cat[f.category] }),
        h('span', {}, h('div', { class: 'name' }, f.name), h('div', { class: 'meta' }, meta)),
        h('span', { class: 'size' }, size(f.size_bytes)),
        chev),
      detail(f));
  }

  function detail(f) {
    const ref = hit => h('li', {},
      h('span', { class: 'who' }, hit.reference.owner || '–'),
      h('span', { class: 'what' }, [t().state[hit.reference.state], t().kind[hit.reference.kind] || hit.reference.kind, hit.reference.source].join(' · ')),
      h('span', { class: 'where' }, hit.reference.path));
    const facts = [
      [t().size, size(f.size_bytes)],
      [t().lastChange, f.last_modified && ago(f.last_modified)],
      [t().firstSeen, f.first_seen && ago(f.first_seen)],
      [t().checked, f.checked_sources.join(', ') || '–'],
    ].filter(([, v]) => v);
    return h('div', { class: 'detail' },
      h('p', { class: 'path' }, f.path),
      h('div', { class: 'facts' }, facts.map(([k, v]) => h('span', {}, k + ' ', h('b', {}, v)))),
      h('h4', {}, t().why),
      h('ul', { class: 'reasons' }, f.reasons.map(rs => h('li', {}, reasonText(f, rs)))),
      f.protected_by.length ? [h('h4', {}, t().refs), h('ul', { class: 'refs' }, f.protected_by.map(ref))] : null,
      f.broad_access.length ? [h('h4', {}, t().broad), h('ul', { class: 'refs' }, f.broad_access.map(ref))] : null);
  }

  /* ---------- actions ------------------------------------------------- */
  async function scan(btn) {
    if (state.demo) { flash(btn, t().demoNoScan); return; }
    btn.disabled = true; btn.textContent = t().scanning;
    try {
      const res = await fetch('api/scan', { method: 'POST' });
      if (!res.ok) throw new Error(res.statusText);
      await load();
    } finally { btn.disabled = false; btn.textContent = t().scan; }
  }
  function flash(el, text) {
    const before = el.textContent;
    el.textContent = text;
    setTimeout(() => { el.textContent = before; }, 1400);
  }

  async function load() {
    try {
      const res = await fetch('api/report', { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error(res.statusText);
      state.report = await res.json(); state.demo = false;
    } catch {
      const res = await fetch('demo/report.json');
      state.report = await res.json(); state.demo = true;
    }
    render();
  }

  document.querySelectorAll('[data-theme-set]').forEach(b => b.addEventListener('click', () => {
    state.theme = b.dataset.themeSet; store.set('theme', state.theme); render();
  }));
  document.querySelectorAll('[data-lang-set]').forEach(b => b.addEventListener('click', () => {
    state.lang = b.dataset.langSet; store.set('lang', state.lang); render();
  }));

  render();
  load();
})();
