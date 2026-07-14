'use strict';

/* ==========================================================================
 * Reach — static Instagram / Twitter follower scraper.
 * Thin front-end client of the hosted backend at fanatics-ig-scraper-ecru:
 * the backend holds the Apify token server-side, runs the scrape, and returns
 * already-normalized results. No login, no token, no Apify logic in the browser.
 * ======================================================================== */

const API_BASE = 'https://fanatics-ig-scraper-ecru.vercel.app';

// Shared client tag sent on every backend call as the X-Reach-Client header. The
// backend rejects requests without it (it compares against the REACH_CLIENT_TAG
// Vercel env var), which keeps the public internet from hitting the API by curl.
// This is NOT a true secret — it ships in this file — but the app is only
// reachable to FBG people behind Twingate, so only they can read it. The value
// here MUST match the Vercel env var exactly. To rotate: change both and redeploy.
const CLIENT_TAG = 'reach-alveus-prod-56ecfed0';
const apiHeaders = () => ({ 'Content-Type': 'application/json', 'X-Reach-Client': CLIENT_TAG });

// ── Cost rates (per result) — client-side estimate only ─────────────────────
const COST_PER_FOLLOWER = 0.002;          // IG followers
const COST_PER_PROFILE = 0.0023;          // IG profile-details second pass
const COST_PER_FOLLOWER_TW = 0.00015;     // Twitter follower actor (~$0.15/1k)
const TWITTER_MIN_LIMIT = 200;            // Twitter actor floors result count at 200
const FREE_TIER_WARN = 5;                 // ~$5/month Apify free tier

// ── App state ───────────────────────────────────────────────────────────────
let currentData = [];
let hasDetails = false;
let curPlatform = 'instagram';
let statusFilter = 'all';
let sortCol = null;
let sortDir = 'asc';
let lastCheckedIdx = null;

/* ==========================================================================
 * Seed-count helper (cost preview only — the backend parses the real input)
 * ======================================================================== */

// Count the seed handles in the raw input, purely for the per-seed Twitter
// cost estimate. The backend does the authoritative parsing on scrape.
function countSeeds(raw) {
  let n = 0;
  for (let u of (raw || '').split(',')) {
    u = u.trim().replace(/^@+|@+$/g, '');
    const parts = u.split('/').filter(Boolean);
    const username = parts.length ? parts[parts.length - 1] : '';
    if (username && username !== 'www.instagram.com' && username !== 'instagram.com') n++;
  }
  return n;
}

/* ==========================================================================
 * Scrape — POST to backend /api/scrape (results already normalized)
 * ======================================================================== */

document.getElementById('scrapeForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const rawInput = document.getElementById('usernames').value.trim();
  const limit = Math.max(100, Math.min(parseInt(document.getElementById('limit').value) || 200, 5000));
  const type = document.getElementById('type').value;
  const platform = document.getElementById('platform').value;
  if (!rawInput) return;
  curPlatform = platform;

  const btn = document.getElementById('submitBtn');
  const status = document.getElementById('status');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Scraping';
  status.className = 'status visible';
  status.innerHTML = '<span class="spinner"></span><span>Scraping — this can take a few minutes...</span>';
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('resultsCard').classList.remove('visible');
  document.getElementById('detailsChip').style.display = 'none';
  document.getElementById('bioInput').style.display = 'none';
  hasDetails = false;

  try {
    const res = await fetch(API_BASE + '/api/scrape', {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ usernames: rawInput, limit, type, platform }),
    });
    if (!res.ok) {
      let msg = '';
      try { const b = await res.json(); msg = b && b.error; } catch (_) {}
      throw new Error(msg || 'Scrape failed — the backend may be busy or the handle is private.');
    }
    const data = await res.json();
    const results = Array.isArray(data.results) ? data.results : [];
    const elapsed = data.elapsed != null ? data.elapsed : '?';
    currentData = results;
    document.getElementById('resultChip').textContent = results.length;
    status.className = 'status visible success';
    const noun = platform === 'twitter' ? 'followers' : type.toLowerCase();
    status.innerHTML = '<span>✓ Scraped <b>' + results.length + '</b> ' + noun + ' in ' + elapsed + 's</span>';
    renderTable();
    document.getElementById('resultsCard').classList.add('visible');
  } catch (err) {
    status.className = 'status visible error';
    status.textContent = err.message || 'Scrape failed — the backend may be busy or the handle is private.';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="13 17 18 12 13 7"/><polyline points="6 17 11 12 6 7"/></svg> Scrape';
  }
});

/* ==========================================================================
 * Profile details (IG second pass) — POST to backend /api/profile-details
 * ======================================================================== */

async function fetchProfileDetails() {
  const selected = getSelectedFromVisible();
  const targets = selected.length ? selected : currentData.map(r => r.username);
  if (!targets.length) return;

  const cost = (targets.length * COST_PER_PROFILE).toFixed(2);
  const scope = selected.length ? '<b>' + selected.length + ' selected</b>' : '<b>all ' + targets.length + '</b>';
  const ok = await appConfirm({
    title: 'Fetch profile details',
    body: 'Pull bio, follower count, and post count for ' + scope + ' profile' + (targets.length === 1 ? '' : 's') + '.<br><span class="modal-cost">Estimated cost ~$' + cost + '</span>',
    okLabel: 'Fetch details',
  });
  if (!ok) return;

  const btn = document.getElementById('detailsBtn');
  const status = document.getElementById('status');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Fetching';
  status.className = 'status visible';
  status.innerHTML = '<span class="spinner"></span><span>Fetching profile details for ' + targets.length + ' handles...</span>';

  try {
    const cleaned = targets.map(u => u.trim().replace(/^@/, '')).filter(Boolean);
    const res = await fetch(API_BASE + '/api/profile-details', {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ usernames: cleaned }),
    });
    if (!res.ok) {
      let msg = '';
      try { const b = await res.json(); msg = b && b.error; } catch (_) {}
      throw new Error(msg || 'Profile details failed — the backend may be busy or a handle is private.');
    }
    const data = await res.json();
    const items = Array.isArray(data.results) ? data.results : [];
    const elapsed = data.elapsed != null ? data.elapsed : '?';
    // The backend returns already-normalized profile records; merge by username.
    const map = {};
    items.forEach((item) => {
      const uname = (item.username || '').toLowerCase();
      if (!uname) return;
      map[uname] = item;
    });
    let matched = 0;
    currentData.forEach((row) => {
      const d = map[(row.username || '').toLowerCase()];
      if (!d) return;
      const bio = d.biography != null ? d.biography : (d.bio != null ? d.bio : '');
      const followers = d.followers_count != null ? d.followers_count : d.followersCount;
      const follows = d.follows_count != null ? d.follows_count : d.followsCount;
      const posts = d.posts_count != null ? d.posts_count : d.postsCount;
      const external = d.external_url || d.externalUrl || '';
      const links = Array.isArray(d.links) ? d.links : (Array.isArray(d.externalUrls) ? d.externalUrls : null);
      row.biography = bio || row.biography || '';
      row.bio = bio || row.bio || '';
      row.followers_count = followers != null ? followers : row.followers_count;
      row.follows_count = follows != null ? follows : row.follows_count;
      row.posts_count = posts != null ? posts : row.posts_count;
      row.external_url = external || row.external_url || '';
      row.location = d.location || row.location || '';
      row.links = (links && links.length) ? links : (row.links || []);
      matched++;
    });
    hasDetails = true;
    document.getElementById('detailsChip').style.display = 'inline-flex';
    document.getElementById('bioInput').style.display = 'inline-block';
    status.className = 'status visible success';
    status.innerHTML = '<span>✓ Got profile details for <b>' + matched + '</b> of ' + targets.length + ' in ' + elapsed + 's</span>';
    renderTable();
  } catch (err) {
    status.className = 'status visible error';
    status.textContent = err.message || 'Profile details failed — the backend may be busy or a handle is private.';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg> Get profile details';
  }
}

/* ==========================================================================
 * Cost preview — client-side estimate only
 * ======================================================================== */

function updateCostTag() {
  let limit = parseInt(document.getElementById('limit').value) || 0;
  const isTw = document.getElementById('platform').value === 'twitter';
  const seedCount = Math.max(1, countSeeds(document.getElementById('usernames').value));
  if (isTw) limit = Math.max(limit, TWITTER_MIN_LIMIT);
  const rate = isTw ? COST_PER_FOLLOWER_TW : COST_PER_FOLLOWER;
  // Twitter actor is per-seed; IG actors take all seeds in one run.
  const cost = isTw ? (limit * rate * seedCount) : (limit * rate);
  document.getElementById('costTag').textContent = '~$' + cost.toFixed(2);
  document.getElementById('costWarn').classList.toggle('visible', cost > FREE_TIER_WARN);
}

function onPlatformChange() {
  const platform = document.getElementById('platform').value;
  const isTw = platform === 'twitter';
  document.getElementById('usernames').placeholder = isTw
    ? 'elonmusk  (or paste X/Twitter URL)'
    : 'dynastyrewards  (or paste IG URL)';
  document.getElementById('detailsBtn').style.display = isTw ? 'none' : '';
  document.getElementById('type').closest('.field').style.display = isTw ? 'none' : '';
  document.getElementById('emptySub').innerHTML = isTw
    ? 'Try <span style="color:var(--accent);">elonmusk</span>, <span style="color:var(--accent);">nasa</span>, or any public Twitter / X account.'
    : 'Try <span style="color:var(--accent);">dynastyrewards</span>, <span style="color:var(--accent);">humansofny</span>, or any public IG account.';
  document.getElementById('costNote').textContent = isTw
    ? '≈ $' + COST_PER_FOLLOWER_TW.toFixed(5) + ' per result · min limit ' + TWITTER_MIN_LIMIT + ' (estimate)'
    : '≈ $' + COST_PER_FOLLOWER.toFixed(4) + ' per result · min limit 100 (estimate)';
  updateCostTag();
}
document.getElementById('limit').addEventListener('input', updateCostTag);
document.getElementById('usernames').addEventListener('input', updateCostTag);

/* ==========================================================================
 * Confirm modal
 * ======================================================================== */

function appConfirm({ title, body, okLabel = 'Confirm', cancelLabel = 'Cancel' }) {
  return new Promise((resolve) => {
    const backdrop = document.getElementById('modalBackdrop');
    const ok = document.getElementById('modalOk');
    const cancel = document.getElementById('modalCancel');
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalBody').innerHTML = body;
    ok.textContent = okLabel;
    cancel.textContent = cancelLabel;
    cancel.style.display = cancelLabel ? '' : 'none';
    backdrop.classList.add('visible');

    const close = (val) => {
      backdrop.classList.remove('visible');
      ok.removeEventListener('click', okHandler);
      cancel.removeEventListener('click', cancelHandler);
      backdrop.removeEventListener('click', bgHandler);
      document.removeEventListener('keydown', keyHandler);
      resolve(val);
    };
    const okHandler = () => close(true);
    const cancelHandler = () => close(false);
    const bgHandler = (e) => { if (e.target === backdrop) close(false); };
    const keyHandler = (e) => {
      if (e.key === 'Escape') close(false);
      else if (e.key === 'Enter') close(true);
    };
    ok.addEventListener('click', okHandler);
    cancel.addEventListener('click', cancelHandler);
    backdrop.addEventListener('click', bgHandler);
    document.addEventListener('keydown', keyHandler);
    ok.focus();
  });
}

/* ==========================================================================
 * Filter / sort / selection
 * ======================================================================== */

function setStatusFilter(s) {
  statusFilter = s;
  document.querySelectorAll('.filter-pill').forEach(p => p.classList.toggle('active', p.dataset.status === s));
  renderTable();
}

function applyFilters(rows) {
  const search = document.getElementById('searchInput').value.toLowerCase().trim();
  const bioKw = document.getElementById('bioInput').value.toLowerCase().trim();
  return rows.filter((r) => {
    if (statusFilter === 'public' && r.is_private) return false;
    if (statusFilter === 'private' && !r.is_private) return false;
    if (statusFilter === 'verified' && !r.is_verified) return false;
    if (search) {
      const hay = (r.username + ' ' + (r.full_name || '')).toLowerCase();
      if (!hay.includes(search)) return false;
    }
    if (bioKw) {
      const bio = (r.biography || '').toLowerCase();
      if (!bio.includes(bioKw)) return false;
    }
    return true;
  });
}

function applySort(rows) {
  if (!sortCol) return rows;
  const col = sortCol, dir = sortDir === 'asc' ? 1 : -1;
  const get = (r) => {
    switch (col) {
      case 'username': return (r.username || '').toLowerCase();
      case 'full_name': return (r.full_name || '').toLowerCase();
      case 'first_name': return (r.first_name || '').toLowerCase();
      case 'last_name': return (r.last_name || '').toLowerCase();
      case 'location': return (r.location || '').toLowerCase();
      case 'is_verified': return r.is_verified ? 1 : 0;
      case 'is_private': return r.is_private ? 1 : 0;
      case 'followers_count': return r.followers_count != null ? r.followers_count : -1;
      case 'posts_count': return r.posts_count != null ? r.posts_count : -1;
      default: return '';
    }
  };
  return [...rows].sort((a, b) => {
    const av = get(a), bv = get(b);
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
}

function clickSort(col) {
  if (sortCol === col) sortDir = (sortDir === 'asc') ? 'desc' : 'asc';
  else { sortCol = col; sortDir = 'asc'; }
  renderTable();
}

function getSelectedFromVisible() {
  return [...document.querySelectorAll('.row-check:checked')].map(cb => cb.dataset.username).filter(Boolean);
}

function updateSelectCount() {
  const n = getSelectedFromVisible().length;
  document.getElementById('selectedCount').textContent = n;
  document.getElementById('selectBar').classList.toggle('visible', n > 0);
}

function onRowCheck(ev, cb) {
  const allRows = [...document.querySelectorAll('tbody tr')];
  const tr = cb.closest('tr');
  const idx = allRows.indexOf(tr);
  if (ev.shiftKey && lastCheckedIdx !== null && lastCheckedIdx !== idx) {
    const [a, b] = idx < lastCheckedIdx ? [idx, lastCheckedIdx] : [lastCheckedIdx, idx];
    for (let i = a; i <= b; i++) {
      const c = allRows[i].querySelector('.row-check');
      if (c) { c.checked = cb.checked; allRows[i].classList.toggle('selected', cb.checked); }
    }
  } else {
    tr.classList.toggle('selected', cb.checked);
  }
  lastCheckedIdx = idx;
  updateSelectCount();
}

function toggleSelectAll(el) {
  document.querySelectorAll('tbody .row-check').forEach(cb => { cb.checked = el.checked; cb.closest('tr').classList.toggle('selected', el.checked); });
  lastCheckedIdx = null;
  updateSelectCount();
}

function selectAll() {
  document.querySelectorAll('tbody .row-check').forEach(cb => { cb.checked = true; cb.closest('tr').classList.add('selected'); });
  const h = document.getElementById('headerCheck'); if (h) h.checked = true;
  updateSelectCount();
}

function deselectAll() {
  document.querySelectorAll('tbody .row-check').forEach(cb => { cb.checked = false; cb.closest('tr').classList.remove('selected'); });
  const h = document.getElementById('headerCheck'); if (h) h.checked = false;
  updateSelectCount();
}

/* ==========================================================================
 * DM Launcher (per-recipient personalization) — client-side only
 * ======================================================================== */

let dmQueue = [];

function openDmLauncher() {
  const selected = getSelectedFromVisible();
  if (!selected.length) {
    appConfirm({ title: 'No profiles selected', body: 'Select at least one profile to DM.', okLabel: 'OK', cancelLabel: '' });
    return;
  }
  const map = {};
  currentData.forEach(r => { if (r.username) map[r.username] = r; });
  dmQueue = selected.map(u => ({ username: u, full_name: (map[u] && map[u].full_name) || '', sent: false, skipped: false }));
  renderDmQueue();
  document.getElementById('dmModalBackdrop').classList.add('visible');
  document.getElementById('dmTemplate').addEventListener('input', renderDmQueue);
}

function closeDmLauncher() { document.getElementById('dmModalBackdrop').classList.remove('visible'); }

function personalizeMessage(template, row) {
  const fullName = (row.full_name || '').trim();
  const firstName = fullName ? fullName.split(/\s+/)[0] : row.username;
  return template.replace(/\{name\}/g, firstName).replace(/\{username\}/g, row.username);
}

function renderDmQueue() {
  const tmpl = document.getElementById('dmTemplate').value;
  const list = document.getElementById('dmQueueList');
  const sentN = dmQueue.filter(r => r.sent).length;
  document.getElementById('dmProgress').textContent = sentN + ' of ' + dmQueue.length + ' sent';
  list.innerHTML = dmQueue.map((row, i) => {
    const msg = personalizeMessage(tmpl, row);
    const stateBadge = row.sent
      ? '<span class="dm-status">✓ Sent</span>'
      : (row.skipped ? '<span class="dm-status skipped">Skipped</span>' : '');
    const rowClass = row.sent || row.skipped ? 'dm-row sent' : 'dm-row';
    const actions = (row.sent || row.skipped)
      ? '<button class="btn btn-muted btn-xs" onclick="dmReset(' + i + ')">Reset</button>'
      : '<button class="btn btn-muted btn-xs" onclick="dmSkip(' + i + ')">Skip</button>' +
        '<button class="btn btn-primary btn-xs" onclick="dmOpenOne(' + i + ')">Open + Copy</button>';
    return '<div class="' + rowClass + '">' +
      '<div class="dm-num">' + (i + 1) + '</div>' +
      '<div class="dm-handle"><a href="https://instagram.com/' + row.username + '" target="_blank">@' + escapeHtml(row.username) + '</a><div class="dim" style="font-size:11px; font-weight:400;">' + escapeHtml(row.full_name || '') + '</div></div>' +
      '<div class="dm-msg" title="' + escapeHtml(msg) + '">' + escapeHtml(msg) + '</div>' +
      '<div>' + stateBadge + '</div>' +
      '<div class="dm-actions">' + actions + '</div>' +
    '</div>';
  }).join('');
}

async function dmOpenOne(idx) {
  const row = dmQueue[idx];
  if (!row || row.sent) return;
  const tmpl = document.getElementById('dmTemplate').value;
  const msg = personalizeMessage(tmpl, row);
  try { await navigator.clipboard.writeText(msg); }
  catch (err) { showToast('Clipboard write failed — message: ' + msg.slice(0, 80), false); }
  window.open('https://www.instagram.com/' + row.username + '/', '_blank', 'noopener');
  showToast('Opened @' + row.username + ' · message copied. Paste with Cmd+V', true);
  row.sent = true;
  row.skipped = false;
  renderDmQueue();
}

function dmSkip(idx) { if (dmQueue[idx]) { dmQueue[idx].skipped = true; dmQueue[idx].sent = false; renderDmQueue(); } }
function dmReset(idx) { if (dmQueue[idx]) { dmQueue[idx].sent = false; dmQueue[idx].skipped = false; renderDmQueue(); } }

async function dmOpenAll() {
  const remaining = dmQueue.filter(r => !r.sent && !r.skipped).length;
  if (!remaining) return;
  const ok = await appConfirm({
    title: 'Open ' + remaining + ' IG tabs?',
    body: 'Tabs will open one at a time with a 600ms delay so your browser doesn\'t block popups. The clipboard will hold the <b>last opened</b> recipient\'s message — for batch sends, use <b>Open + Copy</b> per row instead.',
    okLabel: 'Open all',
  });
  if (!ok) return;
  for (let i = 0; i < dmQueue.length; i++) {
    const row = dmQueue[i];
    if (row.sent || row.skipped) continue;
    const tmpl = document.getElementById('dmTemplate').value;
    const msg = personalizeMessage(tmpl, row);
    try { await navigator.clipboard.writeText(msg); } catch (_) {}
    window.open('https://www.instagram.com/' + row.username + '/', '_blank', 'noopener');
    row.sent = true;
    renderDmQueue();
    await new Promise(r => setTimeout(r, 600));
  }
  showToast('All tabs opened. Switch to each and paste with Cmd+V', true);
}

/* ==========================================================================
 * Bulk DM (shared message)
 * ======================================================================== */

let bulkDmSelected = [];
let bulkDmMsgCache = '';

function bulkDmOpen() {
  const selected = getSelectedFromVisible();
  if (!selected.length) { showToast('Select at least one profile first', false); return; }
  bulkDmSelected = selected;

  const backdrop = document.getElementById('bulkDmBackdrop');
  const textarea = document.getElementById('bulkDmMessage');
  const goBtn = document.getElementById('bulkDmGo');
  const cancelBtn = document.getElementById('bulkDmCancel');
  const tryAllBtn = document.getElementById('bulkDmTryAll');
  const list = document.getElementById('bulkDmList');
  const intro = document.getElementById('bulkDmIntro');
  const footNote = document.getElementById('bulkDmFootNote');

  list.style.display = 'none';
  list.innerHTML = '';
  tryAllBtn.style.display = 'none';
  goBtn.style.display = '';
  goBtn.textContent = 'Prepare links';
  textarea.style.display = '';
  intro.style.display = '';
  footNote.textContent = '';

  document.getElementById('bulkDmCount').textContent = '· ' + selected.length + ' ' + (selected.length === 1 ? 'profile' : 'profiles');
  textarea.value = localStorage.getItem('bulkDmMessage') || 'Hey! Saw you and wanted to connect.';
  backdrop.classList.add('visible');
  textarea.focus();
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);

  const close = () => {
    backdrop.classList.remove('visible');
    goBtn.removeEventListener('click', goHandler);
    cancelBtn.removeEventListener('click', cancelHandler);
    tryAllBtn.removeEventListener('click', tryAllHandler);
    backdrop.removeEventListener('click', bgHandler);
    document.removeEventListener('keydown', keyHandler);
  };
  const goHandler = () => {
    const msg = textarea.value.trim();
    if (!msg) { textarea.focus(); return; }
    localStorage.setItem('bulkDmMessage', msg);
    bulkDmMsgCache = msg;
    navigator.clipboard.writeText(msg).catch(() => {});
    renderBulkDmList(selected);
    textarea.style.display = 'none';
    intro.style.display = 'none';
    list.style.display = '';
    goBtn.style.display = 'none';
    tryAllBtn.style.display = '';
    footNote.innerHTML = '✓ Message copied to clipboard. Click each handle below — your browser opens 1 tab per click (no popup blocker).';
  };
  const tryAllHandler = () => {
    let opened = 0, blocked = 0;
    for (const u of bulkDmSelected) {
      const w = window.open('https://www.instagram.com/' + u + '/', '_blank', 'noopener');
      if (w) { opened++; markBulkLinkOpened(u); } else blocked++;
    }
    if (blocked > 0) {
      footNote.innerHTML = '<span style="color:#fca5a5;">' + blocked + ' of ' + bulkDmSelected.length + ' blocked.</span> Allow popups for this site in your address bar and retry, or click handles individually below.';
    } else {
      footNote.innerHTML = '<span style="color:#a7f3d0;">All ' + opened + ' tabs open.</span>';
    }
  };
  const cancelHandler = () => close();
  const bgHandler = (e) => { if (e.target === backdrop) close(); };
  const keyHandler = (e) => {
    if (e.key === 'Escape') close();
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && goBtn.style.display !== 'none') goHandler();
  };
  goBtn.addEventListener('click', goHandler);
  cancelBtn.addEventListener('click', cancelHandler);
  tryAllBtn.addEventListener('click', tryAllHandler);
  backdrop.addEventListener('click', bgHandler);
  document.addEventListener('keydown', keyHandler);
}

function renderBulkDmList(usernames) {
  const list = document.getElementById('bulkDmList');
  const map = {};
  currentData.forEach(r => { if (r.username) map[r.username] = r; });
  list.innerHTML = '<div class="bulk-grid">' + usernames.map((u) => {
    return '<a class="bulk-link" href="https://www.instagram.com/' + u + '/" target="_blank" rel="noopener" data-username="' + escapeHtml(u) + '" onclick="markBulkLinkOpened(\'' + u.replace(/'/g, "\\'") + '\')">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>' +
      '<span class="name">@' + escapeHtml(u) + '</span>' +
    '</a>';
  }).join('') + '</div>';
}

function markBulkLinkOpened(username) {
  const el = document.querySelector('.bulk-link[data-username="' + CSS.escape(username) + '"]');
  if (el) el.classList.add('opened');
  if (bulkDmMsgCache) navigator.clipboard.writeText(bulkDmMsgCache).catch(() => {});
}

function showToast(msg, success) {
  const toast = document.getElementById('dmToast');
  toast.className = 'dm-toast visible' + (success ? ' success' : '');
  toast.innerHTML = success
    ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg> ' + escapeHtml(msg)
    : escapeHtml(msg);
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { toast.classList.remove('visible'); }, 3500);
}

async function openSelectedInIG() {
  const selected = getSelectedFromVisible();
  if (!selected.length) return;
  if (selected.length > 15) {
    const ok = await appConfirm({
      title: 'Open ' + selected.length + ' Instagram tabs?',
      body: 'This will open <b>' + selected.length + '</b> new tabs at once. Your browser may block popups — you\'ll see a popup-blocked icon in the address bar if so.',
      okLabel: 'Open tabs',
    });
    if (!ok) return;
  }
  const base = curPlatform === 'twitter' ? 'https://twitter.com/' : 'https://instagram.com/';
  selected.forEach(u => window.open(base + u, '_blank', 'noopener'));
}

/* ==========================================================================
 * Render / export
 * ======================================================================== */

function avatarFor(item) {
  const initial = escapeHtml((item.username || '?')[0].toUpperCase());
  const base = curPlatform === 'twitter' ? 'https://twitter.com/' : 'https://instagram.com/';
  if (item.profile_pic_url) {
    return '<a href="' + base + item.username + '" target="_blank"><img class="avatar" src="' + escapeHtml(item.profile_pic_url) + '" alt="" loading="lazy" onerror="this.outerHTML=\'<div class=avatar-fallback>' + initial + '</div>\';"></a>';
  }
  return '<div class="avatar-fallback">' + initial + '</div>';
}

function fmtNum(n) {
  if (n == null) return '—';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n);
}

function buildHeader() {
  const showFields = hasDetails || curPlatform === 'twitter';
  const cols = [
    { key: 'check', label: '<input type="checkbox" class="row-check" onchange="toggleSelectAll(this)" id="headerCheck">', sort: false, w: '32px' },
    { key: 'avatar', label: '', sort: false, w: '44px' },
    { key: 'username', label: 'Username', sort: true },
    { key: 'full_name', label: 'Full name', sort: true },
    { key: 'first_name', label: 'First name', sort: true },
    { key: 'last_name', label: 'Last name', sort: true },
    { key: 'is_verified', label: 'Status', sort: true },
  ];
  if (hasDetails) {
    cols.push({ key: 'followers_count', label: 'Followers', sort: true, align: 'right' });
    cols.push({ key: 'posts_count', label: 'Posts', sort: true, align: 'right' });
  } else if (curPlatform === 'twitter') {
    cols.push({ key: 'followers_count', label: 'Followers', sort: true, align: 'right' });
  } else {
    cols.push({ key: 'username_scrape', label: 'Source', sort: false });
  }
  if (showFields) {
    cols.push({ key: 'biography', label: 'Bio', sort: false });
    if (curPlatform === 'twitter') cols.push({ key: 'location', label: 'Location', sort: true });
    cols.push({ key: 'links', label: 'Links', sort: false });
  }
  return cols.map((c) => {
    const isSorted = sortCol === c.key;
    const arrow = c.sort ? '<span class="sort-arrow">' + (isSorted ? (sortDir === 'asc' ? '▲' : '▼') : '▲▼') + '</span>' : '';
    const cls = (c.sort ? 'sortable ' : '') + (isSorted ? 'sorted' : '');
    const onclick = c.sort ? ' onclick="clickSort(\'' + c.key + '\')"' : '';
    const style = (c.w ? 'width:' + c.w + ';' : '') + (c.align === 'right' ? 'text-align:right;' : '');
    return '<th class="' + cls + '" style="' + style + '"' + onclick + '>' + c.label + arrow + '</th>';
  }).join('');
}

function renderTable() {
  const filtered = applySort(applyFilters(currentData));
  document.getElementById('tableHeader').innerHTML = buildHeader();
  document.getElementById('resultChip').textContent = currentData.length;

  const stat = document.getElementById('filterStat');
  if (filtered.length === currentData.length) stat.textContent = currentData.length + ' rows';
  else stat.textContent = filtered.length + ' of ' + currentData.length + ' rows';

  const showFields = hasDetails || curPlatform === 'twitter';
  const profileBase = curPlatform === 'twitter' ? 'https://twitter.com/' : 'https://instagram.com/';
  const body = document.getElementById('resultsBody');
  body.innerHTML = filtered.map((item) => {
    const checkCell = '<td><input type="checkbox" class="row-check" data-username="' + escapeHtml(item.username) + '" onclick="onRowCheck(event, this)"></td>';
    const avatarCell = '<td>' + avatarFor(item) + '</td>';
    const usernameCell = '<td><a class="handle" href="' + profileBase + item.username + '" target="_blank">@' + escapeHtml(item.username) + '</a></td>';
    const nameCell = '<td>' + escapeHtml(item.full_name || '') + '</td>';
    const firstCell = '<td>' + (escapeHtml(item.first_name || '') || '<span class="dim">—</span>') + '</td>';
    const lastCell = '<td>' + (escapeHtml(item.last_name || '') || '<span class="dim">—</span>') + '</td>';
    const statusCell = '<td>' + (item.is_verified ? '<span class="badge verified">✓ Verified</span> ' : '') + (item.is_private ? '<span class="badge private">Private</span>' : '<span class="badge public">Public</span>') + '</td>';

    let extra = '';
    if (hasDetails) {
      extra += '<td class="num-cell">' + fmtNum(item.followers_count) + '</td>';
      extra += '<td class="num-cell">' + fmtNum(item.posts_count) + '</td>';
    } else if (curPlatform === 'twitter') {
      extra += '<td class="num-cell">' + fmtNum(item.followers_count) + '</td>';
    } else {
      extra += '<td><a class="sub-handle" href="https://instagram.com/' + (item.username_scrape || '') + '" target="_blank">@' + escapeHtml(item.username_scrape || '—') + '</a></td>';
    }
    if (showFields) {
      const bioText = item.biography || item.bio || '';
      extra += '<td class="bio-cell">' + (escapeHtml(bioText).slice(0, 240) || '<span class="dim">—</span>') + '</td>';
      if (curPlatform === 'twitter') {
        extra += '<td>' + (escapeHtml(item.location || '') || '<span class="dim">—</span>') + '</td>';
      }
      const norm = u => (u || '').replace(/^https?:\/\//, '').replace(/\/$/, '').toLowerCase();
      const links = Array.isArray(item.links) ? item.links.slice() : [];
      if (item.external_url && !links.some(l => norm(l) === norm(item.external_url))) links.unshift(item.external_url);
      const linksHtml = links.length
        ? links.map((u) => { const h = /^https?:\/\//.test(u) ? u : 'https://' + u; return '<a href="' + escapeHtml(h) + '" target="_blank" rel="noopener">' + escapeHtml(u.replace(/^https?:\/\//, '')) + '</a>'; }).join('<br>')
        : '<span class="dim">—</span>';
      extra += '<td class="bio-cell">' + linksHtml + '</td>';
    }
    return '<tr>' + checkCell + avatarCell + usernameCell + nameCell + firstCell + lastCell + statusCell + extra + '</tr>';
  }).join('');
  updateSelectCount();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function exportCSV() {
  if (!currentData.length) return;
  const rows = applySort(applyFilters(currentData));
  const showFields = hasDetails || curPlatform === 'twitter';
  const headers = ['username', 'full_name', 'first_name', 'last_name', 'id', 'is_private', 'is_verified', 'username_scrape'];
  if (hasDetails) headers.push('biography', 'followers_count', 'follows_count', 'posts_count');
  else if (curPlatform === 'twitter') headers.push('biography', 'followers_count');
  if (curPlatform === 'twitter') headers.push('location');
  if (showFields) headers.push('links');
  const out = rows.map((r) => headers.map((h) => {
    let val = r[h];
    if (Array.isArray(val)) val = val.join('; ');
    return '"' + String(val == null ? '' : val).replace(/"/g, '""') + '"';
  }).join(','));
  download([headers.join(','), ...out].join('\n'), 'followers.csv', 'text/csv');
}

function exportJSON() {
  if (!currentData.length) return;
  const rows = applySort(applyFilters(currentData));
  download(JSON.stringify(rows, null, 2), 'followers.json', 'application/json');
}

function download(content, filename, mime) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], { type: mime }));
  a.download = filename;
  a.click();
}

/* ==========================================================================
 * Boot — no auth/config load; just initialize the UI.
 * ======================================================================== */
onPlatformChange();
updateCostTag();
