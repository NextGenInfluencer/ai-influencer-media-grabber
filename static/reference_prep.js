(() => {
    const el = id => document.getElementById(id);
    const dialog = el('referenceDialog');
    let project = null, previewUrl = null, pollTimer = null, busy = false, carousel = null;
    const status = text => { el('referenceStatus').textContent = text; };
    const mediaUrl = name => '/api/media/' + ['Kling References', project.id, name].map(encodeURIComponent).join('/') + '?t=' + Date.now();
    async function api(url, options) {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Request failed.');
        return data;
    }
    function setBusy(value) {
        busy = value;
        for (const id of ['referencePrepare', 'referenceVideoInput', 'referenceStart', 'referenceFirstFrame', 'referenceCurrentFrame', 'referenceProjects']) el(id).disabled = value;
    }
    function clearResults() {
        project = null;
        clearTimeout(pollTimer);
        for (const id of ['referenceOriginalImage', 'referenceEditedImage', 'referenceFrameDownload', 'referenceSheetDownload', 'referenceExport', 'referenceCandidatesSection']) {
            if (!el(id)) continue;
            el(id).hidden = true;
            el(id).removeAttribute('src');
            el(id).removeAttribute('href');
        }
        if (el('referenceCandidates')) el('referenceCandidates').replaceChildren();
        el('referenceImageInput').disabled = true;
        el('referenceImageInput').value = '';
        el('referenceOpenFolder').disabled = true;
    }
    async function refreshProjects() {
        const rows = await api('/api/reference/projects');
        const select = el('referenceProjects');
        select.replaceChildren(new Option('New reference set', ''));
        for (const row of rows) select.add(new Option(`${row.name} — ${row.start_seconds}s — ${row.state}`, row.id));
        if (project) select.value = project.id;
    }
    function renderCandidates(data) {
        const box = el('referenceCandidates');
        const section = el('referenceCandidatesSection');
        if (!box || !section) return;
        box.replaceChildren();
        if (!data.candidates?.length) { section.hidden = true; return; }
        section.hidden = false;
        if (data.contact_sheet && el('referenceSheetDownload')) {
            el('referenceSheetDownload').href = mediaUrl(data.contact_sheet);
            el('referenceSheetDownload').hidden = false;
        }
        data.candidates.forEach(cand => {
            const card = document.createElement('div'); card.className = 'ref-card';
            const img = document.createElement('img'); img.src = mediaUrl(cand.file); img.alt = `Frame at ${cand.seconds}s`;
            const btn = document.createElement('button'); btn.type = 'button';
            btn.textContent = `Use ${cand.seconds}s frame`;
            btn.onclick = async () => {
                if (busy) return;
                setBusy(true);
                el('referenceStart').value = cand.seconds;
                updateHint();
                try {
                    await api(`/api/reference/${data.id}/select-frame`, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({start_seconds: cand.seconds})
                    });
                    poll(data.id);
                } catch (e) { status(e.message); setBusy(false); }
            };
            card.append(img, btn);
            box.append(card);
        });
    }
    function showProject(data) {
        project = data;
        status(data.status);
        if (data.state !== 'ready') return;
        setBusy(false);
        el('referenceOriginalImage').src = mediaUrl(data.frame);
        el('referenceOriginalImage').hidden = false;
        el('referenceFrameDownload').href = mediaUrl(data.frame);
        el('referenceFrameDownload').hidden = false;
        el('referenceImageInput').disabled = false;
        el('referenceOpenFolder').disabled = false;
        renderCandidates(data);
        if (data.edited_image) {
            el('referenceEditedImage').src = mediaUrl(data.edited_image);
            el('referenceEditedImage').hidden = false;
            el('referenceExport').href = `/api/reference/${data.id}/export`;
            el('referenceExport').hidden = false;
            status(`Matched dimensions: ${data.dimensions.join(' × ')}. Compare the pose and framing, then export your set.`);
        }
    }
    async function poll(id) {
        try {
            const data = await api(`/api/reference/${id}`);
            if (project && project.id !== id) return;
            showProject(data);
            if (data.state === 'processing') pollTimer = setTimeout(() => poll(id), 1500);
            else { setBusy(false); await refreshProjects(); }
        } catch (error) {
            status('Status unavailable. Preparation may still be running. Reopen this saved set to check: ' + error.message);
            setBusy(false);
        }
    }
    window.openReferencePrep = async () => {
        dialog.showModal();
        try { await refreshProjects(); await refreshCarousels(); } catch (e) { status(e.message); }
    };
    window.openCarouselStudio = async () => {
        dialog.showModal();
        const ws = el('carouselWorkspace');
        if (ws) { ws.open = true; setTimeout(() => ws.scrollIntoView({behavior: 'smooth', block: 'start'}), 60); }
        try { await refreshProjects(); await refreshCarousels(); } catch (e) { cStatus(e.message); }
    };
    el('referenceClose').onclick = () => dialog.close();
    el('referenceVideoInput').onchange = () => {
        clearResults();
        el('referenceProjects').value = '';
        if (previewUrl) URL.revokeObjectURL(previewUrl);
        const file = el('referenceVideoInput').files[0];
        if (!file) return;
        previewUrl = URL.createObjectURL(file);
        el('referenceVideoPreview').src = previewUrl;
        el('referenceStart').value = '0';
        updateHint();
        status('First frame selected. Prepare the reference when ready.');
    };
    function updateHint() {
        const start = Number(el('referenceStart').value);
        el('referenceStartHint').textContent = start > 0
            ? `The reference video will start at ${start}s. Its first frame will be extracted after trimming, so they match.`
            : 'First frame selected. Your original video is copied without re-encoding.';
    }
    el('referenceFirstFrame').onclick = () => {
        el('referenceStart').value = '0';
        el('referenceVideoPreview').currentTime = 0;
        updateHint();
    };
    el('referenceCurrentFrame').onclick = () => {
        el('referenceVideoPreview').pause();
        el('referenceStart').value = el('referenceVideoPreview').currentTime.toFixed(3);
        updateHint();
    };
    el('referenceStart').oninput = updateHint;
    el('referencePrepare').onclick = async () => {
        if (busy) return;
        const file = el('referenceVideoInput').files[0];
        const start = Number(el('referenceStart').value);
        const duration = el('referenceVideoPreview').duration;
        if (!file) return status('Choose a reference video first.');
        if (!Number.isFinite(start) || start < 0 || (Number.isFinite(duration) && start >= duration)) return status('Choose a time inside the video.');
        clearResults();
        setBusy(true);
        status('Uploading your video to the local app…');
        const body = new FormData(); body.append('video', file); body.append('start_seconds', start);
        try {
            const data = await api('/api/reference/prepare', {method:'POST', body});
            project = {id:data.id};
            poll(data.id);
        } catch (e) { status(e.message); setBusy(false); }
    };
    el('referenceImageInput').onchange = async () => {
        const file = el('referenceImageInput').files[0];
        if (!file || !project) return;
        const body = new FormData(); body.append('image', file);
        body.append('resize', el('referenceResizeImage').checked ? 'true' : 'false');
        el('referenceImageInput').disabled = true;
        try { showProject(await api(`/api/reference/${project.id}/image`, {method:'POST', body})); }
        catch (e) { status(e.message); }
        finally { el('referenceImageInput').disabled = false; el('referenceImageInput').value = ''; }
    };
    el('referenceOpenFolder').onclick = async () => {
        if (!project) return;
        try { await api('/api/open_folder', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({path:project.folder})}); }
        catch (e) { status(e.message); }
    };
    el('referenceProjects').onchange = async () => {
        const id = el('referenceProjects').value;
        clearResults();
        if (!id) { status('Choose a video to prepare a new reference set.'); return; }
        try {
            project = {id};
            const data = await api(`/api/reference/${id}`);
            el('referenceStart').value = data.start_seconds;
            el('referenceVideoInput').value = '';
            if (data.video) el('referenceVideoPreview').src = mediaUrl(data.video);
            updateHint(); showProject(data);
            if (data.state === 'processing') { setBusy(true); poll(id); }
        } catch (e) { status(e.message); }
    };

    // --- Phase 6: Carousel & Still Image Studio ---
    const cStatus = text => { if (el('carouselStatus')) el('carouselStatus').textContent = text; };
    async function refreshCarousels() {
        if (!el('carouselProjects')) return;
        const rows = await api('/api/carousel/projects');
        const sel = el('carouselProjects');
        sel.replaceChildren(new Option('New carousel', ''));
        for (const r of rows) sel.add(new Option(`${r.name} (${r.slides?.length || 0} slides)`, r.id));
        if (carousel) sel.value = carousel.id;
    }
    function renderCarousel(data) {
        carousel = data;
        if (!el('carouselSlides')) return;
        el('carouselAspect').value = data.settings.aspect || 'portrait';
        el('carouselFit').value = data.settings.fit || 'fill';
        if (el('carouselFilter')) el('carouselFilter').value = data.settings.filter || 'none';
        el('carouselMargin').value = data.settings.margin || 0;
        el('carouselBg').value = data.settings.background || '#141526';
        if (el('carouselFont')) el('carouselFont').value = data.settings.font || 'Montserrat';
        if (el('carouselFontSize')) el('carouselFontSize').value = data.settings.font_size ?? 4.5;
        if (el('carouselTextColor')) el('carouselTextColor').value = data.settings.text_color || '#ffffff';
        if (el('carouselTextBg')) el('carouselTextBg').checked = data.settings.text_bg !== false;
        el('carouselCaption').value = data.settings.shared_caption || '';
        el('carouselApply').disabled = false;
        el('carouselExport').href = `/api/carousel/${data.id}/export`;
        el('carouselExport').hidden = false;
        cStatus(`Carousel ready: ${data.slides.length} slides (${data.settings.aspect}). Reorder, rotate, or add text overlays.`);
        const grid = el('carouselSlides');
        grid.replaceChildren();
        data.slides.forEach((s, idx) => {
            const card = document.createElement('div'); card.className = 'ref-card';
            const img = document.createElement('img');
            img.src = `/api/carousel/${data.id}/media/${encodeURIComponent(s.file)}?t=${Date.now()}`;
            img.alt = `Slide ${idx + 1}`;
            const cap = document.createElement('input');
            cap.type = 'text'; cap.placeholder = `Slide ${idx + 1} text…`; cap.value = s.caption || '';
            cap.onchange = () => updateCarousel({slides: [{id: s.id, caption: cap.value}]});
            const row = document.createElement('div'); row.className = 'ref-actions';
            const left = document.createElement('button'); left.type = 'button'; left.textContent = '←'; left.disabled = idx === 0;
            left.onclick = () => {
                const order = data.slides.map(x => x.id);
                [order[idx - 1], order[idx]] = [order[idx], order[idx - 1]];
                updateCarousel({order});
            };
            const right = document.createElement('button'); right.type = 'button'; right.textContent = '→'; right.disabled = idx === data.slides.length - 1;
            right.onclick = () => {
                const order = data.slides.map(x => x.id);
                [order[idx], order[idx + 1]] = [order[idx + 1], order[idx]];
                updateCarousel({order});
            };
            const rot = document.createElement('button'); rot.type = 'button'; rot.textContent = '↻ 90°';
            rot.onclick = () => updateCarousel({slides: [{id: s.id, rotate: ((s.rotate || 0) + 90) % 360}]});
            row.append(left, right, rot);
            card.append(img, cap, row);
            grid.append(card);
        });
    }
    async function updateCarousel(patch) {
        if (!carousel) return;
        try {
            const updated = await api(`/api/carousel/${carousel.id}/update`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(patch)
            });
            renderCarousel(updated);
        } catch (e) { cStatus(e.message); }
    }
    if (el('carouselCreate')) {
        el('carouselCreate').onclick = async () => {
            const files = el('carouselInput').files;
            if (!files?.length) return cStatus('Choose at least one photo first.');
            const body = new FormData();
            for (const f of files) body.append('images', f);
            body.append('aspect', el('carouselAspect').value);
            try {
                const created = await api('/api/carousel/create', {method: 'POST', body});
                await refreshCarousels();
                renderCarousel(created);
            } catch (e) { cStatus(e.message); }
        };
        el('carouselApply').onclick = () => updateCarousel({
            settings: {
                aspect: el('carouselAspect').value,
                fit: el('carouselFit').value,
                filter: el('carouselFilter') ? el('carouselFilter').value : 'none',
                margin: Number(el('carouselMargin').value || 0),
                background: el('carouselBg').value,
                font: el('carouselFont') ? el('carouselFont').value : 'Montserrat',
                font_size: el('carouselFontSize') ? Number(el('carouselFontSize').value || 4.5) : 4.5,
                text_color: el('carouselTextColor') ? el('carouselTextColor').value : '#ffffff',
                text_bg: el('carouselTextBg') ? el('carouselTextBg').checked : true,
                shared_caption: el('carouselCaption').value
            }
        });
        el('carouselProjects').onchange = async () => {
            const cid = el('carouselProjects').value;
            if (!cid) return;
            try { renderCarousel(await api(`/api/carousel/${cid}`)); } catch (e) { cStatus(e.message); }
        };
    }
})();
