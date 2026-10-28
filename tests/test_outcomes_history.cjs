'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'docs/outcomes.js'), 'utf8');
const legacy = JSON.parse(fs.readFileSync(path.join(root, 'docs/data/outcomes/2026-10-21-intraday-audit-v1.json'), 'utf8'));
const first = {...legacy, id:'2026-10-21-first'}, second = {...legacy, id:'2026-10-21-second'};
const catalog = {audits:[first, second].map(d => ({id:d.id, market_date:d.market_date, path:`data/outcomes/${d.id}.json`}))};
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.dataset={}; this.textContent=''; this.value=''; this.listeners={}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children=items; }
  addEventListener(type, fn) { this.listeners[type]=fn; }
}
function setup(initialUrl, index=catalog, failingPath=null) {
  const nodes = {audit:new Element('main'), status:new Element('p'), 'audit-date':new Element('select')};
  const document = {createElement:tag=>new Element(tag), createTextNode:text=>({textContent:text,children:[]}), getElementById:id=>nodes[id]};
  const listeners = {}, location = {href:initialUrl}, pushed=[];
  const window = {location, addEventListener:(type,fn)=>{listeners[type]=fn;}, history:{pushState:(_state,_title,url)=>{location.href=String(url); pushed.push(location.href);}}};
  const fetch = async url => {
    if (url === 'data/outcomes/index.json') return {ok:index !== null,json:async()=>index};
    if (url === failingPath) return {ok:false};
    const item = [first,second].find(d=>url === `data/outcomes/${d.id}.json`);
    return {ok:!!item,json:async()=>item};
  };
  vm.runInNewContext(source, {document,window,fetch,URL,Intl,console});
  return {nodes,listeners,location,pushed};
}
async function settle() { for (let i=0; i<12; i++) await Promise.resolve(); }
(async()=>{
  const app=setup('https://example.test/outcomes.html?audit=2026-10-21-first'); await settle();
  assert.equal(app.nodes.audit.dataset.auditId, first.id);
  assert.equal(app.nodes['audit-date'].value, first.id);
  app.nodes['audit-date'].value=second.id; app.nodes['audit-date'].listeners.change(); await settle();
  assert.equal(app.nodes.audit.dataset.auditId, second.id);
  assert.equal(new URL(app.pushed[0]).searchParams.get('audit'),second.id);
  app.location.href='https://example.test/outcomes.html?audit=2026-10-21-first'; app.listeners.popstate(); await settle();
  assert.equal(app.nodes.audit.dataset.auditId, first.id);
  assert.equal(app.nodes['audit-date'].value, first.id);
  app.location.href='https://example.test/outcomes.html?audit=missing'; app.listeners.popstate(); await settle();
  assert.equal(app.nodes.audit.dataset.auditId, undefined);
  assert.match(app.nodes.status.textContent,/not in the published catalog/);
  const empty=setup('https://example.test/outcomes.html',{audits:[]}); await settle();
  assert.equal(empty.nodes['audit-date'].disabled,true); assert.match(empty.nodes.status.textContent,/No outcome audits/);
  const bad=setup('https://example.test/outcomes.html',null); await settle();
  assert.equal(bad.nodes['audit-date'].disabled,true); assert.match(bad.nodes.status.textContent,/catalog unavailable/i);
  const missing=setup('https://example.test/outcomes.html',catalog,`data/outcomes/${second.id}.json`); await settle();
  assert.equal(missing.nodes.audit.dataset.auditId,undefined); assert.match(missing.nodes.status.textContent,/could not be loaded/);
  console.log('Outcome URL history and error handling passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
