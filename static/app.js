const $ = (id) => document.getElementById(id);

const form = $('config-form');
const target = $('target');
const vus = $('vus');
const duration = $('duration');
const ramp = $('ramp');
const think = $('think');
const userAgent = $('user-agent');
const chunk = $('chunk');
const own = $('own');
const startButton = $('start-button');
const fullButton = $('full-button');
const stopButton = $('stop-button');
const resetButton = $('reset-button');
const message = $('message');
const statusBadge = $('status-badge');
const runStatus = $('run-status');
const runTarget = $('run-target');
const runVus = $('run-vus');
const runDuration = $('run-duration');
const runElapsed = $('run-elapsed');
const runExit = $('run-exit');
const runId = $('run-id');
const log = $('log');
const summaryLink = $('summary-link');
const logLink = $('log-link');
const campaignBox = $('campaign-box');
const campaignProgress = $('campaign-progress');
const campaignBar = $('campaign-bar');
const campaignStatus = $('campaign-status');
const campaignChunk = $('campaign-chunk');
const campaignSession = $('campaign-session');
const chunksBox = $('chunks');
const estimate = $('estimate');
const codespaceEstimate = $('codespace-estimate');

const STORAGE_KEY = 'loadtest-codespace-config';
let lastStatus = null;

function readForm() {
  return {
    target: target.value.trim(),
    vus: Number(vus.value),
    duration_minutes: Number(duration.value),
    total_minutes: Number(duration.value),
    ramp_up_seconds: Number(ramp.value),
    think_time_seconds: Number(think.value),
    user_agent: userAgent.value.trim() || 'loadtest-codespace/1.0',
    chunk_minutes: Number(chunk.value),
  };
}

function saveForm() {
  const data = readForm();
  data.own = own.checked;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch (error) {
    return;
  }
}

function loadForm() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    if (data.target) target.value = data.target;
    if (data.vus) vus.value = data.vus;
    if (data.duration_minutes) duration.value = data.duration_minutes;
    if (data.ramp_up_seconds !== undefined) ramp.value = data.ramp_up_seconds;
    if (data.think_time_seconds !== undefined) think.value = data.think_time_seconds;
    if (data.user_agent) userAgent.value = data.user_agent;
    if (data.chunk_minutes) chunk.value = data.chunk_minutes;
    if (data.own) own.checked = true;
  } catch (error) {
    localStorage.removeItem(STORAGE_KEY);
  }
}

function setMessage(text, kind) {
  message.textContent = text || '';
  message.className = 'note' + (kind ? ' ' + kind : '');
}

function fmtDuration(seconds) {
  const total = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((value) => String(value).padStart(2, '0')).join(':');
}

function updateEstimate() {
  const v = Number(vus.value) || 0;
  const minutes = Number(duration.value) || 0;
  const vuHours = (v * minutes) / 60;
  estimate.textContent = `${vuHours.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} vu-hours`;
  const coreHours = (minutes / 60) * 4;
  codespaceEstimate.textContent = `~${coreHours.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} core-hours`;
}

function renderCampaign(campaign) {
  if (!campaign) {
    campaignBox.hidden = true;
    chunksBox.innerHTML = '';
    return;
  }
  campaignBox.hidden = false;
  const total = campaign.total_minutes || 0;
  const done = campaign.completed_minutes || 0;
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0;
  campaignProgress.textContent = `${done} / ${total} min`;
  campaignBar.style.width = `${pct}%`;
  campaignStatus.textContent = campaign.status;
  campaignChunk.textContent = campaign.current_chunk
    ? `chunk ${campaign.current_chunk} / ${campaign.chunks_total}`
    : `${campaign.chunks_completed} / ${campaign.chunks_total} chunks`;
  campaignSession.textContent = `session ${fmtDuration(lastStatus ? lastStatus.session_elapsed_seconds : 0)}`;
  chunksBox.innerHTML = '';
  for (const item of campaign.chunks || []) {
    const row = document.createElement('div');
    row.className = 'chunk';
    const index = document.createElement('strong');
    index.textContent = String(item.index).padStart(2, '0');
    const label = document.createElement('span');
    label.textContent = `${item.minutes} min · ${item.status}`;
    const link = document.createElement('a');
    if (item.summary_url) {
      link.href = item.summary_url;
      link.textContent = 'summary';
    } else if (item.log_url) {
      link.href = item.log_url;
      link.textContent = 'log';
    }
    row.append(index, label, link);
    chunksBox.append(row);
  }
}

function render(data) {
  lastStatus = data;
  const status = data.status || 'idle';
  statusBadge.textContent = status;
  statusBadge.className = 'status ' + status;
  runStatus.textContent = status;
  runId.textContent = data.run_id || 'no run';
  if (data.config) {
    runTarget.textContent = data.config.target || '-';
    runVus.textContent = data.config.vus || '-';
    runDuration.textContent = `${data.config.duration_minutes || 0} min`;
  } else {
    runTarget.textContent = '-';
    runVus.textContent = '-';
    runDuration.textContent = '-';
  }
  runElapsed.textContent = fmtDuration(data.elapsed_seconds);
  runExit.textContent = data.exit_code === null || data.exit_code === undefined ? '-' : data.exit_code;
  if (data.log !== undefined) {
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
    log.textContent = data.log || 'waiting for a run';
    if (atBottom) log.scrollTop = log.scrollHeight;
  }
  if (data.summary_url) {
    summaryLink.hidden = false;
    summaryLink.href = data.summary_url;
  } else {
    summaryLink.hidden = true;
    summaryLink.removeAttribute('href');
  }
  if (data.log_url) {
    logLink.hidden = false;
    logLink.href = data.log_url;
  } else {
    logLink.hidden = true;
    logLink.removeAttribute('href');
  }
  renderCampaign(data.campaign);
  const running = status === 'running' || status === 'stopping';
  startButton.disabled = running;
  fullButton.disabled = running;
  stopButton.disabled = !running;
  resetButton.disabled = running;
  if (data.campaign) {
    const campaign = data.campaign;
    if (campaign.status === 'paused') {
      fullButton.textContent = 'continue campaign';
      fullButton.disabled = running;
      startButton.disabled = true;
    } else if (campaign.status === 'completed') {
      fullButton.textContent = 'campaign completed';
      fullButton.disabled = true;
      startButton.disabled = true;
    } else if (campaign.status === 'running') {
      fullButton.textContent = 'campaign running';
      fullButton.disabled = true;
      startButton.disabled = true;
    }
  } else {
    fullButton.textContent = 'full power';
  }
  if (data.error) {
    setMessage(data.error, 'error');
  }
}

async function request(path, body) {
  const options = { method: 'POST', headers: { 'Content-Type': 'application/json' } };
  if (body) options.body = JSON.stringify(body);
  const response = await fetch(path, options);
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = { error: 'invalid response' };
  }
  if (!response.ok) {
    throw new Error(data.error || `http ${response.status}`);
  }
  return data;
}

function ensureReady() {
  if (!target.value.trim()) {
    target.focus();
    throw new Error('укажи target url');
  }
  if (!own.checked) {
    own.focus();
    throw new Error('подтверди, что сайт твой');
  }
}

async function startSingle(event) {
  event.preventDefault();
  try {
    ensureReady();
    const data = readForm();
    if (data.duration_minutes > 600) {
      throw new Error('single run max 600 min, используй full power');
    }
    saveForm();
    setMessage('запускаю', 'ok');
    const result = await request('/start', data);
    render(result);
  } catch (error) {
    setMessage(error.message, 'error');
  }
}

async function fullPower() {
  try {
    ensureReady();
    if (lastStatus && lastStatus.campaign && lastStatus.campaign.status === 'paused') {
      const session = lastStatus.session_elapsed_seconds || 0;
      const nextChunk = lastStatus.campaign.chunks.find((item) => item.status === 'pending' || item.status === 'interrupted');
      if (nextChunk && session + nextChunk.minutes * 60 > 11 * 3600) {
        const ok = confirm('сессия уже длинная. codespace может умереть на 12h. лучше остановить и запустить заново. продолжить?');
        if (!ok) return;
      }
      setMessage('продолжаю кампанию', 'ok');
      const result = await request('/continue');
      render(result);
      return;
    }
    if (lastStatus && lastStatus.campaign) {
      throw new Error('сначала reset campaign');
    }
    vus.value = 500;
    duration.value = 1000;
    ramp.value = 5;
    think.value = 0;
    chunk.value = 500;
    updateEstimate();
    saveForm();
    const data = readForm();
    setMessage('запускаю full power: 500 vu, 1000 min, 2 chunks', 'ok');
    const result = await request('/start-campaign', data);
    render(result);
  } catch (error) {
    setMessage(error.message, 'error');
  }
}

async function stopRun() {
  try {
    const result = await request('/stop');
    render(result);
    setMessage('останавливаю', 'ok');
  } catch (error) {
    setMessage(error.message, 'error');
  }
}

async function resetCampaign() {
  if (!confirm('удалить активную кампанию? summary и логи останутся.')) return;
  try {
    const result = await request('/reset');
    render(result);
    setMessage('кампания сброшена', 'ok');
  } catch (error) {
    setMessage(error.message, 'error');
  }
}

async function poll() {
  try {
    const response = await fetch('/status', { cache: 'no-store' });
    if (response.ok) {
      render(await response.json());
    }
  } catch (error) {
    statusBadge.textContent = 'offline';
    statusBadge.className = 'status failed';
  }
  setTimeout(poll, 2000);
}

form.addEventListener('submit', startSingle);
fullButton.addEventListener('click', fullPower);
stopButton.addEventListener('click', stopRun);
resetButton.addEventListener('click', resetCampaign);
for (const input of [vus, duration, ramp, think, chunk]) {
  input.addEventListener('input', updateEstimate);
}
loadForm();
updateEstimate();
poll();
