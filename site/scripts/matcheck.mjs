import puppeteer from "puppeteer";
const b = await puppeteer.launch({headless:true,args:["--use-gl=angle","--use-angle=metal","--enable-unsafe-swiftshader"]});
const p = await b.newPage();
await p.setViewport({width:800,height:450});
await p.goto("http://localhost:5173/", {waitUntil:"domcontentloaded"}).catch(()=>{});
await p.setContent(`<canvas id=c width=800 height=450></canvas><script type="module">
import * as THREE from "/node_modules/three/build/three.module.js";
import { Manhattan, MANHATTAN } from "/src/globe/manhattan.js";
MANHATTAN.lat=40.7264; MANHATTAN.lon=-73.9818;
const r=new THREE.WebGLRenderer({canvas:document.getElementById("c")});
const cam=new THREE.PerspectiveCamera(50,16/9,1,100000);
const m=new Manhattan(r,cam); await m.load();
for(let i=0;i<200;i++){m.place(0.8);m.update();m.render();await new Promise(x=>setTimeout(x,25));}
const kinds={}; let sample=null;
m.tiles.group.traverse(o=>{ if(o.isMesh&&o.material){kinds[o.material.type]=(kinds[o.material.type]||0)+1; sample=sample||{type:o.material.type,fog:o.material.fog,lights:o.material.lights};}});
window.out={kinds,sample,fogOnScene:Boolean(m.scene.fog)};
<\/script>`, {waitUntil:"networkidle0"});
await p.waitForFunction("window.out", {timeout:90000, polling:1000}).catch(()=>{});
console.log(JSON.stringify(await p.evaluate("window.out"),null,2));
await b.close();
