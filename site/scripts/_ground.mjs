import puppeteer from "puppeteer";
const H = `
<!doctype html><html><body style="margin:0;background:#000">
<canvas id="c" width="640" height="360"></canvas>
<script type="module">
  import * as THREE from "/node_modules/three/build/three.module.js";
  import { Manhattan, MANHATTAN } from "/src/globe/manhattan.js";
  MANHATTAN.lat = 40.72588; MANHATTAN.lon = -73.98290;
  window.state = { stage: "starting" };
  (async () => {
    try {
      const renderer = new THREE.WebGLRenderer({ canvas: document.getElementById("c") });
      const camera = new THREE.PerspectiveCamera(38, 16/9, 8, 80000);
      const m = new Manhattan(renderer, camera);
      await m.load();
      camera.position.set(0, 700, 700); camera.lookAt(0,0,0); camera.updateMatrixWorld();
      for (let k = 0; k < 500; k++) {
        m.update(); m.render();
        const s = m.tiles.stats ?? {};
        if (k > 10 && !s.downloading && !s.parsing) break;
        await new Promise(r => setTimeout(r, 25));
      }
      const ray = new THREE.Raycaster(new THREE.Vector3(0, 6000, 0), new THREE.Vector3(0, -1, 0));
      ray.far = 30000;
      const hits = ray.intersectObject(m.tiles.group, true);
      const box = new THREE.Box3().setFromObject(m.tiles.group);
      window.state = {
        stage: "done",
        topHitY: hits.length ? +hits[0].point.y.toFixed(1) : null,
        hits: hits.length,
        allHitY: hits.slice(0, 6).map(h => +h.point.y.toFixed(1)),
        boxMinY: +box.min.y.toFixed(1), boxMaxY: +box.max.y.toFixed(1),
        spanX: +(box.max.x - box.min.x).toFixed(0),
        scale: m.tiles.group.scale.toArray().map(v => +v.toFixed(4)),
      };
    } catch (e) { window.state = { stage: "failed", why: String(e).slice(0,300) }; }
  })();
<\/script></body></html>`;
const b = await puppeteer.launch({ headless: true, args: ["--use-gl=angle","--use-angle=metal","--enable-gpu","--enable-unsafe-swiftshader"] });
const p = await b.newPage();
await p.setViewport({ width: 640, height: 360 });
await p.goto("http://localhost:5173/", { waitUntil: "domcontentloaded" }).catch(()=>{});
await p.setContent(H, { waitUntil: "networkidle0" });
await p.waitForFunction("window.state !== undefined && window.state.stage !== 'starting'", { timeout: 150000 });
console.log(JSON.stringify(await p.evaluate("window.state"), null, 2));
await b.close();
