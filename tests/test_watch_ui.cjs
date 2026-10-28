const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const BuyingScoreV2 = require('../docs/buying-score-v2.js');
const vm = require('node:vm');
class Node {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.textContent='';this.value='';this.dataset={};this.attrs={};this.listeners={};this.classList={toggle(){}};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,v){this.listeners[k]=v;}
  querySelectorAll(tag){return this.children.flatMap(n=>n.tagName===tag?[n]:n.querySelectorAll?.(tag)||[]);}
  get lastChild(){return this.children.at(-1);}
  scrollIntoView(){}
}
function setup(fetchImpl=async()=>{throw Error('offline')}){
 const nodes=new Map();
 const document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);},createElement:t=>new Node(t),createTextNode:t=>({textContent:t})};
 const location={hash:''};const history={pushState(_state,_title,hash){location.hash=hash;}};
 const window={listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}};
 const source=fs.readFileSync('docs/watch.js','utf8').replace(/load\(\);\s*$/,'');
 const context=vm.createContext({document,location,history,window,BuyingScoreV2,Intl,Date,URL,Map,Set,console,fetch:fetchImpl});
 vm.runInContext(source,context);return {nodes,location,window,run:s=>vm.runInContext(s,context),context};
}
const data=JSON.parse(fs.readFileSync('docs/data/watch.json','utf8'));
test('latest assessment never replaces soft status or counts unavailable as zero',()=>{const x=setup();x.context.data=data;x.run('render(data)');assert.match(x.nodes.get('coverage').textContent,/scored/);assert.equal(x.nodes.get('scores').children.length,32);assert.match(x.nodes.get('soft-detail').textContent,new RegExp(data.last_soft_check.status));assert.equal(x.nodes.get('view-label').textContent,'Latest published assessment');});
test('historical review keeps original timestamps, banner, ranking and return control',()=>{const x=setup();x.context.data=data;x.run('render(data)');const old=JSON.parse(fs.readFileSync('docs/'+data.score_history[0].path,'utf8'));x.context.old=old;x.run('selectReview(old)');assert.match(x.nodes.get('view-context').textContent,/Historical snapshot/);assert.equal(x.nodes.get('return-latest').hidden,false);assert.equal(x.run('rows[0].score'),Math.max(...old.records.filter(r=>r.score!==null).map(r=>r.score)));x.nodes.get('return-latest').listeners.click();assert.equal(x.nodes.get('return-latest').hidden,true);assert.equal(x.run('selectedId'),data.last_hard_check.id);});
test('search empty state and clear restore all 32',()=>{const x=setup();x.context.data=data;x.run('render(data)');x.nodes.get('search').value='no-such-symbol';x.run('cards()');assert.match(x.nodes.get('result-count').textContent,/0 of 32/);x.nodes.get('search').value='';x.run('cards()');assert.equal(x.nodes.get('scores').children.length,32);});
test('unsafe source schemes and history paths rejected',()=>{const x=setup();assert.equal(x.run("safeUrl('javascript:alert(1)')"),null);assert.equal(x.run("safeUrl('https://user:secret@example.com')"),null);x.run("historyEntry({path:'../../private.json'},0)");assert.equal(x.nodes.has('history'),false);});

function text(node){return [node.textContent,...(node.children||[]).map(text)].join(' ');}
function v2record(p=8,f=8){
  const original=data.last_hard_check.records[0];
  const checks=BuyingScoreV2.CHECKS.map((c,i)=>({id:c.id,status:i<p?'pass':i<p+f?'fail':'unknown',evidence:'Synthetic test evidence only.',source_url:null,observed_at:null}));
  const summary=BuyingScoreV2.summarize(checks);
  return {...original,rubric_version:'buying-score-v2',cohort:'v2-regular',score:summary.score,score_status:summary.score===null?'unavailable':'available_provisional',evidence_checks:checks,component_scores:summary.component_scores};
}
test('v2 numeric score has a prominent provisional label and distinct completeness',()=>{
 const x=setup();x.context.record=v2record();x.run('rows=[record];cards()');
 const content=text(x.nodes.get('scores'));
 assert.match(content,/Provisional evidence-based entry score/);assert.match(content,/Evidence coverage: 80%/);
 assert.match(content,/8 pass · 8 fail · 4 unknown/);assert.match(content,/40–60\/100/);
 assert.match(content,/Not a confidence interval or probability of profit/);
});
test('v2 all unknown is unavailable but all failed is a real zero with full coverage',()=>{
 const x=setup();x.context.record=v2record(0,0);x.run('rows=[record];cards()');
 assert.match(text(x.nodes.get('scores')),/All twenty checks are unknown; no numeric score/);
 x.context.record=v2record(0,20);x.run('rows=[record];cards()');
 const content=text(x.nodes.get('scores'));assert.match(content,/Evidence coverage: 100%/);assert.match(content,/0–0\/100/);assert.doesNotMatch(content,/All twenty checks are unknown/);
});
test('legacy numeric provisional scores are explicitly labeled without changing values',()=>{
 const x=setup();const original=JSON.parse(fs.readFileSync('docs/'+data.score_history[0].path,'utf8')).records.find(r=>r.score!==null);
 x.context.record={...original,score_status:'available_provisional'};x.run('rows=[record];cards()');
 assert.match(text(x.nodes.get('scores')),/Provisional v1 buying score/);assert.equal(x.run('scoreValue(record)'),original.score);
});
test('v2 mismatch cannot display supplied score, and malicious evidence remains text',()=>{
 const x=setup();const record=v2record();record.score=95;record.evidence_checks[0].evidence='<script>private()</script>';record.evidence_checks[0].source_url='javascript:alert(1)';
 x.context.record=record;x.run('rows=[record];cards()');
 const content=text(x.nodes.get('scores'));assert.match(content,/numeric display withheld/);assert.match(content,/<script>private\(\)<\/script>/);assert.equal(x.run('scoreValue(record)'),null);
 const links=x.nodes.get('scores').querySelectorAll('a');assert.ok(links.every(a=>!String(a.href).startsWith('javascript:')));
});
test('historical v2 official-close observation never implies current entry',()=>{
 const x=setup();x.context.record={...v2record(),cohort:'v2-historical-official-close'};x.run('rows=[record];cards()');
 assert.match(text(x.nodes.get('scores')),/Historical observation.*Not a current entry score/);
});


test('history selections produce deep links and respond to back and forward',()=>{
 const x=setup();x.context.data=data;x.run('render(data)');
 const old=JSON.parse(fs.readFileSync('docs/'+data.score_history[0].path,'utf8'));x.context.old=old;
 x.run('reviews.set(old.id,old);selectReview(old)');assert.equal(x.location.hash,'#review='+old.id);
 x.location.hash='#research';x.window.listeners.popstate();assert.equal(x.run('selectedId'),data.last_hard_check.id);
 x.location.hash='#review='+old.id;x.window.listeners.popstate();assert.equal(x.run('selectedId'),old.id);
});
test('failed refresh does not strand an in-flight history entry',async()=>{
 let finishHistory;
 const pending=new Promise(resolve=>{finishHistory=resolve;});
 const x=setup(async path=>path==='data/watch.json'?{ok:false,status:500}:pending);
 const item=data.score_history[0],old=JSON.parse(fs.readFileSync('docs/'+item.path,'utf8'));
 x.context.snapshot={...data,score_history:[item]};x.run('render(snapshot)');
 const button=x.nodes.get('history').children[0].children[0];assert.equal(button.disabled,true);
 await x.run('load()');finishHistory({ok:true,json:async()=>old});
 await new Promise(resolve=>setImmediate(resolve));assert.equal(button.disabled,false);
});
test('empty assessment is distinct from an empty search',()=>{
 const x=setup();x.context.snapshot={...data,last_hard_check:null,score_history:[]};x.run('render(snapshot)');
 assert.match(text(x.nodes.get('scores')),/No assessment has been published yet/);
 assert.doesNotMatch(text(x.nodes.get('scores')),/No stocks match/);
});
test('missing or unavailable deep links are clearly labeled',async()=>{
 const x=setup();x.location.hash='#review=missing';x.context.data=data;x.run('render(data)');
 assert.match(x.nodes.get('load-status').textContent,/not found/);
 const item=data.score_history[0];x.location.hash='#review='+item.id;x.window.listeners.hashchange();
 await new Promise(resolve=>setImmediate(resolve));assert.match(x.nodes.get('load-status').textContent,/could not be loaded/);
});
