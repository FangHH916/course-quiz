'use strict';
(() => {
  const canvas=document.querySelector('#ambient-canvas'),ctx=canvas.getContext('2d'),glow=document.querySelector('#cursor-glow');
  if(!ctx)return;
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)'),coarse=window.matchMedia('(pointer: coarse)');
  let enabled=true;try{enabled=JSON.parse(localStorage.getItem('shizhi-effects'))!==false;}catch{}
  let width=0,height=0,particles=[],frame=0,last=0,pointer={x:-1000,y:-1000},smooth={x:0,y:0},tracked=null;
  function resize(){width=innerWidth;height=innerHeight;const dpr=Math.min(devicePixelRatio||1,2);canvas.width=width*dpr;canvas.height=height*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);const count=Math.min(80,Math.max(22,Math.round(width*height/24000)));particles=Array.from({length:count},()=>({x:Math.random()*width,y:Math.random()*height,vx:(Math.random()-.5)*.16,vy:(Math.random()-.5)*.16,r:Math.random()*.9+.45,phase:Math.random()*Math.PI*2}));}
  function active(){return enabled&&!reduced.matches&&!document.hidden;}
  function draw(now){frame=0;if(!active())return;const dt=last?Math.min((now-last)/16.67,2):1;last=now;ctx.clearRect(0,0,width,height);
    smooth.x+=(pointer.x-smooth.x)*.08;smooth.y+=(pointer.y-smooth.y)*.08;
    if(!coarse.matches&&pointer.x>=0)glow.style.transform=`translate(${smooth.x-250}px,${smooth.y-250}px)`;
    for(let i=0;i<particles.length;i++){
      const p=particles[i],dx=p.x-pointer.x,dy=p.y-pointer.y,distance=Math.hypot(dx,dy);
      if(distance<130&&distance>1){p.x+=dx/distance*(1-distance/130)*.65*dt;p.y+=dy/distance*(1-distance/130)*.65*dt;}
      p.x+=p.vx*dt;p.y+=p.vy*dt;if(p.x<-10)p.x=width+10;if(p.x>width+10)p.x=-10;if(p.y<-10)p.y=height+10;if(p.y>height+10)p.y=-10;
      const alpha=.17+Math.sin(now*.0006+p.phase)*.09;ctx.fillStyle=`rgba(151,240,191,${alpha})`;ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);ctx.fill();
      if(distance<190){ctx.strokeStyle=`rgba(138,246,192,${(1-distance/190)*.14})`;ctx.lineWidth=.5;ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(pointer.x,pointer.y);ctx.stroke();}
      for(let j=i+1;j<particles.length;j++){const q=particles[j],d=Math.hypot(p.x-q.x,p.y-q.y);if(d<105){ctx.strokeStyle=`rgba(118,185,151,${(1-d/105)*.055})`;ctx.lineWidth=.5;ctx.beginPath();ctx.moveTo(p.x,p.y);ctx.lineTo(q.x,q.y);ctx.stroke();}}
    }
    frame=requestAnimationFrame(draw);
  }
  function sync(){document.body.classList.toggle('effects-off',!enabled||reduced.matches);if(frame){cancelAnimationFrame(frame);frame=0;}last=0;if(active())frame=requestAnimationFrame(draw);else ctx.clearRect(0,0,width,height);}
  document.addEventListener('pointermove',event=>{if(!enabled||reduced.matches||event.pointerType==='touch')return;pointer.x=event.clientX;pointer.y=event.clientY;glow.style.opacity='1';const target=event.target.closest('.card,.button-primary');if(target){const rect=target.getBoundingClientRect();target.style.setProperty('--pointer-x',`${event.clientX-rect.left}px`);target.style.setProperty('--pointer-y',`${event.clientY-rect.top}px`);if(target!==tracked)tracked=target;}} ,{passive:true});
  document.addEventListener('pointerleave',()=>{pointer.x=-1000;pointer.y=-1000;glow.style.opacity='0';});
  document.addEventListener('visibilitychange',sync);document.addEventListener('shizhi:effects',event=>{enabled=Boolean(event.detail);sync();});reduced.addEventListener('change',sync);window.addEventListener('resize',resize,{passive:true});
  resize();sync();
})();
