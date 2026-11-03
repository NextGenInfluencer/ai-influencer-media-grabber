/* AI Setup, AI Engines and Downloads & Storage sheets, plus first-use notices.
 * Shared by every page. Nothing downloads unless the user presses Install in a sheet that
 * shows the live size, source and license first.
 */
(() => {
    'use strict';

    const SETUP_SEEN_KEY = 'mg.aiSetupSeen';
    const NOTICE_KEY = name => `mg.notice.${name}`;
    const ROLE_LABELS = {helper: 'Helper (Copilot, SEO)', translator: 'Translator', vision: 'Vision', speech: 'Speech (Whisper)'};
    const PROFILE_LABELS = {essentials: 'Essentials (no AI)', laptop: 'Laptop / CPU', gpu_mid: 'GPU 6–10 GB', gpu_high: 'GPU 12–16 GB', gpu_ultra: 'GPU 24 GB+'};
    const DOCS = 'https://github.com/NextGenInfluencer/ai-influencer-media-grabber/blob/main/docs/';
    const NOTICES = {
        responsible_use: {
            icon: '🤝', title: 'Responsible use: consent and likeness',
            subtitle: 'Face swap, lip-sync and portrait animation change what a real person appears to say or do.',
            points: [
                'Only use the face, voice or likeness of yourself or of people who clearly agreed to this use.',
                'Never impersonate, mislead about real events, harass, sexualise or defame anyone, or target minors. In many countries this is illegal.',
                'Label AI-edited or AI-generated media where viewers could mistake it for real footage.',
                'Some face models are licensed for personal / non-commercial use only.',
            ],
            doc: 'RESPONSIBLE_USE.md', agree: 'I have consent from everyone whose likeness I use, and I will label synthetic media.',
        },
        download_copyright: {
            icon: '©️', title: 'Before your first download',
            subtitle: 'Being able to download something does not mean you may re-use it.',
            points: [
                'Download only content you own, have permission to use, or that the law lets you use (for example private study).',
                'Respect each platform’s terms of service; automated access can get accounts rate-limited or suspended.',
                'Keep credits: the source link is saved next to every download so you can attribute the creator.',
                'Only use your own logged-in session, and never share your cookies file.',
            ],
            doc: 'RESPONSIBLE_USE.md', agree: 'I understand and will only download content I am allowed to use.',
        },
    };

    // ------------------------------------------------------------------ helpers

    const token = () => document.querySelector('meta[name="media-token"]')?.content || '';

    async function api(url, {method = 'GET', body} = {}) {
        const options = {method, headers: {}};
        if (method !== 'GET') options.headers['X-Media-Token'] = token();
        if (body !== undefined) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(body);
        }
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(data.error || `Request failed (${response.status})`);
            Object.assign(error, {status: response.status, setupHint: data.setup_hint, consentRequired: data.consent_required, data});
            throw error;
        }
        return data;
    }

    function h(tag, props = {}, ...children) {
        const node = document.createElement(tag);
        for (const [key, value] of Object.entries(props || {})) {
            if (value === undefined || value === null || value === false) continue;
            if (key === 'class') node.className = value;
            else if (key === 'text') node.textContent = value;
            else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
            else if (value === true) node.setAttribute(key, '');
            else node.setAttribute(key, value);
        }
        for (const child of children.flat()) {
            if (child === null || child === undefined || child === false) continue;
            node.append(child instanceof Node ? child : document.createTextNode(String(child)));
        }
        return node;
    }

    const safeUrl = value => {
        try { const url = new URL(value); return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null; } catch { return null; }
    };
    const link = (href, text) => (safeUrl(href) ? h('a', {href: safeUrl(href), target: '_blank', rel: 'noopener noreferrer'}, text) : h('span', {}, text));

    function bytes(value) {
        if (value === null || value === undefined) return 'size unknown';
        if (value < 1024 ** 2) return `${Math.max(1, Math.round(value / 1024))} KB`;
        if (value < 1024 ** 3) return `${Math.round(value / 1024 ** 2)} MB`;
        return `${(value / 1024 ** 3).toFixed(1)} GB`;
    }
    const eta = seconds => (!seconds ? '' : seconds < 90 ? `~${Math.max(1, Math.round(seconds))} s` : `~${Math.round(seconds / 60)} min`);
    const chip = (text, kind = '') => h('span', {class: `ais-chip ${kind}`.trim(), text});
    const localChip = local => chip(local === false ? 'Cloud' : 'Local', local === false ? 'cloud' : 'local');
    const ncBadge = () => chip('Personal / non-commercial use only', 'nc');
    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
    const toast = (title, message) => (typeof window.showToast === 'function' ? window.showToast(title, message) : null);

    function emptyState(icon, title, text, action) {
        return h('div', {class: 'ais-empty'}, h('div', {class: 'ais-empty-icon', text: icon}), h('h4', {text: title}), h('p', {text}), action || null);
    }

    function errorNote(error) {
        return h('p', {class: 'ais-note error', role: 'alert', text: error.message || String(error)});
    }

    // ------------------------------------------------------------------ sheet shell

    let activeSheet = null;

    function openSheet({icon, title, subtitle, onClose}) {
        activeSheet?.close();
        const previousFocus = document.activeElement;
        const body = h('div', {class: 'ais-body'});
        const foot = h('div', {class: 'ais-foot'});
        const closeButton = h('button', {class: 'ais-close', type: 'button', 'aria-label': 'Close', text: '×'});
        const titleId = `ais-title-${Date.now()}`;
        const sheet = h('div', {class: 'ais-sheet', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId},
            h('div', {class: 'ais-head'}, h('div', {class: 'ais-head-icon', text: icon}),
                h('div', {}, h('h2', {id: titleId, text: title}), subtitle ? h('p', {text: subtitle}) : null), closeButton),
            body, foot);
        const overlay = h('div', {class: 'ais-overlay'}, sheet);
        let closed = false;
        const api_ = {
            body, foot,
            set(...nodes) { body.replaceChildren(...nodes.flat().filter(Boolean)); },
            footer(...nodes) { foot.replaceChildren(...nodes.flat().filter(Boolean)); foot.hidden = !foot.childNodes.length; },
            close() {
                if (closed) return;
                closed = true;
                document.removeEventListener('keydown', onKey, true);
                overlay.remove();
                if (activeSheet === api_) activeSheet = null;
                onClose?.();
                previousFocus?.focus?.();
            },
            get closed() { return closed; },
        };
        function onKey(event) {
            if (event.key === 'Escape') { event.stopPropagation(); api_.close(); }
        }
        closeButton.addEventListener('click', () => api_.close());
        overlay.addEventListener('mousedown', event => { if (event.target === overlay) api_.close(); });
        document.addEventListener('keydown', onKey, true);
        document.body.append(overlay);
        activeSheet = api_;
        closeButton.focus();
        api_.set(h('div', {class: 'ais-empty'}, h('span', {class: 'ais-spinner'}), h('p', {text: 'Checking this PC…'})));
        api_.footer();
        return api_;
    }

    // ------------------------------------------------------------------ first-use notices

    function noticeAcceptedLocally(name) {
        try { return localStorage.getItem(NOTICE_KEY(name)) === '1'; } catch { return false; }
    }
    function rememberNotice(name) {
        try { localStorage.setItem(NOTICE_KEY(name), '1'); } catch { /* storage disabled: server copy still applies */ }
    }

    /** Resolve true once the notice is accepted (now or earlier); false if the user cancels. */
    window.ensureNoticeAccepted = async function ensureNoticeAccepted(name) {
        const notice = NOTICES[name];
        if (!notice) throw new Error(`Unknown notice: ${name}`);
        if (noticeAcceptedLocally(name)) return true;
        try {
            const settings = await api('/api/ai/settings');
            if (settings.notices?.[name]) { rememberNotice(name); return true; }
        } catch { /* offline settings: ask again rather than assume */ }
        return new Promise(resolve => {
            let accepted = false;
            const sheet = openSheet({icon: notice.icon, title: notice.title, subtitle: notice.subtitle, onClose: () => resolve(accepted)});
            const agree = h('input', {type: 'checkbox'});
            const proceed = h('button', {class: 'ais-btn primary', type: 'button', text: 'Continue', disabled: true});
            agree.addEventListener('change', () => { proceed.disabled = !agree.checked; });
            proceed.addEventListener('click', async () => {
                accepted = true;
                rememberNotice(name);
                api('/api/ai/settings', {method: 'POST', body: {notices: {[name]: true}}}).catch(() => {});
                sheet.close();
            });
            sheet.set(
                h('ul', {class: 'ais-points'}, notice.points.map(point => h('li', {text: point}))),
                h('p', {class: 'ais-note'}, 'Full policy: ', link(DOCS + notice.doc, notice.doc), ' · ', link(DOCS + 'PRIVACY.md', 'PRIVACY.md')),
                h('label', {class: 'ais-check'}, agree, h('span', {text: notice.agree})));
            sheet.footer(h('span', {class: 'ais-spacer'}),
                h('button', {class: 'ais-btn', type: 'button', text: 'Cancel', onclick: () => sheet.close()}), proceed);
        });
    };

    // ------------------------------------------------------------------ AI Engine Pack (Python packages)

    async function enginePackStatus() {
        try { return await api('/api/ai_status'); } catch { return null; }
    }

    function enginePackPanel(status, onDone) {
        const panel = h('div', {class: 'ais-card'});
        const render = async () => {
            if (status?.is_installing) return renderProgress();
            let notice;
            try { notice = await api('/api/install_ai/notice'); } catch (error) { panel.replaceChildren(errorNote(error)); return; }
            const install = h('button', {class: 'ais-btn primary', type: 'button', text: `Install AI Engine Pack (~${bytes(notice.approx_download_mb * 1024 ** 2)})`,
                disabled: notice.enough_disk === false});
            install.addEventListener('click', async () => {
                install.disabled = true;
                try {
                    await api('/api/install_ai', {method: 'POST', body: {accept: true, pack: notice.pack}});
                    status = {...(status || {}), is_installing: true};
                    renderProgress();
                } catch (error) { install.disabled = false; panel.append(errorNote(error)); }
            });
            panel.replaceChildren(
                h('div', {class: 'ais-row-title'}, `AI Engine Pack · ${notice.label}`, localChip(true)),
                h('p', {class: 'ais-note', text: `${notice.summary} ${notice.reason}`}),
                h('div', {}, notice.items.map(item => h('div', {class: 'ais-row'},
                    h('div', {class: 'ais-row-main'},
                        h('div', {class: 'ais-row-title'}, item.name, chip(`~${bytes(item.approx_mb * 1024 ** 2)}`)),
                        h('div', {class: 'ais-row-meta'}, item.purpose, ' · ', link(item.license_url, item.license), ' · ', link(item.source, 'source')))))),
                h('div', {class: 'ais-total'}, h('span', {text: `Disk needed ~${bytes(notice.approx_disk_mb * 1024 ** 2)} · free ${notice.disk_free_mb === null ? 'unknown' : bytes(notice.disk_free_mb * 1024 ** 2)}`}), install),
                notice.enough_disk === false ? h('p', {class: 'ais-note warn', text: 'Not enough free disk space for this pack.'}) : null,
                h('p', {class: 'ais-note', text: notice.note}));
        };
        const renderProgress = async () => {
            const bar = h('div', {class: 'ais-progress'}, h('div'));
            const label = h('div', {class: 'ais-row-meta', text: 'Starting…'});
            const log = h('div', {class: 'ais-log'});
            panel.replaceChildren(h('div', {class: 'ais-row-title', text: 'Installing the AI Engine Pack'}), bar, label, log);
            for (;;) {
                const current = await enginePackStatus();
                if (!current) { await sleep(2000); continue; }
                bar.firstChild.style.width = `${current.install_progress || 5}%`;
                label.textContent = current.install_status || '';
                log.textContent = (current.install_log || []).join('\n');
                if (!current.is_installing) {
                    if (current.install_error) {
                        bar.classList.add('failed');
                        panel.append(h('p', {class: 'ais-note error', text: current.install_error}));
                    } else {
                        bar.classList.add('done');
                        panel.append(h('p', {class: 'ais-note', text: 'Installed and verified. Restart the app to load the new AI libraries.'}),
                            h('button', {class: 'ais-btn primary', type: 'button', text: 'Restart now', onclick: restartApp}));
                        onDone?.();
                    }
                    return;
                }
                await sleep(1500);
            }
        };
        render();
        return panel;
    }

    async function restartApp() {
        try { await api('/api/restart', {method: 'POST'}); } catch { /* server going down */ }
        toast('Restarting', 'The app will reload in a few seconds.');
        setTimeout(() => window.location.reload(), 6000);
    }

    // ------------------------------------------------------------------ AI Setup wizard

    function hardwareCard(profile, onProfile) {
        const hw = profile.hardware || {};
        const select = h('select', {class: 'ais-select', 'aria-label': 'Hardware profile'},
            h('option', {value: '', text: `Automatic (${PROFILE_LABELS[profile.detected_profile] || profile.detected_profile})`}),
            (profile.profiles || []).map(name => h('option', {value: name, text: PROFILE_LABELS[name] || name})));
        select.value = profile.override || '';
        select.addEventListener('change', () => onProfile(select.value || null));
        return h('div', {class: 'ais-section'}, h('h3', {text: '1 · This PC'}),
            h('div', {class: 'ais-card'},
                h('div', {class: 'ais-grid'},
                    h('div', {class: 'ais-stat'}, h('span', {text: 'Graphics'}), h('strong', {text: hw.gpu_name ? `${hw.gpu_name}${hw.vram_gb ? ` · ${Math.round(hw.vram_gb)} GB` : ''}` : 'No dedicated GPU'})),
                    h('div', {class: 'ais-stat'}, h('span', {text: 'Memory'}), h('strong', {text: hw.ram_gb ? `${Math.round(hw.ram_gb)} GB RAM` : 'Unknown'})),
                    h('div', {class: 'ais-stat'}, h('span', {text: 'Free disk'}), h('strong', {text: hw.disk_free_gb ? `${Math.round(hw.disk_free_gb)} GB` : 'Unknown'})),
                    h('div', {class: 'ais-stat'}, h('span', {text: 'Profile'}), h('strong', {text: PROFILE_LABELS[profile.profile] || profile.profile}))),
                h('div', {class: 'ais-row', style: 'margin-top:10px;align-items:center'},
                    h('span', {class: 'ais-row-meta', text: 'Recommended models follow this profile. Override it if detection is wrong.'}), h('span', {class: 'ais-spacer', style: 'flex:1'}), select)));
    }

    function itemRow(itemId, state) {
        const box = h('input', {type: 'checkbox', 'aria-label': `Install ${itemId}`});
        const ncBox = h('input', {type: 'checkbox'});
        const title = h('div', {class: 'ais-row-title', text: itemId});
        const meta = h('div', {class: 'ais-row-meta', text: 'Reading live size from the source…'});
        const extra = h('div');
        const bar = h('div', {class: 'ais-progress', hidden: true}, h('div'));
        const status = h('div', {class: 'ais-row-meta'});
        const cancel = h('button', {class: 'ais-btn small', type: 'button', text: 'Cancel', hidden: true});
        const row = h('div', {class: 'ais-row'}, box, h('div', {class: 'ais-row-main'}, title, meta, extra, bar, status), cancel);
        const entry = {id: itemId, row, box, ncBox, notice: null, bar, status, cancel,
            get selected() { return box.checked && !box.disabled; },
            get ready() { return !entry.notice?.non_commercial || entry.notice.license_accepted || ncBox.checked; }};
        api(`/api/ai/notice/${encodeURIComponent(itemId)}`).then(notice => {
            entry.notice = notice;
            // DOM replaceChildren() stringifies null, so drop absent badges first.
            title.replaceChildren(...[notice.name, localChip(notice.local), notice.installed ? chip('Installed', 'ok') : null,
                notice.non_commercial ? ncBadge() : null].filter(Boolean));
            const parts = [];
            if (notice.features?.length) parts.push(`Unlocks: ${notice.features.join(', ')}`);
            parts.push(notice.installed ? 'Already on this PC' : `Download ${bytes(notice.download_bytes)}${notice.size_source === 'live' ? ' (live size)' : ''}${eta(notice.eta_download_seconds) ? ` · ${eta(notice.eta_download_seconds)}` : ''}`);
            if (notice.vram_gb) parts.push(`${notice.vram_gb} GB VRAM`);
            else if (notice.ram_gb) parts.push(`${notice.ram_gb} GB RAM`);
            meta.replaceChildren(parts.join(' · '));
            const source = notice.source || {};
            extra.replaceChildren(h('div', {class: 'ais-row-meta'},
                'By ', link(source.url, source.publisher || 'source'), ' · License ', link(notice.license?.url, notice.license?.name || 'see source'),
                notice.companions?.some(c => !c.installed) ? ` · includes ${notice.companions.filter(c => !c.installed).map(c => c.name).join(', ')}` : ''));
            if (notice.non_commercial && !notice.license_accepted) {
                extra.append(h('label', {class: 'ais-check'}, ncBox,
                    h('span', {text: 'I accept this license and will use the model for personal, non-commercial purposes only.'})));
                ncBox.addEventListener('change', state.refresh);
            }
            if (!notice.disk_ok && !notice.installed) extra.append(h('p', {class: 'ais-note warn', text: 'Not enough free disk space for this download.'}));
            box.checked = !notice.installed;
            box.disabled = notice.installed;
            state.refresh();
        }).catch(error => {
            meta.replaceChildren(error.message);
            box.disabled = true;
            state.refresh();
        });
        box.addEventListener('change', state.refresh);
        return entry;
    }

    async function installEntry(entry) {
        entry.bar.hidden = false;
        entry.box.disabled = true;
        entry.status.textContent = 'Starting…';
        const started = await api('/api/ai/install', {method: 'POST', body: {item_id: entry.id, accept_license: true}});
        entry.cancel.hidden = false;
        entry.cancel.onclick = () => api(`/api/ai/jobs/${started.job_id}/cancel`, {method: 'POST'}).catch(() => {});
        for (;;) {
            const job = await api(`/api/ai/jobs/${started.job_id}`);
            entry.bar.firstChild.style.width = `${Math.round((job.progress || 0) * 100)}%`;
            const amount = job.bytes_total ? ` · ${bytes(job.bytes_done)} of ${bytes(job.bytes_total)}` : '';
            entry.status.textContent = `${job.message || job.state}${amount}`;
            if (!['queued', 'running'].includes(job.state)) {
                entry.cancel.hidden = true;
                if (job.state === 'done') {
                    entry.bar.classList.add('done');
                    entry.bar.firstChild.style.width = '100%';
                    entry.status.textContent = 'Installed and verified';
                    return true;
                }
                entry.bar.classList.add('failed');
                entry.status.textContent = job.error || job.message || 'Install stopped.';
                return false;
            }
            await sleep(1000);
        }
    }

    window.openAISetup = async function openAISetup(itemId, {firstRun = false} = {}) {
        const target = typeof itemId === 'string' && !['ai_setup', 'ai_pack'].includes(itemId) ? itemId : null;
        const sheet = openSheet({icon: '✨', title: target ? 'Set up a local model' : 'Set up AI for this PC',
            subtitle: 'Everything runs on your computer. Sizes, sources and licenses are shown before anything downloads.',
            onClose: firstRun ? markSetupSeen : null});
        const load = async () => {
            let profile, pack;
            try { [profile, pack] = await Promise.all([api('/api/ai/profile'), enginePackStatus()]); } catch (error) {
                sheet.set(errorNote(error)); return;
            }
            const state = {entries: [], installing: false, refresh: () => {}};
            const total = h('strong', {text: '—'});
            const disk = h('span', {class: 'ais-row-meta'});
            const install = h('button', {class: 'ais-btn primary', type: 'button', text: 'Install selected'});
            state.refresh = () => {
                const selected = state.entries.filter(e => e.selected);
                const sum = selected.reduce((acc, e) => acc + (e.notice?.download_bytes || 0), 0);
                total.textContent = selected.length ? bytes(sum) : 'Nothing selected';
                const free = state.entries.find(e => e.notice)?.notice.disk_free_bytes;
                disk.textContent = free ? `Free on the models drive: ${bytes(free)}` : '';
                install.disabled = state.installing || !selected.length || selected.some(e => !e.ready || !e.notice);
            };
            const ids = target ? [target] : (profile.bundle || []).map(item => item.id);
            state.entries = ids.map(id => itemRow(id, state));
            install.addEventListener('click', async () => {
                state.installing = true;
                state.refresh();
                for (const entry of state.entries.filter(e => e.selected)) {
                    try { await installEntry(entry); } catch (error) { entry.status.textContent = error.message; entry.bar.classList.add('failed'); }
                }
                state.installing = false;
                toast('AI Setup', 'Installs finished. Check each row for its result.');
                refreshBadges();
            });
            const packMissing = pack && !pack.all_installed;
            const checklist = state.entries.length
                ? h('div', {class: 'ais-card'}, state.entries.map(e => e.row))
                : emptyState('🌿', 'Essentials profile', 'This profile uses no local models. Downloads, editing and captions work without AI.');
            sheet.set(
                packMissing ? h('div', {class: 'ais-section'}, h('h3', {text: 'AI Engine Pack (required first for speech, vision and the built-in engine)'}),
                    enginePackPanel(pack, refreshBadges)) : null,
                target ? null : hardwareCard(profile, async value => {
                    try { await api('/api/ai/profile', {method: 'POST', body: {profile: value}}); } catch (error) { toast('Profile', error.message); }
                    load();
                }),
                h('div', {class: 'ais-section'}, h('h3', {text: target ? 'Model' : `2 · Recommended for ${PROFILE_LABELS[profile.profile] || profile.profile}`}), checklist),
                state.entries.length ? h('div', {class: 'ais-section'}, h('h3', {text: '3 · Install'}),
                    h('div', {class: 'ais-card'}, h('div', {class: 'ais-total'}, h('span', {}, 'Total download ', total), disk),
                        h('p', {class: 'ais-note', text: 'Each file is pinned to an exact version and verified (SHA-256) before use. Downloads can be cancelled and resume later.'}))) : null);
            state.refresh();
            sheet.footer(
                firstRun ? h('button', {class: 'ais-btn', type: 'button', text: 'Use without AI', onclick: () => sheet.close()}) : null,
                h('button', {class: 'ais-btn', type: 'button', text: 'Downloads & Storage', onclick: () => window.openAIStorage()}),
                h('span', {class: 'ais-spacer'}),
                h('button', {class: 'ais-btn', type: 'button', text: 'Close', onclick: () => sheet.close()}),
                state.entries.length ? install : null);
        };
        await load();
    };

    function markSetupSeen() {
        try { localStorage.setItem(SETUP_SEEN_KEY, '1'); } catch { /* ignore */ }
        api('/api/ai/settings', {method: 'POST', body: {setup_seen: true}}).catch(() => {});
    }

    // ------------------------------------------------------------------ Downloads & Storage

    window.openAIStorage = async function openAIStorage() {
        const sheet = openSheet({icon: '🗄️', title: 'Downloads & Storage', subtitle: 'Everything the AI features installed on this PC, and space you can reclaim.'});
        const load = async () => {
            let data;
            try { data = await api('/api/ai/storage'); } catch (error) { sheet.set(errorNote(error)); return; }
            const installed = data.installed || [];
            const reclaim = data.reclaimable || [];
            const reclaimTotal = reclaim.reduce((acc, entry) => acc + (entry.size_bytes || 0), 0);
            const removeItem = item => async () => {
                if (!window.confirm(`Remove ${item.name} (${bytes(item.size_bytes)})? Features that use it stop working until you install it again.`)) return;
                try { await api('/api/ai/remove', {method: 'POST', body: {item_id: item.id}}); toast('Removed', item.name); } catch (error) { toast('Remove failed', error.message); }
                load();
                refreshBadges();
            };
            const verifyItem = item => async () => {
                try { await api('/api/ai/storage/verify', {method: 'POST', body: {item_id: item.id}}); toast('Verified', item.name); } catch (error) { toast('Verify failed', error.message); }
                load();
            };
            const reclaimAll = async () => {
                if (!window.confirm(`Delete ${reclaim.length} file(s) and free ${bytes(reclaimTotal)}? Only duplicates, obsolete models and stale partial downloads are listed here.`)) return;
                for (const entry of reclaim) {
                    try { await api('/api/ai/remove', {method: 'POST', body: {id: entry.id}}); } catch (error) { toast('Could not remove a file', error.message); }
                }
                load();
            };
            sheet.set(
                h('div', {class: 'ais-section'}, h('h3', {text: 'Installed'}),
                    installed.length ? h('div', {class: 'ais-card'}, installed.map(item => h('div', {class: 'ais-row'},
                        h('div', {class: 'ais-row-main'},
                            h('div', {class: 'ais-row-title'}, item.name, chip(bytes(item.size_bytes)), item.verified === true ? chip('Verified', 'ok') : item.verified === null ? chip('Checking…') : chip('Not verified', 'warn'),
                                item.non_commercial ? ncBadge() : null),
                            item.features?.length ? h('div', {class: 'ais-row-meta', text: `Used by: ${item.features.join(', ')}`}) : null,
                            item.missing_companions?.length ? h('div', {class: 'ais-note warn', text: `Needs ${item.missing_companions.join(', ')} to run`}) : null,
                            item.path ? h('div', {class: 'ais-path', text: item.path}) : null),
                        item.verified !== true ? h('button', {class: 'ais-btn small', type: 'button', text: 'Verify', onclick: verifyItem(item)}) : null,
                        h('button', {class: 'ais-btn small danger', type: 'button', text: 'Remove', onclick: removeItem(item)}))))
                        : emptyState('📦', 'No AI models installed', 'Set up AI to pick models for this PC. Downloads, editing and manual captions work without them.',
                            h('button', {class: 'ais-btn primary', type: 'button', text: 'Set up AI', onclick: () => window.openAISetup()}))),
                h('div', {class: 'ais-section'}, h('h3', {text: 'Reclaim space'}),
                    reclaim.length ? h('div', {class: 'ais-card'},
                        reclaim.map(entry => h('div', {class: 'ais-row'}, h('div', {class: 'ais-row-main'},
                            h('div', {class: 'ais-row-title'}, entry.reason, chip(bytes(entry.size_bytes))),
                            entry.duplicate_of ? h('div', {class: 'ais-row-meta', text: `Same file as ${entry.duplicate_of}`}) : null,
                            h('div', {class: 'ais-path', text: entry.path})))),
                        h('div', {class: 'ais-total', style: 'margin-top:10px'}, h('span', {}, 'Total ', h('strong', {text: bytes(reclaimTotal)})),
                            h('button', {class: 'ais-btn danger', type: 'button', text: `Remove all (${bytes(reclaimTotal)})`, onclick: reclaimAll})))
                        : h('div', {class: 'ais-card'}, h('p', {class: 'ais-note', text: 'Nothing to reclaim — no duplicate, obsolete or partial model files were found.'}))),
                h('p', {class: 'ais-note'}, `Models: ${data.models_dir} · Engines: ${data.engines_dir} · Free: ${bytes(data.disk_free_bytes)}`));
            sheet.footer(h('button', {class: 'ais-btn', type: 'button', text: 'AI Engines', onclick: () => window.openAIEngines()}),
                h('span', {class: 'ais-spacer'}), h('button', {class: 'ais-btn primary', type: 'button', text: 'Done', onclick: () => sheet.close()}));
            if (!sheet.closed && installed.some(i => i.verified === null)) {
                setTimeout(() => { if (!sheet.closed) load(); }, 1500);
            }
        };
        await load();
    };

    // ------------------------------------------------------------------ AI Engines

    const ENGINE_INFO = {
        ollama: {name: 'Ollama', text: 'Runs the helper, translator and vision models on the GPU.'},
        builtin: {name: 'Built-in engine', text: 'llama.cpp on the processor, for laptops without a capable GPU.'},
        comfy: {name: 'Creative engine (ComfyUI)', text: 'Images, video, lip-sync and portrait animation on GPUs with 8 GB+.'},
    };

    window.openAIEngines = async function openAIEngines() {
        const sheet = openSheet({icon: '⚙️', title: 'AI Engines', subtitle: 'Which local engine and model each AI feature uses on this PC.'});
        const load = async () => {
            let engines, profile, models, settings, catalog;
            try {
                [engines, profile, models, settings, catalog] = await Promise.all([
                    api('/api/ai/engines'), api('/api/ai/profile'), api('/api/ai/models'), api('/api/ai/settings'), api('/api/ai/catalog')]);
            } catch (error) { sheet.set(errorNote(error)); return; }
            const engineRows = Object.entries(engines.engines || {}).map(([key, status]) => {
                const info = ENGINE_INFO[key] || {name: key, text: ''};
                const control = action => async () => {
                    try { await api(`/api/ai/engines/${key}/${action}`, {method: 'POST'}); } catch (error) { toast(info.name, error.message); }
                    load();
                };
                const actions = [];
                if (status.installed && key !== 'builtin') {
                    actions.push(status.running
                        ? h('button', {class: 'ais-btn small', type: 'button', text: 'Stop', onclick: control('stop')})
                        : h('button', {class: 'ais-btn small', type: 'button', text: 'Start', onclick: control('start')}));
                } else if (!status.installed && status.setup_hint) {
                    actions.push(h('button', {class: 'ais-btn small', type: 'button', text: 'Set up', onclick: () => window.openAISetup(status.setup_hint)}));
                }
                return h('div', {class: 'ais-row'}, h('div', {class: 'ais-row-main'},
                    h('div', {class: 'ais-row-title'}, info.name, localChip(true),
                        status.running ? chip('Running', 'ok') : status.installed ? chip('Installed') : chip('Not installed')),
                    h('div', {class: 'ais-row-meta', text: [info.text, status.version ? `v${status.version}` : ''].filter(Boolean).join(' · ')}),
                    status.patch_warnings?.length ? h('div', {class: 'ais-note warn', text: `Custom node patch warning: ${status.patch_warnings.join('; ')}`}) : null), ...actions);
            });
            const speechItems = (catalog.items || []).filter(item => item.kind === 'asr' && item.status?.installed);
            const roleRows = ['helper', 'translator', 'vision', 'speech'].map(role => {
                const resolved = profile.roles?.[role] || {};
                const options = role === 'speech'
                    ? speechItems.map(item => ({value: item.id, label: item.name}))
                    : (models.models || []).map(model => ({value: model.name, label: `${model.name} · ${model.backend === 'builtin' ? 'Built-in' : 'Ollama'}`}));
                const select = h('select', {class: 'ais-select', 'aria-label': `${ROLE_LABELS[role]} model`},
                    h('option', {value: '', text: 'Auto (best for this PC)'}), options.map(o => h('option', {value: o.value, text: o.label})));
                select.value = settings.roles?.[role] || '';
                select.addEventListener('change', async () => {
                    try { await api('/api/ai/settings', {method: 'POST', body: {roles: {[role]: select.value || null}}}); } catch (error) { toast('AI Engines', error.message); }
                    load();
                    refreshBadges();
                });
                return h('div', {class: 'ais-row', style: 'align-items:center'}, h('div', {class: 'ais-row-main'},
                    h('div', {class: 'ais-row-title'}, ROLE_LABELS[role], resolved.available ? localChip(true) : chip('Not installed')),
                    h('div', {class: 'ais-row-meta', text: resolved.available
                        ? `${resolved.model}${resolved.backend ? ` · ${resolved.backend}` : ''}${resolved.eta_seconds ? ` · ${eta(resolved.eta_seconds)} per answer` : ''}${resolved.vram_gb ? ` · ${resolved.vram_gb} GB VRAM` : ''}`
                        : resolved.error || 'No local model'})),
                    resolved.available ? select : h('button', {class: 'ais-btn small', type: 'button', text: 'Set up', onclick: () => window.openAISetup(resolved.setup_hint)}));
            });
            const gpu = Object.entries(engines.gpu || {});
            const cloudRows = Object.entries(settings.cloud || {}).map(([provider, info]) => {
                const input = h('input', {class: 'ais-input', type: 'password', autocomplete: 'off', placeholder: info.has_key ? info.masked_key : 'Paste your API key'});
                const enabled = h('input', {type: 'checkbox', checked: info.enabled, disabled: !info.has_key});
                enabled.addEventListener('change', async () => {
                    try { await api('/api/ai/settings', {method: 'POST', body: {cloud: {[provider]: {enabled: enabled.checked}}}}); } catch (error) { toast(info.name, error.message); }
                    load();
                });
                const save = async () => {
                    if (!input.value.trim()) return;
                    try { await api('/api/ai/cloud/key', {method: 'POST', body: {provider, key: input.value.trim()}}); toast(info.name, 'Key saved in Windows Credential Manager.'); } catch (error) { toast(info.name, error.message); }
                    load();
                };
                const remove = async () => {
                    try { await api('/api/ai/cloud/key', {method: 'POST', body: {provider, delete: true}}); } catch (error) { toast(info.name, error.message); }
                    load();
                };
                return h('div', {class: 'ais-row', style: 'align-items:center'}, h('div', {class: 'ais-row-main'},
                    h('div', {class: 'ais-row-title'}, info.name, localChip(false), info.has_key ? chip(info.masked_key || 'Key saved', 'ok') : null),
                    h('div', {style: 'display:flex;gap:6px;align-items:center;flex-wrap:wrap'}, input,
                        h('button', {class: 'ais-btn small', type: 'button', text: 'Save key', onclick: save}),
                        info.has_key ? h('button', {class: 'ais-btn small danger', type: 'button', text: 'Delete', onclick: remove}) : null,
                        h('label', {class: 'ais-check'}, enabled, h('span', {text: 'Allow opt-in cloud actions'})))));
            });
            const nothingLocal = !Object.values(engines.engines || {}).some(s => s.installed) && !(models.models || []).length;
            sheet.set(
                nothingLocal ? emptyState('🧠', 'No local AI engine yet', 'Set up AI to choose the right engine and models for this PC. Everything else in the app works without them.',
                    h('button', {class: 'ais-btn primary', type: 'button', text: 'Set up AI', onclick: () => window.openAISetup()})) : null,
                h('div', {class: 'ais-section'}, h('h3', {text: 'Engines'}), h('div', {class: 'ais-card'}, engineRows)),
                h('div', {class: 'ais-section'}, h('h3', {text: 'Model roles'}), h('div', {class: 'ais-card'}, roleRows)),
                h('div', {class: 'ais-section'}, h('h3', {text: 'GPU memory'}), h('div', {class: 'ais-card'},
                    gpu.length ? gpu.map(([name, info]) => h('div', {class: 'ais-row-meta', text: `${name}: ${info.vram_gb} GB${info.active ? ' · in use' : ` · idle ${Math.round(info.idle_seconds)} s`}`}))
                        : h('p', {class: 'ais-note', text: 'No model is loaded on the GPU. Models are released shortly after their last use.'}))),
                h('div', {class: 'ais-section'}, h('h3', {text: 'Optional cloud (opt-in, costs credits)'}), h('div', {class: 'ais-card'},
                    h('p', {class: 'ais-note', text: 'Never used automatically. Cloud actions send only the media you select to the provider, use your own key and bill your account; you confirm the cost each time. Keys stay in Windows Credential Manager and are never shown in full.'}),
                    cloudRows)));
            sheet.footer(h('button', {class: 'ais-btn', type: 'button', text: 'Downloads & Storage', onclick: () => window.openAIStorage()}),
                h('button', {class: 'ais-btn', type: 'button', text: 'Set up AI', onclick: () => window.openAISetup()}),
                h('span', {class: 'ais-spacer'}), h('button', {class: 'ais-btn primary', type: 'button', text: 'Done', onclick: () => sheet.close()}));
        };
        await load();
    };

    // ------------------------------------------------------------------ header badge and model chips

    function profileBadgeText(profile) {
        const hw = profile.hardware || {};
        if (profile.profile?.startsWith('gpu')) return `⚡ GPU · ${hw.gpu_name || 'NVIDIA'}${hw.vram_gb ? ` ${Math.round(hw.vram_gb)} GB` : ''}`;
        if (profile.profile === 'laptop') return '💻 Laptop';
        return '🌿 Essentials';
    }

    async function refreshBadges() {
        const container = document.getElementById('aiEngineBadgeContainer');
        const chips = document.querySelectorAll('[data-ai-chip]');
        if (!container && !chips.length) return;
        let profile;
        try { profile = await api('/api/ai/profile'); } catch { return; }
        if (container) {
            const badge = h('button', {class: 'ai-profile-badge', type: 'button', title: 'AI Engines: models, engines and cloud keys', text: profileBadgeText(profile)});
            badge.addEventListener('click', () => window.openAIEngines());
            container.replaceChildren(badge);
        }
        chips.forEach(node => {
            const role = profile.roles?.[node.dataset.aiChip] || {};
            node.classList.toggle('missing', !role.available);
            node.textContent = role.available ? `AI: ${role.model} · Local` : 'AI: not installed · Set up';
            node.onclick = () => (role.available ? window.openAIEngines() : window.openAISetup(role.setup_hint));
        });
    }
    window.refreshAIBadges = refreshBadges;

    async function maybeFirstRun() {
        if (window.location.pathname !== '/') return;
        try { if (localStorage.getItem(SETUP_SEEN_KEY) === '1') return; } catch { return; }
        try {
            const settings = await api('/api/ai/settings');
            if (settings.setup_seen) { localStorage.setItem(SETUP_SEEN_KEY, '1'); return; }
        } catch { return; }
        window.openAISetup(null, {firstRun: true});
    }

    function start() {
        refreshBadges();
        maybeFirstRun();
        if (window.location.hash === '#ai-setup') window.openAISetup();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
