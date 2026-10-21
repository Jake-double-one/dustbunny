// Skins come from the server (src/dustbunny/skins/ and SKINS_DIR): their colours as <style id="skins">
// and the list as JSON in #skin-list. Nothing saved = data-theme="auto": the CSS follows the browser.

let list = { defaults: { light: 'light', dark: 'dark' }, skins: [] };
try {
  const el = document.getElementById('skin-list');
  if (el) list = JSON.parse(el.textContent);
} catch { /* keep the fallback */ }

const KEY = 'dustbunny.skin';
const load = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
const save = v => { try { localStorage.setItem(KEY, v); } catch { /* private mode */ } };
const darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
const browserScheme = () => (darkQuery?.matches ? 'dark' : 'light');
const known = id => list.skins.some(s => s.id === id);

export const skinList = () => list.skins;
export const skinName = (skin, lang) => skin.names[lang] ?? skin.names[''] ?? skin.id;
export const savedSkin = () => { const s = load(); return s && known(s) ? s : null; };
export const currentSkin = () => savedSkin() ?? list.defaults[browserScheme()];

export function applySkin() {
  document.documentElement.dataset.theme = savedSkin() ?? 'auto';
}

export function setSkin(id) {
  if (!known(id)) return;
  save(id);
  applySkin();
}

export const onSchemeChange = fn => darkQuery?.addEventListener?.('change', fn);
