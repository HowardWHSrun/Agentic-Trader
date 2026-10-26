const test = require('node:test');
const assert = require('node:assert/strict');
const {CHECKS,WEIGHTS,summarize} = require('../docs/buying-score-v2.js');
const checks=(p=8,f=8)=>CHECKS.map((c,i)=>({id:c.id,status:i<p?'pass':i<p+f?'fail':'unknown',evidence:'Synthetic test evidence.',source_url:null,observed_at:null}));
test('v2 fixed denominator and independent evidence coverage',()=>{
 const s=summarize(checks());assert.equal(s.score,40);assert.equal(s.coverage,80);assert.equal(s.unresolved,20);assert.deepEqual(s.completion_range,[40,60]);
});
test('v2 all unknown differs from all fail',()=>{
 assert.equal(summarize(checks(0,0)).score,null);assert.equal(summarize(checks(0,0)).coverage,0);
 assert.equal(summarize(checks(0,20)).score,0);assert.equal(summarize(checks(0,20)).coverage,100);
 assert.deepEqual(summarize(checks(20,0)).component_scores,WEIGHTS);
});
test('v2 every state-count combination keeps denominator and component total',()=>{
 for(let p=0;p<=20;p++)for(let f=0;f<=20-p;f++){const s=summarize(checks(p,f));assert.equal(Object.values(s.component_scores).reduce((a,b)=>a+b,0),5*p);assert.equal(s.coverage+s.unresolved,100);}
});
test('v2 rejects incomplete, duplicate and unknown check states',()=>{
 const duplicate=checks();duplicate[0].id=duplicate[1].id;
 const invalid=checks();invalid[0].status=true;
 const empty=checks();empty[0].evidence='';
 for(const candidate of [checks().slice(1),[...checks(),checks()[0]],duplicate,invalid,empty])assert.throws(()=>summarize(candidate));
});
