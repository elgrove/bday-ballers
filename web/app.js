const form = document.getElementById('dob-form');
const dobInput = document.getElementById('dob');
const errorEl = document.getElementById('error');
const albumEl = document.getElementById('album');

const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];

function fmtDate(iso) {
  const [y, m, d] = iso.split('-');
  return `${parseInt(d, 10)} ${MONTHS[parseInt(m, 10) - 1]} ${y}`;
}

function tag(name, attrs = {}, ...kids) {
  const el = document.createElement(name);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k === 'style') el.style.cssText = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, '');
    else if (v != null && v !== false) el.setAttribute(k, v);
  }
  for (const k of kids.flat()) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}

function render(dob, results) {
  albumEl.innerHTML = '';
  if (!results.length) {
    albumEl.append(tag('p', { class: 'skeleton' }, 'No players found near that date.'));
    return;
  }

  const userDate = new Date(dob + 'T00:00:00Z');

  results.forEach((p, i) => {
    const playerDate = new Date(p.date_of_birth + 'T00:00:00Z');
    const signed = Math.round((playerDate - userDate) / 86_400_000);
    const abs = Math.abs(signed);
    const same = signed === 0;

    const nationality = p.national_team
      || (p.nationality ? p.nationality.split(',')[0].trim() : null);

    const daysText = same
      ? 'Same day!'
      : `${abs} days ${signed > 0 ? 'younger' : 'older'}`;

    const stats = [];
    stats.push(tag('span', { class: 'chip' }, daysText));
    if (nationality) stats.push(tag('span', { class: 'chip ghost' }, nationality));
    if (p.caps != null) stats.push(tag('span', { class: 'chip ghost' }, `Intl ${p.caps}/${p.goals ?? 0}`));
    if (p.foot) stats.push(tag('span', { class: 'chip ghost' }, p.foot === 'both' ? 'Both feet' : `${p.foot} foot`));

    const portrait = tag('div', {
      class: 'portrait',
      style: p.image_url ? `background-image: url("${p.image_url}")` : '',
    });

    const nameNode = p.profile_url
      ? tag('a', { href: p.profile_url, target: '_blank', rel: 'noopener' }, p.name)
      : p.name;

    const card = tag('article', { class: 'card', style: `animation-delay: ${i * 70}ms` },
      portrait,
      tag('div', {},
        tag('h2', { class: 'name' }, nameNode),
        tag('div', { class: 'meta' },
          fmtDate(p.date_of_birth), ' · ',
          tag('strong', {}, p.current_club || '—'),
          p.position ? ' · ' + p.position.split(' - ').pop() : ''
        ),
      ),
      tag('div', { class: 'stats' }, ...stats),
    );

    albumEl.append(card);
  });
}

async function search(dob) {
  errorEl.hidden = true;
  albumEl.innerHTML = '<p class="skeleton">Opening the packets…</p>';

  try {
    const r = await fetch(`/api/players?dob=${encodeURIComponent(dob)}&limit=10`);
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.error || `HTTP ${r.status}`);
    }
    const json = await r.json();
    render(dob, json.results);

    const url = new URL(window.location);
    url.searchParams.set('dob', dob);
    history.replaceState(null, '', url);
  } catch (err) {
    albumEl.innerHTML = '';
    errorEl.textContent = err.message;
    errorEl.hidden = false;
  }
}

form.addEventListener('submit', (e) => {
  e.preventDefault();
  if (dobInput.value) search(dobInput.value);
});

// Prefill from URL or use the default already on the input
const initial = new URL(window.location).searchParams.get('dob');
if (initial) dobInput.value = initial;
search(dobInput.value);
