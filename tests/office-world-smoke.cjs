"use strict";
/* Node-only deterministic browser harness: checks UI events and canvas rendering
   without contacting any broker, GitHub, GCP, or a public website. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync("dashboard/static/office-world.js", "utf8");
function element(dataset = {}) {
  const handlers = Object.create(null);
  const attrs = Object.create(null);
  return {
    dataset, textContent: "", style: {}, disabled: false, clientWidth: 760,
    classList: { toggle() {} },
    setAttribute(key,value){attrs[key] = value;},
    getAttribute(key){return attrs[key];},
    addEventListener(name, fn){handlers[name] = fn;},
    trigger(name,payload){assert.ok(handlers[name],name);handlers[name](payload);},
    scrollTo(next){this.scrollLeft = next.left;}
  };
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
const ids = Object.fromEntries([
  "motion-toggle","camera-follow","zoom-in","zoom-out","zoom-level",
  "agent-avatar","inspector-number","agent-name","agent-role",
  "agent-task","agent-detail","agent-state","agent-opinion",
  "agent-confidence","agent-provenance"
].map(name=>[name,element()]));
const canvas=element();canvas.getContext=()=>painter;
canvas.getBoundingClientRect=()=>({left:0,top:0,width:1152,height:704});
ids["office-world"]=canvas;
const viewport=element();viewport.clientWidth=750;
ids["world-viewport"]=viewport;
const documentListeners=Object.create(null);
const document={
  hidden:false,
  getElementById(name){return ids[name]??null;},
  querySelectorAll(name){
    assert.equal(name,"#agent-roster .agent-btn");
    return buttons;
  },
  createElement(tag){assert.equal(tag,"canvas");return {width:0,height:0,getContext:()=>painter};},
  addEventListener(name,fn){documentListeners[name]=fn;}
};
let frames=[];
const reduced={matches:false,addEventListener(){}};
const window={
  matchMedia:()=>reduced,
  requestAnimationFrame(fn){frames.push(fn);}
};
let imageLoads=[];
class Image {
  constructor(){this.complete=false;this.naturalWidth=0;this.naturalHeight=0;}
  set src(v){imageLoads.push(v);}
}
vm.runInNewContext(source,{document,window,Image,console,Math});
assert.equal(imageLoads.length,6);
assert.ok(imageLoads.every((s,i)=>s==="/office/sprites/char_"+i+".png"));
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
const framesToRun=25;
for(let i=0;i<framesToRun;i++){
  assert.equal(frames.length,1);
  const frame=frames.shift();
  frame(i*100);
}
ids["motion-toggle"].trigger("click");
assert.ok(ids["motion-toggle"].textContent.includes("RESUME"));
assert.equal(ids["motion-toggle"].getAttribute("aria-pressed"),"false");
ids["motion-toggle"].trigger("click");
assert.ok(ids["motion-toggle"].textContent.includes("PAUSE"));
document.hidden=true;
documentListeners.visibilitychange();
assert.equal(frames.length,1);
frames.shift()(3000);
assert.equal(frames.length,1);
console.log("Office gameworld smoke passed: sprites, canvas, selection, verified state, zoom, follow, pause and hidden tab.");
