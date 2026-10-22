const fs=require('fs');
const path=require('path');
const {spawn}=require('child_process');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
  const [chromePath,profile,url]=process.argv.slice(2);
  const chrome=spawn(chromePath,['--headless','--disable-gpu','--no-first-run','--no-default-browser-check',
    '--disable-background-networking','--disable-background-timer-throttling','--disable-renderer-backgrounding',
    '--no-proxy-server','--window-size=1200,1200','--remote-debugging-port=0','--user-data-dir='+profile,
    '--host-resolver-rules=MAP fonts.googleapis.com ~NOTFOUND, MAP fonts.gstatic.com ~NOTFOUND','about:blank'],{windowsHide:true,stdio:'ignore'});
  let socket;
  try{
    const portFile=path.join(profile,'DevToolsActivePort');
    for(let attempt=0;attempt<100&&!fs.existsSync(portFile);attempt++)await delay(100);
    const port=fs.readFileSync(portFile,'utf8').split('\n')[0];
    const tab=await(await fetch('http://127.0.0.1:'+port+'/json/new?'+encodeURIComponent(url),{method:'PUT'})).json();
    socket=new WebSocket(tab.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
    let id=0;const pending=new Map();
    socket.onmessage=event=>{const message=JSON.parse(event.data);if(pending.has(message.id)){pending.get(message.id)(message);pending.delete(message.id);}};
    const send=(method,params={})=>new Promise(resolve=>{pending.set(++id,resolve);socket.send(JSON.stringify({id,method,params}));});
    let report='RUNNING';
    for(let attempt=0;attempt<220;attempt++){
      const reply=await send('Runtime.evaluate',{expression:"document.querySelector('#report')?.textContent",returnByValue:true});
      report=reply.result?.result?.value;
      if(report&&report!=='RUNNING')break;
      await delay(200);
    }
    const screenshot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
    if(screenshot.result?.data){const artifact=path.join(__dirname,'../instance/cups-browser.png');fs.mkdirSync(path.dirname(artifact),{recursive:true});fs.writeFileSync(artifact,Buffer.from(screenshot.result.data,'base64'));}
    console.log(report||'RUNNING');
    await Promise.race([send('Browser.close'),delay(2000)]);
  }finally{
    socket?.close();
    if(chrome.exitCode===null)await Promise.race([new Promise(resolve=>chrome.once('exit',resolve)),delay(3000)]);
    if(chrome.exitCode===null)chrome.kill();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
