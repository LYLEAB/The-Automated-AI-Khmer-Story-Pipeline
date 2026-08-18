/**
 * app.js — Khmer Story Pipeline Frontend Logic
 * ==============================================
 * Handles:
 *  - Tab switching (Paste / AI Generate)
 *  - API communication (REST + SSE real-time progress)
 *  - Pipeline progress UI updates
 *  - Video player population (mobile phone frame + laptop browser frame)
 *  - Metadata display (titles, descriptions, hashtags)
 *  - Clipboard copy for captions
 *  - Story preview modal
 *  - Toast notifications
 */

'use strict';

// ─────────────────────────────────────────────
// CONFIGURATION
// ─────────────────────────────────────────────

/** Read API URL from the input field, localStorage, or environment (injected by Vercel). */
function getApiUrl() {
  const inputVal = document.getElementById('api-url-input')?.value?.trim();
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

// ─────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────

let currentJobId = null;
let currentEventSource = null;
let currentMode = 'paste_story';    // 'paste_story' | 'ai_generate'
let selectedStyle = 'dramatic';
let previewedScenes = null;         // scenes from "Preview Story" modal

const PROMPT_IDEAS = [
  "រឿងព្រេងខ្មែរបុរាណនិយាយពីអ្នកក្លាហានដែលការពារនគរពីបិសាច",
  "A cyberpunk version of Phnom Penh in the year 2150",
  "រឿងកំប្លែងនិយាយពីសត្វឆ្កែមួយក្បាលដែលចេះនិយាយភាសាខ្មែរ",
  "A dramatic story about a young apsara dancer finding her inner strength",
  "រឿងស្នេហាកំសត់នៅសម័យលង្វែក",
  "A mysterious thriller set in the ruins of Angkor Wat at midnight",
  "រឿងនិទានអប់រំកុមារអំពីសត្វទន្សាយមានប្រាជ្ញា",
  "An action-packed heroic tale of a Bokator master"
];

// ─────────────────────────────────────────────
// DOM REFERENCES
// ─────────────────────────────────────────────

const $ = (id) => document.getElementById(id);
const $el = (sel) => document.querySelector(sel);

// ─────────────────────────────────────────────
// INITIALIZATION
// ─────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  initSlider();
  initStyleChips();
  initButtons();
  initCharCounter();
  restoreApiUrl();
});

// ─────────────────────────────────────────────
// TAB SWITCHING
// ─────────────────────────────────────────────

function initTabs() {
  const tabs = document.querySelectorAll('.mode-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');
      const targetId = tab.getAttribute('aria-controls');
      document.getElementById(targetId)?.classList.add('active');
      currentMode = tab.id === 'tab-paste' ? 'paste_story' : 'ai_generate';
    });
  });
}

// ─────────────────────────────────────────────
// RANGE SLIDER
// ─────────────────────────────────────────────

function initSlider() {
  const slider = $('range-scenes');
  const label  = $('scenes-val');
  if (!slider) return;

  function updateSlider() {
    const pct = ((slider.value - slider.min) / (slider.max - slider.min)) * 100;
    slider.style.setProperty('--pct', `${pct}%`);
    label.textContent = slider.value;
    slider.setAttribute('aria-valuenow', slider.value);
  }

  slider.addEventListener('input', updateSlider);
  updateSlider();
}

// ─────────────────────────────────────────────
// STYLE CHIPS
// ─────────────────────────────────────────────

function initStyleChips() {
  document.querySelectorAll('.style-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('.style-chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      selectedStyle = chip.dataset.style;
    });
  });
}

// ─────────────────────────────────────────────
// CHARACTER COUNTER
// ─────────────────────────────────────────────

function initCharCounter() {
  const ta = $('story-text');
  const counter = $('char-count');
  if (!ta || !counter) return;
  ta.addEventListener('input', () => {
    counter.textContent = `${ta.value.length} chars`;
    counter.style.color = ta.value.length > 5000 ? 'var(--red)' : 'var(--text-muted)';
  });
}

// ─────────────────────────────────────────────
// RESTORE API URL FROM LOCALSTORAGE
// ─────────────────────────────────────────────

function restoreApiUrl() {
  const saved = localStorage.getItem('khmer_api_url');
  if (saved) {
    const input = $('api-url-input');
    if (input) input.value = saved;
  }
}

// ─────────────────────────────────────────────
// BUTTON WIRING
// ─────────────────────────────────────────────

function initButtons() {
  $('btn-generate')?.addEventListener('click', handleGenerate);
  $('btn-preview-story')?.addEventListener('click', handlePreviewStory);
  $('btn-copy-caption')?.addEventListener('click', handleCopyCaption);
  $('btn-new-run')?.addEventListener('click', handleNewRun);
  $('btn-modal-close')?.addEventListener('click', closeModal);
  $('btn-modal-run')?.addEventListener('click', handleRunFromModal);
  $('btn-surprise-me')?.addEventListener('click', handleSurpriseMe);

  // Close modal on backdrop click
  $('story-preview-modal')?.addEventListener('click', (e) => {
    if (e.target === $('story-preview-modal')) closeModal();
  });
}

// ─────────────────────────────────────────────
// VALIDATION
// ─────────────────────────────────────────────

function getStoryInput() {
  if (currentMode === 'paste_story') {
    return $('story-text')?.value?.trim() || '';
  }
  return $('story-prompt')?.value?.trim() || '';
}

function validate() {
  const input = getStoryInput();
  if (!input) {
    showToast('Please enter a story or prompt first.', 'error');
    return false;
  }
  if (input.length < 20) {
    showToast('Your input is too short. Please add more detail.', 'error');
    return false;
  }
  const apiUrl = getApiUrl();
  const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
  if (!apiUrl && !isLocal) {
    showToast('Please enter your Render Backend API URL in Advanced Settings.', 'error');
    $('adv-details')?.setAttribute('open', '');
    $('api-url-input')?.focus();
    return false;
  }
  return true;
}

// ─────────────────────────────────────────────
// SURPRISE ME (RANDOM PROMPT)
// ─────────────────────────────────────────────
function handleSurpriseMe() {
  const promptInput = $('story-prompt');
  if (!promptInput) return;
  
  const randomPrompt = PROMPT_IDEAS[Math.floor(Math.random() * PROMPT_IDEAS.length)];
  
  // Quick typing effect
  promptInput.value = '';
  let i = 0;
  function typeWriter() {
    if (i < randomPrompt.length) {
      promptInput.value += randomPrompt.charAt(i);
      i++;
      setTimeout(typeWriter, 15);
    }
  }
  typeWriter();
}

// ─────────────────────────────────────────────
// MAIN GENERATE HANDLER
// ─────────────────────────────────────────────

async function handleGenerate() {
  if (!validate()) return;

  const payload = {
    prompt:          getStoryInput(),
    mode:            currentMode,
    num_scenes:      parseInt($('range-scenes')?.value || '6'),
    export_profile:  $('sel-profile')?.value || 'both',
    tts_provider:    $('sel-tts')?.value || 'gtts',
    image_provider:  $('sel-image')?.value || 'gemini_imagen',
    story_style:     selectedStyle,
  };

  setGenerateButtonState('loading');
  showProgressView();

  try {
    const apiUrl = getApiUrl();
    const res = await fetch(`${apiUrl}/api/run`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    currentJobId = data.job_id;
    connectSSE(currentJobId);
    showToast(`Job started: ${currentJobId}`, 'info');

  } catch (err) {
    setGenerateButtonState('idle');
    showToast(`Failed to start pipeline: ${err.message}`, 'error');
    hideProgressView();
  }
}

// ─────────────────────────────────────────────
// SERVER-SENT EVENTS (SSE) — REAL-TIME PROGRESS
// ─────────────────────────────────────────────

function connectSSE(jobId) {
  if (currentEventSource) currentEventSource.close();

  const apiUrl = getApiUrl();
  const url = `${apiUrl}/api/progress/${jobId}`;
  currentEventSource = new EventSource(url);

  currentEventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);

    // Update progress bar
    if (typeof data.progress_pct === 'number') {
      updateProgressBar(data.progress_pct);
    }

    // Update step cards
    if (data.step) {
      updateStepCard(data.step, data.status, data.message);
    }

    // Update live message
    if (data.message) {
      $('live-message-text').textContent = data.message;
      $('progress-status-text').textContent = data.message;
    }

    // Pipeline done
    if (data.done) {
      currentEventSource.close();

      if (data.outputs) {
        // Fetch full job state for scene previews and metadata
        fetchJobAndShowOutputs(currentJobId);
      } else if (data.status === 'failed') {
        setGenerateButtonState('idle');
        showToast('Pipeline failed. Check the console.', 'error');
        updateProgressBar(0);
      }
    }
  };

  currentEventSource.onerror = () => {
    // Reconnect automatically — SSE will handle keepalive
    // Don't show error on routine keepalive interruptions
  };
}

// ─────────────────────────────────────────────
// PROGRESS UI
// ─────────────────────────────────────────────

const STEP_ICONS = { 1: '️', 2: '️', 3: '', 4: '', 5: '' };

function updateProgressBar(pct) {
  const bar = $('progress-bar');
  const disp = $('progress-pct-display');
  const aria = document.querySelector('.overall-progress');
  if (bar)  { bar.style.width = `${pct}%`; }
  if (disp) { disp.textContent = `${pct}%`; }
  if (aria) { aria.setAttribute('aria-valuenow', pct); }
}

function updateStepCard(step, status, message) {
  const card = $(`step-${step}`);
  const statusEl = $(`step-${step}-status`);
  if (!card || !statusEl) return;

  card.className = 'step-card';
  if (status === 'running') {
    card.classList.add('running');
    statusEl.innerHTML = `<span class="spinner" aria-hidden="true"></span> Running`;
  } else if (status === 'done') {
    card.classList.add('done');
    statusEl.textContent = ' Done';
    // Mark all prior steps as done too
    for (let i = 1; i < step; i++) {
      $(`step-${i}`)?.classList.remove('running');
      $(`step-${i}`)?.classList.add('done');
      if ($(`step-${i}-status`)) $(`step-${i}-status`).textContent = ' Done';
    }
  } else if (status === 'failed') {
    card.classList.add('failed');
    statusEl.textContent = ' Failed';
  }
}

function addSceneCard(scene) {
  const gallery = $('scene-gallery');
  if (!gallery) return;

  const apiUrl = getApiUrl();
  const card = document.createElement('div');
  card.className = 'scene-card';
  card.setAttribute('role', 'listitem');
  card.innerHTML = `
    ${scene.image_url
      ? `<img class="scene-card-img" src="${apiUrl}${scene.image_url}" alt="Scene ${scene.scene_id} image" loading="lazy" />`
      : `<div class="scene-card-img placeholder" aria-hidden="true"></div>`
    }
    <div class="scene-card-body">
      <div class="scene-card-id">SCENE ${scene.scene_id}</div>
      <div class="scene-card-mood">${scene.mood || '—'}</div>
      <div class="scene-card-narration" lang="km">${scene.narration_preview || ''}</div>
    </div>
  `;
  gallery.appendChild(card);
}

// ─────────────────────────────────────────────
// FETCH JOB & POPULATE OUTPUTS
// ─────────────────────────────────────────────

async function fetchJobAndShowOutputs(jobId) {
  try {
    const apiUrl = getApiUrl();
    const res = await fetch(`${apiUrl}/api/job/${jobId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const job = await res.json();

    // Populate scene gallery
    const gallery = $('scene-gallery');
    if (gallery) gallery.innerHTML = '';
    (job.scene_previews || []).forEach(addSceneCard);

    // Story title
    const storyTitle = job.outputs?.story_title || 'Your Story';
    $('output-story-name').textContent = storyTitle;
    $('progress-story-name').textContent = storyTitle;

    // Show output section
    showOutputView(job.outputs);

    // Load metadata
    const metaRes = await fetch(`${apiUrl}/api/metadata/${jobId}`);
    if (metaRes.ok) {
      const meta = await metaRes.json();
      populateMetadata(meta, jobId);
    }

    setGenerateButtonState('idle');
    showToast(' Your videos are ready!', 'success');

  } catch (err) {
    setGenerateButtonState('idle');
    showToast(`Could not load results: ${err.message}`, 'error');
  }
}

// ─────────────────────────────────────────────
// POPULATE OUTPUT VIEW
// ─────────────────────────────────────────────

function showOutputView(outputs) {
  const apiUrl = getApiUrl();

  // Mobile video
  if (outputs?.video_mobile) {
    const src = `${apiUrl}${outputs.video_mobile}`;
    $('video-mobile-src').src = src;
    $('video-mobile').load();
    $('placeholder-mobile').style.display = 'none';
    $('dl-mobile').href = src;
  }

  // Laptop video
  if (outputs?.video_laptop) {
    const src = `${apiUrl}${outputs.video_laptop}`;
    $('video-laptop-src').src = src;
    $('video-laptop').load();
    $('placeholder-laptop').style.display = 'none';
    $('dl-laptop').href = src;
  }

  // Stats
  if (outputs?.total_scenes)    { /* could update stat chips */ }
  if (outputs?.total_duration_s) { /* could show duration */ }

  $('output-section').style.display = 'block';
  $('output-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function populateMetadata(meta, jobId) {
  const apiUrl = getApiUrl();

  // Title variants
  const titlesEl = $('title-variants');
  if (titlesEl) {
    titlesEl.innerHTML = '';
    (meta.title_variants || []).forEach(title => {
      const div = document.createElement('div');
      div.className = 'title-variant';
      div.setAttribute('role', 'listitem');
      div.textContent = title;
      div.addEventListener('click', () => {
        navigator.clipboard.writeText(title).then(() => showToast('Title copied!', 'success'));
      });
      titlesEl.appendChild(div);
    });
  }

  // Descriptions
  if ($('desc-khmer'))   $('desc-khmer').textContent = meta.description_khmer || '—';
  if ($('desc-english')) $('desc-english').textContent = meta.description_english || '—';

  // Hashtags
  const cloud = $('hashtags-cloud');
  if (cloud) {
    cloud.innerHTML = '';
    (meta.hashtags || []).forEach(tag => {
      const span = document.createElement('span');
      const isKhmer = /[\u1780-\u17FF]/.test(tag);
      const isViralTag = ['#fyp','#foryoupage','#storytime','#animatedstory'].includes(tag.toLowerCase());
      span.className = `hashtag ${isKhmer ? 'hashtag-khmer' : isViralTag ? 'hashtag-viral' : 'hashtag-english'}`;
      span.textContent = tag;
      span.setAttribute('role', 'listitem');
      span.addEventListener('click', () => {
        navigator.clipboard.writeText(tag).then(() => showToast(`${tag} copied!`, 'success'));
      });
      cloud.appendChild(span);
    });
    if ($('hashtag-count')) $('hashtag-count').textContent = `(${meta.hashtags?.length || 0})`;
  }

  // Best post time
  if ($('best-post-time')) $('best-post-time').textContent = meta.best_post_time || '—';

  // Store caption URL for copy
  $('btn-copy-caption').dataset.captionUrl = `${apiUrl}/api/caption/${jobId}`;
}

// ─────────────────────────────────────────────
// COPY CAPTION
// ─────────────────────────────────────────────

async function handleCopyCaption() {
  const btn = $('btn-copy-caption');
  const url = btn.dataset.captionUrl;

  try {
    if (url) {
      const res = await fetch(url);
      if (!res.ok) throw new Error('Caption not available');
      const text = await res.text();
      await navigator.clipboard.writeText(text);
    } else {
      // Fallback: build caption from DOM
      const titles = [...document.querySelectorAll('.title-variant')].map(el => el.textContent).join('\n');
      const desc = $('desc-khmer')?.textContent || '';
      const hashtags = [...document.querySelectorAll('.hashtag')].map(el => el.textContent).join(' ');
      await navigator.clipboard.writeText(`${titles}\n\n${desc}\n\n${hashtags}`);
    }
    btn.classList.add('copied');
    btn.textContent = ' Caption Copied!';
    showToast('Full caption copied to clipboard!', 'success');
    setTimeout(() => {
      btn.classList.remove('copied');
      btn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
         Copy Full Caption to Clipboard
      `;
    }, 3000);
  } catch (err) {
    showToast('Copy failed. Please copy manually.', 'error');
  }
}

// ─────────────────────────────────────────────
// STORY PREVIEW MODAL
// ─────────────────────────────────────────────

async function handlePreviewStory() {
  const prompt = $('story-prompt')?.value?.trim();
  if (!prompt || prompt.length < 10) {
    showToast('Please enter a story prompt first.', 'error');
    return;
  }

  const btn = $('btn-preview-story');
  btn.textContent = ' Generating preview…';
  btn.disabled = true;

  try {
    const apiUrl = getApiUrl();
    const res = await fetch(`${apiUrl}/api/generate-story`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        prompt,
        num_scenes: parseInt($('range-scenes')?.value || '6'),
        style:      selectedStyle,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    previewedScenes = data;
    showPreviewModal(data);

  } catch (err) {
    showToast(`Preview failed: ${err.message}`, 'error');
  } finally {
    btn.textContent = ' Preview Story Scenes First';
    btn.disabled = false;
  }
}

function showPreviewModal(data) {
  $('modal-story-title').textContent = `${data.story_title} — ${data.story_title_en}`;

  const list = $('preview-scene-list');
  list.innerHTML = '';
  (data.scenes || []).forEach(scene => {
    const item = document.createElement('div');
    item.className = 'preview-scene-item';
    item.setAttribute('role', 'listitem');
    item.innerHTML = `
      <div class="preview-scene-num" aria-label="Scene ${scene.scene_id}">${scene.scene_id}</div>
      <div>
        <div class="preview-scene-narration" lang="km">${scene.khmer_narration}</div>
        <div class="preview-scene-prompt">${scene.visual_prompt}</div>
        <div style="margin-top:6px;">
          <span class="scene-card-mood" style="display:inline-block; padding:2px 8px; border-radius:10px; background:var(--purple-dim); color:var(--purple-light); font-size:11px; font-weight:600;">${scene.mood}</span>
          <span style="font-size:11px; color:var(--text-muted); margin-left:8px;">~${scene.duration_hint_seconds}s</span>
        </div>
      </div>
    `;
    list.appendChild(item);
  });

  $('story-preview-modal').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  $('story-preview-modal').classList.remove('open');
  document.body.style.overflow = '';
}

async function handleRunFromModal() {
  closeModal();
  if (!previewedScenes) return;
  // Populate the prompt field with the story title so pipeline uses same story
  const prompt = $('story-prompt');
  if (prompt && previewedScenes.story_title) {
    prompt.value = previewedScenes.story_title;
  }
  await handleGenerate();
}

// ─────────────────────────────────────────────
// VIEW TRANSITIONS
// ─────────────────────────────────────────────

function showProgressView() {
  $('progress-section').style.display = 'block';
  $('output-section').style.display = 'none';
  $('scene-gallery').innerHTML = '';
  $('progress-story-name').textContent = 'Generating…';
  updateProgressBar(0);

  // Reset all step cards
  for (let i = 1; i <= 5; i++) {
    const card = $(`step-${i}`);
    const status = $(`step-${i}-status`);
    if (card)   card.className = 'step-card';
    if (status) status.textContent = 'Waiting…';
  }

  $('progress-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function hideProgressView() {
  $('progress-section').style.display = 'none';
}

function handleNewRun() {
  if (currentEventSource) { currentEventSource.close(); currentEventSource = null; }
  currentJobId = null;
  $('output-section').style.display = 'none';
  $('progress-section').style.display = 'none';
  $('input-view').scrollIntoView({ behavior: 'smooth' });
  // Reset video players
  $('video-mobile').pause();
  $('video-laptop').pause();
  $('placeholder-mobile').style.display = 'flex';
  $('placeholder-laptop').style.display = 'flex';
}

// ─────────────────────────────────────────────
// GENERATE BUTTON STATES
// ─────────────────────────────────────────────

function setGenerateButtonState(state) {
  const btn = $('btn-generate');
  if (!btn) return;
  if (state === 'loading') {
    btn.disabled = true;
    btn.innerHTML = '<div class="btn-shine" aria-hidden="true"></div><span class="spinner" aria-hidden="true"></span> Pipeline Running…';
  } else {
    btn.disabled = false;
    btn.innerHTML = '<div class="btn-shine" aria-hidden="true"></div> Generate Video';
  }
}

// ─────────────────────────────────────────────
// TOAST NOTIFICATIONS
// ─────────────────────────────────────────────

function showToast(message, type = 'info') {
  const container = $('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  const icons = { success: '', error: '', info: 'ℹ️' };
  toast.innerHTML = `<span aria-hidden="true">${icons[type] || 'ℹ️'}</span><span>${message}</span>`;
  toast.setAttribute('role', 'alert');

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(20px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 400);
  }, 4000);
}

// ─────────────────────────────────────────────
// KEYBOARD ACCESSIBILITY
// ─────────────────────────────────────────────

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeModal();
});
