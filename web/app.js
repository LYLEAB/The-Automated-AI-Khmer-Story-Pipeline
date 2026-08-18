/**
 * app.js — Clean & Responsive KhmerAI Studio Controller
 */

'use strict';

let currentJobId = null;
let currentEventSource = null;
let currentMode = 'ai_generate';
let selectedStyle = 'dramatic';

const PROMPT_IDEAS = [
  "រឿងកុលាបប៉ៃលិន — a legendary romance in the emerald mountains of Pailin",
  "A courageous young Khmer warrior protecting his ancient village in Angkor",
  "A mysterious bedtime fable about a wise rabbit and a golden elephant",
  "រឿងព្រេងបុរាណ — An ancient tale of friendship and perseverance",
  "A dramatic story about an Apsara dancer overcoming adversity in Phnom Penh",
  "រឿងខ្មោចព្រាយ — A spine-chilling midnight mystery in an old pagoda"
];

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

document.addEventListener('DOMContentLoaded', () => {
  const savedUrl = localStorage.getItem('khmer_api_url');
  if (savedUrl && $('api-url-input')) {
    $('api-url-input').value = savedUrl;
  }
});

function switchMode(mode) {
  currentMode = mode;
  $('tab-ai')?.classList.toggle('active', mode === 'ai_generate');
  $('tab-paste')?.classList.toggle('active', mode === 'paste_story');

  $('pane-ai')?.classList.toggle('hidden', mode !== 'ai_generate');
  $('pane-paste')?.classList.toggle('hidden', mode !== 'paste_story');
}

function selectStyle(style) {
  selectedStyle = style;
  document.querySelectorAll('.chip').forEach(chip => {
    chip.classList.toggle('active', chip.dataset.style === style);
  });
}

function handleSurpriseMe() {
  const promptInput = $('story-prompt');
  if (!promptInput) return;
  switchMode('ai_generate');
  const randomPrompt = PROMPT_IDEAS[Math.floor(Math.random() * PROMPT_IDEAS.length)];
  promptInput.value = randomPrompt;
}

function handleSceneSliderChange(val) {
  const badge = $('num-scenes-val');
  if (badge) {
    badge.textContent = `${val} Scenes (~${val * 10}s)`;
  }
}

function toggleProjectsModal() {
  const modal = $('projects-modal');
  if (!modal) return;
  const isHidden = modal.classList.toggle('hidden');
  if (!isHidden) {
    loadRecentProjects();
  }
}

async function loadRecentProjects() {
  const container = $('project-history-list');
  if (!container) return;

  const apiUrl = getApiUrl();
  try {
    const res = await fetch(`${apiUrl}/api/jobs`);
    if (!res.ok) throw new Error('API failed');
    const jobs = await res.json();
    if (!jobs || jobs.length === 0) {
      container.innerHTML = '<p class="empty-text">No previous videos yet.</p>';
      return;
    }

    container.innerHTML = jobs.map(j => `
      <div style="padding: 10px 0; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center;">
        <div>
          <div style="font-weight: 600; color: var(--text-khmer); font-size: 0.85rem;">${j.story_title || j.prompt.slice(0, 30)}...</div>
          <div style="font-size: 0.72rem; color: var(--text-muted);">${j.created_at ? new Date(j.created_at).toLocaleTimeString() : ''}</div>
        </div>
        <button class="btn-copy" onclick="fetchCompletedJob('${apiUrl}', '${j.id}'); toggleProjectsModal();">View</button>
      </div>
    `).join('');
  } catch (e) {
    container.innerHTML = '<p class="empty-text">Could not load project history.</p>';
  }
}

async function handleGenerate() {
  const prompt = currentMode === 'paste_story' ? $('story-text')?.value?.trim() : $('story-prompt')?.value?.trim();
  if (!prompt || prompt.length < 8) {
    showToast('Please enter a story or prompt first.');
    return;
  }

  const apiUrl = getApiUrl();
  const numScenes = parseInt($('num-scenes')?.value || '6', 10);
  const exportProfile = $('export-profile')?.value || 'both';
  const ttsProvider = $('tts-provider')?.value || 'gtts';

  $('progress-view')?.classList.remove('hidden');
  $('results-view')?.classList.add('hidden');
  $('progress-view')?.scrollIntoView({ behavior: 'smooth' });

  updateProgress(0, 'Starting pipeline...', 'running', 1);

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
        image_provider: 'gemini_imagen',
        story_style: selectedStyle
      })
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    currentJobId = data.job_id;

    listenToSseProgress(apiUrl, currentJobId);
  } catch (err) {
    showToast(`Error: ${err.message}`);
    updateProgress(0, err.message, 'failed', 1);
  }
}

function listenToSseProgress(apiUrl, jobId) {
  if (currentEventSource) currentEventSource.close();
  const sseUrl = `${apiUrl}/api/progress/${jobId}`;
  currentEventSource = new EventSource(sseUrl);

  currentEventSource.onmessage = (event) => {
    if (!event.data) return;
    try {
      const data = JSON.parse(event.data);
      const { step, progress_pct, message, status } = data;
      updateProgress(progress_pct, message, status, step);

      if (progress_pct >= 100 || status === 'done') {
        currentEventSource.close();
        showToast('Video ready!');
        fetchCompletedJob(apiUrl, jobId);
      } else if (status === 'failed') {
        currentEventSource.close();
        showToast(`Failed: ${message}`);
      }
    } catch (e) {}
  };

  currentEventSource.onerror = () => {
    pollJobStatus(apiUrl, jobId);
  };
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
  $('progress-pct-val').textContent = `${pct}%`;
  $('progress-bar-fill').style.width = `${pct}%`;
  $('progress-msg').textContent = msg;

  for (let i = 1; i <= 5; i++) {
    const el = $(`step-${i}`);
    if (!el) continue;
    if (i < step || (i === 5 && pct >= 100)) {
      el.className = 'step done';
    } else if (i === step) {
      el.className = 'step active';
    } else {
      el.className = 'step';
    }
  }
}

async function fetchCompletedJob(apiUrl, jobId) {
  try {
    const res = await fetch(`${apiUrl}/api/jobs`);
    if (!res.ok) return;
    const jobs = await res.json();
    const job = jobs.find(j => j.id === jobId) || jobs[0];
    if (!job) return;

    $('progress-view')?.classList.add('hidden');
    $('results-view')?.classList.remove('hidden');
    $('results-view')?.scrollIntoView({ behavior: 'smooth' });

    $('out-story-title').textContent = job.story_title || 'Khmer Story Video';

    const mobileUrl = `${apiUrl}/api/video/${jobId}/mobile`;
    const laptopUrl = `${apiUrl}/api/video/${jobId}/laptop`;

    const mobPlayer = $('video-player-mobile');
    const lapPlayer = $('video-player-laptop');

    if (mobPlayer) {
      mobPlayer.src = mobileUrl;
      mobPlayer.load();
      $('btn-dl-mobile').href = mobileUrl;
    }
    if (lapPlayer) {
      lapPlayer.src = laptopUrl;
      lapPlayer.load();
      $('btn-dl-laptop').href = laptopUrl;
    }

    try {
      const metaRes = await fetch(`${apiUrl}/api/metadata/${jobId}`);
      if (metaRes.ok) {
        const meta = await metaRes.json();
        $('out-caption-box').value = `${meta.title_variants?.[0] || job.story_title}\n\n${meta.description_khmer || ''}\n\n${(meta.hashtags || []).join(' ')}`;
      } else {
        $('out-caption-box').value = `${job.story_title}\n\n#KhmerStory #រឿងខ្មែរ #TikTokCambodia #CambodiaCinema`;
      }
    } catch (e) {
      $('out-caption-box').value = `${job.story_title}\n\n#KhmerStory #រឿងខ្មែរ #TikTokCambodia #CambodiaCinema`;
    }
  } catch (e) {}
}

function handleReset() {
  $('results-view')?.classList.add('hidden');
  $('progress-view')?.classList.add('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function copyText(id) {
  const el = $(id);
  if (!el) return;
  navigator.clipboard.writeText(el.value || el.innerText).then(() => {
    showToast('Copied to clipboard!');
  });
}

function showToast(msg) {
  const container = $('toast-container');
  if (!container) return;
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => {
    t.remove();
  }, 3500);
}
