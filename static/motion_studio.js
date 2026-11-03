/* Reference frame snapper and AI Studio shortcut for the main window.
 * snapFrame() saves the current video frame as a lossless reference in the library;
 * open() goes to AI Studio, where Face Swap Video and Performance run as real jobs.
 */
(() => {
  'use strict';

  const token = () => document.querySelector('meta[name="media-token"]')?.content || '';

  function notify(message, isError = false, action) {
    document.getElementById('motionStudioToast')?.remove();
    const toast = document.createElement('div');
    toast.id = 'motionStudioToast';
    toast.className = 'snapperToast';
    toast.setAttribute('role', 'status');
    const text = document.createElement('span');
    text.textContent = message;
    toast.append(text);
    if (action) {
      const link = document.createElement('a');
      link.href = action.href;
      link.textContent = action.label;
      link.style.marginLeft = '10px';
      toast.append(link);
    }
    if (isError) toast.style.borderColor = 'rgba(255,69,58,.6)';
    document.body.append(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 250); }, 5000);
  }

  function activeVideo() {
    const modal = document.getElementById('previewModal');
    const preview = document.getElementById('previewModalVideo');
    if (modal && !modal.classList.contains('hidden') && modal.style.display !== 'none' && preview?.style.display !== 'none') {
      return preview;
    }
    return [document.getElementById('video'), document.getElementById('videoPreview')]
      .find((video) => video && (video.currentSrc || video.src)) || document.querySelector('video');
  }

  function sourcePath(video) {
    if (video.id === 'previewModalVideo') {
      const shown = document.getElementById('previewModalPath')?.textContent.trim();
      if (shown) return shown;
    }
    const src = video.getAttribute('src') || video.currentSrc || '';
    try {
      const url = new URL(src, window.location.origin);
      if (url.pathname === '/api/preview_file' && url.searchParams.get('path')) return url.searchParams.get('path');
      return url.origin === window.location.origin ? url.pathname : src;
    } catch (_) {
      return src;
    }
  }

  async function snapFrame() {
    const video = activeVideo();
    if (!video || !(video.currentSrc || video.src)) {
      notify('Open a video first, then snap a frame.', true);
      return;
    }
    const response = await fetch('/api/motion/extract-frame', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Media-Token': token() },
      body: JSON.stringify({ video_path: sourcePath(video), timestamp: video.currentTime || 0 }),
    }).catch(() => null);
    const data = response ? await response.json().catch(() => ({})) : {};
    if (!response || !response.ok) {
      notify(data.error || 'The frame could not be saved.', true);
      return;
    }
    notify(`Saved reference frame at ${Number(data.timestamp).toFixed(2)} s.`, false,
      { href: '/video-studio#faceswap', label: 'Open AI Studio' });
  }

  window.motionStudio = {
    open: (section = 'faceswap') => { window.location.href = `/video-studio#${section}`; },
    snapFrame,
  };
})();
