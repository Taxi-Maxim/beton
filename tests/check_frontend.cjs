const fs=require('fs');
const vm=require('vm');
const assert=require('assert/strict');
const html=fs.readFileSync(require('path').join(__dirname,'../games_5_7.html'),'utf8');
const script=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
new vm.Script(script);
const helpers=script.slice(script.indexOf('const money='),script.indexOf('const rnd='));
const state=script.slice(script.indexOf('function freshState()'),script.indexOf('function load()'));
const context=vm.createContext({assert});
vm.runInContext("const LS='wallet-test';"+helpers+state+`
const huge=10n**100n;
assert.equal(moneyProduct(huge,2.7),huge*27n/10n);
assert.equal(moneyProduct(50n,2.5),125n);
assert.equal(normalizeState({balance:huge.toString()}).balance,huge.toString());
assert.equal(normalizeState({balance:'1e+100'}).balance,huge.toString());
assert.equal(normalizeState({balance:'1.2345e+30'}).balance,(12345n*10n**26n).toString());
assert.equal(JSON.parse(stringifyMoney({balance:huge,bets:{cups:huge}})).bets.cups,huge.toString());
assert.equal(fmt(huge).replace(/\\s/g,''),huge.toString());
assert.equal(moneyAbs(-huge),huge);
`,context);
console.log('Frontend syntax and exact money checks passed');

const timing=script.slice(script.indexOf('function cupShuffleTiming('),script.indexOf('function createCupTable('));
vm.runInContext(timing+`
const speeds=Array.from({length:28},(_,step)=>cupShuffleTiming(step,28));
assert.equal(speeds[0].duration,220);
assert.equal(speeds[1].duration,220);
assert.equal(speeds[0].pause,50);
assert.equal(speeds[27].duration,45);
assert.equal(speeds[27].pause,0);
assert.equal(speeds[18].duration,45);
assert.equal(JSON.stringify(cupOrderAfterMove([0,1,2],[0,1,2])),JSON.stringify([2,0,1]));
assert.equal(JSON.stringify(cupOrderAfterMove([0,1,2],[0,2,1])),JSON.stringify([1,2,0]));
assert.equal(JSON.stringify(cupOrderAfterMove([0,1,2],[0,2])),JSON.stringify([2,1,0]));
for(let i=1;i<speeds.length;i++){
  assert.ok(speeds[i].duration<=speeds[i-1].duration);
  assert.ok(speeds[i].pause<=speeds[i-1].pause);
}
`,context);
console.log('Cup shuffle starts at the original speed and progressively accelerates');

const persistence=script.slice(script.indexOf('function load()'),script.indexOf('let firstStoryLaunch='));
vm.runInContext(persistence+`
const memory=new Map();
const localStorage={getItem:key=>memory.get(key)??null,setItem:(key,value)=>memory.set(key,value)};
let S=normalizeState({balance:'1e+100',owned:['watch']});
persistState();
S.balance=(money(S.balance)+50n).toString();persistState();
assert.equal(load().balance,(10n**100n+50n).toString());
localStorage.setItem(LS,'null');
assert.equal(load().balance,(10n**100n).toString());
assert.equal(load().owned[0],'watch');
assert.throws(()=>normalizeState({balance:'Infinity'}));
`,context);
console.log('Scientific amounts and backup recovery preserve balances instead of resetting progress');

const highlow=script.slice(script.indexOf('const HIGHLOW_RTP='),script.indexOf('function buildHighlow('));
vm.runInContext('const hasSkill=()=>false;'+highlow+`
for(const current of [2,7,14])for(const direction of ['high','low']){
  assert.ok(highLowCorrect(current,current,direction));
  const count=direction==='high'?15-current:current-1;
  assert.ok(Math.abs(highLowStep(current,direction).growth-.96*13/count)<1e-10);
}
assert.equal(highLowCorrect(7,6,'high'),false);
assert.equal(highLowCorrect(7,8,'low'),false);
`,context);
console.log('High/low ties succeed for both directions, including two and ace');
