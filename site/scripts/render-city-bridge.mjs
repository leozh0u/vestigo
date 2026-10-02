// Offline image renderer. Uses one root tileset session; never exports map meshes.
// Requires a same-day verification that the existing account cannot charge cash.
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import { build } from 'esbuild';
import puppeteer from 'puppeteer';

const opts = Object.fromEntries(process.argv.slice(2).map(v => v.split('=')));
if (opts['--verified-no-cash-trial'] !== new Date().toISOString().slice(0,10)) {
  throw new Error('Verify the project billing account is still an unupgraded no-charge trial today.');
}
const env = await fs.readFile(opts['--env-file'], 'utf8');
const key = /^VITE_GOOGLE_MAPS_KEY=(.*)$/m.exec(env)?.[1]?.trim();
if (!key) throw new Error('Missing Maps key');
const dir = path.resolve(opts['--out'] || 'media/continuous/approach-2');
const poses = JSON.parse(await fs.readFile(path.join(dir,'camera.json')));
const descent = opts['--segment'] === 'descent';
const selected = descent ? Array.from({length:198},(_,i)=>i+1) : opts['--frames'] === 'all' ? poses.map(p=>p.frame)
  : (opts['--frames'] || '1,13,25,37,49,61,73,85,97').split(',').map(Number);
const width = Number(opts['--width'] || 640), height = Math.round(width*9/16);
const bundled = await build({entryPoints:['scripts/scene-entry.js'], bundle:true,
  format:'iife', globalName:'SCENE', write:false,
  define:{'import.meta.env.VITE_GOOGLE_MAPS_KEY':JSON.stringify(key)}});
const publicRoot=path.resolve('public');
const server = http.createServer(async(req,res)=>{
  const pathname=new URL(req.url,'http://localhost').pathname;
  if(pathname==='/'){res.end('<html><body></body></html>');return;}
  const file=path.resolve(publicRoot,'.'+pathname);
  if(!file.startsWith(publicRoot+path.sep)){res.writeHead(403);res.end();return;}
  try{res.end(await fs.readFile(file));}catch{res.writeHead(404);res.end();}
});
await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(5173,'127.0.0.1',resolve);});
const browser = await puppeteer.launch({headless:true,args:['--use-gl=angle','--use-angle=metal','--enable-gpu','--hide-scrollbars']});
const jobs=selected.map(frame=>({frame,segment:descent?'descent':'city'}));
if(opts['--segment']==='complete') jobs.unshift(...Array.from({length:198},(_,i)=>({frame:i+1,segment:'descent'})));
let roots=0, failures=0;
const attributions=[];
try {
  const page=await browser.newPage();
  await page.setViewport({width,height,deviceScaleFactor:1});
  await page.setRequestInterception(true);
  page.on('request',req=>{
    const u=new URL(req.url());
    if(u.hostname==='tile.googleapis.com' && u.pathname.endsWith('/root.json')) {
      roots++;
      if(roots>1) { failures++; req.abort(); return; }
    }
    req.continue();
  });
  page.on('response',res=>{ if(res.status()>=400 && res.url().includes('tile.googleapis.com')) failures++; });
  await page.goto('http://localhost:5173');
  await page.setContent(`<body style="margin:0"><canvas id="c"></canvas><script>${bundled.outputFiles[0].text}</script><script>
  window.ready=(async()=>{
    const {THREE,Manhattan,MANHATTAN}=SCENE;
    MANHATTAN.lat=40.72466;MANHATTAN.lon=-73.98096;
    const renderer=new THREE.WebGLRenderer({canvas:document.getElementById('c'),antialias:true,preserveDrawingBuffer:true});
    renderer.setPixelRatio(1);renderer.setSize(${width},${height});
    const camera=new THREE.PerspectiveCamera(42,16/9,.05,40000000);
    const m=new Manhattan(renderer,camera);
    await m.load({fade:false,errorTarget:1});
    window.m=m;
    window.settle=async()=>{
      let quiet=0;
      for(let k=0;k<1000;k++){
        m.update();m.render();
        const s=m.tiles.stats||{};
        quiet=(!s.downloading&&!s.parsing)?quiet+1:0;
        if(k>25&&quiet>=15)return;
        await new Promise(r=>setTimeout(r,25));
      }
      throw new Error('City tiles did not settle');
    };
    m.place(1,45);m.blackout=0;await window.settle();
    const floor=m.groundLevel();
    if(!Number.isFinite(floor))throw new Error('No measured ground level');
    window.floor=floor;
    const n=new THREE.Vector3(-.5953,0,.8035).normalize();
    const right=new THREE.Vector3(n.z,0,-n.x);
    const forward=n.clone().negate();
    const origin=new THREE.Vector3(-23.67,floor+16,6.07).addScaledVector(n,1.3);
    const basis=v=>right.clone().multiplyScalar(v[0]).addScaledVector(forward,v[1]).add(new THREE.Vector3(0,v[2],0));
    window.aerial=frame=>{m.place((frame-1)/24/9.4);m.blackout=0;};
    window.place=p=>{
      camera.position.copy(origin).add(basis(p.position));
      camera.up.copy(basis(p.up));
      camera.lookAt(camera.position.clone().add(basis(p.forward)));
      camera.near=.05;camera.updateProjectionMatrix();camera.updateMatrixWorld();
      m.blackout=0;
      if(m.facade)m.facade.visible=false;
    };
  })();</script>`);
  await page.evaluate(()=>window.ready);
  await page.evaluate(poses=>{
    const m=window.m, W=m.renderer.domElement.width, H=m.renderer.domElement.height;
    const output=document.createElement('canvas');output.width=W;output.height=H;
    output.style.cssText='position:absolute;left:0;top:0';document.body.append(output);
    const ctx=output.getContext('2d'), result=ctx.createImageData(W,H);
    const gl=m.renderer.getContext(), buf=new Uint8Array(W*H*4), sum=new Float32Array(W*H*4);
    window.shoot=(frame,segment)=>{
      sum.fill(0);
      for(let k=0;k<3;k++){
        const f=frame+((k+.5)/3-.5)*.5;
        if(segment==='descent')window.aerial(f);
        else{
          const i=Math.max(0,Math.min(poses.length-1,f-1)),a=poses[Math.floor(i)],b=poses[Math.ceil(i)],t=i%1;
          const p={};for(const name of ['position','forward','up'])p[name]=a[name].map((v,j)=>v+(b[name][j]-v)*t);
          window.place(p);
        }
        m.render();gl.readPixels(0,0,W,H,gl.RGBA,gl.UNSIGNED_BYTE,buf);
        for(let i=0;i<sum.length;i++)sum[i]+=buf[i]/3;
      }
      for(let y=0;y<H;y++)for(let x=0;x<W*4;x++)result.data[y*W*4+x]=sum[(H-1-y)*W*4+x];
      ctx.putImageData(result,0,0);
    };
  },poses);
  console.log('Measured street datum:',await page.evaluate(()=>window.floor));
  for(const {frame,segment} of jobs) {
    if(failures)throw new Error(`Map requests failed (${failures}); stop without publishing`);
    if(segment==='descent') await page.evaluate(frame=>window.aerial(frame),frame);
    else await page.evaluate(p=>window.place(p),poses[frame-1]);
    await page.evaluate(()=>window.settle());
    if(failures)throw new Error('Tile request failed during settling');
    attributions.push({frame,segment,values:await page.evaluate(()=>window.m.tiles.getAttributions().filter(a=>a.type==='string').map(a=>a.value))});
    await page.evaluate(({frame,segment})=>window.shoot(frame,segment),{frame,segment});
    await page.screenshot({path:path.join(dir,`${segment}-${String(frame).padStart(4,'0')}.png`)});
    console.log('Rendered',segment,'frame',frame);
  }
  await fs.writeFile(path.join(dir,opts['--segment']==='complete'?'full-render.json':descent?'descent-render.json':'city-render.json'),JSON.stringify({date:new Date().toISOString(),roots,failures,width,height,frames:selected,attributions,ground:await page.evaluate(()=>window.floor)},null,2));
} finally { await browser.close();await new Promise(r=>server.close(r)); }
