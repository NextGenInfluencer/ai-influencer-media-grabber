/* AI Studio — storyboard, keyframes, animation, performance and face swap.
 * Every generative action is a server job (/api/jobs/<id>) with progress and cancel.
 * When a model is missing the server answers 424 + setup_hint and the card shows an
 * honest "Not available on this PC" state. Paid cloud runs need an explicit confirmation.
 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const token = () => document.querySelector('meta[name="media-token"]')?.content || '';
  const state = {
    capabilities: null, projects: [], project: null, scenes: [], videos: [], references: [],
    persona: null, outputs: [],
  };

  // ------------------------------------------------------------------ helpers

  class ApiError extends Error {
    constructor(message, status, data) {
      super(message);
      this.status = status;
      this.data = data || {};
    }
  }

  async function api(url, { method = 'GET', body, form } = {}) {
    const headers = { 'X-Media-Token': token() };
    const options = { method, headers };
    if (form) options.body = form;
    else if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({ error: 'The app did not answer. Restart it if the connection was lost.' }));
    if (!response.ok && response.status !== 202) throw new ApiError(data.error || `Request failed (${response.status})`, response.status, data);
    return data;
  }

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) {
      if (child !== null && child !== undefined && child !== false) node.append(child instanceof Node ? child : String(child));
    }
    return node;
  }

  const formatSeconds = (s) => {
    if (!s && s !== 0) return '';
    if (s < 90) return `~${Math.round(s)} s`;
    return `~${Math.round(s / 60)} min`;
  };

  function openSetup(hint) {
    if (typeof window.openAISetup === 'function') window.openAISetup(hint);
    else window.location.href = '/#ai-setup';
  }

  function toast(message, isError = false) {
    let host = $('studioToast');
    if (!host) {
      host = el('div', { id: 'studioToast', role: 'status', 'aria-live': 'polite' });
      document.body.append(host);
    }
    host.textContent = message;
    host.className = isError ? 'show error' : 'show';
    clearTimeout(host._timer);
    host._timer = setTimeout(() => { host.className = ''; }, 5000);
  }

  // ------------------------------------------------------------------ availability

  function unavailableCard(feature, message, hint) {
    const info = state.capabilities?.features?.[feature];
    const cost = info?.cost || {};
    const needs = [];
    if (cost.vram_gb) needs.push(`${cost.vram_gb} GB GPU memory`);
    if (cost.ram_gb) needs.push(`${cost.ram_gb} GB RAM`);
    const missing = info?.missing_names?.length ? `Needs: ${info.missing_names.join(', ')}.` : '';
    const card = el('div', { class: 'unavailable', role: 'note' },
      el('strong', { text: 'Not available on this PC' }),
      el('p', { text: message || (info?.cloud_only ? 'This feature only runs in the cloud with your own key.' : `${info?.label || 'This feature'} is not installed.`) }),
      needs.length ? el('p', { class: 'hint', text: `Requirements: ${needs.join(' · ')}.` }) : null,
      missing ? el('p', { class: 'hint', text: missing }) : null,
      info && info.recommended_for_profile === false ? el('p', { class: 'hint', text: 'Not recommended for this PC\'s hardware profile.' }) : null,
      el('div', { class: 'buttonRow' },
        el('button', { type: 'button', class: 'primary small', text: 'Set up AI', onclick: () => openSetup(hint || info?.setup_hint) }),
        info?.cloud ? el('span', { class: 'hint', text: info.cloud.enabled && info.cloud.has_key
          ? `Cloud option ready (${info.cloud.name}, paid).` : `Cloud option: enable ${info.cloud.name} in AI Setup → Cloud (paid, your key).` }) : null));
    return card;
  }

  function renderFeatureCards() {
    document.querySelectorAll('.feature[data-feature]').forEach((card) => {
      const feature = card.dataset.feature;
      const info = state.capabilities?.features?.[feature];
      const slot = card.querySelector('.availability');
      slot.replaceChildren();
      if (!info) return;
      const localReady = info.available;
      if (!localReady) slot.append(unavailableCard(feature));
      else slot.append(costChip(info.cost));
      card.querySelectorAll('button.primary').forEach((b) => { b.disabled = !localReady; });
      const cloudBtn = card.querySelector('.cloudBtn');
      if (cloudBtn) cloudBtn.hidden = !info.cloud;
    });
    const notice = $('generationNotice');
    notice.replaceChildren();
    const f = state.capabilities?.features || {};
    if (f.keyframe && !f.keyframe.available) notice.append(unavailableCard('keyframe'));
    else if (f.animate_fast && !f.animate_fast.available) notice.append(unavailableCard('animate_fast'));
    const director = f.director;
    $('directorCost').replaceChildren(director?.available
      ? costChip({ local: true, models: [director.cost.model], eta_seconds: director.cost.eta_seconds })
      : unavailableCard('director', director?.cost?.error, director?.setup_hint));
  }

  function costChip(cost) {
    const parts = [cost.local === false ? 'Cloud' : 'Local'];
    if (cost.models?.length) parts.push(cost.models.join(' + '));
    if (cost.vram_gb) parts.push(`${cost.vram_gb} GB VRAM`);
    if (cost.eta_seconds) parts.push(formatSeconds(cost.eta_seconds));
    return el('span', { class: `costChip ${cost.local === false ? 'cloud' : ''}`, text: parts.join(' · ') });
  }

  async function loadStatus() {
    try {
      state.capabilities = await api('/api/video-studio/capabilities');
    } catch (e) {
      toast(e.message, true);
    }
    renderFeatureCards();
    api('/api/ai/profile').then((p) => { $('profileChip').textContent = `Profile: ${p.profile}`; })
      .catch(() => { $('profileChip').textContent = 'Profile: unknown'; });
    api('/api/ai/engines').then((data) => {
      const comfy = data.engines?.comfy;
      const chip = $('engineChip');
      if (!comfy?.installed) { chip.textContent = 'Creative engine: not installed'; chip.className = 'chip warn'; }
      else { chip.textContent = comfy.running ? 'Creative engine: running' : 'Creative engine: idle'; chip.className = 'chip ok'; }
    }).catch(() => { $('engineChip').textContent = 'Creative engine: unknown'; });
  }

  // ------------------------------------------------------------------ jobs

  async function confirmCost(cost) {
    const dialog = $('costDialog');
    $('costText').textContent = `${cost.label} runs on ${cost.provider === 'fal' ? 'fal.ai' : 'Google Gemini'} and is billed to your account.`;
    $('costDocs').href = cost.docs || '#';
    dialog.returnValue = '';
    dialog.showModal();
    return new Promise((resolve) => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true }));
  }

  function jobView(slot, label) {
    const bar = el('progress', { max: '1', value: '0' });
    const message = el('span', { class: 'jobMessage', text: 'Starting…' });
    const cancel = el('button', { type: 'button', class: 'ghost small', text: 'Cancel' });
    const view = el('div', { class: 'job' }, el('div', { class: 'jobHead' }, el('strong', { text: label }), cancel), bar, message);
    slot.replaceChildren(view);
    return { view, bar, message, cancel };
  }

  /** POST a job request, handle 424/409, poll progress, resolve with the job result (or null). */
  async function runJob(url, body, slot, label) {
    let data;
    try {
      data = await api(url, { method: 'POST', body });
    } catch (e) {
      if (e.status === 409 && e.data.needs_confirmation) {
        if (!await confirmCost(e.data.cost)) return null;
        return runJob(url, { ...body, confirm_cost: true }, slot, label);
      }
      if (e.status === 424) {
        slot.replaceChildren(unavailableCard(null, e.message, e.data.setup_hint));
        return null;
      }
      slot.replaceChildren(el('p', { class: 'error', text: e.message }));
      return null;
    }
    const job = data.job;
    const ui = jobView(slot, job.label || label);
    ui.cancel.onclick = () => api(`/api/jobs/${job.id}/cancel`, { method: 'POST' }).catch((e) => toast(e.message, true));
    const started = Date.now();
    for (;;) {
      await new Promise((r) => setTimeout(r, 1000));
      let current;
      try { current = await api(`/api/jobs/${job.id}`); } catch (e) { ui.message.textContent = e.message; continue; }
      ui.bar.value = current.progress || 0;
      const eta = current.eta_seconds ? ` · estimated ${formatSeconds(current.eta_seconds)}` : '';
      ui.message.textContent = `${current.message || ''}${eta} · ${Math.round((Date.now() - started) / 1000)} s`;
      if (current.status === 'running') continue;
      if (current.status === 'completed') {
        slot.replaceChildren();
        if (current.result?.url) addOutput(current.result, current.label);
        return current.result;
      }
      if (current.status === 'cancelled') {
        slot.replaceChildren(el('p', { class: 'hint', text: 'Cancelled. Nothing was saved.' }));
        return null;
      }
      slot.replaceChildren(current.setup_hint ? unavailableCard(null, current.error, current.setup_hint)
        : el('p', { class: 'error', text: current.error || 'The job failed.' }));
      return null;
    }
  }

  function addOutput(result, label) {
    state.outputs.unshift({ ...result, label });
    const list = $('outputList');
    list.replaceChildren(...state.outputs.slice(0, 24).map((item) => {
      const isVideo = /\.(mp4|webm|mov)$/i.test(item.filename || item.url);
      const media = isVideo ? el('video', { src: item.url, controls: true, playsinline: true, preload: 'metadata' })
        : el('img', { src: item.url, alt: item.label || 'Result' });
      return el('figure', { class: 'output' }, media,
        el('figcaption', {}, el('span', { text: item.label || item.filename }),
          item.ai === false ? el('span', { class: 'badge', text: 'Preview (no AI)' })
            : el('span', { class: `badge ${item.local === false ? 'cloud' : ''}`, text: item.local === false ? 'Cloud' : 'Local AI' }),
          el('button', { type: 'button', class: 'ghost small', text: 'Show in folder',
            onclick: () => api('/api/open_folder', { method: 'POST', body: { path: item.path } }).catch((e) => toast(e.message, true)) })));
    }));
  }

  // ------------------------------------------------------------------ library lists

  async function loadLibraries() {
    const [projects, videos, refs, persona] = await Promise.all([
      api('/api/video-studio/projects').catch(() => ({ projects: [] })),
      api('/api/motion/driving-videos').catch(() => ({ videos: [] })),
      api('/api/motion/references').catch(() => ({ references: [] })),
      api('/api/characters/active').catch(() => ({ active: null })),
    ]);
    state.projects = projects.projects || [];
    state.videos = videos.videos || [];
    state.references = refs.references || [];
    state.persona = persona.active;
    $('activePersonaName').textContent = state.persona?.tag || state.persona?.name || 'none';
    const selected = $('projectSelect').value;
    $('projectSelect').replaceChildren(el('option', { value: '', text: 'Freeform (no song)' }),
      ...state.projects.map((p) => el('option', { value: p.id, text: `${p.name} · ${Math.round(p.duration)} s · ${p.cues} lines` })));
    $('projectSelect').value = state.projects.some((p) => p.id === selected) ? selected : '';
    document.querySelectorAll('.videoSelect').forEach((select) => {
      const value = select.value;
      select.replaceChildren(el('option', { value: '', text: state.videos.length ? 'Choose a video…' : 'No videos yet — upload one' }),
        ...state.videos.map((v) => el('option', { value: v.path, text: `${v.name} (${v.size_mb} MB)` })));
      if (value) select.value = value;
    });
    document.querySelectorAll('.audioSelect').forEach((select) => {
      const value = select.value;
      select.replaceChildren(el('option', { value: '', text: state.projects.length ? 'Choose a song project…' : 'No captions projects yet' }),
        ...state.projects.map((p) => el('option', { value: p.audio_url, text: p.name })));
      if (value) select.value = value;
    });
    const portrait = $('swapPortrait');
    const current = portrait.value;
    portrait.replaceChildren(el('option', { value: '', text: 'Active persona portrait' }),
      ...state.references.map((r) => el('option', { value: r.url, text: r.name })));
    portrait.value = current;
  }

  async function uploadVideo(targetSelect) {
    const input = $('videoUploadInput');
    input.onchange = async () => {
      const file = input.files[0];
      input.value = '';
      if (!file) return;
      const form = new FormData();
      form.append('video', file);
      try {
        const saved = await api('/api/motion/upload-driving-video', { method: 'POST', form });
        await loadLibraries();
        targetSelect.value = saved.path;
        toast(`Added ${saved.name}`);
      } catch (e) { toast(e.message, true); }
    };
    input.click();
  }

  async function uploadReference() {
    const input = $('referenceUploadInput');
    input.onchange = async () => {
      const file = input.files[0];
      input.value = '';
      if (!file) return;
      const form = new FormData();
      form.append('image', file);
      try {
        const saved = await api('/api/motion/upload-swapped-frame', { method: 'POST', form });
        await loadLibraries();
        $('swapPortrait').value = saved.url;
      } catch (e) { toast(e.message, true); }
    };
    input.click();
  }

  // ------------------------------------------------------------------ storyboard

  const storageKey = () => `aiStudio.storyboard.${$('projectSelect').value || 'freeform'}`;

  function saveScenes() {
    localStorage.setItem(storageKey(), JSON.stringify(state.scenes));
    $('sendToCaptionsBtn').disabled = !$('projectSelect').value || !state.scenes.some((s) => s.video_path);
    const pid = $('projectSelect').value;
    if (pid) {
      api(`/api/captions/${pid}/storyboard`, { method: 'POST', body: { storyboard: state.scenes } }).catch(() => {});
    }
  }

  function loadScenes() {
    try { state.scenes = JSON.parse(localStorage.getItem(storageKey()) || '[]'); } catch (_) { state.scenes = []; }
    const project = state.projects.find((p) => p.id === $('projectSelect').value);
    state.project = project || null;
    $('freeformDuration').hidden = Boolean(project);
    renderScenes();
  }

  function renderScenes() {
    const grid = $('sceneGrid');
    $('storyboardMeta').textContent = state.scenes.length
      ? `${state.scenes.length} scenes${state.project ? ` · ${state.project.name}` : ''}`
      : 'No scenes yet. Plan a storyboard or add a scene.';
    grid.replaceChildren(...state.scenes.map((scene, index) => sceneCard(scene, index)));
    $('sendToCaptionsBtn').disabled = !state.project || !state.scenes.some((s) => s.video_path);
  }

  function sceneCard(scene, index) {
    const update = (key) => (event) => { scene[key] = event.target.value; saveScenes(); };
    const slot = el('div', { class: 'jobSlot' });
    const preview = scene.video_url
      ? el('video', { src: scene.video_url, controls: true, playsinline: true, preload: 'metadata' })
      : scene.image_url ? el('img', { src: scene.image_url, alt: `Scene ${index + 1} keyframe` })
        : el('div', { class: 'placeholder', text: 'No keyframe yet' });
    const features = state.capabilities?.features || {};
    const keyframeReady = features.keyframe?.available || features.identity_keyframe?.available;
    const quality = $('animateQuality').value;
    const animateReady = features[quality === 'fast' ? 'animate_fast' : 'animate_quality']?.available;
    return el('article', { class: 'scene' },
      el('header', {},
        el('strong', { text: `Scene ${index + 1}` }),
        el('span', { class: 'hint', text: `${Number(scene.start || 0).toFixed(2)}–${Number(scene.end || 0).toFixed(2)} s` }),
        scene.preview_only ? el('span', { class: 'badge', text: 'Preview (no AI)' }) : null,
        el('button', { type: 'button', class: 'ghost small', 'aria-label': `Remove scene ${index + 1}`, text: '✕',
          onclick: () => { state.scenes.splice(index, 1); saveScenes(); renderScenes(); } })),
      el('div', { class: 'sceneMedia' }, preview),
      scene.lyric ? el('p', { class: 'lyric', text: `“${scene.lyric}”` }) : null,
      el('label', { text: 'Image prompt' }),
      el('textarea', { rows: '3', oninput: update('image_prompt') }, scene.image_prompt || ''),
      el('label', { text: 'Motion prompt' }),
      el('input', { type: 'text', value: scene.motion_prompt || '', oninput: update('motion_prompt') }),
      el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: scene.use_character !== false,
        onchange: (e) => { scene.use_character = e.target.checked; saveScenes(); } }), ' Include persona'),
      el('div', { class: 'buttonRow' },
        el('button', { type: 'button', class: 'primary small', disabled: !keyframeReady, title: keyframeReady ? '' : 'Not available on this PC',
          text: scene.image_path ? 'Re-render keyframe' : 'Render keyframe', onclick: () => renderKeyframe(index, slot) }),
        el('button', { type: 'button', class: 'small', disabled: !scene.image_path || !animateReady,
          title: animateReady ? '' : 'Not available on this PC', text: 'Animate', onclick: () => animateScene(index, slot) }),
        el('button', { type: 'button', class: 'ghost small', disabled: !scene.image_path, text: 'Preview (no AI)',
          onclick: () => previewScene(index, slot) })),
      slot);
  }

  async function planStoryboard() {
    const pid = $('projectSelect').value;
    const body = {
      concept: $('conceptInput').value, mood: $('moodInput').value, character_id: state.persona?.id,
      num_scenes: Number($('sceneCountInput').value) || undefined,
    };
    if (pid) body.project_id = pid;
    else body.duration = Number($('durationInput').value) || 15;
    const result = await runJob('/api/video-studio/storyboard/generate', body, $('planJob'), 'AI Director');
    if (!result) return;
    state.scenes = result.scenes;
    $('storyboardTitle').textContent = result.title || 'Storyboard';
    saveScenes();
    renderScenes();
    toast(`Planned ${result.scenes.length} scenes with ${result.model}.`);
  }

  async function renderKeyframe(index, slot) {
    const scene = state.scenes[index];
    const result = await runJob('/api/video-studio/render-image', {
      prompt: scene.image_prompt, scene_number: index + 1, character_id: state.persona?.id,
      use_character: scene.use_character !== false,
    }, slot, `Keyframe · scene ${index + 1}`);
    if (!result) return;
    Object.assign(scene, { image_path: result.path, image_url: result.url, video_path: '', video_url: '', preview_only: false });
    saveScenes();
    renderScenes();
  }

  async function animateScene(index, slot) {
    const scene = state.scenes[index];
    const result = await runJob('/api/video-studio/render-video', {
      image_path: scene.image_path, motion_prompt: scene.motion_prompt, quality: $('animateQuality').value,
      duration: Math.min(15, Math.max(1, (scene.end || 5) - (scene.start || 0))), scene_number: index + 1,
    }, slot, `Animate · scene ${index + 1}`);
    if (!result) return;
    Object.assign(scene, { video_path: result.path, video_url: result.url, preview_only: false });
    saveScenes();
    renderScenes();
  }

  async function previewScene(index, slot) {
    const scene = state.scenes[index];
    const result = await runJob('/api/video-studio/render-video', {
      image_path: scene.image_path, preview: true, camera_motion: 'push_in', scene_number: index + 1,
      duration: Math.min(15, Math.max(1, (scene.end || 4) - (scene.start || 0))),
    }, slot, 'Preview (no AI)');
    if (!result) return;
    Object.assign(scene, { video_path: result.path, video_url: result.url, preview_only: true });
    saveScenes();
    renderScenes();
  }

  async function sendToCaptions() {
    const pid = $('projectSelect').value;
    if (!pid) return toast('Choose a captions project first.', true);
    try {
      const project = await api(`/api/captions/${pid}`);
      await api(`/api/captions/${pid}/bridge-storyboard`, { method: 'POST', body: { revision: project.revision, storyboard: state.scenes } });
      window.location.href = `/captions?project=${encodeURIComponent(pid)}`;
    } catch (e) {
      toast(e.status === 409 ? 'The project changed or is busy. Wait for it to finish, then send again.' : e.message, true);
    }
  }

  async function askDirector() {
    const question = $('directorQuestion').value.trim();
    if (!question) return;
    const box = $('directorAnswer');
    box.hidden = false;
    box.textContent = 'Thinking…';
    try {
      const data = await api('/api/video-studio/director/chat', { method: 'POST', body: {
        message: question, character_id: state.persona?.id,
        lyrics: state.scenes.map((s) => s.lyric).filter(Boolean).join('\n'),
      } });
      box.textContent = data.reply;
      box.append(el('small', { class: 'hint', text: ` — ${data.model} (local)` }));
    } catch (e) {
      box.replaceChildren(e.status === 424 ? unavailableCard('director', e.message, e.data.setup_hint) : el('p', { class: 'error', text: e.message }));
    }
  }

  // ------------------------------------------------------------------ performance and face swap

  function audioPayload(modeSelect, projectSelect) {
    const mode = modeSelect.value;
    if (mode === 'project' && !projectSelect.value) throw new Error('Choose the song project for the audio.');
    return mode === 'project' ? { audio_mode: 'project', audio_path: projectSelect.value } : { audio_mode: mode, mute: mode === 'mute' };
  }

  const slotOf = (button) => button.closest('.card').querySelector('.jobSlot');

  async function lipSync(button) {
    if (!$('lipVideo').value || !$('lipAudio').value) return toast('Choose a face video and a song.', true);
    await runJob('/api/video-studio/performance/lip-sync', { video_path: $('lipVideo').value, audio_path: $('lipAudio').value },
      slotOf(button), 'Lip-sync');
  }

  async function livePortrait(button, cloud) {
    if (!$('lpVideo').value) return toast('Choose a driving video.', true);
    let audio;
    try { audio = audioPayload($('lpAudioMode'), $('lpProjectAudio')); } catch (e) { return toast(e.message, true); }
    await runJob('/api/motion/render', { engine: 'live_portrait', cloud, driving_video: $('lpVideo').value,
      character_id: state.persona?.id, ...audio }, slotOf(button), cloud ? 'LivePortrait (cloud)' : 'Portrait animation');
  }

  function identityPayload() {
    const value = $('swapPortrait').value;
    return value ? { custom_portrait_path: value } : { character_id: state.persona?.id };
  }

  async function swapVideo(button) {
    if (!$('swapVideo').value) return toast('Choose a video.', true);
    let audio;
    try { audio = audioPayload($('swapAudioMode'), $('swapProjectAudio')); } catch (e) { return toast(e.message, true); }
    await runJob('/api/motion/render', { engine: 'face_swap', driving_video: $('swapVideo').value,
      restore: $('swapRestore').checked, ...identityPayload(), ...audio }, slotOf(button), 'Face Swap Video');
  }

  async function swapFrame(button, engine) {
    if (!$('swapVideo').value) return toast('Choose a video.', true);
    const result = await runJob('/api/motion/swap-identity', { driving_video_path: $('swapVideo').value, engine,
      restore: $('swapRestore').checked, ...identityPayload() }, slotOf(button), engine ? 'Identity edit (cloud)' : 'Face Swap (frame)');
    if (result) await loadLibraries();
  }

  async function klingTransfer(button) {
    if (!$('swapVideo').value) return toast('Choose the motion video in the Face Swap Video card.', true);
    await runJob('/api/motion/render', { engine: 'kling', driving_video: $('swapVideo').value, prompt: $('klingPrompt').value,
      ...identityPayload() }, slotOf(button), 'Motion transfer (Kling, cloud)');
  }

  // ------------------------------------------------------------------ tabs, copilot hooks, boot

  function showTab(name) {
    document.querySelectorAll('.tab').forEach((tab) => {
      const active = tab.dataset.tab === name;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('[role="tabpanel"]').forEach((panel) => { panel.hidden = panel.id !== `tab-${name}`; });
    if (window.location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
  }

  window.copilotContext = () => ({
    page: 'studio',
    project: state.project ? { id: state.project.id, name: state.project.name, duration: state.project.duration } : null,
    persona: state.persona ? { name: state.persona.name, tag: state.persona.tag } : null,
    scenes: state.scenes.map((s, i) => ({ scene: i + 1, start: s.start, end: s.end, lyric: s.lyric, image_prompt: s.image_prompt,
      has_keyframe: Boolean(s.image_path), has_video: Boolean(s.video_path) })),
  });

  window.copilotActions = {
    generate_storyboard: async (args) => {
      showTab('storyboard');
      if (args.concept) $('conceptInput').value = args.concept;
      if (args.num_scenes) $('sceneCountInput').value = args.num_scenes;
      await planStoryboard();
      return true;
    },
    generate_keyframe: async (args) => {
      showTab('storyboard');
      const index = Math.max(0, (Number(args.scene) || 1) - 1);
      if (!state.scenes[index]) state.scenes[index] = { start: 0, end: 5, image_prompt: args.prompt };
      if (args.prompt) state.scenes[index].image_prompt = args.prompt;
      renderScenes();
      await renderKeyframe(index, $('sceneGrid').children[index].querySelector('.jobSlot'));
      return true;
    },
    animate_keyframe: async (args) => {
      showTab('storyboard');
      const index = Math.max(0, (Number(args.scene) || 1) - 1);
      if (!state.scenes[index]?.image_path) throw new Error('Render that scene\'s keyframe first.');
      if (args.quality) $('animateQuality').value = args.quality;
      await animateScene(index, $('sceneGrid').children[index].querySelector('.jobSlot'));
      return true;
    },
    face_swap: async (args) => {
      showTab('faceswap');
      if (args.video_path) $('swapVideo').value = args.video_path;
      await swapVideo($('swapVideoBtn'));
      return true;
    },
    lip_sync: async (args) => {
      showTab('performance');
      if (args.video_path) $('lipVideo').value = args.video_path;
      await lipSync($('lipSyncBtn'));
      return true;
    },
  };

  function bind() {
    document.querySelectorAll('.tab').forEach((tab) => tab.addEventListener('click', () => showTab(tab.dataset.tab)));
    $('setupAiBtn').onclick = () => openSetup();
    $('activePersonaBtn').onclick = () => window.characterStudio?.open();
    $('projectSelect').onchange = loadScenes;
    $('planBtn').onclick = planStoryboard;
    $('directorAskBtn').onclick = askDirector;
    $('addSceneBtn').onclick = () => {
      const last = state.scenes[state.scenes.length - 1];
      const start = last ? last.end : 0;
      state.scenes.push({ id: `scene_${Date.now()}`, start, end: start + 5, image_prompt: '', motion_prompt: '', use_character: true });
      saveScenes();
      renderScenes();
    };
    $('animateQuality').onchange = renderScenes;
    $('sendToCaptionsBtn').onclick = sendToCaptions;
    $('lipSyncBtn').onclick = (e) => lipSync(e.currentTarget);
    $('livePortraitBtn').onclick = (e) => livePortrait(e.currentTarget, false);
    $('livePortraitCloudBtn').onclick = (e) => livePortrait(e.currentTarget, true);
    $('swapVideoBtn').onclick = (e) => swapVideo(e.currentTarget);
    $('swapFrameBtn').onclick = (e) => swapFrame(e.currentTarget, undefined);
    $('nanoBananaBtn').onclick = (e) => swapFrame(e.currentTarget, 'nano_banana');
    $('klingBtn').onclick = (e) => klingTransfer(e.currentTarget);
    $('uploadReferenceBtn').onclick = uploadReference;
    document.querySelectorAll('.uploadVideoBtn').forEach((button) => {
      button.onclick = () => uploadVideo(button.parentElement.querySelector('select'));
    });
    document.querySelectorAll('.audioMode').forEach((select) => {
      select.onchange = () => { select.parentElement.querySelector('.projectAudio').hidden = select.value !== 'project'; };
    });
    window.addEventListener('active-persona-changed', loadLibraries);
    window.addEventListener('focus', () => loadStatus());
  }

  document.addEventListener('DOMContentLoaded', async () => {
    bind();
    const hash = window.location.hash.replace('#', '');
    showTab(['storyboard', 'performance', 'faceswap'].includes(hash) ? hash : 'storyboard');
    await Promise.all([loadStatus(), loadLibraries()]);
    const requested = new URLSearchParams(window.location.search).get('project');
    if (requested && state.projects.some((p) => p.id === requested)) $('projectSelect').value = requested;
    loadScenes();
  });
})();
