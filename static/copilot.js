/* AI Influencer Studio Copilot - Client Controller */
(function() {
  'use strict';

  function getToken() {
    const meta = document.querySelector('meta[name="media-token"]');
    return meta ? meta.content : '';
  }

  const state = {
    open: false,
    model: '',
    messages: [
      {
        role: 'assistant',
        content: '👋 Hi! I am your AI Influencer Studio Copilot. How can I help with your video, character prompts, captions, or social media today?'
      }
    ]
  };

  function createDrawerHTML() {
    if (document.getElementById('copilotDrawer')) return;

    // Trigger Pill
    const trigger = document.createElement('div');
    trigger.id = 'copilotTrigger';
    trigger.setAttribute('role', 'button');
    trigger.setAttribute('tabindex', '0');
    trigger.setAttribute('aria-label', 'Open AI Copilot');
    trigger.innerHTML = `
      <span>✨ AI Copilot</span>
      <span class="badge">Ctrl+K</span>
    `;
    document.body.appendChild(trigger);

    // Slide-over Drawer
    const drawer = document.createElement('aside');
    drawer.id = 'copilotDrawer';
    drawer.setAttribute('aria-label', 'AI Copilot Assistant');
    drawer.innerHTML = `
      <div class="copilotHeader">
        <div class="copilotTitleGroup">
          <span>✨</span>
          <h3>Studio Copilot</h3>
          <select id="copilotModelSelect" class="copilotModelSelect" aria-label="Select AI Model"></select>
        </div>
        <button id="copilotCloseBtn" class="copilotCloseBtn" aria-label="Close Copilot">✕</button>
      </div>

      <div id="copilotMessages" class="copilotMessages"></div>

      <div class="copilotChips">
        <button class="copilotChip" data-prompt="Apply the Cyberpunk neon style preset to my captions">🌆 Cyberpunk Style</button>
        <button class="copilotChip" data-prompt="Apply the Beast Pop bold yellow style preset">⚡ Beast Pop</button>
        <button class="copilotChip" data-prompt="Generate 3 viral TikTok hook titles, caption, and hashtags">📱 Viral Post</button>
        <button class="copilotChip" data-prompt="Write a Google Flow Nano Banana prompt for @Airi in a dim recording booth">🎬 Flow Prompt @Airi</button>
        <button class="copilotChip" data-prompt="Shift all captions 0.25 seconds forward">⏩ Shift +0.25s</button>
      </div>

      <form id="copilotForm" class="copilotInputArea">
        <textarea id="copilotInput" rows="1" placeholder="Ask Copilot or give a command (Ctrl+K)…" aria-label="Copilot input"></textarea>
        <button id="copilotSendBtn" class="copilotSendBtn" type="submit" aria-label="Send message">↑</button>
      </form>
    `;
    document.body.appendChild(drawer);

    // Bind Events
    trigger.onclick = toggleDrawer;
    document.getElementById('copilotCloseBtn').onclick = closeDrawer;

    document.getElementById('copilotForm').onsubmit = (e) => {
      e.preventDefault();
      submitMessage();
    };

    document.getElementById('copilotInput').onkeydown = (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitMessage();
      }
    };

    document.querySelectorAll('.copilotChip').forEach(chip => {
      chip.onclick = () => {
        const p = chip.dataset.prompt;
        if (p) {
          document.getElementById('copilotInput').value = p;
          submitMessage();
        }
      };
    });

    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        toggleDrawer();
      } else if (e.key === 'Escape' && state.open) {
        closeDrawer();
      }
    });

    renderMessages();
    loadModels();
  }

  function toggleDrawer() {
    state.open = !state.open;
    const d = document.getElementById('copilotDrawer');
    if (d) d.classList.toggle('open', state.open);
    if (state.open) {
      setTimeout(() => document.getElementById('copilotInput')?.focus(), 150);
    }
  }

  function closeDrawer() {
    state.open = false;
    const d = document.getElementById('copilotDrawer');
    if (d) d.classList.remove('open');
  }

  async function loadModels() {
    try {
      const res = await fetch('/api/copilot/models', {
        headers: { 'X-Media-Token': getToken() }
      });
      if (!res.ok) return;
      const data = await res.json();
      const select = document.getElementById('copilotModelSelect');
      if (!select || !data.models) return;
      select.replaceChildren(
        ...data.models.map(m => {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = m.name;
          return opt;
        })
      );
      if (data.models.length) {
        state.model = data.models[0].id;
        select.value = state.model;
      }
      select.onchange = () => { state.model = select.value; };
    } catch (_) {}
  }

  function renderMessages() {
    const container = document.getElementById('copilotMessages');
    if (!container) return;
    container.replaceChildren();

    state.messages.forEach(msg => {
      const el = document.createElement('div');
      el.className = `copilotMsg ${msg.role}`;
      const textP = document.createElement('p');
      textP.textContent = msg.content;
      el.appendChild(textP);

      if (msg.actions && msg.actions.length) {
        msg.actions.forEach(act => {
          const card = document.createElement('div');
          card.className = 'copilotActionCard';

          if (act.action === 'apply_style_preset') {
            card.innerHTML = `
              <div class="actionTitle">🎨 Style Preset: ${act.preset}</div>
              <div class="actionBody">${act.message}</div>
              <button class="copilotActionBtn" type="button">✓ Apply to Project</button>
            `;
            card.querySelector('button').onclick = () => {
              if (window.applyPresetByName) {
                window.applyPresetByName(act.preset);
              } else {
                const btn = document.querySelector(`[data-preset="${act.preset}"]`);
                if (btn) btn.click();
              }
            };
          } else if (act.action === 'social_metadata') {
            card.innerHTML = `
              <div class="actionTitle">📱 Social Media Hooks & Captions</div>
              <div class="actionBody">
                <strong>Hooks:</strong><br>• ${act.title_hooks.join('<br>• ')}<br><br>
                <strong>Caption & Tags:</strong><br>${act.caption.replace(/\n/g, '<br>')}
              </div>
              <button class="copilotActionBtn" type="button">📋 Copy to Clipboard</button>
            `;
            card.querySelector('button').onclick = () => {
              const fullText = `${act.title_hooks[0]}\n\n${act.caption}`;
              navigator.clipboard.writeText(fullText);
              card.querySelector('button').textContent = '✓ Copied!';
            };
          } else if (act.action === 'flow_prompt') {
            card.innerHTML = `
              <div class="actionTitle">🎬 Google Flow Prompt (${act.character})</div>
              <div class="actionBody">${act.prompt}</div>
              <button class="copilotActionBtn" type="button">📋 Copy Prompt</button>
            `;
            card.querySelector('button').onclick = () => {
              navigator.clipboard.writeText(act.prompt);
              card.querySelector('button').textContent = '✓ Copied for Flow!';
            };
          } else if (act.action === 'shift_caption_timing') {
            card.innerHTML = `
              <div class="actionTitle">⏱️ Timing Adjustment</div>
              <div class="actionBody">${act.message}</div>
              <button class="copilotActionBtn" type="button">✓ Shift Timing</button>
            `;
            card.querySelector('button').onclick = () => {
              const shiftInput = document.getElementById('shift');
              const shiftBtn = document.getElementById('shiftAll');
              if (shiftInput && shiftBtn) {
                shiftInput.value = act.seconds;
                shiftBtn.click();
              }
            };
          }

          el.appendChild(card);
        });
      }

      container.appendChild(el);
    });

    container.scrollTop = container.scrollHeight;
  }

  async function submitMessage() {
    const input = document.getElementById('copilotInput');
    const sendBtn = document.getElementById('copilotSendBtn');
    if (!input || !input.value.trim()) return;

    const text = input.value.trim();
    input.value = '';
    state.messages.push({ role: 'user', content: text });
    renderMessages();

    // Disable input while generating
    input.disabled = true;
    if (sendBtn) sendBtn.disabled = true;

    try {
      // Gather active project context if available
      let projData = null;
      if (window.currentProjectData) {
        projData = window.currentProjectData();
      }

      const res = await fetch('/api/copilot/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Media-Token': getToken()
        },
        body: JSON.stringify({
          messages: state.messages.map(m => ({ role: m.role, content: m.content })),
          model: state.model || 'qwen2.5:14b',
          project: projData
        })
      });

      if (!res.ok) throw new Error('Copilot response error');
      const data = await res.json();

      state.messages.push({
        role: 'assistant',
        content: data.reply || 'Action completed.',
        actions: data.actions || []
      });

      // Auto-execute style preset if in Studio
      if (data.actions) {
        data.actions.forEach(a => {
          if (a.action === 'apply_style_preset') {
            const btn = document.querySelector(`[data-preset="${a.preset}"]`);
            if (btn) btn.click();
          }
        });
      }

    } catch (err) {
      state.messages.push({
        role: 'assistant',
        content: '⚠️ Could not connect to local AI Copilot. Ensure Ollama or local engine is running.'
      });
    } finally {
      input.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
      renderMessages();
      input.focus();
    }
  }

  // Auto-init on page load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createDrawerHTML);
  } else {
    createDrawerHTML();
  }
})();
