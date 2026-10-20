/* Local caption editor. All imported text is rendered through textContent. */
(() => {
    'use strict';
    const $ = id => document.getElementById(id), video = $('video');
    const token = document.querySelector('meta[name="media-token"]').content;
    const copy = value => JSON.parse(JSON.stringify(value));
    const styleKeys = ['font','size','color','highlight','outline','position','background','karaoke'];
    let project = null, selected = -1, history = [], future = [], dirty = false;
    let saveTimer, pollTimer, saving = null, generation = 0, busy = false, dragging = false, pendingPreview = false;
    const say = (text, error = false) => {
        $('status').textContent = text; $('status').classList.toggle('error', error);
        document.querySelectorAll('dialog[open] .dialogStatus').forEach(node=>{node.textContent=error?text:'';});
    };
    const media = name => `/api/captions/${project.id}/media/${encodeURIComponent(name)}`;
    const snapshot = () => copy({cues:project.cues, style:project.style, timing:project.timing});
    const current = () => project?.cues[selected];
    const fmt = t => `${Math.floor(t/60)}:${(t%60).toFixed(2).padStart(5,'0')}`;
    async function api(url, method = 'GET', body) {
        const options = {method, headers:{'X-Media-Token':token}};
        if (body instanceof FormData) options.body = body;
        else if (body !== undefined) { options.headers['Content-Type']='application/json'; options.body=JSON.stringify(body); }
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({error:'The app could not complete this request. Restart it if the connection was lost.'}));
        if (!response.ok) throw new Error(data.error || 'Request failed');
        return data;
    }
    const act = fn => async event => { try { await fn(event); } catch (e) { say(e.message, true); } };
    function checkpoint() { history.push(snapshot()); if (history.length>80) history.shift(); future=[]; }
    function changed(redraw = true) {
        if (redraw) {
            const cue=current();project.cues.sort((a,b)=>a.start-b.start);selected=project.cues.indexOf(cue);
        }
        dirty=true; generation++; $('saveStatus').textContent='Unsaved changes';
        clearTimeout(saveTimer); saveTimer=setTimeout(() => save().catch(e=>say(e.message,true)),900);
        if (redraw) { drawTimeline(); drawList(); fillSelection(); }
        drawCaption();
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
            if(version===generation) { dirty=false; $('saveStatus').textContent='All changes saved'; }
        }).catch(e=>{ $('saveStatus').textContent='Not saved — check the message'; throw e; }).finally(()=>{saving=null;});
        await saving;
        if(dirty) return save();
    }
    function setBusy(value) {
        busy=value;
        for(const node of document.querySelectorAll('.style input,.style select,.style button,#selection input,#selection textarea,#selection button,.toolbar button,.toolbar select,#export,#renderCheck,#srt,#save,#paste,#subtitleFile,#videoFile,#openLibrary,#projects,#reload,#undo,#redo')) node.disabled=value || !project;
        $('videoFile').disabled=value; $('projects').disabled=value; $('openLibrary').disabled=value;$('newSong').disabled=value;
    }
    async function listProjects() {
        const items=await api('/api/captions');
        $('projects').replaceChildren(new Option('Saved projects…',''),...items.map(p=>new Option(p.name,p.id)));
        if(project) $('projects').value=project.id;
    }
    async function load(pid) {
        await save(); video.pause(); clearTimeout(pollTimer);
        project=await api(`/api/captions/${pid}`); selected=project.cues.length?0:-1;
        history=[];future=[];dirty=false;generation=0;
        if(project.width) mountVideo();
        refresh(); await listProjects();
        if(project.state==='busy') poll();
    }
    function mountVideo() {
        const url=media('preview.mp4');
        if(video.getAttribute('src')!==url) video.src=url;
        $('empty').hidden=true; $('empty').style.display='none';
        fitVideo();
    }
    function fitVideo() {
        if(!project?.width) return;
        const ratio=project.width/project.height;
        const maxWidth=$('stage').parentElement.clientWidth-32;
        const h=Math.min(window.innerWidth<500?250:380,maxWidth/ratio);
        $('stage').style.height=h+'px'; $('stage').style.width=h*ratio+'px';
        drawCaption();
    }
    function refresh() {
        setBusy(project?.state==='busy');
        if(!project) return;
        for(const key of styleKeys) {
            if($(key).type==='checkbox') $(key).checked=project.style[key]; else $(key).value=project.style[key];
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
        drawTimeline();drawList();fillSelection();drawDownloads();drawCaption();
    }
    function poll() {
        clearTimeout(pollTimer);
        pollTimer=setTimeout(async()=>{
            try {
                project=await api(`/api/captions/${project.id}`);
                if(project.state==='busy') {say(project.status);poll();return;}
                if(project.width) mountVideo();
                selected=project.cues.length?0:-1; refresh();
                if(pendingPreview && project.last_render && project.last_render.startsWith('check_') && project.state==='ready') {
                    $('renderVideo').src=media(project.last_render); $('renderDialog').showModal();
                }
                pendingPreview=false;
                await listProjects();
            } catch(e) {say(e.message,true);setBusy(false);}
        },1000);
    }
    function drawCaption() {
        const box=$('caption');box.replaceChildren();
        if(!project) return;
        const cue=project.cues.find(c=>c.start<=video.currentTime && c.end>video.currentTime);
        const s=project.style, h=$('stage').clientHeight;
        Object.assign(box.style,{fontFamily:`"${s.font}",sans-serif`,fontSize:h*s.size/100+'px',color:s.color,
            top:s.position+'%',webkitTextStroke:`${2*h*s.outline/360}px black`});
        if(!cue) return;
        const content=document.createElement('span');
        content.style.background=s.background?'rgba(0,0,0,.65)':'transparent';
        if(s.karaoke && cue.words?.length) {
            cue.words.forEach((w,i)=>{
                if(i) content.append(' ');
                const span=document.createElement('span');span.textContent=w.text;
                if(w.start<=video.currentTime && video.currentTime<w.end) span.style.color=s.highlight;
                content.append(span);
            });
        } else content.textContent=cue.text;
        box.append(content);
    }
    function select(index,seek=true) {
        selected=index;
        drawList();fillSelection();drawTimeline();drawCaption();
        if(seek&&current()&&Number.isFinite(current().start)) video.currentTime=Math.max(0,Math.min(project.duration,current().start+.01));
    }
    function drawList() {
        const list=$('cueList');list.replaceChildren();
        if(!project) return;
        project.cues.forEach((c,i)=>{
            const row=document.createElement('button');row.className='cue'+(i===selected?' active':'');
            const time=document.createElement('time');time.textContent=`${fmt(c.start)} → ${fmt(c.end)}`;
            const text=document.createElement('span');text.textContent=c.text;row.append(time,text);
            row.onclick=()=>select(i);list.append(row);
        });
    }
    function fillSelection() {
        const c=current();
        $('text').value=c?.text||'';$('start').value=c?.start.toFixed(2)||'';$('end').value=c?.end.toFixed(2)||'';
        for(const node of document.querySelectorAll('#selection textarea,#selection input,#selection button')) node.disabled=!c||busy;
        $('words').replaceChildren();
        if(c&&!c.words?.length) {
            const note=document.createElement('p');note.className='hint';
            note.textContent='This line has no word timings, so karaoke cannot highlight it yet. Estimate timings for this line, or use Paste lyrics → Use current caption text → Sync lyrics to audio.';
            $('words').append(note);
        }
        (c?.words||[]).forEach((w,i)=>{
            const row=document.createElement('div');row.className='word';
            const label=document.createElement('span');label.textContent=w.text;row.append(label);
            for(const k of ['start','end']) {
                const input=document.createElement('input');input.type='number';input.step='.01';input.value=w[k].toFixed(2);
                input.setAttribute('aria-label',`${w.text} ${k}`);input.disabled=busy;
                input.onchange=()=>timingEdit(()=>{c.words[i][k]=Number(input.value);});
                row.append(input);
            }
            $('words').append(row);
        });
    }
    function drawTimeline() {
        if(!project?.duration || dragging) return;
        const timeline=$('timeline');const width=Math.max(400,$('timelineScroll').clientWidth)*Number($('zoom').value);
        timeline.style.width=width+'px';
        const canvas=$('waveform');canvas.width=width;canvas.height=80;
        const ctx=canvas.getContext('2d');ctx.fillStyle='#72cfc5';
        const peaks=project.peaks||[], max=Math.max(.01,...peaks);
        peaks.forEach((p,i)=>{const h=p/max*70;ctx.fillRect(i/peaks.length*width,40-h/2,Math.max(1,width/peaks.length),h);});
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
                        const shift=Math.max(before-original.start,Math.min(after-original.end,delta));
                        c.start=original.start+shift;c.end=original.end+shift;
                        c.words=original.words.map(w=>({...w,start:w.start+shift,end:w.end+shift}));
                    } else {
                        c[side]=side==='start'?Math.max(before,Math.min(original.end-.05,original.start+delta)):Math.min(after,Math.max(original.start+.05,original.end+delta));
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
        await save();video.pause();setBusy(true);say('Copying video and preparing your project…');
        try {project=await api('/api/captions','POST',form);dirty=false;history=[];future=[];selected=-1;refresh();poll();}
        catch(e){setBusy(false);throw e;}
    }
    $('videoFile').onchange=act(async()=>{const file=$('videoFile').files[0];if(file){const f=new FormData();f.append('video',file);await create(f);}$('videoFile').value='';});
    $('newSong').onclick=()=>$('songDialog').showModal();
    $('cancelSong').onclick=()=>$('songDialog').close();
    $('createSong').onclick=act(async()=>{
        const song=$('songFile').files[0];if(!song)throw Error('Choose your song first.');
        const form=new FormData();form.append('audio',song);form.append('shape',$('songShape').value);form.append('color',$('songColor').value);form.append('visualizer',$('songVisualizer').checked);
        const bg=$('songBackground').files[0];if(bg)form.append('background',bg);else if($('songLibrary').value)form.append('background_path',$('songLibrary').value);
        $('createSong').disabled=true;
        try {await create(form);$('songDialog').close();} finally {$('createSong').disabled=false;}
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
    for(const key of styleKeys) $(key).oninput=()=>edit(()=>{project.style[key]=$(key).type==='checkbox'?$(key).checked:$(key).type==='range'?Number($(key).value):$(key).value;},false);
    const presets={clean:{font:'Arial',size:5,outline:2,background:false,karaoke:false,color:'#ffffff'},bold:{font:'Impact',size:6,outline:3,background:false,karaoke:false,color:'#ffffff'},lyrics:{font:'Georgia',size:4.5,outline:1,background:false,karaoke:false,color:'#ffffff'},karaoke:{font:'Verdana',size:5,outline:2,karaoke:true,highlight:'#ffdc55'}};
    document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>{edit(()=>Object.assign(project.style,presets[b.dataset.preset]));refresh();});
    $('saveStyle').onclick=act(()=>{if(project){localStorage.setItem('captionStyle',JSON.stringify(project.style));say('Style saved in this browser.');}});
    $('loadStyle').onclick=act(()=>{const s=JSON.parse(localStorage.getItem('captionStyle')||'null');if(!s)throw Error('Save a style first.');edit(()=>{project.style=s;});refresh();});
    $('text').oninput=()=>{
        if(current()) {
            edit(()=>{current().text=$('text').value;current().words=[];},false);
            drawTimeline();drawList();$('words').replaceChildren();
        }
    };
    $('text').onchange=()=>{drawTimeline();drawList();fillSelection();};
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
        const words=c.text.trim().split(/\s+/);if(words.length<2)throw Error('At least two words are needed to split a line.');
        const index=Math.max(1,Math.min(words.length-1,Math.round(words.length*(t-c.start)/(c.end-c.start))));
        edit(()=>project.cues.splice(selected,1,{start:c.start,end:t,text:words.slice(0,index).join(' '),words:[]},{start:t,end:c.end,text:words.slice(index).join(' '),words:[]}));
    });
    $('merge').onclick=()=>{const c=current(),next=project?.cues[selected+1];if(c&&next)edit(()=>project.cues.splice(selected,2,{start:c.start,end:next.end,text:c.text+' '+next.text,words:[]}));};
    $('estimateWords').onclick=()=>{const c=current();if(c)timingEdit(()=>{const words=c.text.trim().split(/\s+/);c.words=words.map((text,i)=>({text,start:c.start+(c.end-c.start)*i/words.length,end:c.start+(c.end-c.start)*(i+1)/words.length}));say('Word timings are evenly spaced estimates for this line only. Play this line to see highlighting; adjust the timings while listening.');});};
    $('shiftAll').onclick=act(()=>{
        if(!project)return;const shift=Number($('shift').value);
        if(!Number.isFinite(shift)||project.cues.some(c=>c.start+shift<0||c.end+shift>project.duration))throw Error('That shift would move captions outside the video.');
        edit(()=>project.cues.forEach(c=>{c.start+=shift;c.end+=shift;c.words.forEach(w=>{w.start+=shift;w.end+=shift;});}));
    });
    function undo(redo=false) {
        if(!project||busy)return;const source=redo?future:history,dest=redo?history:future;if(!source.length)return;
        dest.push(snapshot());Object.assign(project,source.pop());selected=Math.min(selected,project.cues.length-1);changed();refresh();
    }
    $('undo').onclick=()=>undo();$('redo').onclick=()=>undo(true);
    $('paste').onclick=()=>{if(project){$('alignStart').value=0;$('alignEnd').value=project.duration.toFixed(3);$('alignLanguage').value=$('language').value||'en';$('lyricsDialog').showModal();}};
    $('useCurrentLyrics').onclick=()=>{$('lyrics').value=project.cues.map(c=>c.text).join('\n');};
    $('alignLyrics').onclick=act(async()=>{
        if(!$('lyrics').value.trim())throw Error('Paste the lyrics sung in this video first.');
        if(project.cues.length&&!confirm('Replace the current captions with aligned lyrics? You can undo this after alignment.'))return;
        const options={text:$('lyrics').value,language:$('alignLanguage').value,start:Number($('alignStart').value),end:Number($('alignEnd').value)};
        $('alignLyrics').disabled=true;
        try {checkpoint();await job('align',options);$('lyricsDialog').close();} finally {$('alignLyrics').disabled=false;}
    });
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
        project=await api(`/api/captions/${project.id}/${kind}`,'POST',options);
        pendingPreview=kind==='render' && options.preview;
        setBusy(true);say(project.status);poll();
    }
    $('transcribe').onclick=act(async()=>{
        if(project?.cues.length&&!confirm('Replace existing captions with automatic transcription? The current version stays saved if transcription fails.'))return;
        checkpoint();await job('transcribe',{language:$('language').value});
    });
    $('renderCheck').onclick=act(()=>job('render',{preview:true,start:Math.min(video.currentTime,Math.max(0,project.duration-.1))}));
    $('export').onclick=act(()=>job('render',{preview:false}));
    $('srt').onclick=act(async()=>{await save();const a=document.createElement('a');a.href=`/api/captions/${project.id}/srt`;a.click();});
    $('stop').onclick=act(async()=>{if(confirm('Stop active app jobs, including downloads and caption processing?')){const d=await api('/api/cancel_all','POST',{});say(d.status||'Stopping…');}});
    $('closeRender').onclick=()=>{$('renderVideo').pause();$('renderDialog').close();};
    window.addEventListener('resize',()=>{fitVideo();drawTimeline();});
    window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
    document.addEventListener('keydown',e=>{
        if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||document.querySelector('dialog[open]'))return;
        if(e.code==='Space'){e.preventDefault();$('play').click();}
        if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();undo(e.shiftKey);}
    });
    setInterval(()=>fetch('/api/heartbeat').catch(()=>{}),2000);
    setBusy(false);tick();
    (async()=>{
        await listProjects();
        const entries=await api('/api/gallery');
        $('library').replaceChildren(new Option('Choose from library…',''),...entries.filter(e=>e.type==='video'&&e.folder!=='Caption Projects').map(e=>new Option(e.name,e.full_path)));
        $('songLibrary').replaceChildren(new Option('Use colour / uploaded background',''),...entries.filter(e=>['image','video'].includes(e.type)&&e.folder!=='Caption Projects').map(e=>new Option(e.name,e.full_path)));
    })().catch(e=>say(e.message,true));
})();
