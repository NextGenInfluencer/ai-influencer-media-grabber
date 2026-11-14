/* Media Grabber Command Center — Phase 2 Action Cards, Phase 3a Lineage Map & Phase 3b Split-Screen Configurator.
 * Zero idle VRAM policy: never wakes Ollama, ComfyUI, or PyTorch when computing cards or reading telemetry.
 */
(() => {
  'use strict';

  const PIPELINE_DEFAULTS_KEY = 'agy.pipelineDefaults.v1';
  const PIPELINE_IDS = ['forceH264', 'extractFrame', 'aiBypass', 'identifySong'];

  let lastConfigPayload = null;
  let lastLineagePayload = null;
  let highlightedPath = '';
  let recentCompletedItem = null;

  function token() {
    return document.querySelector('meta[name="media-token"]')?.content || '';
  }

  function makeEl(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function notify(title, message) {
    if (typeof window.showToast === 'function') {
      window.showToast(title, message);
    }
  }

  // ------------------------------------------------------------------ Converter 9:16 Quick Reframe

  async function openInConverter916(filePath, fileName) {
    if (!filePath) return;
    window.switchTab?.('converter');
    window.setAspectRatioPreset?.('crop_9_16');

    const autoCrop = document.getElementById('convAutoCrop');
    if (autoCrop) {
      autoCrop.checked = true;
      autoCrop.dispatchEvent(new Event('change', { bubbles: true }));
    }

    const input = document.getElementById('mediaFile');
    if (!input) return;

    try {
      const url = `/api/preview_file?path=${encodeURIComponent(filePath)}`;
      const res = await fetch(url, { headers: { 'X-Media-Token': token() } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const len = Number(res.headers.get('content-length') || 0);
      if (len > 200 * 1024 * 1024) {
        notify('Large File Notice', 'Switch to Converter and drop the file directly (>200 MB).');
        return;
      }
      const blob = await res.blob();
      if (blob.size > 200 * 1024 * 1024) {
        notify('Large File Notice', 'File exceeds 200 MB browser staging limit.');
        return;
      }
      const safeName = fileName || filePath.split(/[\\/]/).pop() || 'clip.mp4';
      const file = new File([blob], safeName, { type: blob.type || 'video/mp4' });
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      notify('9:16 Reframe Ready', `Loaded "${safeName}" with 9:16 crop & CPU face-tracking.`);
    } catch (err) {
      notify('Could Not Stage Clip', err.message || 'Select the clip manually in Offline Media Tools.');
    }
  }

  // ------------------------------------------------------------------ Grabber & Gallery Proactive Action Cards

  function collectRecentVideos() {
    const out = [];
    const seen = new Set();
    if (recentCompletedItem && recentCompletedItem.full_path) {
      out.push(recentCompletedItem);
      seen.add(recentCompletedItem.full_path.toLowerCase());
    }
    const items = Array.isArray(window.currentGalleryItems) ? window.currentGalleryItems : [];
    for (const item of items) {
      if (!item || item.type !== 'video' || !item.full_path || (item.section || 'downloads') === 'studio') continue;
      const key = item.full_path.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(item);
      if (out.length >= 4) break;
    }
    return out;
  }

  async function runGrabberProactiveAction(action, payload = {}) {
    if (action === 'open-in-captions') {
      if (!payload.path) return 'No video clip selected.';
      window.location.href = `/captions?import=${encodeURIComponent(payload.path)}`;
      return 'Opening clip in Creator Studio…';
    }
    if (action === 'reframe-9-16') {
      await openInConverter916(payload.path, payload.name);
      return 'Loaded clip into 9:16 Reframe tool.';
    }
    if (action === 'open-lineage') {
      await focusLineageForPath(payload.path || '');
      return 'Opened Media Lineage Map.';
    }
    return false;
  }

  function refreshGrabberActionCards() {
    if (typeof window.ActionCards === 'undefined') return;
    const recentVideos = collectRecentVideos();
    const zeroAi = document.documentElement?.dataset?.hideAi === 'true';
    const cards = window.ActionCards.computeGrabberCards({ recentVideos, zeroAi });

    const queueMount = document.getElementById('grabberActionCards');
    if (queueMount) {
      window.ActionCards.renderStrip(queueMount, 'grabber', cards, runGrabberProactiveAction, {
        headerLabel: '⚡ Smart Next Steps',
        maxCards: 2,
      });
    }

    const galMount = document.getElementById('galleryActionCards');
    if (galMount) {
      window.ActionCards.renderStrip(galMount, 'grabber', cards, runGrabberProactiveAction, {
        headerLabel: '⚡ Recommended Workflow Actions',
        maxCards: 2,
      });
    }
  }

  window.copilotProactiveProvider = () => ({
    scope: 'grabber',
    cards: typeof window.ActionCards !== 'undefined'
      ? window.ActionCards.computeGrabberCards({
          recentVideos: collectRecentVideos(),
          zeroAi: document.documentElement?.dataset?.hideAi === 'true',
        })
      : [],
    onApply: runGrabberProactiveAction,
  });

  // ------------------------------------------------------------------ Phase 3a: Interactive Media Lineage Map

  function formatShortSize(bytes) {
    const n = Number(bytes || 0);
    if (!n) return '';
    if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  }

  function renderNode(stageClass, tagText, titleText, subText, actions = [], isEmpty = false) {
    const node = makeEl('div', `lineage-node ${stageClass}${isEmpty ? ' is-empty' : ''}`);
    const top = makeEl('div');
    top.append(
      makeEl('div', 'lineage-stage-tag', tagText),
      makeEl('div', 'lineage-node-title', titleText),
      makeEl('div', 'lineage-node-sub', subText || '')
    );
    if (titleText) top.children[1].title = titleText;
    node.append(top);

    if (actions.length) {
      const bar = makeEl('div', 'lineage-node-actions');
      for (const act of actions) {
        const btn = makeEl('button', `lineage-mini-btn${act.primary ? ' primary' : ''}`, act.label);
        btn.type = 'button';
        btn.onclick = act.onClick;
        bar.append(btn);
      }
      node.append(bar);
    }
    return node;
  }

  function renderLineageView(data) {
    const container = document.getElementById('lineageContainer');
    const badge = document.getElementById('galleryLineageBadge');
    const summary = data?.summary || {};
    if (badge) badge.textContent = String(summary.total_chains ?? (data?.chains?.length || 0));
    if (!container) return;

    const query = (document.getElementById('gallerySearch')?.value || '').trim().toLowerCase();
    const allChains = Array.isArray(data?.chains) ? data.chains : [];
    const chains = query
      ? allChains.filter((c) => {
          const hay = [
            c.source?.url,
            c.source?.uploader,
            c.source?.platform,
            c.raw?.name,
            ...(c.derived || []).map((d) => d.name),
            ...(c.exports || []).map((e) => e.project_name),
          ].join(' ').toLowerCase();
          return hay.includes(query);
        })
      : allChains;

    container.replaceChildren();

    const bar = makeEl('div', 'lineage-summary-bar');
    const kpis = makeEl('div', 'lineage-kpi-row');
    kpis.append(
      makeEl('span', 'lineage-kpi-pill', `🧬 ${summary.total_chains || 0} Chains`),
      makeEl('span', 'lineage-kpi-pill', `🔗 ${summary.with_source_url || 0} URL Sources`),
      makeEl('span', 'lineage-kpi-pill', `🎞️ ${summary.derived_count || 0} Derived Assets`),
      makeEl('span', 'lineage-kpi-pill', `🎬 ${summary.studio_projects || 0} Studio Projects (${summary.rendered_exports || 0} Exports)`)
    );
    const refreshBtn = makeEl('button', 'lineage-mini-btn primary', '↻ Refresh Graph');
    refreshBtn.type = 'button';
    refreshBtn.onclick = () => loadMediaLineage(true);
    bar.append(kpis, refreshBtn);
    container.append(bar);

    if (!chains.length) {
      const empty = makeEl('div', 'obsidian-card p-8 text-center flex flex-col items-center justify-center gap-3');
      const ico = makeEl('div', 'w-12 h-12 rounded-2xl bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 text-lg');
      ico.textContent = '🧬';
      empty.append(
        ico,
        makeEl('h4', 'text-sm font-bold text-white', query ? `No lineage matches "${query}"` : 'Media Lineage Graph Ready'),
        makeEl('p', 'text-xs text-zinc-400 max-w-md', 'Download a social clip or open one in Creator Studio to trace its full Source URL → Raw Clip → Extracted Assets → Final Exports graph here.')
      );
      const btns = makeEl('div', 'flex items-center gap-2 pt-1');
      const dlBtn = makeEl('button', 'lineage-mini-btn primary', '⬇️ Grab Media');
      dlBtn.type = 'button';
      dlBtn.onclick = () => window.switchTab?.('downloader');
      const stBtn = makeEl('button', 'lineage-mini-btn', '🎬 Open Creator Studio');
      stBtn.type = 'button';
      stBtn.onclick = () => { window.location.href = '/captions'; };
      btns.append(dlBtn, stBtn);
      empty.append(btns);
      container.append(empty);
      return;
    }

    for (const chain of chains) {
      const raw = chain.raw;
      const src = chain.source || {};
      const card = makeEl('div', 'lineage-chain-card');
      if (highlightedPath && raw?.full_path && raw.full_path.toLowerCase() === highlightedPath.toLowerCase()) {
        card.classList.add('is-highlighted');
      }

      const grid = makeEl('div', 'lineage-flow-grid');

      // Stage 1: Source URL
      const srcActs = [];
      if (src.url) {
        srcActs.push({ label: '↗ Open Post', onClick: () => window.open(src.url, '_blank', 'noopener') });
      }
      grid.append(renderNode(
        'stage-source',
        '1. Source Origin',
        src.uploader ? `@${src.uploader} · ${src.platform || 'Social'}` : (src.platform || 'Local Import'),
        src.url || 'No external URL recorded',
        srcActs,
        !src.url
      ));

      // Stage 2: Raw Media
      if (raw) {
        const rawActs = [];
        if (raw.full_path) {
          if (raw.type === 'video' || raw.type === 'audio') {
            rawActs.push({ label: '▶ Play', onClick: () => window.playCompletedFile?.(raw.full_path) });
          } else if (raw.url) {
            rawActs.push({ label: '🔍 View', onClick: () => window.open(raw.url, '_blank') });
          }
          rawActs.push({ label: '📂 Folder', onClick: () => window.openFolder?.(raw.full_path) });
          if (raw.type === 'video' && !(chain.exports || []).length) {
            rawActs.push({
              label: '🎬 Studio',
              primary: true,
              onClick: () => { window.location.href = `/captions?import=${encodeURIComponent(raw.full_path)}`; },
            });
          }
        }
        grid.append(renderNode(
          'stage-raw',
          '2. Raw Media',
          raw.name || 'Downloaded file',
          `${raw.folder || 'Library'} · ${formatShortSize(raw.size)}`,
          rawActs,
          false
        ));
      } else {
        grid.append(renderNode('stage-raw', '2. Raw Media', 'Direct Studio Upload', 'Imported inside Creator Studio', [], true));
      }

      // Stage 3: Derived Frames / Edits
      const derived = chain.derived || [];
      if (derived.length) {
        const firstD = derived[0];
        const drvActs = [
          {
            label: firstD.type === 'image' ? '🖼 Frame' : '▶ Play',
            onClick: () => {
              if (firstD.type === 'image' && firstD.url) window.open(firstD.url, '_blank');
              else if (firstD.full_path) window.playCompletedFile?.(firstD.full_path);
            },
          },
          { label: '📂 Folder', onClick: () => firstD.full_path && window.openFolder?.(firstD.full_path) },
        ];
        const subNames = derived.slice(1).map((d) => d.name).join(', ');
        grid.append(renderNode(
          'stage-derived',
          `3. Derived (${derived.length})`,
          firstD.name || 'Derived asset',
          subNames ? `+${derived.length - 1} more: ${subNames}` : `${firstD.kind || firstD.folder || 'Derivative'}`,
          drvActs,
          false
        ));
      } else {
        const drvActs = [];
        if (raw?.full_path && raw.type === 'video') {
          drvActs.push({ label: '📱 Prep 9:16', onClick: () => openInConverter916(raw.full_path, raw.name) });
        }
        grid.append(renderNode('stage-derived', '3. Derived Assets', 'No Conversions Yet', 'Extract frame or 9:16 vertical crop', drvActs, true));
      }

      // Stage 4: Captions & Studio Exports
      const exports = chain.exports || [];
      if (exports.length) {
        const firstEx = exports[0];
        const exActs = [
          { label: '🎬 Open Project', primary: true, onClick: () => { window.location.href = firstEx.studio_url; } },
        ];
        const renderedCount = (firstEx.export_files || []).length;
        grid.append(renderNode(
          'stage-export',
          `4. Studio (${exports.length})`,
          firstEx.project_name || 'Caption Project',
          `${firstEx.cue_count || 0} cues${firstEx.has_music ? ' · +MP3 Mix' : ''} · ${renderedCount} export${renderedCount === 1 ? '' : 's'}`,
          exActs,
          false
        ));
      } else {
        const expActs = [];
        if (raw?.full_path && raw.type === 'video') {
          expActs.push({
            label: '🎬 Create Captions',
            primary: true,
            onClick: () => { window.location.href = `/captions?import=${encodeURIComponent(raw.full_path)}`; },
          });
        }
        grid.append(renderNode('stage-export', '4. Studio Exports', 'Not Captioned Yet', 'Send directly to Creator Studio', expActs, true));
      }

      card.append(grid);
      container.append(card);
    }
  }

  async function loadMediaLineage(force = false) {
    if (!force && lastLineagePayload && document.getElementById('lineageContainer')?.children?.length) {
      renderLineageView(lastLineagePayload);
      return lastLineagePayload;
    }
    try {
      const res = await fetch('/api/lineage', { headers: { 'X-Media-Token': token() } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      lastLineagePayload = data;
      renderLineageView(data);
      return data;
    } catch (err) {
      const container = document.getElementById('lineageContainer');
      if (container) {
        container.replaceChildren(makeEl('div', 'p-6 text-center text-xs text-red-400', `Could not load Media Lineage: ${err.message}`));
      }
      return null;
    }
  }

  async function focusLineageForPath(filePath) {
    highlightedPath = filePath || '';
    window.switchTab?.('gallery');
    window.switchGallerySection?.('lineage');
    await loadMediaLineage(true);
    const hl = document.querySelector('#lineageContainer .lineage-chain-card.is-highlighted');
    hl?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  }

  window.loadMediaLineage = loadMediaLineage;
  window.focusLineageForPath = focusLineageForPath;

  // ------------------------------------------------------------------ Phase 3b: Split-Screen Tooling & Live JSON Configurator

  function readPipelineDefaults() {
    let saved = {};
    try {
      saved = JSON.parse(localStorage.getItem(PIPELINE_DEFAULTS_KEY) || '{}') || {};
    } catch {
      saved = {};
    }
    const out = {};
    for (const id of PIPELINE_IDS) {
      const el = document.getElementById(id);
      if (Object.prototype.hasOwnProperty.call(saved, id)) {
        out[id] = Boolean(saved[id]);
      } else if (el) {
        out[id] = Boolean(el.checked);
      } else {
        out[id] = id === 'extractFrame' || id === 'identifySong';
      }
    }
    return out;
  }

  function applyPipelineDefaultsToDom(defaults) {
    for (const id of PIPELINE_IDS) {
      const val = Boolean(defaults[id]);
      const mainEl = document.getElementById(id);
      if (mainEl) mainEl.checked = val;
      document.querySelectorAll(`[data-pipeline-switch="${id}"]`).forEach((sw) => {
        sw.checked = val;
      });
    }
  }

  function savePipelineDefaults(defaults) {
    try {
      localStorage.setItem(PIPELINE_DEFAULTS_KEY, JSON.stringify(defaults));
    } catch {
      /* ignore storage errors */
    }
  }

  function syncPipelineSwitchBindings() {
    const initial = readPipelineDefaults();
    applyPipelineDefaultsToDom(initial);

    for (const id of PIPELINE_IDS) {
      const mainEl = document.getElementById(id);
      mainEl?.addEventListener('change', () => {
        const next = readPipelineDefaults();
        next[id] = Boolean(mainEl.checked);
        savePipelineDefaults(next);
        applyPipelineDefaultsToDom(next);
        renderJsonInspector();
      });

      document.querySelectorAll(`[data-pipeline-switch="${id}"]`).forEach((sw) => {
        sw.addEventListener('change', () => {
          const next = readPipelineDefaults();
          next[id] = Boolean(sw.checked);
          savePipelineDefaults(next);
          applyPipelineDefaultsToDom(next);
          renderJsonInspector();
        });
      });
    }
  }

  function appendJsonToken(parent, cls, text) {
    if (!cls) {
      parent.append(document.createTextNode(text));
      return;
    }
    const span = document.createElement('span');
    span.className = cls;
    span.textContent = text;
    parent.append(span);
  }

  function renderSyntaxJson(preEl, obj) {
    if (!preEl) return;
    const raw = JSON.stringify(obj, null, 2);
    preEl.replaceChildren();
    const tokRe = /("(\\u[\da-fA-F]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g;
    let last = 0;
    let match;
    while ((match = tokRe.exec(raw)) !== null) {
      if (match.index > last) {
        appendJsonToken(preEl, '', raw.slice(last, match.index));
      }
      const tokenStr = match[0];
      let cls = 'json-tok-num';
      if (/^"/.test(tokenStr)) {
        cls = /:$/.test(tokenStr) ? 'json-tok-key' : 'json-tok-str';
      } else if (/true|false/.test(tokenStr)) {
        cls = 'json-tok-bool';
      } else if (/null/.test(tokenStr)) {
        cls = 'json-tok-null';
      }
      appendJsonToken(preEl, cls, tokenStr);
      last = tokRe.lastIndex;
    }
    if (last < raw.length) {
      appendJsonToken(preEl, '', raw.slice(last));
    }
  }

  function renderBinaryMatrix(cfg) {
    const grid = document.getElementById('binaryDetectorGrid');
    if (!grid || !cfg) return;
    const bins = cfg.binaries || {};
    const ai = cfg.ai || {};
    const eng = ai.engines || {};
    const ollamaRunning = Boolean(eng.ollama?.running);
    const ollamaInstalled = Boolean(eng.ollama?.installed || ollamaRunning);
    const comfyInstalled = Boolean(eng.comfyui?.installed || eng.comfy?.installed);
    const comfyRunning = Boolean(eng.comfyui?.running || eng.comfy?.running);

    const tiles = [
      {
        name: 'yt-dlp',
        ok: Boolean(bins.yt_dlp?.installed),
        status: bins.yt_dlp?.installed ? 'Ready' : 'Missing',
        detail: bins.yt_dlp?.version ? `v${bins.yt_dlp.version}` : 'Not installed',
        aiOnly: false,
      },
      {
        name: 'FFmpeg Encoder',
        ok: Boolean(bins.ffmpeg?.installed),
        status: bins.ffmpeg?.hardware_accelerated ? 'GPU NVENC' : 'CPU / Ready',
        detail: `${bins.ffmpeg?.encoder || 'libx264'} · ${bins.ffmpeg?.display_name || 'Software'}`,
        aiOnly: false,
      },
      {
        name: 'gallery-dl',
        ok: Boolean(bins.gallery_dl?.installed),
        status: bins.gallery_dl?.installed ? 'Ready' : 'Missing',
        detail: bins.gallery_dl?.version ? `v${bins.gallery_dl.version}` : 'Carousel & photo grabber',
        aiOnly: false,
      },
      {
        name: 'Whisper ASR',
        ok: Boolean(bins.whisper?.installed),
        status: bins.whisper?.installed ? 'Installed' : 'Optional',
        detail: bins.whisper?.installed ? 'Offline lyric & speech alignment' : 'Install AI pack to enable',
        aiOnly: true,
      },
      {
        name: 'Ollama LLM',
        ok: ollamaInstalled,
        status: ollamaRunning ? 'Running' : ollamaInstalled ? 'Standby' : 'Not Set Up',
        detail: ollamaRunning ? 'Active on localhost:11434' : '0 MB VRAM until invoked',
        aiOnly: true,
      },
      {
        name: 'ComfyUI Video',
        ok: comfyInstalled,
        status: comfyRunning ? 'Running' : comfyInstalled ? 'Standby' : 'Optional',
        detail: comfyInstalled ? 'Keyframe & Wan motion backend' : '0 MB VRAM (not running)',
        aiOnly: true,
      },
    ];

    grid.replaceChildren();
    for (const item of tiles) {
      const tile = makeEl('div', `binary-tile ${item.ok ? 'is-ok' : 'is-warn'}`);
      if (item.aiOnly) tile.setAttribute('data-ai-ui', '');
      const head = makeEl('div', 'binary-tile-head');
      const nameWrap = makeEl('span', 'binary-tile-name');
      nameWrap.append(makeEl('span', 'binary-dot'), document.createTextNode(item.name));
      head.append(nameWrap, makeEl('span', 'binary-tile-status', item.status));
      tile.append(head, makeEl('div', 'binary-tile-detail', item.detail));
      grid.append(tile);
    }
  }

  function buildMergedConfigObject() {
    const zeroAi = document.documentElement?.dataset?.hideAi === 'true';
    const base = lastConfigPayload || {};
    const defaults = readPipelineDefaults();
    return {
      app: base.app || { name: 'AI Influencer Media Grabber' },
      runtime_mode: {
        zero_ai_laptop_mode: zeroAi,
        hardware_profile: base.ai?.profile || 'laptop',
        gpu_name: base.ai?.hardware?.gpu_name || 'CPU / Integrated',
        vram_allocated_gb: zeroAi ? 0 : (base.ai?.vram_guard?.allocated_gb ?? 0),
        idle_release_sec: base.ai?.vram_guard?.idle_timeout_sec ?? 300,
      },
      grabber_pipeline_defaults: defaults,
      binaries: base.binaries || {},
      ai_engines: zeroAi ? { hidden_by_laptop_mode: true } : (base.ai?.engines || {}),
    };
  }

  function renderJsonInspector() {
    const pre = document.getElementById('pipelineConfigJson');
    const modeBadge = document.getElementById('pipelineModeBadge');
    const cfg = buildMergedConfigObject();
    if (modeBadge) {
      const zeroAi = cfg.runtime_mode.zero_ai_laptop_mode;
      modeBadge.textContent = zeroAi
        ? 'Laptop Mode · 0 MB VRAM'
        : `${cfg.runtime_mode.vram_allocated_gb} GB VRAM`;
    }
    renderSyntaxJson(pre, cfg);
  }

  async function refreshPipelineConfigurator() {
    try {
      const res = await fetch('/api/pipeline/config', { headers: { 'X-Media-Token': token() } });
      if (res.ok) {
        lastConfigPayload = await res.json();
        renderBinaryMatrix(lastConfigPayload);
      }
    } catch {
      /* keep last cached payload */
    }
    renderJsonInspector();
  }

  window.refreshPipelineConfigurator = refreshPipelineConfigurator;

  function initCommandCenter() {
    syncPipelineSwitchBindings();

    document.getElementById('refreshPipelineConfigBtn')?.addEventListener('click', () => {
      refreshPipelineConfigurator().then(() => notify('Telemetry Refreshed', 'Live binaries and VRAM metrics updated.'));
    });

    document.getElementById('copyPipelineConfigBtn')?.addEventListener('click', async () => {
      const text = JSON.stringify(buildMergedConfigObject(), null, 2);
      try {
        await navigator.clipboard.writeText(text);
        notify('Copied JSON Config', 'pipeline.config.json copied to clipboard.');
      } catch {
        notify('Copy Unavailable', 'Select text inside the inspector to copy manually.');
      }
    });

    window.addEventListener('grabber:download-complete', (ev) => {
      const d = ev?.detail;
      if (d?.file_path) {
        recentCompletedItem = {
          name: d.title || d.file_path.split(/[\\/]/).pop() || 'Downloaded Clip',
          full_path: d.file_path,
          folder: d.platform || 'Downloads',
          type: 'video',
        };
      }
      refreshGrabberActionCards();
      if (window.activeGallerySection === 'lineage') loadMediaLineage(true);
    });

    window.addEventListener('grabber:gallery-loaded', () => refreshGrabberActionCards());
    window.addEventListener('zero-ai-changed', () => {
      refreshGrabberActionCards();
      renderJsonInspector();
    });
    window.addEventListener('vram-updated', () => {
      refreshPipelineConfigurator();
    });

    setTimeout(() => {
      refreshGrabberActionCards();
      refreshPipelineConfigurator();
    }, 250);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCommandCenter);
  } else {
    initCommandCenter();
  }
})();
