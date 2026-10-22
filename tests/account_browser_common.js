const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const check=(condition,message)=>{if(!condition)throw new Error(message);};
async function waitFor(predicate,message){for(let i=0;i<350;i++){if(predicate())return;await pause(30);}throw new Error(message);}
function runAccountCheck(run){
  const frame=document.createElement('iframe');frame.style.cssText='width:1000px;height:1100px';
  frame.onload=async()=>{
    frame.onload=null;const w=frame.contentWindow,d=w.document,checks=[],requests=[];let holdStatus=false,lostReply=null;
    const nativeFetch=w.fetch.bind(w);
    w.fetch=async(path,options={})=>{
      const entry={path:String(path),body:options.body?JSON.parse(options.body):null};requests.push(entry);
      const response=await nativeFetch(path,options);entry.status=response.status;entry.json=await response.clone().json().catch(()=>null);
      if(lostReply&&entry.path===lostReply.path&&(!lostReply.action||entry.body?.action===lostReply.action)){lostReply=null;entry.lost=true;throw new TypeError('Simulated lost server response');}
      if(holdStatus&&entry.body?.action==='status'){holdStatus=false;entry.held=true;await pause(650);}return response;
    };
    const start=()=>d.querySelector('[data-game-start]');
    const action=name=>d.querySelector('[data-action="'+name+'"]');
    const latest=path=>requests.filter(entry=>entry.path===path).at(-1);
    const api=w.apiRequest;
    const ctx={w,d,checks,requests,start,action,latest,
      async setup(name,game=name,options={}){
        await api('/__account_test_scenario',{method:'POST',body:JSON.stringify({name,balance:options.balance??20000})});
        w.applyServerState((await api('/api/state')).state);w.openGame(game);
        await waitFor(()=>game==='highlow'?!d.querySelector('[data-highlow-action="start"]').disabled:start()&&!start().disabled,'Game not ready: '+name);
        const input=d.querySelector('.betbar input');input.value=options.bet||'500';d.querySelector('.apply-bet').click();
      },
      async begin(){
        const count=requests.filter(entry=>entry.path==='/api/games/start').length;start().click();
        await waitFor(()=>requests.filter(entry=>entry.path==='/api/games/start').length>count&&latest('/api/games/start')?.json?.user,'Start response missing');
        await waitFor(()=>!start().disabled||action('stand')||action('draw')||action('cashout')||d.querySelector('.tile:not(:disabled)')||d.querySelector('.cup-choice.peek'),'Start did not render');
        return latest('/api/games/start').json;
      },
      async move(name){
        const count=requests.filter(entry=>entry.path==='/api/games/action').length;check(action(name)&&!action(name).disabled,'Action unavailable: '+name);action(name).click();
        await waitFor(()=>requests.filter(entry=>entry.path==='/api/games/action').length>count&&latest('/api/games/action')?.json?.user,'Action response missing: '+name);
        await waitFor(()=>!start().disabled||!action(name)?.disabled,'Action never unlocked: '+name);return latest('/api/games/action').json;
      },
      async reopen(game){w.showView('lobby');w.openGame(game);await waitFor(()=>requests.filter(entry=>entry.path==='/api/games/active').at(-1)?.json?.round_id&&((game==='mines'&&d.querySelector('.tile:not(:disabled)'))||action('stand')||action('draw')||action('cashout')),'Round did not restore: '+game);},
      async finished(){
        await waitFor(()=>start()&&!start().disabled,'Round did not finish');
        const active=await api('/api/games/active');check(active.round_id===null,'Server round remains active');
        check(BigInt(w.eval('S.balance'))===BigInt(active.state.balance),'Displayed balance diverged from server');
        check(!d.querySelector('[data-action]'),'Actions remain after settlement');return active;
      },
      heldStatus(){holdStatus=true;},
      loseReply(path,action=null){lostReply={path,action};},
      hands(){return Object.fromEntries(['dealer','player'].map(name=>[name,[...d.querySelectorAll('[data-hand="'+name+'"] .card')].map(card=>card.dataset.cardKey)]));},
      assertHands(round){
        const actual=this.hands();for(const name of ['dealer','player'])check(JSON.stringify(actual[name])===JSON.stringify(round[name].map(card=>card?card.r+card.s:'back')),'Cards differ from server: '+name);
        check([...d.querySelectorAll('[data-hand]')].map(hand=>hand.dataset.hand).join(',')==='dealer,player','Hands swapped position');
      }
    };
    try{
      await waitFor(()=>w.eval('authReady'),'Account initialization timed out');w.eval('maybeOpenStory=()=>{};S.sound=false;');await pause(400);d.querySelector('#dialogOverlay').classList.remove('on');
      const account=await api('/api/auth/register',{method:'POST',body:JSON.stringify({email:'games-browser@example.com',username:'games_browser',password:'test-password-123'})});await w.activateAccount(account.user);
      await run(ctx);d.querySelector('#dialogOverlay').classList.remove('on');document.querySelector('#report').textContent=JSON.stringify({ok:true,checks});
    }catch(error){document.querySelector('#report').textContent=JSON.stringify({ok:false,error:error.stack,checks});}
  };
  frame.src='/';document.body.appendChild(frame);
}
