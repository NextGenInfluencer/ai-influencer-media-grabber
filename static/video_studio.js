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
      loadActivePersona()
    ]);
  }

  function bindEvents() {
    document.getElementById('vsProjectSelect').onchange = onProjectChange;
    document.getElementById('generateStoryboardBtn').onclick = generateStoryboardScenes;
    document.getElementById('renderAllImagesBtn').onclick = renderAllKeyframes;
    document.getElementById('animateAllVideosBtn').onclick = animateAllScenes;
    document.getElementById('bridgeToCaptionsBtn').onclick = bridgeToCaptionStudio;

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
      notify(`✓ Photo ready for Scene #${sceneNum}!`, 'success');
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
    notify(`Animating Scene #${sceneNum} with Wan 2.1…`, 'info');

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
      notify(`✓ Scene #${sceneNum} video clip ready!`, 'success');
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
