"use strict";
/* Deterministic, network-free browser harness for sprite motion and live role states. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("dashboard/static/office-world.js", "utf8");
function element(dataset = {}) {
  const handlers = Object.create(null), attrs = Object.create(null);
  const selectors = Object.create(null);
  const classes = new Set();
  const el = {
    dataset, textContent: "", style: {}, disabled: false, clientWidth: 760,
    className:"",
    classList: {
      toggle(name, force) {if (force) classes.add(name); else classes.delete(name);},
      add(name){classes.add(name);},
      contains(name){return classes.has(name);}
    },
    querySelector(name){return selectors[name] ?? null;},
    setChild(name,child){selectors[name]=child;},
    setAttribute(key,value){attrs[key] = value;},
    getAttribute(key){return attrs[key];},
    addEventListener(name, fn){handlers[name] = fn;},
    trigger(name,payload){assert.ok(handlers[name],name);return handlers[name](payload);},
    scrollTo(next){this.scrollLeft = next.left;}
  };
  return el;
}
const painter={
  fillRect(){},strokeRect(){},drawImage(){},fillText(){},save(){},
  restore(){},translate(){},scale(){},
  set imageSmoothingEnabled(v){this._smoothing = v;}
};
const roleNames = ["Market Analyst","Technical Analyst","News Researcher",
  "Strategy Analyst","Risk Manager","Desk Lead","Trade Reviewer"];
const names = ["Maya","Theo","Nova","Iris","Sage","Atlas","Quinn"];
const buttons=names.map((name,i)=>element({
  name, role:roleNames[i],task:"Research duty",detail:"Read-only",
  color:"#78ddbb",stage:i===0?"WORKING":i===4?"FAILED":"UNAVAILABLE",
  action:i===0?"HOLD":"UNAVAILABLE",symbol:i===0?"SPY":"",
  confidence:i===0?"50%":""
}));
buttons.forEach(b=>b.setChild(".state",element()));
const rows = names.map(()=> {
  const row=element();
  for(const selector of [".role-stage",".role-proof",".dot"])row.setChild(selector,element());
  return row;
});
const ids = Object.fromEntries([
  "motion-toggle","camera-follow","zoom-in","zoom-out","zoom-level",
  "agent-avatar","inspector-number","agent-name","agent-role",
  "agent-task","agent-detail","agent-state","agent-opinion",
  "agent-confidence","agent-provenance","run-indicator","live-connection",
  "research-consensus","research-decision","research-provider","research-date",
  "verified-count"
].map(name=>[name,element()]));
const canvas=element();canvas.getContext=()=>painter;
canvas.getBoundingClientRect=()=>({left:0,top:0,width:1152,height:704});
ids["office-world"]=canvas;
const viewport=element();viewport.clientWidth=750;ids["world-viewport"]=viewport;
const docEvents=Object.create(null);
const document={
  hidden:false,
  getElementById(name){return ids[name]??null;},
  querySelectorAll(name){
    if(name==="#agent-roster .agent-btn")return buttons;
    if(name==="#verified-timeline li")return rows;
    throw Error("Unexpected DOM query: "+name);
  },
  createElement(tag){assert.equal(tag,"canvas");return {width:0,height:0,getContext:()=>painter};},
  addEventListener(name,fn){docEvents[name]=fn;}
};
let frames=[], timers=[], timerId=0, responseIndex=0, requests=[];
const reduced={matches:false,addEventListener(){}};
const responseFor=(stages,source="VERIFIED")=>({
 source,checked_at:"2026-10-22T23:36:03+00:00",refresh_after_seconds:100,
 verified_count:stages.filter(s=>s!=="UNAVAILABLE").length,
 run:{state:"in_progress",active:true,queued:false,expired:false,conclusion:"",run_url:"https://github.com/williamRut261/webull-paper/actions/runs/5"},
 roles:roleNames.map((role,i)=>({role,stage:stages[i],action:"HOLD",symbol:"SPY",confidence:"50%"})),
 research:{consensus:"NO_CONSENSUS",decision:"NO EXECUTABLE AGENT DECISION",provider:"gemini",as_of:"2026-10-22",stale:false}
});
const stages1=["DONE","WORKING","UNAVAILABLE","UNAVAILABLE","UNAVAILABLE","UNAVAILABLE","UNAVAILABLE"];
const stages2=["DONE","DONE","FAILED","UNAVAILABLE","UNAVAILABLE","UNAVAILABLE","UNAVAILABLE"];
const replies=[responseFor(stages1),responseFor(stages2),null];
const window={
  matchMedia:()=>reduced,
  requestAnimationFrame(fn){frames.push(fn);},
  setTimeout(fn,delay){const id=++timerId;timers.push({id,fn,delay});return id;},
  clearTimeout(id){timers=timers.filter(t=>t.id!==id);},
  async fetch(url,opts){
    requests.push({url,opts});
    const value = replies[Math.min(responseIndex++,replies.length-1)];
    if(value===null)throw Error("offline");
    return {ok:true,json:async()=>value};
  }
};
let images=[];
class Image{
  constructor(){this.complete=false;this.naturalWidth=0;this.naturalHeight=0;}
  set src(v){images.push(v);}
}
function flush(){return new Promise(resolve=>setImmediate(resolve));}
(async()=>{
vm.runInNewContext(source,{document,window,Image,console,Math,Set});
assert.equal(images.length,6);
assert.ok(images.every((s,i)=>s==="/office/sprites/char_"+i+".png"));
assert.equal(ids["agent-name"].textContent,"Maya");
assert.equal(ids["agent-state"].textContent,"WORKING");
assert.equal(ids["agent-opinion"].textContent,"HOLD SPY");
buttons[4].trigger("click");
assert.equal(ids["agent-name"].textContent,"Sage");
assert.equal(ids["agent-state"].textContent,"FAILED");
ids["camera-follow"].trigger("click");
assert.equal(ids["camera-follow"].getAttribute("aria-pressed"),"true");
ids["zoom-in"].trigger("click");
assert.equal(ids["zoom-level"].textContent,"110%");
ids["zoom-out"].trigger("click");
assert.equal(ids["zoom-level"].textContent,"100%");
for(let i=0;i<25;i++) {
 assert.equal(frames.length,1);
 frames.shift()(i*100);
}
ids["motion-toggle"].trigger("click");
assert.ok(ids["motion-toggle"].textContent.includes("RESUME"));
ids["motion-toggle"].trigger("click");
assert.ok(ids["motion-toggle"].textContent.includes("PAUSE"));
// Poll #1: true recorded transitions, without restarting canvas animation.
assert.equal(timers.length,1);
timers.shift().fn();
await flush();
assert.equal(requests.length,1);
assert.equal(requests[0].url,"/office/status");
assert.equal(requests[0].opts.credentials,"same-origin");
assert.equal(ids["agent-state"].textContent,"UNAVAILABLE"); // Sage has no Check now
assert.equal(buttons[0].dataset.stage,"DONE");
assert.equal(buttons[1].dataset.stage,"WORKING");
assert.equal(ids["verified-count"].textContent,"2 / 7 verified");
// Poll #2: recorded success/failure transition.
assert.equal(timers.length,1);timers.shift().fn();await flush();
assert.equal(buttons[1].dataset.stage,"DONE");
assert.equal(buttons[2].dataset.stage,"FAILED");
assert.equal(ids["verified-count"].textContent,"3 / 7 verified");
// Poll #3: upstream unavailable; never retain a glowing WORKING status.
assert.equal(timers.length,1);timers.shift().fn();await flush();
assert.ok(buttons.every(b=>b.dataset.stage==="UNAVAILABLE"));
assert.equal(ids["verified-count"].textContent,"0 / 7 verified");
assert.ok(ids["live-connection"].textContent.includes("unavailable"));
document.hidden=true;docEvents.visibilitychange();
assert.equal(frames.length,1);frames.shift()(3000);assert.equal(frames.length,1);
console.log("Office live-sync smoke passed: seven sprites, role transitions, polling, outage fail-closed, inspector, zoom, follow and pause.");
})().catch(e=>{console.error(e);process.exitCode=1;});
