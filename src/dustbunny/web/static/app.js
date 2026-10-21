import { LANGUAGES, VERSION, has, initI18n, lang, notice, setLang, store, t } from './i18n.js';
import { applySkin, currentSkin, onSchemeChange, setSkin, skinList, skinName } from './skins.js';

const CATS = ['orphan', 'defined-only', 'stopped', 'active', 'ignored'];
const RAIL_ORDER = ['active', 'stopped', 'defined-only', 'orphan', 'ignored'];
const SEG = { active: 'seg-active', stopped: 'seg-stopped', 'defined-only': 'seg-defined', orphan: 'seg-orphan', ignored: 'seg-ignored' };
const STATE_RANK = { running: 0, stopped: 1, defined: 2 };
const DEMO = new URLSearchParams(location.search).has('demo');

// Sorting: 'category' keeps the server's order (orphaned first). Names go A–Z, sizes and dates
// largest/newest first; "reverse" flips that. Unknown values (no size, no creation date) stay last.
const SORTS = ['category', 'name', 'size', 'created', 'changed'];
const SORT_KEYS = {
  name: f => f.name.toLocaleLowerCase(),
  size: f => f.size_bytes,
  created: f => (f.created ? Date.parse(f.created) : null),
  changed: f => (f.last_modified ? Date.parse(f.last_modified) : null),
};
const savedSort = store.get('sort');

const state = {
  report: null, status: null, filter: 'all', query: '', open: new Set(), error: null,
  sort: SORTS.includes(savedSort) ? savedSort : 'category',
  reverse: store.get('reverse') === '1',
};

/* ---------- helpers ---------------------------------------------------- */
// Builds DOM nodes. Text children are always inserted as text, never as HTML.
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}

function sizeParts(bytes) {
  if (bytes == null) return ['–', ''];
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let v = bytes, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  const nf = new Intl.NumberFormat(lang, { maximumFractionDigits: i === 0 || v >= 100 ? 0 : 1 });
  return [nf.format(v), units[i]];
}
const size = b => sizeParts(b).join(' ').trim();

// Demo data has a fixed timestamp; anchor "now" to it so ages stay stable.
const now = () => (DEMO && state.report ? new Date(state.report.generated_at) : new Date());
const daysSince = iso => Math.floor((now() - new Date(iso)) / 86400000);

function ago(iso) {
  if (!iso) return null;
  const diff = (new Date(iso) - now()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' });
  const units = [[60, 'second', 1], [3600, 'minute', 60], [86400, 'hour', 3600], [86400 * 30, 'day', 86400], [86400 * 365, 'month', 86400 * 30], [Infinity, 'year', 86400 * 365]];
  for (const [limit, unit, div] of units) if (Math.abs(diff) < limit) return rtf.format(Math.round(diff / div), unit);
  return null;
}

function clock(iso) {
  const d = new Date(iso);
  const time = d.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' });
  return d.toDateString() === now().toDateString()
    ? t('time.today', { time })
    : d.toLocaleString(lang, { dateStyle: 'medium', timeStyle: 'short' });
}

function owners(hits, onlyState) {
  const names = [];
  for (const hit of hits) {
    if (onlyState && hit.reference.state !== onlyState) continue;
    const n = hit.reference.owner || hit.reference.origin || hit.reference.path;
    if (!names.includes(n)) names.push(n);
  }
  return names.join(', ');
}
const bestState = f => f.protected_by.map(x => x.reference.state).sort((a, b) => STATE_RANK[a] - STATE_RANK[b])[0];

// a translated label, or the raw code if no language file knows it
const label = (prefix, code) => (has(`${prefix}.${code}`) ? t(`${prefix}.${code}`) : code);

function flash(el, text) {
  const before = el.textContent;
  el.textContent = text;
  setTimeout(() => { el.textContent = before; }, 1600);
}

/* ---------- header ------------------------------------------------------ */
function renderHeader() {
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-label]').forEach(el => el.setAttribute('aria-label', t(el.dataset.i18nLabel)));
  document.getElementById('version').textContent = VERSION ? `v${VERSION}` : '';

  document.getElementById('lang').value = lang;

  const current = currentSkin();
  const picker = document.getElementById('skin-picker');
  const focused = picker.contains(document.activeElement);
  picker.replaceChildren(...skinList().map(s => h('button', {
    type: 'button', role: 'radio', class: 'swatch',
    style: `--sw-bg:${s.bg};--sw-accent:${s.accent}`,
    'aria-checked': String(s.id === current),
    tabindex: s.id === current ? '0' : '-1',
    'aria-label': skinName(s, lang), title: skinName(s, lang),
    onclick: () => { setSkin(s.id); renderHeader(); },
  })));
  if (focused) picker.querySelector('[aria-checked="true"]')?.focus();
}

// radio group: arrow keys move between skins
function onPickerKey(e) {
  const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  if (!(e.key in keys)) return;
  const buttons = [...e.currentTarget.querySelectorAll('.swatch')];
  const i = buttons.indexOf(document.activeElement);
  const next = buttons[(i + keys[e.key] + buttons.length) % buttons.length];
  e.preventDefault();
  next?.click();
}

/* ---------- main ------------------------------------------------------- */
function render() {
  renderHeader();
  // keep typing in the search box while the page updates
  const search = document.activeElement?.classList.contains('search') ? document.activeElement : null;
  const caret = search ? [search.selectionStart, search.selectionEnd] : null;
  const app = document.getElementById('app');
  const r = state.report;
  const parts = [hints()];
  if (r) parts.unshift(lede(r), sizesKnown(r) ? rail(r) : null, stats(r));
  else parts.unshift(lede(null));
  if (r) parts.push(toolbar(r), list(r));
  app.replaceChildren(...parts);
  if (search) {
    const input = app.querySelector('.search');
    input?.focus();
    input?.setSelectionRange(...caret);
  }
}

const sizesKnown = r => r.folders.some(f => f.size_bytes != null);

const scanning = () => !!state.status?.scanning;

function lede(r) {
  const orphans = r?.summary.counts.orphan || 0;
  // without sizes (SCAN_SIZES=false) the big number is the count of orphaned folders
  const [num, unit] = r && !sizesKnown(r)
    ? [new Intl.NumberFormat(lang).format(orphans), t('hero.unitFolders', { count: orphans })]
    : sizeParts(r?.summary.orphan_bytes || 0);
  let text;
  if (!r) text = t('hero.noScan');
  else {
    text = orphans ? t('hero.text', { count: orphans, roots: r.roots.join(', ') }) : t('hero.clean');
    text += ' ' + t('hero.lastScan', { time: clock(r.generated_at) });
  }
  const next = state.status?.next_scan_at;
  if (next && !DEMO && !scanning()) text += ' ' + t('hero.nextScan', { time: clock(next) });
  const button = h('button', {
    class: 'chip chip-main', type: 'button', id: 'scan',
    disabled: scanning() || !!state.status?.config_error,
    onclick: e => startScan(e.currentTarget),
  }, scanning() ? t('scan.running') : t('scan.start'));
  return h('section', { class: 'lede' },
    h('p', { class: 'eyebrow' }, t('hero.eyebrow')),
    h('div', { class: 'hero' }, orphans ? num : '0', h('small', {}, orphans ? unit : '')),
    h('p', {}, text),
    h('div', { class: 'lede-actions' }, button));
}

function rail(r) {
  const total = r.summary.total_bytes || 1;
  const bytes = Object.fromEntries(CATS.map(c => [c, 0]));
  for (const f of r.folders) bytes[f.category] += f.size_bytes || 0;
  return h('section', { class: 'card' },
    h('p', { class: 'eyebrow', style: 'margin-bottom:12px' }, t('rail.eyebrow')),
    h('div', { class: 'rail-track', role: 'img', 'aria-label': RAIL_ORDER.map(c => `${t('category.' + c)} ${size(bytes[c])}`).join(', ') },
      RAIL_ORDER.filter(c => bytes[c] > 0).map(c => h('span', { class: SEG[c], style: `width:${(bytes[c] / total) * 100}%` }))),
    h('ul', { class: 'legend' }, RAIL_ORDER.map(c => h('li', {},
      h('span', { class: `sw ${SEG[c]}` }), t('category.' + c), h('span', { class: 'v mono' }, size(bytes[c]))))));
}

function stats(r) {
  const c = r.summary.counts;
  const cell = (cat, cls) => h('div', { class: 'stat' }, h('dt', {}, t('category.' + cat)), h('dd', { class: cls }, c[cat] || 0));
  return h('dl', { class: 'stats' },
    cell('active'), cell('stopped'), cell('defined-only'), cell('orphan', c.orphan ? 'gold' : null));
}

function hints() {
  const items = [];
  const s = state.status;
  const r = state.report;
  if (state.error) items.push(h('div', { class: 'hint alert' }, t('hint.unreachable')));
  if (s?.config_error) items.push(h('div', { class: 'hint alert' }, t('hint.config', { error: s.config_error })));
  if (s?.last_error) items.push(h('div', { class: 'hint alert' }, t('hint.scanFailed', { error: s.last_error })));
  if (!r && scanning()) items.push(h('div', { class: 'hint loading' }, t('hint.firstScan')));
  if (r && !r.complete) items.push(h('div', { class: 'hint alert' }, t('hint.incomplete')));
  if (r && r.uncertain) items.push(h('div', { class: 'hint alert' }, t('hint.uncertain')));
  for (const w of r?.warnings || []) items.push(h('div', { class: 'hint' }, notice('warning', w)));
  if (DEMO) items.push(h('div', { class: 'hint' }, t('hint.demo')));
  return h('div', { class: 'hints', hidden: items.length === 0 }, items);
}

function toolbar(r) {
  const counts = r.summary.counts;
  const chip = (key, label, n) => h('button', {
    class: 'chip', type: 'button', 'aria-pressed': String(state.filter === key),
    onclick: () => { state.filter = key; render(); },
  }, label, h('span', { class: 'n' }, n));
  const input = h('input', {
    class: 'search', type: 'search', placeholder: t('search.placeholder'), 'aria-label': t('search.placeholder'), value: state.query,
    oninput: e => { state.query = e.target.value; refreshList(); },
  });
  const sort = h('select', {
    class: 'pill-select', 'aria-label': t('sort.label'), title: t('sort.label'),
    onchange: e => { state.sort = e.target.value; store.set('sort', state.sort); refreshList(); },
  }, SORTS.map(s => h('option', { value: s, selected: s === state.sort }, t('sort.' + s))));
  const reverse = h('button', {
    class: 'chip', type: 'button', 'aria-pressed': String(state.reverse),
    'aria-label': t('sort.reverse'), title: t('sort.reverse'),
    onclick: e => {
      state.reverse = !state.reverse;
      store.set('reverse', state.reverse ? '1' : '0');
      e.currentTarget.setAttribute('aria-pressed', String(state.reverse));
      refreshList();
    },
  }, '⇅');
  return h('div', { class: 'toolbar' }, input,
    h('div', { class: 'chips', role: 'group' },
      chip('all', t('filter.all'), r.summary.total),
      CATS.filter(c => counts[c]).map(c => chip(c, t('category.' + c), counts[c]))),
    h('div', { class: 'sorting' }, sort, reverse));
}

function sorted(folders) {
  const key = SORT_KEYS[state.sort];
  let out = [...folders];
  if (key) {
    const asc = state.sort === 'name';
    out.sort((a, b) => {
      const x = key(a), y = key(b);
      if (x == null || y == null) return (x == null) - (y == null);
      const order = x < y ? -1 : x > y ? 1 : 0;
      return asc ? order : -order;
    });
  }
  if (state.reverse) {
    // flip the order of the known values, unknown ones stay at the end
    const known = key ? out.filter(f => key(f) != null) : out;
    out = [...known.reverse(), ...out.filter(f => !known.includes(f))];
  }
  return out;
}

function refreshList() {
  document.querySelector('.list')?.replaceWith(list(state.report));
}

function matches(f) {
  if (state.filter !== 'all' && f.category !== state.filter) return false;
  const q = state.query.trim().toLowerCase();
  if (!q) return true;
  const hay = [f.name, f.path, ...[...f.protected_by, ...f.broad_access].map(x => x.reference.owner || '')];
  return hay.some(s => s.toLowerCase().includes(q));
}

function list(r) {
  const rows = sorted(r.folders.filter(matches)).map(row);
  return h('div', { class: 'list' }, rows.length ? rows : h('div', { class: 'empty' }, t('list.empty')));
}

function row(f) {
  let meta;
  if (f.category === 'orphan') {
    const days = f.first_seen ? daysSince(f.first_seen) : null;
    meta = [
      days == null ? null : days < 1 ? t('row.orphanedToday') : t('row.orphanedFor', { count: days }),
      f.last_modified && t('row.changed', { when: ago(f.last_modified) }),
    ].filter(Boolean).join(' · ');
  } else if (f.protected_by.length && f.category !== 'ignored') {
    const st = bestState(f);
    meta = t('row.usedBy', { owners: owners(f.protected_by, st), state: t('state.' + st) });
  } else {
    meta = f.reasons[0] ? notice('reason', f.reasons[0]) : '';
  }
  // the date the list is sorted by is shown in every row
  if (state.sort === 'created') meta = [meta, t('row.created', { when: f.created ? ago(f.created) : '–' })].filter(Boolean).join(' · ');
  if (state.sort === 'changed' && f.category !== 'orphan' && f.last_modified) meta = [meta, t('row.changed', { when: ago(f.last_modified) })].filter(Boolean).join(' · ');
  const chev = h('span', { class: 'chev', 'aria-hidden': 'true' });
  chev.innerHTML = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>';
  const details = h('details', { class: 'row', 'data-cat': f.category, open: state.open.has(f.path) },
    h('summary', {},
      h('span', { class: `dot ${f.category}`, title: t('category.' + f.category), role: 'img', 'aria-label': t('category.' + f.category) }),
      h('span', {}, h('span', { class: 'name' }, f.name), h('span', { class: 'meta' }, meta)),
      h('span', { class: 'size' }, size(f.size_bytes)),
      chev),
    detail(f));
  details.addEventListener('toggle', () => { details.open ? state.open.add(f.path) : state.open.delete(f.path); });
  return details;
}

function detail(f) {
  const ref = hit => h('li', {},
    h('span', { class: 'who' }, hit.reference.owner || '–'),
    h('span', { class: 'what' }, [label('state', hit.reference.state), label('kind', hit.reference.kind), hit.reference.source].join(' · ')),
    hit.size_bytes != null ? h('span', { class: 'size' }, size(hit.size_bytes)) : null,
    h('span', { class: 'where' }, hit.reference.path));
  const facts = [
    [t('detail.size'), size(f.size_bytes)],
    [t('detail.created'), f.created && ago(f.created)],
    [t('detail.lastChange'), f.last_modified && ago(f.last_modified)],
    [t('detail.orphanedSince'), f.first_seen && ago(f.first_seen)],
    [t('detail.sources'), f.checked_sources.join(', ') || '–'],
  ].filter(([, v]) => v);
  const userIgnored = f.reasons.some(x => x.code === 'ignored-by-user');
  const canIgnore = f.category !== 'ignored' || userIgnored;
  return h('div', { class: 'detail' },
    h('p', { class: 'path' }, f.path),
    h('div', { class: 'facts' }, facts.map(([k, v]) => h('span', {}, k + ' ', h('b', {}, v)))),
    h('h4', {}, t('detail.why')),
    h('ul', { class: 'reasons' }, f.reasons.map(x => h('li', {}, notice('reason', x)))),
    f.protected_by.length ? [h('h4', {}, t('detail.usedBy')), h('ul', { class: 'refs' }, f.protected_by.map(ref))] : null,
    f.broad_access.length ? [h('h4', {}, t('detail.broad')), h('ul', { class: 'refs' }, f.broad_access.map(ref))] : null,
    canIgnore && !DEMO ? h('div', { class: 'actions' }, h('button', {
      class: 'chip', type: 'button',
      onclick: e => toggleIgnore(f.path, !userIgnored, e.currentTarget),
    }, userIgnored ? t('detail.unignore') : t('detail.ignore'))) : null);
}

/* ---------- data ------------------------------------------------------- */
async function api(path, options) {
  const res = await fetch(path, { headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, ...options });
  if (!res.ok) { const err = new Error(String(res.status)); err.status = res.status; throw err; }
  return res.json();
}

async function loadStatus() {
  state.status = await api('api/status');
}

async function loadReport() {
  try { state.report = await api('api/report'); } catch (e) { if (e.status !== 404) throw e; state.report = null; }
}

let polling = null;
let shown = null;
async function refresh() {
  const wasScanning = scanning();
  try {
    const before = state.status?.last_scan_at;
    await loadStatus();
    if (!state.report || state.status.last_scan_at !== before) await loadReport();
    state.error = null;
  } catch {
    state.error = true;
  }
  // while scanning, redraw only on changes; otherwise once a minute, so "3 minutes ago" stays true
  const now = JSON.stringify([state.status, state.report?.generated_at, state.error]);
  if (now !== shown || !scanning()) { shown = now; render(); }
  if (wasScanning && !scanning() && state.report) announce(t('hero.lastScan', { time: clock(state.report.generated_at) }));
  clearTimeout(polling);
  polling = setTimeout(refresh, scanning() ? 2000 : 60000);
}

function announce(text) {
  document.getElementById('live').textContent = text;
}

async function startScan(button) {
  if (DEMO) { flash(button, t('scan.demo')); return; }
  try {
    await api('api/scan', { method: 'POST', body: '{}' });
    state.status = { ...state.status, scanning: true };
    render();
    announce(t('scan.running'));
    clearTimeout(polling);
    polling = setTimeout(refresh, 1000);
  } catch { flash(button, t('detail.failed')); }
}

async function toggleIgnore(path, ignored, button) {
  try {
    state.report = await api('api/ignore', { method: 'POST', body: JSON.stringify({ path, ignored }) });
    render();
  } catch { flash(button, t('detail.failed')); }
}

/* ---------- start ------------------------------------------------------ */
applySkin();
onSchemeChange(renderHeader);
const select = document.getElementById('lang');
select.replaceChildren(...LANGUAGES.map(l => h('option', { value: l.code }, l.name)));
select.hidden = LANGUAGES.length < 2;
select.addEventListener('change', async e => { await setLang(e.target.value); render(); });
document.getElementById('skin-picker').addEventListener('keydown', onPickerKey);

await initI18n();
if (DEMO) {
  state.report = await (await fetch('static/demo/report.json')).json();
  state.status = { scanning: false };
  render();
} else {
  await refresh();
}
