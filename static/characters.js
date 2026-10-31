/* AI Influencer Studio - Universal Character Library & Modal */
(function() {
  'use strict';

  function getToken() {
    const meta = document.querySelector('meta[name="media-token"]');
    return meta ? meta.content : '';
  }

  function notify(msg, type = 'info') {
    const existing = document.getElementById('charStudioToast');
    if (existing) existing.remove();

    const t = document.createElement('div');
    t.id = 'charStudioToast';
    t.className = 'snapperToast';
    t.style.maxWidth = '380px';
    t.style.display = 'flex';
    t.style.alignItems = 'center';
    t.style.gap = '10px';

    const icon = document.createElement('span');
    icon.textContent = type === 'error' ? '⚠️' : (type === 'success' ? '✓' : (type === 'warning' ? '⚡' : 'ℹ️'));

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

  let characterList = [];
  let selectedCid = 'airi';
  let lockedActiveCid = 'airi';

  function createCharacterModalHTML() {
    if (document.getElementById('characterModal')) return;

    const modal = document.createElement('div');
    modal.id = 'characterModal';
    modal.className = 'studioModal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-label', 'AI Character Library');
    modal.innerHTML = `
      <div class="studioModalBackdrop"></div>
      <div class="studioModalDialog characterDialog">
        <div class="studioModalHeader">
          <div class="modalTitleGroup">
            <span class="modalIcon">👤</span>
            <div>
              <h3>AI Influencer & Character Library</h3>
              <p class="modalSubtitle">Manage consistent creator personas, portrait references, and Google Flow Nano Banana prompts</p>
            </div>
          </div>
          <button class="modalCloseBtn" id="closeCharModalBtn" aria-label="Close">✕</button>
        </div>

        <div class="characterModalBody">
          <!-- Left: Character List Sidebar -->
          <div class="charSidebar">
            <div class="charSidebarHeader">
              <span class="sidebarTitle">Personas</span>
              <button id="newCharBtn" class="primaryMiniBtn" type="button">+ New</button>
            </div>
            <div id="charItemsList" class="charItemsList"></div>
          </div>

          <!-- Right: Character Details Form -->
          <div class="charDetails" id="charDetailsForm">
            <div class="charFormRow">
              <div class="formGroup" style="flex:1;">
                <label for="charNameInput">Character Name</label>
                <input type="text" id="charNameInput" placeholder="e.g. Airi" maxlength="50" required>
              </div>
              <div class="formGroup" style="flex:1;">
                <label for="charTagInput">Flow Trigger Tag</label>
                <input type="text" id="charTagInput" placeholder="e.g. @Airi" maxlength="50">
              </div>
              <div class="formGroup" style="width:110px;">
                <label for="charAspectSelect">Aspect Ratio</label>
                <select id="charAspectSelect">
                  <option value="9:16">9:16 (Vertical)</option>
                  <option value="16:9">16:9 (Landscape)</option>
                  <option value="1:1">1:1 (Square)</option>
                </select>
              </div>
            </div>

            <!-- Image References (Portrait & Turnaround Triptych) -->
            <div class="charImagesSection">
              <div class="charImageCard">
                <div class="charImageHeader">
                  <span>👤 Face Portrait</span>
                  <label class="uploadLink">
                    <span>Change</span>
                    <input type="file" id="uploadPortraitFile" accept="image/png,image/jpeg,image/webp" style="display:none;">
                  </label>
                </div>
                <div class="charImagePreview" id="portraitPreview">
                  <span class="imagePlaceholder">No portrait uploaded</span>
                </div>
                <span class="imageCaption">Used for face consistency & LivePortrait</span>
              </div>

              <div class="charImageCard">
                <div class="charImageHeader">
                  <span>🖼️ Turnaround Triptych (Front / Side / Back)</span>
                  <label class="uploadLink">
                    <span>Change</span>
                    <input type="file" id="uploadTriptychFile" accept="image/png,image/jpeg,image/webp" style="display:none;">
                  </label>
                </div>
                <div class="charImagePreview" id="triptychPreview">
                  <span class="imagePlaceholder">No turnaround sheet uploaded</span>
                </div>
                <span class="imageCaption">Used by Google Flow Nano Banana for full-body consistency</span>
              </div>
            </div>

            <div class="formGroup" style="margin-top:10px;">
              <label for="charTriggerInput">Nano Banana Trigger Prompt</label>
              <textarea id="charTriggerInput" rows="2" placeholder="e.g. Airi, 22yo Japanese virtual singer, dark purple bob haircut, amber eyes, oversized cropped hoodie…"></textarea>
            </div>

            <div class="formGroup">
              <label for="charNegativeInput">Negative Prompt</label>
              <input type="text" id="charNegativeInput" placeholder="e.g. blurry, low quality, distorted anatomy, extra limbs, altered face">
            </div>

            <div class="formGroup">
              <label for="charBioInput">Persona Bio & Aesthetic Notes</label>
              <textarea id="charBioInput" rows="2" placeholder="e.g. Virtual R&B singer, streetwear aesthetic, late night studio mood…"></textarea>
            </div>

            <div class="charActionsRow">
              <div class="leftActions">
                <button id="lockActivePersonaBtn" class="primaryMiniBtn" style="background:#7c3aed;padding:6px 12px;" type="button">🔒 Lock as Active Persona</button>
                <button id="copyFlowPromptBtn" class="secondaryBtn" type="button">📋 Copy Flow Tag</button>
                <button id="deleteCharBtn" class="dangerBtn" type="button">🗑️ Delete</button>
              </div>
              <button id="saveCharBtn" class="primaryBtn" type="button">💾 Save Character</button>
            </div>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    // Event listeners
    document.getElementById('closeCharModalBtn').onclick = closeCharacterModal;
    modal.querySelector('.studioModalBackdrop').onclick = closeCharacterModal;
    document.getElementById('newCharBtn').onclick = createNewCharacter;
    document.getElementById('saveCharBtn').onclick = saveActiveCharacter;
    document.getElementById('lockActivePersonaBtn').onclick = lockCurrentCharacterAsActive;
    document.getElementById('deleteCharBtn').onclick = deleteActiveCharacter;
    document.getElementById('copyFlowPromptBtn').onclick = copyFlowPrompt;

    document.getElementById('uploadPortraitFile').onchange = (e) => handleImageUpload(e, 'portrait');
    document.getElementById('uploadTriptychFile').onchange = (e) => handleImageUpload(e, 'triptych');
  }

  async function loadCharacters() {
    try {
      const [resChars, resActive] = await Promise.all([
        fetch('/api/characters'),
        fetch('/api/characters/active').catch(() => null)
      ]);
      if (!resChars.ok) return;
      const data = await resChars.json();
      characterList = data.characters || [];

      if (resActive && resActive.ok) {
        const actData = await resActive.json();
        if (actData?.active?.id) lockedActiveCid = actData.active.id;
      }

      renderCharacterSidebar();
      if (characterList.length) {
        selectCharacter(characterList.find(c => c.id === lockedActiveCid)?.id || characterList[0].id);
      }
    } catch (_) {}
  }

  function renderCharacterSidebar() {
    const listEl = document.getElementById('charItemsList');
    if (!listEl) return;
    listEl.replaceChildren();

    characterList.forEach(c => {
      const item = document.createElement('div');
      item.className = 'charSidebarItem' + (c.id === selectedCid ? ' active' : '');
      item.onclick = () => selectCharacter(c.id);

      const avatar = document.createElement('div');
      avatar.className = 'charAvatar';
      if (c.portrait_file) {
        avatar.style.backgroundImage = `url('/api/characters/${c.id}/image/${c.portrait_file}')`;
        avatar.textContent = '';
      } else {
        avatar.textContent = (c.name || 'C').charAt(0).toUpperCase();
      }

      const info = document.createElement('div');
      info.className = 'charMeta';
      const strong = document.createElement('strong');
      strong.textContent = c.name;
      const small = document.createElement('small');
      small.textContent = c.tag;
      info.replaceChildren(strong, small);

      item.appendChild(avatar);
      item.appendChild(info);

      if (c.id === lockedActiveCid) {
        const lockBadge = document.createElement('span');
        lockBadge.className = 'charLockBadge';
        lockBadge.style.cssText = 'background:rgba(124,58,237,0.25);color:#c084fc;border:1px solid rgba(124,58,237,0.4);font-size:10px;padding:2px 6px;border-radius:12px;margin-left:auto;font-weight:600;';
        lockBadge.textContent = '🔒 Active';
        item.appendChild(lockBadge);
      }

      listEl.appendChild(item);
    });
  }

  function selectCharacter(cid) {
    selectedCid = cid;
    renderCharacterSidebar();
    const c = characterList.find(x => x.id === cid);
    if (!c) return;

    document.getElementById('charNameInput').value = c.name || '';
    document.getElementById('charTagInput').value = c.tag || '';
    document.getElementById('charAspectSelect').value = c.aspect_ratio || '9:16';
    document.getElementById('charTriggerInput').value = c.trigger_prompt || '';
    document.getElementById('charNegativeInput').value = c.negative_prompt || '';
    document.getElementById('charBioInput').value = c.bio || '';

    const lockBtn = document.getElementById('lockActivePersonaBtn');
    if (lockBtn) {
      if (cid === lockedActiveCid) {
        lockBtn.textContent = '✓ Locked as Active Persona';
        lockBtn.style.background = '#059669';
      } else {
        lockBtn.textContent = '🔒 Lock as Active Persona';
        lockBtn.style.background = '#7c3aed';
      }
    }

    // Update image previews safely
    const pPrev = document.getElementById('portraitPreview');
    if (c.portrait_file) {
      const img = document.createElement('img');
      img.src = `/api/characters/${encodeURIComponent(c.id)}/image/${encodeURIComponent(c.portrait_file)}`;
      img.alt = 'Portrait';
      pPrev.replaceChildren(img);
    } else {
      const span = document.createElement('span');
      span.className = 'imagePlaceholder';
      span.textContent = 'No portrait uploaded';
      pPrev.replaceChildren(span);
    }

    const tPrev = document.getElementById('triptychPreview');
    if (c.triptych_file) {
      const img = document.createElement('img');
      img.src = `/api/characters/${encodeURIComponent(c.id)}/image/${encodeURIComponent(c.triptych_file)}`;
      img.alt = 'Triptych';
      tPrev.replaceChildren(img);
    } else {
      const span = document.createElement('span');
      span.className = 'imagePlaceholder';
      span.textContent = 'No turnaround sheet uploaded';
      tPrev.replaceChildren(span);
    }
  }

  function createNewCharacter() {
    const newId = 'char_' + Date.now().toString(36);
    const newChar = {
      id: newId,
      name: 'New Character',
      tag: '@NewCharacter',
      aspect_ratio: '9:16',
      trigger_prompt: '',
      negative_prompt: 'blurry, low quality, distorted anatomy',
      bio: '',
      portrait_file: '',
      triptych_file: ''
    };
    characterList.push(newChar);
    selectCharacter(newId);
  }

  async function lockCurrentCharacterAsActive() {
    try {
      const res = await fetch('/api/characters/active', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({ id: selectedCid })
      });
      if (!res.ok) throw new Error('Could not lock active character');
      const data = await res.json();
      lockedActiveCid = data?.active?.id || selectedCid;
      renderCharacterSidebar();
      selectCharacter(selectedCid);
      const c = characterList.find(x => x.id === selectedCid);
      notify(`✓ ${c?.name || selectedCid} locked as active persona!`, 'success');
      window.dispatchEvent(new CustomEvent('active-persona-changed', { detail: data?.active }));
    } catch (e) {
      notify('Could not lock persona: ' + e.message, 'error');
    }
  }

  async function saveActiveCharacter() {
    const name = document.getElementById('charNameInput').value.trim();
    if (!name) {
      notify('Please enter a character name.', 'warning');
      return;
    }
    let tag = document.getElementById('charTagInput').value.trim();
    if (tag && !tag.startsWith('@')) tag = '@' + tag;

    const payload = {
      id: selectedCid,
      name: name,
      tag: tag || ('@' + name.replace(/\s+/g, '')),
      aspect_ratio: document.getElementById('charAspectSelect').value,
      trigger_prompt: document.getElementById('charTriggerInput').value.trim(),
      negative_prompt: document.getElementById('charNegativeInput').value.trim(),
      bio: document.getElementById('charBioInput').value.trim()
    };

    try {
      const res = await fetch('/api/characters', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error('Save failed');
      const saved = await res.json();
      const idx = characterList.findIndex(c => c.id === saved.id);
      if (idx >= 0) characterList[idx] = saved;
      else characterList.push(saved);
      selectedCid = saved.id;
      renderCharacterSidebar();

      const btn = document.getElementById('saveCharBtn');
      const orig = btn.textContent;
      btn.textContent = '✓ Saved!';
      notify('✓ Character profile saved!', 'success');
      setTimeout(() => { btn.textContent = orig; }, 1500);
    } catch (e) {
      notify('Could not save character: ' + e.message, 'error');
    }
  }

  async function deleteActiveCharacter() {
    if (characterList.length <= 1) {
      notify('At least one character profile must remain.', 'warning');
      return;
    }
    if (!confirm(`Delete character ${document.getElementById('charNameInput').value}?`)) return;

    try {
      await fetch(`/api/characters/${selectedCid}`, {
        method: 'DELETE',
        headers: { 'X-Media-Token': getToken() }
      });
      characterList = characterList.filter(c => c.id !== selectedCid);
      selectedCid = characterList[0].id;
      renderCharacterSidebar();
      selectCharacter(selectedCid);
      notify('Character removed.', 'info');
    } catch (e) {
      notify('Could not delete character: ' + e.message, 'error');
    }
  }

  async function handleImageUpload(e, imgType) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('type', imgType);
    formData.append('file', file);

    try {
      const res = await fetch(`/api/characters/${selectedCid}/upload`, {
        method: 'POST',
        headers: { 'X-Media-Token': getToken() },
        body: formData
      });
      if (!res.ok) throw new Error('Upload failed');
      const data = await res.json();
      const c = characterList.find(x => x.id === selectedCid);
      if (c) {
        if (imgType === 'portrait') c.portrait_file = data.filename;
        else c.triptych_file = data.filename;
      }
      selectCharacter(selectedCid);
      notify(`✓ Reference ${imgType} uploaded!`, 'success');
    } catch (err) {
      notify('Image upload failed: ' + err.message, 'error');
    }
  }

  function copyFlowPrompt() {
    const c = characterList.find(x => x.id === selectedCid);
    if (!c) return;
    const promptText = `Add ${c.tag}, ${c.trigger_prompt || c.name}, cinematic volumetric lighting, 8k --ar ${c.aspect_ratio || '9:16'}` +
      (c.negative_prompt ? ` --no ${c.negative_prompt}` : '');
    navigator.clipboard.writeText(promptText);

    const btn = document.getElementById('copyFlowPromptBtn');
    const orig = btn.textContent;
    btn.textContent = '✓ Copied for Flow!';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  }

  function openCharacterModal() {
    createCharacterModalHTML();
    loadCharacters();
    const modal = document.getElementById('characterModal');
    if (modal) modal.classList.add('open');
  }

  function closeCharacterModal() {
    const modal = document.getElementById('characterModal');
    if (modal) modal.classList.remove('open');
  }

  // Expose global interface
  window.characterStudio = {
    open: openCharacterModal,
    close: closeCharacterModal,
    list: () => characterList,
    current: () => characterList.find(x => x.id === selectedCid) || characterList[0]
  };

  // Auto-init modal on DOM load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createCharacterModalHTML);
  } else {
    createCharacterModalHTML();
  }
})();
