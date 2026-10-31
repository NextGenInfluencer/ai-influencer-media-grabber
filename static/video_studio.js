/* AI Video Studio - Client Orchestrator */
(function() {
  'use strict';

  function getToken() {
    const meta = document.querySelector('meta[name="media-token"]');
    return meta ? meta.content : '';
  }

  function notify(msg, type = 'info') {
    const existing = document.getElementById('vsToast');
    if (existing) existing.remove();

    const t = document.createElement('div');
    t.id = 'vsToast';
    t.className = 'snapperToast';
    t.style.maxWidth = '380px';
    t.style.display = 'flex';
    t.style.alignItems = 'center';
    t.style.gap = '10px';

    const icon = document.createElement('span');
    icon.textContent = type === 'error' ? '⚠️' : (type === 'success' ? '✓' : 'ℹ️');

    const txt = document.createElement('span');
    txt.textContent = msg;

    t.append(icon, txt);
    document.body.appendChild(t);
    setTimeout(() => t.classList.add('show'), 10);
    setTimeout(() => {
      t.classList.remove('show');
      setTimeout(() => t.remove(), 250);
    }, 3500);
  }

  let currentProject = null;
  let activePersona = null;
  let storyboardScenes = [];

  async function init() {
    bindEvents();
    await Promise.all([
      loadProjects(),
      loadActivePersona(),
      loadModelHubState()
    ]);
  }

  function bindEvents() {
    document.getElementById('vsProjectSelect').onchange = onProjectChange;
    document.getElementById('generateStoryboardBtn').onclick = generateStoryboardScenes;
    document.getElementById('renderAllImagesBtn').onclick = renderAllKeyframes;
    document.getElementById('animateAllVideosBtn').onclick = animateAllScenes;
    document.getElementById('bridgeToCaptionsBtn').onclick = bridgeToCaptionStudio;

    // AI Model Hub modal triggers
    const modelHubBtn = document.getElementById('openModelHubBtn');
    if (modelHubBtn) modelHubBtn.onclick = openModelHub;
    const closeHubBtn = document.getElementById('closeModelHubBtn');
    if (closeHubBtn) closeHubBtn.onclick = closeModelHub;
    const closeHubFooterBtn = document.getElementById('closeModelHubFooterBtn');
    if (closeHubFooterBtn) closeHubFooterBtn.onclick = closeModelHub;

    const tabLocal = document.getElementById('tabBtnLocalModels');
    if (tabLocal) tabLocal.onclick = () => switchModelTab('local');
    const tabCloud = document.getElementById('tabBtnCloudBackend');
    if (tabCloud) tabCloud.onclick = () => switchModelTab('cloud');

    const testComfy = document.getElementById('testComfyBtn');
    if (testComfy) testComfy.onclick = testComfyConnection;
    const saveCloud = document.getElementById('saveCloudSettingsBtn');
    if (saveCloud) saveCloud.onclick = saveCloudSettings;

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeModelHub();
    });

    const personaBtn = document.getElementById('activePersonaBtn');
    if (personaBtn) {
      personaBtn.onclick = () => {
        if (window.characterStudio) window.characterStudio.open();
      };
    }
    const editPersonaBtn = document.getElementById('openPersonaModalBtn');
    if (editPersonaBtn) {
      editPersonaBtn.onclick = () => {
        if (window.characterStudio) window.characterStudio.open();
      };
    }

    window.addEventListener('active-persona-changed', (e) => {
      if (e.detail) {
        activePersona = e.detail;
        updatePersonaUI();
      }
    });
  }

  async function loadProjects() {
    try {
      const res = await fetch('/api/captions');
      if (!res.ok) return;
      const projects = await res.json();
      const sel = document.getElementById('vsProjectSelect');
      sel.replaceChildren(
        Object.assign(document.createElement('option'), { value: '', textContent: 'Select Song / Project…' }),
        ...projects.map(p => Object.assign(document.createElement('option'), {
          value: p.id,
          textContent: p.name || 'Untitled Song'
        }))
      );
      const urlParams = new URLSearchParams(window.location.search);
      const reqPid = urlParams.get('project');
      if (reqPid && projects.some(p => p.id === reqPid)) {
        sel.value = reqPid;
      } else if (projects.length) {
        sel.value = projects[0].id;
      }
      if (sel.value) onProjectChange();
    } catch (_) {}
  }

  async function loadActivePersona() {
    try {
      const res = await fetch('/api/characters/active');
      if (!res.ok) return;
      const data = await res.json();
      activePersona = data.active;
      updatePersonaUI();
    } catch (_) {}
  }

  function updatePersonaUI() {
    if (!activePersona) return;
    const nameEl = document.getElementById('activePersonaName');
    const tagEl = document.getElementById('sidebarPersonaTag');
    const titleEl = document.getElementById('sidebarPersonaTitle');
    const avatarEl = document.getElementById('sidebarPersonaAvatar');

    if (nameEl) nameEl.textContent = activePersona.tag || activePersona.name;
    if (tagEl) tagEl.textContent = activePersona.tag;
    if (titleEl) titleEl.textContent = activePersona.name;
    if (avatarEl) {
      if (activePersona.portrait_file) {
        avatarEl.style.backgroundImage = `url('/api/characters/${activePersona.id}/image/${activePersona.portrait_file}')`;
        avatarEl.textContent = '';
      } else {
        avatarEl.style.backgroundImage = 'none';
        avatarEl.textContent = (activePersona.name || 'A').charAt(0).toUpperCase();
      }
    }
  }

  async function onProjectChange() {
    const sel = document.getElementById('vsProjectSelect');
    const pid = sel.value;
    if (!pid) return;

    try {
      const res = await fetch(`/api/captions/${pid}`);
      if (!res.ok) return;
      currentProject = await res.json();

      document.getElementById('vsSongDuration').textContent = fmt(currentProject.duration || 0);
      document.getElementById('vsCueCount').textContent = (currentProject.cues || []).length;

      // Audio setup
      const audioEl = document.getElementById('vsAudioPlayer');
      if (currentProject.source) {
        audioEl.src = `/api/captions/${pid}/media/${encodeURIComponent(currentProject.preview || currentProject.source)}`;
      }

      // Check if project has saved storyboard
      if (currentProject.storyboard && currentProject.storyboard.length) {
        storyboardScenes = currentProject.storyboard;
        renderStoryboardGrid();
      } else {
        // Auto-generate fresh storyboard concept
        generateStoryboardScenes();
      }
    } catch (_) {}
  }

  async function generateStoryboardScenes() {
    if (!currentProject) {
      notify('Select a project first.', 'warning');
      return;
    }
    const mood = document.getElementById('vsMoodSelect').value;
    const genBtn = document.getElementById('generateStoryboardBtn');
    genBtn.disabled = true;
    genBtn.textContent = '⏳ Directing Scenes…';

    try {
      const res = await fetch('/api/video-studio/storyboard/generate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          cues: currentProject.cues || [],
          duration: currentProject.duration || 60.0,
          character_id: activePersona?.id || 'airi',
          mood: mood
        })
      });
      if (!res.ok) throw new Error('Failed to generate storyboard');
      const data = await res.json();
      storyboardScenes = data.storyboard || [];
      renderStoryboardGrid();
      notify(`✓ Created ${storyboardScenes.length} beat-synced scenes!`, 'success');
      saveStoryboardToProject();
    } catch (e) {
      notify('Error generating storyboard: ' + e.message, 'error');
    } finally {
      genBtn.disabled = false;
      genBtn.textContent = '⚡ Generate Storyboard';
    }
  }

  function renderStoryboardGrid() {
    const grid = document.getElementById('vsSceneGrid');
    const countLabel = document.getElementById('vsSceneCountLabel');
    if (!grid) return;

    countLabel.textContent = `${storyboardScenes.length} Scenes`;
    grid.replaceChildren();

    storyboardScenes.forEach(s => {
      const card = document.createElement('div');
      card.className = 'vsSceneCard';
      card.id = `sceneCard_${s.number}`;

      // Header
      const header = document.createElement('div');
      header.className = 'vsSceneCardHeader';
      const badge = document.createElement('span');
      badge.className = 'sceneBadge';
      badge.textContent = `Scene #${s.number}`;
      const timeSpan = document.createElement('span');
      timeSpan.className = 'sceneTiming';
      timeSpan.textContent = `${fmt(s.start_time)} → ${fmt(s.end_time)}`;
      header.append(badge, timeSpan);

      // Lyrics snippet
      const lyricsDiv = document.createElement('div');
      lyricsDiv.className = 'sceneLyricsSnippet';
      lyricsDiv.textContent = s.lyrics ? `"${s.lyrics}"` : '(Instrumental / Ambient section)';

      // Media row
      const mediaRow = document.createElement('div');
      mediaRow.className = 'sceneMediaRow';

      // 1. Photo slot
      const imgBox = document.createElement('div');
      imgBox.className = 'sceneMediaBox';
      const imgLabel = document.createElement('span');
      imgLabel.className = 'mediaBoxLabel';
      imgLabel.textContent = 'Keyframe Photo (FLUX)';
      imgBox.appendChild(imgLabel);

      if (s.image_path) {
        const img = document.createElement('img');
        const fname = s.image_path.split(/[\\/]/).pop();
        img.src = `/api/video-studio/images/file/${encodeURIComponent(fname)}`;
        img.alt = `Scene ${s.number} Photo`;
        imgBox.appendChild(img);
      } else {
        const ph = document.createElement('div');
        ph.className = 'sceneEmptyPlaceholder';
        ph.innerHTML = '<span>🖼️</span><span>No photo generated</span>';
        imgBox.appendChild(ph);
      }

      // 2. Video slot
      const vidBox = document.createElement('div');
      vidBox.className = 'sceneMediaBox';
      const vidLabel = document.createElement('span');
      vidLabel.className = 'mediaBoxLabel';
      vidLabel.textContent = 'Video Clip (Wan 2.1)';
      vidBox.appendChild(vidLabel);

      if (s.video_path) {
        const vid = document.createElement('video');
        const fname = s.video_path.split(/[\\/]/).pop();
        vid.src = `/api/video-studio/videos/file/${encodeURIComponent(fname)}`;
        vid.autoplay = true;
        vid.loop = true;
        vid.muted = true;
        vid.controls = true;
        vidBox.appendChild(vid);
      } else {
        const ph = document.createElement('div');
        ph.className = 'sceneEmptyPlaceholder';
        ph.innerHTML = '<span>🎬</span><span>Ready to animate</span>';
        vidBox.appendChild(ph);
      }

      mediaRow.append(imgBox, vidBox);

      // Prompt Box
      const promptBox = document.createElement('div');
      promptBox.style.fontSize = '11px';
      promptBox.style.color = '#94a3b8';
      promptBox.textContent = `Prompt: ${s.image_prompt}`;

      // Card actions
      const actions = document.createElement('div');
      actions.className = 'sceneCardActions';

      const rollImgBtn = document.createElement('button');
      rollImgBtn.className = 'sceneMiniBtn';
      rollImgBtn.type = 'button';
      rollImgBtn.textContent = '🎲 Roll Photo';
      rollImgBtn.onclick = () => renderSingleImage(s.number);

      const animBtn = document.createElement('button');
      animBtn.className = 'sceneMiniBtn';
      animBtn.type = 'button';
      animBtn.textContent = '✨ Animate Scene';
      animBtn.onclick = () => renderSingleVideo(s.number);

      actions.append(rollImgBtn, animBtn);

      card.append(header, lyricsDiv, mediaRow, promptBox, actions);
      grid.appendChild(card);
    });
  }

  async function renderSingleImage(sceneNum) {
    const scene = storyboardScenes.find(s => s.number === sceneNum);
    if (!scene) return;
    notify(`Generating Photo for Scene #${sceneNum}…`, 'info');

    try {
      const res = await fetch('/api/video-studio/render-image', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          scene_number: sceneNum,
          prompt: scene.image_prompt,
          character_id: activePersona?.id || 'airi'
        })
      });
      if (!res.ok) throw new Error('Image render failed');
      const data = await res.json();
      scene.image_path = data.image.path;
      renderStoryboardGrid();
      if (data.image && data.image.model_ready === false) {
        notify(`ℹ️ Scene #${sceneNum} preview created. Open 'AI Models' in the header to download FLUX or connect cloud!`, 'info');
      } else {
        notify(`✓ Photo ready for Scene #${sceneNum}!`, 'success');
      }
      saveStoryboardToProject();
    } catch (e) {
      notify('Photo render failed: ' + e.message, 'error');
    }
  }

  async function renderSingleVideo(sceneNum) {
    const scene = storyboardScenes.find(s => s.number === sceneNum);
    if (!scene) return;
    if (!scene.image_path) {
      await renderSingleImage(sceneNum);
    }
    notify(`Animating Scene #${sceneNum}…`, 'info');

    try {
      const dur = Math.max(3.0, (scene.end_time - scene.start_time) || 5.0);
      const res = await fetch('/api/video-studio/render-video', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          scene_number: sceneNum,
          image_path: scene.image_path,
          motion_prompt: scene.motion_prompt,
          duration: dur
        })
      });
      if (!res.ok) throw new Error('Video animation failed');
      const data = await res.json();
      scene.video_path = data.video.path;
      renderStoryboardGrid();
      if (data.video && data.video.model_ready === false) {
        notify(`ℹ️ Scene #${sceneNum} camera motion preview created. Download Wan 2.1 in 'AI Models' for full motion diffusion!`, 'info');
      } else {
        notify(`✓ Scene #${sceneNum} video clip ready!`, 'success');
      }
      saveStoryboardToProject();
    } catch (e) {
      notify('Video animation failed: ' + e.message, 'error');
    }
  }

  // --- Sequential Review Workflow (Phase 1: Render All Photos -> Pause -> Phase 2: Animate All) ---
  async function renderAllKeyframes() {
    if (!storyboardScenes.length) {
      notify('Generate a storyboard first.', 'warning');
      return;
    }
    const btn = document.getElementById('renderAllImagesBtn');
    btn.disabled = true;
    btn.textContent = '⏳ Rendering Photos…';

    for (let i = 0; i < storyboardScenes.length; i++) {
      const s = storyboardScenes[i];
      btn.textContent = `⏳ Rendering Photo ${i + 1}/${storyboardScenes.length}…`;
      await renderSingleImage(s.number);
    }

    btn.disabled = false;
    btn.textContent = '✓ Photos Complete!';
    document.getElementById('vsPhaseBadge').textContent = 'Phase 1 Complete: Review & Re-roll Photos Below';
    notify('✓ All keyframe photos ready! Review them, roll again if needed, then click Animate Scenes.', 'success');
  }

  async function animateAllScenes() {
    if (!storyboardScenes.length) return;
    const btn = document.getElementById('animateAllVideosBtn');
    btn.disabled = true;

    for (let i = 0; i < storyboardScenes.length; i++) {
      const s = storyboardScenes[i];
      btn.textContent = `⏳ Animating Scene ${i + 1}/${storyboardScenes.length}…`;
      await renderSingleVideo(s.number);
    }

    btn.disabled = false;
    btn.textContent = '✓ Videos Complete!';
    document.getElementById('vsPhaseBadge').textContent = 'Phase 2 Complete: Ready to Open in Caption Studio';
    notify('✓ All video scenes animated! Click "Open in Caption Studio" to lock on timeline.', 'success');
  }

  async function saveStoryboardToProject() {
    if (!currentProject) return;
    try {
      await fetch(`/api/captions/${currentProject.id}/storyboard`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({ storyboard: storyboardScenes })
      });
    } catch (_) {}
  }

  async function bridgeToCaptionStudio() {
    if (!currentProject) {
      notify('Select a project first.', 'warning');
      return;
    }
    const readyVideos = storyboardScenes.filter(s => Boolean(s.video_path));
    if (!readyVideos.length) {
      notify('Please animate at least one scene video first.', 'warning');
      return;
    }

    const bridgeBtn = document.getElementById('bridgeToCaptionsBtn');
    bridgeBtn.disabled = true;
    bridgeBtn.textContent = '⏳ Assembling Timeline…';

    try {
      const res = await fetch(`/api/captions/${currentProject.id}/bridge-storyboard`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        }
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || 'Failed to bridge storyboard');
      }
      notify('✓ Timeline sequence assembled! Opening Caption Studio…', 'success');
      setTimeout(() => {
        window.location.href = `/captions?project=${encodeURIComponent(currentProject.id)}`;
      }, 1000);
    } catch (e) {
      notify('Bridge error: ' + e.message, 'error');
      bridgeBtn.disabled = false;
      bridgeBtn.textContent = '🎤 Open in Caption Studio';
    }
  }

  // --- AI Model Hub Client Orchestrator (12GB GPU & Cloud Weights) ---
  let modelsData = null;
  let modelPollTimer = null;

  async function loadModelHubState() {
    try {
      const res = await fetch('/api/video-studio/models');
      if (!res.ok) return;
      modelsData = await res.json();
      updateModelHubUI(modelsData);
    } catch (_) {}
  }

  function updateModelHubUI(data) {
    if (!data) return;
    const { models, gpu, config, summary } = data;

    // Header badge
    const badge = document.getElementById('modelHubStatusBadge');
    if (badge) {
      if (summary.image_ready && summary.video_ready) {
        badge.textContent = '🟢 2 Ready';
        badge.style.color = '#34d399';
      } else if (summary.image_ready || summary.video_ready) {
        badge.textContent = '🟡 1 Ready';
        badge.style.color = '#fbbf24';
      } else if (summary.cloud_enabled) {
        badge.textContent = '☁️ Cloud Active';
        badge.style.color = '#38bdf8';
      } else {
        badge.textContent = '⚪ Not Installed';
        badge.style.color = '#94a3b8';
      }
    }

    // Engine pill in toolbar
    const pill = document.getElementById('vsEnginePill');
    if (pill && gpu) {
      const vramStr = gpu.vram_gb > 0 ? `${gpu.vram_gb}GB VRAM` : 'No CUDA';
      const activeImg = config.active_image_model ? config.active_image_model.split('-')[0].toUpperCase() : 'FLUX';
      const activeVid = config.active_video_model ? 'Wan 2.1' : 'Video';
      pill.textContent = `⚡ GPU: ${gpu.device_name} (${vramStr}) • ${activeImg} & ${activeVid}`;
    }

    // Hardware Banner in Modal
    const gpuNameEl = document.getElementById('gpuDeviceName');
    const gpuRecEl = document.getElementById('gpuRecommendation');
    const gpuBadgeEl = document.getElementById('gpuVramBadge');
    if (gpuNameEl && gpu) gpuNameEl.textContent = `${gpu.device_name} (${gpu.vram_gb} GB VRAM)`;
    if (gpuRecEl && gpu) gpuRecEl.textContent = `Preset: ${gpu.recommended_preset} • Optimized for 12GB Quantized weights`;
    if (gpuBadgeEl && gpu) gpuBadgeEl.textContent = `${gpu.vram_gb} GB VRAM`;

    // Render Cards in Grids
    renderModelGrid('imageModelsGrid', models.filter(m => m.category === 'image'), config.active_image_model);
    renderModelGrid('videoModelsGrid', models.filter(m => m.category === 'video'), config.active_video_model);

    // Populate Cloud Config
    if (config.cloud_backend) {
      const cb = config.cloud_backend;
      const toggle = document.getElementById('enableCloudToggle');
      const comfy = document.getElementById('comfyUrlInput');
      const prov = document.getElementById('cloudApiProvider');
      const key = document.getElementById('cloudApiKeyInput');
      if (toggle) toggle.checked = Boolean(cb.enabled);
      if (comfy && !comfy.value) comfy.value = cb.comfy_url || 'http://127.0.0.1:8188';
      if (prov) prov.value = cb.api_provider || 'huggingface';
      if (key && !key.value) key.value = cb.api_key || '';
    }

    // Real-time polling if any download is active
    const isDownloading = models.some(m => m.status === 'downloading');
    clearTimeout(modelPollTimer);
    if (isDownloading) {
      modelPollTimer = setTimeout(loadModelHubState, 1500);
      if (badge) {
        badge.textContent = '⏳ Downloading…';
        badge.style.color = '#38bdf8';
      }
    }
  }

  function renderModelGrid(containerId, modelsList, activeModelId) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.replaceChildren();

    modelsList.forEach(m => {
      const card = document.createElement('div');
      card.className = `hubModelCard ${m.id === activeModelId ? 'activeModel' : ''}`;

      // Top row
      const top = document.createElement('div');
      top.className = 'hubCardTop';
      const title = document.createElement('div');
      title.className = 'hubCardTitle';
      title.textContent = m.name;
      const vramBadge = document.createElement('span');
      vramBadge.className = 'hubCardVramBadge';
      vramBadge.textContent = m.vram_req;
      top.append(title, vramBadge);

      // Description
      const desc = document.createElement('div');
      desc.className = 'hubCardDesc';
      desc.textContent = m.recommended_for;

      // Meta row
      const meta = document.createElement('div');
      meta.className = 'hubCardMetaRow';
      const sizeSpan = document.createElement('span');
      sizeSpan.textContent = `Size: ~${m.size_gb} GB (${m.format.toUpperCase()})`;

      const statusBox = document.createElement('div');
      statusBox.className = 'hubCardStatus';
      const dot = document.createElement('span');
      dot.className = `hubStatusDot ${m.status}`;
      const statusLabel = document.createElement('span');
      statusLabel.textContent = m.status === 'ready' ? 'Ready' : (m.status === 'downloading' ? `Downloading ${m.progress}%` : 'Not Installed');
      statusBox.append(dot, statusLabel);
      meta.append(sizeSpan, statusBox);

      card.append(top, desc, meta);

      // Progress bar if downloading
      if (m.status === 'downloading') {
        const progWrapper = document.createElement('div');
        progWrapper.className = 'hubProgressWrapper';
        const progHeader = document.createElement('div');
        progHeader.className = 'hubProgressHeader';
        progHeader.innerHTML = `<span>${m.speed || 'Downloading...'}</span><span>${m.progress}%</span>`;
        const track = document.createElement('div');
        track.className = 'hubProgressBarTrack';
        const fill = document.createElement('div');
        fill.className = 'hubProgressBarFill';
        fill.style.width = `${m.progress}%`;
        track.appendChild(fill);
        progWrapper.append(progHeader, track);
        card.appendChild(progWrapper);
      }

      // Actions row
      const actions = document.createElement('div');
      actions.className = 'hubCardActions';

      if (m.status === 'ready') {
        const selectBtn = document.createElement('button');
        selectBtn.type = 'button';
        selectBtn.className = `hubBtn ${m.id === activeModelId ? 'hubBtnPrimary' : 'hubBtnSecondary'}`;
        selectBtn.textContent = m.id === activeModelId ? '✓ Active Model' : 'Select as Active';
        selectBtn.onclick = () => selectActiveModel(m.category, m.id);

        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'hubBtn hubBtnDanger';
        deleteBtn.title = 'Delete downloaded weights to reclaim disk space';
        deleteBtn.innerHTML = '🗑️';
        deleteBtn.onclick = () => deleteModelWeights(m.id);

        actions.append(selectBtn, deleteBtn);
      } else if (m.status === 'downloading') {
        const cancelBtn = document.createElement('button');
        cancelBtn.type = 'button';
        cancelBtn.className = 'hubBtn hubBtnSecondary';
        cancelBtn.textContent = '⏹️ Cancel Download';
        cancelBtn.onclick = () => cancelDownload(m.id);
        actions.appendChild(cancelBtn);
      } else {
        const dlBtn = document.createElement('button');
        dlBtn.type = 'button';
        dlBtn.className = 'hubBtn hubBtnPrimary';
        dlBtn.innerHTML = `📥 Download (${m.size_gb} GB)`;
        dlBtn.onclick = () => triggerDownload(m.id);
        actions.appendChild(dlBtn);
      }

      card.appendChild(actions);
      el.appendChild(card);
    });
  }

  function openModelHub() {
    const modal = document.getElementById('modelHubModal');
    if (modal) {
      modal.style.display = 'flex';
      loadModelHubState();
    }
  }

  function closeModelHub() {
    const modal = document.getElementById('modelHubModal');
    if (modal) modal.style.display = 'none';
  }

  function switchModelTab(tab) {
    const isLocal = tab === 'local';
    document.getElementById('tabBtnLocalModels').classList.toggle('active', isLocal);
    document.getElementById('tabBtnCloudBackend').classList.toggle('active', !isLocal);
    document.getElementById('tabPanelLocalModels').style.display = isLocal ? 'block' : 'none';
    document.getElementById('tabPanelCloudBackend').style.display = isLocal ? 'none' : 'block';
  }

  async function triggerDownload(modelId) {
    notify(`Starting download for ${modelId}…`, 'info');
    try {
      const res = await fetch('/api/video-studio/models/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Media-Token': getToken() },
        body: JSON.stringify({ model_id: modelId })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to start download');
      notify(`✓ ${data.message || 'Download started!'}`, 'success');
      loadModelHubState();
    } catch (e) {
      notify(`Download error: ${e.message}`, 'error');
    }
  }

  async function cancelDownload(modelId) {
    try {
      await fetch('/api/video-studio/models/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Media-Token': getToken() },
        body: JSON.stringify({ model_id: modelId })
      });
      notify('Download cancelled.', 'info');
      loadModelHubState();
    } catch (e) {
      notify('Failed to cancel: ' + e.message, 'error');
    }
  }

  async function deleteModelWeights(modelId) {
    if (!confirm(`Are you sure you want to delete ${modelId} weights from your PC to reclaim storage?`)) return;
    try {
      const res = await fetch('/api/video-studio/models/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Media-Token': getToken() },
        body: JSON.stringify({ model_id: modelId })
      });
      const data = await res.json();
      notify(`✓ ${data.message || 'Model removed'}`, 'success');
      loadModelHubState();
    } catch (e) {
      notify('Delete failed: ' + e.message, 'error');
    }
  }

  async function selectActiveModel(category, modelId) {
    try {
      const payload = category === 'image' ? { active_image_model: modelId } : { active_video_model: modelId };
      const res = await fetch('/api/video-studio/models/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Media-Token': getToken() },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        notify(`✓ Set active ${category} model to ${modelId}`, 'success');
        loadModelHubState();
      }
    } catch (_) {}
  }

  async function testComfyConnection() {
    const url = document.getElementById('comfyUrlInput').value.trim() || 'http://127.0.0.1:8188';
    notify(`Testing connection to ${url}…`, 'info');
    try {
      const res = await fetch(`${url}/system_stats`, { mode: 'cors' }).catch(() => null);
      if (res && res.ok) {
        notify(`✓ Connected to ComfyUI successfully!`, 'success');
      } else {
        notify(`Could not reach ComfyUI at ${url}. Ensure ComfyUI is running with --enable-cors-header.`, 'warning');
      }
    } catch (e) {
      notify(`Connection error: ${e.message}`, 'error');
    }
  }

  async function saveCloudSettings() {
    const enabled = document.getElementById('enableCloudToggle').checked;
    const comfy_url = document.getElementById('comfyUrlInput').value.trim();
    const api_provider = document.getElementById('cloudApiProvider').value;
    const api_key = document.getElementById('cloudApiKeyInput').value.trim();

    try {
      const res = await fetch('/api/video-studio/models/cloud-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Media-Token': getToken() },
        body: JSON.stringify({ enabled, comfy_url, api_provider, api_key })
      });
      if (res.ok) {
        notify('✓ Cloud backend configuration saved!', 'success');
        loadModelHubState();
      }
    } catch (e) {
      notify('Failed to save settings: ' + e.message, 'error');
    }
  }

  function fmt(s) {
    if (!Number.isFinite(s)) return '0:00';
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60).toString().padStart(2, '0');
    return `${m}:${sec}`;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
