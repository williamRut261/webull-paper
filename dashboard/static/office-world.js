/* Stonks AgentOffice game floor.
   Art direction adapted from MIT-licensed harishkotra/agent-office.
   Rendered state is server-sanitized GitHub Checks metadata. Walks are decoration.
   No network APIs, broker commands, model execution, external scripts or storage. */
(() => {
  "use strict";
  const canvas = document.getElementById("office-world");
  const viewport = document.getElementById("world-viewport");
  const buttons = [...document.querySelectorAll("#agent-roster .agent-btn")];
  if (!canvas || !viewport || buttons.length !== 7) return;
  const ctx = canvas.getContext("2d", { alpha: false });
  if (!ctx) return;
  const W = 1152, H = 704;
  ctx.imageSmoothingEnabled = false;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const motionButton = document.getElementById("motion-toggle");
  const followButton = document.getElementById("camera-follow");
  const zoomIn = document.getElementById("zoom-in"), zoomOut = document.getElementById("zoom-out");
  const zoomLabel = document.getElementById("zoom-level");
  let selected = 0, zoom = 1, follow = false, running = true, visible = !document.hidden;
  let last = 0, tick = 0, sinceWalk = 0, wandering = -1;
  const agents = buttons.map((button, i) => {
    const d = button.dataset;
    const desks = [
      [146, 248], [398, 248], [650, 248], [902, 248],
      [263, 510], [563, 510], [861, 510]
    ];
    const home = { x: desks[i][0] + 42, y: desks[i][1] + 45 };
    return {
      name: d.name, role: d.role, task: d.task, detail: d.detail,
      color: d.color, stage: d.stage, action: d.action, symbol: d.symbol,
      confidence: d.confidence, desk: desks[i], home,
      x: home.x, y: home.y, path: [], dwell: 0, sprite: i % 6, direction: "down",
      walking: false
    };
  });
  const chars = [];
  for (let i = 0; i < 6; i++) {
    const img = new Image();
    img.decoding = "async";
    img.src = "/office/sprites/char_" + i + ".png";
    chars.push(img);
  }

  const floor = document.createElement("canvas");
  floor.width = W; floor.height = H;
  const g = floor.getContext("2d");
  g.imageSmoothingEnabled = false;

  function rect(c, x, y, w, h, color) {
    c.fillStyle = color; c.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  }
  function stroke(c, x, y, w, h, color, line = 2) {
    rect(c, x, y, w, line, color); rect(c, x, y + h - line, w, line, color);
    rect(c, x, y, line, h, color); rect(c, x + w - line, y, line, h, color);
  }
  function text(c, value, x, y, color = "#e6f4ec", font = "bold 12px monospace", align = "left") {
    c.fillStyle = color; c.font = font; c.textAlign = align; c.textBaseline = "top";
    c.fillText(value, x, y);
  }
  function plant(c, x, y, size = 1) {
    rect(c, x + 6 * size, y + 21 * size, 22 * size, 15 * size, "#804d45");
    rect(c, x + 10 * size, y + 17 * size, 16 * size, 5 * size, "#ae735d");
    for (const [a,b,s] of [[11,5,13],[3,12,12],[22,12,11],[15,0,11],[9,18,9]]) {
      rect(c, x + a * size, y + b * size, s * size, 10 * size, "#2d896b");
      rect(c, x + (a+3) * size, y + (b+2) * size, (s-6) * size, 5 * size, "#6ed3a0");
    }
  }
  function bookshelf(c,x,y) {
    rect(c,x,y,88,96,"#121928");stroke(c,x,y,88,96,"#586074",5);
    for (let row=0;row<3;row++){
      rect(c,x+7,y+8+row*27,72,3,"#af8b72");
      for(let z=0;z<7;z++)rect(c,x+10+z*10,y+12+row*27,6,17,
        ["#9273bb","#83b9a6","#edbe82","#6d90bd"][((row+z)%4)]);
    }
  }
  function fixtureDesk(c, x, y, i) {
    rect(c, x + 3, y + 82, 137, 13, "#131d2d");
    rect(c, x + 6, y + 11, 124, 73, "#564c56");
    stroke(c,x+6,y+11,124,73,"#987968",5);
    rect(c,x+13,y+16,110,54,"#71616a");
    rect(c,x+10,y+70,119,10,"#c39b78");
    rect(c,x+10,y+80,119,8,"#735f5b");
    rect(c,x+34,y-8,70,53,"#101e2a");
    stroke(c,x+34,y-8,70,53,"#6d8ca1",4);
    rect(c,x+41,y-1,56,39,"#12414b");
    rect(c,x+44,y+3,50,2,"#408a8e");
    rect(c,x+41,y+48,70,5,"#283546");
    rect(c,x+62,y+45,10,10,"#0e1a2d");
    rect(c,x+48,y+56,54,9,"#bfc6b5");
    rect(c,x+45,y+57,58,3,"#485363");
    rect(c,x+6,y+14,18,13,["#b9c9da","#ecc992","#99d8cb"][i%3]);
    rect(c,x+119,y+18,8,23,"#293847");
    rect(c,x+112,y+18,21,7,"#d6ac84");
    rect(c,x+20,y+66,17,8,"#8d6551");
    rect(c,x+46,y+95,44,23,"#303b55");
    rect(c,x+51,y+100,34,16,"#415471");
  }
  function paintFloor() {
    rect(g,0,0,W,H,"#101726");
    // Tiled carpet and skirting.
    rect(g,0,140,W,H-140,"#303747");
    for(let y=140;y<H;y+=32)for(let x=0;x<W;x+=32) {
      const k=((x/32)*13+(y/32)*7)%5;
      rect(g,x,y,31,31,["#313949","#343b4d","#353e4f","#303747","#394152"][k]);
      if((x+y)%96===0)rect(g,x+4,y+4,3,3,"#485265");
    }
    rect(g,0,0,W,142,"#24283b");
    for(let x=0;x<W;x+=48) rect(g,x,24,2,110,"#353a52");
    rect(g,0,130,W,14,"#111a2a");rect(g,0,140,W,7,"#5c6070");
    // city windows
    for(const x of [130,396,660,930]){
      rect(g,x,14,198,100,"#111a2d");stroke(g,x,14,198,100,"#6f768b",6);
      rect(g,x+8,21,182,84,"#254a6d");
      rect(g,x+8,81,182,24,"#182e47");
      for(let z=0;z<6;z++){
        const xx=x+10+z*30;
        rect(g,xx,63-(z%3)*10,23,42+(z%3)*10,"#19263e");
        for(let p=0;p<3;p++)rect(g,xx+4+p*6,69+(p%2)*8,3,3,"#f2c682");
      }
      rect(g,x+102,19,5,88,"#1e283c");
    }
    rect(g,15,167,210,48,"#172335");stroke(g,15,167,210,48,"#638a84",3);
    text(g,"STONKS  /  HQ",29,177,"#8dffd2","bold 20px monospace");
    text(g,"RESEARCH OPERATIONS",29,199,"#b0b9ca","bold 10px monospace");
    rect(g,463,160,238,59,"#141c2e");stroke(g,463,160,238,59,"#596581",4);
    text(g,"SEVEN-AGENT DESK",482,170,"#d1f0df","bold 15px monospace");
    text(g,"GITHUB CHECKS → VERIFIED",482,191,"#8ed0bb","bold 11px monospace");
    // Conference room edge + bench.
    rect(g,24,506,175,162,"#282d40");stroke(g,24,506,175,162,"#655c76",4);
    text(g,"LOUNGE / BREAK",37,513,"#d3b6d9","bold 11px monospace");
    rect(g,53,556,90,27,"#5c4c6b");rect(g,46,581,105,30,"#846f8a");
    stroke(g,46,581,105,30,"#33293a",4);
    rect(g,81,618,42,13,"#927960");rect(g,91,629,23,14,"#614d4c");
    // Break room coffee station
    rect(g,980,502,152,159,"#2c3a3a");stroke(g,980,502,152,159,"#59736f",4);
    text(g,"COFFEE",998,511,"#9af2c9","bold 13px monospace");
    rect(g,1007,545,80,43,"#6f5b54");rect(g,1007,536,80,14,"#b58c6e");
    rect(g,1014,550,33,30,"#293646");rect(g,1020,542,26,14,"#718597");
    rect(g,1058,553,16,18,"#bdc7bb");rect(g,1075,556,7,12,"#d8c9aa");
    rect(g,1001,596,27,39,"#629ab0");stroke(g,1001,596,27,39,"#263b54",4);
    text(g,"☕",1051,605,"#f3d49a","bold 24px sans-serif");
    // Walkway, furniture.
    rect(g,212,410,726,43,"#3e4457");rect(g,212,421,726,4,"#536078");
    rect(g,212,445,726,4,"#263449");
    bookshelf(g,13,260);bookshelf(g,1039,248);
    plant(g,104,454);plant(g,1080,415);plant(g,224,626);plant(g,904,641);
    for(let i=0;i<agents.length;i++){
      const a=agents[i];
      rect(g,a.desk[0]+1,a.desk[1]+125,137,7,"#1f283a");
      fixtureDesk(g,a.desk[0],a.desk[1],i);
      rect(g,a.desk[0]-8,a.desk[1]+4,3,107,
        ["#668dd0","#9676ba","#cca57b","#6ca49c","#c87b92","#ba9458","#6a9dba"][i]);
    }
    rect(g,424,613,307,52,"#22334b");stroke(g,424,613,307,52,"#637685",4);
    text(g,"RESEARCH  •  READ-ONLY",444,626,"#b9f4d3","bold 17px monospace");
    text(g,"7 AGENTS  /  0 DIRECT BROKER ORDERS",444,650,"#b1bbcb","bold 10px monospace");
  }
  paintFloor();

  function typeMonitor(c,a,i,t) {
    if(a.stage!=="WORKING")return;
    const x=a.desk[0],y=a.desk[1];
    rect(c,x+44,y+3,50,35,"#0c5449");
    const levels=[13,19,8,26];
    for(let z=0;z<4;z++){
      rect(c,x+48,y+9+z*7,levels[(z+Math.floor(t/400))%4],3,
        z%2?"#65ffc0":"#a1dfca");
    }
    if(Math.floor(t/260)%2===0)rect(c,x+51,y+59,6,3,"#fff3bf");
  }
  function fallbackCharacter(c,a,x,y) {
    rect(c,x+9,y+10,25,24,"#f0bda0");rect(c,x+7,y+3,29,12,"#453f54");
    rect(c,x+4,y+36,36,29,a.color);
    rect(c,x+7,y+66,11,16,"#35415e");rect(c,x+27,y+66,11,16,"#35415e");
    rect(c,x+14,y+19,4,4,"#17263d");rect(c,x+26,y+19,4,4,"#17263d");
  }
  function character(c,a,index,frame,t) {
    const x=Math.round(a.x-20),y=Math.round(a.y-66);
    const im=chars[a.sprite];
    const animEnabled=running&&!reduced.matches&&visible;
    const cycling=animEnabled&&(a.walking||a.stage==="WORKING");
    const id=cycling?Math.floor(t/(a.walking?180:320))%3:0;
    let row=0,flip=false;
    if(a.walking&&a.direction==="up")row=1;
    else if(a.walking&&a.direction==="left"){row=2;flip=true;}
    else if(a.walking&&a.direction==="right")row=2;
    c.save();
    if(flip){c.translate(x+44,0);c.scale(-1,1);}
    if(im.complete&&im.naturalWidth>=112&&im.naturalHeight>=96){
      c.drawImage(im,id*16,row*32,16,32,flip?0:x,y,44,88);
    }else fallbackCharacter(c,a,flip?0:x,y);
    c.restore();
    if(index===selected){
      c.strokeStyle="#c5ffe7";c.lineWidth=3;c.strokeRect(x-5,y-5,54,97);
      rect(c,x+1,y+88,41,4,"#9ff5cc");
    }
    if(a.stage==="WORKING"){
      rect(c,x+34,y+7,9,9,"#6bf5bd");
    } else if(a.stage==="FAILED"){
      rect(c,x+34,y+7,9,9,"#fa828b");
    } else if(a.stage==="STALE"){
      rect(c,x+34,y+7,9,9,"#ffc77d");
    }
    // Labels always identify specialists and verified states separately.
    const labelX=Math.max(18,Math.min(W-154,x-34));
    rect(c,labelX,y-26,148,19,"#0f1727");stroke(c,labelX,y-26,148,19,index===selected?"#a6fbd1":"#56637b",2);
    text(c,a.name.toUpperCase(),labelX+7,y-23,"#ecf2fa","bold 12px monospace");
    const short=a.stage==="UNAVAILABLE"?"N/A":a.stage;
    text(c,short,labelX+142,y-23,
      a.stage==="WORKING"?"#79f5bc":a.stage==="FAILED"?"#fc9ca0":"#bdc6d7",
      "bold 10px monospace","right");
  }
  function positionTowards(agent, node, dt) {
    const dx=node[0]-agent.x,dy=node[1]-agent.y;
    const distance=Math.hypot(dx,dy);
    if(distance<=1.5){agent.x=node[0];agent.y=node[1];agent.path.shift();return;}
    agent.direction=Math.abs(dx)>Math.abs(dy)?(dx>0?"right":"left"):(dy>0?"down":"up");
    const step=Math.min(distance,dt*0.09);
    agent.x+=dx/distance*step;agent.y+=dy/distance*step;
  }
  function sendOnBreak(i) {
    const a=agents[i],coffee=(i%2===0),dest=coffee?[1043,609]:[98,640];
    a.path=[[a.home.x,421],[dest[0],421],[dest[0],dest[1]],
      [dest[0],421],[a.home.x,421],[a.home.x,a.home.y]];
    a.dwell=0;a.walking=true;wandering=i;
  }
  function update(dt) {
    if(!running||reduced.matches||!visible) {
      if(wandering!==-1) resetWalk();
      return;
    }
    sinceWalk+=dt;
    if(wandering<0&&sinceWalk>8000){
      const eligible=agents.map((a,i)=>a.stage==="WORKING"||a.stage==="QUEUED"?-1:i)
        .filter(i=>i!==-1);
      if(eligible.length)sendOnBreak(eligible[Math.floor(Math.random()*eligible.length)]);
      sinceWalk=0;
    }
    if(wandering<0)return;
    const a=agents[wandering];
    if(!a.path.length){a.x=a.home.x;a.y=a.home.y;a.walking=false;wandering=-1;return;}
    if(a.path.length===3&&!a.dwell){
      a.dwell=1200;
      a.walking=false;
    }
    if(a.dwell>0){a.dwell-=dt;return;}
    a.walking=true;
    positionTowards(a,a.path[0],dt);
  }
  function resetWalk(){
    for(const a of agents){a.x=a.home.x;a.y=a.home.y;a.path=[];a.walking=false;a.dwell=0;a.direction="down";}
    wandering=-1;sinceWalk=0;
  }
  function render(timestamp) {
    if(!last)last=timestamp;
    const dt=Math.min(100,timestamp-last);last=timestamp;
    if(running&&!reduced.matches&&visible)tick+=dt;
    update(dt);
    ctx.drawImage(floor,0,0);
    for(let i=0;i<agents.length;i++)typeMonitor(ctx,agents[i],i,tick);
    // Decorative coffee-machine steam and monitor lights: never execution.
    if(running&&!reduced.matches&&visible){
      for(let z=0;z<3;z++){
        const rise=Math.floor((tick/90+z*9)%31);
        rect(ctx,1067+z*7,543-rise,4,6,"#c4c3ac");
      }
    }
    for(let i=0;i<agents.length;i++)character(ctx,agents[i],i,Math.floor(tick/180)%3,tick);
    window.requestAnimationFrame(render);
  }
  function pick(index) {
    if(index<0||index>=agents.length)return;
    selected=index;
    buttons.forEach((b,i)=>{b.classList.toggle("chosen",i===index);b.setAttribute("aria-pressed",i===index?"true":"false");});
    const a=agents[index];
    const put=(id,value)=>{const el=document.getElementById(id);if(el)el.textContent=value;};
    const face=document.getElementById("agent-avatar");
    if(face){face.style.background=a.color;face.textContent=a.name[0];}
    put("inspector-number",String(index+1).padStart(2,"0")+"/07");
    put("agent-name",a.name);put("agent-role",a.role);
    put("agent-task",a.task);put("agent-detail",a.detail);
    put("agent-state",a.stage);
    put("agent-opinion",a.action==="UNAVAILABLE"?"UNAVAILABLE":a.action+" "+a.symbol);
    put("agent-confidence",a.confidence||"UNAVAILABLE");
    put("agent-provenance",a.stage==="WORKING"?
      "WORKING is verified from the current GitHub research-run Check. Decorative walking is not execution.":
      "This stage reflects the selected GitHub run's Check, or UNAVAILABLE when no validated Check exists. Opinions are the last published research, not live trades.");
    if(follow)center(index);
  }
  function center(index) {
    const a=agents[index];
    const cssW=canvas.getBoundingClientRect().width,ratio=cssW/W;
    viewport.scrollTo({left:Math.max(0,a.x*ratio-viewport.clientWidth/2),behavior:reduced.matches?"auto":"smooth"});
  }
  buttons.forEach((button,i)=>button.addEventListener("click",()=>{pick(i);center(i);}));
  canvas.addEventListener("click",ev=>{
    const r=canvas.getBoundingClientRect();
    const x=(ev.clientX-r.left)*W/r.width,y=(ev.clientY-r.top)*H/r.height;
    let best=-1,dist=54;
    agents.forEach((a,i)=>{
      const d=Math.hypot(a.x-x,a.y-35-y);
      if(d<dist){dist=d;best=i;}
    });
    if(best>=0)pick(best);
  });
  function syncMotion() {
    const enabled=running&&!reduced.matches;
    motionButton.setAttribute("aria-pressed",enabled?"true":"false");
    motionButton.textContent=enabled?"Ⅱ PAUSE AMBIENCE":"▶ RESUME AMBIENCE";
    if(!enabled)resetWalk();
  }
  motionButton.addEventListener("click",()=>{running=!running;syncMotion();});
  followButton.addEventListener("click",()=>{follow=!follow;followButton.setAttribute("aria-pressed",follow?"true":"false");if(follow)center(selected);});
  function resizeZoom(next){
    zoom=Math.max(.8,Math.min(1.5,next));
    canvas.style.width=Math.round(W*zoom)+"px";
    canvas.style.minWidth="0";
    zoomLabel.textContent=Math.round(zoom*100)+"%";
    zoomOut.disabled=zoom<=.8;zoomIn.disabled=zoom>=1.5;
    if(follow)center(selected);
  }
  zoomIn.addEventListener("click",()=>resizeZoom(Math.round((zoom+.1)*10)/10));
  zoomOut.addEventListener("click",()=>resizeZoom(Math.round((zoom-.1)*10)/10));
  document.addEventListener("visibilitychange",()=>{
    visible=!document.hidden;if(!visible)resetWalk();last=0;
  });
  if(reduced.addEventListener)reduced.addEventListener("change",syncMotion);
  pick(0);syncMotion();
  window.requestAnimationFrame(render);
})();