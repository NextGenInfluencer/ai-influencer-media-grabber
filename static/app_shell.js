/* Shared Media Grabber Pro Shell: Zero-AI / Laptop Mode + Live GPU VRAM Guard */
(() => {
  'use strict';

  const STORAGE_HIDE_AI = 'mg_hide_ai_ui';
  const STORAGE_RAIL_COLLAPSED = 'mg_rail_collapsed';
  const VALID_TABS = new Set(['downloader', 'converter', 'cleaner', 'gallery', 'history', 'settings']);
  const AI_CHECKBOX_IDS = [
    'transcribeAudio',
    'burnSubtitles',
    'exportSubtitlesDownloader',
    'autoExtractPrompt',
    'aiSummarize',
    'convBurnSubtitles',
    'convExportSubtitles',
  ];

  let vramBusyReleasing = false;

  function mediaToken() {
    return document.querySelector('meta[name="media-token"]')?.content || '';
  }

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    const token = mediaToken();
    if (token) headers['X-Media-Token'] = token;
    if (options.body && typeof options.body !== 'string') {
      headers['Content-Type'] = 'application/json';
      options = { ...options, body: JSON.stringify(options.body) };
    }
    const response = await fetch(path, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `Request failed (${response.status})`);
    }
    return data;
  }

  function notify(title, message) {
    if (typeof window.showToast === 'function') {
      window.showToast(title, message);
    }
  }

  function applyZeroAIState(enabled) {
    const isHidden = Boolean(enabled);
    document.documentElement.dataset.hideAi = isHidden ? 'true' : 'false';
    try {
      localStorage.setItem(STORAGE_HIDE_AI, isHidden ? '1' : '0');
    } catch {
      /* ignore */
    }

    document.querySelectorAll('[data-zero-ai-switch]').forEach((input) => {
      if ('checked' in input) input.checked = isHidden;
    });
    document.querySelectorAll('[data-zero-ai-label]').forEach((label) => {
      label.textContent = isHidden ? 'Laptop Mode: On' : 'Laptop Mode: Off';
    });

    if (isHidden) {
      window.copilot?.close?.();
      for (const id of AI_CHECKBOX_IDS) {
        const box = document.getElementById(id);
        if (box && box.checked) box.checked = false;
      }
      const translateSel = document.getElementById('convTranslateLang');
      if (translateSel && translateSel.value !== 'none') translateSel.value = 'none';
    }
  }

  window.setZeroAIMode = async function setZeroAIMode(enabled, { persist = true } = {}) {
    const next = Boolean(enabled);
    applyZeroAIState(next);
    if (persist) {
      try {
        await api('/api/ai/settings', { method: 'POST', body: { hide_ai_ui: next } });
      } catch (err) {
        notify('Settings Notice', err.message);
      }
    }
    if (!next) {
      if (typeof window.refreshAIBadges === 'function') window.refreshAIBadges();
      if (typeof window.refreshVramGuard === 'function') window.refreshVramGuard();
    }
    notify(
      next ? 'Laptop / Zero-AI Mode On' : 'AI Features Enabled',
      next
        ? 'AI tools hidden. Downloading, trimming, 9:16 crop, cleaner, and captions stay active with 0 VRAM.'
        : 'AI Studio, Copilot, and on-demand GPU controls are now visible.'
    );
  };

  window.toggleZeroAIMode = function toggleZeroAIMode() {
    const current = document.documentElement.dataset.hideAi === 'true';
    return window.setZeroAIMode(!current);
  };

  window.toggleNavRail = function toggleNavRail(force) {
    if (!document.body) return;
    const collapsed = typeof force === 'boolean'
      ? force
      : !document.body.classList.contains('rail-collapsed');
    document.body.classList.toggle('rail-collapsed', collapsed);
    try {
      localStorage.setItem(STORAGE_RAIL_COLLAPSED, collapsed ? '1' : '0');
    } catch {
      /* ignore */
    }
  };

  function residentEntries(data) {
    const gpuMap = data?.gpu || {};
    const items = [];
    for (const [name, info] of Object.entries(gpuMap)) {
      const gb = Number(info?.vram_gb || 0);
      const displayName = name.startsWith('ollama:') ? name.slice('ollama:'.length) : name;
      items.push({
        name,
        displayName,
        vramGb: gb,
        active: Boolean(info?.active),
        label: gb > 0 ? `${displayName} (${gb.toFixed(1)} GB)` : displayName,
      });
    }
    const ollamaLoaded = Array.isArray(data?.ollama_loaded) ? data.ollama_loaded : [];
    for (const model of ollamaLoaded) {
      if (!items.some((entry) =>
        entry.name === 'ollama' ||
        entry.name === model ||
        entry.name === `ollama:${model}` ||
        entry.displayName === model
      )) {
        items.push({ name: model, displayName: model, vramGb: 0, active: false, label: model });
      }
    }
    return items;
  }

  function renderVramPill(mount, items) {
    const pill = document.createElement('div');
    pill.className = `vram-pill ${items.length ? 'loaded' : 'idle'}`;

    const infoBtn = document.createElement('button');
    infoBtn.type = 'button';
    infoBtn.className = 'vram-pill-main';
    infoBtn.title = items.length
      ? `Resident on GPU: ${items.map((i) => i.label).join(', ')}`
      : 'GPU VRAM Idle (0 MB) — Click to inspect AI Engines';
    infoBtn.onclick = () => {
      if (typeof window.openAIEngines === 'function') window.openAIEngines();
    };

    const dot = document.createElement('span');
    dot.className = 'vram-dot';

    const text = document.createElement('span');
    text.className = 'vram-pill-text mono-metric';
    if (items.length) {
      const totalGb = items.reduce((sum, item) => sum + item.vramGb, 0);
      text.textContent = totalGb > 0
        ? `VRAM ${totalGb.toFixed(1)} GB`
        : `VRAM ${items[0].displayName || items[0].name}`;
    } else {
      text.textContent = 'VRAM 0 MB';
    }

    infoBtn.append(dot, text);
    pill.appendChild(infoBtn);

    if (items.length) {
      const unloadBtn = document.createElement('button');
      unloadBtn.type = 'button';
      unloadBtn.className = 'vram-unload-btn';
      unloadBtn.disabled = vramBusyReleasing;
      unloadBtn.textContent = vramBusyReleasing ? 'Freeing…' : 'Unload';
      unloadBtn.title = 'Immediately unload resident AI models to reclaim GPU VRAM';
      unloadBtn.onclick = (event) => {
        event.stopPropagation();
        window.releaseGpuVram();
      };
      pill.appendChild(unloadBtn);
    }

    mount.replaceChildren(pill);
  }

  function updateSettingsVramSummary(items) {
    const el = document.getElementById('settingsVramStatus');
    const btn = document.getElementById('settingsReleaseVramBtn');
    if (el) {
      el.textContent = items.length
        ? `Resident now: ${items.map((i) => i.label).join(', ')}`
        : 'Idle · 0 MB allocated by Media Grabber';
    }
    if (btn) {
      btn.disabled = vramBusyReleasing;
    }
  }

  window.refreshVramGuard = async function refreshVramGuard() {
    const mounts = document.querySelectorAll('.vram-guard-mount');
    if (!mounts.length && !document.getElementById('settingsVramStatus')) return;
    if (document.documentElement.dataset.hideAi === 'true') return;
    if (document.visibilityState === 'hidden') return;

    try {
      const data = await api('/api/ai/engines');
      const items = residentEntries(data);
      mounts.forEach((mount) => renderVramPill(mount, items));
      updateSettingsVramSummary(items);
      window.dispatchEvent(new CustomEvent('vram-updated', { detail: { items, data } }));
    } catch {
      /* ignore transient offline polling */
    }
  };

  window.releaseGpuVram = async function releaseGpuVram() {
    if (vramBusyReleasing) return null;
    vramBusyReleasing = true;
    document.querySelectorAll('.vram-unload-btn').forEach((btn) => {
      btn.disabled = true;
      btn.textContent = 'Freeing…';
    });

    try {
      const result = await api('/api/ai/gpu/release', { method: 'POST' });
      const items = residentEntries(result);
      document.querySelectorAll('.vram-guard-mount').forEach((mount) => renderVramPill(mount, items));
      updateSettingsVramSummary(items);
      window.dispatchEvent(new CustomEvent('vram-updated', { detail: { items, data: result } }));
      if (result.freed) {
        notify('GPU VRAM Freed', 'All idle AI models have been unloaded (0 MB active).');
      } else {
        notify('GPU Busy', `Still running: ${(result.busy || []).join(', ')}`);
      }
      return result;
    } catch (err) {
      notify('VRAM Unload Failed', err.message);
      return null;
    } finally {
      vramBusyReleasing = false;
      window.refreshVramGuard();
    }
  };

  function handleHashNavigation() {
    if (window.location.pathname !== '/') return;
    const hash = window.location.hash.replace(/^#/, '');
    if (VALID_TABS.has(hash) && typeof window.switchTab === 'function') {
      window.switchTab(hash);
    }
  }

  async function initShell() {
    try {
      if (localStorage.getItem(STORAGE_RAIL_COLLAPSED) === '1' && document.body) {
        document.body.classList.add('rail-collapsed');
      }
    } catch {
      /* ignore */
    }

    handleHashNavigation();
    window.addEventListener('hashchange', handleHashNavigation);

    try {
      const data = await api('/api/ai/settings');
      applyZeroAIState(data.hide_ai_ui === true);
    } catch {
      applyZeroAIState(document.documentElement.dataset.hideAi === 'true');
    }

    window.refreshVramGuard();
    setInterval(() => {
      if (document.documentElement.dataset.hideAi !== 'true' && document.visibilityState === 'visible') {
        window.refreshVramGuard();
      }
    }, 20000);

    // Header popover menus: only one open at a time, close on outside click / Esc / item action.
    document.addEventListener('click', (event) => {
      const clickedMenu = event.target.closest('details.header-menu');
      document.querySelectorAll('details.header-menu[open]').forEach((menu) => {
        if (menu !== clickedMenu) menu.open = false;
      });
      if (clickedMenu) {
        const panelAction = event.target.closest('.header-menu-panel button, .header-menu-panel a');
        if (panelAction) {
          setTimeout(() => {
            clickedMenu.open = false;
          }, 0);
        }
      }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        document.querySelectorAll('details.header-menu[open]').forEach((menu) => {
          menu.open = false;
        });
      }
    });
  }

  // Apply cached Zero-AI preference synchronously before DOMContentLoaded to minimize flash.
  try {
    applyZeroAIState(localStorage.getItem(STORAGE_HIDE_AI) === '1');
  } catch {
    /* ignore */
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initShell);
  } else {
    initShell();
  }
})();
