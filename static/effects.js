'use strict';
// Ambient background: layered glowing particles, constellation links, cursor vortex,
// click shockwaves and occasional shooting stars. Always on; pauses only while the tab is hidden.
(() => {
  const canvas=document.querySelector('#ambient-canvas'),ctx=canvas&&canvas.getContext('2d'),glow=document.querySelector('#cursor-glow');
  if(!ctx)return;
  const coarse=window.matchMedia('(pointer: coarse)');
  const PALETTE=[[138,246,192],[110,231,255],[151,240,191],[186,160,255],[94,234,212]];
  const LINK=120,CURSOR=230,TAU=Math.PI*2;
  let width=0,height=0,particles=[],waves=[],sparks=[],meteors=[],pulses=[],trail=[],nebulae=[],orbs=[],frame=0,last=0,nextMeteor=0;
  const pointer={x:-1e4,y:-1e4,active:false},smooth={x:0,y:0};

  function makeParticle(){
    const depth=Math.random(),color=PALETTE[Math.floor(Math.random()*PALETTE.length)];
    return {x:Math.random()*width,y:Math.random()*height,vx:(Math.random()-.5)*.25,vy:(Math.random()-.5)*.25,
      depth,r:.6+depth*1.9,color,phase:Math.random()*TAU,twinkle:.6+Math.random()*1.4};
  }
  function resize(){
    width=innerWidth;height=innerHeight;const dpr=Math.min(devicePixelRatio||1,2);
    canvas.width=width*dpr;canvas.height=height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);
    const count=Math.min(150,Math.max(40,Math.round(width*height/12000)));
    particles=Array.from({length:count},makeParticle);
    nebulae=[0,1,2,3].map(i=>({color:PALETTE[[0,1,3,4][i]],ax:.2+Math.random()*.6,ay:.2+Math.random()*.6,rx:.25+Math.random()*.2,ry:.2+Math.random()*.2,speed:.00004+Math.random()*.00005,phase:Math.random()*TAU,size:.45+Math.random()*.25}));
    orbs=Array.from({length:7},()=>({x:Math.random()*width,y:Math.random()*height,r:40+Math.random()*90,vx:(Math.random()-.5)*.12,vy:(Math.random()-.5)*.12,color:PALETTE[Math.floor(Math.random()*PALETTE.length)],phase:Math.random()*TAU}));
  }
  function spawnMeteor(now){
    const fromLeft=Math.random()<.5,angle=(fromLeft?.18:Math.PI-.18)+(Math.random()-.5)*.25,speed=9+Math.random()*6;
    meteors.push({x:fromLeft?-50:width+50,y:Math.random()*height*.55,vx:Math.cos(angle)*speed,vy:Math.sin(angle)*speed,life:1,color:PALETTE[Math.floor(Math.random()*PALETTE.length)]});
    nextMeteor=now+1800+Math.random()*3500;
  }
  function burst(x,y){
    waves.push({x,y,r:0,life:1});
    waves.push({x,y,r:0,life:1.25,slow:true});for(let i=0;i<48;i++){const a=Math.random()*TAU,s=1.5+Math.random()*7;sparks.push({x,y,vx:Math.cos(a)*s,vy:Math.sin(a)*s,life:1,color:PALETTE[i%PALETTE.length]});}
    for(const p of particles){const dx=p.x-x,dy=p.y-y,d=Math.hypot(dx,dy);if(d<260&&d>1){const f=(1-d/260)*5;p.vx+=dx/d*f;p.vy+=dy/d*f;}}
  }
  const rgba=(c,a)=>`rgba(${c[0]},${c[1]},${c[2]},${a})`;

  function draw(now){
    frame=0;if(document.hidden)return;
    const dt=last?Math.min((now-last)/16.67,2.5):1;last=now;
    ctx.clearRect(0,0,width,height);
    smooth.x+=(pointer.x-smooth.x)*.1;smooth.y+=(pointer.y-smooth.y)*.1;
    if(glow&&!coarse.matches&&pointer.active)glow.style.transform=`translate(${smooth.x-250}px,${smooth.y-250}px)`;
    // Slow parallax drift tied to cursor position gives the field depth.
    const px=pointer.active?(smooth.x/width-.5):0,py=pointer.active?(smooth.y/height-.5):0;
    ctx.globalCompositeOperation='lighter';
    // Drifting aurora nebulae.
    const span=Math.max(width,height);
    for(const n of nebulae){
      const t=now*n.speed+n.phase,x=width*(n.ax+Math.sin(t)*n.rx),y=height*(n.ay+Math.cos(t*1.3)*n.ry),r=span*n.size*(.9+Math.sin(t*2.1)*.1);
      const g=ctx.createRadialGradient(x,y,0,x,y,r);g.addColorStop(0,rgba(n.color,.075));g.addColorStop(.5,rgba(n.color,.03));g.addColorStop(1,rgba(n.color,0));
      ctx.fillStyle=g;ctx.fillRect(0,0,width,height);
    }
    // Soft out-of-focus bokeh orbs.
    for(const o of orbs){
      o.x+=o.vx*dt;o.y+=o.vy*dt;if(o.x<-o.r)o.x=width+o.r;else if(o.x>width+o.r)o.x=-o.r;if(o.y<-o.r)o.y=height+o.r;else if(o.y>height+o.r)o.y=-o.r;
      const ox=o.x-px*60,oy=o.y-py*60,a=.05+Math.sin(now*.0007+o.phase)*.025,g=ctx.createRadialGradient(ox,oy,o.r*.2,ox,oy,o.r);
      g.addColorStop(0,rgba(o.color,a));g.addColorStop(.7,rgba(o.color,a*.5));g.addColorStop(1,rgba(o.color,0));ctx.fillStyle=g;ctx.beginPath();ctx.arc(ox,oy,o.r,0,TAU);ctx.fill();
    }

    // Particles: flow-field drift + cursor vortex (pull in, swirl around).
    for(const p of particles){
      const angle=Math.sin(p.x*.0021+now*.00007)*Math.cos(p.y*.0019-now*.00005)*TAU;
      p.vx+=Math.cos(angle)*.006*dt;p.vy+=Math.sin(angle)*.006*dt;
      if(pointer.active){
        const dx=pointer.x-p.x,dy=pointer.y-p.y,d=Math.hypot(dx,dy);
        if(d<CURSOR&&d>8){const f=(1-d/CURSOR);p.vx+=(dx/d*.035-dy/d*.09)*f*dt;p.vy+=(dy/d*.035+dx/d*.09)*f*dt;if(d<40){p.vx-=dx/d*.12*dt;p.vy-=dy/d*.12*dt;}}
      }
      p.vx*=.985;p.vy*=.985;
      const speed=Math.hypot(p.vx,p.vy);if(speed<.08){p.vx+=(Math.random()-.5)*.04;p.vy+=(Math.random()-.5)*.04;}
      p.x+=p.vx*dt;p.y+=p.vy*dt;
      if(p.x<-20)p.x=width+20;else if(p.x>width+20)p.x=-20;if(p.y<-20)p.y=height+20;else if(p.y>height+20)p.y=-20;
      p.sx=p.x-px*30*p.depth;p.sy=p.y-py*30*p.depth;
    }

    // Constellation links via a spatial grid (avoids O(n²) on large screens).
    const grid=new Map(),cell=LINK;
    for(const p of particles){const key=Math.floor(p.sx/cell)+','+Math.floor(p.sy/cell);(grid.get(key)||grid.set(key,[]).get(key)).push(p);}
    ctx.lineWidth=.6;
    for(const p of particles){
      const gx=Math.floor(p.sx/cell),gy=Math.floor(p.sy/cell);
      for(let ox=0;ox<=1;ox++)for(let oy=-1;oy<=1;oy++){
        if(ox===0&&oy<0)continue;const bucket=grid.get((gx+ox)+','+(gy+oy));if(!bucket)continue;
        for(const q of bucket){
          if(q===p||(ox===0&&oy===0&&q.x<=p.x))continue;
          const d=Math.hypot(p.sx-q.sx,p.sy-q.sy);if(d>=LINK)continue;
          let a=(1-d/LINK)*.16;
          if(pointer.active){const m=Math.hypot((p.sx+q.sx)/2-pointer.x,(p.sy+q.sy)/2-pointer.y);if(m<CURSOR)a+=(1-m/CURSOR)*.35;}
          const g=ctx.createLinearGradient(p.sx,p.sy,q.sx,q.sy);g.addColorStop(0,rgba(p.color,a));g.addColorStop(1,rgba(q.color,a));
          ctx.strokeStyle=g;ctx.beginPath();ctx.moveTo(p.sx,p.sy);ctx.lineTo(q.sx,q.sy);ctx.stroke();
          if(pulses.length<40&&Math.random()<.0025*dt)pulses.push({p,q,t:0,speed:.012+Math.random()*.02});
        }
      }
    }

    // Cursor tethers.
    if(pointer.active){
      for(const p of particles){const d=Math.hypot(p.sx-pointer.x,p.sy-pointer.y);if(d<CURSOR*.8){ctx.strokeStyle=rgba(p.color,(1-d/(CURSOR*.8))*.32);ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(p.sx,p.sy);ctx.lineTo(pointer.x,pointer.y);ctx.stroke();}}
    }

    // Energy pulses racing along constellation links.
    for(let i=pulses.length-1;i>=0;i--){
      const u=pulses[i];u.t+=u.speed*dt;const d=Math.hypot(u.p.sx-u.q.sx,u.p.sy-u.q.sy);
      if(u.t>=1||d>LINK*1.3){if(u.t>=1){u.q.flash=1;}pulses.splice(i,1);continue;}
      const x=u.p.sx+(u.q.sx-u.p.sx)*u.t,y=u.p.sy+(u.q.sy-u.p.sy)*u.t,g=ctx.createRadialGradient(x,y,0,x,y,9);
      g.addColorStop(0,rgba([255,255,255],.95));g.addColorStop(.3,rgba(u.p.color,.6));g.addColorStop(1,rgba(u.p.color,0));ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,9,0,TAU);ctx.fill();
    }
    // Comet trail following the cursor.
    if(pointer.active){trail.push({x:smooth.x,y:smooth.y});}
    if(trail.length>28||(!pointer.active&&trail.length))trail.shift();
    for(let i=1;i<trail.length;i++){
      const k=i/trail.length,a=trail[i-1],b=trail[i],c=PALETTE[i%2?0:1];
      ctx.strokeStyle=rgba(c,k*.55);ctx.lineWidth=k*7;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
    }
    if(pointer.active){const g=ctx.createRadialGradient(smooth.x,smooth.y,0,smooth.x,smooth.y,26);g.addColorStop(0,rgba([255,255,255],.5));g.addColorStop(.35,rgba(PALETTE[0],.25));g.addColorStop(1,rgba(PALETTE[0],0));ctx.fillStyle=g;ctx.beginPath();ctx.arc(smooth.x,smooth.y,26,0,TAU);ctx.fill();}
    // Glowing particle bodies with halo.
    for(const p of particles){
      p.flash=(p.flash||0)*Math.pow(.93,dt);
      const pulse=.55+Math.sin(now*.0012*p.twinkle+p.phase)*.45+p.flash,alpha=Math.min(1,(.25+p.depth*.55)*pulse+.12);
      const halo=p.r*(5+pulse*3+p.flash*6),g=ctx.createRadialGradient(p.sx,p.sy,0,p.sx,p.sy,halo);
      g.addColorStop(0,rgba(p.color,alpha*.55));g.addColorStop(1,rgba(p.color,0));
      ctx.fillStyle=g;ctx.beginPath();ctx.arc(p.sx,p.sy,halo,0,TAU);ctx.fill();
      ctx.fillStyle=rgba(p.color,Math.min(1,alpha+.25));ctx.beginPath();ctx.arc(p.sx,p.sy,p.r,0,TAU);ctx.fill();
    }

    // Shooting stars.
    if(now>nextMeteor)spawnMeteor(now);
    for(let i=meteors.length-1;i>=0;i--){
      const m=meteors[i];m.x+=m.vx*dt;m.y+=m.vy*dt;m.life-=.006*dt;
      if(m.life<=0||m.x<-200||m.x>width+200||m.y>height+200){meteors.splice(i,1);continue;}
      const tx=m.x-m.vx*14,ty=m.y-m.vy*14,g=ctx.createLinearGradient(m.x,m.y,tx,ty);
      g.addColorStop(0,rgba([255,255,255],.9*m.life));g.addColorStop(.15,rgba(m.color,.6*m.life));g.addColorStop(1,rgba(m.color,0));
      ctx.strokeStyle=g;ctx.lineWidth=2.2;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(m.x,m.y);ctx.lineTo(tx,ty);ctx.stroke();
      if(sparks.length<220&&Math.random()<.5*dt)sparks.push({x:m.x,y:m.y,vx:m.vx*.08+(Math.random()-.5),vy:m.vy*.08+(Math.random()-.5),life:.8,color:m.color});
    }

    // Click shockwaves and sparks.
    for(let i=waves.length-1;i>=0;i--){
      const w=waves[i];w.r+=(w.slow?4:8)*dt;w.life-=.022*dt;if(w.life<=0){waves.splice(i,1);continue;}
      ctx.strokeStyle=rgba(PALETTE[0],.55*w.life);ctx.lineWidth=2.2*w.life;ctx.beginPath();ctx.arc(w.x,w.y,w.r,0,TAU);ctx.stroke();
      ctx.strokeStyle=rgba(PALETTE[1],.3*w.life);ctx.lineWidth=1;ctx.beginPath();ctx.arc(w.x,w.y,w.r*.62,0,TAU);ctx.stroke();
    }
    for(let i=sparks.length-1;i>=0;i--){
      const s=sparks[i];s.x+=s.vx*dt;s.y+=s.vy*dt;s.vx*=.94;s.vy*=.94;s.life-=.025*dt;if(s.life<=0){sparks.splice(i,1);continue;}
      ctx.fillStyle=rgba(s.color,s.life);ctx.beginPath();ctx.arc(s.x,s.y,1.6*s.life+.4,0,TAU);ctx.fill();
    }

    ctx.globalCompositeOperation='source-over';
    frame=requestAnimationFrame(draw);
  }
  function sync(){if(frame){cancelAnimationFrame(frame);frame=0;}last=0;if(!document.hidden)frame=requestAnimationFrame(draw);}

  document.addEventListener('pointermove',event=>{
    if(event.pointerType==='touch')return;
    if(!pointer.active){smooth.x=event.clientX;smooth.y=event.clientY;}
    pointer.x=event.clientX;pointer.y=event.clientY;pointer.active=true;if(glow)glow.style.opacity='1';
    const target=event.target.closest&&event.target.closest('.card,.button-primary');
    if(target){const rect=target.getBoundingClientRect();target.style.setProperty('--pointer-x',`${event.clientX-rect.left}px`);target.style.setProperty('--pointer-y',`${event.clientY-rect.top}px`);}
  },{passive:true});
  document.addEventListener('pointerdown',event=>burst(event.clientX,event.clientY),{passive:true});
  document.documentElement.addEventListener('pointerleave',()=>{pointer.active=false;pointer.x=pointer.y=-1e4;if(glow)glow.style.opacity='0';});
  document.addEventListener('visibilitychange',sync);
  window.addEventListener('resize',resize,{passive:true});
  resize();nextMeteor=performance.now()+1500;sync();
})();
