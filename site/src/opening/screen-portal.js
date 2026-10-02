// Map the actual page into the filmed display. No screenshot-to-page dissolve.
// Corner order from Blender: bottom-left, bottom-right, top-right, top-left.
export function screenQuad(track, seconds, width, height, videoWidth, videoHeight) {
  const index = Math.max(0, Math.min(track.frames.length - 1, (seconds - track.start) * track.fps));
  const a = track.frames[Math.floor(index)], b = track.frames[Math.ceil(index)];
  const k = index % 1;
  const scale = Math.max(width / videoWidth, height / videoHeight);
  const sw = videoWidth * scale, sh = videoHeight * scale;
  return a.map((p, i) => [
    (p[0] + (b[i][0] - p[0]) * k) * sw - (sw - width) / 2,
    (p[1] + (b[i][1] - p[1]) * k) * sh - (sh - height) / 2,
  ]);
}

export function projectiveMatrix(corners, width, height) {
  const [p0, p1, p2, p3] = [corners[3], corners[2], corners[1], corners[0]];
  const dx1=p1[0]-p2[0], dx2=p3[0]-p2[0], dx3=p0[0]-p1[0]+p2[0]-p3[0];
  const dy1=p1[1]-p2[1], dy2=p3[1]-p2[1], dy3=p0[1]-p1[1]+p2[1]-p3[1];
  const det=dx1*dy2-dx2*dy1;
  if (Math.abs(det)<1e-10) return null;
  const g=(dx3*dy2-dx2*dy3)/det, h=(dx1*dy3-dx3*dy1)/det;
  const a=p1[0]-p0[0]+g*p1[0], b=p3[0]-p0[0]+h*p3[0];
  const d=p1[1]-p0[1]+g*p1[1], e=p3[1]-p0[1]+h*p3[1];
  return [a/width,d/width,0,g/width,b/height,e/height,0,h/height,0,0,1,0,p0[0],p0[1],0,1];
}

export class ScreenPortal {
  constructor(video, track, onPrepare) {
    this.video=video; this.track=track; this.onPrepare=onPrepare;
    this.tick=this.tick.bind(this);
    this.schedule();
  }
  schedule() {
    if (this.stopped) return;
    if (this.video.requestVideoFrameCallback) this.callback=this.video.requestVideoFrameCallback(this.tick);
    else this.callback=requestAnimationFrame(this.tick);
  }
  tick(now, metadata) {
    if (this.stopped) return;
    const time=metadata?.mediaTime ?? this.video.currentTime;
    if (time>=this.track.start) {
      if (!this.stage) this.mount();
      this.place(time);
    }
    this.schedule();
  }
  mount() {
    this.stage=document.createElement('div');
    this.stage.className='opening-live-stage';
    this.stage.inert=true;
    this.moved=[];
    for (const el of document.querySelectorAll('body > .field, body > #stage, body > #ui')) {
      const marker=document.createComment('live screen position');
      el.before(marker); this.moved.push([el,marker]);this.stage.append(el);
    }
    document.body.prepend(this.stage);
    this.onPrepare?.();
    document.documentElement.classList.add('screen-portal-active');
  }
  place(time) {
    const w=window.innerWidth,h=window.innerHeight;
    const quad=screenQuad(this.track,time,w,h,this.video.videoWidth,this.video.videoHeight);
    // On portrait screens the movie is cropped. Fit the live page to the visible
    // portion as the display reaches the edges, ending at the native viewport.
    const visible=quad.map(([x,y])=>[Math.min(w,Math.max(0,x)),Math.min(h,Math.max(0,y))]);
    const matrix=projectiveMatrix(visible,w,h);
    if (!matrix || !matrix.every(Number.isFinite)) return;
    this.stage.style.transform=`matrix3d(${matrix.join(',')})`;
    const [bl,br,tr,tl]=quad;
    this.video.style.clipPath=`polygon(evenodd, 0px 0px, ${w}px 0px, ${w}px ${h}px, 0px ${h}px, 0px 0px, ${tl[0]}px ${tl[1]}px, ${bl[0]}px ${bl[1]}px, ${br[0]}px ${br[1]}px, ${tr[0]}px ${tr[1]}px, ${tl[0]}px ${tl[1]}px)`;
  }
  finish() {
    this.stopped=true;
    if (this.video.cancelVideoFrameCallback) this.video.cancelVideoFrameCallback(this.callback);
    else cancelAnimationFrame(this.callback);
    for (const [el,marker] of this.moved ?? []) marker.replaceWith(el);
    this.stage?.remove();
    this.video.style.clipPath='';
    document.documentElement.classList.remove('screen-portal-active');
  }
}
