/* Studio Copilot drawer — a local agent that proposes real app actions.
 * Streams from /api/copilot/chat/stream (token, tool_call, tool_result, proposal, error, done).
 * Proposals change nothing until the user presses Apply, which calls the app's own endpoints.
 * When no local model is installed the drawer shows the server's message and a Set up AI button.
 */
(() => {
  'use strict';

  const token = () => document.querySelector('meta[name="media-token"]')?.content || '';
  const headers = (json = true) => ({ 'X-Media-Token': token(), ...(json ? { 'Content-Type': 'application/json' } : {}) });
  const PAGE = window.location.pathname.startsWith('/captions') ? 'captions'
    : window.location.pathname.startsWith('/video-studio') ? 'studio' : 'downloader';
  const CHIPS = {
    captions: [['Audit subtitles', 'Audit my subtitles for reading speed, timing and missing translations.'],
      ['Fix fast lines', 'Suggest shorter translations for lines that are too fast to read.'],
      ['Translate', 'Translate all lines into English.'],
      ['🎙️ Narrate', 'Audit my lines for voiceover pacing and propose generating a warm podcast narration track.']],
    downloader: [['Find media', 'Find my recent TikTok videos in the gallery.'], ['Open folder', 'Open my downloads folder.']],
    studio: [['Plan storyboard', 'Plan a storyboard for the selected song.'], ['Scene ideas', 'Suggest a look for the chorus scenes.']],
  };
  const NAV = {
    captions: '/captions', video_studio: '/video-studio', ai_setup: '/#ai-setup', downloader: '/#downloader',
    converter: '/#converter', cleaner: '/#cleaner', gallery: '/#gallery', history: '/#history', settings: '/#settings',
  };
  const state = { open: false, busy: false, model: '', helper: null, messages: [], controller: null };

  // ------------------------------------------------------------------ DOM helpers

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === undefined || value === null || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) {
      if (child !== null && child !== undefined && child !== false) node.append(child instanceof Node ? child : String(child));
    }
    return node;
  }

  function openSetup(hint) {
    if (typeof window.openAISetup === 'function') window.openAISetup(hint);
    else window.location.href = '/#ai-setup';
  }

  // ------------------------------------------------------------------ drawer

  function formatResidentModels(data) {
    const gpuMap = data?.gpu || {};
    const names = [];
    for (const [name, info] of Object.entries(gpuMap)) {
      const label = name.startsWith('ollama:') ? name.slice('ollama:'.length) : name;
      const gb = Number(info?.vram_gb || 0);
      names.push(gb > 0 ? `${label} (${gb.toFixed(1)} GB)` : label);
    }
    for (const model of Array.isArray(data?.ollama_loaded) ? data.ollama_loaded : []) {
      if (!names.some((n) => n === model || n.startsWith(`${model} (`))) names.push(model);
    }
    return names;
  }

  function updateVramBar(itemsOrNames, overrideText = '') {
    const bar = document.getElementById('copilotVramBar');
    if (!bar) return;
    if (overrideText) {
      bar.className = 'copilotVramBar idle';
      bar.replaceChildren(el('span', { class: 'copilotVramDot' }), el('span', { class: 'copilotVramText', text: overrideText }));
      return;
    }
    const labels = (itemsOrNames || []).map((item) => (typeof item === 'string' ? item : item.label || item.displayName || item.name)).filter(Boolean);
    if (labels.length) {
      bar.className = 'copilotVramBar loaded';
      bar.replaceChildren(
        el('span', { class: 'copilotVramDot' }),
        el('span', { class: 'copilotVramText', text: `Loaded in VRAM: ${labels.join(', ')} · Auto-swaps with Translator` })
      );
    } else {
      bar.className = 'copilotVramBar idle';
      bar.replaceChildren(
        el('span', { class: 'copilotVramDot' }),
        el('span', { class: 'copilotVramText', text: 'Standby · 0 MB VRAM — Loads only when you send a prompt' })
      );
    }
  }

  async function refreshCopilotVram() {
    if (document.documentElement.dataset.hideAi === 'true') return;
    try {
      const response = await fetch('/api/ai/engines', { headers: headers(false) });
      if (!response.ok) return;
      const data = await response.json();
      updateVramBar(formatResidentModels(data));
    } catch {
      /* ignore transient fetch failure */
    }
  }

  function stopStream() {
    if (state.busy && state.controller) {
      state.controller.abort();
    }
  }

  function setBusyUi(busy) {
    state.busy = busy;
    const sendBtn = document.getElementById('copilotSendBtn');
    const stopBtn = document.getElementById('copilotStopBtn');
    if (sendBtn) sendBtn.disabled = busy;
    if (stopBtn) stopBtn.hidden = !busy;
  }

  async function unloadAndFreeVram() {
    const btn = document.getElementById('copilotUnloadBtn');
    stopStream();
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Freeing…';
    }
    try {
      let result = null;
      if (typeof window.releaseGpuVram === 'function') {
        result = await window.releaseGpuVram();
      } else {
        const res = await fetch('/api/ai/gpu/release', { method: 'POST', headers: headers() });
        result = await res.json().catch(() => null);
      }
      if (result) updateVramBar(formatResidentModels(result));
      else await refreshCopilotVram();
      if (result?.freed !== false) {
        updateVramBar([], 'GPU VRAM Freed (0 MB active) — Standby');
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '⚡ Unload AI';
      }
    }
  }

  function refreshProactiveCards() {
    const mount = document.getElementById('copilotProactiveCards');
    if (!mount || typeof window.ActionCards === 'undefined') return;
    const provider = window.copilotProactiveProvider;
    const info = typeof provider === 'function' ? provider() : null;
    if (!info || !Array.isArray(info.cards) || !info.cards.length) {
      mount.replaceChildren();
      mount.hidden = true;
      return;
    }
    window.ActionCards.renderStrip(
      mount,
      info.scope || PAGE,
      info.cards,
      async (action, payload) => {
        if (typeof info.onApply === 'function') {
          const msg = await info.onApply(action, payload);
          const status = document.getElementById('copilotStatus');
          if (status && typeof msg === 'string' && msg) {
            status.replaceChildren(el('p', { class: 'copilotProposalStatus', text: `✓ ${msg}` }));
          }
          refreshProactiveCards();
        }
      },
      { headerLabel: '⚡ Smart Recommendations', maxCards: 3 }
    );
  }

  function createDrawer() {
    if (document.getElementById('copilotDrawer')) return;
    const backdrop = el('div', { id: 'copilotBackdrop', class: 'copilotBackdrop', 'aria-hidden': 'true' });
    const drawer = el('aside', { id: 'copilotDrawer', 'aria-label': 'AI Copilot' },
      el('div', { class: 'copilotHeader' },
        el('div', { class: 'copilotTitleGroup' }, el('h3', { text: 'Copilot' }),
          el('select', { id: 'copilotModelSelect', class: 'copilotModelSelect', 'aria-label': 'Helper model' })),
        el('div', { class: 'copilotHeaderActions' },
          el('button', { id: 'copilotUnloadBtn', class: 'copilotUnloadBtn', type: 'button', title: 'Stop generation and unload AI models from GPU VRAM', text: '⚡ Unload AI' }),
          el('button', { id: 'copilotCloseBtn', class: 'copilotCloseBtn', type: 'button', 'aria-label': 'Close Copilot', text: '✕ Close' }))),
      el('div', { id: 'copilotVramBar', class: 'copilotVramBar idle' }),
      el('div', { id: 'copilotStatus', class: 'copilotStatus' }),
      el('div', { id: 'copilotProactiveCards', class: 'copilot-proactive-zone', hidden: true }),
      el('div', { id: 'copilotMessages', class: 'copilotMessages', 'aria-live': 'polite' }),
      el('div', { class: 'copilotChips' }, ...(CHIPS[PAGE] || []).map(([label, prompt]) =>
        el('button', { type: 'button', class: 'copilotChip', text: label, onclick: () => submit(prompt) })),
      el('button', { type: 'button', class: 'copilotChip', text: 'What can you do?', onclick: () => submit('What can you do on this PC?') })),
      el('form', { id: 'copilotForm', class: 'copilotInputArea' },
        el('textarea', { id: 'copilotInput', rows: '1', placeholder: 'Ask or give a command…', 'aria-label': 'Message the Copilot' }),
        el('button', { id: 'copilotStopBtn', class: 'copilotStopBtn', type: 'button', hidden: true, title: 'Stop generating response', text: '⏹ Stop' }),
        el('button', { id: 'copilotSendBtn', class: 'copilotSendBtn', type: 'submit', 'aria-label': 'Send', text: '↑' })));
    document.body.append(backdrop, drawer);
    backdrop.onclick = close;
    document.getElementById('copilotCloseBtn').onclick = close;
    document.getElementById('copilotUnloadBtn').onclick = unloadAndFreeVram;
    document.getElementById('copilotStopBtn').onclick = stopStream;
    document.getElementById('copilotForm').onsubmit = (event) => { event.preventDefault(); submit(); };
    document.getElementById('copilotInput').onkeydown = (event) => {
      if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
    };
    window.addEventListener('vram-updated', (event) => {
      if (state.open) {
        updateVramBar(event.detail?.items || []);
        refreshProactiveCards();
      }
    });
    window.addEventListener('zero-ai-changed', () => { if (state.open) refreshProactiveCards(); });
    window.addEventListener('grabber:download-complete', () => { if (state.open) refreshProactiveCards(); });
    window.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        if (document.documentElement.dataset.hideAi === 'true') return;
        event.preventDefault();
        toggle();
      } else if (event.key === 'Escape' && state.open) {
        close();
      }
    });
    updateVramBar([]);
    render();
  }

  function toggle() {
    state.open = !state.open;
    document.getElementById('copilotDrawer')?.classList.toggle('open', state.open);
    document.getElementById('copilotBackdrop')?.classList.toggle('open', state.open);
    if (state.open) {
      refreshProactiveCards();
      loadModels();
      refreshCopilotVram();
      setTimeout(() => document.getElementById('copilotInput')?.focus(), 150);
    }
  }

  function close() {
    state.open = false;
    document.getElementById('copilotDrawer')?.classList.remove('open');
    document.getElementById('copilotBackdrop')?.classList.remove('open');
  }

  async function loadModels() {
    const select = document.getElementById('copilotModelSelect');
    const status = document.getElementById('copilotStatus');
    try {
      const response = await fetch('/api/copilot/models', { headers: headers(false) });
      const data = await response.json();
      state.helper = data.helper;
      const auto = data.helper?.available ? `Automatic (${data.helper.model})` : 'No helper model installed';
      select.replaceChildren(el('option', { value: '', text: auto }),
        ...(data.models || []).map((m) => el('option', { value: m.name, text: `${m.name} · ${m.backend === 'builtin' ? 'built-in CPU' : 'Ollama'}` })));
      select.value = (data.models || []).some((m) => m.name === state.model) ? state.model : '';
      select.onchange = () => { state.model = select.value; };
      status.replaceChildren(data.helper?.available ? '' : setupNotice(data.helper?.error || 'No local helper model is installed.', data.helper?.setup_hint));
    } catch (error) {
      status.replaceChildren(el('p', { class: 'copilotError', text: `Could not reach the app: ${error.message}` }));
    }
  }

  function setupNotice(message, hint) {
    return el('div', { class: 'copilotSetup' }, el('p', { text: message }),
      el('button', { type: 'button', class: 'copilotActionBtn', text: 'Set up AI', onclick: () => openSetup(hint) }));
  }

  // ------------------------------------------------------------------ context

  function context() {
    const unsaved = Boolean(window.copilotHasUnsavedChanges?.());
    if (typeof window.copilotContext === 'function') return { ...window.copilotContext(), unsaved };
    if (PAGE === 'downloader') {
      // downloadQueue is a page-level const in index.html when the downloader is loaded.
      const queue = typeof downloadQueue !== 'undefined' && Array.isArray(downloadQueue) ? downloadQueue : []; // eslint-disable-line no-undef
      return { page: 'downloader', unsaved, queue: queue.slice(0, 20).map((task) => ({
        url: task.payload?.url || task.url, status: task.status, title: task.title })) };
    }
    return { page: PAGE, unsaved };
  }

  // ------------------------------------------------------------------ rendering

  function render() {
    const container = document.getElementById('copilotMessages');
    if (!container) return;
    if (!state.messages.length) {
      container.replaceChildren(el('div', { class: 'copilotMsg assistant' }, el('p', {
        text: 'Hi! I run on a local model and can audit captions, search your library and prepare actions. Nothing changes until you press Apply.' })));
      return;
    }
    container.replaceChildren(...state.messages.map(renderMessage));
    container.scrollTop = container.scrollHeight;
  }

  function renderMessage(message) {
    const node = el('div', { class: `copilotMsg ${message.role}` });
    if (message.tools?.length) {
      node.append(el('div', { class: 'copilotTools' }, ...message.tools.map((tool) =>
        el('span', { class: `copilotTool ${tool.state}`, text: `${tool.state === 'running' ? '…' : tool.state === 'error' ? '⚠' : '✓'} ${tool.name.replace(/_/g, ' ')}` }))));
    }
    if (message.content) node.append(el('p', { class: 'copilotText', text: message.content }));
    for (const proposal of message.proposals || []) node.append(proposalCard(proposal));
    if (message.error) {
      node.append(el('p', { class: 'copilotError', text: message.error }));
      if (message.setup_hint) node.append(setupNotice('This needs a model or engine that is not set up on this PC.', message.setup_hint));
    }
    if (message.model) node.append(el('small', { class: 'copilotModel', text: `${message.model} · local` }));
    return node;
  }

  function proposalCard(proposal) {
    const status = el('p', { class: 'copilotProposalStatus', text: proposal.status || '' });
    const apply = el('button', { type: 'button', class: 'copilotActionBtn', text: 'Apply', disabled: Boolean(proposal.done) });
    const dismiss = el('button', { type: 'button', class: 'copilotActionBtn secondary', text: 'Dismiss', disabled: Boolean(proposal.done) });
    apply.onclick = async () => {
      apply.disabled = dismiss.disabled = true;
      status.textContent = 'Applying…';
      try {
        const message = await applyProposal(proposal);
        proposal.done = true;
        proposal.status = message || 'Applied.';
      } catch (error) {
        proposal.status = error.message;
        apply.disabled = dismiss.disabled = false;
      }
      status.textContent = proposal.status;
    };
    dismiss.onclick = () => { proposal.done = true; proposal.status = 'Dismissed.'; render(); };
    const diff = Array.isArray(proposal.diff) && proposal.diff.length ? el('table', { class: 'copilotDiff' },
      ...proposal.diff.slice(0, 40).map((row) => el('tr', {},
        el('th', { text: `Line ${row.line}${row.field ? ` · ${row.field}` : ''}` }),
        el('td', {}, el('del', { text: row.before || '—' }), el('ins', { text: row.after }))))) : null;
    return el('div', { class: 'copilotActionCard proposal' },
      el('div', { class: 'actionTitle' }, el('span', { text: proposal.action.replace(/_/g, ' ') }),
        el('span', { class: `copilotBadge ${proposal.local === false ? 'cloud' : ''}`, text: proposal.badge || (proposal.local === false ? 'Cloud' : 'Local') }),
        proposal.eta_seconds ? el('span', { class: 'copilotBadge', text: `~${Math.max(1, Math.round(proposal.eta_seconds / 60))} min` }) : null),
      el('div', { class: 'actionBody', text: proposal.summary }), diff,
      el('div', { class: 'copilotBtnGroup' }, apply, dismiss), status);
  }

  // ------------------------------------------------------------------ apply proposals

  async function applyProposal({ action, args }) {
    const pageAction = window.copilotActions?.[action];
    if (typeof pageAction === 'function') {
      const result = await pageAction(args || {});
      if (result === false) throw new Error('The page could not apply this. Open the right project and try again.');
      return typeof result === 'string' ? result : 'Applied.';
    }
    if (action === 'navigate') {
      if (window.copilotHasUnsavedChanges?.()) throw new Error('Save your edits first; the Copilot never leaves a page with unsaved changes.');
      const target = NAV[args.target];
      if (!target) throw new Error('Unknown destination.');
      if (args.target === 'ai_setup') openSetup();
      else window.location.href = target;
      return 'Opening…';
    }
    if (action === 'open_in_explorer') {
      const response = await fetch('/api/open_folder', { method: 'POST', headers: headers(), body: JSON.stringify({ path: args.path || '' }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Could not open the folder.');
      return 'Opened in File Explorer.';
    }
    if (action === 'download_url') return startDownload(args);
    const where = ['generate_storyboard', 'generate_keyframe', 'animate_keyframe', 'face_swap', 'lip_sync'].includes(action) ? 'AI Studio' : 'Captions';
    throw new Error(`Open ${where} to apply this action.`);
  }

  async function startDownload(args) {
    const response = await fetch('/api/download', {
      method: 'POST', headers: headers(),
      body: JSON.stringify({ url: args.url, processing_options: { quality: args.format === 'audio' ? 'audio_only' : 'max' } }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `Download failed (HTTP ${response.status}).`);
    }
    const reader = response.body?.getReader();
    let last = '';
    if (reader) {
      const decoder = new TextDecoder();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        last = (last + decoder.decode(value, { stream: true })).slice(-4000);
      }
    }
    return /error/i.test(last.slice(-600)) ? 'The download reported an error — check the downloader log.' : 'Download finished. It is in your gallery.';
  }

  // ------------------------------------------------------------------ chat

  function parseEvents(buffer, onEvent) {
    const blocks = buffer.split('\n\n');
    const rest = blocks.pop();
    for (const block of blocks) {
      const lines = block.split('\n');
      const event = lines.find((l) => l.startsWith('event: '))?.slice(7);
      const data = lines.filter((l) => l.startsWith('data: ')).map((l) => l.slice(6)).join('\n');
      if (event) {
        try { onEvent(event, JSON.parse(data || '{}')); } catch (_) { onEvent('error', { error: 'The Copilot sent an unreadable update.' }); }
      }
    }
    return rest;
  }

  async function submit(text) {
    const input = document.getElementById('copilotInput');
    const content = (text ?? input.value).trim();
    if (!content || state.busy) return;
    if (!state.open) toggle();
    input.value = '';
    state.messages.push({ role: 'user', content });
    const reply = { role: 'assistant', content: '', tools: [], proposals: [] };
    state.messages.push(reply);
    setBusyUi(true);
    render();
    const history = state.messages.filter((m) => m !== reply && (m.role === 'user' || (m.role === 'assistant' && m.content)))
      .map((m) => ({ role: m.role, content: m.content }));
    state.controller = new AbortController();
    try {
      const response = await fetch('/api/copilot/chat/stream', {
        method: 'POST', headers: headers(), signal: state.controller.signal,
        body: JSON.stringify({ messages: history, context: context(), model: state.model || undefined }),
      });
      if (!response.ok || !response.body) {
        const data = await response.json().catch(() => ({}));
        throw Object.assign(new Error(data.error || `The Copilot request failed (HTTP ${response.status}).`), { setup_hint: data.setup_hint });
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer = parseEvents(buffer + decoder.decode(value, { stream: true }), (event, data) => handleEvent(reply, event, data));
        render();
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        if (!reply.content) reply.content = 'Generation stopped.';
      } else {
        reply.error = error.message;  // shown verbatim; never replaced by canned text
        reply.setup_hint = error.setup_hint;
      }
    } finally {
      state.controller = null;
      setBusyUi(false);
      render();
      setTimeout(() => { window.refreshVramGuard?.(); refreshCopilotVram(); }, 600);
    }
  }

  function handleEvent(reply, event, data) {
    if (event === 'token') reply.content += data.text || '';
    else if (event === 'tool_call') {
      reply.content = '';  // text before a tool call is a preamble; the final answer follows
      reply.tools.push({ name: data.name, state: 'running' });
    } else if (event === 'tool_result' || event === 'proposal') {
      const name = event === 'proposal' ? data.action : data.name;
      const tool = [...reply.tools].reverse().find((t) => t.name === name && t.state === 'running');
      if (tool) tool.state = event === 'proposal' || data.ok ? 'done' : 'error';
      if (event === 'proposal') {
        reply.proposals = reply.proposals.filter((p) => p.action !== data.action);
        reply.proposals.push(data);
      }
    } else if (event === 'error') {
      reply.error = data.error;
      reply.setup_hint = data.setup_hint;
    } else if (event === 'done') {
      reply.content = data.reply || reply.content;
      reply.model = data.model;
      if (!reply.content && reply.proposals.length) reply.content = 'Review the proposal below. Nothing changes until you press Apply.';
    }
  }

  window.copilot = {
    open: () => { if (document.documentElement.dataset.hideAi === 'true') return; if (!state.open) toggle(); },
    close,
    toggle: () => { if (document.documentElement.dataset.hideAi === 'true') return; toggle(); },
    ask: submit,
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', createDrawer);
  else createDrawer();
})();
