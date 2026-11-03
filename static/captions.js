/* Timing validation ships with the editor to avoid mixed-version script loads. */
const CaptionTiming = (() => {
    function validate(cues, duration) {
        let previous=0;
        for(const c of [...cues].sort((a,b)=>a.start-b.start)) {
            if(!Number.isFinite(c.start)||!Number.isFinite(c.end)||c.start<0||c.end>duration||c.end<=c.start)
                throw Error('A caption must start before it ends and stay inside the video.');
            if(c.start<previous-.001)throw Error('Caption lines cannot overlap.');
            previous=c.end;
            let wordEnd=c.start;
            for(const w of c.words||[]) {
                if(!Number.isFinite(w.start)||!Number.isFinite(w.end)||w.start<wordEnd-.005||w.end>c.end+.005||w.end<=w.start)
                    throw Error('Word timings must run forwards, stay inside the line, and not overlap.');
                wordEnd=w.end;
            }
        }
    }
    function visualizerBars(peaks, duration, timeSec, width, height, style={}) {
        const rint = val => Math.floor(val + 0.5);
        const mode = style.visualizer_style || 'spectrum';
        const pos = style.visualizer_position || 'bottom';
        const visH = Number(style.visualizer_height ?? 18);
        const sens = Number(style.visualizer_sensitivity ?? 1.0);
        const count = mode === 'spectrum' ? 36 : 48;
        const pts = (Array.isArray(peaks) && peaks.length > 0) ? peaks : Array(64).fill(0.25);
        const n = pts.length;
        let maxP = 0.01;
        for (const p of pts) if (Number(p) > maxP) maxP = Number(p);
        const dur = Math.max(0.1, Number(duration || 1.0));
        const t = Math.max(0.0, Math.min(dur, Number(timeSec || 0)));
        const center = (t / dur) * (n - 1);
        const bandH = height * (visH / 100.0);
        const startX = width * 0.06;
        const usableW = width * 0.88;
        const stepX = usableW / count;
        const barW = Math.max(2.0, stepX * (mode === 'spectrum' ? 0.65 : 0.75));
        const rects = [];
        for (let i = 0; i < count; i++) {
            let level;
            if (mode === 'spectrum') {
                const idx0 = Math.max(0, Math.min(n - 1, rint(center)));
                const idx1 = Math.max(0, Math.min(n - 1, rint(center + (i - count / 2.0) * 0.5)));
                const idx2 = Math.max(0, Math.min(n - 1, rint(center + ((i % 7) - 3) * 1.5)));
                const p0 = Number(pts[idx0]) / maxP;
                const p1 = Number(pts[idx1]) / maxP;
                const p2 = Number(pts[idx2]) / maxP;
                const u = i / Math.max(1, count - 1);
                const arch = 0.55 + 0.45 * Math.sin(u * Math.PI);
                const ripple = 0.72 + 0.28 * Math.sin(t * (7.0 + (i % 5) * 1.3) + i * 0.65);
                const raw = (0.5 * p0 + 0.3 * p1 + 0.2 * p2) * arch * ripple * sens;
                level = p0 < 0.005 ? 0.04 : Math.min(1.0, Math.max(0.04, Math.sqrt(Math.max(0.0, raw))));
            } else {
                const span = Math.max(8.0, n * 0.04);
                const offset = ((i / Math.max(1, count - 1)) - 0.5) * span;
                const idx = Math.max(0, Math.min(n - 1, rint(center + offset)));
                const p = Number(pts[idx]) / maxP;
                const waveMod = 0.8 + 0.2 * Math.cos(t * 8.0 + i * 0.4);
                const raw = p * waveMod * sens;
                level = p < 0.005 ? 0.04 : Math.min(1.0, Math.max(0.04, Math.sqrt(Math.max(0.0, raw))));
            }
            const bh = Math.max(2.0, level * bandH);
            const x1 = rint(startX + i * stepX);
            const x2 = rint(x1 + barW);
            let y1, y2;
            if (mode === 'waveform' || pos === 'center') {
                const midY = pos === 'bottom' ? (height - bandH * 0.5 - height * 0.02) : pos === 'top' ? (bandH * 0.5 + height * 0.02) : (height * 0.5);
                y1 = rint(midY - bh * 0.5);
                y2 = rint(midY + bh * 0.5);
            } else if (pos === 'top') {
                y1 = 0;
                y2 = rint(bh);
            } else {
                y1 = rint(height - bh);
                y2 = rint(height);
            }
            rects.push([x1, y1, x2, y2]);
        }
        return rects;
    }
    function detectBeats(peaks, duration) {
        if (!Array.isArray(peaks) || peaks.length < 8 || !(duration > 0)) return [];
        const n = peaks.length;
        let maxP = 0.01;
        for (const p of peaks) if (Number(p) > maxP) maxP = Number(p);
        const win = Math.max(3, Math.round(n / Math.max(4, duration * 2)));
        const beats = [];
        let lastBeat = -1;
        for (let i = 2; i < n - 2; i++) {
            const val = Number(peaks[i]);
            if (val < maxP * 0.35) continue;
            if (val < Number(peaks[i-1]) || val < Number(peaks[i+1]) || val < Number(peaks[i-2]) || val < Number(peaks[i+2])) continue;
            let sum = 0, cnt = 0;
            for (let j = Math.max(0, i - win); j <= Math.min(n - 1, i + win); j++) { sum += Number(peaks[j]); cnt++; }
            if (val > (sum / Math.max(1, cnt)) * 1.3) {
                const sec = Number(((i / (n - 1)) * duration).toFixed(3));
                if (sec - lastBeat >= 0.32) {
                    beats.push(sec);
                    lastBeat = sec;
                }
            }
        }
        return beats;
    }
    function splitSequence(sequence, total, time, loop=true) {
        const fixed=sequence.reduce((sum,c)=>sum+Math.max(0,Number(c.duration)||0),0);
        const autos=sequence.filter(c=>!(Number(c.duration)>0)).length;
        const auto=autos?Math.max(.2,total>fixed?(total-fixed)/autos:total/sequence.length):5;
        const clips=[];let t=0;
        while(t<total-.05) {
            for(const c of sequence) {
                if(t>=total-.05)break;
                const duration=Math.min(Number(c.duration)>0?Number(c.duration):auto,total-t);
                if(duration<.05)throw Error('Clip duration is too short.');
                clips.push({...c,duration});t+=duration;
                if(clips.length>30)throw Error('Splitting this repeated sequence would exceed 30 clips. Increase clip durations first.');
            }
            if(!loop||autos||!sequence.length)break;
        }
        if(clips.length && t<total-.05)clips[clips.length-1].duration+=total-t;
        t=0;
        for(let i=0;i<clips.length;i++) {
            const c=clips[i],end=t+c.duration;
            if(time>=t&&time<end) {
                const left=Number((time-t).toFixed(3)),right=Number((end-time).toFixed(3));
                if(left<.1||right<.1)throw Error('Split point must be at least 0.1 seconds from a clip boundary.');
                if(clips.length>=30)throw Error('A sequence can contain at most 30 clips.');
                clips.splice(i,1,{...c,duration:left},{...c,duration:right,source_start:(Number(c.source_start)||0)+left*(Number(c.speed)||1)});
                return clips;
            }
            t=end;
        }
        throw Error('Place the playhead inside a clip.');
    }
    function splitCaption(cue,time,newId){
        const left=JSON.parse(JSON.stringify(cue)),right=JSON.parse(JSON.stringify(cue));
        const tokens=cue.text.trim().split(/\s+/);
        if(tokens.length<2||time<=cue.start||time>=cue.end)throw Error('Choose a split inside a caption with at least two words.');
        let index=Math.max(1,Math.min(tokens.length-1,Math.round(tokens.length*(time-cue.start)/(cue.end-cue.start))));
        let cut=time;
        if(cue.words?.length===tokens.length){
            index=1;
            for(let i=1;i<cue.words.length;i++)if(Math.abs(cue.words[i].start-time)<Math.abs(cue.words[index].start-time))index=i;
            cut=cue.words[index].start;
            if(cue.words[index-1].end>cut)throw Error('Fix overlapping word timings before splitting.');
            left.words=cue.words.slice(0,index);right.words=cue.words.slice(index);
        }else{left.words=[];right.words=[];}
        left.end=cut;right.start=cut;right.id=newId;
        left.text=tokens.slice(0,index).join(' ');right.text=tokens.slice(index).join(' ');
        for(const part of [left,right])for(const tr of Object.values(part.translations||{})){tr.status='stale';tr.locked=false;tr.note='Original line split. Review and adapt this translation.';}
        return [left,right];
    }
    function mergeCaptions(left,right){
        const merged=JSON.parse(JSON.stringify(left));merged.end=right.end;merged.text=left.text+' '+right.text;
        merged.words=left.words?.length&&right.words?.length?[...left.words,...right.words]:[];
        // Combined text is kept but marked stale (empty source): it always needs review, never auto-approves.
        const languages=new Set([...Object.keys(left.translations||{}),...Object.keys(right.translations||{})]);
        merged.translations=Object.fromEntries([...languages].map(lang=>[lang,{
            text:[left.translations?.[lang]?.text,right.translations?.[lang]?.text].filter(Boolean).join(' '),
            source:'',status:'stale',locked:false,note:'Original lines merged. Review this combined translation.'}]));
        return merged;
    }
    /* Translation record contract (docs/v5-architecture.md): source = sha256(normalizeWs(cue.text)).
       The whitespace class is identical to assets/lyric_tracks.py so both sides hash the same bytes. */
    const WHITESPACE=/[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/g;
    const TRANSLATION_STATUSES=['approved','review','stale'];
    function normalizeWs(text){return String(text??'').replace(WHITESPACE,' ').replace(/^ +| +$/g,'');}
    async function sourceHash(text){
        const digest=await globalThis.crypto.subtle.digest('SHA-256',new TextEncoder().encode(normalizeWs(text)));
        return Array.from(new Uint8Array(digest),x=>x.toString(16).padStart(2,'0')).join('');
    }
    /** The only writer of cue.translations records. Manual edits are approved; Copilot edits land in review. */
    async function setCueTranslation(cue,lang,text,{status='approved',locked,note,origin='user'}={}){
        if(!/^[a-z]{2,3}$/.test(String(lang)))throw Error('Choose a supported translation language.');
        if(!TRANSLATION_STATUSES.includes(status))throw Error('Invalid translation review state.');
        const value=String(text??'');
        if(value.length>2000)throw Error('A translation must contain at most 2,000 characters.');
        let lineText,source;
        do{lineText=cue.text;source=await sourceHash(lineText);}while(cue.text!==lineText);
        const previous=cue.translations?.[lang]||{};
        const record={text:value.trim(),source,status,locked:Boolean(locked??previous.locked??false),
            note:String(note??(origin==='copilot'?'Suggested by Copilot. Review, then Keep to approve.':previous.note??'')).slice(0,500)};
        cue.translations={...(cue.translations||{}),[lang]:record};
        return record;
    }
    function translationState(cue,lang,style={}){
        const entry=cue?.translations?.[lang];
        const hasText=Boolean(entry?.text?.trim());
        const duplicate=hasText&&normalizeWs(entry.text)===normalizeWs(cue.text);
        return {entry,hasText,pending:hasText&&entry.status!=='approved',
            hiddenDuplicate:duplicate&&entry.status==='approved'&&style.track_mode==='both'&&style.hide_duplicate_translation!==false&&!cue.show_duplicate_translation};
    }
    /* Embedded copy of static/anim_constants.json (fallback if the fetch fails); the export reads the same file. */
    const ANIM_DEFAULTS={
        fade:{duration:0.18},
        pop:{duration:0.16,from_scale:0.85},
        zoom_in:{duration:0.2,from_scale:0.7},
        slide_up:{duration:0.18,offset:0.035},
        typewriter:{char_duration:0.045,min_duration:0.4,word_reveal:0.85,min_word:0.08},
        word_pop:{scale:1.15},
        glow:{radius:0.0066},
        title:{fade_in:0.25,fade_out:0.35,y:0.28,scale:1.25,pad_x:0.45,pad_y:0.14,radius:0.28}
    };
    function mergeAnimConstants(loaded){
        const result=JSON.parse(JSON.stringify(ANIM_DEFAULTS));
        for(const [group,values] of Object.entries(result)){
            for(const key of Object.keys(values)){
                const value=Number(loaded?.[group]?.[key]);
                if(Number.isFinite(value)&&value>=0)values[key]=value;
            }
        }
        return result;
    }
    function entranceScale(anim,elapsed,constants=ANIM_DEFAULTS){
        const spec=constants[anim];
        const progress=Math.min(1,Math.max(0,elapsed)/spec.duration);
        return spec.from_scale+(1-spec.from_scale)*progress;
    }
    return {validate, visualizerBars, detectBeats, splitSequence, splitCaption, mergeCaptions,
        normalizeWs, sourceHash, setCueTranslation, translationState, ANIM_DEFAULTS, mergeAnimConstants, entranceScale};
})();
if(typeof module!=="undefined" && module.exports) module.exports=CaptionTiming;
/* Local caption editor. All imported text is rendered through textContent. */
(() => {
    'use strict';
    if(typeof document==='undefined')return;
    const $ = id => document.getElementById(id), video = $('video');
    const token = document.querySelector('meta[name="media-token"]').content;
    const copy = value => JSON.parse(JSON.stringify(value));
    const styleKeys = ['layout_enabled','line_spacing','letter_spacing','box_width','horizontal','alignment','box_padding','box_radius','track_mode','translation_language','translation_size','translation_color','translation_gap','hide_duplicate_translation','font','size','color','highlight','outline','position','background','karaoke','cumulative','word_pop','animation','glow','visualizer','visualizer_style','visualizer_position','visualizer_height','visualizer_sensitivity','visualizer_color','video_filter','vignette','film_grain','sharpen','chromatic','noise_cancel','voice_isolation','audio_effect'];
    const styleChecks = ['layout_enabled','hide_duplicate_translation','background','karaoke','cumulative','word_pop','visualizer','vignette','noise_cancel','voice_isolation'];
    const styleNumbers = ['line_spacing','letter_spacing','box_width','horizontal','box_padding','box_radius','translation_size','translation_gap','size','outline','position','glow','visualizer_height','visualizer_sensitivity','film_grain','sharpen','chromatic'];
    const cssVideoFilters = {
        none:'',
        beauty:'blur(0.8px) contrast(1.08) brightness(1.05) saturate(1.15)',
        vhs:'contrast(1.16) saturate(1.12) drop-shadow(2px 0 0 rgba(255,0,80,0.5)) drop-shadow(-2px 0 0 rgba(0,242,234,0.5))',
        teal_orange:'contrast(1.2) saturate(1.25) hue-rotate(-12deg) sepia(0.15)',
        vaporwave:'contrast(1.25) saturate(1.65) hue-rotate(320deg)',
        bling:'contrast(1.25) brightness(1.08) saturate(1.35) drop-shadow(0 0 4px rgba(255,255,255,0.7))',
        fisheye:'contrast(1.05)',
        noir:'contrast(1.4) saturate(0.5) brightness(0.96)',
        bw:'grayscale(1)',
        sepia:'sepia(1)',
        vintage:'sepia(0.45) contrast(1.1) brightness(0.95)',
        cyberpunk:'contrast(1.25) saturate(1.6) hue-rotate(-12deg)',
        warm:'sepia(0.22) saturate(1.2) brightness(1.03)',
        cool:'saturate(1.1) contrast(1.08) hue-rotate(12deg)',
        dramatic:'contrast(1.35) brightness(0.96) saturate(0.85)',
        dreamy:'blur(1.2px) brightness(1.06) contrast(0.95) saturate(1.2)'
    };
    let ANIM = CaptionTiming.mergeAnimConstants(CaptionTiming.ANIM_DEFAULTS);
    if(typeof fetch==='function'){
        fetch('/static/anim_constants.json').then(r=>r.ok?r.json():null)
            .then(data=>{if(data&&typeof data==='object'&&data.fade){ANIM=CaptionTiming.mergeAnimConstants(data);}})
            .catch(()=>{});
    }
    let project = null, selected = -1, history = [], future = [], dirty = false;
    let compFilledSource = null;
    let saveTimer, pollTimer, saving = null, generation = 0, busy = false, dragging = false, pendingPreview = false;
    const clockNow = () => (typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now());
    let animPreviewStart = 0, animPreviewType = null;
    function triggerAnimationPreview(type) {
        animPreviewType = type || (project?.style?.animation) || 'none';
        animPreviewStart = clockNow();
        drawCaption();
    }
    const say = (text, error = false) => {
        $('status').textContent = text; $('status').classList.toggle('error', error);
        document.querySelectorAll('dialog[open] .dialogStatus').forEach(node=>{node.textContent=error?text:'';});
    };
    /** Append a [Set up AI] action to the status line for a missing local model (never auto-downloads). */
    function offerSetup(hint) {
        if (!hint || typeof window.openAISetup !== 'function') return;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'status-setup';
        button.textContent = 'Set up AI';
        button.onclick = () => window.openAISetup(hint);
        $('status').append(' ', button);
    }
    const media = name => `/api/captions/${project.id}/media/${encodeURIComponent(name)}`;
    const draftKey = kind => `creator-${kind}-${project.id}`;
    function readDraft(kind) {try{return JSON.parse(localStorage.getItem(draftKey(kind)));}catch{return null;}}
    function storeDraft(kind, value) {try{if(value===null)localStorage.removeItem(draftKey(kind));else localStorage.setItem(draftKey(kind),JSON.stringify(value));}catch{}}
    const snapshot = () => copy({cues:project.cues, style:project.style, timing:project.timing, translation_settings:project.translation_settings||{}});
    const current = () => project?.cues[selected];
    const fmt = t => `${Math.floor(t/60)}:${(t%60).toFixed(2).padStart(5,'0')}`;
    async function api(url, method = 'GET', body) {
        const options = {method, headers:{'X-Media-Token':token}};
        if (body instanceof FormData) options.body = body;
        else if (body !== undefined) { options.headers['Content-Type']='application/json'; options.body=JSON.stringify(body); }
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({error:'The app could not complete this request. Restart it if the connection was lost.'}));
        if (!response.ok) throw Object.assign(new Error(data.error || 'Request failed'), {status: response.status, setupHint: data.setup_hint});
        return data;
    }
    const act = fn => async event => { try { await fn(event); } catch (e) { say(e.message, true); offerSetup(e.setupHint); } };
    function checkpoint() { history.push(snapshot()); if (history.length>80) history.shift(); future=[]; }
    function changed(redraw = true) {
        for(const cue of project.cues){if(!cue.id)cue.id='cue_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2);}

        if (redraw) {
            const cue=current();project.cues.sort((a,b)=>a.start-b.start);selected=project.cues.indexOf(cue);
        }
        dirty=true; generation++;storeDraft('captions',{revision:project.revision,data:snapshot()}); $('saveStatus').textContent='Unsaved changes';
        clearTimeout(saveTimer); saveTimer=setTimeout(() => save().catch(e=>say(e.message,true)),900);
        if (redraw) { drawTimeline(); drawList(); fillSelection(); }
        drawCaption();drawKaraokeSummary();
    }
    function edit(fn, redraw = true) {
        if (!project || busy) return;
        checkpoint(); fn(); changed(redraw);
    }
    function timingEdit(fn) {
        if(!project||busy)return;
        const before=snapshot(), index=selected;
        try {
            fn();CaptionTiming.validate(project.cues,project.duration);
        } catch(e) {
            Object.assign(project,before);selected=index;
            fillSelection();say(e.message,true);return;
        }
        history.push(before);if(history.length>80)history.shift();future=[];changed();
    }
    async function save() {
        clearTimeout(saveTimer);
        if (saving) { await saving; return save(); }
        if (!project || !dirty || busy) return;
        const pid=project.id, version=generation, payload={...snapshot(),revision:project.revision};
        $('saveStatus').textContent='Saving…';
        saving=api(`/api/captions/${pid}`,'PUT',payload).then(data=>{
            project.revision=data.revision;
            if(version===generation) { dirty=false;storeDraft('captions',null); $('saveStatus').textContent='All changes saved'; }
        }).catch(e=>{ $('saveStatus').textContent='Not saved — check the message'; throw e; }).finally(()=>{saving=null;});
        await saving;
        if(dirty) return save();
    }
    function setBusy(value) {
        busy=value;
        for(const node of document.querySelectorAll('.style input,.style select,.style button,#selection input,#selection textarea,#selection button,.toolbar button,.toolbar select,#export,#renderCheck,#srt,#save,#paste,#subtitleFile,#videoFile,#openLibrary,#projects,#reload,#undo,#redo')) node.disabled=value || !project;
        for(const node of document.querySelectorAll('#sequenceList input,#sequenceList select,#sequenceList button,#compSequenceList input,#compSequenceList select,#compSequenceList button'))node.disabled=value||!project;
        $('videoFile').disabled=value; $('projects').disabled=value; $('openLibrary').disabled=value;$('newSong').disabled=value;
        for(const id of ['editComposition','restoreComposition','duplicateProject','recoverEdits']) $(id).disabled=value||!project;
    }
    async function listProjects() {
        const items=await api('/api/captions');
        $('projects').replaceChildren(new Option('Saved projects…',''),...items.map(p=>new Option(p.name,p.id)));
        if(project) $('projects').value=project.id;
    }
    async function load(pid) {
        await save(); video.pause(); clearTimeout(pollTimer);
        clearTimeout(uploadDraftTimer);
        await saveUploadDraft();
        const nextProject=await api(`/api/captions/${pid}`);
        clearUploadInputs();
        project=nextProject; selected=project.cues.length?0:-1;
        history=[];future=[];dirty=false;generation=0;
        if(project.width) mountVideo();
        const ts=project.translation_settings||{};
        $('translationNotes').value=ts.notes||'';$('translationGlossary').value=ts.glossary||'';
        refreshTranslationModels();
        restoringUploads=true;
        try {refresh(); await restoreUploadDraft();} finally {restoringUploads=false;}
        await finishCompositionSubmission();
        await listProjects();
        if(project.state==='busy') poll();
    }
    function mountVideo() {
        const url=media(project.preview||'preview.mp4');
        if(video.getAttribute('src')!==url) video.src=url;
        $('empty').hidden=true; $('empty').style.display='none';
        fitVideo();
    }
    function fitVideo() {
        const stage = $('stage');
        if (!stage) return;
        const parent = stage.parentElement;
        const parentW = (parent && parent.clientWidth) ? parent.clientWidth : (window.innerWidth || 1200);
        const parentH = (parent && parent.clientHeight) ? parent.clientHeight : 600;

        const statusRow = parent?.querySelector ? parent.querySelector('.centerStatusRow') : null;
        const transport = parent?.querySelector ? parent.querySelector('.transport') : null;
        const playingHint = $('playingCaption');

        const statusH = (statusRow?.offsetHeight || 26);
        const transportH = (transport?.offsetHeight || 44);
        const hintH = (playingHint && playingHint.offsetHeight && playingHint.textContent ? playingHint.offsetHeight : 0);
        const pad = 24;

        const availH = Math.max(180, parentH - statusH - transportH - hintH - pad);
        const availW = Math.max(200, parentW - 32);

        const ratio = (project && project.width && project.height) ? (project.width / project.height) : (16 / 9);

        let h, w;
        if (availW / availH > ratio) {
            h = Math.round(availH);
            w = Math.round(h * ratio);
        } else {
            w = Math.round(availW);
            h = Math.round(w / ratio);
        }

        stage.style.height = h + 'px';
        stage.style.width = w + 'px';
        drawCaption();
    }
    function refresh() {
        setBusy(project?.state==='busy');
        if(!project) return;
        const translationSettings=project.translation_settings||{};
        $('translationNotes').value=translationSettings.notes||'';
        $('translationGlossary').value=translationSettings.glossary||'';
        const translationModel=translationSettings.model==='qwen3-4b-local'?'qwen3-4b':(translationSettings.model||'');
        if(translationModel&&!Array.from($('translationModel').options).some(o=>o.value===translationModel)) {
            $('translationModel').add(new Option(translationModel,translationModel));
        }
        $('translationModel').value=translationModel;
        for(const key of styleKeys) {
            if(key==='font' && project.style.font) {
                if(!Array.from($('font').options).some(o=>o.value===project.style.font)) {
                    $('font').add(new Option(project.style.font, project.style.font));
                }
            }
            if(styleChecks.includes(key)) $(key).checked=!!project.style[key]; else if(project.style[key]!==undefined) $(key).value=project.style[key];
        }
        $('saveStatus').textContent=dirty?'Unsaved changes':'All changes saved';
        $('timingNote').textContent=({
            manual:'Add captions, paste lyrics, or transcribe the audio.',
            estimated:'Evenly spaced estimates — adjust timing while listening. These lyrics have not been aligned to the audio.',
            automatic:'Automatic transcription — review words and timing, especially for songs.',
            aligned:'Lyrics matched to audio — review timing, especially sustained notes and repeated choruses. Every word remains editable.',
            imported:'Imported timings — review synchronization with this video.',
            edited:'Review timing while listening. Word timings are editable below.'
        })[project.timing] || 'Review timing while listening.';
        say(project.status,project.state==='error');
        if(project.state==='error')offerSetup(project.setup_hint);
        drawTimeline();drawList();fillSelection();drawDownloads();drawCaption();drawKaraokeSummary();drawComposition();
        $('reviewLyrics').hidden=!project.lyric_proposal;
    }
    function poll() {
        clearTimeout(pollTimer);
        pollTimer=setTimeout(async()=>{
            try {
                project=await api(`/api/captions/${project.id}`);
                if(project.state==='busy') {say(project.status);poll();return;}
                await finishCompositionSubmission();
                if(project.width) mountVideo();
                selected=project.cues.length?Math.max(0,Math.min(selected,project.cues.length-1)):-1; refresh();
                if(pendingPreview && project.last_render && project.last_render.startsWith('check_') && project.state==='ready') {
                    $('renderVideo').src=media(project.last_render); $('renderDialog').showModal();
                }
                pendingPreview=false;
                if(project.state==='ready' && project.lyric_proposal) showLyricReview();
                if(project.state==='ready' && project.translation_proposal) showTranslationReview();
                await listProjects();
            } catch(e) {say(e.message,true);setBusy(false);}
        },1000);
    }
    function drawVisualizer() {
        const vcanvas=$('stageVisualizer');
        if(!project || !vcanvas) return;
        const s=project.style||{};
        const showVis=!!s.visualizer;
        vcanvas.hidden=!showVis;
        if(!showVis) return;
        const w=Math.max(1,$('stage').clientWidth||600), h=Math.max(1,$('stage').clientHeight||380);
        vcanvas.width=w; vcanvas.height=h;
        const vctx=vcanvas.getContext('2d');
        vctx.fillStyle=s.visualizer_color||'#bba6ff';
        vctx.globalAlpha=0.85;
        const rects=CaptionTiming.visualizerBars(project.peaks,project.duration,video.currentTime,w,h,s);
        rects.forEach(([x1,y1,x2,y2])=>vctx.fillRect(x1,y1,Math.max(1,x2-x1),Math.max(1,y2-y1)));
    }
    let sharedLayoutKey='',sharedLayoutRows=null,sharedLayoutPending='';
    function drawSharedLayout(box,cue,s,h){
        const key=JSON.stringify([project.id,cue,s,project.width,project.height]);
        if(key!==sharedLayoutKey){
            if(sharedLayoutPending!==key){
                sharedLayoutPending=key;
                api(`/api/captions/${project.id}/layout`,'POST',{cue,style:s,editor_preview:true}).then(data=>{
                    if(sharedLayoutPending===key){sharedLayoutKey=key;sharedLayoutRows=data.rows;drawCaption();}
                }).catch(e=>{if(sharedLayoutPending===key){sharedLayoutKey=key;sharedLayoutRows=[];say(e.message,true);}});
            }
            return;
        }
        box.replaceChildren();Object.assign(box.style,{left:'0',width:'100%',top:'0',height:'100%',transform:'none',opacity:'1'});
        function appendFontRuns(node,text,offset,runs){
            if(!runs){node.textContent=text;return;}
            let cursor=0;
            for(const run of runs){
                const from=Math.max(offset,cursor),to=Math.min(offset+text.length,cursor+run.text.length);
                if(to>from){const span=document.createElement('span');span.style.fontFamily=JSON.stringify(run.font);span.textContent=text.slice(from-offset,to-offset);node.append(span);}
                cursor+=run.text.length;
            }
        }
        for(const row of sharedLayoutRows||[]){
            const line=document.createElement('div');const xShift=row.alignment==='left'?'0':row.alignment==='right'?'-100%':'-50%';
            const rowPadding=s.background?h*(s.box_padding||0)/100:0;
            const originX=row.alignment==='left'?`${rowPadding}px`:row.alignment==='right'?`calc(100% - ${rowPadding}px)`:'50%';
            Object.assign(line.style,{position:'absolute',left:(row.x/project.width*100)+'%',top:(row.y/project.height*100)+'%',
                transformOrigin:`${originX} calc(100% - ${rowPadding}px)`,
                boxSizing:'content-box',width:s.background?h*row.width/project.height+'px':'max-content',
                transform:`translate(${xShift},-100%)`,fontSize:h*row.size/100+'px',whiteSpace:'pre',lineHeight:'1',marginLeft:s.background?(row.alignment==='left'?-1:row.alignment==='right'?1:0)*h*(s.box_padding||0)/100+'px':'0',marginTop:s.background?h*(s.box_padding||0)/100+'px':'0',
                letterSpacing:h*(row.letter_spacing??s.letter_spacing??0)/100+'px',color:row.color,textAlign:row.alignment,
                background:s.background?'rgba(10,12,20,.78)':'transparent',padding:s.background?h*(s.box_padding||0)/100+'px':'0',borderRadius:h*(s.box_radius||0)/100+'px'});
            if(row.pending){
                // Editor-only: unapproved translations stay visible but dimmed; exports omit them.
                line.classList.add?.('pendingTranslation');
                Object.assign(line.style,{opacity:'.45',fontStyle:'italic',outline:'1px dashed rgba(255,214,10,.75)',outlineOffset:'3px'});
                line.title='Needs review: not included in exports until you Keep it.';
            }
            if(Number(s.glow)>0)line.style.textShadow=`0 0 ${(h*ANIM.glow.radius*Number(s.glow)).toFixed(1)}px ${s.highlight}`;
            const elapsed=video.currentTime-cue.start,remaining=cue.end-video.currentTime;
            const anim=s.animation==='pop_in'?'pop':s.animation, tw=ANIM.typewriter;
            if(row.track==='original'&&anim==='fade')line.style.opacity=String(Math.max(0,Math.min(1,elapsed/ANIM.fade.duration,remaining/ANIM.fade.duration)));
            if(row.track==='original'&&(anim==='pop'||anim==='zoom_in')&&elapsed<ANIM[anim].duration)line.style.transform+=` scale(${CaptionTiming.entranceScale(anim,elapsed,ANIM)})`;
            if(row.track==='original'&&anim==='slide_up'&&elapsed<ANIM.slide_up.duration)line.style.marginTop=(rowPadding+h*ANIM.slide_up.offset*(1-Math.max(0,elapsed)/ANIM.slide_up.duration))+'px';
            if(row.track==='original' && row.words.length){
                let wordOffset=0;
                row.words.forEach((w,i)=>{if(anim==='typewriter'&&w.start>video.currentTime)return;if(i)line.append(' ');const word=document.createElement('span');word.textContent=w.text;
                    if(anim==='typewriter'&&video.currentTime<w.end){const chars=Array.from(w.text);word.textContent=chars.slice(0,Math.max(1,Math.ceil(chars.length*(video.currentTime-w.start)/(Math.max(tw.min_word,w.end-w.start)*tw.word_reveal)))).join('');}
                    const active=w.start<=video.currentTime&&video.currentTime<w.end;
                    if(s.cumulative?video.currentTime>=w.start:s.karaoke&&active)word.style.color=s.highlight;
                    if(active&&s.word_pop)Object.assign(word.style,{display:'inline-block',transform:`scale(${ANIM.word_pop.scale})`});
                    const start=row.text.indexOf(w.text,wordOffset);wordOffset=start+w.text.length;
                    const visibleText=word.textContent;word.textContent='';appendFontRuns(word,visibleText,start,row.runs);
                    line.append(word);});
            }else {let text=row.text;if(row.track==='original'&&anim==='typewriter'){const chars=Array.from(row.text),d=Math.min(cue.end-cue.start,Math.max(tw.min_duration,chars.length*tw.char_duration));text=chars.slice(0,Math.max(1,Math.ceil(chars.length*elapsed/d))).join('');}appendFontRuns(line,text,0,row.runs);}
            box.append(line);
        }
    }
    function drawCaption() {
        const box=$('caption');box.replaceChildren();
        if(!project) return;
        drawVisualizer();
        let cue=project.cues.find(c=>c.start<=video.currentTime && c.end>video.currentTime);
        const s={...project.style,...(cue?.style_override||{})}, h=$('stage').clientHeight||380;
        const baked=project.composition||{};
        const fxAlreadyBaked = baked.fx_baked !== false && (baked.video_filter !== undefined || baked.vignette !== undefined);
        const activeFilter = (!fxAlreadyBaked || (s.video_filter||'none')!==(baked.video_filter||'none')) ? (s.video_filter||'none') : 'none';
        const rgbShift = (!fxAlreadyBaked ? (s.chromatic > 0) : ((s.chromatic||0)!==(baked.chromatic||0) && s.chromatic>0)) ? ` drop-shadow(-${Math.max(1,Math.round(s.chromatic/2))}px 0 0 rgba(255,0,80,.55)) drop-shadow(${Math.max(1,Math.round(s.chromatic/2))}px 0 0 rgba(0,220,255,.55))` : '';
        video.style.filter = ((cssVideoFilters[activeFilter]||'')+rgbShift).trim();
        video.style.borderRadius = activeFilter === 'fisheye' ? '28px' : '';
        video.style.transform = activeFilter === 'fisheye' ? 'scale(1.05)' : '';
        const vig=$('stageVignette');
        if(vig) vig.hidden = !(s.vignette || activeFilter==='vintage' || activeFilter==='dramatic');
        const compSet=project.studio?.settings||project.composition||{};
        const showTitle=Boolean(compSet.title_text && compSet.title_duration>0 && video.currentTime>=0 && video.currentTime<=compSet.title_duration);
        drawTitleCard(compSet,showTitle,s,h);
        const st=$('stageSticker');
        if(st) {
            // Use live form values so placement/face-snap changes show before Apply; fall back to saved settings.
            const stk={...compSet, ...liveStickerSettings()};
            const stickerAsset=project.studio?.assets?.sticker;
            const hasStk=(stickerAsset || selectedEmoji) && (Number(stk.sticker_duration)>0) && project.composition?.sticker_baked===false;
            const stkStart=Number(stk.sticker_start)||0;
            const stkDur=Number(stk.sticker_duration)||0;
            const inRange=hasStk && video.currentTime>=stkStart && video.currentTime<=(stkStart+stkDur);
            if(inRange) {
                st.hidden=false;
                const scalePct=Number(stk.sticker_scale)||25;
                const posX=stk.sticker_x!==undefined?Number(stk.sticker_x):85;
                const posY=stk.sticker_y!==undefined?Number(stk.sticker_y):15;
                const rawOp=stk.sticker_opacity!==undefined?Number(stk.sticker_opacity):1;
                const op=rawOp>1?rawOp/100:rawOp;
                // Same geometry as export: centre at x%/y%, width = video width × scale%, kept inside the frame.
                const stageW=$('stage').clientWidth||1, stageH=$('stage').clientHeight||1;
                const boxW=stageW*scalePct/100;
                const boxH=st.offsetHeight||boxW;
                st.style.width=boxW+'px';
                st.style.left=Math.max(0,Math.min(stageW-boxW,stageW*posX/100-boxW/2))+'px';
                st.style.top=Math.max(0,Math.min(stageH-boxH,stageH*posY/100-boxH/2))+'px';
                st.style.opacity=String(op);
                let stTransform='none';
                const elapsed=video.currentTime-stkStart;
                const remain=(stkStart+stkDur)-video.currentTime;
                if(stk.sticker_anim==='pop' && elapsed<0.22) {
                    stTransform=`scale(${(0.5+0.5*(elapsed/0.22)).toFixed(2)})`;
                } else if(stk.sticker_anim==='fade') {
                    const fade=Math.min(stk.sticker_duration/2,Number(stk.sticker_fade)||0);
                    if(fade>0)st.style.opacity=String(Math.max(0,Math.min(op, op*elapsed/fade, op*remain/fade)));
                } else if(stk.sticker_anim==='slide' && elapsed<0.22) {
                    stTransform=`translateY(${-stageH*0.04*(1-elapsed/0.22)}px)`;
                }
                st.style.transform=stTransform;
                if(selectedEmoji) {
                    const key='emoji:'+selectedEmoji;
                    if(st.dataset.src!==key) {
                        st.dataset.src=key;
                        st.replaceChildren();
                        const span=document.createElement('span');
                        span.textContent=selectedEmoji;
                        span.style.cssText='line-height:1;display:block;text-align:center;filter:drop-shadow(0 4px 12px rgba(0,0,0,0.6));';
                        st.append(span);
                    }
                    st.firstChild.style.fontSize=(boxW*0.86)+'px';
                } else if(stickerAsset) {
                    const src=media(stickerAsset.file);
                    if(st.dataset.src!==src) {
                        st.dataset.src=src;
                        st.innerHTML=`<img src="${src}" style="width:100%;height:auto;display:block;filter:drop-shadow(0 4px 12px rgba(0,0,0,0.6));" alt="sticker">`;
                    }
                }
            } else {
                st.hidden=true;
            }
        }

        const now = clockNow();
        let previewElapsed = animPreviewStart > 0 ? (now - animPreviewStart) / 1000 : null;
        let isPreviewing = previewElapsed !== null && previewElapsed < 1.35;
        if (!video.paused && isPreviewing) {
            animPreviewStart = 0;
            animPreviewType = null;
            isPreviewing = false;
            previewElapsed = null;
        } else if (!isPreviewing && animPreviewStart > 0) {
            animPreviewStart = 0;
            animPreviewType = null;
        }

        const activeAnim = isPreviewing ? (animPreviewType || s.animation || 'none') : (s.animation || 'none');

        if (isPreviewing && !cue) {
            cue = current() || project.cues[0] || {
                text: 'Preview Lyrics Animation',
                start: 0,
                end: 2.5,
                words: [
                    { start: 0.0, end: 0.6, text: 'Preview' },
                    { start: 0.6, end: 1.4, text: 'Lyrics' },
                    { start: 1.4, end: 2.3, text: 'Animation' }
                ]
            };
        }

        // Same constants and curves as the ASS export (static/anim_constants.json).
        const glowPx=h*ANIM.glow.radius*Number(s.glow||0);
        let animTransform='translateY(-100%)', animOpacity='1';
        const shownAnim=activeAnim==='pop_in'?'pop':activeAnim;
        if(cue && shownAnim && shownAnim!=='none') {
            const animElapsed = isPreviewing ? previewElapsed : Math.max(0, video.currentTime - cue.start);
            const animRemain = isPreviewing ? Math.max(0, 1.35 - previewElapsed) : Math.max(0, cue.end - video.currentTime);
            if(shownAnim==='fade') {
                animOpacity=String(Math.max(0,Math.min(1, animElapsed/ANIM.fade.duration, animRemain/ANIM.fade.duration)));
            } else if((shownAnim==='pop'||shownAnim==='zoom_in') && animElapsed < ANIM[shownAnim].duration) {
                animTransform=`translateY(-100%) scale(${CaptionTiming.entranceScale(shownAnim,animElapsed,ANIM).toFixed(3)})`;
            } else if(shownAnim==='slide_up' && animElapsed < ANIM.slide_up.duration) {
                const dy=h*ANIM.slide_up.offset*(1-animElapsed/ANIM.slide_up.duration);
                animTransform=`translateY(calc(-100% + ${dy.toFixed(1)}px))`;
            }
        }
        Object.assign(box.style,{fontFamily:`"${s.font}",Roboto,"Noto Sans KR",sans-serif`,fontSize:h*s.size/100+'px',color:s.color,
            top:s.position+'%',webkitTextStroke:`${2*h*s.outline/360}px black`,
            transform:animTransform,opacity:animOpacity,textShadow:glowPx>0?`0 0 ${glowPx.toFixed(1)}px ${s.highlight}`:'none'});
        if(isPreviewing && cue) {
            $('playingCaption').textContent = `Previewing animation: ${activeAnim} · ${cue.text}`;
        } else {
            $('playingCaption').textContent=cue ? 'Playing: '+cue.text+((s.karaoke||s.cumulative||s.word_pop)&&!cue.words?.length?' · No word timings — use Add karaoke timing.':'') : (showTitle ? 'Title card: '+compSet.title_text : '');
        }
        if(!cue) return;
        const content=document.createElement('span');
        content.style.background=s.background?'rgba(10,12,20,.78)':'transparent';
        if(s.background) Object.assign(content.style,{padding:'.14em .45em',borderRadius:'.28em',boxDecorationBreak:'clone',webkitBoxDecorationBreak:'clone'});

        const isTypewriter = (activeAnim === 'typewriter');
        let effectiveTime = video.currentTime;
        if(isPreviewing && isTypewriter && cue) {
            const cueSpan = Math.max(0.5, (cue.end || 2.5) - (cue.start || 0));
            const frac = Math.min(1, Math.max(0, previewElapsed / 1.15));
            effectiveTime = (cue.start || 0) + frac * cueSpan;
        }

        if(cue.words?.length) {
            const separators = cue.text.match(/\s+/g) || [];
            let isTypingActive = false;

            cue.words.forEach((w,i)=>{
                if(isTypewriter && w.start > effectiveTime) {
                    return;
                }
                if(i > 0) {
                    const prevWord = cue.words[i - 1];
                    if(!isTypewriter || prevWord.start <= effectiveTime) {
                        content.append(separators[i - 1] || ' ');
                    }
                }
                const span=document.createElement('span');
                const isWordActive = w.start <= effectiveTime && effectiveTime < w.end;
                const isWordLit = s.cumulative ? (effectiveTime >= w.start) : (isWordActive && s.karaoke);

                let wordText = w.text;
                if(isTypewriter && isWordActive) {
                    isTypingActive = true;
                    const wElapsed = Math.max(0, effectiveTime - w.start);
                    const wDur = Math.max(ANIM.typewriter.min_word, w.end - w.start);
                    const charProgress = Math.min(1, Math.max(0, wElapsed / (wDur * ANIM.typewriter.word_reveal)));
                    const letters = Array.from(w.text);
                    const charsToShow = Math.max(1, Math.min(letters.length, Math.ceil(letters.length * charProgress)));
                    wordText = letters.slice(0, charsToShow).join('');
                }

                span.textContent=wordText;
                if(isWordLit) span.style.color=s.highlight;
                if(isWordActive && s.word_pop) {
                    Object.assign(span.style,{display:'inline-block',transform:`scale(${ANIM.word_pop.scale})`});
                }
                content.append(span);
            });

            // The blinking cursor is an editor hint for the animation demo only; exports never draw it.
            if(isPreviewing && isTypewriter && (isTypingActive || (cue.words.length > 0 && effectiveTime < cue.words[0].start))) {
                const cursor = document.createElement('span');
                cursor.className = 'typewriterCursor';
                cursor.textContent = '▎';
                cursor.style.color = s.highlight || '#fff';
                content.append(cursor);
            }
        } else {
            let displayText = cue.text;
            let showCursor = false;
            if(isTypewriter) {
                let frac;
                if(isPreviewing) {
                    frac = Math.min(1, previewElapsed / 1.15);
                } else {
                    const elapsed = Math.max(0, video.currentTime - cue.start);
                    const typeDur = Math.min(cue.end - cue.start, Math.max(ANIM.typewriter.min_duration, (cue.text || '').length * ANIM.typewriter.char_duration));
                    frac = Math.min(1, elapsed / typeDur);
                }
                const visibleCount = Math.max(1, Math.min(cue.text.length, Math.ceil(frac * cue.text.length)));
                displayText = cue.text.slice(0, visibleCount);
                if(isPreviewing && visibleCount < cue.text.length) showCursor = true;
            }
            content.textContent = displayText;
            if(showCursor) {
                const cursor = document.createElement('span');
                cursor.className = 'typewriterCursor';
                cursor.textContent = '▎';
                cursor.style.color = s.highlight || '#fff';
                content.append(cursor);
            }
        }
        box.append(content);
        // Background plates use the shared server layout so rounded boxes match the export.
        if(cue&&(cue.style_override||s.layout_enabled||s.background||s.track_mode&&s.track_mode!=='original'))drawSharedLayout(box,cue,s,h);
        else Object.assign(box.style,{left:'6%',width:'88%',height:'auto'});
    }
    function drawTitleCard(compSet,show,s,h) {
        let card=$('stageTitle');
        if(!card){
            if(!show||!$('stage')?.append)return;
            card=document.createElement('div');card.id='stageTitle';card.className='stageTitle';$('stage').append(card);
        }
        card.hidden=!show;
        if(!show)return;
        const spec=ANIM.title,t=video.currentTime,duration=Number(compSet.title_duration)||0;
        card.textContent=compSet.title_text;
        Object.assign(card.style,{position:'absolute',left:'50%',top:(spec.y*100)+'%',transform:'translate(-50%,-50%)',
            fontFamily:`"${s.font}",Roboto,"Noto Sans KR",sans-serif`,fontSize:(h*s.size/100*spec.scale)+'px',color:s.color,
            padding:`${spec.pad_y}em ${spec.pad_x}em`,borderRadius:spec.radius+'em',background:'rgba(10,12,20,.78)',
            lineHeight:'1.2',whiteSpace:'nowrap',pointerEvents:'none',zIndex:'4',webkitTextStroke:`${2*h*s.outline/360}px black`,
            opacity:String(Math.max(0,Math.min(1,t/spec.fade_in,(duration-t)/spec.fade_out)))});
    }
    function drawTranslationReview(c) {
        const lang=project?.style?.translation_language||'en';
        const state=c?CaptionTiming.translationState(c,lang,project.style):{};
        const box=$('translationReviewBox');
        if(box){
            box.hidden=!state.pending;
            if(state.pending){
                $('translationReviewText').textContent=state.entry.status==='stale'
                    ?'The original line changed after this translation was written. It is hidden from exports until you keep or retranslate it.'
                    :(state.entry.note||'Suggested translation. It is hidden from exports until you keep it.');
            }
        }
        const note=$('duplicateNote');
        if(note){
            const duplicate=Boolean(c&&state.hasText&&state.entry.status==='approved'&&project.style.track_mode==='both'&&project.style.hide_duplicate_translation!==false
                &&CaptionTiming.normalizeWs(state.entry.text)===CaptionTiming.normalizeWs(c.text));
            note.hidden=!duplicate;
            if($('showDuplicateTranslation'))$('showDuplicateTranslation').checked=Boolean(c?.show_duplicate_translation);
        }
    }
    function select(index,seek=true) {
        selected=index;
        drawList();fillSelection();drawTimeline();drawCaption();
        $('cueList').children[selected]?.scrollIntoView?.({block:'nearest'});
        if(seek&&current()&&Number.isFinite(current().start)) video.currentTime=Math.max(0,Math.min(project.duration,current().start+.01));
    }
    function drawList() {
        const list=$('cueList');list.replaceChildren();
        if(!project) return;
        project.cues.forEach((c,i)=>{
            const row=document.createElement('button');row.className='cue'+(i===selected?' active':'');
            const time=document.createElement('time');
            time.textContent=`#${i+1}  ${fmt(c.start)} → ${fmt(c.end)}`;
            const textWrap=document.createElement('div');
            textWrap.style.display='flex';textWrap.style.flexDirection='column';textWrap.style.gap='2px';textWrap.style.minWidth='0';textWrap.style.flex='1';
            const text=document.createElement('span');text.textContent=(needsReview(c)?'⚑ ': '')+c.text;
            textWrap.append(text);
            const trState=CaptionTiming.translationState(c,project?.style?.translation_language||'en',project?.style);
            const trans=trState.entry;
            if(trState.hasText && (trState.pending || CaptionTiming.normalizeWs(trans.text)!==CaptionTiming.normalizeWs(c.text))){
                const sub=document.createElement('small');
                sub.className='cueTranslation'+(trState.pending?' pending':'');
                sub.style.color='#c084fc';sub.style.fontSize='11px';sub.style.opacity=trState.pending?'0.55':'0.95';
                sub.style.overflow='hidden';sub.style.textOverflow='ellipsis';sub.style.whiteSpace='nowrap';
                sub.style.cursor='pointer';
                sub.title=trState.pending?'Needs review: not exported until you Keep it. Click to review.':'Click to edit translated subtitle';
                sub.textContent=(trState.pending?'⚠ Needs review · ':'🌐 ') + trans.text;
                sub.onclick=(e)=>{
                    e.stopPropagation();
                    select(i);
                    const st=$('sideTranslationText');
                    if(st){
                        st.focus();
                        if(typeof st.scrollIntoView === 'function') st.scrollIntoView({behavior:'smooth', block:'center'});
                    }
                };
                textWrap.append(sub);
            }
            row.append(time,textWrap);
            row.onclick=()=>select(i);list.append(row);
        });
    }
    function fillSelection() {
        const c=current();
        if(project){
            const effective={...project.style,...($('styleScope').value==='selected'?c?.style_override||{}:{})};
            for(const key of styleKeys){
                if(styleChecks.includes(key))$(key).checked=!!effective[key];
                else if(effective[key]!==undefined)$(key).value=effective[key];
            }
        }
        if($('workspace_translation_language') && project?.style?.translation_language) $('workspace_translation_language').value=project.style.translation_language;
        if($('workspace_track_mode') && project?.style?.track_mode) $('workspace_track_mode').value=project.style.track_mode;
        const tr=c?.translations?.[project?.style.translation_language||'en'];
        const trDraft=c?readDraft('translation-'+c.id+'-'+(project.style.translation_language||'en')):null;
        const trVal=trDraft?.text??tr?.text??'';
        if($('translationText')) $('translationText').value=trVal;
        if($('sideTranslationText')) $('sideTranslationText').value=trVal;
        if($('translationLocked')) $('translationLocked').checked=!!tr?.locked;
        if($('selectedCueBadge')) $('selectedCueBadge').textContent = c ? `Line #${selected + 1}` : 'None';
        if(project?.state==='busy' && project.status?.includes('Translat')) {
            $('translationState').textContent='⏳ '+project.status;
        } else {
            $('translationState').textContent=tr?`Translation: ${tr.status}${tr.note?' · '+tr.note:''}`:'No translation for this line yet.';
        }
        drawTranslationReview(c);
        $('lineReview').textContent=c?.karaoke?.note || (c?.words?.length ? 'Word timings available — listen and adjust if needed.' : 'No word timings yet.');
        $('text').value=c?.text||'';$('start').value=c?.start.toFixed(2)||'';$('end').value=c?.end.toFixed(2)||'';
        for(const node of document.querySelectorAll('#selection textarea,#selection input,#selection button')) node.disabled=!c||busy;
        $('words').replaceChildren();
        if(c&&!c.words?.length) {
            const note=document.createElement('p');note.className='hint';
            note.textContent='This line has no word timings, so karaoke cannot highlight it yet. Estimate timings for this line, or use Paste lyrics → Use current caption text → Sync lyrics to audio.';
            $('words').append(note);
        }
        const lane=$('wordLane');lane.replaceChildren();
        if(c)for(const [index,w] of (c.words||[]).entries()){
            const block=document.createElement('button');block.type='button';block.className='wordTimingBlock';block.textContent=w.text;
            block.style.left=((w.start-c.start)/(c.end-c.start)*100)+'%';block.style.width=((w.end-w.start)/(c.end-c.start)*100)+'%';
            block.title='Drag center to move, edges to resize. Arrow keys move by 0.02 seconds.';
            block.onkeydown=act(event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();event.stopPropagation();
                const delta=event.key==='ArrowLeft'?-.02:.02;
                timingEdit(()=>{const a=w.start+delta,b=w.end+delta;if(a<(c.words[index-1]?.end??c.start)||b>(c.words[index+1]?.start??c.end))throw Error('Words must stay in order.');w.start=a;w.end=b;});});
            block.onpointerdown=event=>{
                if(busy)return;event.preventDefault();const rect=block.getBoundingClientRect(),area=lane.getBoundingClientRect();
                const mode=event.clientX-rect.left<8?'start':rect.right-event.clientX<8?'end':'move';
                const startX=event.clientX,a=w.start,b=w.end,min=c.words[index-1]?.end??c.start,max=c.words[index+1]?.start??c.end;
                let nextA=a,nextB=b;block.setPointerCapture(event.pointerId);
                block.onpointermove=e=>{const delta=(e.clientX-startX)/area.width*(c.end-c.start);
                    if(mode==='start')nextA=Math.max(min,Math.min(b-.01,a+delta));
                    else if(mode==='end')nextB=Math.min(max,Math.max(a+.01,b+delta));
                    else {nextA=Math.max(min,Math.min(max-(b-a),a+delta));nextB=nextA+b-a;}
                    block.style.left=((nextA-c.start)/(c.end-c.start)*100)+'%';block.style.width=((nextB-nextA)/(c.end-c.start)*100)+'%';};
                block.onpointerup=()=>{block.onpointermove=null;block.onpointerup=null;
                    timingEdit(()=>{w.start=nextA;w.end=nextB;c.karaoke={state:'edited',note:'Word timings adjusted. Listen to verify.'};});};
                block.onpointercancel=()=>{block.onpointermove=null;block.onpointerup=null;fillSelection();};
            };
            lane.append(block);
        }
        (c?.words||[]).forEach((w,i)=>{
            const row=document.createElement('div');row.className='word';
            const label=document.createElement('span');label.textContent=w.text;row.append(label);
            for(const k of ['start','end']) {
                const input=document.createElement('input');input.type='number';input.step='.01';input.value=w[k].toFixed(2);
                input.setAttribute('aria-label',`${w.text} ${k}`);input.disabled=busy;
                input.onchange=()=>timingEdit(()=>{c.words[i][k]=Number(input.value);c.karaoke={state:'edited',note:'Word timings edited — check while listening'};});
                row.append(input);
            }
            $('words').append(row);
        });
    }
    function snapTime(val, minBound, maxBound) {
        if(!$('snapTimeline')?.checked) return Math.max(minBound, Math.min(maxBound, val));
        const beats=CaptionTiming.detectBeats(project.peaks, project.duration);
        const targets=[0, project.duration, video.currentTime, ...beats, Math.round(val*4)/4];
        for(const t of targets) {
            if(t>=minBound && t<=maxBound && Math.abs(val-t)<0.08) return t;
        }
        return Math.max(minBound, Math.min(maxBound, val));
    }
    function drawTimeline() {
        if(!project?.duration || dragging) return;
        const timeline=$('timeline');const width=Math.max(400,$('timelineScroll').clientWidth)*Number($('zoom').value);
        timeline.style.width=width+'px';
        const vLane=$('videoTrackLane');
        if(vLane) {
            vLane.replaceChildren();
            const cs=project.studio?.settings||project.composition||{};
            const assets=project.studio?.assets||{};
            const bgClips=project.studio?.tracks?.[0]?.clips||[];
            if(bgClips.length>=2) {
                bgClips.forEach((clip,idx)=>{
                    const cb=document.createElement('div');cb.className='trackBlock'+(idx%2===1?' clipAlt':'');
                    cb.style.left=(clip.start/project.duration*100)+'%';
                    cb.style.width=(clip.duration/project.duration*100)+'%';
                    const clipAsset=assets[clip.asset]||{};
                    const isMuted=(cs.background_volume===0)||(clipAsset.kind==='image')||(clipAsset.has_audio===false);
                    const audioIcon=isMuted?'🔇':'🔊';
                    cb.textContent=`${audioIcon} Clip ${idx+1}: ${clip.name||clip.asset} (${clip.duration.toFixed(1)}s)`;
                    cb.title=`Clip ${idx+1}: ${clip.name||clip.asset} (${fmt(clip.start)} → ${fmt(clip.start+clip.duration)}) [${isMuted?'Muted/No audio':'Audio active'}]`;
                    cb.onclick=()=>{switchDock('media');video.currentTime=clip.start;};
                    vLane.append(cb);
                });
            } else {
                const bgBlock=document.createElement('div');bgBlock.className='trackBlock';
                const bgDur=cs.background_duration>0?Math.min(project.duration,cs.background_duration):project.duration;
                bgBlock.style.left='0%';bgBlock.style.width=(bgDur/project.duration*100)+'%';
                const bgKind=assets.background?.kind||'Colour';
                const isMuted=(cs.background_volume===0)||(bgKind==='image')||(assets.background?.has_audio===false);
                const audioIcon=isMuted?'🔇':'🔊';
                bgBlock.textContent=`${audioIcon} Video: ${bgKind} (${cs.shape||'portrait'}${cs.background_speed&&cs.background_speed!==1?' · '+cs.background_speed+'×':''})`;
                bgBlock.onclick=()=>switchDock('media');
                vLane.append(bgBlock);
            }
            if(cs.title_text && cs.title_duration>0) {
                const tb=document.createElement('div');tb.className='trackBlock titleCard';
                tb.style.left='0%';tb.style.width=(Math.min(project.duration,cs.title_duration)/project.duration*100)+'%';
                tb.textContent='Title: '+cs.title_text;tb.onclick=()=>openCompositionEditor();
                vLane.append(tb);
            }
            if(project.studio?.assets?.broll && cs.broll_duration>0) {
                const bb=document.createElement('div');bb.className='trackBlock broll';
                bb.style.left=(Math.min(project.duration,cs.broll_start||0)/project.duration*100)+'%';
                bb.style.width=(Math.min(project.duration-(cs.broll_start||0),cs.broll_duration)/project.duration*100)+'%';
                bb.textContent='B-Roll ('+(cs.broll_scale||100)+'%)';bb.onclick=()=>openCompositionEditor();
                vLane.append(bb);
            }
            if(project.studio?.assets?.sticker && cs.sticker_duration>0) {
                const sb=document.createElement('div');sb.className='trackBlock sticker';
                sb.style.left=(Math.min(project.duration,cs.sticker_start||0)/project.duration*100)+'%';
                sb.style.width=(Math.min(project.duration-(cs.sticker_start||0),cs.sticker_duration)/project.duration*100)+'%';
                sb.textContent='🎨 Sticker ('+(cs.sticker_scale||25)+'%)';sb.onclick=()=>switchDock('stickers');
                vLane.append(sb);
            }
        }
        const canvas=$('waveform');canvas.width=width;canvas.height=80;
        const ctx=canvas.getContext('2d');ctx.fillStyle='#72cfc5';
        const peaks=project.peaks||[], max=Math.max(.01,...peaks);
        peaks.forEach((p,i)=>{const h=p/max*70;ctx.fillRect(i/peaks.length*width,40-h/2,Math.max(1,width/peaks.length),h);});
        const beats=CaptionTiming.detectBeats(peaks, project.duration);
        if(beats.length) {
            ctx.fillStyle='#ffd166aa';
            beats.forEach(b=>{const bx=Math.round((b/project.duration)*width);ctx.fillRect(bx,0,2,12);ctx.fillRect(bx,68,2,12);});
        }
        $('blocks').replaceChildren();
        project.cues.forEach((c,i)=>{
            const block=document.createElement('div');block.className='block'+(selected===i?' selected':'');block.textContent=c.text;
            block.style.left=c.start/project.duration*100+'%';block.style.width=(c.end-c.start)/project.duration*100+'%';
            for(const side of ['left','right']) {const edge=document.createElement('span');edge.className='edge '+side;block.append(edge);}
            block.onpointerdown=e=>{
                if(busy)return;
                e.preventDefault();video.pause();selected=i;fillSelection();drawList();
                const original=copy(c), x=e.clientX, side=e.target.classList.contains('left')?'start':e.target.classList.contains('right')?'end':'move';
                checkpoint();dragging=true;block.setPointerCapture(e.pointerId);
                const before=i?project.cues[i-1].end:0, after=i+1<project.cues.length?project.cues[i+1].start:project.duration;
                block.onpointermove=ev=>{
                    const delta=(ev.clientX-x)/width*project.duration;
                    if(side==='move') {
                        const rawStart=snapTime(original.start+delta, before, after-(original.end-original.start));
                        const shift=rawStart-original.start;
                        c.start=original.start+shift;c.end=original.end+shift;
                        c.words=original.words.map(w=>({...w,start:Math.max(c.start,Math.min(c.end,w.start+shift)),end:Math.max(c.start,Math.min(c.end,w.end+shift))}));
                        if(c.words.length){c.words[0].start=c.start;c.words[c.words.length-1].end=c.end;}
                    } else {
                        c[side]=side==='start'?snapTime(original.start+delta,before,original.end-.05):snapTime(original.end+delta,original.start+.05,after);
                        c.words=[];
                    }
                    block.style.left=c.start/project.duration*100+'%';block.style.width=(c.end-c.start)/project.duration*100+'%';
                    video.currentTime=c.start;drawCaption();
                };
                const end=()=>{dragging=false;block.onpointermove=null;block.onpointerup=null;block.onpointercancel=null;changed();};
                block.onpointerup=end;block.onpointercancel=end;
            };
            $('blocks').append(block);
        });
        $('playhead').style.left=video.currentTime/project.duration*100+'%';
    }
    function drawDownloads() {
        $('downloads').replaceChildren();
        (project?.exports||[]).slice().reverse().forEach((name,i)=>{
            const link=document.createElement('a');link.href=media(name)+'?download=1';
            link.textContent=(name.startsWith('check_')?'Preview':'Captioned video')+' · '+(project.exports.length-i);
            $('downloads').append(link);
        });
    }
    async function create(form) {
        await save();clearTimeout(uploadDraftTimer);await saveUploadDraft();
        video.pause();setBusy(true);say('Copying video and preparing your project…');
        try {
            const created=await api('/api/captions','POST',form);
            clearUploadInputs();project=created;dirty=false;history=[];future=[];selected=-1;
            refresh();poll();
        }
        catch(e){setBusy(false);throw e;}
    }
    const selectedStock={song:null,composition:null};
    let stockTarget='composition';
    let clipSequence=[];
    let appliedSequence='[]';
    const sequenceHasChanges=()=>JSON.stringify(clipSequence)!==appliedSequence;
    let clipSequenceSource=null;
    let reopenCompAfterStock=false;
    function syncSequenceFromProject(force=false) {
        if(!project?.studio){clipSequence=[];clipSequenceSource=null;return;}
        const sig=`${project.id}:${project.source}`;
        if(!force && clipSequenceSource===sig) return;
        clipSequenceSource=sig;
        const savedSeq=project.studio.settings?.sequence||[];
        if(savedSeq.length) {
            clipSequence=savedSeq.map(item=>({
                asset:item.asset,
                name:item.name||project.studio.assets?.[item.asset]?.name||project.studio.assets?.[item.asset]?.file||item.asset,
                duration:Number(item.duration)||0,
                speed:Number(item.speed)||1,
                source_start:Number(item.source_start)||0
            }));
        } else if(project.studio.assets?.background) {
            const bg=project.studio.assets.background;
            clipSequence=[{
                asset:'background',
                name:bg.name||bg.provenance?.attribution||bg.file||'Current background',
                duration:0,
                speed:1
            }];
        } else {
            clipSequence=[];
        }
        appliedSequence=JSON.stringify(clipSequence);
        const draft=readDraft('sequence');
        if(!force && draft?.source===project.source && Array.isArray(draft.clips))clipSequence=draft.clips;
    }
    function checkpointSequence() {
        history.push({_sequence:clipSequence.map(c=>({...c}))});
        if(history.length>80)history.shift();future=[];
    }
    function renderSequenceBox(container) {
        if(!container) return;
        container.replaceChildren();
        if(!clipSequence.length) {
            const hint=document.createElement('span');hint.className='hint';
            hint.textContent='No clips in sequence (plain colour background). Click "+ Add clip from Pixabay" or "+ Upload clips" to add multiple videos!';
            container.append(hint);
            return;
        }
        clipSequence.forEach((item,idx)=>{
            const pill=document.createElement('div');pill.className='seqItem';

            // Row 1: Header (Badge, Title, Reorder Controls, Delete Button)
            const row1=document.createElement('div');row1.className='seqHeader';
            const num=document.createElement('span');num.className='seqBadge';num.textContent=`#${idx+1}`;
            const name=document.createElement('span');name.className='seqName';name.textContent=item.name||`Clip ${idx+1}`;name.title=item.name||'';

            const actions=document.createElement('div');actions.className='seqActions';
            const leftBtn=document.createElement('button');leftBtn.type='button';leftBtn.className='seqIconBtn';leftBtn.textContent='◀';leftBtn.title='Move clip earlier';leftBtn.disabled=busy||idx===0;
            leftBtn.onclick=()=>{checkpointSequence();const tmp=clipSequence[idx-1];clipSequence[idx-1]=clipSequence[idx];clipSequence[idx]=tmp;drawSequenceLists();};
            const rightBtn=document.createElement('button');rightBtn.type='button';rightBtn.className='seqIconBtn';rightBtn.textContent='▶';rightBtn.title='Move clip later';rightBtn.disabled=busy||idx===clipSequence.length-1;
            rightBtn.onclick=()=>{checkpointSequence();const tmp=clipSequence[idx+1];clipSequence[idx+1]=clipSequence[idx];clipSequence[idx]=tmp;drawSequenceLists();};

            const delBtn=document.createElement('button');delBtn.type='button';delBtn.className='seqDelBtn';delBtn.textContent='✕';delBtn.title='Remove clip from sequence';delBtn.disabled=busy;
            delBtn.onclick=()=>{checkpointSequence();clipSequence.splice(idx,1);drawSequenceLists();};

            actions.append(leftBtn,rightBtn,delBtn);
            row1.append(num,name,actions);

            // Row 2: Duration & Playback Speed
            const row2=document.createElement('div');row2.className='seqControls';

            const durWrap=document.createElement('div');durWrap.className='seqField';
            const durIcon=document.createElement('span');durIcon.className='seqFieldIcon';durIcon.textContent='⏱';
            const durInput=document.createElement('input');durInput.type='number';durInput.min='0';durInput.max='1200';durInput.step='0.5';
            durInput.value=String(item.duration||0);durInput.title='Clip duration in seconds (0 = Auto split song evenly)';durInput.disabled=busy;
            durInput.onchange=()=>{checkpointSequence();item.duration=Math.max(0,Number(durInput.value)||0);drawSequenceLists();};
            const durUnit=document.createElement('span');durUnit.className='seqFieldUnit';durUnit.textContent=(Number(item.duration)>0?'s':'s (Auto)');
            durWrap.append(durIcon,durInput,durUnit);

            const spdWrap=document.createElement('div');spdWrap.className='seqField';
            const spdIcon=document.createElement('span');spdIcon.className='seqFieldIcon';spdIcon.textContent='⚡';
            const spdSel=document.createElement('select');spdSel.className='seqSpeed';spdSel.title='Clip playback speed';spdSel.disabled=busy;
            [{l:'0.25× Slow',v:0.25},{l:'0.5× Slow',v:0.5},{l:'0.75×',v:0.75},{l:'1× Normal',v:1},{l:'1.25×',v:1.25},{l:'1.5×',v:1.5},{l:'2× Fast',v:2},{l:'4× Hyper',v:4}].forEach(o=>{
                const opt=new Option(o.l,String(o.v));
                if(Math.abs((Number(item.speed)||1)-o.v)<0.05) opt.selected=true;
                spdSel.add(opt);
            });
            spdSel.onchange=()=>{checkpointSequence();item.speed=Number(spdSel.value)||1;drawSequenceLists();};
            spdWrap.append(spdIcon,spdSel);

            const source=document.createElement('input');source.type='number';source.min='0';source.max='7200';source.step='.01';
            source.value=String(item.source_start||0);source.title='Source start (seconds)';source.setAttribute('aria-label','Source start (seconds)');source.disabled=busy;
            source.onchange=()=>{checkpointSequence();item.source_start=Math.max(0,Number(source.value)||0);drawSequenceLists();};
            const sourceRow=document.createElement('label');sourceRow.className='seqControls';sourceRow.textContent='Source start (s)';source.style.width='80px';sourceRow.append(source);
            row2.append(durWrap,spdWrap);
            pill.append(row1,row2,sourceRow);
            container.append(pill);
        });
    }
    function drawSequenceLists() {
        if(project) {
            const saved=project.studio?.settings?.sequence||[];
            const pending=sequenceHasChanges();
            let notice=$('sequenceNotice');
            if(!notice){notice=document.createElement('p');notice.id='sequenceNotice';notice.className='hint';$('sequenceList')?.after(notice);}
            notice.textContent=pending?'Sequence edits are not applied. Apply the sequence before export.':'';
            if(!clipSequence.some(c=>c.file))storeDraft('sequence',{source:project.source,clips:clipSequence});
        }
        scheduleUploadDraft();
        renderSequenceBox($('sequenceList'));
        renderSequenceBox($('compSequenceList'));
        if($('applyStockSequence')) {
            $('applyStockSequence').hidden=!project?.studio || !clipSequence.length;
            $('applyStockSequence').textContent=`Apply ${clipSequence.length} clip(s) to video now`;
        }
    }
    let uploadDraftTimer=null,restoringUploads=false,selectedEmoji=null,clearStickerPending=false;
    const uploadInputIds=['compAudio','compBackground','compBroll','stickerFile'];
    function clearUploadInputs(){
        selectedStock.composition=null;selectedEmoji=null;clearStickerPending=false;
        if($('activeStickerNotice'))$('activeStickerNotice').textContent='';
        if($('compStockNotice')){$('compStockNotice').hidden=true;$('compStockNotice').textContent='';}
        if($('snapFaceStatus'))$('snapFaceStatus').textContent='';
        for(const id of uploadInputIds)if($(id))$(id).value='';
        for(const id of ['compLibrary','compBrollLibrary'])if($(id))$(id).value='';
        for(const id of ['compClear','compClearBroll'])if($(id))$(id).checked=false;
    }
    function uploadDatabase(){return new Promise((resolve,reject)=>{
        const req=indexedDB.open('creator-upload-drafts',1);
        req.onupgradeneeded=()=>req.result.createObjectStore('projects');
        req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);
    });}
    async function saveUploadDraft(){
        if(!project||restoringUploads||typeof indexedDB==='undefined')return;
        const pid=project.id,source=project.source,files={};
        for(const id of uploadInputIds)files[id]=Array.from($(id)?.files||[]);
        const sequence=clipSequence.map(c=>({...c}));
        const selections={library:$('compLibrary').value,brollLibrary:$('compBrollLibrary').value,
            clear:$('compClear').checked,clearBroll:$('compClearBroll').checked,
            selectedEmoji,clearStickerPending,stockComposition:selectedStock.composition};
        const bytes=[...Object.values(files).flat(),...sequence.map(c=>c.file).filter(Boolean)].reduce((n,f)=>n+f.size,0);
        if(bytes>512*1024*1024)throw Error('Upload draft exceeds 512 MB. Apply the composition before switching projects to keep these uploads.');
        const db=await uploadDatabase();
        try{await new Promise((resolve,reject)=>{const tx=db.transaction('projects','readwrite');tx.objectStore('projects').put({source,files,sequence,selections},pid);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
        finally{db.close();}
    }
    function scheduleUploadDraft(){if(restoringUploads)return;clearTimeout(uploadDraftTimer);uploadDraftTimer=setTimeout(()=>saveUploadDraft().catch(e=>say(e.message||'Upload draft could not be stored. Keep this tab open or apply the composition before closing.',true)),500);}
    async function restoreUploadDraft(){
        if(!project||typeof indexedDB==='undefined')return;
        restoringUploads=true;const pid=project.id;
        try{const db=await uploadDatabase();let draft;
            try{draft=await new Promise((resolve,reject)=>{const req=db.transaction('projects').objectStore('projects').get(pid);req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});}finally{db.close();}
            const submission=readDraft('composition-submission');
            if(project.id!==pid||!draft||(draft.source!==project.source&&draft.source!==submission?.source))return;
            for(const id of uploadInputIds){const files=draft.files?.[id]||[];if($(id)){const transfer=new DataTransfer();files.forEach(f=>transfer.items.add(f));$(id).files=transfer.files;}}
            $('compLibrary').value=draft.selections?.library||'';
            $('compBrollLibrary').value=draft.selections?.brollLibrary||'';
            $('compClear').checked=!!draft.selections?.clear;
            $('compClearBroll').checked=!!draft.selections?.clearBroll;
            selectedEmoji=draft.selections?.selectedEmoji||null;
            clearStickerPending=!!draft.selections?.clearStickerPending;
            selectedStock.composition=draft.selections?.stockComposition||null;
            if($('activeStickerNotice')){
                const sf=$('stickerFile')?.files?.[0];
                $('activeStickerNotice').textContent=selectedEmoji?`Active sticker: Emoji ${selectedEmoji} (Click Apply to save)`:sf?`Active sticker: File "${sf.name}" (Click Apply to upload)`:clearStickerPending?'Sticker removed. Click Apply to save.':'';
            }
            if($('compStockNotice')&&selectedStock.composition?.provenance?.attribution){
                $('compStockNotice').hidden=false;
                $('compStockNotice').textContent=`Added to sequence: ${selectedStock.composition.provenance.attribution}`;
            }
            if(draft.sequence.some(c=>c.file)){clipSequence=draft.sequence;drawSequenceLists();}
        }catch{say('Could not restore uploaded draft files. Saved project media is still available.',true);}
        finally{restoringUploads=false;}
    }
    for(const id of ['compAudio','compBackground','compBroll','stickerFile'])$(id)?.addEventListener('change',scheduleUploadDraft);
    for(const id of ['compLibrary','compBrollLibrary','compClear','compClearBroll'])$(id)?.addEventListener('change',scheduleUploadDraft);
    async function refreshLibraries() {
        const entries=await api('/api/gallery');
        const prevLib=$('library').value, prevComp=$('compLibrary').value, prevSong=$('songLibrary').value, prevBroll=$('compBrollLibrary').value;
        const mediaItems=entries.filter(e=>['image','video'].includes(e.type)&&e.folder!=='Caption Projects');
        $('library').replaceChildren(new Option('Choose from library…',''),...entries.filter(e=>e.type==='video'&&e.folder!=='Caption Projects').map(e=>new Option(e.name,e.full_path)));
        $('compLibrary').replaceChildren(new Option('Keep current / choose clip…',''),...mediaItems.map(e=>new Option(e.name,e.full_path)));
        if($('seqLibrarySelect')) $('seqLibrarySelect').replaceChildren(new Option('+ Add clip from library…',''),...mediaItems.map(e=>new Option(e.name,e.full_path)));
        $('compBrollLibrary').replaceChildren(new Option('Keep current B-roll',''),...mediaItems.map(e=>new Option(e.name,e.full_path)));
        $('songLibrary').replaceChildren(new Option('Use colour / uploaded background',''),...mediaItems.map(e=>new Option(e.name,e.full_path)));
        if(prevLib)$('library').value=prevLib;
        if(prevComp)$('compLibrary').value=prevComp;
        if(prevBroll)$('compBrollLibrary').value=prevBroll;
        if(prevSong)$('songLibrary').value=prevSong;
    }
    $('videoFile').onchange=act(async()=>{const file=$('videoFile').files[0];if(file){const f=new FormData();f.append('video',file);await create(f);}$('videoFile').value='';});
    $('newSong').onclick=()=>$('songDialog').showModal();
    $('cancelSong').onclick=()=>$('songDialog').close();
    $('createSong').onclick=act(async()=>{
        const song=$('songFile').files[0];if(!song)throw Error('Choose your song first.');
        const form=new FormData();form.append('audio',song);form.append('shape',$('songShape').value);form.append('color',$('songColor').value);form.append('visualizer',$('songVisualizer').checked);
        const bg=$('songBackground').files[0];
        if(bg)form.append('background',bg);
        else if($('songLibrary').value){
            form.append('background_path',$('songLibrary').value);
            if(selectedStock.song?.path===$('songLibrary').value && selectedStock.song?.provenance) form.append('stock_provenance',JSON.stringify(selectedStock.song.provenance));
        }
        $('createSong').disabled=true;
        try {await create(form);$('songDialog').close();} finally {$('createSong').disabled=false;}
    });
    // The audio visualizer lives only in the caption style (one visualizer, previewed live and exported as ASS bars).
    const compositionKeys=['shape','color','fit','x','y','blur','dim','overlay','opacity','zoom','brightness','contrast','saturation','video_filter','vignette','film_grain','sharpen','chromatic','background_speed','transition_in','transition_out','keyframe_end_x','keyframe_end_y','title_text','title_duration','broll_start','broll_duration','broll_x','broll_y','broll_scale','broll_opacity','broll_fade','sticker_start','sticker_duration','sticker_x','sticker_y','sticker_scale','sticker_opacity','sticker_fade','sticker_anim','start','end','offset','volume','fade_in','fade_out','noise_cancel','voice_isolation','audio_effect','background_volume','ducking','loop','background_start','background_duration','sequence_transition','sequence_transition_duration'];
    const compositionChecks=['loop','ducking','vignette','noise_cancel','voice_isolation'], compositionStrings=['shape','color','fit','overlay','title_text','video_filter','audio_effect','sequence_transition','sticker_anim'];
    let previousComposition=null;
    function fillComposition(settings) {
        previousComposition=copy(settings);
        for(const key of compositionKeys) {
            const input=$('comp_'+key);
            if(compositionChecks.includes(key)) input.checked=!!settings[key];
            else if(key==='sticker_opacity' && settings[key]!==undefined) {
                const v=Number(settings[key]);
                input.value=String(Math.round(v>1?v:v*100));  // slider shows %, canonical value is 0-1
            }
            else if(settings[key]!==undefined) input.value=settings[key];
        }
    }
    function compositionValue(key) {
        const input=$('comp_'+key);
        if(compositionChecks.includes(key)) return input.checked;
        if(compositionStrings.includes(key)) return input.value;
        if(key==='sticker_opacity') return Number(input.value)/100;
        return Number(input.value);
    }
    function compositionSettings() {
        return Object.fromEntries(compositionKeys.map(key=>[key,compositionValue(key)]));
    }
    const stickerKeys=['sticker_start','sticker_duration','sticker_x','sticker_y','sticker_scale','sticker_opacity','sticker_fade','sticker_anim'];
    function liveStickerSettings() {
        if(compFilledSource===null) return {};
        return Object.fromEntries(stickerKeys.filter(k=>$('comp_'+k)).map(k=>[k,compositionValue(k)]));
    }
    for(const key of stickerKeys) {
        const input=$('comp_'+key);
        if(input && input.addEventListener) input.addEventListener('input',()=>drawCaption());
    }
    function switchDock(name) {
        document.querySelectorAll('[data-dock]').forEach(b=>b.classList.toggle('active',b.dataset.dock===name));
        document.querySelectorAll('[data-dock-pane]').forEach(p=>p.classList.toggle('active',p.dataset.dockPane===name));
        if(name==='stock') {
            syncStockKeyStatus();
            if($('stockResults') && !$('stockResults').children.length) {
                if(!$('stockQuery').value.trim()) $('stockQuery').value='dance';
                runStockSearch().catch(()=>{});
            }
        }
        setTimeout(fitVideo, 30);
    }
    document.querySelectorAll('[data-dock]').forEach(b=>{b.onclick=()=>switchDock(b.dataset.dock);});
    document.querySelectorAll('[data-insp]').forEach(b=>{
        b.onclick=()=>{
            const mode=b.dataset.insp;
            document.querySelectorAll('[data-insp]').forEach(t=>t.classList.toggle('active',t.dataset.insp===mode));
            document.querySelectorAll('[data-insp-pane]').forEach(p=>{p.hidden=(mode!=='both' && p.dataset.inspPane!==mode);});
            setTimeout(fitVideo, 30);
        };
    });
    for(const [id,dock] of [['songDialog','media'],['compositionDialog','canvas'],['stockDialog','stock'],['lyricsDialog','lyrics']]) {
        const el=$(id);
        if(el && typeof el.showModal!=='function') {
            el.showModal=()=>{switchDock(dock);el.open=true;};
            el.close=()=>{el.open=false;if(id==='stockDialog')switchDock('media');};
        }
    }
    function drawComposition() {
        const studio=project?.studio;
        $('editComposition').disabled=busy||!studio;
        $('openStockBrowser').disabled=busy;
        $('restoreComposition').disabled=busy||!project?.composition_backup;
        $('recoverEdits').disabled=busy||!readDraft('captions');
        if($('sequenceBar')) $('sequenceBar').hidden=!studio;
        syncSequenceFromProject(false);
        drawSequenceLists();
        if(studio && compFilledSource!==`${project.id}:${project.source}`) {
            compFilledSource=`${project.id}:${project.source}`;
            const draft=readDraft('composition');
            fillComposition(draft?.source===project.source?draft.settings:studio.settings);
            const prov=studio.assets.background?.provenance;
            const broll=studio.assets.broll;
            $('compositionAssets').textContent='Current song: '+studio.assets.audio.file+(prov?` · Background: ${prov.attribution} (${prov.license})`:'')+(broll?` · B-Roll: ${broll.file}`:'');
            $('alignStart').value=0;
            $('alignEnd').value=project.duration.toFixed(3);
            const lDraft=readDraft('lyrics');
            if(lDraft?.text) {
                $('lyrics').value=lDraft.text;
                if(lDraft.language)$('alignLanguage').value=lDraft.language;
                if(lDraft.start!==undefined)$('alignStart').value=lDraft.start;
                if(lDraft.end!==undefined)$('alignEnd').value=lDraft.end;
            } else $('lyrics').value='';
        }
        document.querySelectorAll('[data-filter-pill]').forEach(b=>b.classList.toggle('active',b.dataset.filterPill===(project?.style?.video_filter||'none')));
        const prov=studio?.assets?.background?.provenance;
        const provText=prov?` · ${prov.attribution} (${prov.license})`:'';
        const seqCount=(studio?.settings?.sequence||[]).length;
        const seqText=seqCount>=2?` · ${seqCount}-clip sequence`:'';
        const brollText=studio?.assets?.broll && studio?.settings?.broll_duration>0 ? ` · B-Roll ${studio.settings.broll_duration}s` : '';
        const fxParts=[];
        if((project?.style?.video_filter||studio?.settings?.video_filter||'none')!=='none') fxParts.push(`filter: ${project?.style?.video_filter||studio?.settings?.video_filter}`);
        if(project?.style?.voice_isolation||studio?.settings?.voice_isolation) fxParts.push('voice isolation');
        else if(project?.style?.noise_cancel||studio?.settings?.noise_cancel) fxParts.push('noise cancel');
        if((project?.style?.audio_effect||studio?.settings?.audio_effect||'none')!=='none') fxParts.push(`audio FX: ${project?.style?.audio_effect||studio?.settings?.audio_effect}`);
        const fxText=fxParts.length ? ` · ${fxParts.join(', ')}` : '';
        $('compositionSummary').textContent=studio ? `${studio.settings.shape} · ${studio.assets.background?.kind||'Colour'} background${seqText}${provText}${brollText}${fxText} · song ${fmt(studio.settings.start)}–${fmt(studio.settings.end)} · ${studio.settings.offset}s delay`+(project.missing_assets?.length?` · Missing media: ${project.missing_assets.join(', ')}. Open Canvas & PiP to relink.`:'') : 'Open a prepared project to edit its clips, background, and audio.';
    }
    function openCompositionEditor() {
        if(!project?.studio)return;
        video.pause();const draft=readDraft('composition');
        fillComposition(draft?.source===project.source?draft.settings:project.studio.settings);
        drawSequenceLists();
        const prov=project.studio.assets.background?.provenance;
        const broll=project.studio.assets.broll;
        $('compositionAssets').textContent='Current song: '+project.studio.assets.audio.file+(prov?` · Background: ${prov.attribution} (${prov.license})`:'')+(broll?` · B-Roll: ${broll.file}`:'')+(project.missing_assets?.length?' · Missing: '+project.missing_assets.join(', ')+'. Upload the original file again.':'');
        $('compositionDialog').showModal();
    }
    $('editComposition').onclick=act(openCompositionEditor);
    for(const key of compositionKeys) $('comp_'+key).onchange=()=>{
        if(!project)return;
        if(previousComposition){history.push({_composition:copy(previousComposition)});if(history.length>80)history.shift();future=[];}
        previousComposition=compositionSettings();storeDraft('composition',{source:project.source,settings:previousComposition});drawCaption();
    };
    $('resetCompositionDraft').onclick=()=>{fillComposition(project.studio.settings);syncSequenceFromProject(true);drawSequenceLists();storeDraft('composition',null);};
    $('closeComposition').onclick=()=>$('compositionDialog').close();
    async function finishCompositionSubmission() {
        const submitted=readDraft('composition-submission');
        if(!submitted||project.state==='busy')return;
        // A completed composition gets a new source; a failed job retains the old one.
        if(project.state==='ready'&&project.source!==submitted.source) {
            clearTimeout(uploadDraftTimer);
            if(submitted.full) {
                clearUploadInputs();storeDraft('composition',null);
            } else {
                if(submitted.full)clearUploadInputs();
                const draft=readDraft('composition');
                if(draft){draft.source=project.source;storeDraft('composition',draft);}
            }
            if(submitted.full){selectedEmoji=null;clearStickerPending=false;}
            storeDraft('sequence',null);
            syncSequenceFromProject(true);
            fillComposition(readDraft('composition')?.settings||project.studio.settings);
            history=[];future=[];
            await saveUploadDraft();
        }
        storeDraft('composition-submission',null);
    }
    async function applyCompositionChanges(fromDialog=true) {
        if(!project||busy)return;
        await save();video.pause();
        const settings=fromDialog?compositionSettings():{...project.studio.settings};
        const bg=fromDialog?$('compBackground').files[0]:null;
        const libBg=fromDialog?$('compLibrary').value:'';
        const clearBg=fromDialog?$('compClear').checked:(clipSequence.length===0);
        const uploadFiles=[];
        let seqPayload=[];
        if(!clearBg && !((bg||libBg) && clipSequence.length<=1 && clipSequence[0]?.asset==='background')) {
            seqPayload=clipSequence.map(item=>{
                const dur=Math.max(0,Number(item.duration)||0);
                const spd=Math.max(0.25,Math.min(4.0,Number(item.speed)||1));
                if(item.file) {
                    const idx=uploadFiles.length;
                    uploadFiles.push(item.file);
                    return {upload_index:idx,name:item.name,duration:dur,speed:spd,source_start:Number(item.source_start)||0};
                }
                if(item.path) {
                    return {path:item.path,name:item.name,duration:dur,speed:spd,source_start:Number(item.source_start)||0,...(item.provenance?{provenance:item.provenance}:{})};
                }
                return {asset:item.asset,name:item.name,duration:dur,speed:spd,source_start:Number(item.source_start)||0};
            });
        }
        settings.sequence=seqPayload;
        const form=new FormData();
        form.append('revision',project.revision);
        form.append('settings',JSON.stringify(settings));
        uploadFiles.forEach(f=>form.append('clip_files',f));
        if(bg)form.append('background',bg);
        else if(libBg){
            form.append('background_path',libBg);
            if(selectedStock.composition?.path===libBg && selectedStock.composition?.provenance) form.append('stock_provenance',JSON.stringify(selectedStock.composition.provenance));
        }
        const stickerFile=fromDialog?$('stickerFile')?.files?.[0]:null; if(stickerFile) form.append('sticker', stickerFile);

        if(fromDialog&&selectedEmoji) form.append('emoji_sticker', selectedEmoji);
        form.append('clear_sticker', fromDialog?clearStickerPending:false);



        if(fromDialog) {
            const audio=$('compAudio').files[0],broll=$('compBroll').files[0];
            if(broll)form.append('broll',broll);
            else if($('compBrollLibrary').value)form.append('broll_path',$('compBrollLibrary').value);
            if(audio)form.append('audio',audio);
            form.append('clear_broll',$('compClearBroll').checked);
        } else {
            form.append('clear_broll',false);
        }
        form.append('clear_background',clearBg);
        $('applyComposition').disabled=true;
        if($('applySequenceNow')) $('applySequenceNow').disabled=true;
        try{
            // Keep retryable drafts until the background render actually succeeds.
            clearTimeout(uploadDraftTimer);await saveUploadDraft();
            if(fromDialog)storeDraft('composition',{source:project.source,settings});
            storeDraft('composition-submission',{source:project.source,full:fromDialog});
            project=await api(`/api/captions/${project.id}/composition`,'POST',form);
            dirty=false;
            if($('compositionDialog').open)$('compositionDialog').close();
            refresh();poll();
        } finally {
            $('applyComposition').disabled=false;
            if($('applySequenceNow')) $('applySequenceNow').disabled=false;
        }
    }
    $('applyComposition').onclick=act(()=>applyCompositionChanges(true));
    if($('applyAudioComp')) $('applyAudioComp').onclick=act(()=>applyCompositionChanges(true));
    if($('applySequenceNow')) $('applySequenceNow').onclick=act(()=>applyCompositionChanges(false));
    if($('seqBrowseStock')) $('seqBrowseStock').onclick=()=>openStockDialog('composition');
    function handleClipUpload(input) {
        if(!input?.files?.length) return;
        checkpointSequence();
        Array.from(input.files).forEach(f=>clipSequence.push({file:f,name:f.name,duration:0}));
        const count=input.files.length;
        input.value='';
        drawSequenceLists();
        say(`Added ${count} uploaded clip(s) to sequence (${clipSequence.length} total). Click "Apply clip sequence" to render.`);
    }
    if($('seqUploadInput')) $('seqUploadInput').onchange=()=>handleClipUpload($('seqUploadInput'));
    if($('compSeqUpload')) $('compSeqUpload').onchange=()=>handleClipUpload($('compSeqUpload'));
    if($('seqLibrarySelect')) $('seqLibrarySelect').onchange=()=>{
        const sel=$('seqLibrarySelect');
        if(!sel.value) return;
        const opt=sel.selectedOptions[0];
        checkpointSequence();
        clipSequence.push({path:sel.value,name:opt?.textContent||sel.value,duration:0});
        sel.value='';
        drawSequenceLists();
        say(`Added "${opt?.textContent||'library clip'}" to sequence (${clipSequence.length} total). Click "Apply clip sequence" to render.`);
    };
    if($('seqEvenSplit')) $('seqEvenSplit').onclick=()=>{
        checkpointSequence();
        clipSequence.forEach(c=>{c.duration=0;});
        drawSequenceLists();
        say('All clips set to 0s (Auto — song duration split evenly across all clips).');
    };
    if($('seqCycle10')) $('seqCycle10').onclick=()=>{
        checkpointSequence();
        clipSequence.forEach(c=>{c.duration=10;});
        drawSequenceLists();
        say('All clips set to 10s each (clips will cycle every 10 seconds across the song).');
    };
    function splitClipAtPlayhead() {
        if(!project) {
            say('Open a video project to split clips.', true);
            return;
        }
        if(!clipSequence.length) {
            syncSequenceFromProject(true);
        }
        if(!clipSequence.length) {
            say('No clips in sequence to split. Add clips or background first.', true);
            return;
        }
        const currTime = Number(video.currentTime) || 0;
        const totalDuration = Number(project.duration) || 0;
        if(currTime < 0.1 || currTime > totalDuration - 0.1) {
            say('Playhead must be inside the video to split (at least 0.1s from start/end).', true);
            return;
        }

        try {
            const split=CaptionTiming.splitSequence(clipSequence,totalDuration,currTime,project.studio.settings.loop);
            checkpointSequence();clipSequence=split;drawSequenceLists();switchDock('media');
            say('Clip split. Apply the sequence to update the preview and export.');
        } catch(error) { say(error.message,true); }

    }
    if($('seqSplitAtPlayhead')) $('seqSplitAtPlayhead').onclick=()=>splitClipAtPlayhead();
    if($('splitClip')) $('splitClip').onclick=()=>splitClipAtPlayhead();
    if($('seqSyncBeats')) $('seqSyncBeats').onclick=()=>{
        if(!project?.duration || clipSequence.length < 2) {
            say('Add at least 2 clips to sequence to cut to the beat.', true);
            return;
        }
        const beats = CaptionTiming.detectBeats(project.peaks, project.duration);
        if(!beats || !beats.length) {
            say('No distinct beat peaks detected in this audio. Using even split instead.', true);
            return;
        }
        const K = clipSequence.length;
        const D = project.duration;
        let lastCut = 0;
        for (let j = 1; j < K; j++) {
            const ideal = (j * D) / K;
            const minTime = lastCut + 0.35;
            const maxTime = D - 0.35 * (K - j);
            const candidates = beats.filter(b => b >= minTime && b <= maxTime);
            let chosen = ideal;
            if (candidates.length > 0) {
                chosen = candidates.reduce((prev, curr) => Math.abs(curr - ideal) < Math.abs(prev - ideal) ? curr : prev);
            }
            chosen = Math.round(chosen * 100) / 100;
            const dur = Math.round((chosen - lastCut) * 100) / 100;
            clipSequence[j - 1].duration = dur;
            lastCut = chosen;
        }
        clipSequence[K - 1].duration = Math.max(0.1, Math.round((D - lastCut) * 100) / 100);
        drawSequenceLists();
        say(`⚡ Synced ${K} clips to musical beats! Click "Apply clip sequence" to bake.`);
    };



    document.querySelectorAll('.emojiBtn').forEach(btn => {
        btn.onclick = () => {
            selectedEmoji = btn.dataset.emoji;
            clearStickerPending = false;
            if ($('activeStickerNotice')) $('activeStickerNotice').textContent = `Active sticker: Emoji ${selectedEmoji} (Click Apply to save)`;
            scheduleUploadDraft();
            if ($('stickerFile')) $('stickerFile').value = '';
            // Auto-align AR face target based on prop category
            if ($('snapTarget')) {
                if (selectedEmoji === '🕶️') $('snapTarget').value = 'eyes';
                else if (['👑','😇','🐶','🐱','🐰'].includes(selectedEmoji)) $('snapTarget').value = 'head';
                else if (['🎭','💖'].includes(selectedEmoji)) $('snapTarget').value = 'center';
            }
            drawCaption();
        };
    });
    if ($('snapToFaceBtn')) {
        $('snapToFaceBtn').onclick = act(async () => {
            if (!project) return;
            const target = $('snapTarget')?.value || 'head';
            if ($('snapFaceStatus')) $('snapFaceStatus').textContent = '🎯 Detecting face in video with OpenCV…';
            const data = await api(`/api/captions/${project.id}/track-face`, 'POST', {
                time: video.currentTime || 0,
                target: target
            });
            if (data.found) {
                if ($('comp_sticker_x')) $('comp_sticker_x').value = data.x;
                if ($('comp_sticker_y')) $('comp_sticker_y').value = data.y;
                if ($('comp_sticker_scale')) $('comp_sticker_scale').value = Math.max(10, Math.min(80, data.scale));
                if ($('comp_sticker_duration') && Number($('comp_sticker_duration').value) <= 0) {
                    $('comp_sticker_duration').value = '4';
                    $('comp_sticker_start').value = Math.max(0, video.currentTime).toFixed(1);
                }
                const msg = `🎯 Sticker placed on the face (${target}) found at ${data.time}s — ${data.x}%, ${data.y}%, scale ${data.scale}%. It stays at this spot; press Apply to save.`;
                if ($('snapFaceStatus')) $('snapFaceStatus').textContent = msg;
                say(msg);
                drawCaption();
            } else {
                const msg = data.message || 'No face detected around this timestamp.';
                if ($('snapFaceStatus')) $('snapFaceStatus').textContent = `⚠️ ${msg}`;
                say(msg, true);
            }
        });
    }
    if ($('stickerFile')) {
        $('stickerFile').onchange = () => {
            const f = $('stickerFile').files[0];
            if (f) {
                selectedEmoji = null;
                clearStickerPending = false;
                if ($('activeStickerNotice')) $('activeStickerNotice').textContent = `Active sticker: File "${f.name}" (Click Apply to upload)`;
                drawCaption();
            }
        };
    }
    if ($('clearStickerBtn')) {
        $('clearStickerBtn').onclick = () => {
            selectedEmoji = null;
            clearStickerPending = true;
            if ($('activeStickerNotice')) $('activeStickerNotice').textContent = 'Sticker removed. Click Apply to save.';
            scheduleUploadDraft();
            if ($('comp_sticker_duration')) $('comp_sticker_duration').value = '0';
            drawCaption();
        };
    }
    if ($('applyStickerBtn')) $('applyStickerBtn').onclick = act(() => applyCompositionChanges(true));
    async function syncStockKeyStatus() {
        try {
            const prov=$('stockProvider').value;
            document.querySelectorAll('[data-stock-provider]').forEach(b=>b.classList.toggle('active',b.dataset.stockProvider===prov));
            if(prov==='youtube'||prov==='mixkit') {
                $('stockKeySummary').textContent=`✅ No API Key Needed (${prov==='youtube'?'YouTube Shorts / Google':'Mixkit HD Stock'} is free)`;
                if($('stockKeyDetails')) $('stockKeyDetails').open=false;
                return;
            }
            const keys=await api('/api/captions/stock/keys');
            $('stockKeySummary').textContent=keys[prov]?`API key setup (${prov.toUpperCase()} key saved ✓)`:'API key setup (paste your free API key below)';
            if($('stockKeyDetails')) $('stockKeyDetails').open=!keys[prov];
        } catch {}
    }
    function openStockDialog(target) {
        stockTarget=target;
        reopenCompAfterStock=!!$('compositionDialog')?.open;
        if(reopenCompAfterStock) $('compositionDialog').close();
        $('stockStatus').textContent='';
        const shape=target==='song'?$('songShape').value:($('comp_shape').value||project?.studio?.settings?.shape||'portrait');
        if(['portrait','landscape','square'].includes(shape)) $('stockOrientation').value=shape;
        drawSequenceLists();
        syncStockKeyStatus();
        $('stockDialog').showModal();
        if($('stockResults') && !$('stockResults').children.length) {
            if(!$('stockQuery').value.trim()) $('stockQuery').value='dance';
            runStockSearch().catch(()=>{});
        }
    }
    $('browseStockSong').onclick=()=>openStockDialog('song');
    $('browseStockComp').onclick=()=>openStockDialog('composition');
    $('openStockBrowser').onclick=()=>openStockDialog(project?.studio?'composition':'song');
    $('closeStock').onclick=()=>{
        $('stockDialog').close();
        if(reopenCompAfterStock && project?.studio) {
            reopenCompAfterStock=false;
            $('compositionDialog').showModal();
            drawSequenceLists();
        }
    };
    if($('applyStockSequence')) $('applyStockSequence').onclick=act(async()=>{
        reopenCompAfterStock=false;
        $('stockDialog').close();
        await applyCompositionChanges(false);
    });
    $('stockProvider').onchange=syncStockKeyStatus;
    $('saveStockKey').onclick=act(async()=>{
        const prov=$('stockProvider').value, key=$('stockApiKey').value.trim();
        await api('/api/captions/stock/keys','POST',{[prov]:key});
        $('stockApiKey').value='';
        await syncStockKeyStatus();
        $('stockStatus').textContent=key?`${prov.toUpperCase()} API key saved locally.`:`${prov.toUpperCase()} API key cleared.`;
    });
    async function runStockSearch() {
        $('stockStatus').textContent='Searching stock backgrounds…';
        $('stockSearch').disabled=true;
        try {
            const payload={
                provider:$('stockProvider').value,
                kind:$('stockKind').value,
                orientation:$('stockOrientation').value,
                max_duration:Number($('stockMaxDuration').value||0),
                query:$('stockQuery').value,
                api_key:$('stockApiKey').value.trim()
            };
            const data=await api('/api/captions/stock/search','POST',payload);
            if(payload.api_key){$('stockApiKey').value='';syncStockKeyStatus();}
            const grid=$('stockResults');grid.replaceChildren();
            if(!data.results?.length){$('stockStatus').textContent='No matching stock backgrounds found. Try another search term or orientation.';return;}
            $('stockStatus').textContent=`Found ${data.results.length} stock backgrounds. Hover video cards to preview; click "+ Add clip to video" on as many clips as you want!`;
            const isProjectMode = stockTarget !== 'song' && !!project?.studio;
            const defaultBtnLabel = isProjectMode ? '+ Add clip to video' : 'Download & select';
            data.results.forEach(item=>{
                const card=document.createElement('div');card.className='stockCard';
                if(item.kind==='video' && item.provider!=='youtube') {
                    const vid=document.createElement('video');
                    vid.src=item.download_url;vid.poster=item.preview_url;vid.muted=true;vid.loop=true;vid.playsInline=true;vid.preload='none';
                    vid.onmouseenter=()=>vid.play?.().catch(()=>{});
                    vid.onmouseleave=()=>{vid.pause?.();};
                    card.append(vid);
                } else {
                    const img=document.createElement('img');img.src=item.preview_url;img.alt=item.title;img.loading='lazy';
                    card.append(img);
                }
                const title=document.createElement('strong');title.textContent=item.title;title.style.fontSize='12px';
                const meta=document.createElement('small');
                const link=document.createElement('a');link.href=item.source_url;link.target='_blank';link.rel='noopener noreferrer';link.textContent=item.attribution;
                meta.append(link, ` · ${item.width}×${item.height} · ${item.license}`);
                const useBtn=document.createElement('button');useBtn.type='button';useBtn.className='primary';useBtn.textContent=defaultBtnLabel;
                let addedCount=0;
                useBtn.onclick=act(async()=>{
                    useBtn.disabled=true;useBtn.textContent='Downloading…';
                    try {
                        const saved=await api('/api/captions/stock/download','POST',item);
                        await refreshLibraries();
                        if(!isProjectMode) {
                            selectedStock.song=saved;
                            if(![...$('songLibrary').options].some(o=>o.value===saved.path)) $('songLibrary').append(new Option(saved.name,saved.path));
                            $('songLibrary').value=saved.path;$('songBackground').value='';
                            $('songStockNotice').hidden=false;
                            $('songStockNotice').textContent=`Selected stock: ${saved.provenance.attribution} (${saved.provenance.license})`;
                            $('stockDialog').close();
                            if(!$('songDialog').open) $('songDialog').showModal();
                        } else {
                            selectedStock.composition=saved;
                            checkpointSequence();clipSequence.push({path:saved.path,name:saved.name,duration:0,provenance:saved.provenance});
                            addedCount++;
                            drawSequenceLists();
                            if(![...$('compLibrary').options].some(o=>o.value===saved.path)) $('compLibrary').append(new Option(saved.name,saved.path));
                            $('compStockNotice').hidden=false;
                            $('compStockNotice').textContent=`Added to sequence (${clipSequence.length} clips total): ${saved.provenance.attribution}`;
                            $('stockStatus').textContent=`Added "${saved.name}" — ${clipSequence.length} clip(s) in your video sequence! Add more clips or click "Apply ${clipSequence.length} clip(s) to video now" below.`;
                        }
                        say(`Downloaded ${saved.name} (${saved.provenance.attribution}).`);
                    } finally {
                        useBtn.disabled=false;
                        useBtn.textContent=addedCount?`✓ Added (#${clipSequence.length}) · Add again`:defaultBtnLabel;
                    }
                });
                card.append(title,meta,useBtn);grid.append(card);
            });
        } finally {$('stockSearch').disabled=false;}
    }
    $('stockSearch').onclick=act(runStockSearch);
    $('stockQuery').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('stockSearch').click();}};
    document.querySelectorAll('[data-stock-provider]').forEach(b=>{
        b.onclick=()=>{
            $('stockProvider').value=b.dataset.stockProvider;
            syncStockKeyStatus();
            if(!$('stockQuery').value.trim()) $('stockQuery').value='dance';
            runStockSearch().catch(e=>say(e.message,true));
        };
    });
    document.querySelectorAll('[data-stock-chip]').forEach(b=>{
        b.onclick=()=>{
            $('stockQuery').value=b.dataset.stockChip;
            runStockSearch().catch(e=>say(e.message,true));
        };
    });
    async function grabSocialClip(inputEl, btnEl) {
        const url=(inputEl?.value||'').trim();
        if(!url) throw Error('Paste a TikTok, Instagram Reel, or YouTube Short URL first.');
        const origText=btnEl.textContent;
        btnEl.disabled=true; btnEl.textContent='Grabbing…';
        say('Downloading video clip without watermark…');
        try {
            const saved=await api('/api/captions/stock/grab-url','POST',{url});
            inputEl.value='';
            await refreshLibraries();
            if(project?.studio) {
                checkpointSequence();clipSequence.push({path:saved.path,name:saved.title||saved.name,duration:0});
                drawSequenceLists();
                if($('stockStatus')) $('stockStatus').textContent=`Grabbed "${saved.title||saved.name}" and added to your clip sequence (${clipSequence.length} clips total)! Click "✨ Apply" to render.`;
                say(`Grabbed "${saved.title||saved.name}" and added to your video sequence (${clipSequence.length} clips). Click "✨ Apply Clip Sequence to Video" to render!`);
            } else {
                if(![...$('songLibrary').options].some(o=>o.value===saved.path)) $('songLibrary').append(new Option(saved.name,saved.path));
                $('songLibrary').value=saved.path;
                say(`Grabbed "${saved.title||saved.name}" into your library! Open or create a project to use it.`);
            }
        } finally {
            btnEl.disabled=false; btnEl.textContent=origText;
        }
    }
    if($('grabClipBtn')) $('grabClipBtn').onclick=act(()=>grabSocialClip($('grabClipUrl'),$('grabClipBtn')));
    if($('grabClipUrl')) $('grabClipUrl').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('grabClipBtn').click();}};
    if($('grabStockBtn')) $('grabStockBtn').onclick=act(()=>grabSocialClip($('grabStockUrl'),$('grabStockBtn')));
    if($('grabStockUrl')) $('grabStockUrl').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('grabStockBtn').click();}};

    // --- Autonomous AI Backdrop Generator ---
    let latestGeneratedBackdrop = null;

    document.querySelectorAll('[data-backdrop-prompt]').forEach(b => {
        b.onclick = () => {
            const promptVal = b.dataset.backdropPrompt;
            if (promptVal === 'auto-lyrics') {
                let words = [];
                if (project?.captions?.length) {
                    words = project.captions.slice(0, 12).map(c => c.text || '').filter(Boolean);
                }
                const sampleText = words.length ? words.join(' ') : ($('songLibrary')?.value || 'Aesthetic music video');
                const cleanSample = sampleText.replace(/[^a-zA-Z0-9\s]/g, '').trim().slice(0, 100);
                $('aiBackdropPrompt').value = `Cinematic atmospheric music backdrop for: "${cleanSample}", dynamic volumetric lighting, 8k vertical video wallpaper`;
                say('Prompt auto-generated from song lyrics!');
            } else {
                $('aiBackdropPrompt').value = promptVal;
            }
        };
    });

    if ($('aiBackdropSongBtn')) $('aiBackdropSongBtn').onclick = () => {
        switchDock('ai-backdrop');
        if (!$('aiBackdropPrompt').value.trim()) {
            $('aiBackdropFromLyricsBtn')?.click();
        }
    };
    if ($('seqAiBackdropBtn')) $('seqAiBackdropBtn').onclick = () => switchDock('ai-backdrop');
    if ($('compAiBackdropBtn')) $('compAiBackdropBtn').onclick = () => switchDock('ai-backdrop');

    function showBackdropUnavailable(statusEl, message, hint) {
        const setup = document.createElement('button');
        setup.type = 'button';
        setup.className = 'primary';
        setup.textContent = 'Set up AI';
        setup.onclick = () => (typeof window.openAISetup === 'function' ? window.openAISetup(hint) : (window.location.href = '/#ai-setup'));
        const title = document.createElement('strong');
        title.textContent = 'Not available on this PC';
        const text = document.createElement('span');
        text.textContent = ` ${message} `;
        statusEl.hidden = false;
        statusEl.replaceChildren(title, text, setup);
    }
    if ($('generateAiBackdropBtn')) {
        $('generateAiBackdropBtn').onclick = act(async () => {
            const prompt = ($('aiBackdropPrompt')?.value || '').trim();
            if (!prompt) throw Error('Please describe the backdrop or select a preset chip above.');

            const style = $('aiBackdropStyle')?.value || 'auto';
            const format = $('aiBackdropFormat')?.value || 'image';
            const isMotion = format === 'video';
            const btn = $('generateAiBackdropBtn');
            const statusEl = $('aiBackdropStatus');

            const origText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<span>⏳ Generating with FLUX on this PC…</span>`;
            if (statusEl) {
                statusEl.hidden = false;
                statusEl.textContent = isMotion ? 'Generating the image, then adding a camera push-in (no AI motion)…' : 'Generating the image locally…';
            }

            try {
                let res;
                try {
                    res = await api('/api/captions/generate-backdrop', 'POST', {prompt, style, motion: isMotion, duration: 10.0, use_character: false});
                } catch (error) {
                    if (error.status !== 424 || !statusEl) throw error;
                    showBackdropUnavailable(statusEl, error.message, error.setupHint);
                    return;
                }

                latestGeneratedBackdrop = res;
                await refreshLibraries();

                const card = $('aiBackdropResultCard');
                const imgEl = $('aiBackdropPreviewImg');
                const vidEl = $('aiBackdropPreviewVid');

                if (card) card.style.display = 'block';

                if (isMotion && vidEl) {
                    vidEl.src = res.url;
                    vidEl.style.display = 'block';
                    if (imgEl) imgEl.style.display = 'none';
                    vidEl.play().catch(() => {});
                } else if (imgEl) {
                    imgEl.src = res.url;
                    imgEl.style.display = 'block';
                    if (vidEl) {
                        vidEl.pause();
                        vidEl.style.display = 'none';
                    }
                }

                if (statusEl) {
                    statusEl.textContent = `✓ Generated ${res.name} • Ready to apply or add to sequence!`;
                }
                say(isMotion ? '✓ Backdrop generated (camera push-in added, no AI motion).' : '✓ Backdrop generated with FLUX.');
            } finally {
                btn.disabled = false;
                btn.innerHTML = origText;
            }
        });
    }

    if ($('aiBackdropApplyBgBtn')) {
        $('aiBackdropApplyBgBtn').onclick = act(async () => {
            if (!latestGeneratedBackdrop) throw Error('No backdrop generated yet.');
            const item = latestGeneratedBackdrop;

            if (![...$('songLibrary').options].some(o => o.value === item.path)) {
                $('songLibrary').append(new Option(item.name, item.path));
            }
            $('songLibrary').value = item.path;
            if ($('songBackground')) $('songBackground').value = '';

            if (project?.studio) {
                if (![...$('compLibrary').options].some(o => o.value === item.path)) {
                    $('compLibrary').append(new Option(item.name, item.path));
                }
                $('compLibrary').value = item.path;
                if ($('compClear')) $('compClear').checked = false;
                say(`✓ Applied "${item.name}" as active project background!`);
                switchDock('canvas');
                drawCaption();
            } else {
                say(`✓ Set "${item.name}" as background for your new song project!`);
                switchDock('media');
            }
        });
    }

    if ($('aiBackdropAddToSeqBtn')) {
        $('aiBackdropAddToSeqBtn').onclick = act(async () => {
            if (!latestGeneratedBackdrop) throw Error('No backdrop generated yet.');
            const item = latestGeneratedBackdrop;

            if (project?.studio) {
                checkpointSequence();
                clipSequence.push({
                    path: item.path,
                    name: item.name,
                    duration: 0,
                    provenance: item.provenance
                });
                drawSequenceLists();
                say(`✓ Added "${item.name}" to video sequence (${clipSequence.length} clips total)!`);
                switchDock('media');
            } else {
                if (![...$('songLibrary').options].some(o => o.value === item.path)) {
                    $('songLibrary').append(new Option(item.name, item.path));
                }
                $('songLibrary').value = item.path;
                say(`Saved to library: "${item.name}". Open or create a project to use it.`);
            }
        });
    }

    if ($('aiBackdropDownloadBtn')) {
        $('aiBackdropDownloadBtn').onclick = () => {
            if (!latestGeneratedBackdrop) return;
            const a = document.createElement('a');
            a.href = latestGeneratedBackdrop.url;
            a.download = latestGeneratedBackdrop.name;
            a.click();
        };
    }
    $('restoreComposition').onclick=act(async()=>{
        if(!project||!confirm('Restore the previous composition and its captions? The current version will become the restore point.'))return;
        await save();video.pause();project=await api(`/api/captions/${project.id}/restore-composition`,'POST',{revision:project.revision});history=[];future=[];selected=0;mountVideo();refresh();
    });
    $('duplicateProject').onclick=act(async()=>{
        if(!project)return;await save();video.pause();
        const data=await api(`/api/captions/${project.id}/duplicate`,'POST',{revision:project.revision});await load(data.id);
    });
    $('recoverEdits').onclick=act(()=>{
        const draft=readDraft('captions');if(!draft)return;
        if(!confirm('Recover this browser’s unsaved caption draft? Review it before saving; it may be older than your current project.'))return;
        CaptionTiming.validate(draft.data.cues,project.duration);checkpoint();Object.assign(project,draft.data);selected=0;changed();refresh();
    });
    $('openLibrary').onclick=act(async()=>{if(!$('library').value)throw Error('Choose a library video.');const f=new FormData();f.append('path',$('library').value);await create(f);});
    $('projects').onchange=act(async()=>{if($('projects').value)await load($('projects').value);});
    $('reload').onclick=act(async()=>{if(!project)return;if(dirty&&!confirm('Discard unsaved edits and reload the saved project?'))return;dirty=false;await load(project.id);});
    $('save').onclick=act(save);
    $('play').onclick=act(async()=>{if(video.paused)await video.play();else video.pause();});
    video.onplay=()=>{$('play').textContent='❚❚ Pause';};video.onpause=()=>{$('play').textContent='▶ Play';};
    $('speed').onchange=()=>{video.playbackRate=Number($('speed').value);};
    $('safe').onchange=()=>{$('guides').hidden=!$('safe').checked;};
    $('zoom').oninput=drawTimeline;
    $('waveform').onclick=e=>{if(project)video.currentTime=(e.clientX-e.currentTarget.getBoundingClientRect().left)/e.currentTarget.clientWidth*project.duration;};
    function tick() {
        if(project){
            if($('loop').checked && current() && !video.paused && (video.currentTime>=current().end || video.currentTime<current().start))video.currentTime=current().start;
            $('time').textContent=fmt(video.currentTime)+' / '+fmt(project.duration);
            $('playhead').style.left=video.currentTime/project.duration*100+'%';drawCaption();
        }
        requestAnimationFrame(tick);
    }
    for(const key of styleKeys) {
        const updateStyle=()=>{
            if(!project||busy)return;
            const scoped=new Set(['font','size','color','highlight','outline','position','background','alignment','horizontal','box_width','line_spacing','letter_spacing','box_padding','box_radius','translation_size','translation_color','translation_gap','animation','glow']);
            const val=styleChecks.includes(key)?$(key).checked:styleNumbers.includes(key)?Number($(key).value):$(key).value;
            const selectedScope=$('styleScope').value==='selected'&&current()&&scoped.has(key);
            const previous=selectedScope?(current().style_override?.[key]??project.style[key]):project.style[key];
            if(previous===val)return;
            edit(()=>{
            if(['line_spacing','letter_spacing','box_width','horizontal','alignment','box_padding','box_radius','translation_size','translation_color','translation_gap'].includes(key)){project.style.layout_enabled=true;$('layout_enabled').checked=true;}
            if($('styleScope').value==='selected'&&current()&&scoped.has(key)){current().style_override??={};current().style_override[key]=val;}
            else project.style[key]=val;
            const compMirror=key.startsWith('visualizer')?null:$('comp_'+key);
            if(compMirror) {if(styleChecks.includes(key))compMirror.checked=!!val;else compMirror.value=val;}
            if(key==='translation_language' && $('workspace_translation_language')) $('workspace_translation_language').value=val;
            if(key==='track_mode' && $('workspace_track_mode')) $('workspace_track_mode').value=val;
            if(key==='video_filter') document.querySelectorAll('[data-filter-pill]').forEach(b=>b.classList.toggle('active',b.dataset.filterPill===val));
            if(key==='animation') triggerAnimationPreview(val);
            },false);
        };
        $(key).oninput=updateStyle; $(key).onchange=updateStyle;
    }
    let positionMode=false;
    $('placeCaption').onclick=()=>{positionMode=!positionMode;$('placeCaption').textContent=positionMode?'Click or drag on the preview…':'Place text on preview';};
    $('stage').addEventListener('pointerdown',event=>{
        if(!positionMode||!project||busy)return;event.preventDefault();video.pause();
        const before=snapshot(),rect=$('stage').getBoundingClientRect();
        const update=e=>{let x=(e.clientX-rect.left)/rect.width*100,y=(e.clientY-rect.top)/rect.height*100;
            if(Math.abs(x-50)<2)x=50;if(Math.abs(y-50)<2)y=50;
            const target=$('styleScope').value==='selected'&&current()?(current().style_override??={}):project.style;
            target.horizontal=Math.max(2,Math.min(98,x));target.position=Math.max(10,Math.min(95,y));project.style.layout_enabled=true;drawCaption();};
        $('stage').setPointerCapture(event.pointerId);update(event);
        $('stage').onpointermove=update;
        $('stage').onpointerup=()=>{$('stage').onpointermove=null;$('stage').onpointerup=null;history.push(before);future=[];changed();positionMode=false;$('placeCaption').textContent='Place text on preview';refresh();};
        $('stage').onpointercancel=()=>{$('stage').onpointermove=null;$('stage').onpointerup=null;Object.assign(project,before);refresh();};
    });
    $('styleScope').onchange=()=>fillSelection();
    $('clearLineStyle').onclick=()=>{if(current())edit(()=>{delete current().style_override;});};
    const prevAnimBtn = $('previewAnimBtn');
    if(prevAnimBtn) {
        prevAnimBtn.onclick = () => triggerAnimationPreview($('animation')?.value);
    }
    document.querySelectorAll('[data-filter-pill]').forEach(b=>{
        b.onclick=()=>{
            if(!project||busy) return;
            $('video_filter').value=b.dataset.filterPill;
            $('video_filter').onchange();
        };
    });
    const presets={
        mrbeast_bold:{font:'Montserrat',size:6.8,outline:3.8,position:78,background:false,karaoke:true,cumulative:false,word_pop:true,animation:'pop',color:'#ffe600',highlight:'#ffffff',visualizer:false},
        cyberpunk_neon:{font:'Montserrat',size:5.5,outline:2.8,position:82,background:false,karaoke:true,cumulative:true,word_pop:true,animation:'typewriter',glow:8,color:'#00f0ff',highlight:'#ff0055',visualizer:true,visualizer_style:'spectrum',visualizer_position:'bottom',visualizer_height:20,visualizer_sensitivity:1.4,visualizer_color:'#00f0ff'},
        frosted_vlog:{font:'Roboto',size:4.6,outline:0,position:86,background:true,karaoke:true,cumulative:false,word_pop:false,animation:'fade',color:'#f8f9fa',highlight:'#a5f3fc',visualizer:false},
        sunset_glow:{font:'Montserrat',size:5.4,outline:2.2,position:80,background:false,karaoke:true,cumulative:true,word_pop:true,animation:'slide_up',glow:6,color:'#ffffff',highlight:'#ff7b54',visualizer:true,visualizer_style:'waveform',visualizer_position:'bottom',visualizer_height:16,visualizer_sensitivity:1.1,visualizer_color:'#ff7b54'},
        neon_karaoke:{font:'Montserrat',size:5.5,outline:2.5,position:82,background:false,karaoke:true,cumulative:true,word_pop:true,color:'#ffffff',highlight:'#00f5d4',visualizer:true,visualizer_style:'spectrum',visualizer_position:'bottom',visualizer_height:18,visualizer_sensitivity:1.2,visualizer_color:'#00f5d4'},
        cinematic_clean:{font:'Roboto',size:4.5,outline:1.5,position:88,background:true,karaoke:true,cumulative:false,word_pop:false,color:'#f8f9fa',highlight:'#ffd166',visualizer:false},
        bold_pop:{font:'Montserrat',size:6.5,outline:3.5,position:78,background:false,karaoke:true,cumulative:false,word_pop:true,color:'#ffffff',highlight:'#ffdc55',visualizer:true,visualizer_style:'spectrum',visualizer_position:'bottom',visualizer_height:20,visualizer_sensitivity:1.3,visualizer_color:'#ffdc55'},
        minimalist_lyric:{font:'Roboto',size:4.25,outline:1,position:85,background:false,karaoke:true,cumulative:true,word_pop:false,color:'#e9ecef',highlight:'#bba6ff',visualizer:true,visualizer_style:'waveform',visualizer_position:'bottom',visualizer_height:14,visualizer_sensitivity:1.0,visualizer_color:'#bba6ff'},
        clean:{font:'Arial',size:5,outline:2,background:false,karaoke:false,cumulative:false,word_pop:false,color:'#ffffff'},
        bold:{font:'Impact',size:6,outline:3,background:false,karaoke:false,cumulative:false,word_pop:false,color:'#ffffff'},
        lyrics:{font:'Georgia',size:4.5,outline:1,background:false,karaoke:false,cumulative:false,word_pop:false,color:'#ffffff'},
        karaoke:{font:'Verdana',size:5,outline:2,karaoke:true,cumulative:false,word_pop:false,highlight:'#ffdc55'}
    };
    document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>{edit(()=>Object.assign(project.style,presets[b.dataset.preset]));refresh();});
    $('saveStyle').onclick=act(()=>{if(project){localStorage.setItem('captionStyle',JSON.stringify({...project.style,...($('styleScope').value==='selected'?current()?.style_override||{}:{})}));say('Style saved in this browser.');}});
    $('loadStyle').onclick=act(()=>{const s=JSON.parse(localStorage.getItem('captionStyle')||'null');if(!s)throw Error('Save a style first.');edit(()=>{if($('styleScope').value==='selected'&&current()){const {track_mode,translation_language,hide_duplicate_translation,layout_enabled,...rest}=s;const allowed=['font','size','color','highlight','outline','position','background','alignment','horizontal','box_width','line_spacing','letter_spacing','box_padding','box_radius','translation_size','translation_color','translation_gap','animation','glow'];current().style_override=Object.fromEntries(Object.entries(rest).filter(([k])=>allowed.includes(k)));}else project.style=s;});refresh();});
    function injectFontFace(family, url) {
        let tag = $('dynamicCustomFonts');
        if (!tag) {
            tag = document.createElement('style');
            tag.id = 'dynamicCustomFonts';
            document.head.appendChild(tag);
        }
        const rule = `@font-face { font-family: ${JSON.stringify(family)}; src: url(${JSON.stringify(url)}); font-display: swap; }`;
        if (!tag.textContent.includes(`"${family}"`)) {
            tag.textContent += '\n' + rule;
        }
    }
    async function loadCustomFonts() {
        try {
            const res = await api('/api/captions/fonts');
            if (res.custom && Array.isArray(res.custom)) {
                res.custom.forEach(f => {
                    injectFontFace(f.family, f.url);
                    if (!Array.from($('font').options).some(o => o.value === f.family)) {
                        $('font').add(new Option(`${f.family} (Custom)`, f.family));
                    }
                });
            }
        } catch {}
    }
    if ($('fontUploadInput')) {
        $('fontUploadInput').onchange = act(async () => {
            const file = $('fontUploadInput').files[0];
            if (!file) return;
            const fd = new FormData();
            fd.append('font_file', file);
            say('Uploading custom font…');
            const res = await api('/api/captions/fonts/upload', 'POST', fd);
            if (res.family && res.url) {
                injectFontFace(res.family, res.url);
                let opt = Array.from($('font').options).find(o => o.value === res.family);
                if (!opt) {
                    opt = new Option(`${res.family} (Custom)`, res.family);
                    $('font').add(opt);
                }
                $('font').value = res.family;
                if (project?.style) {
                    edit(() => { project.style.font = res.family; }, false);
                    drawCaption();
                }
                say(`Custom font "${res.family}" imported and applied!`);
            }
            $('fontUploadInput').value = '';
        });
    }
    $('text').oninput=()=>{
        if(current()) {
            edit(()=>{const c=current(),value=$('text').value;if(c.text.trim().split(/\s+/).join(' ')!==value.trim().split(/\s+/).join(' ')){c.words=[];for(const tr of Object.values(c.translations||{}))tr.status='stale';}c.text=value;},false);
            drawTimeline();drawList();$('words').replaceChildren();
        }
    };
    $('text').onchange=()=>{drawTimeline();drawList();fillSelection();};
    /** Editor wrapper around CaptionTiming.setCueTranslation: one undo step, autosave, redraw. */
    async function writeTranslation(cue,lang,text,options={}) {
        if(!project||busy||!cue)return null;
        checkpoint();
        const record=await CaptionTiming.setCueTranslation(cue,lang,text,options);
        changed(false);
        drawList();fillSelection();
        return record;
    }
    if($('sideTranslationText')){
        // Writes are chained so a slower hash can never overwrite newer keystrokes.
        let sideWrite=Promise.resolve();
        $('sideTranslationText').oninput=()=>{
            const c=current();
            if(!c||busy)return;
            const lang=project?.style?.translation_language||'en';
            const val=$('sideTranslationText').value;
            storeDraft('translation-'+c.id+'-'+lang,{text:val});
            if($('translationText')) $('translationText').value=val;
            sideWrite=sideWrite.then(async()=>{
                if(current()!==c)return;
                checkpoint();
                await CaptionTiming.setCueTranslation(c,lang,$('sideTranslationText').value,{status:'approved',locked:true});
                changed(false);
                drawTimeline();drawList();drawTranslationReview(c);
            }).catch(e=>say(e.message,true));
        };
        $('sideTranslationText').onchange=()=>{drawTimeline();drawList();drawCaption();};
    }
    if($('keepTranslation')) $('keepTranslation').onclick=act(async()=>{
        const c=current(),lang=project?.style?.translation_language||'en',entry=c?.translations?.[lang];
        if(!entry?.text)throw Error('This line has no translation to keep.');
        await writeTranslation(c,lang,entry.text,{status:'approved',note:''});
        say('Translation kept and approved for the current line.');
    });
    if($('retranslateLine')) $('retranslateLine').onclick=act(async()=>{
        if(!current())throw Error('Select a lyric line first.');
        await job('translate',{language:project.style.translation_language||'en',ids:[current().id]});
    });
    if($('showDuplicateTranslation')) $('showDuplicateTranslation').onchange=()=>{
        const c=current();if(!c)return;
        const show=$('showDuplicateTranslation').checked;
        edit(()=>{if(show)c.show_duplicate_translation=true;else delete c.show_duplicate_translation;},false);
        drawCaption();
    };
    for(const k of ['start','end']) $(k).onchange=()=>{if(current())timingEdit(()=>{current()[k]=Number($(k).value);current().words=[];});};
    $('setStart').onclick=()=>{if(current())timingEdit(()=>{current().start=video.currentTime;current().words=[];});};
    $('setEnd').onclick=()=>{if(current())timingEdit(()=>{current().end=video.currentTime;current().words=[];});};
    $('add').onclick=act(()=>{
        if(!project)return;const t=video.currentTime;
        if(project.cues.some(c=>c.start<=t&&c.end>t))throw Error('Move the playhead into a gap before adding a line.');
        const next=project.cues.find(c=>c.start>t),end=Math.min(t+2,next?.start??project.duration);
        if(end-t<.05)throw Error('There is no room for a caption here.');
        edit(()=>{const cue={start:t,end,text:'New caption',words:[]};project.cues.push(cue);project.cues.sort((a,b)=>a.start-b.start);selected=project.cues.indexOf(cue);});
    });
    $('delete').onclick=()=>{if(current())edit(()=>{project.cues.splice(selected,1);selected=Math.min(selected,project.cues.length-1);});};
    $('split').onclick=act(()=>{
        const c=current(),t=video.currentTime;if(!c||t<=c.start||t>=c.end)throw Error('Place the playhead inside the selected line.');
        edit(()=>project.cues.splice(selected,1,...CaptionTiming.splitCaption(c,t,'cue_'+Date.now().toString(36)+'_'+Math.random().toString(36).slice(2))));
    });
    $('merge').onclick=()=>{const c=current(),next=project?.cues[selected+1];if(c&&next)edit(()=>project.cues.splice(selected,2,CaptionTiming.mergeCaptions(c,next)));};
    $('estimateWords').onclick=()=>{const c=current();if(c)timingEdit(()=>{const words=c.text.trim().split(/\s+/);c.words=words.map((text,i)=>({text,start:i===0?c.start:c.start+(c.end-c.start)*i/words.length,end:i===words.length-1?c.end:c.start+(c.end-c.start)*(i+1)/words.length}));c.karaoke={state:'estimated',note:'Evenly spaced estimates, not audio alignment'};say('Word timings are evenly spaced estimates for this line only. Play this line to see highlighting; adjust the timings while listening.');});};
    $('shiftAll').onclick=act(()=>{
        if(!project)return;const shift=Number($('shift').value);
        if(!Number.isFinite(shift)||project.cues.some(c=>c.start+shift<0||c.end+shift>project.duration))throw Error('That shift would move captions outside the video.');
        edit(()=>project.cues.forEach(c=>{c.start+=shift;c.end+=shift;c.words.forEach(w=>{w.start+=shift;w.end+=shift;});}));
    });
    function undo(redo=false) {
        if(!project||busy)return;const source=redo?future:history,dest=redo?history:future;if(!source.length)return;
        const state=source.pop();
        if(state._composition){dest.push({_composition:compositionSettings()});fillComposition(state._composition);storeDraft('composition',{source:project.source,settings:state._composition});drawCaption();return;}
        if(state._sequence){dest.push({_sequence:clipSequence.map(c=>({...c}))});clipSequence=state._sequence;drawSequenceLists();return;}
        dest.push(snapshot());Object.assign(project,state);selected=Math.min(selected,project.cues.length-1);changed();refresh();
    }
    $('undo').onclick=()=>undo();$('redo').onclick=()=>undo(true);
    function saveLyricsDraft() {
        if(project) storeDraft('lyrics', {text:$('lyrics').value, language:$('alignLanguage').value, start:$('alignStart').value, end:$('alignEnd').value});
    }
    $('lyrics').oninput=saveLyricsDraft;
    $('alignLanguage').onchange=saveLyricsDraft;
    $('alignStart').onchange=saveLyricsDraft;
    $('alignEnd').onchange=saveLyricsDraft;
    $('clearLyricsDraft').onclick=()=>{if(project)storeDraft('lyrics',null);$('lyrics').value='';};
    $('paste').onclick=()=>{
        if(!project)return;
        $('alignStart').value=0;
        $('alignEnd').value=project.duration.toFixed(3);
        $('alignLanguage').value=$('language').value||'en';
        const draft=readDraft('lyrics');
        if(draft&&draft.text) {
            $('lyrics').value=draft.text;
            if(draft.language)$('alignLanguage').value=draft.language;
            if(draft.start!==undefined)$('alignStart').value=draft.start;
            if(draft.end!==undefined)$('alignEnd').value=draft.end;
        }
        $('lyricsDialog').showModal();
    };
    $('useCurrentLyrics').onclick=()=>{
        $('lyrics').value=project.cues.map(c=>c.text).join('\n');
        saveLyricsDraft();
    };
    $('correctLyrics').onclick=act(async()=>{
        if(!$('lyrics').value.trim())throw Error('Paste your correct lyrics first.');
        if(!project.cues?.length)throw Error('Transcribe the audio or import subtitles first so we have line timings to match.');
        const options={text:$('lyrics').value,language:$('alignLanguage').value,start:Number($('alignStart').value),end:Number($('alignEnd').value),review:true};
        $('correctLyrics').disabled=true;
        try {checkpoint();await job('correct-lyrics',options);$('lyricsDialog').close();}
        finally {$('correctLyrics').disabled=false;}
    });
    $('alignLyrics').onclick=act(async()=>{
        if(!$('lyrics').value.trim())throw Error('Paste the lyrics sung in this video first.');
        const options={text:$('lyrics').value,language:$('alignLanguage').value,start:Number($('alignStart').value),end:Number($('alignEnd').value),review:true};
        $('alignLyrics').disabled=true;
        try {checkpoint();await job('align',{...options,sections:true});$('lyricsDialog').close();} finally {$('alignLyrics').disabled=false;}
    });
    $('resumeLyrics').onclick=act(async()=>{
        if(!$('lyrics').value.trim())throw Error('Restore the same pasted lyrics, language and range before resuming.');
        await job('align',{text:$('lyrics').value,language:$('alignLanguage').value,
            start:Number($('alignStart').value),end:Number($('alignEnd').value),review:true,sections:true,resume:true});
        $('lyricsDialog').close();
    });
    let lyricListenEnd=null;
    video.addEventListener('timeupdate',()=>{
        if(lyricListenEnd!==null && video.currentTime>=lyricListenEnd){video.pause();lyricListenEnd=null;}
    });
    $('lyricReviewDialog').addEventListener('close',()=>{video.pause();lyricListenEnd=null;});
    function showLyricReview() {
        const proposal=project?.lyric_proposal;
        if(!proposal)return;
        const rows=$('lyricReviewRows');rows.replaceChildren();
        const cues=proposal.cues.filter(c=>c.start>=proposal.start && c.end<=proposal.end);
        const flagged=cues.filter(needsReview).length;
        $('lyricReviewSummary').textContent=`${cues.length} proposed lines · ${flagged} need timing review. Your saved captions are unchanged. Listen to the song and compare the text below. Timing labels are checks, not accuracy scores.`;
        for(const cue of cues) {
            const card=document.createElement('article');card.className='lyricReviewRow';
            const timing=document.createElement('button');timing.type='button';
            timing.textContent=`Listen ${cue.start.toFixed(2)}–${cue.end.toFixed(2)} s`;
            timing.onclick=act(async()=>{$('loop').checked=false;lyricListenEnd=cue.end;video.currentTime=cue.start;await video.play();});
            const label=document.createElement('strong');label.textContent=needsReview(cue)?'Check timing':'Word timings available';
            const old=document.createElement('p');
            old.textContent='Current: '+(project.cues.filter(c=>c.start<cue.end && c.end>cue.start).map(c=>c.text).join(' / ')||'(No caption here)');
            const next=document.createElement('p');next.textContent='Proposed: '+cue.text;
            const note=document.createElement('small');note.textContent=cue.karaoke?.note||'Review while listening, especially sustained notes and repeated choruses.';
            card.append(timing,label,old,next,note);rows.append(card);
        }
        $('lyricReviewDialog').showModal();
    }
    $('reviewLyrics').onclick=showLyricReview;
    $('closeLyricReview').onclick=()=>{video.pause();$('lyricReviewDialog').close();};
    async function finishLyricReview(action) {
        video.pause();await save();
        const proposal=project.lyric_proposal;if(!proposal)return;
        if(action==='apply')checkpoint();
        project=await api(`/api/captions/${project.id}/lyric-proposal`,'POST',
            {revision:project.revision,id:proposal.id,action});
        $('lyricReviewDialog').close();selected=0;refresh();
    }
    $('applyLyricReview').onclick=act(()=>finishLyricReview('apply'));
    $('discardLyricReview').onclick=act(()=>finishLyricReview('discard'));
    $('translationText').oninput=()=>{if(current())storeDraft('translation-'+current().id+'-'+(project.style.translation_language||'en'),{text:$('translationText').value});};
    $('approveManualTranslation').onclick=act(async()=>{
        const c=current();if(!c)throw Error('Select a caption line first.');
        const text=$('translationText').value.trim();if(!text)throw Error('Enter a translation.');
        const language=project.style.translation_language||'en';
        storeDraft('translation-'+c.id+'-'+language,null);
        await writeTranslation(c,language,text,{status:'approved',locked:$('translationLocked').checked,note:''});
    });
    for(const id of ['translationNotes','translationGlossary','translationModel'])$(id).onchange=()=>{
        if(project)edit(()=>{project.translation_settings={notes:$('translationNotes').value,glossary:$('translationGlossary').value,model:$('translationModel').value};},false);
    };
    let translationSetup=null;
    const ROLE_LABELS={helper:'Helper',translator:'Translator',vision:'Vision'};
    async function refreshTranslationModels(){
        try{
            const data=await api('/api/captions/translation-models');
            const currentVal=$('translationModel').value||(project?.translation_settings?.model||'');
            const auto=data.auto||{};
            translationSetup=data.setup||null;
            const autoLabel=auto.available?`Auto (best for this PC): ${auto.model} · Local`:'Auto (best for this PC): no translator installed';
            const label=m=>`${m.name} · ${(m.roles||[]).map(r=>ROLE_LABELS[r]||r).join(' / ')} · ${m.backend==='builtin'?'Built-in':'Ollama'} · Local`;
            $('translationModel').replaceChildren(new Option(autoLabel,''),...(data.models||[]).map(m=>new Option(label(m),m.name)));
            if(currentVal&&(data.models||[]).some(m=>m.name===currentVal))$('translationModel').value=currentVal;
            const size=translationSetup?.size_bytes?` (${(translationSetup.size_bytes/1e9).toFixed(1)} GB)`:'';
            $('setupTranslationModel').textContent=translationSetup?`Set up ${translationSetup.name}${size}`:'Set up local translator';
            $('setupTranslationModel').hidden=Boolean(auto.available&&!translationSetup);
        }catch(e){say(e.message,true);}
    }
    refreshTranslationModels();
    $('findTranslationModels').onclick=act(async()=>{await refreshTranslationModels();say('Local translation models updated.');});
    $('setupTranslationModel').onclick=()=>{
        if(typeof window.openAISetup==='function')window.openAISetup(translationSetup?.item_id);
    };
    function renderTranslationAB(result){
        const box=$('translationAB');
        const card=(role,title)=>{
            const side=result[role]||{};
            const node=document.createElement('div');
            node.className='ab-side';
            const heading=document.createElement('strong');
            heading.textContent=side.model?`${title} · ${side.model} · Local`:title;
            const body=document.createElement('p');
            body.textContent=side.error||side.text||'';
            node.append(heading,body);
            if(side.note){const note=document.createElement('small');note.textContent=side.note;node.append(note);}
            if(side.text){
                const use=document.createElement('button');
                use.type='button';
                use.textContent='Use this translation';
                use.onclick=act(async()=>{
                    const cue=project.cues.find(c=>c.id===result.cue_id);
                    if(!cue)throw Error('This line no longer exists.');
                    await writeTranslation(cue,result.language,side.text,{status:'approved',note:side.note||'',origin:'ai'});
                    box.hidden=true;say(`${title} translation approved for this line.`);
                });
                node.append(use);
            }else if(side.setup_hint){
                const setup=document.createElement('button');
                setup.type='button';setup.textContent='Set up';
                setup.onclick=()=>window.openAISetup?.(side.setup_hint);
                node.append(setup);
            }
            return node;
        };
        box.replaceChildren(card('translator','Translator'),card('helper','Helper'));
        box.hidden=false;
    }
    $('compareTranslation').onclick=act(async()=>{
        if(!project)throw Error('Open a project first.');
        const cue=current();if(!cue)throw Error('Select a lyric line first.');
        if(dirty)await save();
        say('Comparing Translator and Helper on this line (local)…');
        const result=await api(`/api/captions/${project.id}/translate-ab`,'POST',{cue_id:cue.id,language:project.style.translation_language||'en'});
        renderTranslationAB(result);
        say('Pick the version that reads best. Nothing is saved until you choose.');
    });
    const translateJob=(selectedOnly=false,resume=false)=>act(async()=>{
        if(!project)throw Error('Open a project first.');
        if(selectedOnly&&!current())throw Error('Select a lyric line first.');
        await job('translate',{language:project.style.translation_language||'en',ids:selectedOnly?[current().id]:null,resume});
    });
    $('translateAll').onclick=translateJob();$('translateSelected').onclick=translateJob(true);$('resumeTranslation').onclick=translateJob(false,true);
    if($('workspace_translation_language')){
        $('workspace_translation_language').onchange=()=>{
            const v=$('workspace_translation_language').value;
            if($('translation_language')){$('translation_language').value=v;$('translation_language').dispatchEvent(new Event('change'));}
        };
    }
    if($('workspace_track_mode')){
        $('workspace_track_mode').onchange=()=>{
            const v=$('workspace_track_mode').value;
            if($('track_mode')){$('track_mode').value=v;$('track_mode').dispatchEvent(new Event('change'));}
        };
    }
    function showTranslationReview(){
        const proposal=project?.translation_proposal;if(!proposal){say('No translation proposal is ready.');return;}
        const list=$('translationReviewRows');list.replaceChildren();
        for(const cue of project.cues){const entry=proposal.lines[cue.id];if(!entry)continue;
            const row=document.createElement('article');row.className='lyricReviewRow';
            const original=document.createElement('p');original.textContent=cue.text;
            const text=document.createElement('textarea');text.value=entry.text;text.maxLength=2000;text.dataset.cueId=cue.id;text.setAttribute('aria-label','Translation of '+cue.text);
            const routeLabel={translator:'Translator',helper:'Helper (mixed language)',same:'Same as original'}[entry.route]||entry.route||'';
            const note=document.createElement('p');note.textContent=[routeLabel,entry.note&&entry.note!==routeLabel?entry.note:''].filter(Boolean).join(' · ');row.dataset.route=entry.route||'';
            const warning=document.createElement('small');
            const lengthCheck=()=>{warning.textContent=Array.from(text.value).length/(cue.end-cue.start)>20?'Long for its display time. Consider shorter wording.':'';};text.oninput=lengthCheck;lengthCheck();
            row.append(original,text,note,warning);list.append(row);
        }
        $('translationReviewDialog').showModal();
    }
    $('reviewTranslation').onclick=showTranslationReview;
    $('closeTranslationReview').onclick=()=>$('translationReviewDialog').close();
    async function finishTranslation(action){
        await save();const p=project.translation_proposal;if(!p)return;
        const lines=copy(p.lines);
        for(const input of $('translationReviewRows').querySelectorAll('textarea'))lines[input.dataset.cueId].text=input.value;
        checkpoint();project=await api(`/api/captions/${project.id}/translation-proposal`,'POST',{id:p.id,revision:project.revision,action,lines});
        if(action==='apply' && project?.style?.track_mode==='original'){
            project.style.track_mode='both';
            await save();
        }
        $('translationReviewDialog').close();refresh();
    }
    $('applyTranslationReview').onclick=act(()=>finishTranslation('apply'));
    $('discardTranslationReview').onclick=act(()=>finishTranslation('discard'));
    async function downloadCaptionFile(path, filename) {
        await save();
        const response = await fetch(`/api/captions/${project.id}/${path}`);
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw Error(error.error || 'Could not export captions. Please try again.');
        }
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement('a');
        link.href = url; link.download = filename;
        document.body.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    }
    /* Export guard: nothing is silently dropped from a bilingual or translation export. */
    let exportGuardResolve=null;
    function closeExportGuard(choice){
        const resolve=exportGuardResolve;exportGuardResolve=null;
        if($('exportGuardDialog')?.open)$('exportGuardDialog').close();
        resolve?.(choice);
    }
    async function exportGuard(mode) {
        if(!project||mode==='original')return {proceed:true,skip:false};
        await save();
        const language=project.style.translation_language||'en';
        const report=await api(`/api/captions/${project.id}/translation-status?language=${encodeURIComponent(language)}`);
        const pending=[...report.review,...report.stale],missing=report.missing;
        if(!pending.length&&!missing.length)return {proceed:true,skip:false};
        const total=pending.length+missing.length;
        $('exportGuardTitle').textContent=`${total} line${total===1?'':'s'} need${total===1?'s':''} review`;
        const parts=[];
        if(pending.length)parts.push(`${pending.length} translation${pending.length===1?' is':'s are'} waiting for review (suggested or written for an earlier version of the line).`);
        if(missing.length)parts.push(`${missing.length} line${missing.length===1?' has':'s have'} no translation yet.`);
        parts.push(mode==='translation'?'Lines without an approved translation are left out of a translation-only export.':'Unapproved lines export with the original text only.');
        $('exportGuardSummary').textContent=parts.join(' ');
        const rows=$('exportGuardRows');rows.replaceChildren();
        for(const item of [...pending,...missing].sort((a,b)=>a.index-b.index).slice(0,8)){
            const li=document.createElement('li');
            const badge=document.createElement('span');badge.className='trBadge '+(item.status||'missing');
            badge.textContent=item.status==='missing'?'Missing':item.status==='stale'?'Changed line':'Needs review';
            const label=document.createElement('span');label.textContent=`#${item.index+1} ${item.text}${item.translation?' → '+item.translation:''}`;
            li.append(badge,label);rows.append(li);
        }
        if(total>8){const more=document.createElement('li');more.className='hint';more.textContent=`…and ${total-8} more.`;rows.append(more);}
        $('exportGuardKeep').disabled=!pending.length;
        const choice=await new Promise(resolve=>{exportGuardResolve=resolve;$('exportGuardDialog').showModal();});
        if(choice==='keep'){
            checkpoint();
            for(const item of pending){
                const cue=project.cues.find(c=>c.id===item.id),entry=cue?.translations?.[language];
                if(entry?.text)await CaptionTiming.setCueTranslation(cue,language,entry.text,{status:'approved',note:''});
            }
            changed();await save();
            say(`${pending.length} translation${pending.length===1?'':'s'} kept and approved.`);
            return {proceed:true,skip:missing.length>0};
        }
        if(choice==='review'){
            const first=[...pending,...missing].sort((a,b)=>a.index-b.index)[0];
            const index=project.cues.findIndex(c=>c.id===first?.id);
            if(index>=0){select(index);$('sideTranslationText')?.focus?.();}
            return {proceed:false};
        }
        return choice==='skip'?{proceed:true,skip:true}:{proceed:false};
    }
    if($('exportGuardKeep')){
        $('exportGuardKeep').onclick=()=>closeExportGuard('keep');
        $('exportGuardReview').onclick=()=>closeExportGuard('review');
        $('exportGuardSkip').onclick=()=>closeExportGuard('skip');
        $('exportGuardCancel').onclick=()=>closeExportGuard('cancel');
        $('exportGuardDialog').addEventListener('close',()=>closeExportGuard('cancel'));
    }
    async function guardedCaptionFile(mode,path,filename){
        const guard=await exportGuard(mode);
        if(!guard.proceed)return;
        const separator=path.includes('?')?'&':'?';
        await downloadCaptionFile(guard.skip?`${path}${separator}skip_missing=1`:path,filename);
    }
    $('translationSrt').onclick=act(()=>guardedCaptionFile('translation',`srt?mode=translation&language=${project.style.translation_language||'en'}`, 'translation.srt'));
    $('bilingualSrt').onclick=act(()=>guardedCaptionFile('both',`srt?mode=both&language=${project.style.translation_language||'en'}`, 'bilingual.srt'));
    $('styledAss').onclick=act(()=>guardedCaptionFile(project.style.track_mode||'original','ass', 'captions.ass'));
    $('cancelLyrics').onclick=()=>$('lyricsDialog').close();
    $('applyLyrics').onclick=act(()=>{
        const lines=$('lyrics').value.split(/\r?\n/).map(l=>l.trim()).filter(Boolean);
        if(!lines.length||lines.length>5000)throw Error('Paste between 1 and 5,000 lines.');
        if(project.cues.length&&!confirm('Replace existing captions with these lyrics? You can undo this.'))return;
        edit(()=>{project.cues=lines.map((text,i)=>({text,start:project.duration*i/lines.length,end:project.duration*(i+1)/lines.length,words:[]}));project.timing='estimated';selected=0;});
        $('lyricsDialog').close();$('timingNote').textContent='Evenly spaced lyric estimates — drag each line to match the vocals. These have not been aligned to the audio.';
    });
    $('subtitleFile').onchange=act(async()=>{
        const file=$('subtitleFile').files[0];if(!file||!project)return;
        if(file.size>2000000)throw Error('Use a subtitle file smaller than 2 MB.');
        const data=await api(`/api/captions/${project.id}/import`,'POST',{text:await file.text()});
        if(project.cues.length&&!confirm('Replace existing captions with this file? You can undo this.'))return;
        edit(()=>{project.cues=data.cues;project.timing='imported';selected=0;});$('subtitleFile').value='';
    });
    async function job(kind,options) {
        if(!project)return;await save();
        project=await api(`/api/captions/${project.id}/${kind}`,'POST',{...options,revision:project.revision});
        pendingPreview=kind==='render' && options.preview;
        setBusy(true);say(project.status);poll();
    }
    function needsReview(c){return !c.words?.length || ['review','estimated','edited'].includes(c.karaoke?.state);}
    function drawKaraokeSummary() {
        if(!project)return;
        const total=project.cues.length, missing=project.cues.filter(c=>!c.words?.length).length;
        const review=project.cues.filter(needsReview).length;
        $('karaokeSummary').textContent=`${total-missing}/${total} lines have word timings · ${review} to review · ${missing} missing timings`+(project.style.karaoke?'':' · Enable Highlight the current word to preview karaoke.');
        $('restoreKaraoke').disabled=busy||!project.karaoke_backup;
    }
    async function addKaraoke(index, extra={}) {
        if(!project?.cues.length)throw Error('Import subtitles or add lines first.');
        video.pause();checkpoint();await job('karaoke',{language:$('karaokeLanguage').value,index,...extra});
    }
    $('estimateMissing').onclick=act(()=>{if(!project||!confirm('Use evenly spaced estimates for all lines still missing word timings? These are not matched to the audio.'))return;timingEdit(()=>project.cues.filter(c=>!c.words?.length).forEach(c=>{const words=c.text.trim().split(/\s+/);c.words=words.map((text,i)=>({text,start:i===0?c.start:c.start+(c.end-c.start)*i/words.length,end:i===words.length-1?c.end:c.start+(c.end-c.start)*(i+1)/words.length}));c.karaoke={state:'estimated',note:'Evenly spaced estimates, not audio alignment'};}));});
    $('karaokeAll').onclick=act(()=>addKaraoke());
    $('karaokeReview').onclick=act(()=>addKaraoke(undefined,{only_review:true}));
    $('karaokeResume').onclick=act(()=>addKaraoke(undefined,{resume:true}));
    $('karaokeLine').onclick=act(()=>{if(current())return addKaraoke(selected);});
    $('nextReview').onclick=()=>{if(!project)return;for(let n=1;n<=project.cues.length;n++){const i=(Math.max(-1,selected)+n)%project.cues.length;if(needsReview(project.cues[i])){select(i);return;}}say('No lines are flagged. You can still review any line while listening.');};
    $('markReviewed').onclick=act(()=>{if(!current()?.words?.length)throw Error('Add word timings before marking this line reviewed.');edit(()=>{current().karaoke={...current().karaoke,state:'checked',note:'Reviewed manually'};});});
    $('restoreKaraoke').onclick=act(async()=>{if(!project||!confirm('Restore captions from before the last karaoke operation? Current caption edits will be replaced; your video and style are kept.'))return;await save();checkpoint();project=await api(`/api/captions/${project.id}/restore-karaoke`,'POST',{revision:project.revision});selected=0;refresh();});
    $('transcribe').onclick=act(async()=>{
        if(project?.cues.length&&!confirm('Replace existing captions with automatic transcription? The current version stays saved if transcription fails.'))return;
        checkpoint();await job('transcribe',{language:$('language').value});
    });
    // A 5-second check is not an export: it renders approved translations only and never blocks on review.
    $('renderCheck').onclick=act(()=>{if(sequenceHasChanges())throw Error('Apply your clip sequence changes before rendering.');return job('render',{preview:true,quality:$('renderQuality').value||'standard',force_cpu:$('renderCpu').checked,skip_unapproved:true,start:Math.min(video.currentTime,Math.max(0,project.duration-.1))});});
    $('export').onclick=act(async()=>{
        if(sequenceHasChanges())throw Error('Apply your clip sequence changes before exporting.');
        const guard=await exportGuard(project.style.track_mode||'original');if(!guard.proceed)return;
        return job('render',{preview:false,quality:$('renderQuality').value||'standard',force_cpu:$('renderCpu').checked,skip_unapproved:guard.skip});
    });
    $('srt').onclick=act(async()=>{await save();const a=document.createElement('a');a.href=`/api/captions/${project.id}/srt`;a.click();});
    $('stop').onclick=act(async()=>{
        if(!project)return;
        if(project.state!=='busy'){say('Nothing is running for this project.');return;}
        if(!confirm('Stop the current task for this project? Saved captions are kept; other app jobs keep running.'))return;
        const d=await api(`/api/captions/${project.id}/cancel`,'POST',{});
        say(d.status||'Stopping…');
        if(d.cancelled)poll();
    });
    $('closeRender').onclick=()=>{$('renderVideo').pause();$('renderDialog').close();};
    window.addEventListener('resize',()=>{fitVideo();drawTimeline();});
    if(typeof ResizeObserver !== 'undefined') {
        const centerEl = document.querySelector('.capcutCenter');
        if(centerEl) {
            new ResizeObserver(()=>{fitVideo();drawTimeline();}).observe(centerEl);
        }
    }
    window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
    document.addEventListener('keydown',e=>{
        if(document.querySelector('dialog[open]')) {
            if(e.key === 'Escape') {
                const openModal = document.querySelector('dialog[open]');
                if(openModal) openModal.close();
            }
            return;
        }
        if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
        if(e.code==='Space'){e.preventDefault();$('play').click();}
        if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();undo(e.shiftKey);}
        if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='b'){e.preventDefault();splitClipAtPlayhead();}
        if(e.key==='ArrowLeft'){
            e.preventDefault();
            const step = e.shiftKey ? 1.0 : 0.1;
            video.currentTime = Math.max(0, video.currentTime - step);
            drawTimeline();
        }
        if(e.key==='ArrowRight'){
            e.preventDefault();
            const step = e.shiftKey ? 1.0 : 0.1;
            video.currentTime = Math.min(video.duration || 0, video.currentTime + step);
            drawTimeline();
        }
        if((e.key==='Delete' || e.key==='Backspace') && selected !== null && selected !== undefined && project?.cues?.[selected]){
            e.preventDefault();
            $('delete').click();
        }
        if(e.key.toLowerCase()==='l' && !e.ctrlKey && !e.metaKey){
            e.preventDefault();
            const loopEl = $('loop');
            if(loopEl){loopEl.checked = !loopEl.checked; loopEl.dispatchEvent(new Event('change'));}
        }
    });
    function sendCaptionsHeartbeat() {
        fetch('/api/heartbeat', { method: 'POST', keepalive: true }).catch(()=>{});
    }
    setInterval(sendCaptionsHeartbeat, 4000);
    sendCaptionsHeartbeat();
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') sendCaptionsHeartbeat();
    });
    window.addEventListener('focus', () => sendCaptionsHeartbeat());
    
    // Shortcuts Dialog Wireup
    if($('aiVideoStudioBtn')) $('aiVideoStudioBtn').onclick = (e) => {
        if(project && project.id) {
            e.preventDefault();
            window.location.href = `/video-studio?project=${encodeURIComponent(project.id)}`;
        }
    };
    if($('shortcutsBtn')) $('shortcutsBtn').onclick = () => {
        const d = $('shortcutsDialog');
        if(d) d.showModal();
    };
    if($('closeShortcuts')) $('closeShortcuts').onclick = () => {
        const d = $('shortcutsDialog');
        if(d) d.close();
    };

    // Timeline Zoom Quick Actions
    if($('zoomOutBtn')) $('zoomOutBtn').onclick = () => {
        const z = $('zoom');
        if(!z) return;
        z.value = Math.max(1, Number(z.value) - 2);
        z.dispatchEvent(new Event('input'));
    };
    if($('zoomInBtn')) $('zoomInBtn').onclick = () => {
        const z = $('zoom');
        if(!z) return;
        z.value = Math.min(20, Number(z.value) + 2);
        z.dispatchEvent(new Event('input'));
    };
    if($('zoomFitBtn')) $('zoomFitBtn').onclick = () => {
        const z = $('zoom');
        if(!z) return;
        z.value = 1;
        z.dispatchEvent(new Event('input'));
    };

    async function checkRestart() {
        try {const health=await api('/api/health_check');$('restartNotice').hidden=!health.needs_restart;} catch {}
    }
    $('restartNow').onclick=act(async()=>{
        await save();
        say('Restarting local app engine…');
        await api('/api/restart','POST',{});
        setTimeout(()=>location.reload(),2500);
    });
    checkRestart();setInterval(checkRestart,30000);
    setBusy(false);tick();
    (async()=>{
        await loadCustomFonts();
        await listProjects();
        const urlParams = new URLSearchParams(window.location.search);
        const reqPid = urlParams.get('project');
        if(reqPid) {
            try { await load(reqPid); } catch (_) {}
        }
        await refreshLibraries();
    })().catch(e=>say(e.message,true));

    if(typeof window !== 'undefined'){
        window.currentProjectData = () => project;
        window.copilotHasUnsavedChanges = () => Boolean(dirty);
        window.copilotContext = () => ({page: 'captions', project: project ? {
            id: project.id, name: project.name, duration: project.duration,
            style: {translation_language: project.style?.translation_language || 'en', font: project.style?.font},
            cues: project.cues.map(c => ({id: c.id, start: c.start, end: c.end, text: c.text, translations: c.translations || {}})),
        } : null});
        const setSelect = (id, value) => {
            const option = [...($(id)?.options || [])].find(o => o.value.toLowerCase() === String(value).toLowerCase());
            if (!option) return null;
            $(id).value = option.value;
            $(id).dispatchEvent(new Event('change'));
            return option.value;
        };
        // Proposal handlers for the Copilot drawer: each runs the editor's own action, only after Apply.
        window.copilotActions = {
            transcribe_project: ({language} = {}) => {
                if (!project) throw Error('Open a project first.');
                if (language) setSelect('language', language);
                $('transcribe').click();
                return 'Transcription started — progress is shown in the editor.';
            },
            sync_lyrics: () => {
                if (!project) throw Error('Open a project first.');
                $('paste').click();
                return 'Paste the lyrics in the dialog, then choose how to sync them.';
            },
            translate_project: async ({language}) => {
                if (!project) throw Error('Open a project first.');
                if (!setSelect('translation_language', language)) throw Error(`The language "${language}" is not offered for translation.`);
                await job('translate', {language: project.style.translation_language, ids: null, resume: false});
                return 'Translation job started — results arrive marked for review.';
            },
            batch_fix_subtitles: ({updates}) => window.fixSubtitlesBatch(updates),
            shift_timing: ({seconds}) => window.shiftTimingBySeconds(seconds),
            apply_preset: ({preset}) => window.applyPresetByName(preset),
            set_font: ({font}) => {
                const applied = setSelect('font', font);
                if (!applied) throw Error(`The font "${font}" is not installed. Upload it under Style → Font first.`);
                return `Font set to ${applied}.`;
            },
            render_export: () => {
                if (!project) throw Error('Open a project first.');
                $('export').click();
                return 'Export started.';
            },
        };
        window.applyPresetByName = (name) => {
            if(presets && presets[name]){
                edit(()=>Object.assign(project.style, presets[name]));
                refresh();
                return true;
            }
            return false;
        };
        window.shiftTimingBySeconds = (sec) => {
            if(!project||!project.cues) return false;
            const shift=Number(sec);
            if(isNaN(shift)||shift===0) return false;
            timingEdit(()=>{
                for(const cue of project.cues){
                    cue.start=Math.max(0,Math.min(project.duration,cue.start+shift));
                    cue.end=Math.max(0,Math.min(project.duration,cue.end+shift));
                    if(cue.words){
                        for(const w of cue.words){
                            w.start=Math.max(0,Math.min(project.duration,w.start+shift));
                            w.end=Math.max(0,Math.min(project.duration,w.end+shift));
                        }
                    }
                }
            });
            drawTimeline();drawList();drawCaption();
            return true;
        };
        window.setProjectBackgroundMedia = async (filePath) => {
            if (!project || !project.id || !filePath) return false;
            const form = new FormData();
            form.append('revision', String(project.revision));
            form.append('background_path', filePath);
            form.append('clear_background', 'false');
            form.append('clear_broll', 'false');
            form.append('clear_audio', 'false');
            project = await api(`/api/captions/${project.id}/composition`, 'POST', form);
            dirty = false;
            refresh();
            poll();
            return true;
        };

        window.updateCueText = (lineIndexOrId, newText) => {
            if (!project || !project.cues) return false;
            let cue = null;
            if (typeof lineIndexOrId === 'number') {
                const idx = lineIndexOrId > 0 && lineIndexOrId <= project.cues.length ? lineIndexOrId - 1 : lineIndexOrId;
                cue = project.cues[idx];
            } else if (typeof lineIndexOrId === 'string') {
                cue = project.cues.find(c => c.id === lineIndexOrId);
            }
            if (!cue) return false;
            edit(() => {
                if (CaptionTiming.normalizeWs(cue.text) !== CaptionTiming.normalizeWs(newText)) {
                    cue.words = [];
                    for (const tr of Object.values(cue.translations || {})) tr.status = 'stale';
                }
                cue.text = newText;
            });
            return true;
        };

        window.updateCueTranslation = (lineIndexOrId, lang, newTranslation) => {
            if (!project || !project.cues) return false;
            let cue = null;
            if (typeof lineIndexOrId === 'number') {
                const idx = lineIndexOrId > 0 && lineIndexOrId <= project.cues.length ? lineIndexOrId - 1 : lineIndexOrId;
                cue = project.cues[idx];
            } else if (typeof lineIndexOrId === 'string') {
                cue = project.cues.find(c => c.id === lineIndexOrId);
            }
            if (!cue) return false;
            const targetLang = lang || project.style?.translation_language || 'en';
            // Copilot suggestions go through review: visible in the editor, excluded from exports until kept.
            return writeTranslation(cue, targetLang, newTranslation, {status: 'review', locked: false, origin: 'copilot'})
                .then(record => Boolean(record))
                .catch(e => { say(e.message, true); return false; });
        };

        window.fixSubtitlesBatch = async (updates) => {
            if (!project || !project.cues || !Array.isArray(updates) || busy) return false;
            const targets = [];
            for (const u of updates) {
                const lineNum = typeof u.line === 'number' ? u.line : parseInt(u.line, 10);
                const idx = !isNaN(lineNum) && lineNum > 0 && lineNum <= project.cues.length ? lineNum - 1 : lineNum;
                const cue = project.cues[idx] || (u.id ? project.cues.find(c => c.id === u.id) : null);
                if (cue) targets.push([cue, u]);
            }
            if (!targets.length) return false;
            checkpoint();
            try {
                for (const [cue, u] of targets) {
                    if (u.text !== undefined && u.text !== null && CaptionTiming.normalizeWs(u.text) !== CaptionTiming.normalizeWs(cue.text)) {
                        cue.words = [];
                        for (const tr of Object.values(cue.translations || {})) tr.status = 'stale';
                        cue.text = String(u.text);
                    }
                    if (u.translation !== undefined && u.translation !== null) {
                        const l = u.lang || project.style?.translation_language || 'en';
                        await CaptionTiming.setCueTranslation(cue, l, u.translation, {status: 'review', locked: false, origin: 'copilot'});
                    }
                }
            } finally {
                changed();
            }
            return true;
        };

        window.auditProjectSubtitles = () => {
            if (!project || !project.cues) return { total_cues: 0, issues: [] };
            const lang = project.style?.translation_language || 'en';
            const issues = [];
            project.cues.forEach((c, i) => {
                const lineNum = i + 1;
                const dur = (c.end || 0) - (c.start || 0);
                const tr = c.translations?.[lang]?.text || '';
                const trLen = tr.length;

                if (!tr.trim()) {
                    issues.push({
                        line: lineNum,
                        cue_id: c.id,
                        type: 'missing_translation',
                        severity: 'warning',
                        message: `Line ${lineNum} has no ${lang.toUpperCase()} translation.`,
                        text: c.text
                    });
                } else if (dur > 0 && trLen > 0) {
                    const cps = trLen / dur;
                    if (cps > 24) {
                        issues.push({
                            line: lineNum,
                            cue_id: c.id,
                            type: 'reading_speed',
                            severity: 'warning',
                            cps: Math.round(cps),
                            duration: Number(dur.toFixed(2)),
                            message: `Line ${lineNum} translation is too long for its duration (${Math.round(cps)} chars/sec). Consider shortening.`,
                            text: c.text,
                            translation: tr
                        });
                    }
                }

                if (dur < 0.4) {
                    issues.push({
                        line: lineNum,
                        cue_id: c.id,
                        type: 'duration_too_short',
                        severity: 'info',
                        duration: Number(dur.toFixed(2)),
                        message: `Line ${lineNum} duration is very short (${dur.toFixed(2)}s).`,
                        text: c.text
                    });
                }
            });

            return {
                total_cues: project.cues.length,
                language: lang,
                issues: issues
            };
        };
    }
})();
