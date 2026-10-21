const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
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
function setup(){const nodes=new Map();const document={getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);},createElement:t=>new Node(t),createTextNode:t=>({textContent:t})};const source=fs.readFileSync('docs/watch.js','utf8').replace(/load\(\);\s*$/,'');const context=vm.createContext({document,Intl,Date,URL,Map,console,fetch:async()=>{throw Error('offline')}});vm.runInContext(source,context);return {nodes,run:s=>vm.runInContext(s,context),context};}
const data=JSON.parse(fs.readFileSync('docs/data/watch.json','utf8'));
test('latest assessment never replaces soft status or counts unavailable as zero',()=>{const x=setup();x.context.data=data;x.run('render(data)');assert.match(x.nodes.get('coverage').textContent,/scored/);assert.equal(x.nodes.get('scores').children.length,32);assert.match(x.nodes.get('soft-detail').textContent,new RegExp(data.last_soft_check.status));assert.equal(x.nodes.get('view-label').textContent,'Latest published assessment');});
test('historical review keeps original timestamps, banner, ranking and return control',()=>{const x=setup();x.context.data=data;x.run('render(data)');const old=JSON.parse(fs.readFileSync('docs/'+data.score_history[0].path,'utf8'));x.context.old=old;x.run('selectReview(old)');assert.match(x.nodes.get('view-context').textContent,/Historical snapshot/);assert.equal(x.nodes.get('return-latest').hidden,false);assert.equal(x.run('rows[0].score'),Math.max(...old.records.filter(r=>r.score!==null).map(r=>r.score)));x.nodes.get('return-latest').listeners.click();assert.equal(x.nodes.get('return-latest').hidden,true);assert.equal(x.run('selectedId'),data.last_hard_check.id);});
test('search empty state and clear restore all 32',()=>{const x=setup();x.context.data=data;x.run('render(data)');x.nodes.get('search').value='no-such-symbol';x.run('cards()');assert.match(x.nodes.get('result-count').textContent,/0 of 32/);x.nodes.get('search').value='';x.run('cards()');assert.equal(x.nodes.get('scores').children.length,32);});
test('unsafe source schemes and history paths rejected',()=>{const x=setup();assert.equal(x.run("safeUrl('javascript:alert(1)')"),null);assert.equal(x.run("safeUrl('https://user:secret@example.com')"),null);x.run("historyEntry({path:'../../private.json'},0)");assert.equal(x.nodes.has('history'),false);});
