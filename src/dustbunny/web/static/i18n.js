// Translations: one JSON file per language in src/dustbunny/locales/, served at /locales/<code>.json.
// The server lists the available languages in the page (#boot), so a new file needs no code change.
// English is the fallback for missing keys.

const boot = (() => {
  try { return JSON.parse(document.getElementById('boot')?.textContent || '{}'); } catch { return {}; }
})();
export const LANGUAGES = boot.languages?.length ? boot.languages : [{ code: 'en', name: 'English' }];
export const VERSION = boot.version || '';
const FALLBACK = 'en';

let dict = {};
let fallback = {};
export let lang = FALLBACK;

const store = {
  get(k) { try { return localStorage.getItem('dustbunny.' + k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem('dustbunny.' + k, v); } catch { /* private mode */ } },
};
export { store };

async function fetchLocale(code) {
  const res = await fetch(`locales/${encodeURIComponent(code)}.json`);
  if (!res.ok) throw new Error(`locale ${code}: ${res.status}`);
  return res.json();
}

function detect() {
  const known = new Set(LANGUAGES.map(l => l.code));
  const stored = store.get('lang');
  if (stored && known.has(stored)) return stored;
  for (const l of navigator.languages || [navigator.language || '']) {
    const code = String(l).toLowerCase();
    if (known.has(code)) return code;
    if (known.has(code.split('-')[0])) return code.split('-')[0];
  }
  return FALLBACK;
}

export async function initI18n() {
  fallback = await fetchLocale(FALLBACK);
  await setLang(detect(), false);
}

export async function setLang(code, remember = true) {
  if (!LANGUAGES.some(l => l.code === code)) code = FALLBACK;
  dict = code === FALLBACK ? fallback : await fetchLocale(code).catch(() => fallback);
  lang = code;
  if (remember) store.set('lang', code);
  document.documentElement.lang = code;
}

/** t('key', {var}) – `{var}` placeholders; with a numeric `count`, `key_one`/`key_other`/… is used. */
export function t(key, vars = {}) {
  const keys = [];
  if (typeof vars.count === 'number') {
    keys.push(`${key}_${new Intl.PluralRules(lang).select(vars.count)}`, `${key}_other`);
  }
  keys.push(key);
  let text = key;
  for (const k of keys) {
    if (k in dict) { text = dict[k]; break; }
    if (k in fallback) { text = fallback[k]; break; }
  }
  return text.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m));
}

export const has = key => key in dict || key in fallback;

/** A notice from the server ({code, message, params}) in the current language */
export function notice(prefix, item) {
  const key = `${prefix}.${item.code}`;
  return key in dict || key in fallback ? t(key, item.params || {}) : item.message;
}
