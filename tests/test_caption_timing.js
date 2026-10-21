'use strict';
const assert=require('node:assert/strict');
const {validate}=require('../static/captions.js');
const line=(start,end,words=[])=>({start,end,words});
assert.throws(()=>validate([line(185.54,3)],185.54),/start before/);
assert.throws(()=>validate([line(0,3,[line(185.54,94.27),line(94.27,3)])],185.54),/Word timings/);
assert.throws(()=>validate([line(0,3),line(2,4)],10),/overlap/);
assert.throws(()=>validate([line(0,3,[line(0,2),line(1,3)])],10),/Word timings/);
assert.throws(()=>validate([line(NaN,3)],10),/start before/);
assert.doesNotThrow(()=>validate([line(12.74,15.74,[line(12.74,14.24),line(14.24,15.74)])],185.54));
assert.doesNotThrow(()=>validate([line(0,3)],185.54));
console.log('Caption timing regression checks passed.');
// Run the real editor script with no separately loaded timing helper.
const vm=require('node:vm'), fs=require('node:fs');
class Element {
    constructor(){this.children=[];this.style={};this.value='';this.checked=false;this.type='text';this.clientWidth=600;this.clientHeight=380;this.currentTime=0;this.paused=true;this.parentElement={clientWidth:700};this.attrs={};this.classList={toggle(){},contains(){return false;}};}
    append(...items){this.children.push(...items);}
    replaceChildren(...items){this.children=items;}
    setAttribute(k,v){this.attrs[k]=v;}
    getAttribute(k){return this.attrs[k];}
    getContext(){return {fillRect(){}};}
    pause(){this.paused=true;}
}
const nodes=new Map();
const element=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
let animation;
const requests=[];
const project={id:'test',revision:0,duration:185.5,width:1080,height:1920,state:'ready',status:'Ready',timing:'imported',peaks:[],exports:[],style:{font:'Verdana',size:5,color:'#ffffff',highlight:'#ffdc55',outline:2,position:65,background:false,karaoke:true},cues:[{start:30.52,end:32.53,text:'Feeling getting so much warmer',words:[]}]};
const ctx={document:{getElementById:element,querySelector:()=>({content:'test'}),querySelectorAll:()=>[],createElement:()=>new Element(),addEventListener(){}},window:{innerWidth:1200,addEventListener(){}},requestAnimationFrame:fn=>{animation=fn;},setTimeout:()=>1,clearTimeout(){},setInterval(){},FormData:class{},Option:class{},fetch:async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>url==='/api/captions'?[]:url==='/api/gallery'?[]:options?.method==='PUT'?{revision:1}:structuredClone(project)};},console};
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
    element('video').currentTime=185.5;element('setStart').onclick();
    assert.match(element('status').textContent,/start before/);
    assert.equal(element('start').value,'30.52');
    element('karaokeLanguage').value='auto';
    await element('karaokeAll').onclick();
    const request=requests.find(x=>x.url.endsWith('/karaoke'));
    assert(request);const sent=JSON.parse(request.options.body);assert.equal(sent.language,'auto');assert.equal(sent.revision,1);assert.equal(sent.index,undefined);
    console.log('Actual Estimate button and moving karaoke highlight passed without an external helper.');
})().catch(e=>{console.error(e);process.exitCode=1;});
