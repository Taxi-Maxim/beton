const fs=require('fs');
const vm=require('vm');
const assert=require('assert/strict');
const html=fs.readFileSync(require('path').join(__dirname,'../games_5_7.html'),'utf8');
const script=[...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
new vm.Script(script);
const helpers=script.slice(script.indexOf('const money='),script.indexOf('const rnd='));
const state=script.slice(script.indexOf('function freshState()'),script.indexOf('function load()'));
const context=vm.createContext({assert});
vm.runInContext(helpers+state+`
const huge=10n**100n;
assert.equal(moneyProduct(huge,2.7),huge*27n/10n);
assert.equal(moneyProduct(50n,2.5),125n);
assert.equal(normalizeState({balance:huge.toString()}).balance,huge.toString());
assert.equal(JSON.parse(stringifyMoney({balance:huge,bets:{cups:huge}})).bets.cups,huge.toString());
assert.equal(fmt(huge).replace(/\\s/g,''),huge.toString());
assert.equal(moneyAbs(-huge),huge);
`,context);
console.log('Frontend syntax and exact money checks passed');

const timing=script.slice(script.indexOf('function cupShuffleTiming('),script.indexOf('function createCupTable('));
vm.runInContext(timing+`
const speeds=Array.from({length:16},(_,step)=>cupShuffleTiming(step,16));
assert.equal(speeds[0].duration,220);
assert.equal(speeds[1].duration,220);
assert.equal(speeds[0].pause,50);
assert.equal(speeds[15].duration,70);
assert.equal(speeds[15].pause,8);
for(let i=1;i<speeds.length;i++){
  assert.ok(speeds[i].duration<=speeds[i-1].duration);
  assert.ok(speeds[i].pause<=speeds[i-1].pause);
}
`,context);
console.log('Cup shuffle starts at the original speed and progressively accelerates');
