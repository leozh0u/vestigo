// Build a review candidate first. --publish additionally requires a passing review.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';

const dir=path.resolve(process.argv.find(a=>a.startsWith('--dir='))?.slice(6) || 'media/continuous/approach-final');
const room=path.resolve('media/continuous/round-3-motion');
const run=(command,args)=>{
  const p=spawnSync(command,args,{encoding:'utf8',maxBuffer:8*1024*1024});
  if(p.status!==0)throw new Error(`${command} failed: ${p.stderr?.slice(-2000)}`);
  return p.stdout;
};
for(const [prefix,count] of [['descent',198],['city',97],['frame',97]]) {
  for(let i=1;i<=count;i++)await fs.access(path.join(dir,`${prefix}-${String(i).padStart(4,'0')}.png`));
}
const render=JSON.parse(await fs.readFile(path.join(dir,'full-render.json')));
if(render.failures || render.width!==1280 || render.height!==720)throw new Error('Incomplete or mismatched city render');
const poses=JSON.parse(await fs.readFile(path.join(dir,'camera.json')));
const roomPoses=JSON.parse(await fs.readFile(path.join(room,'camera.json')));
if(Math.max(...poses.at(-1).position.map((p,i)=>Math.abs(p-roomPoses[0].camera[i])))>1e-5)throw new Error('Window camera positions do not match');
if(Math.max(...poses.at(-1).rotation.map((p,i)=>Math.abs(p-roomPoses[0].rotation[i])))>1e-5)throw new Error('Window camera rotations do not match');
const providers=[...new Set(render.attributions.flatMap(a=>a.values.flatMap(v=>v.split(';'))).map(s=>s.trim()).filter(Boolean))].sort();
if(!providers.length)throw new Error('Missing map attribution');
const credit=providers.join('; ');
await fs.writeFile(path.join(dir,'attribution.txt'),`City background: ${credit}\nFor promotional purposes only`);
run(process.env.PYTHON || 'python3',['-c',`
from PIL import Image, ImageDraw, ImageFont
import sys
text=open(sys.argv[1]).read()
font=ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',12)
im=Image.new('RGBA',(1120,40),(0,0,0,0))
d=ImageDraw.Draw(im)
box=d.multiline_textbbox((5,3),text,font=font,spacing=2)
d.rectangle((0,0,box[2]+5,39),fill=(0,0,0,166))
d.multiline_text((5,3),text,font=font,spacing=2,fill='white')
im.save(sys.argv[2])
`,path.join(dir,'attribution.txt'),path.join(dir,'attribution.png')]);
const ff=['-hide_banner','-loglevel','error','-y'];
run('ffmpeg',[...ff,'-framerate','24','-i',path.join(dir,'city-%04d.png'),'-framerate','24','-i',path.join(dir,'frame-%04d.png'),
  '-filter_complex','[0:v][1:v]overlay','-frames:v','96','-c:v','libx264','-crf','17','-pix_fmt','yuv420p',path.join(dir,'bridge.mp4')]);
const candidate=path.join(dir,'full-preview.mp4');
// Frame 97 is the accepted room's first pose, so it belongs to that clip only.
// The Earth-to-city overlap remains a registered 3-frame dissolve.
const filter=`[0:v]scale=1280:720,fps=24,settb=AVTB,setsar=1[a];`+
  `[1:v]fps=24,settb=AVTB,setsar=1[b];[a][b]xfade=transition=fade:duration=0.125:offset=4.875[ab];`+
  `[2:v]settb=AVTB,setsar=1[c];[3:v]settb=AVTB,setsar=1[d];[ab][c][d]concat=n=3:v=1:a=0[film];`+
  `[4:v]scale=-1:18[logo];[film][logo]overlay=14:H-32:enable='between(t,4.875,17.125)'[marked];`+
  `[marked][5:v]overlay=125:H-45:enable='between(t,4.875,17.125)'[out]`;
run('ffmpeg',[...ff,'-i','media/earth.mp4','-framerate','24','-i',path.join(dir,'descent-%04d.png'),
  '-i',path.join(dir,'bridge.mp4'),'-i',path.join(room,'window-to-screen.mp4'),'-i','public/opening/google-maps.png','-i',path.join(dir,'attribution.png'),
  '-filter_complex',filter,'-map','[out]','-c:v','libx264','-crf','23','-preset','slow','-pix_fmt','yuv420p','-movflags','+faststart',candidate]);
const probe=JSON.parse(run('ffprobe',['-v','error','-count_frames','-show_entries','stream=width,height,r_frame_rate,nb_read_frames:format=duration','-of','json',candidate]));
if(probe.streams[0].nb_read_frames!=='555' || Number(probe.format.duration)!==23.125)throw new Error('Unexpected sequence timing');
const black=spawnSync('ffmpeg',['-hide_banner','-i',candidate,'-vf','blackdetect=d=0.04:pix_th=0.05','-an','-f','null','-'],{encoding:'utf8'});
if(black.status!==0 || /black_start:/.test(black.stderr))throw new Error('Black interval or failed integrity check');
const bytes=await fs.readFile(candidate),sha=crypto.createHash('sha256').update(bytes).digest('hex');
const manifest={
  src:`/media/continuous/${path.basename(dir)}/full-preview.mp4`,seconds:23.125,
  open:{rotY:-.9,rotX:0,distance:3.55,lift:.18,exposure:1.12},
  ui:JSON.parse(await fs.readFile('media/ui-state.json')),
  portal:{start:17.125,fps:24,frames:roomPoses.map(p=>p.screen)},
  credits:{start:4.875,end:17.125,text:credit},
};
await fs.writeFile('media/continuous/handoff-proof.json',JSON.stringify(manifest));
await fs.writeFile(path.join(dir,'integrity.json'),JSON.stringify({sha256:sha,bytes:bytes.length,probe,blackIntervals:[],cameraJoin:true},null,2));
if(process.argv.includes('--publish')) {
  const review=JSON.parse(await fs.readFile(path.join(dir,'review.json')));
  if(review.status!=='pass' || review.sha256!==sha)throw new Error('This exact film needs a passing review before publication');
  const filename=`intro-${sha.slice(0,10)}.mp4`;
  await fs.copyFile(candidate,path.join('public/opening',filename));
  manifest.src=`/opening/${filename}`;
  await fs.writeFile('public/opening/intro.json',JSON.stringify(manifest,null,2)+'\n');
  console.log('Updated local public manifest:',filename);
}
console.log('Verified candidate:',candidate,sha);
