import puppeteer from "puppeteer";
const OUT = "/private/tmp/claude-501/-Users-leo-Projects/1a890156-e8d2-41dc-b9d6-faf2d035be6c/scratchpad";
const url = process.argv[2] ?? "http://localhost:5173/";
const b = await puppeteer.launch({ args: ["--use-gl=angle", "--enable-webgl", "--mute-audio", "--autoplay-policy=no-user-gesture-required", "--hide-scrollbars"] });
const p = await b.newPage();
const bad = [];
p.on("pageerror", e => bad.push("JS: " + e.message.slice(0, 120)));
p.on("response", r => { if (r.status() >= 400) bad.push(r.status() + " " + r.url().slice(0, 90)); });
await p.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1 });
await p.goto(url, { waitUntil: "networkidle0", timeout: 60000 });
await new Promise(r => setTimeout(r, 3000));
console.log("ENTER present:", await p.evaluate(() => !!document.querySelector(".opening-go")));
await p.evaluate(() => document.querySelector(".opening-go")?.click());
await new Promise(r => setTimeout(r, 2500));
console.log("video:", await p.evaluate(() => {
  const v = document.querySelector(".opening-video");
  return v ? { src: v.getAttribute("src"), dur: v.duration, w: v.videoWidth, playing: !v.paused } : "none";
}));
for (const [n, at] of [["live-0", 0.5], ["live-1", 4], ["live-2", 8], ["live-3", 10.8]]) {
  await p.evaluate((t) => { const v = document.querySelector(".opening-video"); if (v) v.currentTime = t; }, at);
  await new Promise(r => setTimeout(r, 900));
  await p.screenshot({ path: `${OUT}/${n}.png` });
}
console.log("failures:", bad.length ? bad : "none");
await b.close();
