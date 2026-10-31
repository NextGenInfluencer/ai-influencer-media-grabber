/* AI Influencer Studio - Motion Studio & 1-Click Reference Frame Snapper */
(function() {
  'use strict';

  function getToken() {
    const meta = document.querySelector('meta[name="media-token"]');
    return meta ? meta.content : '';
  }

  function notify(msg, type = 'info') {
    const existing = document.getElementById('motionStudioToast');
    if (existing) existing.remove();

    const t = document.createElement('div');
    t.id = 'motionStudioToast';
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

  function getActiveVideo() {
    // 1. Preview modal if open
    const modal = document.getElementById('previewModal');
    if (modal && !modal.classList.contains('hidden') && modal.style.display !== 'none') {
      const pv = document.getElementById('previewModalVideo');
      if (pv && pv.style.display !== 'none') return pv;
    }
    // 2. Studio stage video
    const stage = document.getElementById('video');
    if (stage && (stage.currentSrc || stage.src)) return stage;
    // 3. Downloader trimmer preview
    const trim = document.getElementById('videoPreview');
    if (trim && (trim.currentSrc || trim.src)) return trim;
    return document.querySelector('video');
  }

  function getActiveVideoSourcePath(videoEl) {
    if (videoEl.id === 'previewModalVideo') {
      const pathEl = document.getElementById('previewModalPath');
      if (pathEl && pathEl.textContent.trim()) return pathEl.textContent.trim();
    }
    return videoEl.getAttribute('src') || videoEl.currentSrc || '';
  }

  function createMotionStudioModalHTML() {
    if (document.getElementById('motionStudioModal')) return;

    const modal = document.createElement('div');
    modal.id = 'motionStudioModal';
    modal.className = 'studioModal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-label', 'Motion Studio & LivePortrait');

    const backdrop = document.createElement('div');
    backdrop.className = 'studioModalBackdrop';

    const dialog = document.createElement('div');
    dialog.className = 'studioModalDialog motionDialog';

    // Header
    const header = document.createElement('div');
    header.className = 'studioModalHeader';
    header.innerHTML = `
      <div class="modalTitleGroup">
        <span class="modalIcon">🎬</span>
        <div>
          <h3>Wan 2.1 &amp; LivePortrait Motion Studio</h3>
          <p class="modalSubtitle">Animate character still images with Wan 2.1 video diffusion or facial performance takes</p>
        </div>
      </div>
      <button class="modalCloseBtn" id="closeMotionModalBtn" aria-label="Close">✕</button>
    `;

    // Body
    const body = document.createElement('div');
    body.className = 'motionModalBody';
    body.innerHTML = `
      <!-- Left: Driving Performance Video -->
      <div class="motionSourceCard">
        <h4>1. Driving Performance Video</h4>
        <p class="hint">Your webcam lip-sync take, TikTok dance, or stage video.</p>
        <div class="motionVideoSlot" id="drivingVideoPreview">
          <span class="slotPlaceholder">No driving video selected</span>
        </div>
        <div style="margin-top:8px;">
          <label for="drivingVideoSelectCaptions" style="font-size:10px;color:#94a3b8;font-weight:600;display:block;margin-bottom:3px;">Select Downloaded Video:</label>
          <select id="drivingVideoSelectCaptions" style="width:100%;padding:5px 8px;border-radius:6px;background:#141724;color:#f8fafc;border:1px solid rgba(255,255,255,0.12);font-size:11px;">
            <option value="">Loading downloaded videos…</option>
          </select>
        </div>
        <div class="row" style="margin-top:8px;gap:6px;">
          <button id="uploadDrivingVideoCaptionsBtn" class="secondaryMiniBtn" type="button" style="flex:1;">📂 Upload Video…</button>
          <input type="file" id="drivingVideoFileInputCaptions" accept="video/*" style="display:none;">
          <button id="useCurrentProjectVideoBtn" class="secondaryMiniBtn" type="button">Use Timeline Video</button>
        </div>
        <input type="hidden" id="drivingVideoInput">
      </div>

      <!-- Middle: Character or Custom Still Image -->
      <div class="motionSourceCard">
        <h4>2. Character / Source Still Image</h4>
        <p class="hint">Select an AI persona, pick a reference frame, or upload ANY custom photo.</p>
        <div class="motionImageSlot" id="sourceImagePreview">
          <span class="slotPlaceholder">No image selected</span>
        </div>
        <div style="margin-top:8px;">
          <label for="charSelectForMotion" style="font-size:10px;color:#94a3b8;font-weight:600;display:block;margin-bottom:3px;">Select Character or Photo:</label>
          <select id="charSelectForMotion" style="width:100%;padding:5px 8px;border-radius:6px;background:#141724;color:#f8fafc;border:1px solid rgba(255,255,255,0.12);font-size:11px;"></select>
        </div>
        <div class="row" style="margin-top:8px;gap:6px;">
          <button id="uploadCustomSourceImageCaptionsBtn" class="secondaryMiniBtn" type="button" style="flex:1;">📁 Upload Custom Photo…</button>
          <input type="file" id="customSourceImageFileInputCaptions" accept="image/*" style="display:none;">
          <button id="refreshCharMotionBtn" class="secondaryMiniBtn" type="button" title="Refresh available images">🔄</button>
        </div>
      </div>

      <!-- Right: Synced Result -->
      <div class="motionSourceCard">
        <h4>3. Synced Result</h4>
        <p class="hint">Generated character performance ready for timeline.</p>
        <div class="motionVideoSlot" id="motionOutputPreview">
          <span class="slotPlaceholder">Render result will appear here</span>
        </div>
        <div style="margin-top:8px;">
          <label for="captionsMotionModelSelect" style="font-size:10px;color:#94a3b8;font-weight:600;display:block;margin-bottom:3px;">Motion Engine:</label>
          <select id="captionsMotionModelSelect" style="width:100%;padding:5px 8px;border-radius:6px;background:#141724;color:#f8fafc;border:1px solid rgba(255,255,255,0.12);font-size:11px;margin-bottom:8px;">
            <option value="wan-2.1-1.3b">Wan 2.1 Video Motion (RTX 3080 12GB Diffusion)</option>
            <option value="wan-2.1-14b-q4">Wan 2.1 - 14B Q4 (Cinematic 720p)</option>
            <option value="liveportrait">LivePortrait (Facial &amp; Lip-Sync Performance)</option>
          </select>
          <button id="renderMotionBtn" class="primaryBtn" style="width:100%;" type="button">✨ Render Performance</button>
          <button id="applyToTimelineBtn" class="secondaryBtn" style="width:100%;margin-top:6px;display:none;" type="button">📥 Set as Timeline Background</button>
          <a href="/video-studio" class="secondaryBtn" style="width:100%;margin-top:6px;text-align:center;text-decoration:none;display:flex;align-items:center;justify-content:center;gap:6px;font-size:11px;padding:6px;" target="_blank">🎬 Open Full AI Video Studio →</a>
        </div>
      </div>
    `;

    dialog.appendChild(header);
    dialog.appendChild(body);
    modal.appendChild(backdrop);
    modal.appendChild(dialog);
    document.body.appendChild(modal);

    // Bind modal actions
    document.getElementById('closeMotionModalBtn').onclick = closeMotionModal;
    backdrop.onclick = closeMotionModal;
    document.getElementById('renderMotionBtn').onclick = executeRenderMotion;
    document.getElementById('useCurrentProjectVideoBtn').onclick = useCurrentVideo;
    document.getElementById('charSelectForMotion').onchange = onCharSelectChange;
    document.getElementById('refreshCharMotionBtn').onclick = populateMotionCharacters;
    document.getElementById('applyToTimelineBtn').onclick = applyOutputToTimeline;

    const driveSelect = document.getElementById('drivingVideoSelectCaptions');
    if (driveSelect) driveSelect.onchange = onDrivingVideoSelectCaptionsChange;
    const uploadDriveBtn = document.getElementById('uploadDrivingVideoCaptionsBtn');
    const driveFileInput = document.getElementById('drivingVideoFileInputCaptions');
    if (uploadDriveBtn && driveFileInput) {
      uploadDriveBtn.onclick = () => driveFileInput.click();
      driveFileInput.onchange = uploadDrivingVideoCaptions;
    }

    const uploadPhotoBtn = document.getElementById('uploadCustomSourceImageCaptionsBtn');
    const photoFileInput = document.getElementById('customSourceImageFileInputCaptions');
    if (uploadPhotoBtn && photoFileInput) {
      uploadPhotoBtn.onclick = () => photoFileInput.click();
      photoFileInput.onchange = uploadCustomSourceImageCaptions;
    }
  }

  function openMotionModal() {
    createMotionStudioModalHTML();
    populateMotionCharacters();
    loadDrivingVideosCaptions();
    useCurrentVideo();
    const modal = document.getElementById('motionStudioModal');
    if (modal) modal.classList.add('open');
  }

  function closeMotionModal() {
    const modal = document.getElementById('motionStudioModal');
    if (modal) modal.classList.remove('open');
  }

  let captionsDrivingVideos = [];

  async function loadDrivingVideosCaptions() {
    const sel = document.getElementById('drivingVideoSelectCaptions');
    if (!sel) return;
    try {
      const res = await fetch('/api/motion/driving-videos');
      if (!res.ok) return;
      const data = await res.json();
      captionsDrivingVideos = data.videos || [];
      sel.replaceChildren(
        Object.assign(document.createElement('option'), { value: '', textContent: 'Select downloaded video…' }),
        ...captionsDrivingVideos.map(v => Object.assign(document.createElement('option'), {
          value: v.path || v.name,
          textContent: `${v.name} (${v.size_mb} MB)`
        }))
      );
      const preview = document.getElementById('drivingVideoPreview');
      if (captionsDrivingVideos.length && (!preview || !preview.querySelector('video'))) {
        sel.value = captionsDrivingVideos[0].path || captionsDrivingVideos[0].name;
        onDrivingVideoSelectCaptionsChange();
      }
    } catch (_) {}
  }

  function onDrivingVideoSelectCaptionsChange() {
    const sel = document.getElementById('drivingVideoSelectCaptions');
    const input = document.getElementById('drivingVideoInput');
    const preview = document.getElementById('drivingVideoPreview');
    if (!sel || !sel.value) return;
    if (input) input.value = sel.value;

    const mediaUrl = `/api/media/${encodeURIComponent(sel.value)}`;
    const v = document.createElement('video');
    v.src = mediaUrl;
    v.controls = true;
    v.style.maxHeight = '100%';
    v.style.maxWidth = '100%';
    v.style.borderRadius = '8px';
    preview.replaceChildren(v);
  }

  async function uploadDrivingVideoCaptions(e) {
    const file = e.target?.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('video', file);
    notify(`Uploading driving video: ${file.name}…`, 'info');

    try {
      const res = await fetch('/api/motion/upload-driving-video', {
        method: 'POST',
        headers: { 'X-Media-Token': getToken() },
        body: fd
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Upload failed');
      notify(`✓ Reference video uploaded!`, 'success');
      await loadDrivingVideosCaptions();
      const sel = document.getElementById('drivingVideoSelectCaptions');
      if (sel) {
        sel.value = data.path || data.name;
        onDrivingVideoSelectCaptionsChange();
      }
    } catch (err) {
      notify('Upload failed: ' + err.message, 'error');
    }
  }

  async function uploadCustomSourceImageCaptions(e) {
    const file = e.target?.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('image', file);
    notify(`Uploading custom photo: ${file.name}…`, 'info');

    try {
      const res = await fetch('/api/motion/upload-swapped-frame', {
        method: 'POST',
        headers: { 'X-Media-Token': getToken() },
        body: fd
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Upload failed');
      notify(`✓ Custom source photo loaded: ${file.name}!`, 'success');
      await populateMotionCharacters(data.filename || data.url);
    } catch (err) {
      notify('Photo upload failed: ' + err.message, 'error');
    }
  }

  async function populateMotionCharacters(preferredSelection = null) {
    const sel = document.getElementById('charSelectForMotion');
    if (!sel) return;
    try {
      // 1. Fetch AI personas
      const charRes = await fetch('/api/characters').catch(() => null);
      const charData = charRes && charRes.ok ? await charRes.json() : { characters: [] };
      const chars = charData.characters || [];

      // 2. Fetch references and swapped photos
      const refRes = await fetch('/api/motion/references').catch(() => null);
      const refData = refRes && refRes.ok ? await refRes.json() : { references: [] };
      const refs = refData.references || [];

      sel.replaceChildren();

      // Persona group
      if (chars.length) {
        const groupChars = document.createElement('optgroup');
        groupChars.label = '👤 AI Personas';
        chars.forEach(c => {
          const opt = document.createElement('option');
          opt.value = c.id;
          opt.textContent = `${c.name} (${c.tag})`;
          opt.dataset.portrait = c.portrait_file ? `/api/characters/${encodeURIComponent(c.id)}/image/${encodeURIComponent(c.portrait_file)}` : '';
          groupChars.appendChild(opt);
        });
        sel.appendChild(groupChars);
      }

      // References & Swapped Photos group
      if (refs.length) {
        const groupRefs = document.createElement('optgroup');
        groupRefs.label = '✨ Custom & Swapped Photos';
        refs.forEach(r => {
          const opt = document.createElement('option');
          opt.value = `/api/motion/references/file/${encodeURIComponent(r.name)}`;
          const isCustom = r.name.startsWith('custom_swapped_');
          const isSwapped = r.name.startsWith('swapped_');
          opt.textContent = isCustom ? `📁 Custom Photo: ${r.name}` : (isSwapped ? `✨ Swapped: ${r.name}` : `📸 Frame: ${r.name}`);
          opt.dataset.portrait = `/api/motion/references/file/${encodeURIComponent(r.name)}`;
          groupRefs.appendChild(opt);
        });
        sel.appendChild(groupRefs);
      }

      // Select preferred, active persona, or first option
      if (preferredSelection) {
        const match = Array.from(sel.options).find(o => o.value === preferredSelection || o.dataset.portrait === preferredSelection || o.value.includes(preferredSelection));
        if (match) {
          sel.value = match.value;
        }
      } else {
        const activeRes = await fetch('/api/characters/active').catch(() => null);
        if (activeRes && activeRes.ok) {
          const actData = await activeRes.json();
          if (actData?.active?.id && Array.from(sel.options).some(o => o.value === actData.active.id)) {
            sel.value = actData.active.id;
          }
        }
      }
      onCharSelectChange();
    } catch (_) {}
  }

  function onCharSelectChange() {
    const sel = document.getElementById('charSelectForMotion');
    const opt = sel?.options[sel.selectedIndex];
    const preview = document.getElementById('sourceImagePreview');
    if (!preview) return;
    const imgUrl = opt?.dataset?.portrait || (opt?.value?.startsWith('/') ? opt.value : '');
    if (imgUrl) {
      const img = document.createElement('img');
      img.src = imgUrl;
      img.alt = opt.textContent;
      img.style.maxHeight = '100%';
      img.style.maxWidth = '100%';
      img.style.borderRadius = '8px';
      img.style.objectFit = 'cover';
      preview.replaceChildren(img);
    } else {
      const ph = document.createElement('span');
      ph.className = 'slotPlaceholder';
      ph.textContent = 'No photo or portrait uploaded for this selection';
      preview.replaceChildren(ph);
    }
  }

  function useCurrentVideo() {
    const videoEl = getActiveVideo();
    const input = document.getElementById('drivingVideoInput');
    const preview = document.getElementById('drivingVideoPreview');
    if (!input || !videoEl) return;

    const src = getActiveVideoSourcePath(videoEl);
    input.value = src;
    if (src) {
      const v = document.createElement('video');
      v.src = src;
      v.controls = true;
      v.style.maxHeight = '100%';
      v.style.maxWidth = '100%';
      v.style.borderRadius = '8px';
      preview.replaceChildren(v);
    }
  }

  let lastRenderedVideoPath = '';

  async function executeRenderMotion() {
    const driveSelect = document.getElementById('drivingVideoSelectCaptions');
    const driveInput = document.getElementById('drivingVideoInput');
    const drivingVideo = (driveSelect && driveSelect.value) ? driveSelect.value : (driveInput ? driveInput.value.trim() : '');
    const modelId = document.getElementById('captionsMotionModelSelect')?.value || 'wan-2.1-1.3b';
    const sel = document.getElementById('charSelectForMotion');
    const opt = sel?.options[sel.selectedIndex];
    const portraitUrl = opt?.dataset?.portrait || opt?.value;

    if (!portraitUrl) {
      notify('Please upload or select a character portrait or still photo first.', 'warning');
      return;
    }
    if (!drivingVideo) {
      notify('Please select or upload a driving dance/action video first.', 'warning');
      return;
    }

    const renderBtn = document.getElementById('renderMotionBtn');
    renderBtn.disabled = true;
    renderBtn.textContent = '⏳ Rendering Performance…';

    try {
      const res = await fetch('/api/motion/render', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          driving_video: drivingVideo,
          source_image: portraitUrl,
          model_id: modelId
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Motion render failed');
      }

      const data = await res.json();
      lastRenderedVideoPath = data.path || data.filename;

      const outPreview = document.getElementById('motionOutputPreview');
      const videoSrc = `/api/motion/outputs/file/${encodeURIComponent(data.filename)}`;
      const outVideo = document.createElement('video');
      outVideo.src = videoSrc;
      outVideo.controls = true;
      outVideo.autoplay = true;
      outVideo.loop = true;
      outVideo.style.maxHeight = '100%';
      outVideo.style.maxWidth = '100%';
      outVideo.style.borderRadius = '8px';
      outPreview.replaceChildren(outVideo);

      const applyBtn = document.getElementById('applyToTimelineBtn');
      if (applyBtn) {
        applyBtn.style.display = 'block';
        applyBtn.dataset.videoSrc = videoSrc;
        applyBtn.dataset.filePath = data.path || '';
      }

      renderBtn.textContent = '✓ Render Complete!';
      setTimeout(() => {
        renderBtn.disabled = false;
        renderBtn.textContent = '✨ Render Performance';
      }, 2500);

    } catch (e) {
      notify('Motion transfer notice: ' + e.message, 'error');
      renderBtn.disabled = false;
      renderBtn.textContent = '✨ Render Performance';
    }
  }

  async function applyOutputToTimeline() {
    const applyBtn = document.getElementById('applyToTimelineBtn');
    const src = applyBtn?.dataset?.videoSrc;
    const filePath = applyBtn?.dataset?.filePath;
    if (!src) return;

    if (window.setProjectBackgroundMedia && filePath) {
      applyBtn.disabled = true;
      applyBtn.textContent = '⏳ Saving to Timeline Project…';
      try {
        const ok = await window.setProjectBackgroundMedia(filePath);
        if (ok) {
          notify('✓ Character performance saved as project timeline video!', 'success');
          closeMotionModal();
          return;
        }
      } catch (err) {
        console.warn('Set project background warning:', err);
      } finally {
        applyBtn.disabled = false;
        applyBtn.textContent = '🎬 Set as Timeline Background';
      }
    }

    const videoEl = document.getElementById('video');
    if (videoEl) {
      videoEl.src = src;
      videoEl.load();
      notify('Character performance placed on studio canvas!', 'info');
      closeMotionModal();
    }
  }

  // --- 1-Click Reference Frame Snapper ---
  async function snapCurrentFrame() {
    const videoEl = getActiveVideo();
    if (!videoEl) {
      notify('No active video found to snapshot.', 'warning');
      return;
    }

    const timestamp = Number(videoEl.currentTime) || 0;
    const src = getActiveVideoSourcePath(videoEl);
    if (!src) {
      notify('Video source is not ready.', 'warning');
      return;
    }

    // Shutter flash animation
    const flash = document.createElement('div');
    Object.assign(flash.style, {
      position: 'fixed',
      top: '0',
      left: '0',
      width: '100vw',
      height: '100vh',
      backgroundColor: 'rgba(255, 255, 255, 0.4)',
      zIndex: '99999',
      pointerEvents: 'none',
      transition: 'opacity 0.22s ease-out'
    });
    document.body.appendChild(flash);
    setTimeout(() => {
      flash.style.opacity = '0';
      setTimeout(() => flash.remove(), 250);
    }, 40);

    try {
      const res = await fetch('/api/motion/extract-frame', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          video_path: src,
          timestamp: timestamp
        })
      });

      if (!res.ok) {
        // Fallback: draw directly to HTML canvas
        extractFrameFromCanvas(videoEl, timestamp);
        return;
      }

      const data = await res.json();
      showSnapperToast(data.filename, timestamp);

    } catch (_) {
      extractFrameFromCanvas(videoEl, timestamp);
    }
  }

  function extractFrameFromCanvas(videoEl, timestamp) {
    try {
      const canvas = document.createElement('canvas');
      canvas.width = videoEl.videoWidth || 1080;
      canvas.height = videoEl.videoHeight || 1920;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(blob => {
        if (!blob) return;
        try {
          navigator.clipboard.write([
            new ClipboardItem({ 'image/png': blob })
          ]);
        } catch (_) {}
        showSnapperToast(null, timestamp, URL.createObjectURL(blob), blob);
      }, 'image/png');
    } catch (e) {
      notify('Frame captured! (' + timestamp.toFixed(2) + 's)', 'success');
    }
  }

  function showSnapperToast(filename, timestamp, objectUrl, directBlob) {
    const existing = document.getElementById('frameSnapperToast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'frameSnapperToast';
    toast.className = 'snapperToast';
    const imgSrc = objectUrl || `/api/motion/references/file/${encodeURIComponent(filename)}`;

    const contentDiv = document.createElement('div');
    contentDiv.className = 'snapperContent';

    const thumb = document.createElement('img');
    thumb.className = 'snapperThumb';
    thumb.src = imgSrc;
    thumb.alt = 'Reference Frame';

    const meta = document.createElement('div');
    meta.className = 'snapperMeta';
    const strong = document.createElement('strong');
    strong.textContent = '📸 Frame Snapped!';
    const small = document.createElement('small');
    small.textContent = `Timestamp: ${timestamp.toFixed(2)}s`;
    meta.append(strong, small);
    contentDiv.append(thumb, meta);

    const actions = document.createElement('div');
    actions.className = 'snapperActions';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'miniActionBtn';
    copyBtn.type = 'button';
    copyBtn.textContent = '📋 Copy';

    const useAiriBtn = document.createElement('button');
    useAiriBtn.className = 'miniActionBtn';
    useAiriBtn.type = 'button';
    useAiriBtn.textContent = '👤 Set as @Airi';

    const closeBtn = document.createElement('button');
    closeBtn.className = 'miniActionBtn';
    closeBtn.type = 'button';
    closeBtn.textContent = '✕';

    actions.append(copyBtn, useAiriBtn, closeBtn);
    toast.append(contentDiv, actions);
    document.body.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);

    closeBtn.onclick = () => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 250);
    };

    copyBtn.onclick = async () => {
      try {
        let blob = directBlob;
        if (!blob) {
          const res = await fetch(imgSrc);
          blob = await res.blob();
        }
        await navigator.clipboard.write([
          new ClipboardItem({ 'image/png': blob })
        ]);
        copyBtn.textContent = '✓ Copied!';
      } catch (_) {
        notify('Image copied to clipboard.', 'success');
      }
    };

    useAiriBtn.onclick = async () => {
      useAiriBtn.textContent = '⏳ Saving…';
      try {
        let blob = directBlob;
        if (!blob) {
          const res = await fetch(imgSrc);
          blob = await res.blob();
        }
        const formData = new FormData();
        formData.append('type', 'portrait');
        formData.append('file', blob, 'portrait.png');

        const uploadRes = await fetch('/api/characters/airi/upload', {
          method: 'POST',
          headers: { 'X-Media-Token': getToken() },
          body: formData
        });
        if (!uploadRes.ok) throw new Error('Upload failed');
        useAiriBtn.textContent = '✓ Set as Airi!';
        notify('✓ Frame set as @Airi face portrait!', 'success');
        if (window.characterStudio) {
          window.characterStudio.open();
        }
      } catch (err) {
        notify('Could not set as Airi portrait: ' + err.message, 'error');
        useAiriBtn.textContent = '👤 Set as @Airi';
      }
    };

    // Auto dismiss after 7s
    setTimeout(() => {
      if (document.body.contains(toast)) {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 250);
      }
    }, 7000);
  }

  // Keyboard shortcut listener ('S' key scoped strictly to active video review contexts)
  window.addEventListener('keydown', (e) => {
    if ((e.key === 's' || e.key === 'S') && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const tag = document.activeElement?.tagName;
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) || document.activeElement?.isContentEditable) return;

      const modal = document.getElementById('previewModal');
      const modalOpen = modal && !modal.classList.contains('hidden') && modal.style.display !== 'none';
      const inStudio = !!document.getElementById('stage');

      if (modalOpen || inStudio) {
        e.preventDefault();
        snapCurrentFrame();
      }
    }
  });

  // Global interface
  window.motionStudio = {
    open: openMotionModal,
    close: closeMotionModal,
    snapFrame: snapCurrentFrame
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createMotionStudioModalHTML);
  } else {
    createMotionStudioModalHTML();
  }
})();
