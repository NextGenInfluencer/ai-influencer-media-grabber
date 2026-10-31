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

    // AI Director triggers
    const aiAnalyzeBtn = document.getElementById('aiAnalyzeStylesBtn');
    if (aiAnalyzeBtn) aiAnalyzeBtn.onclick = analyzeSongStyles;

    // Storyboard toolbar model selectors
    const photoModelSel = document.getElementById('storyboardPhotoModelSelect');
    if (photoModelSel) {
      photoModelSel.onchange = updateStoryboardModelLabels;
    }
    const vidModelSel = document.getElementById('storyboardVideoModelSelect');
    if (vidModelSel) {
      vidModelSel.onchange = updateStoryboardModelLabels;
    }
    updateStoryboardModelLabels();

    const aiSendBtn = document.getElementById('aiDirectorSendBtn');
    if (aiSendBtn) aiSendBtn.onclick = () => sendDirectorChatMessage();

    const aiInput = document.getElementById('aiDirectorInput');
    if (aiInput) {
      aiInput.onkeydown = (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          sendDirectorChatMessage();
        }
      };
    }

    document.querySelectorAll('.directorPillBtn').forEach(btn => {
      btn.onclick = () => {
        const prompt = btn.getAttribute('data-prompt') || btn.textContent.trim();
        sendDirectorChatMessage(prompt);
      };
    });

    // + New Project modal triggers
    const newProjBtn = document.getElementById('vsNewProjectBtn');
    if (newProjBtn) newProjBtn.onclick = openNewProjectModal;
    const closeNewProjBtn = document.getElementById('closeNewProjectBtn');
    if (closeNewProjBtn) closeNewProjBtn.onclick = closeNewProjectModal;
    const cancelNewProjBtn = document.getElementById('cancelNewProjectBtn');
    if (cancelNewProjBtn) cancelNewProjBtn.onclick = closeNewProjectModal;
    const cancelAudioProjBtn = document.getElementById('cancelAudioProjectBtn');
    if (cancelAudioProjBtn) cancelAudioProjBtn.onclick = closeNewProjectModal;

    const tabFreeform = document.getElementById('tabBtnFreeform');
    if (tabFreeform) tabFreeform.onclick = () => switchNewProjTab('freeform');
    const tabAudio = document.getElementById('tabBtnAudio');
    if (tabAudio) tabAudio.onclick = () => switchNewProjTab('audio');

    const createFreeformBtn = document.getElementById('createFreeformProjectBtn');
    if (createFreeformBtn) createFreeformBtn.onclick = submitFreeformProject;
    const createAudioBtn = document.getElementById('createAudioProjectBtn');
    if (createAudioBtn) createAudioBtn.onclick = submitAudioProject;

    // Studio Mode Switcher
    const modeStory = document.getElementById('modeStoryboardBtn');
    if (modeStory) modeStory.onclick = () => switchStudioMode('storyboard');
    const modeMotion = document.getElementById('modeMotionBtn');
    if (modeMotion) modeMotion.onclick = () => switchStudioMode('motion');

    // Wan 2.1 Motion Mimic controls
    const driveSelect = document.getElementById('drivingVideoSelect');
    if (driveSelect) driveSelect.onchange = onDrivingVideoChange;
    const refreshDriveBtn = document.getElementById('refreshDrivingVideosBtn');
    if (refreshDriveBtn) refreshDriveBtn.onclick = loadDrivingVideos;
    const uploadDriveBtn = document.getElementById('uploadDrivingVideoBtn');
    const driveFileInput = document.getElementById('drivingVideoFileInput');
    if (uploadDriveBtn && driveFileInput) {
      uploadDriveBtn.onclick = () => driveFileInput.click();
      driveFileInput.onchange = onDrivingVideoUpload;
    }
    const genMotionBtn = document.getElementById('generateWanMotionBtn');
    if (genMotionBtn) genMotionBtn.onclick = generateWanMotion;
    const quickMotionBtn = document.getElementById('quickStartMotionBtn');
    if (quickMotionBtn) quickMotionBtn.onclick = generateWanMotion;
    const extractFrameBtn = document.getElementById('extractRefFrameBtn');
    if (extractFrameBtn) extractFrameBtn.onclick = extractDrivingReferenceFrame;
    const swapIdentityBtn = document.getElementById('motionSwapIdentityBtn');
    if (swapIdentityBtn) swapIdentityBtn.onclick = onSwapIdentityClick;
    const uploadSwapBtn = document.getElementById('uploadSwappedFrameBtn');
    const swapFileInput = document.getElementById('swappedFrameFileInput');
    const engineSel = document.getElementById('motionSwapEngineSelect');
    if (uploadSwapBtn && swapFileInput) {
      uploadSwapBtn.onclick = () => swapFileInput.click();
      swapFileInput.onchange = onCustomSwappedFrameUpload;
    }
    if (engineSel && swapFileInput) {
      engineSel.onchange = () => {
        if (engineSel.value === 'custom') {
          swapFileInput.click();
        }
      };
    }
    const copyPromptBtn = document.getElementById('copyMotionPromptBtn');
    if (copyPromptBtn) copyPromptBtn.onclick = onCopyMotionPromptClick;
    const motionPersonaBtn = document.getElementById('motionSwitchPersonaBtn');
    if (motionPersonaBtn) motionPersonaBtn.onclick = () => { if (window.characterStudio) window.characterStudio.open(); };

    // Audio dropzone in New Project modal
    const dropArea = document.getElementById('audioDropArea');
    const audioInput = document.getElementById('audioFileInput');
    if (dropArea && audioInput) {
      dropArea.onclick = () => audioInput.click();
      dropArea.ondragover = (e) => { e.preventDefault(); dropArea.style.borderColor = '#0a84ff'; };
      dropArea.ondragleave = () => { dropArea.style.borderColor = 'rgba(255,255,255,0.15)'; };
      dropArea.ondrop = (e) => {
        e.preventDefault();
        dropArea.style.borderColor = 'rgba(255,255,255,0.15)';
        if (e.dataTransfer.files.length) {
          audioInput.files = e.dataTransfer.files;
          onAudioFileSelected();
        }
      };
      audioInput.onchange = onAudioFileSelected;
    }

    // Per-Scene Mimic modal
    const closeMimicBtn = document.getElementById('closeSceneMimicBtn');
    if (closeMimicBtn) closeMimicBtn.onclick = closeSceneMimicModal;
    const cancelMimicBtn = document.getElementById('cancelSceneMimicBtn');
    if (cancelMimicBtn) cancelMimicBtn.onclick = closeSceneMimicModal;
    const confirmMimicBtn = document.getElementById('confirmSceneMimicBtn');
    if (confirmMimicBtn) confirmMimicBtn.onclick = confirmSceneMimic;
    const sceneMimicSelect = document.getElementById('sceneMimicSelect');
    if (sceneMimicSelect) sceneMimicSelect.onchange = onSceneMimicSelectChange;

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
      if (e.key === 'Escape') {
        closeModelHub();
        closeNewProjectModal();
        closeSceneMimicModal();
      }
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

    // Motion panel persona
    const mTitle = document.getElementById('motionPersonaTitle');
    const mTag = document.getElementById('motionPersonaTag');
    const mAvatar = document.getElementById('motionPersonaAvatar');
    if (mTitle) mTitle.textContent = activePersona.name;
    if (mTag) mTag.textContent = activePersona.tag;
    if (mAvatar) {
      if (activePersona.portrait_file) {
        mAvatar.style.backgroundImage = `url('/api/characters/${activePersona.id}/image/${activePersona.portrait_file}')`;
        mAvatar.textContent = '';
      } else {
        mAvatar.style.backgroundImage = 'none';
        mAvatar.textContent = (activePersona.name || 'A').charAt(0).toUpperCase();
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
      const cueCountEl = document.getElementById('vsCueCount');
      if (cueCountEl) cueCountEl.textContent = (currentProject.cues || []).length;

      // Audio setup
      const audioEl = document.getElementById('vsAudioPlayer');
      const statsEl = document.getElementById('vsSongStats');
      if (currentProject.source) {
        audioEl.src = `/api/captions/${pid}/media/${encodeURIComponent(currentProject.preview || currentProject.source)}`;
        audioEl.style.display = 'block';
        if (statsEl) statsEl.innerHTML = `Duration: <span id="vsSongDuration">${fmt(currentProject.duration || 0)}</span> • <span id="vsCueCount">${(currentProject.cues || []).length}</span> lyric lines`;
      } else {
        audioEl.removeAttribute('src');
        audioEl.style.display = 'none';
        if (statsEl) statsEl.innerHTML = `Duration: <span id="vsSongDuration">${fmt(currentProject.duration || 0)}</span> • ${(currentProject.storyboard || currentProject.cues || []).length} Scenes (Freeform AI Video, No Music)`;
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

  // ==========================================
  // AI Director: Song Analysis & Bespoke Styles
  // ==========================================

  async function analyzeSongStyles() {
    const btn = document.getElementById('aiAnalyzeStylesBtn');
    const container = document.getElementById('aiSuggestedStylesContainer');
    const genrePill = document.getElementById('aiDirectorGenrePill');
    const tonePill = document.getElementById('aiDirectorTonePill');
    const hookText = document.getElementById('aiDirectorHookText');

    const lyrics = (currentProject?.cues || []).map(c => c.text || '').filter(Boolean).join(' ');
    const songTitle = currentProject?.name || currentProject?.title || '';
    const concept = currentProject?.concept || '';
    const cid = activePersona?.id || 'airi';

    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span>⏳ Analyzing song emotional arc &amp; rhythm…</span>';
    }

    try {
      const res = await fetch('/api/video-studio/director/analyze', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          lyrics: lyrics,
          song_title: songTitle,
          concept: concept,
          character_id: cid
        })
      });

      if (!res.ok) throw new Error('Analysis request failed');
      const data = await res.json();
      const analysis = data.analysis || {};
      const concepts = data.concepts || [];

      if (container) container.style.display = 'flex';
      if (genrePill) genrePill.textContent = `🎵 ${analysis.genre || 'Atmospheric'}`;
      if (tonePill) tonePill.textContent = analysis.tone || 'Dynamic & Cinematic';
      if (hookText) hookText.textContent = analysis.hook || '';

      renderSuggestedStyles(concepts);
      notify(`✓ AI Director formulated ${concepts.length} visual styles tailored for this track!`, 'success');
    } catch (e) {
      notify('AI Director error: ' + e.message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = '<span>🧠 AI Director: Analyze Song &amp; Suggest Styles</span>';
      }
    }
  }

  function renderSuggestedStyles(concepts) {
    const grid = document.getElementById('aiDirectorCardsGrid');
    if (!grid) return;
    grid.replaceChildren();

    concepts.forEach(c => {
      const card = document.createElement('div');
      card.className = 'directorStyleCard';
      card.id = `directorStyle_${c.id || Math.random().toString(36).substring(7)}`;

      const titleRow = document.createElement('div');
      titleRow.className = 'cardStyleTitleRow';
      titleRow.innerHTML = `<span>${c.icon || '🎨'}</span> <span>${c.name}</span>`;

      const tagline = document.createElement('p');
      tagline.className = 'cardTagline';
      tagline.textContent = c.tagline || '';

      const swatchRow = document.createElement('div');
      swatchRow.className = 'swatchRow';
      (c.palette || []).forEach(hex => {
        const dot = document.createElement('span');
        dot.className = 'swatchDot';
        dot.style.backgroundColor = hex;
        dot.title = hex;
        swatchRow.appendChild(dot);
      });

      const brief = document.createElement('div');
      brief.className = 'cardDetailBrief';
      if (c.lighting) {
        const l = document.createElement('span');
        l.textContent = `💡 ${c.lighting}`;
        brief.appendChild(l);
      }
      if (c.camera_style) {
        const cam = document.createElement('span');
        cam.textContent = `🎥 ${c.camera_style}`;
        brief.appendChild(cam);
      }

      card.append(titleRow, tagline, swatchRow, brief);
      card.onclick = () => selectAndApplyDirectorConcept(c, card);
      grid.appendChild(card);
    });
  }

  function selectAndApplyDirectorConcept(concept, cardEl) {
    // 1. Highlight selected card
    document.querySelectorAll('.directorStyleCard').forEach(c => c.classList.remove('active'));
    if (cardEl) cardEl.classList.add('active');

    // 2. Add or select option in #vsMoodSelect
    const moodSelect = document.getElementById('vsMoodSelect');
    if (moodSelect) {
      let found = false;
      for (let i = 0; i < moodSelect.options.length; i++) {
        if (moodSelect.options[i].value === concept.prompt_atmosphere) {
          moodSelect.selectedIndex = i;
          found = true;
          break;
        }
      }
      if (!found) {
        const opt = document.createElement('option');
        opt.value = concept.prompt_atmosphere;
        opt.textContent = `${concept.icon || '🎨'} ${concept.name}`;
        moodSelect.prepend(opt);
        moodSelect.selectedIndex = 0;
      }
    }

    // 3. Update existing storyboard scenes with the new visual aesthetic
    if (storyboardScenes && storyboardScenes.length > 0) {
      const charTag = activePersona?.tag || '@Airi';
      const charTrigger = activePersona?.trigger_prompt || 'Airi, 22yo Japanese virtual singer';
      const aspect = activePersona?.aspect_ratio || '9:16';

      storyboardScenes.forEach((s) => {
        // Build crisp prompt combining persona, scene mood, new directorial atmosphere
        s.image_prompt = `${charTrigger}, ${s.lyrics ? s.lyrics + ', ' : ''}${concept.prompt_atmosphere}, natural hand articulation, photorealistic 8k, aspect ratio ${aspect}`.replace(/\s+/g, ' ').trim();
        s.prompt = s.image_prompt;
        if (concept.camera_style) {
          s.camera_motion = concept.camera_style;
          s.motion_prompt = `Cinematic ${concept.camera_style}. ${charTag} performing naturally with expressive emotion.`;
        }
      });

      renderStoryboardGrid();
      saveStoryboardToProject();
      notify(`✓ Applied "${concept.name}" to all ${storyboardScenes.length} scenes!`, 'success');
    } else {
      notify(`✓ Directorial aesthetic set to "${concept.name}"! Click '⚡ Generate Storyboard' to apply.`, 'success');
    }
  }

  async function sendDirectorChatMessage(overridePrompt) {
    const input = document.getElementById('aiDirectorInput');
    const sendBtn = document.getElementById('aiDirectorSendBtn');
    const chatStream = document.getElementById('aiDirectorChatStream');

    const msg = (overridePrompt || (input ? input.value : '')).trim();
    if (!msg) return;

    if (input) input.value = '';

    // Append User message
    const userMsgEl = document.createElement('div');
    userMsgEl.className = 'chatMsg userMsg';
    userMsgEl.textContent = msg;
    chatStream.appendChild(userMsgEl);
    chatStream.scrollTop = chatStream.scrollHeight;

    // Loading indicator
    const aiMsgEl = document.createElement('div');
    aiMsgEl.className = 'chatMsg aiMsg';
    aiMsgEl.textContent = 'Co-Director formulating aesthetic…';
    chatStream.appendChild(aiMsgEl);
    chatStream.scrollTop = chatStream.scrollHeight;

    if (sendBtn) sendBtn.disabled = true;

    try {
      const lyrics = (currentProject?.cues || []).map(c => c.text || '').filter(Boolean).join(' ');
      const songTitle = currentProject?.name || currentProject?.title || '';
      const cid = activePersona?.id || 'airi';

      const res = await fetch('/api/video-studio/director/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          message: msg,
          lyrics: lyrics,
          song_title: songTitle,
          character_id: cid
        })
      });

      if (!res.ok) throw new Error('Director chat failed');
      const data = await res.json();
      aiMsgEl.textContent = data.reply || "I've tailored a custom directorial concept for this track!";

      if (data.concept) {
        // Automatically apply the invented concept
        selectAndApplyDirectorConcept(data.concept);

        // Also add card to suggestions grid and make it visible
        const container = document.getElementById('aiSuggestedStylesContainer');
        if (container) container.style.display = 'flex';
        const grid = document.getElementById('aiDirectorCardsGrid');
        if (grid) {
          const card = document.createElement('div');
          card.className = 'directorStyleCard active';
          card.id = `directorStyle_custom_${Date.now()}`;

          const titleRow = document.createElement('div');
          titleRow.className = 'cardStyleTitleRow';
          titleRow.innerHTML = `<span>${data.concept.icon || '✨'}</span> <span>${data.concept.name}</span>`;

          const tagline = document.createElement('p');
          tagline.className = 'cardTagline';
          tagline.textContent = data.concept.tagline || '';

          const swatchRow = document.createElement('div');
          swatchRow.className = 'swatchRow';
          (data.concept.palette || []).forEach(hex => {
            const dot = document.createElement('span');
            dot.className = 'swatchDot';
            dot.style.backgroundColor = hex;
            dot.title = hex;
            swatchRow.appendChild(dot);
          });

          card.append(titleRow, tagline, swatchRow);
          card.onclick = () => selectAndApplyDirectorConcept(data.concept, card);
          grid.prepend(card);
        }
      }
    } catch (e) {
      aiMsgEl.textContent = 'Error: ' + e.message;
    } finally {
      if (sendBtn) sendBtn.disabled = false;
      chatStream.scrollTop = chatStream.scrollHeight;
    }
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

      const mimicBtn = document.createElement('button');
      mimicBtn.className = 'vsSceneBtn mimicBtn';
      mimicBtn.type = 'button';
      mimicBtn.textContent = '💃 Mimic Reference Video';
      mimicBtn.onclick = () => openSceneMimicModal(s.number);

      actions.append(rollImgBtn, animBtn, mimicBtn);

      card.append(header, lyricsDiv, mediaRow, promptBox, actions);
      grid.appendChild(card);
    });
  }

  function updateStoryboardModelLabels() {
    const photoSel = document.getElementById('storyboardPhotoModelSelect');
    const photoLabel = document.getElementById('renderAllImagesLabel');
    if (photoSel && photoLabel) {
      const opt = photoSel.options[photoSel.selectedIndex];
      const cleanName = opt ? opt.textContent.replace(/^[^\w]+/, '').replace(/\s*\(.*\)/, '').trim() : 'FLUX';
      photoLabel.textContent = `🎨 1. Render Photos (${cleanName})`;
    }
    const vidSel = document.getElementById('storyboardVideoModelSelect');
    const vidLabel = document.getElementById('animateAllVideosLabel');
    if (vidSel && vidLabel) {
      const opt = vidSel.options[vidSel.selectedIndex];
      const cleanName = opt ? opt.textContent.replace(/^[^\w]+/, '').replace(/\s*\(.*\)/, '').trim() : 'Wan 2.1';
      vidLabel.textContent = `🎬 2. Animate Scenes (${cleanName})`;
    }
  }

  async function renderSingleImage(sceneNum) {
    const scene = storyboardScenes.find(s => s.number === sceneNum);
    if (!scene) return;
    notify(`Generating Photo for Scene #${sceneNum}…`, 'info');

    try {
      const selectedModel = document.getElementById('storyboardPhotoModelSelect')?.value || 'flux-schnell-nf4';
      const res = await fetch('/api/video-studio/render-image', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          scene_number: sceneNum,
          prompt: scene.image_prompt,
          character_id: activePersona?.id || 'airi',
          model_id: selectedModel
        })
      });
      if (!res.ok) throw new Error('Image render failed');
      const data = await res.json();
      scene.image_path = data.image.path;
      renderStoryboardGrid();
      if (data.image && data.image.model_ready === false) {
        notify(`ℹ️ Scene #${sceneNum} preview created. Open 'AI Models' in the header to download ${data.image.model_required || 'model'}!`, 'info');
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
      const selectedModel = document.getElementById('storyboardVideoModelSelect')?.value || 'wan-2.1-1.3b';
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
          duration: dur,
          model_id: selectedModel
        })
      });
      if (!res.ok) throw new Error('Video animation failed');
      const data = await res.json();
      scene.video_path = data.video.path;
      renderStoryboardGrid();
      if (data.video && data.video.model_ready === false) {
        notify(`ℹ️ Scene #${sceneNum} camera motion preview created. Download ${data.video.model_required || 'Wan 2.1'} in 'AI Models'!`, 'info');
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

    // Update Storyboard Toolbar Model Selectors
    const photoSel = document.getElementById('storyboardPhotoModelSelect');
    if (photoSel && models) {
      const curPhoto = photoSel.value;
      const imgModels = models.filter(m => m.category === 'image');
      if (imgModels.length) {
        photoSel.replaceChildren(
          ...imgModels.map(m => {
            const opt = document.createElement('option');
            opt.value = m.id;
            const icon = m.status === 'ready' ? '🟢 ' : (m.status === 'downloading' ? '⏳ ' : '');
            opt.textContent = `${icon}${m.name} (${m.size_gb}GB)`;
            return opt;
          })
        );
        if (curPhoto && Array.from(photoSel.options).some(o => o.value === curPhoto)) {
          photoSel.value = curPhoto;
        } else if (config.active_image_model) {
          photoSel.value = config.active_image_model;
        }
      }
    }

    const vidSel = document.getElementById('storyboardVideoModelSelect');
    if (vidSel && models) {
      const curVid = vidSel.value;
      const vidModels = models.filter(m => m.category === 'video');
      if (vidModels.length) {
        vidSel.replaceChildren(
          ...vidModels.map(m => {
            const opt = document.createElement('option');
            opt.value = m.id;
            const icon = m.status === 'ready' ? '🟢 ' : (m.status === 'downloading' ? '⏳ ' : '');
            opt.textContent = `${icon}${m.name} (${m.size_gb}GB)`;
            return opt;
          })
        );
        if (curVid && Array.from(vidSel.options).some(o => o.value === curVid)) {
          vidSel.value = curVid;
        } else if (config.active_video_model) {
          vidSel.value = config.active_video_model;
        }
      }
    }
    updateStoryboardModelLabels();

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
    const downloadingModels = models.filter(m => m.status === 'downloading');
    const isDownloading = downloadingModels.length > 0;
    clearTimeout(modelPollTimer);
    if (isDownloading) {
      modelPollTimer = setTimeout(loadModelHubState, 1000);
      const activeDl = downloadingModels[0];
      const modelShortName = activeDl.name.replace(/\s*\(.*\)/, '');
      if (badge) {
        badge.textContent = `⏳ ${modelShortName} ${activeDl.progress}% (${activeDl.speed})`;
        badge.style.color = '#38bdf8';
      }
      if (pill) {
        pill.textContent = `⚡ Downloading ${modelShortName}: ${activeDl.progress}% • ${activeDl.speed}`;
        pill.style.borderColor = 'rgba(56, 189, 248, 0.4)';
      }
    } else {
      if (pill && gpu) {
        const vramStr = gpu.vram_gb > 0 ? `${gpu.vram_gb}GB VRAM` : 'No CUDA';
        const activeImg = config.active_image_model ? config.active_image_model.split('-')[0].toUpperCase() : 'FLUX';
        const activeVid = config.active_video_model ? 'Wan 2.1' : 'Video';
        pill.textContent = `⚡ GPU: ${gpu.device_name} (${vramStr}) • ${activeImg} & ${activeVid}`;
        pill.style.borderColor = '';
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
      statusLabel.textContent = m.status === 'ready' ? 'Ready' : (m.status === 'downloading' ? `Downloading ${m.progress}%` : (m.status === 'error' ? 'Download Failed' : 'Not Installed'));
      statusBox.append(dot, statusLabel);
      meta.append(sizeSpan, statusBox);

      card.append(top, desc, meta);

      // Error banner if download failed
      if (m.status === 'error') {
        const errBanner = document.createElement('div');
        errBanner.className = 'hubErrorBanner';
        errBanner.textContent = `⚠️ ${m.error || 'Download failed. Check connection and retry.'}`;
        card.appendChild(errBanner);
      }

      // Progress bar if downloading
      if (m.status === 'downloading') {
        const progWrapper = document.createElement('div');
        progWrapper.className = 'hubProgressWrapper';
        const progHeader = document.createElement('div');
        progHeader.className = 'hubProgressHeader';
        const dlGB = m.downloaded_bytes ? (m.downloaded_bytes / (1024 ** 3)).toFixed(1) : '0';
        const totalGB = m.total_bytes ? (m.total_bytes / (1024 ** 3)).toFixed(1) : m.size_gb;
        progHeader.innerHTML = `<span>${m.speed || 'Downloading…'} (${dlGB} / ${totalGB} GB)</span><span>${m.progress}%</span>`;
        const track = document.createElement('div');
        track.className = 'hubProgressBarTrack';
        const fill = document.createElement('div');
        fill.className = 'hubProgressBarFill';
        fill.style.width = `${Math.max(2, m.progress)}%`;
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
      } else if (m.status === 'error') {
        const retryBtn = document.createElement('button');
        retryBtn.type = 'button';
        retryBtn.className = 'hubBtn hubBtnPrimary';
        retryBtn.innerHTML = `🔄 Retry Download (${m.size_gb} GB)`;
        retryBtn.onclick = () => triggerDownload(m.id, retryBtn);
        actions.appendChild(retryBtn);
      } else {
        const dlBtn = document.createElement('button');
        dlBtn.type = 'button';
        dlBtn.className = 'hubBtn hubBtnPrimary';
        dlBtn.innerHTML = `📥 Download (${m.size_gb} GB)`;
        dlBtn.onclick = () => triggerDownload(m.id, dlBtn);
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

  async function triggerDownload(modelId, btnElement = null) {
    if (btnElement) {
      btnElement.disabled = true;
      btnElement.innerHTML = `⏳ Starting…`;
    }
    notify(`Connecting to download ${modelId}…`, 'info');
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
      loadModelHubState();
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

  // --- New Project Modal & Creation ---
  function openNewProjectModal() {
    const m = document.getElementById('newProjectModal');
    if (m) m.style.display = 'flex';
  }

  function closeNewProjectModal() {
    const m = document.getElementById('newProjectModal');
    if (m) m.style.display = 'none';
  }

  function switchNewProjTab(tab) {
    const tabF = document.getElementById('tabBtnFreeform');
    const tabA = document.getElementById('tabBtnAudio');
    const panelF = document.getElementById('tabPanelFreeform');
    const panelA = document.getElementById('tabPanelAudio');
    if (tab === 'freeform') {
      tabF?.classList.add('active');
      tabA?.classList.remove('active');
      if (panelF) panelF.style.display = 'block';
      if (panelA) panelA.style.display = 'none';
    } else {
      tabA?.classList.add('active');
      tabF?.classList.remove('active');
      if (panelA) panelA.style.display = 'block';
      if (panelF) panelF.style.display = 'none';
    }
  }

  function onAudioFileSelected() {
    const input = document.getElementById('audioFileInput');
    const label = document.getElementById('selectedAudioFileName');
    const titleInput = document.getElementById('newAudioTitle');
    if (input?.files?.length) {
      const file = input.files[0];
      if (label) {
        label.textContent = `✓ Selected: ${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)`;
        label.style.display = 'block';
      }
      if (titleInput && !titleInput.value) {
        titleInput.value = file.name.replace(/\.[^/.]+$/, '');
      }
    }
  }

  async function submitFreeformProject() {
    const title = document.getElementById('newFreeformTitle')?.value.trim() || 'Airi Freeform Storyboard';
    const duration = parseFloat(document.getElementById('newFreeformDuration')?.value) || 15.0;
    const scene_count = parseInt(document.getElementById('newFreeformScenes')?.value) || 4;
    const concept = document.getElementById('newFreeformConcept')?.value.trim() || '';
    const mood = document.getElementById('newFreeformMood')?.value || '';
    const btn = document.getElementById('createFreeformProjectBtn');

    if (btn) {
      btn.disabled = true;
      btn.textContent = '⏳ Creating Storyboard…';
    }

    try {
      const res = await fetch('/api/video-studio/projects/create', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          title,
          mode: 'freeform',
          duration,
          scene_count,
          concept,
          mood,
          character_id: activePersona?.id || 'airi'
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to create project');
      closeNewProjectModal();
      notify(`✓ Created "${title}" with ${scene_count} scenes!`, 'success');
      await loadProjects();
      const sel = document.getElementById('vsProjectSelect');
      if (sel && data.project?.id) {
        sel.value = data.project.id;
        onProjectChange();
      }
    } catch (e) {
      notify('Project creation failed: ' + e.message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '✨ Generate Freeform Storyboard';
      }
    }
  }

  async function submitAudioProject() {
    const input = document.getElementById('audioFileInput');
    if (!input?.files?.length) {
      notify('Please select an audio file first.', 'warning');
      return;
    }
    const file = input.files[0];
    const title = document.getElementById('newAudioTitle')?.value.trim() || file.name.replace(/\.[^/.]+$/, '');
    const mood = document.getElementById('newAudioMood')?.value || '';
    const btn = document.getElementById('createAudioProjectBtn');

    if (btn) {
      btn.disabled = true;
      btn.textContent = '⏳ Uploading & Analyzing Audio…';
    }

    const fd = new FormData();
    fd.append('audio', file);
    fd.append('title', title);
    fd.append('mode', 'audio');
    fd.append('mood', mood);
    fd.append('character_id', activePersona?.id || 'airi');

    try {
      const res = await fetch('/api/video-studio/projects/create', {
        method: 'POST',
        headers: {
          'X-Media-Token': getToken()
        },
        body: fd
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to create music project');
      closeNewProjectModal();
      notify(`✓ Created music storyboard: "${title}"!`, 'success');
      await loadProjects();
      const sel = document.getElementById('vsProjectSelect');
      if (sel && data.project?.id) {
        sel.value = data.project.id;
        onProjectChange();
      }
    } catch (e) {
      notify('Music project failed: ' + e.message, 'error');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '🎵 Create Music Storyboard';
      }
    }
  }

  // --- Studio Mode Switcher (Storyboard vs Wan 2.1 Motion Mimic) ---
  function switchStudioMode(mode) {
    const modeStoryBtn = document.getElementById('modeStoryboardBtn');
    const modeMotionBtn = document.getElementById('modeMotionBtn');
    const storyWorkspace = document.getElementById('storyboardWorkspace');
    const motionWorkspace = document.getElementById('wanMotionWorkspace');

    if (mode === 'motion') {
      modeMotionBtn?.classList.add('active');
      modeStoryBtn?.classList.remove('active');
      if (storyWorkspace) storyWorkspace.style.display = 'none';
      if (motionWorkspace) motionWorkspace.style.display = 'grid';
      loadDrivingVideos();
      updatePersonaUI();
    } else {
      modeStoryBtn?.classList.add('active');
      modeMotionBtn?.classList.remove('active');
      if (storyWorkspace) storyWorkspace.style.display = 'grid';
      if (motionWorkspace) motionWorkspace.style.display = 'none';
    }
  }

  // --- Wan 2.1 Motion Mimic Controller ---
  let drivingVideosList = [];
  let latestMotionResult = null;
  let activeExtractedFramePath = null;
  let activeSwappedFramePath = null;
  let activeSwappedFrameUrl = null;
  let latestSwapPromptText = "";

  async function loadDrivingVideos() {
    try {
      const res = await fetch('/api/motion/driving-videos');
      if (!res.ok) return;
      const data = await res.json();
      drivingVideosList = data.videos || [];
      populateDrivingVideoSelects();
    } catch (_) {}
  }

  function populateDrivingVideoSelects() {
    const selects = [
      document.getElementById('drivingVideoSelect'),
      document.getElementById('sceneMimicSelect')
    ];
    selects.forEach(sel => {
      if (!sel) return;
      sel.replaceChildren(
        Object.assign(document.createElement('option'), { value: '', textContent: 'Select Driving Reference Video…' }),
        ...drivingVideosList.map(v => Object.assign(document.createElement('option'), {
          value: v.name,
          textContent: `${v.name} (${v.size_mb} MB)`
        }))
      );
      if (drivingVideosList.length && !sel.value) {
        sel.value = drivingVideosList[0].name;
      }
    });
    onDrivingVideoChange();
    onSceneMimicSelectChange();
  }

  function onDrivingVideoChange() {
    const sel = document.getElementById('drivingVideoSelect');
    const vidPlayer = document.getElementById('drivingVideoPreview');
    const meta = document.getElementById('drivingVideoMeta');
    if (!sel || !sel.value) return;
    const v = drivingVideosList.find(x => x.name === sel.value);
    const mediaUrl = `/api/media/${encodeURIComponent(v ? v.path : sel.value)}`;
    if (vidPlayer) vidPlayer.src = mediaUrl;
    if (meta) meta.textContent = v ? `File: ${v.name} • ${v.size_mb} MB` : sel.value;

    // Reset frame thumbnails on new video select
    activeExtractedFramePath = null;
    activeSwappedFramePath = null;
    activeSwappedFrameUrl = null;
    const frameThumb = document.getElementById('motionExtractedFrameThumb');
    const framePlace = document.getElementById('motionExtractedFramePlaceholder');
    const swapThumb = document.getElementById('motionSwappedFrameThumb');
    const swapPlace = document.getElementById('motionSwappedFramePlaceholder');
    const promptBox = document.getElementById('motionPromptBox');

    if (frameThumb) frameThumb.style.display = 'none';
    if (framePlace) {
      framePlace.style.display = 'flex';
      framePlace.textContent = 'Extracting Frame 0…';
    }
    if (swapThumb) swapThumb.style.display = 'none';
    if (swapPlace) {
      swapPlace.style.display = 'flex';
      swapPlace.textContent = 'Ready to swap';
    }
    if (promptBox) promptBox.style.display = 'none';

    // Auto extract frame 0 immediately on selection!
    extractDrivingReferenceFrame();
  }

  async function onDrivingVideoUpload(e) {
    const file = e.target?.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('video', file);
    notify(`Uploading driving reference: ${file.name}…`, 'info');

    try {
      const res = await fetch('/api/motion/upload-driving-video', {
        method: 'POST',
        headers: { 'X-Media-Token': getToken() },
        body: fd
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Upload failed');
      notify(`✓ Reference video uploaded!`, 'success');
      await loadDrivingVideos();
      const sel = document.getElementById('drivingVideoSelect');
      if (sel) {
        sel.value = data.name;
        onDrivingVideoChange();
      }
    } catch (err) {
      notify('Upload failed: ' + err.message, 'error');
    }
  }

  async function extractDrivingReferenceFrame() {
    const sel = document.getElementById('drivingVideoSelect');
    const player = document.getElementById('drivingVideoPreview');
    if (!sel?.value) {
      notify('Select a driving video first.', 'warning');
      return;
    }
    const ts = (player && !isNaN(player.currentTime)) ? Math.max(0, Number(player.currentTime)) : 0.0;
    const extractBtn = document.getElementById('extractRefFrameBtn');
    if (extractBtn) {
      extractBtn.disabled = true;
      extractBtn.innerHTML = '<span>⏳ Extracting Frame…</span>';
    }
    const frameThumb = document.getElementById('motionExtractedFrameThumb');
    const framePlace = document.getElementById('motionExtractedFramePlaceholder');
    if (framePlace) {
      framePlace.style.display = 'flex';
      framePlace.textContent = `Extracting Frame ${ts === 0 ? '0' : ts.toFixed(1) + 's'}…`;
    }
    if (frameThumb) frameThumb.style.display = 'none';

    notify(`Extracting frame at ${ts.toFixed(1)}s…`, 'info');
    try {
      const v = drivingVideosList.find(x => x.name === sel.value);
      const vpath = v ? v.path : sel.value;
      const res = await fetch('/api/motion/extract-frame', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Media-Token': getToken() },
        body: JSON.stringify({ video_path: vpath, timestamp: ts })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Extraction failed');

      activeExtractedFramePath = data.filename;
      if (frameThumb) {
        const fileUrl = data.url || `/api/motion/references/file/${encodeURIComponent(data.filename)}`;
        frameThumb.src = `${fileUrl}?t=${Date.now()}`;
        frameThumb.style.display = 'block';
      }
      if (framePlace) framePlace.style.display = 'none';

      notify(`✓ Frame extracted at ${ts.toFixed(1)}s! Click 'Swap Character' to transplant persona.`, 'success');
    } catch (e) {
      notify('Frame extraction error: ' + e.message, 'error');
      if (framePlace) {
        framePlace.style.display = 'flex';
        framePlace.textContent = 'Frame extraction failed. Click button to retry.';
      }
    } finally {
      if (extractBtn) {
        extractBtn.disabled = false;
        extractBtn.innerHTML = '<span>📸 Extract Frame as Reference</span>';
      }
    }
  }

  async function onCustomSwappedFrameUpload(e) {
    const file = e.target?.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('image', file);
    notify(`Uploading custom swapped photo: ${file.name}…`, 'info');

    try {
      const res = await fetch('/api/motion/upload-swapped-frame', {
        method: 'POST',
        headers: { 'X-Media-Token': getToken() },
        body: fd
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Upload failed');

      activeSwappedFramePath = data.path;
      activeSwappedFrameUrl = data.url;

      const swapThumb = document.getElementById('motionSwappedFrameThumb');
      const swapPlace = document.getElementById('motionSwappedFramePlaceholder');
      if (swapThumb) {
        swapThumb.src = `${data.url}?t=${Date.now()}`;
        swapThumb.style.display = 'block';
      }
      if (swapPlace) swapPlace.style.display = 'none';

      // Update engine select to custom
      const engSel = document.getElementById('motionSwapEngineSelect');
      if (engSel) engSel.value = 'custom';

      notify(`✓ Custom swapped frame loaded from ${file.name}! Ready for Wan 2.1 motion.`, 'success');
    } catch (err) {
      notify('Upload failed: ' + err.message, 'error');
    }
  }

  async function onSwapIdentityClick() {
    const sel = document.getElementById('drivingVideoSelect');
    if (!sel?.value) {
      notify('Select a driving reference video first.', 'warning');
      return;
    }
    const v = drivingVideosList.find(x => x.name === sel.value);
    const drivingVideo = v ? v.path : sel.value;

    const engine = document.getElementById('motionSwapEngineSelect')?.value || 'custom';
    if (engine === 'custom') {
      const swapFileInput = document.getElementById('swappedFrameFileInput');
      if (swapFileInput) swapFileInput.click();
      return;
    }

    const swapBtn = document.getElementById('motionSwapIdentityBtn');
    if (swapBtn) {
      swapBtn.disabled = true;
      swapBtn.innerHTML = '<span>⏳ In-App AI Character Transplanting…</span>';
    }

    try {
      const res = await fetch('/api/motion/swap-identity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Media-Token': getToken() },
        body: JSON.stringify({
          driving_video_path: drivingVideo,
          target_frame_path: activeExtractedFramePath,
          character_id: activePersona?.id || 'airi',
          engine: engine
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Identity swap failed');

      activeSwappedFramePath = data.path;
      activeSwappedFrameUrl = data.url;
      latestSwapPromptText = data.prompt || "";

      // Update extracted frame if it was auto-extracted or returned
      if (data.extracted_frame) {
        activeExtractedFramePath = data.extracted_frame;
        const frameThumb = document.getElementById('motionExtractedFrameThumb');
        const framePlace = document.getElementById('motionExtractedFramePlaceholder');
        if (frameThumb) {
          const frameUrl = data.extracted_frame_url || `/api/motion/references/file/${encodeURIComponent(data.extracted_frame)}`;
          frameThumb.src = `${frameUrl}?t=${Date.now()}`;
          frameThumb.style.display = 'block';
        }
        if (framePlace) framePlace.style.display = 'none';
      }

      // Display swapped start frame
      const swapThumb = document.getElementById('motionSwappedFrameThumb');
      const swapPlace = document.getElementById('motionSwappedFramePlaceholder');
      if (swapThumb) {
        swapThumb.src = `${data.url}?t=${Date.now()}`;
        swapThumb.style.display = 'block';
      }
      if (swapPlace) swapPlace.style.display = 'none';

      // Show prompter box
      const promptBox = document.getElementById('motionPromptBox');
      const promptText = document.getElementById('motionPromptText');
      if (promptBox && promptText) {
        promptBox.style.display = 'block';
        promptText.textContent = latestSwapPromptText;
      }

      const isNeural = data.is_neural || data.engine === 'neural_inswapper';
      const engineBadge = isNeural ? 'Neural AI' : 'Draft Preview';
      notify(`✓ @${data.character?.name || 'Airi'} transplanted onto frame (${engineBadge})! Ready for motion.`, 'success');
    } catch (e) {
      notify('Character swap error: ' + e.message, 'error');
    } finally {
      if (swapBtn) {
        swapBtn.disabled = false;
        swapBtn.innerHTML = '<span>✨ 1-Click: AI Swap Character</span>';
      }
    }
  }

  function onCopyMotionPromptClick() {
    if (!latestSwapPromptText) return;
    navigator.clipboard.writeText(latestSwapPromptText).then(() => {
      notify('📋 Copied identity replacement prompt to clipboard!', 'success');
    }).catch(() => {
      notify('Failed to copy to clipboard', 'warning');
    });
  }

  let activeMotionJobId = null;
  let activeMotionPollTimer = null;

  async function generateWanMotion() {
    const sel = document.getElementById('drivingVideoSelect');
    if (!sel?.value) {
      notify('Select or upload a driving reference video first.', 'warning');
      return;
    }
    const v = drivingVideosList.find(x => x.name === sel.value);
    const drivingVideo = v ? v.path : sel.value;

    // Prioritize the in-app character swapped start frame!
    const sourceImage = activeSwappedFramePath || (activePersona?.portrait_file
      ? `/api/characters/${activePersona.id}/image/${activePersona.portrait_file}`
      : (activePersona?.portrait_path || ''));

    if (!sourceImage) {
      notify('No character reference photo available.', 'warning');
      return;
    }

    const modelId = document.getElementById('motionModelSelect')?.value || 'wan-2.2-animate-14b';
    const audioMode = document.getElementById('motionAudioSource')?.value || 'driving';
    const genBtn = document.getElementById('generateWanMotionBtn');
    const statusLabel = document.getElementById('motionOutputStatus');
    const progContainer = document.getElementById('motionProgressContainer');
    const progBar = document.getElementById('motionProgressBar');
    const progPercent = document.getElementById('motionProgressPercent');
    const progLabel = document.getElementById('motionProgressLabel');
    const progDetails = document.getElementById('motionProgressDetails');
    const progFrames = document.getElementById('motionProgressFrames');
    const cancelBtn = document.getElementById('cancelMotionBtn');

    if (genBtn) {
      genBtn.disabled = true;
      genBtn.textContent = '⏳ Synthesizing Character Motion…';
    }
    if (progContainer) {
      progContainer.style.display = 'block';
      if (progBar) progBar.style.width = '0%';
      if (progPercent) progPercent.textContent = '0%';
      if (progLabel) progLabel.textContent = 'Synthesizing Motion Transfer…';
      if (progDetails) progDetails.textContent = 'Starting neural frame processor…';
      if (progFrames) progFrames.textContent = 'Queued…';
    }
    if (statusLabel) statusLabel.textContent = 'Synthesizing 30fps vertical motion video…';

    if (activeMotionPollTimer) {
      clearInterval(activeMotionPollTimer);
      activeMotionPollTimer = null;
    }

    if (cancelBtn) {
      cancelBtn.disabled = false;
      cancelBtn.textContent = 'Cancel';
      cancelBtn.onclick = async () => {
        if (!activeMotionJobId) return;
        cancelBtn.disabled = true;
        cancelBtn.textContent = 'Cancelling…';
        try {
          await fetch(`/api/motion/jobs/${activeMotionJobId}/cancel`, {
            method: 'POST',
            headers: { 'X-Media-Token': getToken() }
          });
          notify('Cancelling motion generation…', 'info');
        } catch (_) {}
      };
    }

    try {
      const res = await fetch('/api/motion/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Media-Token': getToken() },
        body: JSON.stringify({
          driving_video: drivingVideo,
          source_image: sourceImage,
          model_id: modelId,
          audio_path: audioMode === 'project' && currentProject?.source ? currentProject.source : (audioMode === 'mute' ? '' : drivingVideo),
          async: true
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Motion transfer failed');

      activeMotionJobId = data.job_id;

      // Poll job progress
      const resultData = await new Promise((resolve, reject) => {
        activeMotionPollTimer = setInterval(async () => {
          try {
            const pollRes = await fetch(`/api/motion/jobs/${activeMotionJobId}`, {
              headers: { 'X-Media-Token': getToken() }
            });
            if (!pollRes.ok) throw new Error('Job status check failed');
            const job = await pollRes.json();

            if (progBar) progBar.style.width = `${job.progress}%`;
            if (progPercent) progPercent.textContent = `${job.progress}%`;
            if (progLabel) progLabel.textContent = job.stage || 'Synthesizing motion…';
            if (progDetails) progDetails.textContent = job.stage || '';
            if (progFrames) {
              progFrames.textContent = job.total_frames ? `${job.current_frame} / ${job.total_frames} frames` : 'Processing…';
            }

            if (job.status === 'completed' && job.result) {
              clearInterval(activeMotionPollTimer);
              activeMotionPollTimer = null;
              resolve(job.result);
            } else if (job.status === 'cancelled') {
              clearInterval(activeMotionPollTimer);
              activeMotionPollTimer = null;
              reject(new Error('Motion generation was cancelled by user.'));
            } else if (job.status === 'error') {
              clearInterval(activeMotionPollTimer);
              activeMotionPollTimer = null;
              reject(new Error(job.error || 'Motion transfer failed'));
            }
          } catch (err) {
            clearInterval(activeMotionPollTimer);
            activeMotionPollTimer = null;
            reject(err);
          }
        }, 500);
      });

      latestMotionResult = resultData;
      if (progContainer) progContainer.style.display = 'none';
      document.getElementById('motionEmptyState').style.display = 'none';
      const resContainer = document.getElementById('motionResultContainer');
      resContainer.style.display = 'block';

      const compareDrive = document.getElementById('compareDrivingPlayer');
      const compareResult = document.getElementById('compareResultPlayer');
      if (compareDrive) compareDrive.src = `/api/media/${encodeURIComponent(drivingVideo)}`;
      if (compareResult) compareResult.src = resultData.url;

      // Show action buttons
      const actGroup = document.getElementById('motionActionButtons');
      if (actGroup) actGroup.style.display = 'flex';

      const openFolderBtn = document.getElementById('motionOpenFolderBtn');
      if (openFolderBtn) {
        openFolderBtn.onclick = () => window.open(resultData.url, '_blank');
      }
      const downloadBtn = document.getElementById('motionDownloadBtn');
      if (downloadBtn) {
        downloadBtn.onclick = () => {
          const a = document.createElement('a');
          a.href = resultData.url;
          a.download = resultData.filename;
          a.click();
        };
      }
      const addToStoryBtn = document.getElementById('motionAddToStoryboardBtn');
      if (addToStoryBtn) {
        addToStoryBtn.onclick = () => {
          if (!storyboardScenes.length) {
            notify('No storyboard loaded. Create a project first.', 'warning');
            return;
          }
          storyboardScenes[0].video_path = resultData.path;
          renderStoryboardGrid();
          saveStoryboardToProject();
          notify('✓ Added motion video to Scene #1 of Storyboard!', 'success');
          switchStudioMode('storyboard');
        };
      }

      notify(`✓ Generated motion video (${resultData.duration.toFixed(1)}s)!`, 'success');
      if (statusLabel) statusLabel.textContent = `✓ Ready • Motion Transfer (${resultData.duration.toFixed(1)}s)`;
    } catch (e) {
      if (progContainer) progContainer.style.display = 'none';
      notify('Motion error: ' + e.message, 'error');
      if (statusLabel) statusLabel.textContent = 'Motion render failed: ' + e.message;
    } finally {
      if (activeMotionPollTimer) {
        clearInterval(activeMotionPollTimer);
        activeMotionPollTimer = null;
      }
      if (genBtn) {
        genBtn.disabled = false;
        genBtn.textContent = '✨ Generate Character Motion';
      }
    }
  }

  // --- Per-Scene Mimic Reference Modal ---
  let currentMimicSceneNum = null;

  function openSceneMimicModal(sceneNum) {
    currentMimicSceneNum = sceneNum;
    const titleEl = document.getElementById('sceneMimicTitle');
    if (titleEl) titleEl.textContent = `Mimic Dance / Action for Scene #${sceneNum}`;
    const m = document.getElementById('sceneMimicModal');
    if (m) m.style.display = 'flex';
    loadDrivingVideos();
  }

  function closeSceneMimicModal() {
    const m = document.getElementById('sceneMimicModal');
    if (m) m.style.display = 'none';
    currentMimicSceneNum = null;
  }

  function onSceneMimicSelectChange() {
    const sel = document.getElementById('sceneMimicSelect');
    const player = document.getElementById('sceneMimicPreview');
    if (!sel || !sel.value) return;
    const v = drivingVideosList.find(x => x.name === sel.value);
    const mediaUrl = `/api/media/${encodeURIComponent(v ? v.path : sel.value)}`;
    if (player) player.src = mediaUrl;
  }

  async function confirmSceneMimic() {
    if (!currentMimicSceneNum) return;
    const scene = storyboardScenes.find(s => s.number === currentMimicSceneNum);
    if (!scene) return;
    const sel = document.getElementById('sceneMimicSelect');
    if (!sel?.value) {
      notify('Select a reference video first.', 'warning');
      return;
    }
    const v = drivingVideosList.find(x => x.name === sel.value);
    const drivingVideo = v ? v.path : sel.value;
    const sourceImage = scene.image_path
      ? scene.image_path
      : (activePersona?.portrait_file
        ? `/api/characters/${activePersona.id}/image/${activePersona.portrait_file}`
        : '');

    const confirmBtn = document.getElementById('confirmSceneMimicBtn');
    if (confirmBtn) {
      confirmBtn.disabled = true;
      confirmBtn.textContent = '⏳ Transferring Motion…';
    }

    try {
      const res = await fetch('/api/motion/render', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Media-Token': getToken() },
        body: JSON.stringify({
          driving_video: drivingVideo,
          source_image: sourceImage,
          model_id: 'wan-2.2-animate-14b',
          async: true
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Motion transfer failed');

      // Poll scene motion progress
      const resultData = await new Promise((resolve, reject) => {
        const timer = setInterval(async () => {
          try {
            const pRes = await fetch(`/api/motion/jobs/${data.job_id}`, {
              headers: { 'X-Media-Token': getToken() }
            });
            if (!pRes.ok) throw new Error('Job status check failed');
            const job = await pRes.json();
            if (confirmBtn) confirmBtn.textContent = `⏳ Animating ${job.progress}%…`;

            if (job.status === 'completed' && job.result) {
              clearInterval(timer);
              resolve(job.result);
            } else if (job.status === 'cancelled') {
              clearInterval(timer);
              reject(new Error('Cancelled'));
            } else if (job.status === 'error') {
              clearInterval(timer);
              reject(new Error(job.error || 'Failed'));
            }
          } catch (e) {
            clearInterval(timer);
            reject(e);
          }
        }, 500);
      });

      scene.video_path = resultData.path;
      renderStoryboardGrid();
      saveStoryboardToProject();
      closeSceneMimicModal();
      notify(`✓ Scene #${scene.number} animated with motion transfer!`, 'success');
    } catch (e) {
      notify('Scene motion failed: ' + e.message, 'error');
    } finally {
      if (confirmBtn) {
        confirmBtn.disabled = false;
        confirmBtn.textContent = '✨ Animate Scene with Wan 2.1';
      }
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
