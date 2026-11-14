/* Deterministic Proactive Action Cards (0 MB GPU VRAM, 0 LLM calls).
 * Computes contextual, high-value next actions from live editor or grabber state
 * and renders non-intrusive Apply / Skip cards with plain-English reasoning.
 */
(function (root) {
  'use strict';

  const STORAGE_KEY = 'agy.skippedActionCards.v1';

  function readSkippedSet() {
    if (typeof sessionStorage === 'undefined') return new Set();
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      const list = raw ? JSON.parse(raw) : [];
      return new Set(Array.isArray(list) ? list : []);
    } catch {
      return new Set();
    }
  }

  function writeSkippedSet(set) {
    if (typeof sessionStorage === 'undefined') return;
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...set].slice(-120)));
    } catch {
      /* ignore quota failures */
    }
  }

  function dismissKey(scope, card) {
    return `${scope}:${card.id}:${card.targetKey || ''}`;
  }

  function skipCard(scope, card) {
    const skipped = readSkippedSet();
    skipped.add(dismissKey(scope, card));
    writeSkippedSet(skipped);
  }

  function filterSkipped(scope, cards, includeSkipped = false) {
    if (includeSkipped) return cards;
    const skipped = readSkippedSet();
    return cards.filter((c) => !skipped.has(dismissKey(scope, c)));
  }

  /**
   * Compute proactive recommendations for Creator Studio (/captions).
   * Pure deterministic heuristics — uses 0 MB GPU VRAM.
   */
  function computeStudioCards(ctx = {}) {
    const project = ctx.project;
    if (!project) return [];
    const duration = Number(project.duration) || 0;
    const cues = Array.isArray(project.cues) ? project.cues : [];
    const zeroAi = Boolean(ctx.zeroAi);
    const hasMusic = Boolean(project.studio?.assets?.music || ctx.hasPendingMusic);
    const targetKey = `${project.id || 'p'}:${project.revision ?? 0}`;
    const cards = [];

    if (duration > 0.5 && cues.length === 0) {
      const card = {
        id: 'uncaptioned-clip',
        targetKey,
        tone: 'emerald',
        badge: '0 MB · Ready',
        icon: '💬',
        title: 'Clip has no captions yet',
        why: 'Import lyrics/SRT instantly with 0 VRAM, or run speech transcription.',
        applyAction: 'paste-lyrics',
        applyLabel: '📄 Paste / Import',
        requiresAi: false,
      };
      if (!zeroAi) {
        card.secondaryAction = 'auto-transcribe';
        card.secondaryLabel = '🎙️ Auto-Transcribe';
      }
      cards.push(card);
    }

    if (cues.length > 0) {
      let fastCount = 0;
      let maxCps = 0;
      let issueCount = 0;
      let pendingTrCount = 0;
      const sorted = [...cues].sort((a, b) => Number(a.start) - Number(b.start));

      for (let i = 0; i < sorted.length; i += 1) {
        const cur = sorted[i];
        const dur = Math.max(0.15, Number(cur.end) - Number(cur.start));
        const textLen = String(cur.text || '').trim().length;
        if (textLen > 0) {
          const cps = textLen / dur;
          if (cps > 22) {
            fastCount += 1;
            if (cps > maxCps) maxCps = cps;
          }
        }
        if (i + 1 < sorted.length) {
          const nxt = sorted[i + 1];
          const gap = Number(nxt.start) - Number(cur.end);
          if (gap < -0.005 || (gap >= 0.04 && gap <= 0.35)) {
            issueCount += 1;
          }
        }
        for (const tr of Object.values(cur.translations || {})) {
          if (tr && (tr.status === 'review' || tr.status === 'draft' || tr.status === 'needs_review' || tr.status === 'stale')) {
            pendingTrCount += 1;
          }
        }
      }

      if (fastCount > 0) {
        cards.push({
          id: 'fast-cps',
          targetKey,
          tone: 'amber',
          badge: `Timing · ${Math.round(maxCps)} CPS`,
          icon: '🔥',
          title: `Reflow ${fastCount} fast caption line${fastCount === 1 ? '' : 's'} (${maxCps.toFixed(1)} CPS)`,
          why: 'Viewers read comfortably up to ~20 chars/s. Splitting into 2–3 word punchy cues boosts retention.',
          applyAction: 'reflow-punchy',
          applyLabel: '🔥 Reflow 2–3w',
          requiresAi: false,
        });
      }

      if (issueCount > 0) {
        cards.push({
          id: 'micro-gaps',
          targetKey,
          tone: 'amber',
          badge: 'Sync · Gaps',
          icon: '🧲',
          title: `Smooth ${issueCount} micro-gap${issueCount === 1 ? '' : 's'} / overlap${issueCount === 1 ? '' : 's'}`,
          why: 'Tiny 40–350ms gaps make subtitles flash between phrases. Smooth Gaps locks clean continuity.',
          applyAction: 'smooth-gaps',
          applyLabel: '🧲 Smooth Gaps',
          requiresAi: false,
        });
      }

      if (pendingTrCount > 0) {
        cards.push({
          id: 'pending-translations',
          targetKey,
          tone: 'violet',
          badge: 'Translation',
          icon: '🌐',
          title: `Review ${pendingTrCount} translated line${pendingTrCount === 1 ? '' : 's'}`,
          why: 'Draft or stale translations stay dimmed until reviewed before burning into final export.',
          applyAction: 'review-translations',
          applyLabel: '🌐 Review',
          requiresAi: false,
        });
      }
    }

    if (duration >= 3 && !hasMusic) {
      cards.push({
        id: 'add-bg-music',
        targetKey: `${project.id || 'p'}`,
        tone: 'emerald',
        badge: 'Multi-Audio',
        icon: '🎵',
        title: 'Layer a background MP3 track',
        why: 'Add an MP3 or song with auto-ducking and instant live browser audition before FFmpeg renders.',
        applyAction: 'open-audio-mixer',
        applyLabel: '🎵 Open Mixer',
        requiresAi: false,
      });
    }

    return cards;
  }

  /**
   * Compute proactive next steps for Downloader & Gallery (/).
   * Uses 0 MB GPU VRAM.
   */
  function computeGrabberCards(ctx = {}) {
    const items = Array.isArray(ctx.recentVideos) ? ctx.recentVideos.filter((v) => v && v.full_path) : [];
    if (!items.length) return [];
    const latest = items[0];
    const targetKey = latest.full_path;
    const cards = [];

    cards.push({
      id: 'caption-latest',
      targetKey,
      tone: 'emerald',
      badge: 'Creator Studio',
      icon: '🎬',
      title: `Caption & mix "${latest.name || 'Clip'}"`,
      why: 'Open directly in Creator Studio for 2–3w karaoke captions and multi-track MP3 mixing.',
      applyAction: 'open-in-captions',
      applyLabel: '🎬 Open in Studio',
      payload: { path: latest.full_path, name: latest.name },
      requiresAi: false,
    });

    if (latest.folder !== 'Conversions') {
      cards.push({
        id: 'reframe-vertical',
        targetKey,
        tone: 'amber',
        badge: '9:16 Reframe',
        icon: '📱',
        title: `Reframe "${latest.name || 'Clip'}" to 9:16 Vertical`,
        why: 'Load into Offline Media Tools with 9:16 crop & CPU face-tracking pre-selected (0 MB VRAM).',
        applyAction: 'reframe-9-16',
        applyLabel: '📱 Prep 9:16',
        payload: { path: latest.full_path, name: latest.name },
        requiresAi: false,
      });
    }

    cards.push({
      id: 'trace-lineage',
      targetKey,
      tone: 'violet',
      badge: 'Pipeline Map',
      icon: '🧬',
      title: 'Inspect Media Lineage Graph',
      why: 'Trace Source URL → Raw Download → Extracted Assets → Studio Exports in one visual map.',
      applyAction: 'open-lineage',
      applyLabel: '🧬 View Map',
      payload: { path: latest.full_path, name: latest.name },
      requiresAi: false,
    });

    return cards;
  }

  function makeEl(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  /**
   * Render proactive action cards safely via DOM APIs (no HTML string interpolation).
   */
  function renderStrip(container, scope, cards, onApply, opts = {}) {
    if (!container) return [];
    const visible = filterSkipped(scope, cards || [], Boolean(opts.includeSkipped)).slice(0, opts.maxCards || 4);
    container.replaceChildren();
    if (!visible.length) {
      container.hidden = true;
      container.classList?.toggle('hidden', true);
      return [];
    }

    container.hidden = false;
    container.classList?.toggle('hidden', false);

    if (opts.headerLabel) {
      const head = makeEl('div', 'proactive-strip-header');
      head.append(makeEl('span', 'proactive-strip-title', opts.headerLabel));
      head.append(makeEl('span', 'proactive-strip-meta', '0 MB VRAM'));
      container.append(head);
    }

    const list = makeEl('div', 'proactive-cards-list');
    for (const card of visible) {
      const el = makeEl('div', 'proactive-card');
      el.setAttribute('data-tone', card.tone || 'emerald');
      el.setAttribute('data-card-id', card.id);

      const top = makeEl('div', 'proactive-card-head');
      const titleWrap = makeEl('div', 'proactive-card-title-wrap');
      if (card.icon) titleWrap.append(makeEl('span', 'proactive-card-icon', card.icon));
      titleWrap.append(makeEl('span', 'proactive-card-title', card.title));
      top.append(titleWrap);
      if (card.badge) top.append(makeEl('span', 'proactive-card-badge', card.badge));
      el.append(top);

      if (card.why) {
        el.append(makeEl('p', 'proactive-card-why', card.why));
      }

      const actions = makeEl('div', 'proactive-card-actions');
      const skipBtn = makeEl('button', 'proactive-btn-skip', 'Skip');
      skipBtn.type = 'button';
      skipBtn.onclick = (e) => {
        e.stopPropagation();
        skipCard(scope, card);
        renderStrip(container, scope, cards, onApply, opts);
      };

      const applyBtn = makeEl('button', 'proactive-btn-apply', card.applyLabel || 'Apply');
      applyBtn.type = 'button';
      applyBtn.onclick = async (e) => {
        e.stopPropagation();
        if (typeof onApply !== 'function') return;
        applyBtn.disabled = true;
        try {
          await onApply(card.applyAction, card.payload || {}, card);
          if (opts.onApplied) opts.onApplied(card);
        } finally {
          applyBtn.disabled = false;
        }
      };

      actions.append(skipBtn, applyBtn);

      if (card.secondaryAction && card.secondaryLabel) {
        const secBtn = makeEl('button', 'proactive-btn-secondary', card.secondaryLabel);
        secBtn.type = 'button';
        secBtn.onclick = async (e) => {
          e.stopPropagation();
          if (typeof onApply !== 'function') return;
          secBtn.disabled = true;
          try {
            await onApply(card.secondaryAction, card.payload || {}, card);
          } finally {
            secBtn.disabled = false;
          }
        };
        actions.append(secBtn);
      }

      el.append(actions);
      list.append(el);
    }
    container.append(list);
    return visible;
  }

  const api = {
    computeStudioCards,
    computeGrabberCards,
    skipCard,
    filterSkipped,
    renderStrip,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ActionCards = api;
  }
})(typeof window !== 'undefined' ? window : globalThis);
