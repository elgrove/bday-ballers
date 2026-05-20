const form = document.getElementById('dob-form');
const dobInput = document.getElementById('dob');
const errorEl = document.getElementById('error');
const resultsEl = document.getElementById('results');

const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];

function fmtDate(iso) {
  const [y, m, d] = iso.split('-');
  return `${parseInt(d, 10)} ${MONTHS[parseInt(m, 10) - 1]} ${y}`;
}

function fmtMoney(eur) {
  if (eur == null) return null;
  if (eur >= 1_000_000) return `€${(eur / 1_000_000).toFixed(eur >= 10_000_000 ? 0 : 1)}m peak`;
  if (eur >= 1_000)     return `€${Math.round(eur / 1_000)}k peak`;
  return `€${eur} peak`;
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
  resultsEl.innerHTML = '';
  if (!results.length) {
    resultsEl.append(tag('p', { class: 'skeleton' }, 'No players found near that date.'));
    return;
  }

  resultsEl.append(
    tag('div', { class: 'intro' },
      tag('span', {}, 'Top ', tag('strong', {}, results.length), ' near ', tag('strong', {}, fmtDate(dob))),
      tag('span', {}, 'Ranked by notability'),
    ),
  );

  const userDate = new Date(dob + 'T00:00:00Z');

  results.forEach((p, i) => {
    const playerDate = new Date(p.date_of_birth + 'T00:00:00Z');
    const signedDays = Math.round((playerDate - userDate) / 86_400_000);
    const absDays = Math.abs(signedDays);
    const isSameDay = signedDays === 0;
    const ageLabel = isSameDay
      ? 'Same day'
      : (signedDays > 0 ? 'younger' : 'older');
    const ageWord = isSameDay
      ? 'Same day'
      : (absDays === 1 ? `Day ${ageLabel}` : `Days ${ageLabel}`);

    const meta = [];
    if (p.national_team)  meta.push(p.national_team);
    else if (p.nationality) meta.push(p.nationality.split(',')[0].trim());
    if (p.current_club)    meta.push(tag('span', { class: 'club' }, p.current_club));
    if (p.position)        meta.push(p.position.split(' - ').pop());

    // Interleave with separators
    const metaNodes = [];
    meta.forEach((m, idx) => {
      if (idx > 0) metaNodes.push(tag('span', { class: 'sep' }, '·'));
      metaNodes.push(m);
    });

    const badges = [];
    if (p.peak_market_value_eur)
      badges.push(tag('span', { class: 'badge peak' }, fmtMoney(p.peak_market_value_eur)));
    if (p.caps != null)
      badges.push(tag('span', { class: 'badge' }, `${p.caps} caps · ${p.goals ?? 0} gls`));
    if (p.height_cm)
      badges.push(tag('span', { class: 'badge' }, `${p.height_cm} cm`));

    const portrait = p.image_url
      ? tag('div', { class: 'portrait', style: `background-image: url("${p.image_url}")` })
      : tag('div', { class: 'portrait' });

    const nameNode = p.profile_url
      ? tag('a', { href: p.profile_url, target: '_blank', rel: 'noopener' }, p.name)
      : p.name;

    const card = tag('article',
      { class: 'card' + (isSameDay ? ' is-same-day' : ''), style: `animation-delay: ${i * 60}ms` },
      tag('div', { class: 'rank' }, String(i + 1).padStart(2, '0')),
      portrait,
      tag('div', { class: 'body' },
        tag('h2', { class: 'name' }, nameNode),
        tag('p', { class: 'meta' }, fmtDate(p.date_of_birth), tag('span', { class: 'sep' }, '·'), ...metaNodes),
        badges.length ? tag('div', { class: 'badges' }, ...badges) : null,
      ),
      tag('div', { class: 'days-off' },
        isSameDay
          ? null
          : tag('span', { class: 'n' }, String(absDays)),
        tag('span', { class: 'label' + (isSameDay ? ' is-same' : '') }, ageWord),
      ),
    );

    resultsEl.append(card);
  });
}

async function search(dob) {
  errorEl.hidden = true;
  resultsEl.innerHTML = '';
  resultsEl.append(tag('p', { class: 'skeleton' }, 'Looking…'));

  try {
    const r = await fetch(`/api/players?dob=${encodeURIComponent(dob)}&limit=10`);
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.error || `HTTP ${r.status}`);
    }
    const json = await r.json();
    render(dob, json.results);

    // Update URL without reload so the result is shareable
    const url = new URL(window.location);
    url.searchParams.set('dob', dob);
    history.replaceState(null, '', url);
  } catch (err) {
    resultsEl.innerHTML = '';
    errorEl.textContent = err.message;
    errorEl.hidden = false;
  }
}

form.addEventListener('submit', (e) => {
  e.preventDefault();
  const dob = dobInput.value;
  if (!dob) return;
  search(dob);
});

// Prefill from URL or default to a sensible date
const initial = new URL(window.location).searchParams.get('dob');
if (initial) {
  dobInput.value = initial;
  search(initial);
}
