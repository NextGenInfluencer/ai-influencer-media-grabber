/* AI Influencer Studio Copilot - Client Controller */
(function() {
  'use strict';

  function getToken() {
    const meta = document.querySelector('meta[name="media-token"]');
    return meta ? meta.content : '';
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function executeAppNavigation(target) {
    if (window.switchTab) {
      if (target === 'gallery_studio') {
        window.switchTab('gallery');
        if (window.switchGallerySection) window.switchGallerySection('studio');
        return true;
      }
      if (target === 'gallery_downloads') {
        window.switchTab('gallery');
        if (window.switchGallerySection) window.switchGallerySection('downloads');
        return true;
      }
      if (['downloader', 'converter', 'cleaner', 'gallery', 'history'].includes(target)) {
        window.switchTab(target);
        return true;
      }
    }
    if (target === 'captions') {
      if (!window.location.pathname.includes('/captions')) {
        window.location.href = '/captions';
      }
      return true;
    }
    if (target === 'video_studio') {
      if (!window.location.pathname.includes('/video-studio')) {
        window.location.href = '/video-studio';
      }
      return true;
    }
    if (target.startsWith('gallery') || ['downloader', 'converter', 'cleaner', 'history'].includes(target)) {
      if (window.location.pathname.includes('/captions') || window.location.pathname.includes('/video-studio')) {
        window.location.href = '/#' + target;
        return true;
      }
    }
    return false;
  }

  const state = {
    open: false,
    model: '',
    messages: [
      {
        role: 'assistant',
        content: '👋 Hi! I am your AI Influencer Studio Copilot. I can edit & fix subtitle translations, apply pro styling presets, create Wan 2.1 video prompts, manage your downloads, and answer anything about the app.'
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
        <button class="copilotChip" data-prompt="What can you do on this app?">⚡ Capabilities</button>
        <button class="copilotChip" data-prompt="Audit my subtitles for reading speed and issues">🔍 Audit Subtitles</button>
        <button class="copilotChip" data-prompt="Make line 1 translation poetic and soulful">📝 Poetic Line 1</button>
        <button class="copilotChip" data-prompt="Apply the Cyberpunk neon style preset to my captions">🌆 Cyberpunk Preset</button>
        <button class="copilotChip" data-prompt="Apply the Beast Pop bold yellow style preset">⚡ Beast Pop</button>
        <button class="copilotChip" data-prompt="Show AI Studio pictures and videos">🎬 AI Studio Assets</button>
        <button class="copilotChip" data-prompt="Open downloads folder in Explorer">📂 Open Folder</button>
        <button class="copilotChip" data-prompt="Generate 3 viral TikTok hook titles, caption, and hashtags">📱 Viral Post</button>
        <button class="copilotChip" data-prompt="Write a Wan 2.1 prompt for @Airi in a dim neon recording booth">🎬 Flow Prompt @Airi</button>
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
      textP.style.whiteSpace = 'pre-wrap';
      textP.textContent = msg.content;
      el.appendChild(textP);

      if (msg.actions && msg.actions.length) {
        msg.actions.forEach(act => {
          const card = document.createElement('div');
          card.className = 'copilotActionCard';

          if (act.action === 'apply_style_preset') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.textContent = `🎨 Style Preset: ${act.preset || ''}`;

            const body = document.createElement('div');
            body.className = 'actionBody';
            body.textContent = act.message || '';

            const btn = document.createElement('button');
            btn.className = 'copilotActionBtn';
            btn.type = 'button';
            btn.textContent = '✓ Apply to Project';
            btn.onclick = () => {
              if (window.applyPresetByName) {
                window.applyPresetByName(act.preset);
              } else {
                const b = document.querySelector(`[data-preset="${act.preset}"]`);
                if (b) b.click();
              }
            };
            card.append(title, body, btn);

          } else if (act.action === 'social_metadata') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.textContent = '📱 Social Media Hooks & Captions';

            const body = document.createElement('div');
            body.className = 'actionBody';

            const hooksLabel = document.createElement('strong');
            hooksLabel.textContent = 'Hooks:';
            body.appendChild(hooksLabel);

            (act.title_hooks || []).forEach(h => {
              const hookLine = document.createElement('div');
              hookLine.textContent = `• ${h}`;
              body.appendChild(hookLine);
            });

            const spacer = document.createElement('div');
            spacer.style.height = '8px';
            body.appendChild(spacer);

            const captionLabel = document.createElement('strong');
            captionLabel.textContent = 'Caption & Tags:';
            body.appendChild(captionLabel);

            const captionText = document.createElement('div');
            captionText.style.whiteSpace = 'pre-wrap';
            captionText.textContent = act.caption || '';
            body.appendChild(captionText);

            const btn = document.createElement('button');
            btn.className = 'copilotActionBtn';
            btn.type = 'button';
            btn.textContent = '📋 Copy to Clipboard';
            btn.onclick = () => {
              const hook = (act.title_hooks && act.title_hooks[0]) ? act.title_hooks[0] + '\n\n' : '';
              const fullText = `${hook}${act.caption || ''}`;
              navigator.clipboard.writeText(fullText);
              btn.textContent = '✓ Copied!';
            };
            card.append(title, body, btn);

          } else if (act.action === 'flow_prompt') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.textContent = `🎬 Wan 2.1 / Flow Prompt (${act.character || 'Persona'})`;

            const body = document.createElement('div');
            body.className = 'actionBody';
            body.style.whiteSpace = 'pre-wrap';
            body.textContent = act.prompt || '';

            const btn = document.createElement('button');
            btn.className = 'copilotActionBtn';
            btn.type = 'button';
            btn.textContent = '📋 Copy Prompt';
            btn.onclick = () => {
              navigator.clipboard.writeText(act.prompt || '');
              btn.textContent = '✓ Copied for Studio!';
            };
            card.append(title, body, btn);

          } else if (act.action === 'shift_caption_timing') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.textContent = '⏱️ Timing Adjustment';

            const body = document.createElement('div');
            body.className = 'actionBody';
            body.textContent = act.message || '';

            const btn = document.createElement('button');
            btn.className = 'copilotActionBtn';
            btn.type = 'button';
            btn.textContent = '✓ Shift Timing';
            btn.onclick = () => {
              if (window.shiftTimingBySeconds) {
                window.shiftTimingBySeconds(act.seconds);
              } else {
                const shiftInput = document.getElementById('shift');
                const shiftBtn = document.getElementById('shiftAll');
                if (shiftInput && shiftBtn) {
                  shiftInput.value = act.seconds;
                  shiftBtn.click();
                }
              }
            };
            card.append(title, body, btn);

          } else if (act.action === 'fix_translation') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.innerHTML = `<span>📝</span> Line ${act.line} Translation Update`;

            const body = document.createElement('div');
            body.className = 'actionBody';

            if (act.original_text) {
              const origRow = document.createElement('div');
              origRow.className = 'copilotSubRow';
              origRow.innerHTML = `<strong>Original:</strong> <em>"${escapeHtml(act.original_text)}"</em>`;
              body.appendChild(origRow);
            }

            if (act.old_translation) {
              const oldRow = document.createElement('div');
              oldRow.className = 'copilotSubRow text-zinc-400';
              oldRow.innerHTML = `<strong>Previous:</strong> <span>"${escapeHtml(act.old_translation)}"</span>`;
              body.appendChild(oldRow);
            }

            const newRow = document.createElement('div');
            newRow.className = 'copilotSubRow highlight';
            newRow.innerHTML = `<strong>Revised:</strong> <span class="highlightText">"${escapeHtml(act.new_translation)}"</span>`;
            body.appendChild(newRow);

            if (act.explanation) {
              const expRow = document.createElement('div');
              expRow.className = 'copilotSubRow note';
              expRow.textContent = `💡 ${act.explanation}`;
              body.appendChild(expRow);
            }

            const btnGroup = document.createElement('div');
            btnGroup.className = 'copilotBtnGroup';

            const applyBtn = document.createElement('button');
            applyBtn.className = 'copilotActionBtn';
            applyBtn.type = 'button';
            applyBtn.textContent = `✓ Apply to Line ${act.line}`;
            applyBtn.onclick = () => {
              let applied = false;
              if (window.updateCueTranslation) {
                applied = window.updateCueTranslation(act.line, act.language, act.new_translation);
              }
              if (applied) {
                applyBtn.textContent = '✓ Applied to Subtitles!';
                applyBtn.classList.add('success');
              } else {
                applyBtn.textContent = '✓ Stored (Open Caption Studio)';
              }
            };

            const copyBtn = document.createElement('button');
            copyBtn.className = 'copilotActionBtn secondary';
            copyBtn.type = 'button';
            copyBtn.textContent = '📋 Copy';
            copyBtn.onclick = () => {
              navigator.clipboard.writeText(act.new_translation || '');
              copyBtn.textContent = '✓ Copied!';
            };

            btnGroup.append(applyBtn, copyBtn);
            card.append(title, body, btnGroup);

          } else if (act.action === 'translation_options') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.innerHTML = `<span>🎭</span> Line ${act.line} Translation Styles`;

            const body = document.createElement('div');
            body.className = 'actionBody';

            if (act.original_text) {
              const origRow = document.createElement('div');
              origRow.className = 'copilotSubRow';
              origRow.innerHTML = `<strong>Original:</strong> <em>"${escapeHtml(act.original_text)}"</em>`;
              body.appendChild(origRow);
            }

            (act.options || []).forEach((opt, idx) => {
              const optCard = document.createElement('div');
              optCard.className = 'copilotOptCard';

              const optHeader = document.createElement('div');
              optHeader.className = 'copilotOptHeader';
              optHeader.innerHTML = `<strong>Option ${idx+1}: ${escapeHtml(opt.style || '')}</strong>`;

              const optText = document.createElement('div');
              optText.className = 'copilotOptText';
              optText.textContent = `"${opt.text || ''}"`;

              const optNote = document.createElement('div');
              optNote.className = 'copilotOptNote';
              optNote.textContent = opt.note || '';

              const optBtn = document.createElement('button');
              optBtn.className = 'copilotActionBtn small';
              optBtn.type = 'button';
              optBtn.textContent = `✓ Apply Option ${idx+1}`;
              optBtn.onclick = () => {
                let applied = false;
                if (window.updateCueTranslation) {
                  applied = window.updateCueTranslation(act.line, act.language, opt.text);
                }
                optBtn.textContent = applied ? '✓ Applied!' : '✓ Selected';
                optBtn.classList.add('success');
              };

              optCard.append(optHeader, optText, optNote, optBtn);
              body.appendChild(optCard);
            });

            card.append(title, body);

          } else if (act.action === 'fix_subtitle_text') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.innerHTML = `<span>✏️</span> Line ${act.line} Text Correction`;

            const body = document.createElement('div');
            body.className = 'actionBody';

            if (act.old_text) {
              const oldRow = document.createElement('div');
              oldRow.className = 'copilotSubRow text-zinc-400';
              oldRow.innerHTML = `<strong>Previous:</strong> <s>"${escapeHtml(act.old_text)}"</s>`;
              body.appendChild(oldRow);
            }

            const newRow = document.createElement('div');
            newRow.className = 'copilotSubRow highlight';
            newRow.innerHTML = `<strong>Corrected:</strong> <span class="highlightText">"${escapeHtml(act.new_text)}"</span>`;
            body.appendChild(newRow);

            if (act.explanation) {
              const expRow = document.createElement('div');
              expRow.className = 'copilotSubRow note';
              expRow.textContent = `💡 ${act.explanation}`;
              body.appendChild(expRow);
            }

            const applyBtn = document.createElement('button');
            applyBtn.className = 'copilotActionBtn';
            applyBtn.type = 'button';
            applyBtn.textContent = `✓ Apply Text Change`;
            applyBtn.onclick = () => {
              let applied = false;
              if (window.updateCueText) {
                applied = window.updateCueText(act.line, act.new_text);
              }
              applyBtn.textContent = applied ? '✓ Updated!' : '✓ Saved';
              applyBtn.classList.add('success');
            };

            card.append(title, body, applyBtn);

          } else if (act.action === 'subtitle_audit') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.innerHTML = `<span>🔍</span> Subtitle Quality & Reading Speed Audit`;

            const body = document.createElement('div');
            body.className = 'actionBody';

            const summary = document.createElement('div');
            summary.className = 'copilotAuditSummary';
            summary.textContent = act.message || `Audited ${act.total_cues || 0} lines.`;
            body.appendChild(summary);

            if (act.issues && act.issues.length) {
              act.issues.forEach(iss => {
                const item = document.createElement('div');
                item.className = 'copilotAuditItem';
                item.innerHTML = `
                  <div class="auditBadge ${iss.severity || 'warning'}">Line ${iss.line}</div>
                  <div class="auditDesc">${escapeHtml(iss.message)}</div>
                `;
                body.appendChild(item);
              });
            } else {
              const cleanMsg = document.createElement('div');
              cleanMsg.className = 'copilotAuditClean';
              cleanMsg.textContent = '✨ All subtitle lines have good reading speed and valid translations!';
              body.appendChild(cleanMsg);
            }

            card.append(title, body);

          } else if (act.action === 'navigate_app') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.innerHTML = `<span>🧭</span> Navigation: ${escapeHtml(act.label || act.target)}`;

            const body = document.createElement('div');
            body.className = 'actionBody';
            body.textContent = act.message || '';

            const btn = document.createElement('button');
            btn.className = 'copilotActionBtn';
            btn.type = 'button';
            btn.textContent = `→ Go to ${act.label || act.target}`;
            btn.onclick = () => {
              executeAppNavigation(act.target);
            };

            card.append(title, body, btn);

          } else if (act.action === 'open_downloads_folder') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.innerHTML = `<span>📂</span> Windows File Explorer`;

            const body = document.createElement('div');
            body.className = 'actionBody';
            body.textContent = act.message || 'Opening downloads folder in Windows File Explorer...';

            const btn = document.createElement('button');
            btn.className = 'copilotActionBtn';
            btn.type = 'button';
            btn.textContent = '📂 Open Explorer Now';
            btn.onclick = async () => {
              try {
                await fetch('/api/open_folder', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ path: '' })
                });
                btn.textContent = '✓ Explorer Opened!';
              } catch (_) {}
            };

            card.append(title, body, btn);

          } else if (act.action === 'change_font') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.innerHTML = `<span>🔤</span> Font Styling`;

            const body = document.createElement('div');
            body.className = 'actionBody';
            body.textContent = `Typography font: ${act.font}`;

            const btn = document.createElement('button');
            btn.className = 'copilotActionBtn';
            btn.type = 'button';
            btn.textContent = `✓ Apply ${act.font} Font`;
            btn.onclick = () => {
              const fontSelect = document.getElementById('font');
              if (fontSelect) {
                fontSelect.value = act.font;
                fontSelect.dispatchEvent(new Event('change'));
                btn.textContent = '✓ Font Updated!';
              }
            };
            card.append(title, body, btn);

          } else if (act.action === 'show_capabilities') {
            const title = document.createElement('div');
            title.className = 'actionTitle';
            title.innerHTML = `<span>⚡</span> Studio Copilot Capabilities Directory`;

            const body = document.createElement('div');
            body.className = 'actionBody copilotCapsGrid';

            const categories = [
              {
                icon: '📝',
                title: 'Subtitle & Translation AI',
                desc: 'Fix awkward lines, audit reading speed, rephrase in poetic/viral styles.',
                prompt: 'Audit my subtitles for reading speed and issues'
              },
              {
                icon: '🎬',
                title: 'AI Video Studio',
                desc: 'Autonomous song director, storyboard keyframes, Wan 2.1 motion mimic.',
                prompt: 'How does Wan 2.1 motion work?'
              },
              {
                icon: '📥',
                title: 'Media Downloader',
                desc: 'Download Instagram profiles, carousels, TikToks, and 4K YouTube.',
                prompt: 'How do I download an Instagram profile?'
              },
              {
                icon: '🎨',
                title: 'Caption Styling',
                desc: 'Beast Pop, Cyberpunk, Frosted Glass presets, and typography.',
                prompt: 'Apply the Cyberpunk neon style preset to my captions'
              },
              {
                icon: '📂',
                title: 'Files & Explorer',
                desc: 'Reveal downloads in Windows File Explorer, switch to AI Studio gallery.',
                prompt: 'Show AI Studio pictures and videos'
              },
              {
                icon: '⌨️',
                title: 'Keyboard Shortcuts',
                desc: 'Fast controls for timeline editing, splitting, play/pause, and undo.',
                prompt: 'What keyboard shortcuts are there?'
              }
            ];

            categories.forEach(cat => {
              const capCard = document.createElement('div');
              capCard.className = 'copilotCapCard';
              capCard.innerHTML = `
                <div class="capHeader">
                  <span>${cat.icon}</span>
                  <strong>${cat.title}</strong>
                </div>
                <p>${cat.desc}</p>
                <button type="button" class="copilotActionBtn small" data-prompt="${escapeHtml(cat.prompt)}">Try: "${escapeHtml(cat.prompt)}"</button>
              `;
              capCard.querySelector('button').onclick = () => {
                const inp = document.getElementById('copilotInput');
                if (inp) {
                  inp.value = cat.prompt;
                  submitMessage();
                }
              };
              body.appendChild(capCard);
            });

            card.append(title, body);
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

    input.disabled = true;
    if (sendBtn) sendBtn.disabled = true;

    try {
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

      // Auto-execute immediate UI changes if appropriate
      if (data.actions) {
        data.actions.forEach(a => {
          if (a.action === 'apply_style_preset') {
            const btn = document.querySelector(`[data-preset="${a.preset}"]`);
            if (btn) btn.click();
          } else if (a.action === 'navigate_app') {
            executeAppNavigation(a.target);
          } else if (a.action === 'open_downloads_folder') {
            fetch('/api/open_folder', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ path: '' })
            }).catch(() => {});
          } else if (a.action === 'change_font') {
            const fontSel = document.getElementById('font');
            if (fontSel) {
              fontSel.value = a.font;
              fontSel.dispatchEvent(new Event('change'));
            }
          }
        });
      }

    } catch (err) {
      state.messages.push({
        role: 'assistant',
        content: '👋 Copilot active! I can answer questions about the app, fix translations, and execute styling commands.'
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
