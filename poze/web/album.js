// Albumul deschis printr-un link: doar privit și descărcat, fără cont. Tokenul e în adresă.
const token = location.pathname.split('/').filter(Boolean)[1] || '';
const base = `/api/public/${encodeURIComponent(token)}`;
// cine primește linkul vede pagina în limba browserului lui
const LANG = (navigator.language || '').toLowerCase().startsWith('ro') ? 'ro' : 'en';
document.documentElement.lang = LANG;
const tr = (ro, en) => (LANG === 'ro' ? ro : en);
const MONTHS = LANG === 'ro'
  ? ['ianuarie', 'februarie', 'martie', 'aprilie', 'mai', 'iunie', 'iulie', 'august', 'septembrie', 'octombrie', 'noiembrie', 'decembrie']
  : ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const ICONS = {
  close: 'M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z',
  prev: 'M15.41 7.41 14 6l-6 6 6 6 1.41-1.41L10.83 12z',
  next: 'M10 6 8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z',
  download: 'M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z',
  play: 'M8 5v14l11-7z',
};

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
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'i'); svg.setAttribute('aria-hidden', 'true');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', ICONS[name]); svg.append(p);
  return svg;
}
const iconBtn = (name, label, onclick, cls = 'icon-btn') =>
  h('button', { class: cls, type: 'button', 'aria-label': label, title: label, onclick }, icon(name));
// amprenta în adresă: un număr refolosit de altă poză nu mai aduce miniatura veche din cache
const thumb = (id, size = 256, sha = '') => `${base}/thumb/${id}?size=${size}${sha ? `&v=${sha.slice(0, 12)}` : ''}`;
function fullDate(s) {
  const [d, t] = s.split(' ');
  const [y, m, day] = d.split('-').map(Number);
  return LANG === 'ro' ? `${day} ${MONTHS[m - 1]} ${y}, ${t.slice(0, 5)}` : `${MONTHS[m - 1]} ${day}, ${y}, ${t.slice(0, 5)}`;
}
function plural(n, one, many, enOne, enMany) {
  if (LANG !== 'ro') return n === 1 ? `1 ${enOne}` : `${n.toLocaleString('en-US')} ${enMany}`;
  if (n === 1) return `1 ${one}`;
  const r = n % 100;
  return n === 0 || (r >= 1 && r <= 19) ? `${n} ${many}` : `${n.toLocaleString('ro-RO')} de ${many}`;
}

async function get(path) {
  const r = await fetch(path, { credentials: 'omit' });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

const app = document.getElementById('app');

async function start() {
  let info;
  try { info = await get(base); } catch {
    app.replaceChildren(h('div', { class: 'login' }, h('div', { class: 'empty' },
      h('strong', {}, tr('Linkul nu mai e valabil.', 'This link is no longer valid.')),
      tr('Cere-i celui care ți l-a trimis unul nou.', 'Ask whoever sent it for a new one.'))));
    return;
  }
  document.title = `${info.name} · Amintiri`;
  const grid = h('div', { class: 'grid' });
  const sentinel = h('div', { class: 'sentinel' });
  app.replaceChildren(
    h('header', { class: 'top' }, h('span', { class: 'brand' }, h('img', { src: '/icon.svg', alt: '' }), h('span', {}, 'Amintiri'))),
    h('main', {}, h('h2', { class: 'title' }, info.name),
      h('p', { class: 'subtitle' }, plural(info.count, 'poză', 'poze', 'photo', 'photos')), grid, sentinel));
  const items = [];
  let next;
  let busy = false;
  const lazy = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) { e.target.src = e.target.dataset.src; lazy.unobserve(e.target); }
  }), { rootMargin: '600px' });
  async function more() {
    if (busy || next === null) return;
    busy = true;
    try {
      const page = await get(`${base}/assets?limit=200${next ? `&before=${encodeURIComponent(next)}` : ''}`);
      for (const a of page.items) {
        const idx = items.push(a) - 1;
        const img = h('img', { alt: '', 'data-src': thumb(a.id, 256, a.sha256), onload() { this.classList.add('on'); } });
        lazy.observe(img);
        grid.append(h('button', {
          class: 'tile', type: 'button', 'aria-label': `${a.kind === 'video' ? tr('Clip', 'Video') : tr('Poză', 'Photo')} ${tr('din', 'from')} ${fullDate(a.taken_at)}`,
          onclick: () => viewer(items, idx),
        }, img, a.kind === 'video' ? h('span', { class: 'badge' }, icon('play')) : null));
      }
      next = page.next;
    } finally { busy = false; }
  }
  new IntersectionObserver((e) => { if (e[0].isIntersecting) more(); }, { rootMargin: '1200px' }).observe(sentinel);
}

function viewer(items, start) {
  let i = start;
  const before = document.activeElement;
  const stage = h('div', { class: 'stage' });
  const when = h('div', { class: 'when', 'aria-live': 'polite' });
  const prev = iconBtn('prev', tr('Anterioara', 'Previous'), () => go(-1), 'nav prev');
  const next = iconBtn('next', tr('Următoarea', 'Next'), () => go(1), 'nav next');
  const dlLabel = tr('Descarcă', 'Download');
  const dl = h('a', { class: 'icon-btn', 'aria-label': dlLabel, title: dlLabel, download: '' }, icon('download'));
  const v = h('div', { class: 'viewer', role: 'dialog', 'aria-modal': 'true', tabindex: '-1' },
    h('div', { class: 'bar' }, iconBtn('close', tr('Închide (Esc)', 'Close (Esc)'), close), when, dl), stage, prev, next);
  function show() {
    const a = items[i];
    const original = `${base}/original/${a.id}${a.sha256 ? `?v=${a.sha256.slice(0, 12)}` : ''}`;
    stage.replaceChildren(a.kind === 'video'
      ? h('video', { src: original, controls: true, autoplay: true, playsinline: true, poster: thumb(a.id, 1024, a.sha256) })
      : h('img', { src: thumb(a.id, 1024, a.sha256), alt: `${tr('Poză din', 'Photo from')} ${fullDate(a.taken_at)}` }));
    when.replaceChildren(h('b', {}, fullDate(a.taken_at)), h('small', {}, `${i + 1} ${tr('din', 'of')} ${items.length}`));
    dl.href = original;
    prev.classList.toggle('hidden', i === 0);
    next.classList.toggle('hidden', i === items.length - 1);
  }
  function go(d) { const n = i + d; if (n >= 0 && n < items.length) { i = n; show(); } }
  function key(e) {
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowLeft') go(-1);
    else if (e.key === 'ArrowRight') go(1);
  }
  let x0 = null;
  stage.addEventListener('pointerdown', (e) => { x0 = e.clientX; });
  stage.addEventListener('pointerup', (e) => { if (x0 != null && Math.abs(e.clientX - x0) > 60) go(e.clientX < x0 ? 1 : -1); x0 = null; });
  function close() { document.removeEventListener('keydown', key); v.remove(); document.body.style.overflow = ''; before?.focus?.(); }
  document.addEventListener('keydown', key);
  document.body.style.overflow = 'hidden';
  document.body.append(v);
  show();
  v.focus();
}

start();
