(() => {
    const el = id => document.getElementById(id);
    const dialog = el('referenceDialog');
    let project = null, previewUrl = null, pollTimer = null, busy = false;
    const status = text => { el('referenceStatus').textContent = text; };
    const mediaUrl = name => '/api/media/' + ['Kling References', project.id, name].map(encodeURIComponent).join('/');
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
        for (const id of ['referenceOriginalImage', 'referenceEditedImage', 'referenceFrameDownload', 'referenceExport']) {
            el(id).hidden = true;
            el(id).removeAttribute('src');
            el(id).removeAttribute('href');
        }
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
        try { await refreshProjects(); } catch (e) { status(e.message); }
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
})();
