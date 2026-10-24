(()=>{
 const mascot=document.getElementById('ticker-mascot'),launch=document.getElementById('ticker-launch'),card=document.getElementById('ticker-card'),close=document.getElementById('ticker-close');
 const hero=document.querySelector('.hero'),rig=mascot.querySelector('.ticker-rig'),hand=mascot.querySelector('.ticker-wave-hand'),leftEye=document.getElementById('ticker-pupil-left'),rightEye=document.getElementById('ticker-pupil-right'),pause=document.getElementById('pause-network');
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 let inView=true,greeted=false,frame=0,touchTimer=0,targetX=0,targetY=0,gazeX=0,gazeY=0,lastWave=-Infinity;
 const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
 const motionPaused=()=>reduced.matches||pause?.getAttribute('aria-pressed')==='true';
 function setOpen(open,restoreFocus=false){launch.setAttribute('aria-expanded',String(open));card.hidden=!open;if(restoreFocus)launch.focus();}
 function wave(){if(motionPaused()||!inView||document.hidden||mascot.classList.contains('is-waving')||performance.now()-lastWave<900)return;lastWave=performance.now();mascot.classList.add('is-waving');}
 hand.addEventListener('animationend',event=>{if(event.animationName==='ticker-hand-wave')mascot.classList.remove('is-waving');});
 function applyGaze(){leftEye.setAttribute('transform',`translate(${(gazeX*16).toFixed(2)} ${(gazeY*11).toFixed(2)})`);rightEye.setAttribute('transform',`translate(${(gazeX*17).toFixed(2)} ${(gazeY*12).toFixed(2)})`);mascot.style.setProperty('--ticker-rx',(-gazeY*2).toFixed(2)+'deg');mascot.style.setProperty('--ticker-ry',(gazeX*3).toFixed(2)+'deg');}
 function animateEyes(){frame=0;if(motionPaused()||!inView||document.hidden)return;gazeX+=(targetX-gazeX)*.18;gazeY+=(targetY-gazeY)*.18;const moving=Math.abs(targetX-gazeX)+Math.abs(targetY-gazeY)>.003;if(!moving){gazeX=targetX;gazeY=targetY;}applyGaze();if(moving)frame=requestAnimationFrame(animateEyes);}
 function requestGaze(x,y){targetX=x;targetY=y;if(!frame&&!motionPaused()&&inView&&!document.hidden)frame=requestAnimationFrame(animateEyes);}
 function lookAt(clientX,clientY){if(motionPaused()||!inView||document.hidden)return;const r=rig.getBoundingClientRect(),faceX=r.left+r.width*.49,faceY=r.top+r.height*.30;const dx=(clientX-faceX)/Math.max(180,innerWidth*.35),dy=(clientY-faceY)/Math.max(150,innerHeight*.38);const length=Math.hypot(dx,dy),scale=length>1?1/length:1;requestGaze(clamp(dx*scale,-1,1),clamp(dy*scale,-1,1));}
 function neutral(immediate=false){if(immediate){if(frame)cancelAnimationFrame(frame);frame=0;targetX=targetY=gazeX=gazeY=0;applyGaze();}else requestGaze(0,0);}
 function syncMotion(){const stopped=motionPaused();mascot.classList.toggle('is-motion-paused',stopped);if(stopped){neutral(true);mascot.classList.remove('is-waving');}}
 launch.addEventListener('pointerenter',wave);launch.addEventListener('focus',wave);
 launch.addEventListener('click',()=>{wave();setOpen(card.hidden);});
 launch.addEventListener('pointerdown',event=>{if(event.pointerType==='touch'){wave();lookAt(event.clientX,event.clientY);clearTimeout(touchTimer);touchTimer=setTimeout(()=>neutral(),1100);}});
 close.addEventListener('click',()=>setOpen(false,true));
 card.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>setOpen(false)));
 document.addEventListener('click',event=>{if(!card.hidden&&!mascot.contains(event.target))setOpen(false);});
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!card.hidden){setOpen(false,true);event.stopPropagation();}});
 document.addEventListener('pointermove',event=>{if(event.pointerType==='touch')return;lookAt(event.clientX,event.clientY);},{passive:true});
 document.addEventListener('pointerleave',()=>neutral());window.addEventListener('blur',()=>neutral(true));
 document.addEventListener('visibilitychange',()=>{if(document.hidden)neutral(true);});
 hero.addEventListener('pointerdown',event=>{if(event.target.closest('.pill'))wave();},{passive:true});
 reduced.addEventListener('change',syncMotion);if(pause)new MutationObserver(syncMotion).observe(pause,{attributes:true,attributeFilter:['aria-pressed']});syncMotion();
 function greet(){if(!greeted&&inView&&document.readyState==='complete'&&!motionPaused()){greeted=true;wave();}}
 new IntersectionObserver(entries=>{inView=entries[0].isIntersecting;mascot.classList.toggle('is-out-of-view',!inView);if(!inView){neutral(true);mascot.classList.remove('is-waving');}else greet();},{threshold:.1}).observe(mascot);
 if(document.readyState==='complete')greet();else window.addEventListener('load',greet,{once:true});
})();
