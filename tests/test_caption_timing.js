'use strict';
const assert=require('node:assert/strict');
const {validate, visualizerBars}=require('../static/captions.js');
const line=(start,end,words=[])=>({start,end,words});
assert.throws(()=>validate([line(185.54,3)],185.54),/start before/);
assert.throws(()=>validate([line(0,3,[line(185.54,94.27),line(94.27,3)])],185.54),/Word timings/);
assert.throws(()=>validate([line(0,3),line(2,4)],10),/overlap/);
assert.throws(()=>validate([line(0,3,[line(0,2),line(1,3)])],10),/Word timings/);
assert.throws(()=>validate([line(NaN,3)],10),/start before/);
assert.doesNotThrow(()=>validate([line(12.74,15.74,[line(12.74,14.24),line(14.24,15.74)])],185.54));
assert.doesNotThrow(()=>validate([line(0,3)],185.54));
assert.equal(visualizerBars([0.2,0.8,0.5],10,5,640,360,{visualizer_style:'spectrum',visualizer_position:'bottom'}).length,36);
assert.equal(visualizerBars([0.2,0.8,0.5],10,5,640,360,{visualizer_style:'waveform',visualizer_position:'center'}).length,48);
console.log('Caption timing regression checks passed.');
// Run the real editor script with no separately loaded timing helper.
const vm=require('node:vm'), fs=require('node:fs');
class Element {
    get options(){return this.children;}
    add(option){this.children.push(option);}
    set value(value){this._value=value;if(value==='')this.files=[];}
    get value(){return this._value;}
    constructor(){this.children=[];this.style={};this.value='';this.checked=false;this.type='text';this.clientWidth=600;this.clientHeight=380;this.currentTime=0;this.paused=true;this.parentElement={clientWidth:700};this.attrs={};this.classList={toggle(){},contains(){return false;}};}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;}
    setAttribute(k,v){this.attrs[k]=v;}
    getAttribute(k){return this.attrs[k];}
    getContext(){return {fillRect(){}};}
    pause(){this.paused=true;}
    addEventListener(){ }
    removeEventListener(){ }
}
const nodes=new Map();
const element=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
let animation;
const requests=[];
const project={id:'test',revision:0,duration:185.5,width:1080,height:1920,state:'ready',status:'Ready',timing:'imported',peaks:[],exports:[],style:{font:'Verdana',size:5,color:'#ffffff',highlight:'#ffdc55',outline:2,position:65,background:false,karaoke:true},cues:[{start:30.52,end:32.53,text:'Feeling getting so much warmer',words:[]}]};
const ctx={document:{documentElement:{dataset:{}},getElementById:element,querySelector:()=>({content:'test'}),querySelectorAll:()=>[],createElement:()=>new Element(),addEventListener(){}},window:{innerWidth:1200,addEventListener(){}},Event:class{constructor(t){this.type=t;}},requestAnimationFrame:fn=>{animation=fn;},setTimeout:()=>1,clearTimeout(){},setInterval(){},FormData:class{},Option:class{},fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>url==='/api/captions'&&options?.method!=='POST'?[]:url==='/api/gallery'?[]:url==='/api/captions/translation-models'?{models:[],auto:{available:false}}:options?.method==='PUT'?{revision:1}:structuredClone(project)};},console};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(require.resolve('../static/captions.js'),'utf8'),ctx);
(async()=>{
    await new Promise(resolve=>setImmediate(resolve));
    element('projects').value='test';await element('projects').onchange();
    element('estimateWords').onclick();
    assert.equal(element('words').children.length,5);
    assert(!element('status').textContent.includes('not defined'));
    element('video').currentTime=30.6;animation();
    const spans=element('caption').children[0].children.filter(x=>typeof x==='object');
    assert.equal(spans[0].textContent,'Feeling');assert.equal(spans[0].style.color,'#ffdc55');
    element('video').currentTime=31.1;animation();
    const next=element('caption').children[0].children.filter(x=>typeof x==='object');
    assert.equal(next[1].textContent,'getting');assert.equal(next[1].style.color,'#ffdc55');
    assert.equal(next[0].style.color,undefined);
    element('cumulative').checked=true;element('word_pop').checked=true;element('cumulative').onchange();element('word_pop').onchange();
    animation();
    const cum=element('caption').children[0].children.filter(x=>typeof x==='object');
    assert.equal(cum[0].style.color,'#ffdc55');
    assert.equal(cum[1].style.color,'#ffdc55');
    assert.equal(cum[1].style.transform,'scale(1.15)');
    assert.equal(cum[0].style.transform,undefined);
    element('word_box').checked=true;element('word_box').onchange();
    animation();
    const wb=element('caption').children[0].children.filter(x=>typeof x==='object');
    assert.equal(wb[1].style.backgroundColor,'#ffdc55');
    assert.equal(wb[1].style.color,'#090a0f');
    element('word_box').checked=false;element('word_box').onchange();
    const firstEnd=element('words').children[0].children[2];
    const shortened=Number(firstEnd.value)-.05;
    firstEnd.value=String(shortened);firstEnd.onchange();
    const firstBlock=element('wordLane').children[0];
    await firstBlock.onkeydown({key:'ArrowRight',preventDefault(){},stopPropagation(){}});
    assert.equal(element('words').children[0].children[1].value,'30.54');
    element('undo').onclick();
    assert.equal(element('words').children[0].children[1].value,'30.52');
    assert.equal(element('words').children[0].children[2].value,shortened.toFixed(2));
    element('video').currentTime=185.5;element('setStart').onclick();
    assert.match(element('status').textContent,/start before/);
    assert.equal(element('start').value,'30.52');
    element('karaokeLanguage').value='auto';
    await element('karaokeAll').onclick();
    const request=requests.find(x=>x.url.endsWith('/karaoke'));
    assert(request);const sent=JSON.parse(request.options.body);assert.equal(sent.language,'auto');assert.equal(sent.revision,1);assert.equal(sent.index,undefined);
    console.log('Actual Estimate button and moving karaoke highlight passed without an external helper.');
    const drafts=new Map();
    ctx.indexedDB={open(){const req={};setImmediate(()=>{
        req.result={close(){},transaction(){const tx={objectStore(){return {
            put(value,key){drafts.set(key,structuredClone(value));setImmediate(()=>tx.oncomplete());},
            get(key){const read={};setImmediate(()=>{read.result=structuredClone(drafts.get(key));read.onsuccess();});return read;}
        };}};return tx;}};req.onsuccess();
    });return req;}};
    ctx.DataTransfer=class{constructor(){this.files=[];this.items={add:f=>this.files.push(f)};}};
    element('compAudio').files=[{name:'pending.wav',size:100}];
    element('compClearBroll').checked=true;
    project.id='other';element('projects').value='other';await element('projects').onchange();
    assert.equal(drafts.get('test').files.compAudio[0].name,'pending.wav');
    assert.equal(element('compAudio').files.length,0,'Switching projects must clear previous upload selections');
    assert.equal(element('compClearBroll').checked,false);
    project.id='test';element('projects').value='test';await element('projects').onchange();
    assert.equal(element('compAudio').files[0].name,'pending.wav','Returning to a project restores its own upload draft');
    assert.equal(element('compClearBroll').checked,true);
    assert.equal(drafts.get('other').files.compAudio.length,0,'Other project must not inherit upload files');
    element('compAudio').files=[{name:'oversized.wav',size:513*1024*1024}];
    element('projects').value='other';await element('projects').onchange();
    assert.match(element('status').textContent,/512 MB/);
    assert.equal(element('compAudio').files[0].name,'oversized.wav','Failed draft persistence must not discard pending files');
    element('compAudio').files=[{name:'pending.wav',size:100}];
    ctx.FormData.prototype.append=function(){};
    project.id='new-project';element('library').value='test-source.mp4';await element('openLibrary').onclick();
    assert.equal(element('compAudio').files.length,0,'Creating a project must clear previous upload selections');
    assert.equal(drafts.get('test').files.compAudio[0].name,'pending.wav');
    console.log('Upload draft project isolation and recovery passed.');
    project.translation_settings={model:'qwen3-4b-local',notes:'Song context',glossary:'Keep names'};
    element('projects').value=project.id;await element('projects').onchange();
    assert.equal(element('translationModel').value,'qwen3-4b','The legacy built-in translator id maps to its AI catalog id');
    project.translation_settings={};await element('projects').onchange();
    assert.equal(element('translationModel').value,'','Projects without a model must not inherit the previous selection');
    assert.equal(element('translationNotes').value,'');
    const localDrafts=new Map();
    ctx.localStorage={getItem:key=>localDrafts.get(key)||null,setItem:(key,value)=>localDrafts.set(key,value),removeItem:key=>localDrafts.delete(key)};
    project.source='before-render.mp4';
    project.studio={settings:{shape:'portrait',start:0,end:185.5,sequence:[]},assets:{audio:{file:'song.wav'}}};
    await element('projects').onchange();
    element('compAudio').files=[{name:'replacement.wav',size:100}];
    element('comp_color').value='#123456';
    project.state='busy';await element('applyComposition').onclick();
    assert([...localDrafts.keys()].some(key=>key.startsWith('creator-composition-')&&!key.startsWith('creator-composition-submission-')),'Render submission must retain settings');
    project.state='error';project.status='Simulated render failure';await element('projects').onchange();
    assert.equal(element('compAudio').files[0].name,'replacement.wav','Failed render keeps uploads for retry');
    assert([...localDrafts.keys()].some(key=>key.startsWith('creator-composition-')&&!key.startsWith('creator-composition-submission-')),'Failed render keeps settings for retry');
    project.state='busy';await element('applyComposition').onclick();
    project.state='ready';project.source='after-render.mp4';await element('projects').onchange();
    assert.equal(element('compAudio').files.length,0,'Successful render consumes pending uploads');
    assert(![...localDrafts.keys()].some(key=>key.startsWith('creator-composition-')&&!key.startsWith('creator-composition-submission-')),'Successful render retires settings draft');
    assert.equal(drafts.get(project.id).files.compAudio.length,0,'Successful render releases stored upload blobs');
    element('compAudio').files=[{name:'not-applied.wav',size:100}];
    element('comp_color').value='#aabbcc';element('comp_color').onchange();
    project.state='busy';await element('applySequenceNow').onclick();
    project.state='ready';project.source='sequence-only.mp4';await element('projects').onchange();
    assert.equal(element('compAudio').files[0].name,'not-applied.wav','Sequence-only render keeps unapplied audio upload');
    assert.equal(element('comp_color').value,'#aabbcc','Sequence-only render keeps unapplied canvas settings');
    element('clearStickerBtn').onclick();
    assert.match(element('activeStickerNotice').textContent,/Sticker removed/);
    element('lyrics').value='Project A draft lyrics';element('lyrics').oninput();
    project.id='clean-project';element('projects').value='clean-project';await element('projects').onchange();
    assert.equal(element('activeStickerNotice').textContent,'','Switching projects must clear sticker notice');
    assert.equal(element('lyrics').value,'','Switching to project without lyrics draft must clear lyrics box');
    project.id='new-project';element('projects').value='new-project';await element('projects').onchange();
    assert.match(element('activeStickerNotice').textContent,/Sticker removed/,'Returning to project restores pending sticker state');
    assert.equal(requests.some(x=>x.url==='/api/captions/translation-models'),false,'Translation models must load lazily, not eagerly on open');
    element('openTranslatorBtn').onclick();
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(requests.some(x=>x.url==='/api/captions/translation-models'),true,'Opening AI Translator loads models on demand');
    console.log('Composition success/failure draft lifecycle and lazy translation check passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});

const {splitSequence, chunkCues, transformCuesText, closeGapsAndFixOverlaps, entranceScale}=require('../static/captions.js');
const split=splitSequence([{asset:'background',duration:2,speed:2,source_start:1}],6,3,true);
assert.equal(split.length,4);assert.equal(split[1].duration,1);assert.equal(split[2].source_start,3);
assert.equal(split.reduce((n,c)=>n+c.duration,0),6);
assert.throws(()=>splitSequence([{asset:'background',duration:1}],100,50.5,true),/30 clips/);

const originalCue={id:'original1',start:0,end:4,text:'Hello bright world',words:[{text:'Hello',start:0,end:1},{text:'bright',start:1.2,end:2},{text:'world',start:2.3,end:4}],translations:{en:{text:'Hello bright world',source:'old',status:'approved',locked:true}}};
const phraseParts=require('../static/captions.js').splitCaption(originalCue,2.1,'newpart1');
assert.equal(phraseParts[0].id,'original1');assert.equal(phraseParts[1].id,'newpart1');
assert.equal(phraseParts[0].end,2.3);assert.equal(phraseParts[0].words.length,2);
assert.equal(phraseParts[1].translations.en.status,'stale');assert.equal(originalCue.translations.en.status,'approved');
const mergedPhrase=require('../static/captions.js').mergeCaptions(...phraseParts);
assert.equal(mergedPhrase.words.length,3);assert.equal(mergedPhrase.translations.en.status,'stale');

// Step 5: Futuristic style, visualizer, bounce curve, and viral caption helper checks.
assert.equal(visualizerBars([0.2,0.8,0.5],10,5,640,360,{visualizer_style:'mirror',visualizer_position:'center'}).length,80);
assert.equal(visualizerBars([0.2,0.8,0.5],10,5,640,360,{visualizer_style:'pulse',visualizer_position:'bottom'}).length,32);
assert.ok(Math.abs(entranceScale('bounce',0)-0.65)<1e-6);
assert.ok(Math.abs(entranceScale('bounce',0.28*0.6)-1.12)<1e-6);
assert.ok(Math.abs(entranceScale('bounce',0.28)-1.0)<1e-6);

const longCue={id:'chunk_src_1',start:0,end:5,text:'One, two three four five.',words:[{text:'One,',start:0,end:0.8},{text:'two',start:0.9,end:1.8},{text:'three',start:1.9,end:2.8},{text:'four',start:2.9,end:3.8},{text:'five.',start:3.9,end:4.9}],translations:{en:{text:'One',source:'x',status:'approved',locked:false}}};
const chunked=chunkCues([longCue],3,(c,idx)=>`${c.id}_part_${idx}`);
assert.equal(chunked.length,2);
assert.equal(chunked[0].text,'One, two three');
assert.equal(chunked[1].text,'four five.');
assert.equal(chunked[0].id,'chunk_src_1');
assert.equal(chunked[1].id,'chunk_src_1_part_1');
assert.equal(chunked[0].words.length,3);
assert.equal(chunked[1].translations.en.status,'stale');
assert.doesNotThrow(()=>validate(chunked,10));

const stripped=transformCuesText([longCue],'strip_punct');
assert.equal(stripped[0].text,'One two three four five');
assert.equal(stripped[0].words[0].text,'One');
assert.equal(stripped[0].words[4].text,'five');
assert.equal(transformCuesText([{start:0,end:1,text:'hello world',words:[]} ],'upper')[0].text,'HELLO WORLD');
assert.equal(transformCuesText([{start:0,end:1,text:'HELLO WORLD',words:[]} ],'title')[0].text,'Hello World');
assert.equal(transformCuesText([{start:0,end:1,text:'HELLO',words:[]} ],'lower')[0].text,'hello');

const smoothed=closeGapsAndFixOverlaps([{id:'c1',start:0,end:1.0,text:'A',words:[]},{id:'c2',start:1.2,end:2.5,text:'B',words:[]},{id:'c3',start:2.3,end:3.6,text:'C',words:[]}],5,0.35);
assert.equal(smoothed[0].end,1.2,'Micro-gap <= 0.35s is closed');
assert.ok(smoothed[1].end<=smoothed[2].start,'Overlap between cues is resolved');
assert.doesNotThrow(()=>validate(smoothed,5));
console.log('Viral caption helpers and visualizer regression checks passed.');

const {computeLiveMusicState}=require('../static/captions.js');
const musicCfg={mainVol:1.0,musicVol:0.8,start:1.0,offset:2.0,duration:10.0,fadeIn:2.0,fadeOut:2.0,loop:true,ducking:true};
const beforeOffset=computeLiveMusicState(1.2,12,musicCfg,[]);
assert.equal(beforeOffset.active,false);
assert.equal(beforeOffset.musicVolume,0);
assert.equal(beforeOffset.videoVolume,1);

const midFadeIn=computeLiveMusicState(3.0,12,musicCfg,[]);
assert.equal(midFadeIn.active,true);
assert.equal(midFadeIn.targetTime,2.0);
assert.ok(Math.abs(midFadeIn.musicVolume-0.4)<1e-6,'Fade-in envelope scales musicVolume at rel=1s');

const loopWrap=computeLiveMusicState(16.0,5,{mainVol:1,musicVol:0.5,start:1,offset:0,loop:true},[]);
assert.equal(loopWrap.active,true);
assert.equal(loopWrap.targetTime,1.0,'Loop wraps cleanly inside avail segment [start..mp3Dur]');

const duckedState=computeLiveMusicState(6.0,20,musicCfg,[{start:5.5,end:6.5,text:'Speak'}]);
assert.equal(duckedState.ducked,true);
assert.ok(Math.abs(duckedState.musicVolume-0.8*0.35)<1e-6,'Cue-based ducking drops musicVolume to 35%');

const normState=computeLiveMusicState(5.0,20,{mainVol:2.0,musicVol:0.8,start:0,offset:0},[]);
assert.equal(normState.videoVolume,1.0);
assert.ok(Math.abs(normState.musicVolume-0.4)<1e-6,'Norm divisor keeps boosted mix bounded in [0,1]');

const ActionCards=require('../static/action_cards.js');
const uncaptioned=ActionCards.computeStudioCards({project:{id:'p1',revision:0,duration:8,cues:[]},zeroAi:true});
assert.ok(uncaptioned.some((c)=>c.id==='uncaptioned-clip' && !c.secondaryAction),'zeroAi suppresses secondary auto-transcribe trigger');
assert.ok(uncaptioned.some((c)=>c.id==='add-bg-music'),'Multi-audio card surfaces when no music track is staged');

const activeStudio=ActionCards.computeStudioCards({
    project:{
        id:'p2',
        revision:3,
        duration:12,
        cues:[
            {id:'a',start:0,end:0.4,text:'Way too many fast words inside this subtitle cue',translations:{es:{status:'review'}}},
            {id:'b',start:0.6,end:2.0,text:'Next phrase'}
        ],
        studio:{assets:{music:'music.mp3'}}
    },
    zeroAi:false
});
const activeIds=activeStudio.map((c)=>c.id);
assert.ok(activeIds.includes('fast-cps'));
assert.ok(activeIds.includes('micro-gaps'));
assert.ok(activeIds.includes('pending-translations'));
assert.ok(!activeIds.includes('add-bg-music'),'Already-mixed studio hides add-bg-music');

const grabberCards=ActionCards.computeGrabberCards({recentVideos:[{full_path:'D:/DL/TikTok/clip.mp4',name:'clip.mp4',folder:'TikTok'}],zeroAi:true});
assert.deepEqual(grabberCards.map((c)=>c.id),['caption-latest','reframe-vertical','trace-lineage']);

const memStore=new Map();
global.sessionStorage={
    getItem:(k)=>memStore.has(k)?memStore.get(k):null,
    setItem:(k,v)=>memStore.set(k,String(v))
};
ActionCards.skipCard('studio',uncaptioned[0]);
const afterSkip=ActionCards.filterSkipped('studio',uncaptioned);
assert.ok(!afterSkip.some((c)=>c.id===uncaptioned[0].id),'Skipped card is hidden by sessionStorage filter');
console.log('Live MP3 preview and Proactive Action Cards checks passed.');
