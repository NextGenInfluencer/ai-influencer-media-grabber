/* AI Influencer Studio - AI Storyboard & Google Flow Scene Generator */
(function() {
  'use strict';

  function getToken() {
    const meta = document.querySelector('meta[name="media-token"]');
    return meta ? meta.content : '';
  }

  function createStoryboardModalHTML() {
    if (document.getElementById('storyboardModal')) return;

    const modal = document.createElement('div');
    modal.id = 'storyboardModal';
    modal.className = 'studioModal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-label', 'AI Storyboard & Flow Prompts');
    modal.innerHTML = `
      <div class="studioModalBackdrop"></div>
      <div class="studioModalDialog storyboardDialog">
        <div class="studioModalHeader">
          <div class="modalTitleGroup">
            <span class="modalIcon">🎬</span>
            <div>
              <h3>AI Song Storyboard & Google Flow Prompts</h3>
              <p class="modalSubtitle">Automated scene breakdown with synchronized prompts formatted for Google Flow Nano Banana and Kling</p>
            </div>
          </div>
          <button class="modalCloseBtn" id="closeStoryboardModalBtn" aria-label="Close">✕</button>
        </div>

        <div class="storyboardControlsRow">
          <div class="row" style="align-items:center;gap:10px;">
            <label for="storyboardCharSelect" style="font-size:12px;color:#cbd5e1;font-weight:600;">Influencer Persona:</label>
            <select id="storyboardCharSelect" style="min-width:180px;"></select>
            <button id="refreshStoryboardBtn" class="primaryMiniBtn" type="button">⚡ Refresh Scenes</button>
          </div>
          <button id="copyAllPromptsBtn" class="secondaryMiniBtn" type="button">📋 Copy All Scenes</button>
        </div>

        <div class="storyboardBody" id="storyboardScenesContainer">
          <div class="storyboardEmptyState">
            <span>🎵</span>
            <p>Open a caption project with lyrics to generate an automated music video storyboard!</p>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    document.getElementById('closeStoryboardModalBtn').onclick = closeStoryboardModal;
    modal.querySelector('.studioModalBackdrop').onclick = closeStoryboardModal;
    document.getElementById('refreshStoryboardBtn').onclick = generateScenes;
    document.getElementById('copyAllPromptsBtn').onclick = copyAllScenesText;
  }

  function openStoryboardModal() {
    createStoryboardModalHTML();
    populateStoryboardCharacters();
    generateScenes();
    const modal = document.getElementById('storyboardModal');
    if (modal) modal.classList.add('open');
  }

  function closeStoryboardModal() {
    const modal = document.getElementById('storyboardModal');
    if (modal) modal.classList.remove('open');
  }

  async function populateStoryboardCharacters() {
    const sel = document.getElementById('storyboardCharSelect');
    if (!sel) return;
    try {
      const res = await fetch('/api/characters');
      if (!res.ok) return;
      const data = await res.json();
      const chars = data.characters || [];
      sel.replaceChildren(
        ...chars.map(c => {
          const opt = document.createElement('option');
          opt.value = c.id;
          opt.textContent = `${c.name} (${c.tag})`;
          opt.dataset.tag = c.tag;
          opt.dataset.trigger = c.trigger_prompt;
          opt.dataset.negative = c.negative_prompt;
          opt.dataset.aspect = c.aspect_ratio;
          return opt;
        })
      );
    } catch (_) {}
  }

  function inferLyricMood(lyricsText, sceneIndex) {
    const text = (lyricsText || '').toLowerCase();
    if (/rain|storm|tear|cry|cold|sad|alone/.test(text)) {
      return 'rain-streaked studio glass window, soft melancholy lighting, city reflections, emotional close-up';
    }
    if (/night|dark|moon|midnight|stars|shadow/.test(text)) {
      return 'late night recording booth, deep neon purple and indigo shadows, warm microphone rim light';
    }
    if (/fire|burn|flame|hot|heat|blaze/.test(text)) {
      return 'warm amber tungsten backlights, dramatic golden glow, expressive vocal performance';
    }
    if (/love|heart|hold|kiss|feel|touch/.test(text)) {
      return 'intimate studio close-up portrait, shallow depth of field, gentle golden hour warmth';
    }
    if (/dance|beat|club|party|jump|drop|bass/.test(text)) {
      return 'dynamic stage lighting, pulsing magenta and cyan beams, energetic silhouette performance';
    }
    if (/dream|fly|sky|light|free|high/.test(text)) {
      return 'ethereal atmospheric haze, subtle lens flare, soft cinematic glow, uplifting composition';
    }
    // Cycling creative studio settings
    const presets = [
      'dim studio lighting, cinematic rim lights, atmospheric haze, focused expression',
      'late night recording booth, warm vintage microphone, deep neon purple shadows',
      'studio acoustic wood panels, soft diffused key light, natural handheld 35mm feel'
    ];
    return presets[(sceneIndex - 1) % presets.length];
  }

  function generateScenes() {
    const container = document.getElementById('storyboardScenesContainer');
    if (!container) return;

    let project = null;
    if (window.currentProjectData) {
      project = window.currentProjectData();
    }

    if (!project || !project.cues || !project.cues.length) {
      const emptyDiv = document.createElement('div');
      emptyDiv.className = 'storyboardEmptyState';
      const icon = document.createElement('span');
      icon.textContent = '🎵';
      const msg = document.createElement('p');
      msg.textContent = 'No active project lyrics found. Load or transcribe a song in Captions Studio first.';
      emptyDiv.append(icon, msg);
      container.replaceChildren(emptyDiv);
      return;
    }

    const sel = document.getElementById('storyboardCharSelect');
    const opt = sel?.options[sel.selectedIndex];
    const charTag = opt?.dataset?.tag || '@Airi';
    const charTrigger = opt?.dataset?.trigger || 'Airi, 22yo Japanese virtual singer';
    const charNeg = opt?.dataset?.negative || 'blurry, distorted hands, altered face';
    const aspect = opt?.dataset?.aspect || '9:16';

    // Group cues into 4-cue scenes (~10-15s per scene)
    const cues = project.cues;
    const sceneSize = 4;
    const scenes = [];

    for (let i = 0; i < cues.length; i += sceneSize) {
      const chunk = cues.slice(i, i + sceneSize);
      const startTime = chunk[0].start;
      const endTime = chunk[chunk.length - 1].end;
      const originalLyrics = chunk.map(c => c.text).join(' / ');
      const lang = project?.style?.translation_language || 'en';
      const transLyrics = chunk.map(c => c.translations?.[lang]?.text || '').filter(Boolean).join(' / ');

      const sceneIndex = Math.floor(i / sceneSize) + 1;
      const mood = inferLyricMood(originalLyrics, sceneIndex);
      const flowPrompt = `Add ${charTag}, ${charTrigger}, ${mood}, 35mm lens, photorealistic 8k, aspect ratio ${aspect}. Avoiding: ${charNeg}.`;

      scenes.push({
        number: sceneIndex,
        startTime: startTime,
        endTime: endTime,
        originalLyrics: originalLyrics,
        transLyrics: transLyrics,
        mood: mood,
        flowPrompt: flowPrompt
      });
    }

    container.replaceChildren();
    scenes.forEach(s => {
      const card = document.createElement('div');
      card.className = 'sceneCard';

      // Header
      const header = document.createElement('div');
      header.className = 'sceneHeader';
      const tagSpan = document.createElement('span');
      tagSpan.className = 'sceneTag';
      tagSpan.textContent = `Scene #${s.number}`;
      const timeSpan = document.createElement('span');
      timeSpan.className = 'sceneTime';
      timeSpan.textContent = `${fmt(s.startTime)} → ${fmt(s.endTime)}`;
      header.append(tagSpan, timeSpan);

      // Lyrics
      const lyricsDiv = document.createElement('div');
      lyricsDiv.className = 'sceneLyrics';
      const origDiv = document.createElement('div');
      origDiv.className = 'sceneOrig';
      origDiv.textContent = `"${s.originalLyrics}"`;
      lyricsDiv.appendChild(origDiv);
      if (s.transLyrics) {
        const transDiv = document.createElement('div');
        transDiv.className = 'sceneTrans';
        transDiv.textContent = `🌐 ${s.transLyrics}`;
        lyricsDiv.appendChild(transDiv);
      }

      // Prompt Box
      const promptBox = document.createElement('div');
      promptBox.className = 'scenePromptBox';
      const promptLabel = document.createElement('label');
      promptLabel.textContent = `Google Flow Prompt (${charTag}):`;
      const promptText = document.createElement('div');
      promptText.className = 'promptText';
      promptText.textContent = s.flowPrompt;
      promptBox.append(promptLabel, promptText);

      // Actions
      const actionsDiv = document.createElement('div');
      actionsDiv.className = 'sceneActions';
      const copyBtn = document.createElement('button');
      copyBtn.className = 'miniActionBtn copySceneBtn';
      copyBtn.type = 'button';
      copyBtn.textContent = '📋 Copy Flow Prompt';
      copyBtn.onclick = () => {
        navigator.clipboard.writeText(s.flowPrompt);
        copyBtn.textContent = '✓ Copied for Flow!';
        setTimeout(() => { copyBtn.textContent = '📋 Copy Flow Prompt'; }, 1500);
      };

      const snapBtn = document.createElement('button');
      snapBtn.className = 'miniActionBtn snapRefBtn';
      snapBtn.type = 'button';
      snapBtn.textContent = `📸 Grab Ref at ${fmt(s.startTime)}`;
      snapBtn.onclick = () => {
        const vid = document.getElementById('video');
        if (vid) {
          vid.currentTime = s.startTime;
          if (window.motionStudio) window.motionStudio.snapFrame();
        }
      };
      actionsDiv.append(copyBtn, snapBtn);

      card.append(header, lyricsDiv, promptBox, actionsDiv);
      container.appendChild(card);
    });
  }

  function fmt(s) {
    if (!Number.isFinite(s)) return '0:00.00';
    const m = Math.floor(s / 60);
    const sec = (s % 60).toFixed(2).padStart(5, '0');
    return `${m}:${sec}`;
  }

  function copyAllScenesText() {
    const cards = document.querySelectorAll('.sceneCard');
    if (!cards.length) return;
    let full = '';
    cards.forEach(c => {
      const tag = c.querySelector('.sceneTag')?.textContent;
      const time = c.querySelector('.sceneTime')?.textContent;
      const prompt = c.querySelector('.promptText')?.textContent;
      full += `${tag} (${time})\n${prompt}\n\n`;
    });
    navigator.clipboard.writeText(full);
    const btn = document.getElementById('copyAllPromptsBtn');
    btn.textContent = '✓ All Scenes Copied!';
    setTimeout(() => { btn.textContent = '📋 Copy All Scenes'; }, 1500);
  }

  window.storyboardStudio = {
    open: openStoryboardModal,
    close: closeStoryboardModal,
    refresh: generateScenes
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createStoryboardModalHTML);
  } else {
    createStoryboardModalHTML();
  }
})();
