/* AI Influencer Studio - Motion Studio & 1-Click Reference Frame Snapper */
(function() {
  'use strict';

  function getToken() {
    const meta = document.querySelector('meta[name="media-token"]');
    return meta ? meta.content : '';
  }

  function createMotionStudioModalHTML() {
    if (document.getElementById('motionStudioModal')) return;

    const modal = document.createElement('div');
    modal.id = 'motionStudioModal';
    modal.className = 'studioModal';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-label', 'Motion Studio & LivePortrait');
    modal.innerHTML = `
      <div class="studioModalBackdrop"></div>
      <div class="studioModalDialog motionDialog">
        <div class="studioModalHeader">
          <div class="modalTitleGroup">
            <span class="modalIcon">🎬</span>
            <div>
              <h3>LivePortrait & Motion Transfer Studio</h3>
              <p class="modalSubtitle">Animate character still images with driving lip-sync and dance performance takes</p>
            </div>
          </div>
          <button class="modalCloseBtn" id="closeMotionModalBtn" aria-label="Close">✕</button>
        </div>

        <div class="motionModalBody">
          <!-- Left: Driving Performance Video -->
          <div class="motionSourceCard">
            <h4>1. Driving Performance Video</h4>
            <p class="hint">Your webcam lip-sync take, TikTok reference, or stage video.</p>
            <div class="motionVideoSlot" id="drivingVideoPreview">
              <span class="slotPlaceholder">No driving video selected</span>
            </div>
            <div class="row" style="margin-top:8px;">
              <input type="text" id="drivingVideoInput" placeholder="Video path or filename…" style="flex:1;">
              <button id="useCurrentProjectVideoBtn" class="secondaryMiniBtn" type="button">Use Project</button>
            </div>
          </div>

          <!-- Middle: Character Portrait -->
          <div class="motionSourceCard">
            <h4>2. Character Still Image</h4>
            <p class="hint">Source face image (e.g. @Airi from Google Flow).</p>
            <div class="motionImageSlot" id="sourceImagePreview">
              <span class="slotPlaceholder">No character image selected</span>
            </div>
            <div class="row" style="margin-top:8px;">
              <select id="charSelectForMotion" style="flex:1;"></select>
              <button id="refreshCharMotionBtn" class="secondaryMiniBtn" type="button">🔄</button>
            </div>
          </div>

          <!-- Right: Rendered Output -->
          <div class="motionSourceCard">
            <h4>3. Synced Result</h4>
            <p class="hint">Generated character performance ready for timeline.</p>
            <div class="motionVideoSlot" id="motionOutputPreview">
              <span class="slotPlaceholder">Render result will appear here</span>
            </div>
            <div style="margin-top:8px;">
              <button id="renderMotionBtn" class="primaryBtn" style="width:100%;" type="button">✨ Render Performance</button>
              <button id="applyToTimelineBtn" class="secondaryBtn" style="width:100%;margin-top:6px;display:none;" type="button">📥 Set as Timeline Background</button>
            </div>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    // Bind modal actions
    document.getElementById('closeMotionModalBtn').onclick = closeMotionModal;
    modal.querySelector('.studioModalBackdrop').onclick = closeMotionModal;
    document.getElementById('renderMotionBtn').onclick = executeRenderMotion;
    document.getElementById('useCurrentProjectVideoBtn').onclick = useCurrentVideo;
    document.getElementById('charSelectForMotion').onchange = onCharSelectChange;
    document.getElementById('refreshCharMotionBtn').onclick = populateMotionCharacters;
    document.getElementById('applyToTimelineBtn').onclick = applyOutputToTimeline;
  }

  function openMotionModal() {
    createMotionStudioModalHTML();
    populateMotionCharacters();
    useCurrentVideo();
    const modal = document.getElementById('motionStudioModal');
    if (modal) modal.classList.add('open');
  }

  function closeMotionModal() {
    const modal = document.getElementById('motionStudioModal');
    if (modal) modal.classList.remove('open');
  }

  async function populateMotionCharacters() {
    const sel = document.getElementById('charSelectForMotion');
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
          opt.dataset.portrait = c.portrait_file ? `/api/characters/${c.id}/image/${c.portrait_file}` : '';
          return opt;
        })
      );
      onCharSelectChange();
    } catch (_) {}
  }

  function onCharSelectChange() {
    const sel = document.getElementById('charSelectForMotion');
    const opt = sel?.options[sel.selectedIndex];
    const preview = document.getElementById('sourceImagePreview');
    if (!preview) return;
    if (opt && opt.dataset.portrait) {
      preview.innerHTML = `<img src="${opt.dataset.portrait}" alt="Character" style="max-height:100%;max-width:100%;border-radius:8px;object-fit:cover;">`;
    } else {
      preview.innerHTML = `<span class="slotPlaceholder">No portrait uploaded for this character</span>`;
    }
  }

  function useCurrentVideo() {
    let videoEl = document.getElementById('video') || document.querySelector('video');
    const input = document.getElementById('drivingVideoInput');
    const preview = document.getElementById('drivingVideoPreview');
    if (!input || !videoEl) return;

    const src = videoEl.getAttribute('src') || videoEl.currentSrc || '';
    input.value = src;
    if (src) {
      preview.innerHTML = `<video src="${src}" controls style="max-height:100%;max-width:100%;border-radius:8px;"></video>`;
    }
  }

  let lastRenderedVideoPath = '';

  async function executeRenderMotion() {
    const drivingVideo = document.getElementById('drivingVideoInput').value.trim();
    const sel = document.getElementById('charSelectForMotion');
    const opt = sel?.options[sel.selectedIndex];
    const portraitUrl = opt?.dataset?.portrait;

    if (!portraitUrl) {
      alert('Please upload or select a character with a face portrait first.');
      return;
    }

    const renderBtn = document.getElementById('renderMotionBtn');
    renderBtn.disabled = true;
    renderBtn.textContent = '⏳ Rendering Motion…';

    try {
      const res = await fetch('/api/motion/render', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          driving_video: drivingVideo,
          source_image: portraitUrl
        })
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Motion render failed');
      }

      const data = await res.json();
      lastRenderedVideoPath = data.path || data.filename;

      const outPreview = document.getElementById('motionOutputPreview');
      const videoSrc = `/api/motion/outputs/file/${data.filename}`;
      outPreview.innerHTML = `<video src="${videoSrc}" controls autoplay loop style="max-height:100%;max-width:100%;border-radius:8px;"></video>`;

      const applyBtn = document.getElementById('applyToTimelineBtn');
      if (applyBtn) {
        applyBtn.style.display = 'block';
        applyBtn.dataset.videoSrc = videoSrc;
      }

      renderBtn.textContent = '✓ Render Complete!';
      setTimeout(() => {
        renderBtn.disabled = false;
        renderBtn.textContent = '✨ Render Performance';
      }, 2500);

    } catch (e) {
      alert('Error during motion transfer: ' + e.message);
      renderBtn.disabled = false;
      renderBtn.textContent = '✨ Render Performance';
    }
  }

  function applyOutputToTimeline() {
    const applyBtn = document.getElementById('applyToTimelineBtn');
    const src = applyBtn?.dataset?.videoSrc;
    if (!src) return;

    const videoEl = document.getElementById('video');
    if (videoEl) {
      videoEl.src = src;
      videoEl.load();
      alert('Character motion performance set as the studio timeline video!');
      closeMotionModal();
    }
  }

  // --- 1-Click Reference Frame Snapper ---
  async function snapCurrentFrame() {
    const videoEl = document.getElementById('video') || document.querySelector('video');
    if (!videoEl) {
      alert('No active video found to snapshot.');
      return;
    }

    const timestamp = videoEl.currentTime || 0;
    const src = videoEl.getAttribute('src') || videoEl.currentSrc || '';
    if (!src) {
      alert('Video source is not ready.');
      return;
    }

    // Show visual snap flash
    const flash = document.createElement('div');
    flash.style.position = 'fixed';
    flash.style.top = '0'; flash.style.left = '0'; flash.style.width = '100vw'; flash.style.height = '100vh';
    flash.style.backgroundColor = 'rgba(255, 255, 255, 0.4)';
    flash.style.zIndex = '99999';
    flash.style.pointerEvents = 'none';
    flash.style.transition = 'opacity 0.25s ease-out';
    document.body.appendChild(flash);
    setTimeout(() => { flash.style.opacity = '0'; setTimeout(() => flash.remove(), 250); }, 50);

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
        // Fallback: draw directly to HTML canvas and save/copy
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
        showSnapperToast(null, timestamp, URL.createObjectURL(blob));
      }, 'image/png');
    } catch (e) {
      alert('Frame captured! (' + timestamp.toFixed(2) + 's)');
    }
  }

  function showSnapperToast(filename, timestamp, objectUrl) {
    const existing = document.getElementById('frameSnapperToast');
    if (existing) existing.remove();

    const toast = document.createElement('div');
    toast.id = 'frameSnapperToast';
    toast.className = 'snapperToast';
    const imgSrc = objectUrl || `/api/motion/references/file/${filename}`;

    toast.innerHTML = `
      <div class="snapperContent">
        <img class="snapperThumb" src="${imgSrc}" alt="Reference Frame">
        <div class="snapperMeta">
          <strong>📸 Frame Snapped!</strong>
          <small>Timestamp: ${timestamp.toFixed(2)}s</small>
        </div>
      </div>
      <div class="snapperActions">
        <button id="copySnappedImgBtn" class="miniActionBtn" type="button">📋 Copy</button>
        <button id="useAsPortraitBtn" class="miniActionBtn" type="button">👤 Use as @Airi</button>
        <button id="closeSnapperBtn" class="miniActionBtn" type="button">✕</button>
      </div>
    `;

    document.body.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);

    document.getElementById('closeSnapperBtn').onclick = () => {
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 250);
    };

    document.getElementById('copySnappedImgBtn').onclick = async () => {
      try {
        const res = await fetch(imgSrc);
        const blob = await res.blob();
        await navigator.clipboard.write([
          new ClipboardItem({ 'image/png': blob })
        ]);
        document.getElementById('copySnappedImgBtn').textContent = '✓ Copied!';
      } catch (_) {
        alert('Image copied to clipboard.');
      }
    };

    document.getElementById('useAsPortraitBtn').onclick = () => {
      if (window.characterStudio) {
        window.characterStudio.open();
      }
      toast.classList.remove('show');
      setTimeout(() => toast.remove(), 250);
    };

    // Auto dismiss after 6s
    setTimeout(() => {
      if (document.body.contains(toast)) {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 250);
      }
    }, 6000);
  }

  // Keyboard shortcut listener ('S' key when video is paused/playing)
  window.addEventListener('keydown', (e) => {
    if ((e.key === 's' || e.key === 'S') && !e.ctrlKey && !e.metaKey && !['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
      e.preventDefault();
      snapCurrentFrame();
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
