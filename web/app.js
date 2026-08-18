/**
 * app.js — KhmerAI Studio SaaS Application Controller
 * ====================================================
 * Manages studio workflows, real-time SSE progress streaming,
 * story templates, scene preview inspector, video players,
 * social media publisher toolkit, and project history.
 */

'use strict';

// ── CONFIGURATION & STATE ────────────────────────────────────
let currentJobId = null;
let currentEventSource = null;
let currentMode = 'ai_generate'; // 'ai_generate' | 'paste_story'
let selectedStyle = 'dramatic';
let previewedScenes = null;

const PROMPT_TEMPLATES = {
  legend: "រឿងព្រេងខ្មែរបុរាណនិយាយពីអ្នកក្លាហានដែលការពារនគរពីបិសាច និងការស្វែងរកដាវទិព្វនៅប្រាសាទបុរាណ",
  cyberpunk: "A futuristic cyberpunk version of Phnom Penh in the year 2150 with neon lights, flying tuk-tuks, and AI monks",
  ghost: "A spine-chilling midnight mystery set inside the deep forgotten corridors of Angkor Wat ruins",
  romance: "រឿងកុលាបប៉ៃលិន — a legendary tale of true love, perseverance, and jewel mines in the emerald mountains of Pailin",
  bokator: "An epic martial arts story of an ancient Khmer Bokator master fighting to protect his village",
  fable: "រឿងនិទានអប់រំកុមារបែបកំប្លែងអំពីសត្វទន្សាយមានប្រាជ្ញាឈ្លាសវៃ និងសត្វក្រពើ"
};

const PROMPT_IDEAS = [
  "រឿងព្រេងខ្មែរបុរាណនិយាយពីអ្នកក្លាហានដែលការពារនគរពីបិសាច",
  "A cyberpunk version of Phnom Penh in the year 2150 with flying vehicles",
  "រឿងកំប្លែងនិយាយពីសត្វឆ្កែមួយក្បាលដែលចេះនិយាយភាសាខ្មែរ",
  "A dramatic story about a young apsara dancer finding her inner strength",
  "រឿងស្នេហាកំសត់នៅសម័យលង្វែក",
  "A mysterious thriller set in the ruins of Angkor Wat at midnight",
  "រឿងនិទានអប់រំកុមារអំពីសត្វទន្សាយមានប្រាជ្ញា",
  "An action-packed heroic tale of an ancient Bokator master"
];

// Helper Selectors
const $ = (id) => document.getElementById(id);

function getApiUrl() {
  const inputVal = $('api-url-input')?.value?.trim();
  if (inputVal) {
    localStorage.setItem('khmer_api_url', inputVal);
    return inputVal.replace(/\/$/, '');
  }
  const saved = localStorage.getItem('khmer_api_url');
  if (saved) return saved.replace(/\/$/, '');
  if (window.KHMER_API_URL) return window.KHMER_API_URL.replace(/\/$/, '');

  const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  if (isLocal) {
    return window.location.origin.includes(':') ? window.location.origin : 'http://localhost:8000';
  }
  return '';
}

// ── INITIALIZATION ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Load saved backend URL
  const savedUrl = localStorage.getItem('khmer_api_url');
  if (savedUrl && $('api-url-input')) {
    $('api-url-input').value = savedUrl;
  }

  // Character counter listeners
  $('story-prompt')?.addEventListener('input', (e) => {
    $('prompt-char-count').textContent = `${e.target.value.length} chars`;
  });
  $('story-text')?.addEventListener('input', (e) => {
    $('text-char-count').textContent = `${e.target.value.length} chars`;
  });
});

// ── VIEW SWITCHING ───────────────────────────────────────────
function switchMainView(view) {
  $('nav-btn-studio')?.classList.toggle('active', view === 'studio');
  $('nav-btn-gallery')?.classList.toggle('active', view === 'gallery');

  if (view === 'studio') {
    $('studio-view-container')?.classList.remove('hidden');
    $('gallery-view')?.classList.add('hidden');
  } else if (view === 'gallery') {
    $('studio-view-container')?.classList.add('hidden');
    $('gallery-view')?.classList.remove('hidden');
    fetchRecentJobs();
  }
}

// ── SCRIPT ENGINE MODE SWITCHER ──────────────────────────────
function switchMode(mode) {
  currentMode = mode;
  $('tab-ai')?.classList.toggle('active', mode === 'ai_generate');
  $('tab-paste')?.classList.toggle('active', mode === 'paste_story');

  $('pane-ai')?.classList.toggle('active', mode === 'ai_generate');
  $('pane-ai')?.classList.toggle('hidden', mode !== 'ai_generate');
  $('pane-paste')?.classList.toggle('active', mode === 'paste_story');
  $('pane-paste')?.classList.toggle('hidden', mode !== 'paste_story');
}

function toggleTemplateDrawer() {
  $('template-drawer')?.classList.toggle('hidden');
}

function applyTemplate(key) {
  const text = PROMPT_TEMPLATES[key];
  if (!text) return;

  switchMode('ai_generate');
  $('story-prompt').value = text;
  $('prompt-char-count').textContent = `${text.length} chars`;
  $('template-drawer')?.classList.add('hidden');
  showToast('Template applied to prompt field', 'info');
}

function selectStyle(style) {
  selectedStyle = style;
  document.querySelectorAll('.mood-tag').forEach(tag => {
    tag.classList.toggle('active', tag.dataset.style === style);
  });
}

function handleSurpriseMe() {
  const promptInput = $('story-prompt');
  if (!promptInput) return;

  switchMode('ai_generate');
  const randomPrompt = PROMPT_IDEAS[Math.floor(Math.random() * PROMPT_IDEAS.length)];
  promptInput.value = randomPrompt;
  $('prompt-char-count').textContent = `${randomPrompt.length} chars`;
  showToast('Viral concept generated', 'info');
}

function handleSceneSliderChange(val) {
  $('num-scenes-val').textContent = val;
}

// ── SCENE BREAKDOWN PREVIEW MODAL ────────────────────────────
async function handlePreviewScenes() {
  const prompt = currentMode === 'paste_story' ? $('story-text')?.value?.trim() : $('story-prompt')?.value?.trim();
  if (!prompt || prompt.length < 10) {
    showToast('Please enter a story prompt or script first.', 'error');
    return;
  }

  const modal = $('preview-modal');
  const content = $('preview-modal-content');
  modal.classList.remove('hidden');
  content.innerHTML = `
    <div class="loading-spinner-box">
      <div class="studio-spinner"></div>
      <p style="margin-top: 14px; font-size: 0.88rem; color: var(--text-secondary);">Structuring scenes with Gemini 3.6 Flash...</p>
    </div>
  `;

  try {
    const apiUrl = getApiUrl();
    const res = await fetch(`${apiUrl}/api/generate-story`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: prompt,
        num_scenes: parseInt($('num-scenes')?.value || '6', 10),
        style: selectedStyle
      })
    });

    if (!res.ok) throw new Error(`API returned ${res.status}`);
    const data = await res.json();
    previewedScenes = data;

    let scenesHtml = `
      <div style="margin-bottom: 16px;">
        <h4 style="font-size: 1.1rem; color: var(--gold-bright);">${data.story_title || 'Untitled'}</h4>
        <p style="font-size: 0.8rem; color: var(--text-muted);">${data.story_title_en || ''}</p>
      </div>
      <div style="display: flex; flex-direction: column; gap: 12px;">
    `;

    data.scenes.forEach(s => {
      scenesHtml += `
        <div style="background: rgba(0,0,0,0.3); border: 1px solid var(--border-subtle); padding: 12px 14px; border-radius: 8px;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
            <span style="font-weight: 700; font-size: 0.8rem; color: var(--gold);">Scene ${s.scene_id}</span>
            <span style="font-size: 0.72rem; color: var(--violet-light);">${s.mood}</span>
          </div>
          <p style="font-family: 'Noto Sans Khmer', sans-serif; font-size: 0.88rem; color: var(--text-khmer); line-height: 1.6;">${s.khmer_narration}</p>
          <p style="font-size: 0.75rem; color: var(--text-muted); margin-top: 6px;"><strong>Visual:</strong> ${s.visual_prompt}</p>
        </div>
      `;
    });

    scenesHtml += `</div>`;
    content.innerHTML = scenesHtml;
  } catch (err) {
    content.innerHTML = `
      <div style="padding: 20px; text-align: center; color: var(--rose);">
        <p>Failed to generate scene breakdown: ${err.message}</p>
      </div>
    `;
  }
}

function closePreviewModal(e) {
  $('preview-modal')?.classList.add('hidden');
}

function confirmPreviewAndGenerate() {
  closePreviewModal();
  handleGenerate();
}

// ── PRICING & SAAS PLANS MODAL ───────────────────────────────
function openPricingModal() {
  $('pricing-modal')?.classList.remove('hidden');
}

function closePricingModal(e) {
  $('pricing-modal')?.classList.add('hidden');
}

function selectPlan(tier) {
  closePricingModal();
  if (tier === 'pro') {
    showToast('Creator Pro Plan activated for this session', 'success');
  } else {
    showToast(`Selected ${tier.toUpperCase()} tier`, 'info');
  }
}

// ── PIPELINE EXECUTION & REALTIME SSE STREAM ─────────────────
async function handleGenerate() {
  const prompt = currentMode === 'paste_story' ? $('story-text')?.value?.trim() : $('story-prompt')?.value?.trim();
  if (!prompt || prompt.length < 10) {
    showToast('Please enter a story or prompt with at least 10 characters.', 'error');
    return;
  }

  const apiUrl = getApiUrl();
  const numScenes = parseInt($('num-scenes')?.value || '6', 10);
  const exportProfile = $('export-profile')?.value || 'both';
  const ttsProvider = $('tts-provider')?.value || 'gtts';
  const imageProvider = $('image-provider')?.value || 'gemini_imagen';

  // Switch UI to Progress View
  $('progress-view')?.classList.remove('hidden');
  $('results-view')?.classList.add('hidden');
  $('progress-view')?.scrollIntoView({ behavior: 'smooth' });

  updateProgress(0, 'Initializing pipeline...', 'running', 1);
  appendLog(`[START] Triggered job: "${prompt.slice(0, 40)}..." (${numScenes} scenes, ${exportProfile})`);

  try {
    const res = await fetch(`${apiUrl}/api/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: prompt,
        mode: currentMode,
        num_scenes: numScenes,
        export_profile: exportProfile,
        tts_provider: ttsProvider,
        image_provider: imageProvider,
        story_style: selectedStyle
      })
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentJobId = data.job_id;
    appendLog(`[JOB] Assigned Job ID: ${currentJobId}`);

    listenToSseProgress(apiUrl, currentJobId);
  } catch (err) {
    showToast(`Generation failed: ${err.message}`, 'error');
    appendLog(`[ERROR] ${err.message}`);
    updateProgress(0, `Error: ${err.message}`, 'failed', 1);
  }
}

function listenToSseProgress(apiUrl, jobId) {
  if (currentEventSource) {
    currentEventSource.close();
  }

  const sseUrl = `${apiUrl}/api/progress/${jobId}`;
  currentEventSource = new EventSource(sseUrl);

  currentEventSource.onmessage = (event) => {
    if (!event.data) return;
    try {
      const payload = JSON.parse(event.data);
      handleProgressEvent(payload);
    } catch (e) {}
  };

  currentEventSource.onerror = () => {
    // If SSE drops, poll job status as fallback
    pollJobStatus(apiUrl, jobId);
  };
}

function handleProgressEvent(data) {
  const { step, progress_pct, message, status } = data;
  updateProgress(progress_pct, message, status, step);
  appendLog(`[STEP ${step || 0}] ${message} (${progress_pct}%)`);

  if (progress_pct >= 100 || status === 'done') {
    if (currentEventSource) currentEventSource.close();
    showToast('Video rendering complete!', 'success');
    fetchCompletedJob(getApiUrl(), currentJobId);
  } else if (status === 'failed') {
    if (currentEventSource) currentEventSource.close();
    showToast(`Pipeline stopped: ${message}`, 'error');
  }
}

async function pollJobStatus(apiUrl, jobId) {
  try {
    const res = await fetch(`${apiUrl}/api/jobs`);
    if (!res.ok) return;
    const jobs = await res.json();
    const curr = jobs.find(j => j.id === jobId);
    if (curr) {
      updateProgress(curr.progress_pct, curr.message || '', curr.status, curr.step || 1);
      if (curr.status === 'done') {
        fetchCompletedJob(apiUrl, jobId);
      }
    }
  } catch (e) {}
}

function updateProgress(pct, msg, status, step) {
  $('progress-pct-val').textContent = pct;
  $('progress-bar-fill').style.width = `${pct}%`;
  $('progress-msg').textContent = msg;

  // Stepper highlight
  for (let i = 1; i <= 5; i++) {
    const node = $(`node-step-${i}`);
    const stateLabel = $(`state-step-${i}`);
    if (!node) continue;

    if (i < step || (i === 5 && pct >= 100)) {
      node.className = 'step-node done';
      if (stateLabel) stateLabel.textContent = 'Complete';
    } else if (i === step) {
      node.className = 'step-node running';
      if (stateLabel) stateLabel.textContent = 'Running';
    } else {
      node.className = 'step-node';
      if (stateLabel) stateLabel.textContent = 'Waiting';
    }
  }
}

function appendLog(line) {
  const logs = $('terminal-logs');
  if (!logs) return;
  const div = document.createElement('div');
  div.className = 'log-line';
  const time = new Date().toLocaleTimeString();
  div.textContent = `[${time}] ${line}`;
  logs.appendChild(div);
  logs.scrollTop = logs.scrollHeight;
}

// ── COMPLETED JOB DISPLAY ────────────────────────────────────
async function fetchCompletedJob(apiUrl, jobId) {
  try {
    const res = await fetch(`${apiUrl}/api/jobs`);
    if (!res.ok) return;
    const jobs = await res.json();
    const job = jobs.find(j => j.id === jobId);
    if (!job) return;

    $('progress-view')?.classList.add('hidden');
    $('results-view')?.classList.remove('hidden');
    $('results-view')?.scrollIntoView({ behavior: 'smooth' });

    $('out-story-title').textContent = job.story_title || 'Khmer AI Video';

    // Populate video players
    const mobileVideoUrl = `${apiUrl}/api/video/${jobId}/mobile`;
    const laptopVideoUrl = `${apiUrl}/api/video/${jobId}/laptop`;

    const mobilePlayer = $('video-player-mobile');
    const laptopPlayer = $('video-player-laptop');

    if (mobilePlayer) {
      mobilePlayer.src = mobileVideoUrl;
      $('btn-dl-mobile').href = mobileVideoUrl;
    }
    if (laptopPlayer) {
      laptopPlayer.src = laptopVideoUrl;
      $('btn-dl-laptop').href = laptopVideoUrl;
    }

    // Populate metadata
    $('out-caption-box').value = `${job.story_title || ''}\n\n#KhmerStory #រឿងខ្មែរ #KhmerAI #TikTokCambodia #CambodiaCinema`;
  } catch (e) {}
}

function handleReset() {
  $('results-view')?.classList.add('hidden');
  $('progress-view')?.classList.add('hidden');
  $('studio-view-container')?.classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ── PROJECT HISTORY ──────────────────────────────────────────
async function fetchRecentJobs() {
  const grid = $('project-history-grid');
  if (!grid) return;

  const apiUrl = getApiUrl();
  try {
    const res = await fetch(`${apiUrl}/api/jobs`);
    if (!res.ok) return;
    const jobs = await res.json();

    if (!jobs || jobs.length === 0) {
      grid.innerHTML = `
        <div class="empty-state">
          <p>No previous projects found. Create your first video in Video Studio!</p>
        </div>
      `;
      return;
    }

    grid.innerHTML = jobs.map(j => `
      <div style="background: var(--bg-surface-elev); border: 1px solid var(--border-subtle); border-radius: var(--r-md); padding: 18px; display: flex; justify-content: space-between; align-items: center;">
        <div>
          <span style="font-size: 0.72rem; font-weight: 700; color: var(--gold);">ID: ${j.id}</span>
          <h4 style="font-size: 1rem; color: var(--text-khmer); margin: 4px 0;">${j.story_title || j.prompt.slice(0, 35)}...</h4>
          <span style="font-size: 0.75rem; color: var(--text-muted);">${j.created_at ? new Date(j.created_at).toLocaleString() : ''}</span>
        </div>
        <div>
          <button class="btn-ghost-sm" onclick="fetchCompletedJob('${apiUrl}', '${j.id}')">View Videos</button>
        </div>
      </div>
    `).join('');
  } catch (e) {}
}

// ── CLIPBOARD COPY UTILITY ───────────────────────────────────
function copyText(elementId) {
  const el = $(elementId);
  if (!el) return;
  const text = el.value || el.innerText;
  navigator.clipboard.writeText(text).then(() => {
    showToast('Copied to clipboard', 'success');
  }).catch(() => {
    showToast('Failed to copy', 'error');
  });
}

// ── TOAST NOTIFICATIONS ─────────────────────────────────────
function showToast(message, type = 'info') {
  const container = $('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
