import assert from 'node:assert/strict';
import fs from 'node:fs';
import { screenQuad, projectiveMatrix } from '../src/opening/screen-portal.js';
const track={start:3,fps:24,frames:JSON.parse(fs.readFileSync('media/continuous/round-3-motion/camera.json')).map(f=>f.screen)};
const transform=(m,x,y)=>[(m[0]*x+m[4]*y+m[12])/(m[3]*x+m[7]*y+1),(m[1]*x+m[5]*y+m[13])/(m[3]*x+m[7]*y+1)];
for(const [w,h] of [[1280,720],[1512,771],[390,844],[844,390]]) {
 for(let frame=0;frame<144;frame++){
  const quad=screenQuad(track,3+frame/24,w,h,1280,720).map(([x,y])=>[Math.min(w,Math.max(0,x)),Math.min(h,Math.max(0,y))]);
  const m=projectiveMatrix(quad,w,h);
  assert(m?.every(Number.isFinite));
  const source=[[0,h],[w,h],[w,0],[0,0]];
  source.forEach(([x,y],i)=>transform(m,x,y).forEach((p,axis)=>assert(Math.abs(p-quad[i][axis])<1e-6)));
  if(frame===143)source.forEach((p,i)=>p.forEach((v,axis)=>assert(Math.abs(v-quad[i][axis])<.001)));
 }
}
assert.equal(projectiveMatrix([[0,0],[0,0],[0,0],[0,0]],1280,720),null);
console.log('Portal projection: 576 viewport/frame cases, endpoint identity, and degenerate input pass.');
