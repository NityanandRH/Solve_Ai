/* ═══════════════════════════════════════════════════════
   InnovateTool — script.js
   Full frontend logic: auth, sessions, all tabs, SSE streaming
════════════════════════════════════════════════════════ */

'use strict';

// Same-origin on Azure (FastAPI serves the frontend).
// For local dev set LOCAL_DEV=true in backend .env and run on :8000.
const API = window.location.port === '8000' ? 'http://localhost:8000' : '';

// ── State ────────────────────────────────────────────────────────────────────
let currentUser = null;
let currentSession = null;
let trizData = null;
let adminChatHistory = [];
let adminCharts = {};
let ideateModifyIndex = -1;

// ══════════════════════════════════════════════════════
// UTILITIES
// ══════════════════════════════════════════════════════

function $(id) { return document.getElementById(id); }
function $$(sel) { return document.querySelectorAll(sel); }

function showToast(msg, type = 'info', duration = 3000) {
  const t = $('toast');
  t.textContent = msg;
  t.className = `toast ${type}`;
  t.classList.remove('hidden');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add('hidden'), duration);
}

function showLoading() { $('loading-overlay').classList.remove('hidden'); }
function hideLoading() { $('loading-overlay').classList.add('hidden'); }

function setHtml(el, md) {
  if (typeof marked !== 'undefined') {
    el.innerHTML = marked.parse(md || '');
  } else {
    el.textContent = md || '';
  }
}

// No JWT token storage — App Service session cookie handles auth automatically.

async function api(method, path, body) {
  // No Authorization header — App Service Easy Auth uses a session cookie
  // attached automatically to every same-origin fetch.
  const opts = {
    method,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  if (res.status === 401) {
    // Session expired → redirect to AAD login, preserving current path
    window.location.href = '/.auth/login/aad?post_login_redirect_uri=' +
      encodeURIComponent(window.location.pathname);
    return null;
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

// SSE streaming helper — calls onChunk(text) for each token, onDone(fullText) when done
async function stream(path, body, onChunk, onDone, method = 'POST') {
  const res = await fetch(API + path, {
    method,
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Stream failed');
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let fullText = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const data = JSON.parse(line.slice(6));
        if (data.text) { fullText += data.text; onChunk(data.text); }
        if (data.done) { onDone && onDone(data.full || fullText); }
        if (data.error) { throw new Error(data.error); }
      } catch (e) {
        if (e.message !== 'Unexpected end of JSON input') console.warn(e);
      }
    }
  }
}

// ══════════════════════════════════════════════════════
// AUTH — Azure App Service Easy Auth (SSO)
// ══════════════════════════════════════════════════════

async function init() {
  // App Service Easy Auth has already authenticated the user before
  // this page loaded. Just call /api/auth/me to get identity + auto-provision.
  setSsoStatus('Verifying your organisation account…');
  try {
    const res = await fetch(API + '/api/auth/me', {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }
    });
    if (res.status === 401 || res.status === 403) {
      // Not authenticated — redirect to AAD login
      setSsoStatus('Redirecting to your organisation sign-in…');
      window.location.href = '/.auth/login/aad?post_login_redirect_uri=' +
        encodeURIComponent(window.location.pathname);
      return;
    }
    if (!res.ok) {
      setSsoStatus('Could not connect to the server. Please refresh.');
      return;
    }
    currentUser = await res.json();
    showApp();
  } catch (e) {
    // Network error — could be local dev without backend running
    setSsoStatus('Connection failed. Is the backend running?');
    console.error('Init error:', e);
  }
}

function setSsoStatus(msg) {
  const el = document.getElementById('sso-status');
  if (el) el.textContent = msg;
}

function showApp() {
  document.getElementById('sso-loading').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');

  // Clean slate — no stale state from previous session
  currentSession = null;
  resetAllTabs();
  updateStagePipeline({});
  $('sessions-list').innerHTML = '<div class="empty-state">No sessions yet. Create one to start.</div>';
  $('current-session-name').textContent = 'Select or create a session';

  // Show display_name (full name from AAD) in sidebar, email underneath
  const displayName = currentUser.display_name || currentUser.username;
  const email = currentUser.email || currentUser.username;
  $('user-name').textContent = displayName;
  $('user-avatar').textContent = displayName[0].toUpperCase();

  const emailEl = $('user-email');
  if (emailEl) { emailEl.textContent = email; }

  const badge = $('user-role-badge');
  badge.textContent = currentUser.role;
  if (currentUser.role === 'admin') {
    badge.classList.add('admin');
    $$('.tab-admin').forEach(el => el.classList.remove('hidden'));
    loadTrizData();
    loadAdminTelemetry();
  } else {
    badge.classList.remove('admin');
    $$('.tab-admin').forEach(el => el.classList.add('hidden'));
    loadTrizData();
  }
  loadSessions();
}

function doLogout() {
  // Destroy chart instances
  Object.values(adminCharts).forEach(c => { try { c.destroy(); } catch(_) {} });
  adminCharts = {};
  currentUser = null;
  currentSession = null;
  adminChatHistory = [];
  // App Service /.auth/logout clears the AAD session and redirects back to /
  window.location.href = '/.auth/logout?post_logout_redirect_uri=/';
}

$('logout-btn').addEventListener('click', doLogout);

// ══════════════════════════════════════════════════════
// SESSIONS
// ══════════════════════════════════════════════════════

async function loadSessions() {
  try {
    const data = await api('GET', '/api/sessions');
    if (!data) return;
    renderSessions(data.sessions);
  } catch (err) { showToast(err.message, 'error'); }
}

function renderSessions(sessions) {
  const list = $('sessions-list');
  if (!sessions.length) {
    list.innerHTML = '<div class="empty-state">No sessions yet. Create one to start.</div>';
    return;
  }
  list.innerHTML = sessions.map(s => `
    <div class="session-item ${currentSession?.id === s.id ? 'active' : ''}"
         data-id="${s.id}">
      <span class="session-name" title="${s.name}">${s.name}</span>
      <div class="session-actions">
        <button class="session-action-btn" data-action="rename" data-id="${s.id}" title="Rename">✎</button>
        <button class="session-action-btn" data-action="delete" data-id="${s.id}" title="Delete">✕</button>
      </div>
    </div>
  `).join('');
}

$('sessions-list').addEventListener('click', async e => {
  const item = e.target.closest('.session-item');
  const btn = e.target.closest('[data-action]');
  if (btn) {
    e.stopPropagation();
    const id = btn.dataset.id;
    if (btn.dataset.action === 'rename') openRenameModal(id);
    if (btn.dataset.action === 'delete') await deleteSession(id);
    return;
  }
  if (item) await selectSession(item.dataset.id);
});

async function selectSession(id) {
  try {
    const data = await api('GET', `/api/sessions/${id}`);
    if (!data) return;
    currentSession = data.session;
    $('current-session-name').textContent = currentSession.name;
    updateStagePipeline(currentSession.stage_status || {});
    loadSessionIntoTabs(currentSession);
    renderSessions(await api('GET', '/api/sessions').then(d => d.sessions));
  } catch (err) { showToast(err.message, 'error'); }
}

function updateStagePipeline(status) {
  $$('.stage-step').forEach(el => {
    const stage = el.dataset.stage;
    el.classList.remove('done', 'active');
    if (status[stage]) el.classList.add('done');
  });
}

// Re-fetch session from server and refresh the pipeline indicator
async function refreshSessionStatus() {
  if (!currentSession) return;
  try {
    const data = await api('GET', `/api/sessions/${currentSession.id}`);
    if (!data) return;
    currentSession.stage_status = data.session.stage_status;
    updateStagePipeline(currentSession.stage_status);
  } catch (_) {}
}

function loadSessionIntoTabs(session) {
  // Context
  $('context-input').value = session.initial_context || '';
  updateCharCount($('context-input'), $('context-char-count'));
  $('context-saved-msg').classList.toggle('hidden', !session.stage_status?.context);
  $('no-session-msg').classList.add('hidden');

  // Ideate
  const ideateData = session.ideate_data || {};
  if (ideateData.method) restoreIdeateState(ideateData);
  else resetIdeateUI();

  // Analyze
  const analyzeData = session.analyze_data || {};
  if (analyzeData.method) restoreAnalyzeState(analyzeData);
  else resetAnalyzeUI();

  // Solve
  const solveData = session.solve_data || {};
  if (solveData.initialized) restoreSolveState(solveData);
  else resetSolveUI();

  // TRIZ
  const trizSessionData = session.triz_data || {};
  if (trizSessionData.tool) restoreTrizState(trizSessionData);
  else resetTrizUI();

  // Patent
  const patentData = session.patent_data || {};
  restorePatentState(patentData);
}

// ── New Session ──
$('new-session-btn').addEventListener('click', () => {
  $('new-session-name').value = '';
  $('new-session-modal').classList.remove('hidden');
  setTimeout(() => $('new-session-name').focus(), 50);
});
$('new-session-cancel-btn').addEventListener('click', () => $('new-session-modal').classList.add('hidden'));
$('new-session-overlay').addEventListener('click', () => $('new-session-modal').classList.add('hidden'));
$('new-session-create-btn').addEventListener('click', async () => {
  const name = $('new-session-name').value.trim();
  if (!name) { showToast('Enter a session name', 'error'); return; }
  try {
    const data = await api('POST', '/api/sessions', { name });
    if (!data) return;
    $('new-session-modal').classList.add('hidden');
    await selectSession(data.session.id);
    showToast('Session created', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});
$('new-session-name').addEventListener('keydown', e => {
  if (e.key === 'Enter') $('new-session-create-btn').click();
});

// ── Rename Session ──
function openRenameModal(id) {
  const item = document.querySelector(`[data-id="${id}"] .session-name`);
  $('rename-session-input').value = item?.textContent || '';
  $('rename-session-id').value = id;
  $('rename-session-modal').classList.remove('hidden');
  setTimeout(() => $('rename-session-input').focus(), 50);
}
$('rename-cancel-btn').addEventListener('click', () => $('rename-session-modal').classList.add('hidden'));
$('rename-session-overlay').addEventListener('click', () => $('rename-session-modal').classList.add('hidden'));
$('rename-save-btn').addEventListener('click', async () => {
  const id = $('rename-session-id').value;
  const name = $('rename-session-input').value.trim();
  if (!name) return;
  try {
    await api('PATCH', `/api/sessions/${id}`, { name });
    $('rename-session-modal').classList.add('hidden');
    if (currentSession?.id === id) {
      currentSession.name = name;
      $('current-session-name').textContent = name;
    }
    await loadSessions();
    showToast('Renamed', 'success');
  } catch (err) { showToast(err.message, 'error'); }
});

async function deleteSession(id) {
  if (!confirm('Delete this session? This cannot be undone.')) return;
  try {
    await api('DELETE', `/api/sessions/${id}`);
    if (currentSession?.id === id) {
      currentSession = null;
      $('current-session-name').textContent = 'Select or create a session';
      resetAllTabs();
    }
    await loadSessions();
    showToast('Session deleted', 'info');
  } catch (err) { showToast(err.message, 'error'); }
}

function resetAllTabs() {
  $('context-input').value = '';
  $('context-saved-msg').classList.add('hidden');
  $('no-session-msg').classList.remove('hidden');
  resetIdeateUI();
  resetAnalyzeUI();
  resetSolveUI();
  resetTrizUI();
  resetPatentUI();
  updateStagePipeline({});
}

// ══════════════════════════════════════════════════════
// TAB NAVIGATION
// ══════════════════════════════════════════════════════

$$('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    $$('.tab-panel').forEach(p => p.classList.remove('active'));
    $(`tab-${btn.dataset.tab}`).classList.add('active');
    if (btn.dataset.tab === 'admin' && currentUser?.role === 'admin') {
      loadAdminTelemetry();
    }
  });
});

// ══════════════════════════════════════════════════════
// CONTEXT TAB
// ══════════════════════════════════════════════════════

function updateCharCount(textarea, counter) {
  const len = textarea.value.length;
  counter.textContent = `${len} / 2000`;
  if (len > 1800) counter.style.color = 'var(--accent-red)';
  else counter.style.color = '';
}

$('context-input').addEventListener('input', () => {
  updateCharCount($('context-input'), $('context-char-count'));
});

$('save-context-btn').addEventListener('click', async () => {
  if (!currentSession) { showToast('Select a session first', 'error'); return; }
  const ctx = $('context-input').value.trim();
  if (!ctx) { showToast('Enter your problem context', 'error'); return; }
  if (ctx.length > 2000) { showToast('Context too long (max 2000 chars)', 'error'); return; }
  showLoading();
  try {
    await api('POST', `/api/sessions/${currentSession.id}/context`, { context: ctx });
    currentSession.initial_context = ctx;
    currentSession.stage_status = currentSession.stage_status || {};
    currentSession.stage_status.context = true;
    updateStagePipeline(currentSession.stage_status);
    $('context-saved-msg').classList.remove('hidden');
    showToast('Context saved!', 'success');
    // Auto-switch to Ideate
    setTimeout(() => {
      document.querySelector('[data-tab="ideate"]').click();
    }, 800);
  } catch (err) { showToast(err.message, 'error'); }
  finally { hideLoading(); }
});

// ══════════════════════════════════════════════════════
// IDEATE TAB
// ══════════════════════════════════════════════════════

function resetIdeateUI() {
  $('ideate-method-selector').classList.remove('hidden');
  $('ideate-interview').classList.add('hidden');
  $('ideate-completed-banner').classList.add('hidden');
  $('ideate-answers-review').classList.add('hidden');
  $('ideate-summary-output').classList.add('hidden');
  document.querySelector('input[name="ideate-method"][value="psc"]').checked = true;
}

function restoreIdeateState(data) {
  $('ideate-method-selector').classList.add('hidden');
  $('ideate-interview').classList.remove('hidden');
  renderIdeateInterview(data);
}

function renderIdeateInterview(data) {
  const { method, questions, current_index, summary, completed } = data;
  const methodLabels = { psc: 'PSC', design_thinking: 'Design Thinking', jtbd: 'JTBD' };
  $('ideate-method-badge').textContent = methodLabels[method] || method.toUpperCase();

  const total = questions.length;
  const idx = Math.min(current_index, total);
  const pct = (idx / total) * 100;
  $('ideate-progress-fill').style.width = pct + '%';
  $('ideate-progress-text').textContent = completed
    ? `${total} / ${total} complete`
    : `Question ${idx + 1} of ${total}`;

  if (!completed && idx < total) {
    const q = questions[idx];
    $('ideate-q-number').textContent = `Q${idx + 1}`;
    $('ideate-q-text').textContent = q.question;
    $('ideate-suggestion-text').textContent = q.suggestion || 'Generating hint...';
    $('ideate-answer-input').value = '';
    $('ideate-question-card').classList.remove('hidden');
    $('ideate-answer-area').classList.remove('hidden');
    $('ideate-completed-banner').classList.add('hidden');
  } else {
    $('ideate-question-card').classList.add('hidden');
    $('ideate-answer-area').classList.add('hidden');
    $('ideate-completed-banner').classList.remove('hidden');
    renderIdeateAnswers(questions);
  }

  if (summary) {
    $('ideate-summary-output').classList.remove('hidden');
    setHtml($('ideate-summary-text'), summary);
    $('ideate-summary-btn').classList.add('hidden');
  } else if (completed) {
    $('ideate-summary-section').classList.remove('hidden');
    $('ideate-summary-btn').classList.remove('hidden');
  }
}

function renderIdeateAnswers(questions) {
  $('ideate-answers-review').classList.remove('hidden');
  $('ideate-answers-list').innerHTML = questions.map((q, i) => `
    <div class="answer-review-item" data-index="${i}">
      <div class="answer-review-q">${q.question}</div>
      <div class="answer-review-a">${q.answer || '<em style="color:var(--text-muted)">Not answered</em>'}</div>
    </div>
  `).join('');

  $('ideate-answers-list').addEventListener('click', e => {
    const item = e.target.closest('.answer-review-item');
    if (!item) return;
    ideateModifyIndex = parseInt(item.dataset.index);
    const q = (currentSession?.ideate_data?.questions || [])[ideateModifyIndex];
    if (!q) return;
    $('modify-question-text').textContent = q.question;
    $('modify-answer-input').value = q.answer || '';
    $('ideate-modify-modal').classList.remove('hidden');
    setTimeout(() => $('modify-answer-input').focus(), 50);
  });
}

// Start ideate
$('ideate-start-btn').addEventListener('click', async () => {
  if (!currentSession) { showToast('Select a session first', 'error'); return; }
  if (!currentSession.initial_context) { showToast('Save context first', 'error'); return; }
  const method = document.querySelector('input[name="ideate-method"]:checked').value;
  showLoading();
  try {
    const data = await api('POST', `/api/sessions/${currentSession.id}/ideate/start`, { method });
    if (!data) return;
    currentSession.ideate_data = data.ideate_data;
    $('ideate-method-selector').classList.add('hidden');
    $('ideate-interview').classList.remove('hidden');
    renderIdeateInterview(data.ideate_data);
  } catch (err) { showToast(err.message, 'error'); }
  finally { hideLoading(); }
});

$('ideate-change-method-btn').addEventListener('click', () => {
  if (!confirm('This will reset your current Ideate progress. Continue?')) return;
  resetIdeateUI();
});

// Submit answer
$('ideate-submit-answer-btn').addEventListener('click', async () => {
  const answer = $('ideate-answer-input').value.trim();
  if (!answer) { showToast('Please enter an answer', 'error'); return; }
  showLoading();
  try {
    const data = await api('POST', `/api/sessions/${currentSession.id}/ideate/answer`, { answer });
    if (!data) return;
    currentSession.ideate_data = data.ideate_data;
    renderIdeateInterview(data.ideate_data);
    if (data.ideate_data.completed) await refreshSessionStatus();
  } catch (err) { showToast(err.message, 'error'); }
  finally { hideLoading(); }
});

$('ideate-answer-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    $('ideate-submit-answer-btn').click();
  }
});

// Modify answer modal
$('modify-cancel-btn').addEventListener('click', () => $('ideate-modify-modal').classList.add('hidden'));
$('ideate-modify-modal').querySelector('.modal-overlay').addEventListener('click', () => {
  $('ideate-modify-modal').classList.add('hidden');
});

$('modify-save-btn').addEventListener('click', async () => {
  const newAnswer = $('modify-answer-input').value.trim();
  if (!newAnswer) { showToast('Enter an answer', 'error'); return; }
  $('ideate-modify-modal').classList.add('hidden');
  showLoading();
  try {
    const data = await api('POST', `/api/sessions/${currentSession.id}/ideate/modify`, {
      question_index: ideateModifyIndex,
      new_answer: newAnswer
    });
    if (!data) return;
    currentSession.ideate_data = data.ideate_data;
    renderIdeateInterview(data.ideate_data);
    showToast('Answer updated', 'success');
  } catch (err) { showToast(err.message, 'error'); }
  finally { hideLoading(); }
});

// Generate summary
$('ideate-summary-btn').addEventListener('click', async () => {
  const output = $('ideate-summary-output');
  const textEl = $('ideate-summary-text');
  output.classList.remove('hidden');
  $('ideate-summary-btn').disabled = true;
  textEl.innerHTML = '';
  textEl.classList.add('stream-target');
  let full = '';
  try {
    await stream(
      `/api/sessions/${currentSession.id}/ideate/summary`,
      {},
      chunk => { full += chunk; setHtml(textEl, full); },
      finalText => {
        textEl.classList.remove('stream-target');
        textEl.classList.add('done');
        currentSession.ideate_data = currentSession.ideate_data || {};
        currentSession.ideate_data.summary = finalText;
      }
    );
  } catch (err) { showToast(err.message, 'error'); }
  finally { $('ideate-summary-btn').disabled = false; }
});

$('ideate-summary-confirm-btn').addEventListener('click', () => {
  refreshSessionStatus();
  showToast('Ideate confirmed! Moving to Analyze.', 'success');
  document.querySelector('[data-tab="analyze"]').click();
});

// ══════════════════════════════════════════════════════
// ANALYZE TAB
// ══════════════════════════════════════════════════════

function resetAnalyzeUI() {
  $('analyze-method-selector').classList.remove('hidden');
  $('analyze-interview').classList.add('hidden');
  $('analyze-completed-banner').classList.add('hidden');
  $('analyze-answers-review').classList.add('hidden');
  $('analyze-summary-output').classList.add('hidden');
  document.querySelector('input[name="analyze-method"][value="5why"]').checked = true;
}

function restoreAnalyzeState(data) {
  $('analyze-method-selector').classList.add('hidden');
  $('analyze-interview').classList.remove('hidden');
  renderAnalyzeInterview(data);
}

function renderAnalyzeInterview(data) {
  const { method, questions, current_index, summary, completed } = data;
  const methodLabels = { '5why': '5-Why', 'swot': 'SWOT', 'fishbone': 'Fishbone' };
  $('analyze-method-badge').textContent = methodLabels[method] || method.toUpperCase();

  const total = questions.length;
  const idx = Math.min(current_index, total);
  const pct = (idx / total) * 100;
  $('analyze-progress-fill').style.width = pct + '%';
  $('analyze-progress-text').textContent = completed
    ? 'Analysis complete'
    : `Step ${idx + 1} of ${total}`;

  if (!completed && idx < total) {
    const q = questions[idx];
    $('analyze-q-number').textContent = methodLabels[method] || `Step ${idx + 1}`;
    $('analyze-q-text').textContent = q.question;
    $('analyze-suggestion-text').textContent = q.suggestion || 'Generating context-aware insight...';
    $('analyze-answer-input').value = '';
    $('analyze-question-card').classList.remove('hidden');
    $('analyze-completed-banner').classList.add('hidden');
    document.querySelector('#analyze-interview .answer-area').classList.remove('hidden');
  } else {
    $('analyze-question-card').classList.add('hidden');
    document.querySelector('#analyze-interview .answer-area').classList.add('hidden');
    $('analyze-completed-banner').classList.remove('hidden');
    renderAnalyzeAnswers(questions, method);
  }

  if (summary) {
    $('analyze-summary-output').classList.remove('hidden');
    setHtml($('analyze-summary-text'), summary);
    $('analyze-summary-btn').classList.add('hidden');
  } else if (completed) {
    $('analyze-summary-btn').classList.remove('hidden');
  }
}

function renderAnalyzeAnswers(questions, method) {
  $('analyze-answers-review').classList.remove('hidden');
  $('analyze-answers-list').innerHTML = questions.map((q, i) => `
    <div class="answer-review-item">
      <div class="answer-review-q">${q.question}</div>
      <div class="answer-review-a">${q.answer || '<em style="color:var(--text-muted)">Not answered</em>'}</div>
    </div>
  `).join('');
}

$('analyze-start-btn').addEventListener('click', async () => {
  if (!currentSession) { showToast('Select a session first', 'error'); return; }
  const ideate = currentSession.ideate_data || {};
  if (!ideate.completed && !ideate.summary) {
    showToast('Complete Ideate stage first', 'error'); return;
  }
  const method = document.querySelector('input[name="analyze-method"]:checked').value;
  showLoading();
  try {
    const data = await api('POST', `/api/sessions/${currentSession.id}/analyze/start`, { method });
    if (!data) return;
    currentSession.analyze_data = data.analyze_data;
    $('analyze-method-selector').classList.add('hidden');
    $('analyze-interview').classList.remove('hidden');
    renderAnalyzeInterview(data.analyze_data);
  } catch (err) { showToast(err.message, 'error'); }
  finally { hideLoading(); }
});

$('analyze-change-method-btn').addEventListener('click', () => {
  if (!confirm('Reset current analysis? Progress will be lost.')) return;
  resetAnalyzeUI();
});

$('analyze-submit-answer-btn').addEventListener('click', async () => {
  const answer = $('analyze-answer-input').value.trim();
  if (!answer) { showToast('Please enter an answer', 'error'); return; }
  showLoading();
  try {
    const data = await api('POST', `/api/sessions/${currentSession.id}/analyze/answer`, { answer });
    if (!data) return;
    currentSession.analyze_data = data.analyze_data;
    renderAnalyzeInterview(data.analyze_data);
    if (data.analyze_data.completed) await refreshSessionStatus();
  } catch (err) { showToast(err.message, 'error'); }
  finally { hideLoading(); }
});

$('analyze-answer-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    $('analyze-submit-answer-btn').click();
  }
});

$('analyze-summary-btn').addEventListener('click', async () => {
  const output = $('analyze-summary-output');
  const textEl = $('analyze-summary-text');
  output.classList.remove('hidden');
  $('analyze-summary-btn').disabled = true;
  textEl.innerHTML = '';
  textEl.classList.add('stream-target');
  let full = '';
  try {
    await stream(
      `/api/sessions/${currentSession.id}/analyze/summary`,
      {},
      chunk => { full += chunk; setHtml(textEl, full); },
      finalText => {
        textEl.classList.remove('stream-target');
        textEl.classList.add('done');
        if (currentSession.analyze_data) currentSession.analyze_data.summary = finalText;
      }
    );
  } catch (err) { showToast(err.message, 'error'); }
  finally { $('analyze-summary-btn').disabled = false; }
});

$('analyze-summary-confirm-btn').addEventListener('click', () => {
  refreshSessionStatus();
  showToast('Analysis confirmed! Moving to Solve.', 'success');
  document.querySelector('[data-tab="solve"]').click();
});

// ══════════════════════════════════════════════════════
// SOLVE TAB
// ══════════════════════════════════════════════════════

function resetSolveUI() {
  $('solve-init').classList.remove('hidden');
  $('solve-chat-interface').classList.add('hidden');
  $('solve-messages').innerHTML = '';
}

function restoreSolveState(data) {
  $('solve-init').classList.add('hidden');
  $('solve-chat-interface').classList.remove('hidden');
  $('solve-messages').innerHTML = '';
  (data.chat_history || []).forEach(msg => appendChatBubble('solve-messages', msg.role, msg.content));
}

$('solve-init-btn').addEventListener('click', async () => {
  if (!currentSession) { showToast('Select a session first', 'error'); return; }
  $('solve-init').classList.add('hidden');
  $('solve-chat-interface').classList.remove('hidden');
  const messages = $('solve-messages');
  messages.innerHTML = '';

  const bubble = createStreamBubble('solve-messages');
  let full = '';
  try {
    await stream(
      `/api/sessions/${currentSession.id}/solve/init`,
      {},
      chunk => { full += chunk; setHtml(bubble, full); scrollToBottom(messages); },
      async () => {
        bubble.classList.remove('stream-target');
        if (!currentSession.solve_data) currentSession.solve_data = { chat_history: [] };
        currentSession.solve_data.initialized = true;
        await refreshSessionStatus();
      }
    );
  } catch (err) {
    showToast(err.message, 'error');
    $('solve-init').classList.remove('hidden');
    $('solve-chat-interface').classList.add('hidden');
  }
});

$('solve-send-btn').addEventListener('click', () => sendSolveMessage());
$('solve-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendSolveMessage(); }
});

async function sendSolveMessage() {
  const msg = $('solve-input').value.trim();
  if (!msg || !currentSession) return;
  $('solve-input').value = '';
  $('solve-send-btn').disabled = true;

  appendChatBubble('solve-messages', 'user', msg);
  const messages = $('solve-messages');
  const bubble = createStreamBubble('solve-messages');
  let full = '';

  try {
    await stream(
      `/api/sessions/${currentSession.id}/solve/chat`,
      { message: msg },
      chunk => { full += chunk; setHtml(bubble, full); scrollToBottom(messages); },
      async () => {
        bubble.classList.remove('stream-target');
        await refreshSessionStatus();
      }
    );
  } catch (err) { showToast(err.message, 'error'); }
  finally { $('solve-send-btn').disabled = false; $('solve-input').focus(); }
}

// ══════════════════════════════════════════════════════
// TRIZ TAB
// ══════════════════════════════════════════════════════

async function loadTrizData() {
  try {
    trizData = await api('GET', '/api/triz-data');
    populateTrizToolDropdown(1);
    populateTrizParamDropdowns();
  } catch (_) {}
}

function populateTrizToolDropdown(level) {
  const select = $('triz-tool-select');
  if (!trizData) return;
  const tools = trizData.levels[String(level)]?.tools || {};
  select.innerHTML = Object.entries(tools).map(([key, t]) =>
    `<option value="${key}">${t.name}</option>`
  ).join('');

  const matrixParams = $('triz-matrix-params');
  select.addEventListener('change', () => {
    matrixParams.classList.toggle('hidden', select.value !== 'contradiction_matrix');
  });
  matrixParams.classList.add('hidden');
}

function populateTrizParamDropdowns() {
  if (!trizData) return;
  const params = trizData.engineering_parameters || {};
  const opts = Object.entries(params).map(([k, v]) => `<option value="${k}">${k}. ${v}</option>`).join('');
  $('triz-improving-param').innerHTML = opts;
  $('triz-worsening-param').innerHTML = opts;
  if ($('triz-worsening-param').options.length > 1) $('triz-worsening-param').selectedIndex = 1;
}

$$('input[name="triz-level"]').forEach(radio => {
  radio.addEventListener('change', () => {
    populateTrizToolDropdown(parseInt(radio.value));
  });
});

function resetTrizUI() {
  $('triz-selector').classList.remove('hidden');
  $('triz-results').classList.add('hidden');
  $('triz-analysis-output').innerHTML = '';
  $('triz-messages').innerHTML = '';
}

function restoreTrizState(data) {
  $('triz-selector').classList.add('hidden');
  $('triz-results').classList.remove('hidden');
  if (data.analysis_result) {
    setHtml($('triz-analysis-output'), data.analysis_result);
    $('triz-analysis-output').classList.add('done');
  }
  $('triz-messages').innerHTML = '';
  const history = data.chat_history || [];
  // Skip first item (it's the analysis itself, not a chat message)
  history.slice(1).forEach(msg => appendChatBubble('triz-messages', msg.role, msg.content));
  updateTrizResultHeader(data.level, data.tool);
}

function updateTrizResultHeader(level, tool) {
  if (!trizData) return;
  const toolName = trizData.levels?.[String(level)]?.tools?.[tool]?.name || tool;
  $('triz-result-badge').textContent = `L${level}`;
  $('triz-result-title').textContent = toolName;
}

$('triz-analyze-btn').addEventListener('click', async () => {
  if (!currentSession) { showToast('Select a session first', 'error'); return; }
  const level = parseInt(document.querySelector('input[name="triz-level"]:checked').value);
  const tool = $('triz-tool-select').value;
  const extraParams = {};
  if (tool === 'contradiction_matrix') {
    extraParams.improving_param = $('triz-improving-param').value;
    extraParams.worsening_param = $('triz-worsening-param').value;
  }

  $('triz-selector').classList.add('hidden');
  $('triz-results').classList.remove('hidden');
  $('triz-analysis-output').innerHTML = '';
  $('triz-analysis-output').classList.remove('done');
  $('triz-analysis-output').classList.add('stream-target');
  $('triz-messages').innerHTML = '';
  updateTrizResultHeader(level, tool);

  const output = $('triz-analysis-output');
  let full = '';
  try {
    await stream(
      `/api/sessions/${currentSession.id}/triz/analyze`,
      { level, tool, extra_params: extraParams },
      chunk => { full += chunk; setHtml(output, full); },
      async () => {
        output.classList.remove('stream-target');
        output.classList.add('done');
        if (currentSession.triz_data) {
          currentSession.triz_data.analysis_result = full;
        }
        await refreshSessionStatus();
      }
    );
  } catch (err) { showToast(err.message, 'error'); }
});

$('triz-new-analysis-btn').addEventListener('click', () => resetTrizUI());

$('triz-send-btn').addEventListener('click', () => sendTrizMessage());
$('triz-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendTrizMessage(); }
});

async function sendTrizMessage() {
  const msg = $('triz-input').value.trim();
  if (!msg || !currentSession) return;
  $('triz-input').value = '';
  $('triz-send-btn').disabled = true;

  appendChatBubble('triz-messages', 'user', msg);
  const messages = $('triz-messages');
  const bubble = createStreamBubble('triz-messages');
  let full = '';

  try {
    await stream(
      `/api/sessions/${currentSession.id}/triz/chat`,
      { message: msg },
      chunk => { full += chunk; setHtml(bubble, full); scrollToBottom(messages); },
      () => { bubble.classList.remove('stream-target'); }
    );
  } catch (err) { showToast(err.message, 'error'); }
  finally { $('triz-send-btn').disabled = false; $('triz-input').focus(); }
}

// ══════════════════════════════════════════════════════
// PATENT TAB
// ══════════════════════════════════════════════════════

function resetPatentUI() {
  ['claims', 'prior-art', 'circumvent', 'draft', 'search-strings'].forEach(step => {
    const outputId = `patent-${step.replace('-','')}-output`;
    $(outputId)?.classList.add('hidden');
    const textId = step === 'prior-art' ? 'patent-prior-art-text'
                 : step === 'search-strings' ? 'patent-search-strings-text'
                 : step === 'draft' ? 'patent-draft-text'
                 : `patent-${step}-text`;
    const el = $(textId);
    if (el) el.innerHTML = '';
  });
  $('patent-prior-art-btn').disabled = true;
  $('patent-circumvent-btn').disabled = true;
  $('patent-draft-btn').disabled = true;
  $('patent-generate-claims-btn').disabled = false;
  $('patent-claims-output').classList.add('hidden');
  $('patent-prior-art-output').classList.add('hidden');
  $('patent-circumvent-output').classList.add('hidden');
  $('patent-draft-output').classList.add('hidden');
  $('patent-search-strings-output').classList.add('hidden');
}

function restorePatentState(data) {
  if (!data || !data.claims) { resetPatentUI(); return; }

  if (data.claims) {
    $('patent-claims-output').classList.remove('hidden');
    setHtml($('patent-claims-text'), data.claims);
    $('patent-prior-art-btn').disabled = false;
  }
  if (data.prior_art) {
    $('patent-prior-art-output').classList.remove('hidden');
    setHtml($('patent-prior-art-text'), data.prior_art);
    $('patent-circumvent-btn').disabled = false;
  }
  if (data.circumvention) {
    $('patent-circumvent-output').classList.remove('hidden');
    setHtml($('patent-circumvent-text'), data.circumvention);
    $('patent-draft-btn').disabled = false;
  }
  if (data.draft) {
    $('patent-draft-output').classList.remove('hidden');
    setHtml($('patent-draft-text'), data.draft);
  }
  if (data.search_strings) {
    $('patent-search-strings-output').classList.remove('hidden');
    setHtml($('patent-search-strings-text'), data.search_strings);
  }
}

async function runPatentStep(stepName, btnId, outputId, textId, enableNext) {
  if (!currentSession) { showToast('Select a session first', 'error'); return; }
  const btn = $(btnId);
  const output = $(outputId);
  const textEl = $(textId);
  btn.disabled = true;
  output.classList.remove('hidden');
  textEl.innerHTML = '';
  textEl.classList.add('stream-target');

  let full = '';
  try {
    await stream(
      `/api/sessions/${currentSession.id}/patent/${stepName}`,
      {},
      chunk => { full += chunk; setHtml(textEl, full); },
      async () => {
        textEl.classList.remove('stream-target');
        textEl.classList.add('done');
        if (enableNext) $(enableNext).disabled = false;
        if (!currentSession.patent_data) currentSession.patent_data = {};
        if (stepName === 'claims') currentSession.patent_data.claims = full;
        if (stepName === 'prior-art') currentSession.patent_data.prior_art = full;
        if (stepName === 'circumvent') currentSession.patent_data.circumvention = full;
        if (stepName === 'draft') {
          currentSession.patent_data.draft = full;
          await refreshSessionStatus();
        }
      }
    );
  } catch (err) {
    showToast(err.message, 'error');
    btn.disabled = false;
  }
}

$('patent-generate-claims-btn').addEventListener('click', () =>
  runPatentStep('claims', 'patent-generate-claims-btn', 'patent-claims-output',
    'patent-claims-text', 'patent-prior-art-btn')
);
$('patent-prior-art-btn').addEventListener('click', () =>
  runPatentStep('prior-art', 'patent-prior-art-btn', 'patent-prior-art-output',
    'patent-prior-art-text', 'patent-circumvent-btn')
);
$('patent-circumvent-btn').addEventListener('click', () =>
  runPatentStep('circumvent', 'patent-circumvent-btn', 'patent-circumvent-output',
    'patent-circumvent-text', 'patent-draft-btn')
);
$('patent-draft-btn').addEventListener('click', () =>
  runPatentStep('draft', 'patent-draft-btn', 'patent-draft-output',
    'patent-draft-text', null)
);

$('patent-copy-btn').addEventListener('click', () => {
  navigator.clipboard.writeText($('patent-draft-text').innerText || '')
    .then(() => showToast('Draft copied to clipboard!', 'success'))
    .catch(() => showToast('Copy failed', 'error'));
});

$('patent-print-btn').addEventListener('click', () => {
  const content = $('patent-draft-text').innerHTML || '';
  if (!content.trim()) { showToast('Generate the draft first', 'error'); return; }
  const sessionName = currentSession?.name || 'Patent Draft';

  // Collect all patent sections into the export
  const sections = [];
  const claimsHtml = $('patent-claims-text')?.innerHTML?.trim();
  const priorArtHtml = $('patent-prior-art-text')?.innerHTML?.trim();
  const circumventHtml = $('patent-circumvent-text')?.innerHTML?.trim();
  const draftHtml = $('patent-draft-text')?.innerHTML?.trim();

  if (claimsHtml) sections.push(`<section><h2>PATENT CLAIMS</h2>${claimsHtml}</section>`);
  if (priorArtHtml) sections.push(`<section><h2>PRIOR ART ANALYSIS</h2>${priorArtHtml}</section>`);
  if (circumventHtml) sections.push(`<section><h2>CIRCUMVENTION STRATEGY</h2>${circumventHtml}</section>`);
  if (draftHtml) sections.push(`<section><h2>FULL PATENT DRAFT</h2>${draftHtml}</section>`);

  const win = window.open('', '_blank');
  win.document.write(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>${sessionName} — Patent Report</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Times New Roman', Georgia, serif;
      font-size: 12pt; line-height: 1.75;
      color: #111; background: #fff;
      max-width: 800px; margin: 48px auto; padding: 0 32px;
    }
    .cover {
      text-align: center; padding: 60px 0 40px;
      border-bottom: 2px solid #111; margin-bottom: 40px;
    }
    .cover h1 { font-size: 22pt; font-weight: bold; margin-bottom: 12px; }
    .cover p { font-size: 11pt; color: #555; }
    section { margin-bottom: 48px; page-break-inside: avoid; }
    section h2 {
      font-size: 14pt; font-weight: bold; text-transform: uppercase;
      letter-spacing: 0.06em; border-bottom: 1px solid #ccc;
      padding-bottom: 6px; margin-bottom: 18px; margin-top: 0;
      color: #222;
    }
    h1 { font-size: 16pt; margin: 20px 0 10px; }
    h2:not(section > h2) { font-size: 14pt; margin: 18px 0 8px; }
    h3 { font-size: 12pt; margin: 14px 0 6px; font-weight: bold; }
    h4 { font-size: 11pt; margin: 10px 0 4px; font-weight: bold; font-style: italic; }
    p { margin-bottom: 10px; }
    ul, ol { padding-left: 24px; margin-bottom: 12px; }
    li { margin-bottom: 4px; }
    strong { font-weight: bold; }
    em { font-style: italic; }
    code {
      font-family: 'Courier New', Courier, monospace;
      font-size: 10pt; background: #f4f4f4;
      padding: 2px 5px; border-radius: 2px;
    }
    pre {
      font-family: 'Courier New', Courier, monospace;
      font-size: 10pt; background: #f4f4f4;
      padding: 14px; border-radius: 4px;
      white-space: pre-wrap; word-wrap: break-word;
      margin-bottom: 14px; border: 1px solid #ddd;
    }
    table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 10pt; }
    th { background: #eee; font-weight: bold; text-align: left; padding: 8px 10px; border: 1px solid #ccc; }
    td { padding: 7px 10px; border: 1px solid #ccc; }
    blockquote { border-left: 3px solid #999; padding-left: 14px; color: #444; margin: 12px 0; }
    hr { border: none; border-top: 1px solid #ccc; margin: 28px 0; }
    @media print {
      body { margin: 0; padding: 20mm 25mm; max-width: none; }
      .cover { page-break-after: always; }
      section { page-break-inside: avoid; }
      pre { page-break-inside: avoid; }
      h2 { page-break-after: avoid; }
    }
  </style>
</head>
<body>
  <div class="cover">
    <h1>${sessionName}</h1>
    <p>Patent Report — Generated by InnovateTool</p>
    <p>${new Date().toLocaleDateString('en-GB', { day:'numeric', month:'long', year:'numeric' })}</p>
  </div>
  ${sections.join('\n')}
</body>
</html>`);
  win.document.close();
  win.focus();
  // Small delay so browser finishes rendering before print dialog
  setTimeout(() => { win.print(); }, 600);
});

// ── Patent Search Strings (Step 5) ──
$('patent-search-strings-btn').addEventListener('click', async () => {
  if (!currentSession) { showToast('Select a session first', 'error'); return; }
  const btn = $('patent-search-strings-btn');
  const output = $('patent-search-strings-output');
  const textEl = $('patent-search-strings-text');
  btn.disabled = true;
  output.classList.remove('hidden');
  textEl.innerHTML = '';
  textEl.classList.add('stream-target');
  let full = '';
  try {
    await stream(
      `/api/sessions/${currentSession.id}/patent/search-strings`,
      {},
      chunk => { full += chunk; setHtml(textEl, full); },
      () => {
        textEl.classList.remove('stream-target');
        textEl.classList.add('done');
        if (!currentSession.patent_data) currentSession.patent_data = {};
        currentSession.patent_data.search_strings = full;
      }
    );
  } catch (err) { showToast(err.message, 'error'); }
  finally { btn.disabled = false; }
});

$('patent-search-copy-btn').addEventListener('click', () => {
  navigator.clipboard.writeText($('patent-search-strings-text').innerText || '')
    .then(() => showToast('Search strings copied!', 'success'))
    .catch(() => showToast('Copy failed', 'error'));
});

// ══════════════════════════════════════════════════════
// ADMIN TELEMETRY TAB
// ══════════════════════════════════════════════════════

async function loadAdminTelemetry() {
  if (currentUser?.role !== 'admin') return;
  try {
    const data = await api('GET', '/api/admin/telemetry');
    if (!data) return;
    renderAdminDashboard(data);
  } catch (err) { console.warn('Telemetry load failed:', err.message); }
}

function renderAdminDashboard(data) {
  // KPIs
  $('kpi-users').textContent = data.total_users ?? 0;
  $('kpi-sessions').textContent = (data.sessions || []).length;
  const totalTokens = (data.token_usage_per_user || []).reduce((s, u) => s + (u.total_tokens || 0), 0);
  $('kpi-tokens').textContent = totalTokens > 1000 ? (totalTokens / 1000).toFixed(1) + 'K' : totalTokens;
  $('kpi-completions').textContent = (data.checkpoints || []).length;

  // Token usage chart
  const userLabels = (data.token_usage_per_user || []).map(u => u.username);
  const userTokens = (data.token_usage_per_user || []).map(u => u.total_tokens || 0);
  renderChart('token-chart', 'bar', userLabels, [{ label: 'Tokens', data: userTokens, backgroundColor: 'rgba(79,142,247,0.7)' }]);

  // Stage completion chart
  const stageMap = {};
  (data.stage_stats || []).forEach(s => { stageMap[s.stage] = (stageMap[s.stage] || 0) + s.count; });
  const stages = ['context', 'ideate', 'analyze', 'solve', 'triz', 'patent'];
  const stageCounts = stages.map(s => stageMap[s] || 0);
  const stageColors = ['#4f8ef7','#8b5cf6','#10d98a','#f7a04f','#f7d24f','#f75f5f'];
  renderChart('stage-chart', 'doughnut', stages.map(s => s.charAt(0).toUpperCase() + s.slice(1)),
    [{ data: stageCounts, backgroundColor: stageColors }]);

  // Daily usage chart
  const dailyMap = {};
  (data.daily_usage || []).forEach(d => {
    dailyMap[d.date] = (dailyMap[d.date] || 0) + (d.tokens || 0);
  });
  const dailyLabels = Object.keys(dailyMap).sort().slice(-30);
  const dailyValues = dailyLabels.map(d => dailyMap[d]);
  renderChart('daily-chart', 'line', dailyLabels, [{
    label: 'Tokens/day', data: dailyValues,
    borderColor: 'rgba(139,92,246,0.9)',
    backgroundColor: 'rgba(139,92,246,0.1)',
    fill: true, tension: 0.4,
    pointRadius: 3
  }]);

  // Pipeline table
  renderPipelineTable(data);
}

function renderChart(id, type, labels, datasets) {
  const canvas = $(id);
  if (!canvas) return;
  if (adminCharts[id]) { adminCharts[id].destroy(); }
  adminCharts[id] = new Chart(canvas, {
    type,
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { labels: { color: '#8892b0', font: { size: 11 } } } },
      scales: type === 'bar' || type === 'line' ? {
        x: { ticks: { color: '#8892b0', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
        y: { ticks: { color: '#8892b0', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.05)' } }
      } : undefined
    }
  });
}

function renderPipelineTable(data) {
  const stages = ['context', 'ideate', 'analyze', 'solve', 'triz', 'patent'];
  const userMap = {};
  (data.token_usage_per_user || []).forEach(u => { userMap[u.username] = u; });

  const stageByUser = {};
  (data.checkpoints || []).forEach(cp => {
    if (!stageByUser[cp.username]) stageByUser[cp.username] = new Set();
    stageByUser[cp.username].add(cp.stage);
  });

  const tbody = $('pipeline-table-body');
  const users = Object.keys(userMap);
  if (!users.length) { tbody.innerHTML = '<tr><td colspan="9" style="color:var(--text-muted);text-align:center">No data yet</td></tr>'; return; }

  tbody.innerHTML = users.map(username => {
    const u = userMap[username];
    const completed = stageByUser[username] || new Set();
    const stageDots = stages.map(s =>
      `<td><span class="status-dot ${completed.has(s) ? 'done' : 'pending'}" title="${s}"></span></td>`
    ).join('');
    return `
      <tr>
        <td><strong>${username}</strong></td>
        <td>${u.session_count || 0}</td>
        <td>${(u.total_tokens || 0).toLocaleString()}</td>
        ${stageDots}
      </tr>
    `;
  }).join('');
}

// Admin chat
$('admin-chat-send-btn').addEventListener('click', () => sendAdminMessage());
$('admin-chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAdminMessage(); }
});

async function sendAdminMessage() {
  const msg = $('admin-chat-input').value.trim();
  if (!msg) return;
  $('admin-chat-input').value = '';
  $('admin-chat-send-btn').disabled = true;

  appendChatBubble('admin-messages', 'user', msg);
  const messages = $('admin-messages');
  const bubble = createStreamBubble('admin-messages');
  let full = '';

  try {
    await stream(
      '/api/admin/chat',
      { message: msg, chat_history: adminChatHistory },
      chunk => { full += chunk; setHtml(bubble, full); scrollToBottom(messages); },
      () => {
        bubble.classList.remove('stream-target');
        adminChatHistory.push({ role: 'user', content: msg });
        adminChatHistory.push({ role: 'assistant', content: full });
        if (adminChatHistory.length > 20) adminChatHistory = adminChatHistory.slice(-20);
      }
    );
  } catch (err) { showToast(err.message, 'error'); }
  finally { $('admin-chat-send-btn').disabled = false; }
}

$('admin-refresh-btn').addEventListener('click', () => {
  loadAdminTelemetry();
  showToast('Telemetry refreshed', 'info');
});

// ══════════════════════════════════════════════════════
// CHAT HELPERS
// ══════════════════════════════════════════════════════

function appendChatBubble(containerId, role, content) {
  const container = $(containerId);
  const div = document.createElement('div');
  div.className = `chat-bubble ${role}`;
  if (role === 'assistant') {
    setHtml(div, content);
  } else {
    div.textContent = content;
  }
  container.appendChild(div);
  scrollToBottom(container);
  return div;
}

function createStreamBubble(containerId) {
  const container = $(containerId);
  const div = document.createElement('div');
  div.className = 'chat-bubble assistant stream-target markdown-output';
  container.appendChild(div);
  scrollToBottom(container);
  return div;
}

function scrollToBottom(el) {
  el.scrollTop = el.scrollHeight;
}

// ══════════════════════════════════════════════════════
// BOOT
// ══════════════════════════════════════════════════════

init();
