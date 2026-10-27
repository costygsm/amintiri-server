// Amintiri pe web: aceleași date ca aplicația, sesiunea stă într-un cookie HttpOnly.
// Tot textul venit de la server intră prin textContent, niciodată prin innerHTML.
import { hashFile } from './sha256.js';

// ---------- limba: după browser, sau aleasă din meniu (ține minte browserul) ----------
const LANG_CHOICES = { auto: '', ro: 'Română', en: 'English' };
function langChoice() {
  try { const v = localStorage.getItem('limba'); if (v in LANG_CHOICES) return v; } catch { /* fără stocare */ }
  return 'auto';
}
const BROWSER_LANG = (navigator.language || '').toLowerCase().startsWith('ro') ? 'ro' : 'en';
const LANG = langChoice() === 'auto' ? BROWSER_LANG : langChoice();
document.documentElement.lang = LANG;
/** Textul în limba paginii; româna e prima, ca în restul codului. */
const tr = (ro, en) => (LANG === 'ro' ? ro : en);
function setLang(v) {
  try { localStorage.setItem('limba', v); } catch { /* fără stocare */ }
  location.reload();  // textele se construiesc o singură dată: cel mai simplu e să redesenăm tot
}

const MONTHS = LANG === 'ro'
  ? ['ianuarie', 'februarie', 'martie', 'aprilie', 'mai', 'iunie', 'iulie', 'august', 'septembrie', 'octombrie', 'noiembrie', 'decembrie']
  : ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const CHUNK = 8 * 1024 * 1024;
const COPYRIGHT = '© 2026 BACIU I CONSTANTIN II · servicegsm.eu';
const PARALLEL = 2;

// iconițe Material (aceleași căi ca în aplicație)
const DAYS = LANG === 'ro'
  ? ['duminică', 'luni', 'marți', 'miercuri', 'joi', 'vineri', 'sâmbătă']
  : ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const SEARCH_EXAMPLES = tr('vara 2024|august|iarna 2023|Roma', 'summer 2024|August|winter 2023|Rome').split('|');

// cât de mare e o „grupă” în grilă: zi, lună sau an; omul alege, browserul ține minte
const GROUPS = {
  zi: { len: 10, name: tr('Zile', 'Days'), label: (s) => dayLabel(s) },
  luna: { len: 7, name: tr('Luni', 'Months'), label: (s) => monthLabel(s) },
  an: { len: 4, name: tr('Ani', 'Years'), label: (s) => s.slice(0, 4) },
};
const KINDS = { '': tr('Toate', 'All'), photo: tr('Poze', 'Photos'), video: tr('Clipuri', 'Videos') };
function getPref(key, allowed, fallback) {
  try { const v = localStorage.getItem(key); if (v !== null && v in allowed) return v; } catch { /* fără stocare */ }
  return fallback;
}
function setPref(key, v) { try { localStorage.setItem(key, v); } catch { /* fără stocare */ } }
function getGroup() { return getPref('grupare', GROUPS, 'luna'); }
function setGroup(g) { setPref('grupare', g); }

const ICONS = {
  photo: 'M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z',
  place: 'M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 0 1 0-5 2.5 2.5 0 0 1 0 5z',
  video: 'M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z',
  all: 'M4 8h4V4H4v4zm6 12h4v-4h-4v4zm-6 0h4v-4H4v4zm0-6h4v-4H4v4zm6 0h4v-4h-4v4zm6-10v4h4V4h-4zm-6 4h4V4h-4v4zm6 6h4v-4h-4v4zm0 6h4v-4h-4v4z',
  cloud: 'M19.35 10.04A7.49 7.49 0 0 0 12 4C9.11 4 6.6 5.64 5.35 8.04A5.994 5.994 0 0 0 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96z',
  logout: 'M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z',
  upload: 'M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z',
  eye: 'M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-8a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  eyeOff: 'M12 7a5 5 0 0 1 5 5c0 .65-.13 1.26-.36 1.83l2.92 2.92A11.8 11.8 0 0 0 23 12c-1.73-4.39-6-7.5-11-7.5-1.4 0-2.74.25-3.98.7l2.16 2.16C10.74 7.13 11.35 7 12 7zM2 4.27l2.28 2.28.46.46A11.8 11.8 0 0 0 1 12c1.73 4.39 6 7.5 11 7.5 1.55 0 3.03-.3 4.38-.84l.42.42L19.73 22 21 20.73 3.27 3 2 4.27zM7.53 9.8l1.55 1.55A2.8 2.8 0 0 0 9 12a3 3 0 0 0 3 3c.22 0 .44-.03.65-.08l1.55 1.55A5 5 0 0 1 7.53 9.8zm4.31-.78 3.15 3.15.02-.16a3 3 0 0 0-3-3l-.17.01z',
  close: 'M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z',
  prev: 'M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z',
  next: 'M10 6 8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z',
  download: 'M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z',
  delete: 'M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z',
  album: 'M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm4 18H6V4h7v5h5v11zM8 15.01l1.41 1.41L11 14.84V19h2v-4.16l1.59 1.59L16 15.01 12.01 11z',
  addAlbum: 'M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-1 9h-4v4h-2v-4H9V9h4V5h2v4h4v2z',
  play: 'M8 5v14l11-7z',
  back: 'M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z',
  language: 'M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zm6.93 6h-2.95a15.65 15.65 0 0 0-1.38-3.56A8.03 8.03 0 0 1 18.92 8zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96zM4.26 14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2s.06 1.34.14 2H4.26zm.82 2h2.95c.32 1.25.78 2.45 1.38 3.56A7.99 7.99 0 0 1 5.08 16zm2.95-8H5.08a7.99 7.99 0 0 1 4.33-3.56A15.65 15.65 0 0 0 8.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 3.96zM14.34 14H9.66c-.09-.66-.16-1.32-.16-2s.07-1.35.16-2h4.68c.09.65.16 1.32.16 2s-.07 1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95a8.03 8.03 0 0 1-4.33 3.56zM16.36 14c.08-.66.14-1.32.14-2s-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 2s-.1 1.36-.26 2h-3.38z',
  search: 'M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z',
  expand: 'M7 10l5 5 5-5z',
  collapse: 'M7 14l5-5 5 5z',
  remove: 'M19 13H5v-2h14v2z',
  check: 'M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z',
};

// ---------- mici ajutoare DOM ----------
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
  return el;
}
function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'i');
  svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', ICONS[name]);
  svg.append(p);
  return svg;
}
function iconBtn(name, label, onclick, cls = 'icon-btn') {
  return h('button', { class: cls, type: 'button', 'aria-label': label, title: label, onclick }, icon(name));
}
const $app = () => document.getElementById('app');

// ---------- mișcare ----------
// cine a cerut sistemului „mai puține animații” le primește fără mișcare
const calm = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const EASE_OUT = 'cubic-bezier(.2, .8, .2, 1)';
/** Scoate un element cu o mică animație de ieșire (mai scurtă decât intrarea). */
function leave(el, keyframes = [{ opacity: 1 }, { opacity: 0, transform: 'translateY(8px)' }]) {
  if (!el?.isConnected) return;
  if (calm() || !el.animate) { el.remove(); return; }
  el.animate(keyframes, { duration: 160, easing: 'ease-in', fill: 'forwards' }).finished.then(() => el.remove(), () => el.remove());
}
/**
 * Schimbare animată cu View Transitions: poza din grilă „zboară” în vizualizator și înapoi.
 * [named] primește elementul care poartă numele comun înainte și după schimbare.
 * Fără suport (Firefox vechi) sau cu animațiile oprite, schimbarea se face direct.
 */
async function morph(update, before, after) {
  if (calm() || !document.startViewTransition) { await update(); return; }
  if (before) before.style.viewTransitionName = 'foto';
  const vt = document.startViewTransition(async () => {
    if (before) before.style.viewTransitionName = '';
    await update();
    const el = after?.();
    if (el) {
      el.style.viewTransitionName = 'foto';
      // așteptăm puțin poza mare, ca animația să nu ajungă într-un dreptunghi gol
      await Promise.race([el.decode?.().catch(() => {}), new Promise((r) => setTimeout(r, 250))]);
    }
  });
  vt.finished.finally(() => { const el = after?.(); if (el) el.style.viewTransitionName = ''; });
  await vt.updateCallbackDone.catch(() => {});
}

let toastTimer;
function toast(text) {
  document.querySelector('.toast')?.remove();
  const t = h('div', { class: 'toast', role: 'status' }, text);
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => leave(t), 3500);
}
/** 1 poză, 3 poze, 20 de poze — sau 1 photo, 3 photos. */
function plural(n, one, many, enOne, enMany) {
  if (LANG !== 'ro') return n === 1 ? `1 ${enOne}` : `${n.toLocaleString('en-US')} ${enMany}`;
  const num = n.toLocaleString('ro-RO');
  if (n === 1) return `1 ${one}`;
  const r = n % 100;
  return n === 0 || (r >= 1 && r <= 19) ? `${num} ${many}` : `${num} de ${many}`;
}
/** „5 martie 2025” / „March 5, 2025”; anul doar dacă [withYear]. */
function dayMonth(d, m, y, withYear = true) {
  if (LANG === 'ro') return `${d} ${MONTHS[m - 1]}${withYear ? ` ${y}` : ''}`;
  return `${MONTHS[m - 1]} ${d}${withYear ? `, ${y}` : ''}`;
}
function parseTaken(s) {  // „2025-04-05 14:30:00”, oră locală
  const [d, t = '00:00:00'] = s.split(' ');
  const [y, m, day] = d.split('-').map(Number);
  const [hh, mm] = t.split(':').map(Number);
  return { y, m, d: day, hh, mm, date: new Date(y, m - 1, day) };
}
function monthLabel(s) {
  const t = parseTaken(s);
  const name = MONTHS[t.m - 1];
  return name[0].toUpperCase() + name.slice(1) + (t.y !== new Date().getFullYear() ? ` ${t.y}` : '');
}
function dayLabel(s) {
  const t = parseTaken(s);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((today - t.date) / 86400000);
  if (diff === 0) return tr('Azi', 'Today');
  if (diff === 1) return tr('Ieri', 'Yesterday');
  const name = DAYS[t.date.getDay()];
  return `${name[0].toUpperCase()}${name.slice(1)}, ${dayMonth(t.d, t.m, t.y, t.y !== today.getFullYear())}`;
}
function fullDate(s) {
  const t = parseTaken(s);
  return `${dayMonth(t.d, t.m, t.y)}, ${String(t.hh).padStart(2, '0')}:${String(t.mm).padStart(2, '0')}`;
}
const thumb = (id, size = 256) => `/api/assets/${id}/thumb?size=${size}`;

// ---------- API ----------
class ApiError extends Error {
  constructor(status, body) { super(body?.error || `${tr('Eroare', 'Error')} ${status}`); this.status = status; this.body = body; }
}
async function api(path, { method = 'GET', json, body, headers = {} } = {}) {
  // serverul trimite mesajele de eroare în limba paginii
  const opts = { method, headers: { 'Accept-Language': LANG, ...headers }, credentials: 'same-origin' };
  if (method !== 'GET') opts.headers['X-Poze'] = '1';
  if (json !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(json); }
  else if (body !== undefined) opts.body = body;
  const r = await fetch(path, opts);
  if (r.status === 204) return null;
  const data = await r.json().catch(() => null);
  if (r.status === 401 && path !== '/api/web/login') { showLogin(); throw new ApiError(401, data); }
  if (!r.ok) throw new ApiError(r.status, data);
  return data;
}

// ---------- starea ----------
const state = { user: null, albums: null };

// ---------- logarea ----------
function showLogin() {
  state.user = null;
  selectionCleanup?.(); selectionCleanup = null;
  uploads.reset();
  const err = h('p', { class: 'error', role: 'alert' });
  const user = h('input', { name: 'user', autocomplete: 'username', required: true, autocapitalize: 'none', spellcheck: 'false' });
  const pass = h('input', { name: 'password', type: 'password', autocomplete: 'current-password', required: true });
  try { user.value = localStorage.getItem('ultimul_user') || ''; } catch { /* fără stocare */ }
  const eye = iconBtn('eye', tr('Arată parola', 'Show password'), () => {
    const show = pass.type === 'password';
    pass.type = show ? 'text' : 'password';
    eye.replaceChildren(icon(show ? 'eyeOff' : 'eye'));
    eye.title = show ? tr('Ascunde parola', 'Hide password') : tr('Arată parola', 'Show password');
    eye.setAttribute('aria-label', eye.title);
    eye.setAttribute('aria-pressed', String(show));
  });
  const otp = h('input', { name: 'otp', inputmode: 'numeric', autocomplete: 'one-time-code', pattern: '[0-9]{6}', maxlength: '6' });
  const otpField = h('label', { class: 'field hidden' }, h('span', {}, tr('Codul de 6 cifre din aplicația de autentificare', 'The 6-digit code from your authenticator app')), otp);
  const go = h('button', { class: 'btn', type: 'submit' }, tr('Intră', 'Sign in'));
  const form = h('form', {
    async onsubmit(e) {
      e.preventDefault();
      err.textContent = '';
      go.disabled = true;
      try {
        const body = { user: user.value.trim(), password: pass.value, device: 'web' };
        if (!otpField.classList.contains('hidden')) body.otp = otp.value.trim();
        const r = await api('/api/web/login', { method: 'POST', json: body });
        state.user = r.user;
        setPref('ultimul_user', body.user);
        startApp();
      } catch (ex) {
        if (ex.body?.need_otp) {
          otpField.classList.remove('hidden');
          otp.focus();
        } else {
          err.textContent = ex.status ? ex.message : tr('NAS-ul nu răspunde. Verifică legătura.', "The NAS isn't answering. Check your connection.");
        }
      } finally {
        go.disabled = false;
      }
    },
  },
    h('img', { src: 'icon.svg', alt: '' }),
    h('h1', {}, 'Amintiri'),
    h('p', {}, tr('Intră cu contul de pe NAS.', 'Sign in with your NAS account.')),
    h('label', { class: 'field' }, h('span', {}, tr('Utilizator', 'User name')), user),
    h('label', { class: 'field' }, h('span', {}, tr('Parolă', 'Password')), h('div', { class: 'pw' }, pass, eye)),
    otpField, err, go,
  );
  // telefonul care încă n-are aplicația o ia de aici, înainte de logare
  const apkLink = h('a', { class: 'btn tonal apk hidden', href: '/api/app/apk', download: 'amintiri.apk' },
    icon('download'), h('span', {}, tr('Descarcă aplicația Android', 'Download the Android app')));
  api('/api/app/latest').then((r) => {
    apkLink.href = r.url;
    apkLink.lastChild.textContent = `${tr('Descarcă aplicația Android', 'Download the Android app')} ${r.version_name}`;
    apkLink.classList.remove('hidden');
  }).catch(() => {});
  // alegerea limbii, chiar pe pagina de logare: numele limbii în limba ei
  const other = LANG === 'ro' ? 'en' : 'ro';
  const langLink = h('button', { class: 'btn text lang', type: 'button', onclick: () => setLang(other) },
    icon('language'), LANG_CHOICES[other]);
  $app().replaceChildren(h('div', { class: 'login' }, form, apkLink, langLink, h('small', { class: 'copy' }, COPYRIGHT)));
  document.title = 'Amintiri';
  (user.value ? pass : user).focus();
}

// ---------- cadrul ----------
const ROUTES = [
  { re: /^#?\/?$/, tab: 'poze', render: renderTimeline },
  { re: /^#\/albume$/, tab: 'albume', render: renderAlbums },
  { re: /^#\/album\/(\d+)$/, tab: 'albume', render: renderAlbum },
  { re: /^#\/locuri$/, tab: 'locuri', render: renderPlaces },
  { re: /^#\/loc\/(\d+)$/, tab: 'locuri', render: renderPlace },
  { re: /^#\/cauta(?:\/(.+))?$/, tab: null, render: renderSearch },
];
let main;
let navLinks;
let renderToken = 0;
let selectionCleanup = null;  // bara „N alese” a grilei de pe ecranul curent

function startApp() {
  main = h('main', { id: 'continut' });
  const sections = [['poze', '#/', tr('Poze', 'Photos'), 'photo'], ['albume', '#/albume', tr('Albume', 'Albums'), 'album'],
    ['locuri', '#/locuri', tr('Locuri', 'Places'), 'place']];
  // aceeași secțiune apare de două ori: în antet (telefon) și în bara din stânga (calculator)
  navLinks = Object.fromEntries(sections.map(([k, href, name, ic]) =>
    [k, [h('a', { href }, name), h('a', { href, class: 'side-link' }, icon(ic), h('span', {}, name))]]));
  const picker = h('input', {
    type: 'file', multiple: true, accept: 'image/*,video/*,.heic,.heif,.dng', class: 'hidden',
    onchange() { uploads.add([...picker.files]); picker.value = ''; },
  });
  let menu = null;
  const signOut = async () => {
    try { await api('/api/logout', { method: 'POST' }); } catch { /* deja ieșit */ }
    showLogin();
  };
  // spațiul: cât ocupă pozele tale și cât mai e liber pe NAS (o bară, ca la Google)
  const storage = h('div', { class: 'storage', hidden: true });
  api('/api/stats').then((r) => {
    if (r.total_bytes == null) return;
    const used = r.total_bytes - r.free_bytes;
    const bar = h('div', { class: 'meter' }, h('i'), h('b'));
    bar.firstChild.style.width = `${Math.max(1, (used / r.total_bytes) * 100)}%`;
    bar.lastChild.style.width = `${Math.max(0.5, (r.bytes / r.total_bytes) * 100)}%`;
    storage.replaceChildren(
      h('div', { class: 'storage-title' }, icon('cloud'), tr('Spațiu pe NAS', 'NAS storage')), bar,
      h('div', { class: 'storage-text' }, `${tr('Pozele tale', 'Your photos')}: ${gb(r.bytes)}`),
      h('div', { class: 'storage-text' }, `${tr('Liber', 'Free')}: ${gb(r.free_bytes)} ${tr('din', 'of')} ${gb(r.total_bytes)}`));
    storage.hidden = false;
  }).catch(() => {});
  let apk = null;  // ultimul APK publicat, pentru telefoanele care încă n-au aplicația
  api('/api/app/latest').then((r) => { apk = r; }).catch(() => {});
  function toggleMenu(e, fromSide) {
    e.stopPropagation();
    if (menu) { menu.remove(); menu = null; return; }
    menu = h('div', { class: `menu${fromSide ? ' from-side' : ''}`, role: 'menu' },
      h('div', { class: 'who' }, `${tr('Conectat ca', 'Signed in as')} ${state.user}`),
      apk && h('a', { class: 'btn text', role: 'menuitem', href: apk.url, download: 'amintiri.apk' },
        icon('download'), `${tr('Aplicația Android', 'Android app')} ${apk.version_name}`),
      h('div', { class: 'langs', role: 'group', 'aria-label': tr('Limba', 'Language') },
        icon('language'),
        Object.entries(LANG_CHOICES).map(([k, name]) => h('button', {
          class: 'btn text', type: 'button', role: 'menuitemradio', 'aria-checked': String(langChoice() === k),
          onclick: () => setLang(k),
        }, name || tr('Automat', 'Automatic')))),
      storage.hidden || fromSide ? null : storage.cloneNode(true),  // în bara din stânga se vede deja
      h('button', { class: 'btn text', role: 'menuitem', type: 'button', onclick: signOut }, tr('Ieși din cont', 'Sign out')),
      h('div', { class: 'who copy' }, COPYRIGHT, h('br'),
        h('a', { href: 'mailto:office@servicegsm.eu?subject=Amintiri' }, 'office@servicegsm.eu')));
    document.body.append(menu);
    document.addEventListener('click', () => { menu?.remove(); menu = null; }, { once: true });
  }
  const avatar = h('button', {
    class: 'avatar', type: 'button', 'aria-label': tr('Contul tău', 'Your account'), 'aria-haspopup': 'true',
    onclick: (e) => toggleMenu(e, false),
  }, (state.user || '?')[0].toUpperCase());
  const header = h('header', { class: 'top' },
    h('a', { class: 'brand', href: '#/', 'aria-label': tr('Amintiri, acasă', 'Amintiri, home') }, h('img', { src: 'icon.svg', alt: '' }), h('span', {}, 'Amintiri')),
    h('nav', { class: 'tabs', 'aria-label': tr('Secțiuni', 'Sections') }, Object.values(navLinks).map((l) => l[0])),
    h('a', { class: 'icon-btn', href: '#/cauta', 'aria-label': tr('Caută', 'Search'), title: tr('Caută', 'Search') }, icon('search')),
    h('button', { class: 'btn', type: 'button', onclick: () => picker.click() }, icon('upload'), h('span', {}, tr('Încarcă', 'Upload'))),
    avatar, picker,
  );
  // bara din stânga, pe calculator: secțiunile, încărcarea, filtrul, spațiul și contul jos
  kindButtons = Object.entries(KINDS).map(([k, name]) => h('button', {
    type: 'button', role: 'radio', class: 'side-link', 'data-kind': k,
    onclick() {
      setPref('tip', k);
      if ((location.hash || '#/') === '#/') route(); else location.hash = '#/';
    },
  }, icon({ '': 'all', photo: 'photo', video: 'video' }[k]), h('span', {}, name)));
  const side = h('aside', { class: 'side', 'aria-label': tr('Meniu', 'Menu') },
    h('nav', { 'aria-label': tr('Secțiuni', 'Sections') }, Object.values(navLinks).map((l) => l[1])),
    h('button', { class: 'btn side-upload', type: 'button', onclick: () => picker.click() }, icon('upload'), tr('Încarcă', 'Upload')),
    h('div', { class: 'side-group', role: 'radiogroup', 'aria-label': tr('Arată', 'Show') },
      h('div', { class: 'side-label' }, tr('Arată', 'Show')), kindButtons),
    h('div', { class: 'side-fill' }),
    storage,
    h('div', { class: 'side-account' },
      h('button', { class: 'side-me', type: 'button', 'aria-haspopup': 'true', 'aria-label': tr('Contul tău: limba, aplicația Android', 'Your account: language, Android app'),
        onclick: (e) => toggleMenu(e, true) },
        h('span', { class: 'avatar small', 'aria-hidden': 'true' }, (state.user || '?')[0].toUpperCase()),
        h('span', { class: 'side-who' }, h('small', {}, tr('Conectat ca', 'Signed in as')), h('strong', {}, state.user))),
      iconBtn('logout', tr('Ieși din cont', 'Sign out'), signOut)),
    h('div', { class: 'side-copy' }, COPYRIGHT));
  $app().replaceChildren(header, side, main);
  route();
}
let kindButtons = [];
function gb(b) {
  const v = b >= 1e12 ? [b / 1e12, 'TB'] : b >= 1e9 ? [b / 1e9, 'GB'] : [Math.max(0.1, b / 1e6), 'MB'];
  const n = v[0].toFixed(v[0] >= 100 ? 0 : 1);
  return `${LANG === 'ro' ? n.replace('.', ',') : n} ${v[1]}`;
}

function route() {
  if (!state.user) return;
  const hash = location.hash || '#/';
  for (const r of ROUTES) {
    const m = hash.match(r.re);
    if (m) {
      for (const [k, links] of Object.entries(navLinks)) for (const a of links) {
        if (k === r.tab) a.setAttribute('aria-current', 'page');
        else a.removeAttribute('aria-current');
      }
      const kind = getPref('tip', KINDS, '');
      for (const b of kindButtons) b.setAttribute('aria-checked', String(r.tab === 'poze' && b.dataset.kind === kind));
      const token = ++renderToken;
      selectionCleanup?.(); selectionCleanup = null;
      main.replaceChildren();
      window.scrollTo(0, 0);
      // pagina nouă intră ușor de jos în sus
      if (!calm() && main.animate) {
        main.animate([{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'none' }],
          { duration: 280, easing: EASE_OUT });
      }
      r.render(token, ...m.slice(1)).catch((e) => {
        if (token === renderToken && e.status !== 401) main.replaceChildren(h('div', { class: 'empty' }, h('strong', {}, tr('Nu s-a putut încărca.', "Couldn't load.")), e.message));
      });
      return;
    }
  }
  location.hash = '#/';
}
window.addEventListener('hashchange', route);

// ---------- grila paginată ----------
/** Desenează o cronologie paginată din [url]; grupează pe zile. Întoarce o funcție de reîmprospătare. */
function photoFeed(container, url, token, { emptyText = tr('Nicio poză încă.', 'No photos yet.'), emptyHint = tr('Apasă „Încarcă” sau trage poze aici.', 'Press "Upload" or drop photos here.'), onItems, group = getGroup(), start = null } = {}) {
  // [start] = cursor de unde pornește lista (saltul din bara cu anii); atunci se încarcă și în sus.
  // Fiecare poză are un număr fix (seq): crește în jos, iar cele adăugate deasupra primesc numere negative,
  // ca alegerea și vizualizatorul să nu se încurce când lista crește în sus.
  const items = [];  // în ordinea de pe ecran: items[seq - minSeq]
  const bySeq = new Map();  // seq → { a, tile, check }
  let minSeq = 0, maxSeq = -1;
  const selected = new Set();  // seq-uri
  let anchor = null;  // ultima poză aleasă, pentru Shift+clic
  let next = start ?? undefined;
  let prev = start ? start : null;
  let busy = false;
  let lastDay = null, grid = null;  // ultima secțiune (jos)
  let firstDay = null, firstGrid = null, firstSection = null;  // prima secțiune (sus)
  const sentinel = h('div', { class: 'sentinel' });
  const loading = h('div', { class: 'loading' }, tr('Se încarcă…', 'Loading…'));
  const topSentinel = h('div', { class: 'sentinel' });
  container.append(sentinel, loading);
  if (start) {
    container.prepend(topSentinel);
    container.style.overflowAnchor = 'none';  // ținem ecranul pe loc noi, la fel în toate browserele
  }

  // la derulare repede, pozele peste care ai trecut își anulează cererea: altfel serverul
  // le face pe toate, la rând, înaintea celor la care te-ai oprit
  const lazy = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const img = e.target;
      if (e.isIntersecting) img.src = img.dataset.src;
      else if (!img.complete) img.removeAttribute('src');
    }
  }, { rootMargin: '400px' });

  const section = (a, g) => h('section', { class: 'day month', 'data-t': a.taken_at }, h('h3', {}, GROUPS[group].label(a.taken_at)), g);
  function add(batch) {
    for (const a of batch) {
      const seq = ++maxSeq;
      items.push(a);
      const key = a.taken_at.slice(0, GROUPS[group].len);
      if (key !== lastDay) {
        lastDay = key;
        grid = h('div', { class: `grid g-${group}` });
        const sec = section(a, grid);
        container.insertBefore(sec, sentinel);
        if (!firstSection) { firstSection = sec; firstDay = key; firstGrid = grid; }
      }
      grid.append(makeTile(a, seq));
    }
    onItems?.(items);
  }
  /** Pozele mai noi, deasupra; [batch] vine cea mai nouă prima, toate mai noi decât prima de pe ecran. */
  function prepend(batch) {
    const ref = firstSection;
    const y0 = ref?.getBoundingClientRect().top;
    for (const a of [...batch].reverse()) {
      const seq = --minSeq;
      items.unshift(a);
      const key = a.taken_at.slice(0, GROUPS[group].len);
      if (key !== firstDay) {
        firstDay = key;
        firstGrid = h('div', { class: `grid g-${group}` });
        const sec = section(a, firstGrid);
        container.insertBefore(sec, firstSection ?? sentinel);
        firstSection = sec;
        if (!lastDay) { lastDay = key; grid = firstGrid; }
      } else {
        firstSection.dataset.t = a.taken_at;
      }
      firstGrid.prepend(makeTile(a, seq));
    }
    // ce era pe ecran rămâne pe loc; pozele noi apar deasupra, de unde le vezi derulând în sus
    if (ref) window.scrollBy(0, ref.getBoundingClientRect().top - y0);
    onItems?.(items);
  }
  function makeTile(a, seq) {
    const img = h('img', { alt: '', 'data-src': thumb(a.id), decoding: 'async', onload() { this.classList.add('on'); lazy.unobserve(this); } });
    lazy.observe(img);
    const what = a.kind === 'video' ? tr('Clip', 'Video') : tr('Poză', 'Photo');
    const from = `${what} ${tr('din', 'from')} ${fullDate(a.taken_at)}`;
    const check = h('button', {
      class: 'check', type: 'button', role: 'checkbox', 'aria-checked': 'false', 'aria-label': `${tr('Alege', 'Select')}: ${from}`,
      onclick(e) { select(seq, e.shiftKey); },
    }, icon('check'));
    let pressed = null;  // apăsare lungă pe telefon = alege
    let longDone = false;
    const open = h('button', {
      class: 'open', type: 'button', 'aria-label': from,
      onclick(e) {
        if (longDone) { longDone = false; return; }
        if (selected.size || e.shiftKey || e.ctrlKey || e.metaKey) select(seq, e.shiftKey);
        else openViewer(items, seq - minSeq, { onChange: refresh, thumbOf: (k) => bySeq.get(k + minSeq)?.tile.querySelector('img') });
      },
      onpointerdown(e) {
        if (e.pointerType !== 'touch') return;
        pressed = setTimeout(() => { longDone = true; select(seq, false); navigator.vibrate?.(20); }, 450);
      },
      onpointerup() { clearTimeout(pressed); },
      onpointercancel() { clearTimeout(pressed); },
      onpointermove() { clearTimeout(pressed); },
      oncontextmenu(e) { if (e.pointerType === 'touch' || longDone) e.preventDefault(); },
    }, img, a.kind === 'video' ? h('span', { class: 'badge' }, icon('play'), a.duration_ms ? duration(a.duration_ms) : '') : null);
    const tile = h('div', { class: 'tile' }, open, check);
    // rânduri ca la Google: fiecare poză cu forma ei (CSS-ul folosește --r doar la Zile/Luni)
    const r = a.width && a.height ? Math.min(2.5, Math.max(0.5, a.width / a.height)) : 1;
    tile.style.setProperty('--r', r.toFixed(3));
    bySeq.set(seq, { a, tile, check });
    return tile;
  }

  async function newer() {
    if (busy || !prev || token !== renderToken) return;
    busy = true;
    try {
      const sep = url.includes('?') ? '&' : '?';
      const first = items[0];
      const cursor = first ? `${first.taken_at}|${first.id}` : prev;
      const page = await api(`${url}${sep}limit=200&after=${encodeURIComponent(cursor)}`);
      if (token !== renderToken) return;
      prepend(page.items);
      prev = page.prev;
      if (!prev) { topIo.disconnect(); topSentinel.remove(); }
    } finally {
      busy = false;
    }
  }
  const topIo = new IntersectionObserver((e) => { if (e[0].isIntersecting) newer(); }, { rootMargin: '800px' });

  async function more() {
    if (busy || next === null || token !== renderToken) return;
    busy = true;
    try {
      const sep = url.includes('?') ? '&' : '?';
      const page = await api(`${url}${sep}limit=200${next ? `&before=${encodeURIComponent(next)}` : ''}`);
      if (token !== renderToken) return;
      const firstPage = !items.length;
      add(page.items);
      next = page.next;
      // după un salt: luna aleasă sus pe ecran, abia apoi pornim încărcarea în sus
      if (start && firstPage) {
        firstSection?.scrollIntoView({ block: 'start' });
        requestAnimationFrame(() => topIo.observe(topSentinel));
      }
      if (next === null) {
        loading.remove();
        io.disconnect();
        if (!items.length) container.append(h('div', { class: 'empty' }, h('strong', {}, emptyText), emptyHint));
      }
    } finally {
      busy = false;
    }
    // ecran mare, pagină scurtă: cere încă una fără să aștepte derularea
    if (next && sentinel.getBoundingClientRect().top < innerHeight + 600) more();
  }
  const io = new IntersectionObserver((e) => { if (e[0].isIntersecting) more(); }, { rootMargin: '1200px' });
  io.observe(sentinel);

  function select(seq, range) {
    const on = !selected.has(seq);
    const span = range && anchor !== null ? [Math.min(anchor, seq), Math.max(anchor, seq)] : [seq, seq];
    for (let k = span[0]; k <= span[1]; k++) {
      const t = bySeq.get(k);
      if (!t) continue;
      if (on) selected.add(k); else selected.delete(k);
      t.tile.classList.toggle('picked', on);
      t.check.setAttribute('aria-checked', String(on));
    }
    anchor = seq;
    showBar();
  }
  function clear() {
    for (const k of selected) { const t = bySeq.get(k); t.tile.classList.remove('picked'); t.check.setAttribute('aria-checked', 'false'); }
    selected.clear();
    anchor = null;
    showBar();
  }
  const count = h('strong', {});
  const inAlbum = location.hash.startsWith('#/album/') ? viewerAlbum : null;
  const picked = () => [...selected].sort((x, y) => x - y).map((k) => bySeq.get(k).a);
  const bar = h('div', { class: 'selbar', role: 'toolbar', 'aria-label': tr('Pozele alese', 'Selected photos') },
    iconBtn('close', tr('Renunță (Esc)', 'Cancel (Esc)'), clear), count, h('span', { class: 'spacer' }),
    iconBtn('addAlbum', tr('Adaugă în album', 'Add to album'), async () => { if (await pickAlbum(picked().map((a) => a.sha256))) clear(); }),
    iconBtn('download', tr('Descarcă originalele', 'Download originals'), () => {
      const list = picked();
      // pe rând: browserul poate întreba o dată dacă lasă site-ul să descarce mai multe fișiere
      list.forEach((a, n) => setTimeout(() => {
        const link = h('a', { href: `/api/assets/${a.id}/original`, download: '' });
        document.body.append(link); link.click(); link.remove();
      }, n * 400));
      toast(`${tr('Se descarcă', 'Downloading')} ${plural(list.length, 'fișier', 'fișiere', 'file', 'files')}`);
    }),
    inAlbum ? iconBtn('remove', tr('Scoate din album', 'Remove from album'), async () => {
      const list = picked();
      await api(`/api/albums/${inAlbum.id}/items`, { method: 'DELETE', json: { sha256: list.map((a) => a.sha256) } });
      state.albums = null;
      toast(`${plural(list.length, 'poză scoasă', 'poze scoase', 'photo removed', 'photos removed')} ${tr('din album', 'from the album')}`);
      refresh();
    }) : null,
    iconBtn('delete', tr('Șterge de pe NAS', 'Delete from the NAS'), async () => {
      const list = picked();
      const what = plural(list.length, 'poză', 'poze', 'photo', 'photos');
      if (!await confirmBox(tr(`Ștergi ${what} de pe NAS?`, `Delete ${what} from the NAS?`),
        tr('Ajung în coșul NAS-ului pentru 30 de zile, de unde le poți recupera din aplicație.',
          "They go to the NAS trash for 30 days; you can restore them from the app."), tr('Șterge', 'Delete'))) return;
      bar.classList.add('busy');
      let n = 0;
      try {
        for (const a of list) {
          count.textContent = tr(`Se șterg… ${n} din ${list.length}`, `Deleting… ${n} of ${list.length}`);
          await api(`/api/assets/${a.id}`, { method: 'DELETE' });
          n++;
        }
      } finally { bar.classList.remove('busy'); }
      toast(`${plural(n, 'poză ștearsă', 'poze șterse', 'photo deleted', 'photos deleted')}${tr(' de pe NAS. Le găsești 30 de zile în Coș, în aplicație.', '. They stay in the Trash in the app for 30 days.')}`);
      refresh();
    }));
  function showBar() {
    if (!selected.size) { bar.remove(); document.body.classList.remove('selecting'); return; }
    count.textContent = plural(selected.size, 'aleasă', 'alese', 'selected', 'selected');
    document.body.classList.add('selecting');
    if (!bar.isConnected) document.body.append(bar);
  }
  selectionCleanup = () => { bar.remove(); document.body.classList.remove('selecting'); };
  const onKey = (e) => { if (e.key === 'Escape' && selected.size && !document.querySelector('.viewer, dialog[open]')) clear(); };
  document.addEventListener('keydown', onKey);
  const prevCleanup = selectionCleanup;
  selectionCleanup = () => { prevCleanup(); document.removeEventListener('keydown', onKey); };

  function refresh() { if (token === renderToken) route(); }
  return { refresh, items };
}
function duration(ms) {
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// ---------- ecranele ----------
async function renderTimeline(token) {
  document.title = 'Amintiri';
  const mem = h('div', { class: 'memories', 'aria-label': tr('În ziua asta, în alți ani', 'On this day, in other years') });
  main.append(mem);
  const now = new Date();
  const iso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  api(`/api/memories?date=${iso}`).then((r) => {
    if (token !== renderToken) return;
    for (const y of r.years) {
      if (!y.items.length) continue;
      const label = y.years_ago === 1 ? tr('Acum un an', 'A year ago')
        : tr(`Acum ${plural(y.years_ago, 'an', 'ani')}`, `${y.years_ago} years ago`);
      mem.append(h('button', {
        class: 'memory', type: 'button', 'aria-label': `${label}, ${plural(y.items.length, 'poză', 'poze', 'photo', 'photos')}`,
        onclick: () => openViewer(y.items, 0),
      }, h('img', { src: thumb(y.items[0].id, 1024), alt: '' }), h('span', {}, label)));
    }
    if (mem.childElementCount) mem.before(h('h2', { class: 'title' }, tr('În ziua asta', 'On this day')));
  }).catch(() => {});
  const group = getGroup();
  const kind = getPref('tip', KINDS, '');
  const seg = (label, choices, current, pick, cls = '') => h('div', { class: `seg ${cls}`, role: 'radiogroup', 'aria-label': label },
    Object.entries(choices).map(([k, name]) => h('button', {
      type: 'button', role: 'radio', 'aria-checked': String(k === current),
      onclick() { if (k !== current) { pick(k); route(); } },
    }, name)));
  main.append(h('div', { class: 'toolbar' },
    seg(tr('Arată', 'Show'), KINDS, kind, (k) => setPref('tip', k), 'kind'),
    seg(tr('Grupează pozele pe', 'Group photos by'), Object.fromEntries(Object.entries(GROUPS).map(([g, v]) => [g, v.name])), group, setGroup)));
  const feed = h('div');
  main.append(feed);
  const start = timelineJump;
  timelineJump = null;
  photoFeed(feed, kind ? `/api/assets?kind=${kind}` : '/api/assets', token, {
    group, start: start && monthCursor(start),
    emptyText: kind === 'video' ? tr('Niciun clip încă.', 'No videos yet.') : tr('Nicio poză încă.', 'No photos yet.'),
  });
  yearRail(token, feed, kind);
}

// ---------- bara cu anii (dreapta, pe calculator) ----------
let timelineJump = null;  // luna „2016-03” aleasă din bară; renderTimeline pornește de acolo
/** Cursorul care începe lista cu cea mai nouă poză din luna [m]: tot ce e înainte de luna următoare. */
function monthCursor(m) {
  let [y, mo] = m.split('-').map(Number);
  if (++mo > 12) { mo = 1; y++; }
  return `${y}-${String(mo).padStart(2, '0')}-01 00:00:00|0`;
}
/**
 * Ca în Google Photos: anii pe marginea din dreapta, așezați după câte poze are fiecare.
 * La trecerea mouse-ului arată luna de sub cursor; clic = sari acolo. Doar cu mouse (hover).
 */
async function yearRail(token, feed, kind) {
  if (!matchMedia('(hover: hover) and (pointer: fine)').matches) return;
  const { months } = await api(`/api/assets/months${kind ? `?kind=${kind}` : ''}`);
  if (token !== renderToken || months.length < 2) return;
  const total = months.reduce((n, m) => n + m.count, 0);
  let acc = 0;
  const spans = months.map((m) => { const top = acc / total; acc += m.count; return { ...m, top, bottom: acc / total }; });
  const at = (f) => spans.find((m) => f < m.bottom) ?? spans[spans.length - 1];
  const tip = h('div', { class: 'rail-tip' });
  const marker = h('div', { class: 'rail-marker' });
  const years = h('div', { class: 'rail-years' });
  const rail = h('nav', { class: 'rail', 'aria-label': tr('Sari la un an', 'Jump to a year') }, years, marker, tip);
  // un an = prima lui lună (cea mai nouă); etichetele prea apropiate se sar
  function drawYears() {
    years.replaceChildren();
    const hgt = rail.clientHeight;
    let last = -99;
    for (const m of spans) {
      const y = m.month.slice(0, 4);
      if (m !== spans.find((x) => x.month.startsWith(y))) continue;
      const px = m.top * hgt;
      if (px - last < 22) continue;
      last = px;
      const b = h('button', { type: 'button', onclick: () => jump(m.month) }, y);
      b.style.top = `${px}px`;  // CSP-ul nu lasă atributul style, dar lasă CSSOM
      years.append(b);
    }
  }
  function jump(month) {
    // deja încărcată? doar derulăm până la ea
    const secs = [...feed.querySelectorAll('section.day')];
    const ms = month + '-99';
    const hit = secs.find((sec) => sec.dataset.t <= ms);
    const loaded = secs.length && hit && secs[secs.length - 1].dataset.t.slice(0, 7) <= month && secs[0].dataset.t.slice(0, 7) >= month;
    if (loaded) { hit.scrollIntoView({ block: 'start', behavior: calm() ? 'auto' : 'smooth' }); return; }
    timelineJump = month;
    route();
  }
  rail.addEventListener('pointermove', (e) => {
    const r = rail.getBoundingClientRect();
    const f = Math.min(Math.max((e.clientY - r.top) / r.height, 0), 0.9999);
    tip.textContent = monthLabel(`${at(f).month}-01`);
    tip.style.top = `${e.clientY - r.top}px`;
    rail.classList.add('hover');
  });
  rail.addEventListener('pointerleave', () => rail.classList.remove('hover'));
  rail.addEventListener('click', (e) => {
    if (e.target.closest('button')) return;
    const r = rail.getBoundingClientRect();
    jump(at(Math.min(Math.max((e.clientY - r.top) / r.height, 0), 0.9999)).month);
  });
  // unde ești acum: prima secțiune care încă se vede sub antet
  let raf = 0;
  function place() {
    raf = 0;
    const sec = [...feed.querySelectorAll('section.day')].find((x) => x.getBoundingClientRect().bottom > 80);
    if (!sec) return;
    const m = spans.find((x) => x.month === sec.dataset.t.slice(0, 7));
    if (m) marker.style.top = `${m.top * rail.clientHeight}px`;
  }
  const onScroll = () => { if (!raf) raf = requestAnimationFrame(place); };
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', drawYears);
  document.body.append(rail);
  document.body.classList.add('has-rail');
  drawYears();
  place();
  const prevCleanup = selectionCleanup;
  selectionCleanup = () => {
    prevCleanup?.();
    rail.remove();
    document.body.classList.remove('has-rail');
    removeEventListener('scroll', onScroll);
    removeEventListener('resize', drawYears);
  };
}

// lumina care urmează mouse-ul pe poze (o singură ascultare pentru toată pagina)
document.addEventListener('pointermove', (e) => {
  const o = e.target.closest?.('.tile .open');
  if (!o) return;
  const r = o.getBoundingClientRect();
  o.style.setProperty('--mx', `${e.clientX - r.left}px`);
  o.style.setProperty('--my', `${e.clientY - r.top}px`);
}, { passive: true });

async function renderSearch(token, q = '') {
  q = decodeURIComponent(q).trim();
  document.title = q ? `${q} · Amintiri` : `${tr('Caută', 'Search')} · Amintiri`;
  const input = h('input', {
    type: 'search', name: 'q', value: q, placeholder: tr('Un loc, o lună, un an, un album…', 'A place, a month, a year, an album…'),
    'aria-label': tr('Caută', 'Search'), autocomplete: 'off', enterkeyhint: 'search',
  });
  const go = (v) => { v = v.trim(); if (v) location.hash = `#/cauta/${encodeURIComponent(v)}`; };
  main.append(h('form', { class: 'search', role: 'search', onsubmit(e) { e.preventDefault(); go(input.value); } },
    icon('search'), input));
  if (!q) {
    input.focus();
    const chips = h('div', { class: 'chips' }, SEARCH_EXAMPLES.map((x) => h('button', { type: 'button', class: 'chip', onclick: () => go(x) }, x)));
    main.append(h('h3', { class: 'hint' }, tr('Încearcă', 'Try')), chips);
    const sug = await api('/api/search/suggestions');
    if (token !== renderToken) return;
    if (sug.places.length) {
      main.append(h('h3', { class: 'hint' }, tr('Locuri', 'Places')), h('div', { class: 'chips' },
        sug.places.map((p) => h('button', { type: 'button', class: 'chip', onclick: () => go(p.name) }, p.name))));
    }
    if (sug.years.length) {
      main.append(h('h3', { class: 'hint' }, tr('Ani', 'Years')), h('div', { class: 'chips' },
        sug.years.map((y) => h('button', { type: 'button', class: 'chip', onclick: () => go(String(y)) }, String(y)))));
    }
    return;
  }
  const feed = h('div');
  main.append(feed);
  photoFeed(feed, `/api/search?q=${encodeURIComponent(q)}`, token, {
    emptyText: tr(`Nimic pentru „${q}”.`, `Nothing for "${q}".`),
    emptyHint: tr('Încearcă un loc, o lună („august”), un anotimp („vara 2024”) sau numele unui album.',
      'Try a place, a month ("August"), a season ("summer 2024") or an album name.'),
    group: 'zi',
  });
}

async function loadAlbums() {
  state.albums = (await api('/api/albums')).albums;
  return state.albums;
}

async function renderAlbums(token) {
  document.title = `${tr('Albume', 'Albums')} · Amintiri`;
  const albums = await loadAlbums();
  if (token !== renderToken) return;
  const cards = h('div', { class: 'cards' },
    h('button', { class: 'card new', type: 'button', onclick: () => newAlbum() },
      h('div', { class: 'cover' }, icon('addAlbum')), h('b', {}, tr('Album nou', 'New album'))),
    albums.map((a) => h('a', { class: 'card', href: `#/album/${a.id}` },
      h('div', { class: 'cover' }, a.cover_id ? h('img', { src: thumb(a.cover_id, 1024), alt: '', loading: 'lazy' }) : icon('album')),
      h('b', {}, a.name), h('small', {}, plural(a.count, 'element', 'elemente', 'item', 'items')))),
  );
  main.append(h('h2', { class: 'title' }, tr('Albume', 'Albums')), cards);
}

async function newAlbum(sha256 = []) {
  const name = await promptText(tr('Album nou', 'New album'), tr('Numele albumului', 'Album name'));
  if (!name) return null;
  const r = await api('/api/albums', { method: 'POST', json: { name, sha256 } });
  state.albums = null;
  if (!sha256.length) location.hash = `#/album/${r.album.id}`;
  return r.album;
}

async function renderAlbum(token, id) {
  const albums = state.albums || await loadAlbums();
  const album = albums.find((a) => String(a.id) === id);
  if (!album) { location.hash = '#/albume'; return; }
  document.title = `${album.name} · Amintiri`;
  const title = h('span', {}, album.name);
  main.append(h('h2', { class: 'title' },
    h('a', { href: '#/albume', class: 'icon-btn', 'aria-label': tr('Înapoi la albume', 'Back to albums') }, icon('back')), title,
    h('span', { class: 'spacer' }),
    h('button', { class: 'btn text', type: 'button', async onclick() {
      const name = await promptText(tr('Redenumește albumul', 'Rename album'), tr('Numele albumului', 'Album name'), album.name);
      if (!name || name === album.name) return;
      await api(`/api/albums/${album.id}`, { method: 'PATCH', json: { name } });
      album.name = name; title.textContent = name; state.albums = null;
    } }, tr('Redenumește', 'Rename')),
    h('button', { class: 'btn danger', type: 'button', async onclick() {
      if (!await confirmBox(tr('Ștergi albumul?', 'Delete the album?'), tr('Pozele rămân pe NAS; dispare doar albumul.',
        'The photos stay on the NAS; only the album goes.'), tr('Șterge albumul', 'Delete album'))) return;
      await api(`/api/albums/${album.id}`, { method: 'DELETE' });
      state.albums = null;
      location.hash = '#/albume';
    } }, tr('Șterge', 'Delete')),
  ));
  const feed = h('div');
  main.append(feed);
  photoFeed(feed, `/api/albums/${album.id}/assets`, token, { emptyText: tr('Albumul e gol. Adaugă poze din vizualizator.', 'The album is empty. Add photos from the viewer.') });
  viewerAlbum = album;
}

async function renderPlaces(token) {
  document.title = `${tr('Locuri', 'Places')} · Amintiri`;
  const { places } = await api('/api/places');
  if (token !== renderToken) return;
  main.append(h('h2', { class: 'title' }, tr('Locuri', 'Places')));
  if (!places.length) {
    main.append(h('div', { class: 'empty' }, h('strong', {}, tr('Niciun loc încă.', 'No places yet.')),
      tr('Apar aici pozele care au locația salvată.', 'Photos with a saved location show up here.')));
    return;
  }
  main.append(h('div', { class: 'cards' }, places.map((p) => h('a', { class: 'card', href: `#/loc/${p.id}` },
    h('div', { class: 'cover' }, h('img', { src: thumb(p.cover_id, 1024), alt: '', loading: 'lazy' })),
    h('b', {}, p.name), h('small', {}, `${placeSubtitle(p)} · ${plural(p.count, 'poză', 'poze', 'photo', 'photos')}`)))));
}
function placeSubtitle(p) { return [p.region, p.country].filter(Boolean).join(', '); }

async function renderPlace(token, id) {
  const { places } = await api('/api/places');
  const p = places.find((x) => String(x.id) === id);
  if (!p) { location.hash = '#/locuri'; return; }
  document.title = `${p.name} · Amintiri`;
  main.append(h('h2', { class: 'title' },
    h('a', { href: '#/locuri', class: 'icon-btn', 'aria-label': tr('Înapoi la locuri', 'Back to places') }, icon('back')), p.name));
  const feed = h('div');
  main.append(feed);
  photoFeed(feed, `/api/places/${p.id}/assets`, token);
}

// ---------- dialoguri ----------
function dialog(build) {
  return new Promise((resolve) => {
    const d = h('dialog');
    const done = (v) => { d.close(); d.remove(); resolve(v); };
    d.addEventListener('cancel', (e) => { e.preventDefault(); done(null); });
    d.append(...build(done));
    document.body.append(d);
    d.showModal();
  });
}
function confirmBox(title, text, yes) {
  return dialog((done) => [h('h3', {}, title), h('p', {}, text), h('div', { class: 'actions' },
    h('button', { class: 'btn text', type: 'button', onclick: () => done(false) }, tr('Anulează', 'Cancel')),
    h('button', { class: 'btn', type: 'button', onclick: () => done(true) }, yes))]);
}
function promptText(title, label, value = '') {
  return dialog((done) => {
    const input = h('input', { value, maxlength: '100', required: true });
    queueMicrotask(() => { input.focus(); input.select(); });
    return [h('form', { onsubmit(e) { e.preventDefault(); done(input.value.trim() || null); } },
      h('h3', {}, title), h('label', { class: 'field' }, h('span', {}, label), input),
      h('div', { class: 'actions' },
        h('button', { class: 'btn text', type: 'button', onclick: () => done(null) }, tr('Anulează', 'Cancel')),
        h('button', { class: 'btn', type: 'submit' }, tr('Salvează', 'Save'))))];
  });
}
async function pickAlbum(shas) {
  const what = shas.length === 1 ? tr('Adăugată', 'Added') : plural(shas.length, 'poză adăugată', 'poze adăugate', 'photo added', 'photos added');
  const albums = state.albums || await loadAlbums();
  const choice = await dialog((done) => [h('h3', {}, tr('Adaugă în album', 'Add to album')),
    h('div', { class: 'list' },
      h('button', { type: 'button', onclick: () => done('new') }, `+ ${tr('Album nou', 'New album')}`),
      albums.map((a) => h('button', { type: 'button', onclick: () => done(a) }, a.name))),
    h('div', { class: 'actions' }, h('button', { class: 'btn text', type: 'button', onclick: () => done(null) }, tr('Anulează', 'Cancel')))]);
  if (!choice) return false;
  if (choice === 'new') {
    const a = await newAlbum(shas);
    if (a) toast(tr(`${what} în „${a.name}”`, `${what} to "${a.name}"`));
    return !!a;
  }
  await api(`/api/albums/${choice.id}/items`, { method: 'POST', json: { sha256: shas } });
  state.albums = null;
  toast(tr(`${what} în „${choice.name}”`, `${what} to "${choice.name}"`));
  return true;
}

// ---------- vizualizatorul ----------
let viewerAlbum = null;  // albumul deschis, pentru „Scoate din album”
function openViewer(items, start, { onChange, thumbOf } = {}) {
  const inAlbum = location.hash.startsWith('#/album/') ? viewerAlbum : null;
  let i = start;
  let changed = false;
  const before = document.activeElement;
  const stage = h('div', { class: 'stage' });
  const when = h('div', { class: 'when', 'aria-live': 'polite' });
  const prevBtn = iconBtn('prev', tr('Poza anterioară', 'Previous photo'), () => go(-1), 'nav prev');
  const nextBtn = iconBtn('next', tr('Poza următoare', 'Next photo'), () => go(1), 'nav next');
  const dlLabel = tr('Descarcă originalul', 'Download original');
  const dl = h('a', { class: 'icon-btn', 'aria-label': dlLabel, title: dlLabel, download: '' }, icon('download'));
  const v = h('div', { class: 'viewer', role: 'dialog', 'aria-modal': 'true', 'aria-label': tr('Vizualizator', 'Viewer'), tabindex: '-1' },
    h('div', { class: 'bar' },
      iconBtn('close', tr('Închide (Esc)', 'Close (Esc)'), close), when,
      iconBtn('addAlbum', tr('Adaugă în album', 'Add to album'), () => pickAlbum([items[i].sha256])),
      inAlbum ? iconBtn('remove', tr('Scoate din album', 'Remove from album'), async () => {
        await api(`/api/albums/${inAlbum.id}/items`, { method: 'DELETE', json: { sha256: [items[i].sha256] } });
        changed = true; state.albums = null; drop(); toast(tr('Scoasă din album', 'Removed from album'));
      }) : null,
      dl,
      iconBtn('delete', tr('Șterge de pe NAS', 'Delete from the NAS'), async () => {
        if (!await confirmBox(tr('Ștergi de pe NAS?', 'Delete from the NAS?'), tr('Ajunge în coșul de reciclare al NAS-ului, de unde o poți recupera.',
          "It goes to the NAS recycle bin, where you can restore it."), tr('Șterge', 'Delete'))) return;
        await api(`/api/assets/${items[i].id}`, { method: 'DELETE' });
        changed = true; drop(); toast(tr('Ștearsă', 'Deleted'));
      })),
    stage, prevBtn, nextBtn);

  function drop() {
    items.splice(i, 1);
    if (!items.length) return close();
    i = Math.min(i, items.length - 1);
    show();
  }
  function show() {
    const a = items[i];
    const original = `/api/assets/${a.id}/original`;
    stage.replaceChildren(a.kind === 'video'
      ? h('video', { src: original, controls: true, autoplay: true, playsinline: true, poster: thumb(a.id, 1024) })
      : h('img', { src: thumb(a.id, 1024), alt: `${tr('Poză din', 'Photo from')} ${fullDate(a.taken_at)}` }));
    when.replaceChildren(h('b', {}, fullDate(a.taken_at)), h('small', {}, `${i + 1} ${tr('din', 'of')} ${items.length}`));
    dl.href = original;
    prevBtn.classList.toggle('hidden', i === 0);
    nextBtn.classList.toggle('hidden', i === items.length - 1);
    // următoarea se încarcă dinainte, ca trecerea să fie instantă
    if (items[i + 1]?.kind === 'photo') new Image().src = thumb(items[i + 1].id, 1024);
  }
  function go(d) { const n = i + d; if (n >= 0 && n < items.length) { i = n; show(); } }
  function key(e) {
    if (document.querySelector('dialog[open]')) return;
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft') go(-1);
    else if (e.key === 'ArrowRight') go(1);
  }
  let x0 = null;
  stage.addEventListener('pointerdown', (e) => { x0 = e.clientX; });
  stage.addEventListener('pointerup', (e) => {
    if (x0 != null && Math.abs(e.clientX - x0) > 60) go(e.clientX < x0 ? 1 : -1);
    x0 = null;
  });
  // poza curentă din vizualizator și miniatura ei din grilă: între ele „zboară” animația
  const big = () => stage.querySelector('img');
  const small = () => { const t = thumbOf?.(i); return t?.classList.contains('on') ? t : null; };
  function close() {
    document.removeEventListener('keydown', key);
    const done = () => {
      v.remove();
      document.body.style.overflow = '';
      before?.focus?.();
      if (changed) onChange?.();
    };
    if (changed || !thumbOf) { leave(v, [{ opacity: 1 }, { opacity: 0 }]); setTimeout(done, calm() ? 0 : 170); return; }
    small()?.scrollIntoView({ block: 'nearest' });
    morph(done, big(), small);
  }
  document.addEventListener('keydown', key);
  morph(() => {
    document.body.style.overflow = 'hidden';
    document.body.append(v);
    show();
  }, small(), big).then(() => v.focus());
}

// ---------- încărcarea ----------
const uploads = (() => {
  const queue = [];
  let running = 0;
  let panel = null;
  let list, bar, title, sub, toggle;
  let addedAny = false;

  function ensurePanel() {
    if (panel) return;
    list = h('ul');
    bar = h('progress', { max: '1', value: '0' });
    title = h('b');
    sub = h('small');
    toggle = iconBtn('collapse', tr('Ascunde lista', 'Hide the list'), () => {
      list.classList.toggle('hidden');
      toggle.replaceChildren(icon(list.classList.contains('hidden') ? 'expand' : 'collapse'));
    });
    panel = h('section', { class: 'uploads', 'aria-label': tr('Încărcări', 'Uploads'), 'aria-live': 'polite' },
      h('div', { class: 'head' }, h('div', {}, title, sub), toggle,
        iconBtn('close', tr('Închide', 'Close'), () => {
          if (!running && !queue.some((j) => !j.final)) { panel.remove(); panel = null; queue.length = 0; }
          else toast(tr('Se mai încarcă. Așteaptă să termine.', 'Still uploading. Wait for it to finish.'));
        })),
      bar, list);
    document.body.append(panel);
  }

  function summary() {
    const total = queue.length;
    const done = queue.filter((j) => j.final).length;
    const bytes = queue.reduce((s, j) => s + j.file.size, 0) || 1;
    const sent = queue.reduce((s, j) => s + (j.final ? j.file.size : j.sent), 0);
    bar.value = sent / bytes;
    const errors = queue.filter((j) => j.state === 'err').length;
    if (done === total) {
      title.textContent = errors ? `${tr('Gata, cu', 'Done, with')} ${plural(errors, 'eroare', 'erori', 'error', 'errors')}`
        : tr('Totul e pe NAS', 'Everything is on the NAS');
      const fresh = queue.filter((j) => j.state === 'done').length;
      const dup = queue.filter((j) => j.state === 'dup').length;
      sub.textContent = [fresh && plural(fresh, 'încărcată', 'încărcate', 'uploaded', 'uploaded'),
        dup && (LANG === 'ro' ? (dup === 1 ? '1 era deja' : plural(dup, 'era deja', 'erau deja')) : `${dup} already there`)].filter(Boolean).join(' · ');
      if (addedAny && location.hash.replace(/^#\/?$/, '') === '') { addedAny = false; route(); }
    } else {
      title.textContent = tr(`Se încarcă ${done + 1} din ${total}`, `Uploading ${done + 1} of ${total}`);
      sub.textContent = `${mb(sent)} ${tr('din', 'of')} ${mb(bytes)}`;
    }
  }
  const dec = (s) => (LANG === 'ro' ? s.replace('.', ',') : s);
  function mb(b) { return b >= 1e9 ? `${dec((b / 1e9).toFixed(1))} GB` : `${dec(Math.max(0.1, b / 1e6).toFixed(1))} MB`; }

  function setState(j, st, text) {
    j.state = st;
    j.final = ['done', 'dup', 'err'].includes(st);
    j.li.className = st;
    j.em.textContent = text;
    if (j.final) j.prog.remove();
    summary();
  }

  async function withRetry(fn) {
    for (let attempt = 0; ; attempt++) {
      try { return await fn(); } catch (e) {
        if (e.status && e.status < 500 && e.status !== 408 && e.status !== 429) throw e;
        if (attempt >= 4) throw e;
        await new Promise((r) => setTimeout(r, 1000 * 2 ** attempt));
      }
    }
  }

  async function run(j) {
    const f = j.file;
    setState(j, 'hash', tr('Se pregătește…', 'Preparing…'));
    const sha = await hashFile(f, (n) => { j.prog.value = n / f.size / 4; });
    let start = await withRetry(() => api('/api/uploads', { method: 'POST', json: {
      sha256: sha, size: f.size, filename: f.name, source: 'Web', taken_at_hint_ms: f.lastModified || null,
    } }));
    if (start.exists) return setState(j, 'dup', tr('Era deja', 'Already there'));
    for (let again = 0; ; again++) {
      let offset = start.offset;
      setState(j, 'up', tr('Se încarcă', 'Uploading'));
      while (offset < f.size) {
        const piece = f.slice(offset, offset + CHUNK);
        try {
          offset = (await withRetry(() => api(`/api/uploads/${start.upload_id}?offset=${offset}`, {
            method: 'PUT', body: piece, headers: { 'Content-Type': 'application/octet-stream' },
          }))).offset;
        } catch (e) {
          if (e.status === 409 && typeof e.body?.offset === 'number') { offset = e.body.offset; continue; }
          throw e;
        }
        j.sent = offset;
        j.prog.value = offset / f.size;
        summary();
      }
      try {
        await withRetry(() => api(`/api/uploads/${start.upload_id}/finish`, { method: 'POST' }));
        addedAny = true;
        return setState(j, 'done', tr('Pe NAS', 'On the NAS'));
      } catch (e) {
        if (e.status !== 422 || again) throw e;  // a ajuns stricat: încă o dată de la zero
        start = await api('/api/uploads', { method: 'POST', json: { sha256: sha, size: f.size, filename: f.name, source: 'Web' } });
        j.sent = 0;
      }
    }
  }

  function pump() {
    while (running < PARALLEL) {
      const j = queue.find((x) => x.state === 'wait');
      if (!j) return;
      running++;
      j.state = 'hash';
      run(j).catch((e) => setState(j, 'err', e.status === 415 ? tr('Tip neacceptat', 'Not supported') : (e.status ? e.message : tr('Fără legătură', 'No connection')))).finally(() => { running--; pump(); });
    }
  }

  return {
    add(files) {
      const media = files.filter((f) => f.size > 0);
      if (!media.length) return;
      ensurePanel();
      for (const f of media) {
        const prog = h('progress', { max: '1', value: '0' });
        const em = h('em', {}, tr('În așteptare', 'Waiting'));
        const li = h('li', {}, h('span', { title: f.name }, f.name), em, prog);
        list.append(li);
        queue.push({ file: f, state: 'wait', sent: 0, final: false, li, em, prog });
      }
      summary();
      pump();
    },
    busy: () => running > 0 || queue.some((j) => j.state === 'wait'),
    reset() { queue.length = 0; panel?.remove(); panel = null; },
  };
})();

window.addEventListener('beforeunload', (e) => { if (uploads.busy()) e.preventDefault(); });

// tragerea fișierelor oriunde pe pagină
let dragDepth = 0;
let dropHint = null;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
document.addEventListener('dragenter', (e) => {
  if (!state.user || !hasFiles(e)) return;
  e.preventDefault();
  if (dragDepth++ === 0) document.body.append(dropHint = h('div', { class: 'drop' }, h('div', {}, tr('Lasă pozele aici ca să le încarci', 'Drop the photos here to upload them'))));
});
document.addEventListener('dragover', (e) => { if (state.user && hasFiles(e)) e.preventDefault(); });
document.addEventListener('dragleave', () => { if (dragDepth && --dragDepth === 0) { dropHint?.remove(); dropHint = null; } });
document.addEventListener('drop', (e) => {
  if (!state.user || !hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0; dropHint?.remove(); dropHint = null;
  uploads.add([...e.dataTransfer.files]);
});

// ---------- pornirea ----------
api('/api/me').then((r) => { state.user = r.user; startApp(); }).catch((e) => { if (e.status !== 401) showLogin(); });
