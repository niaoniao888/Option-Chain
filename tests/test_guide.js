"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function createHarness({editable=true,withRefresh=true,storage=new Map(),storageBlocked=false}={}) {
  const elements = new Map(), timers = new Map(), windowListeners = {};
  let timerId = 0, fetchImpl = null;
  const document = {activeElement:null};
  class ClassList {
    constructor(values=[]){this.values=new Set(values);}
    contains(value){return this.values.has(value);}
    add(value){this.values.add(value);}
    remove(value){this.values.delete(value);}
    toggle(value,force){if(force===undefined)force=!this.values.has(value);force?this.values.add(value):this.values.delete(value);return force;}
  }
  class Element {
    constructor(tag="div",id=""){this.tagName=tag.toUpperCase();this.id=id;this.children=[];this.parentNode=null;this.dataset={};this.attributes={};this.listeners={};this.classList=new ClassList();this.textContent="";this.value="";this.disabled=false;this.open=false;}
    get firstChild(){return this.children[0]||null;}
    append(...children){children.forEach(child=>this.appendChild(child));}
    appendChild(child){child.parentNode=this;this.children.push(child);return child;}
    removeChild(child){const index=this.children.indexOf(child);if(index>=0)this.children.splice(index,1);child.parentNode=null;return child;}
    addEventListener(type,handler){(this.listeners[type]??=[]).push(handler);}
    dispatch(type,event={}){event.target??=this;for(const handler of this.listeners[type]||[])handler(event);}
    setAttribute(name,value){this.attributes[name]=String(value);}
    contains(node){for(let current=node;current;current=current.parentNode)if(current===this)return true;return false;}
    focus(){document.activeElement=this;}
    querySelectorAll(selector){const matches=[];const visit=node=>{for(const child of node.children){if(selector==="input"&&child.tagName==="INPUT")matches.push(child);else if(selector==="textarea"&&child.tagName==="TEXTAREA")matches.push(child);else if(selector==="button"&&child.tagName==="BUTTON")matches.push(child);else if(selector===".guide-edit-section"&&String(child.className||"").split(/\s+/).includes("guide-edit-section"))matches.push(child);else if(selector==="details[open]"&&child.tagName==="DETAILS"&&child.open)matches.push(child);visit(child);}};visit(this);return matches;}
  }
  document.createElement=tag=>new Element(tag);
  document.getElementById=id=>elements.get(id)||null;
  const add=(id,classes=[])=>{const node=new Element("div",id);node.classList=new ClassList(classes);elements.set(id,node);return node;};
  const view=add("guideView",["hidden"]);view.dataset.guideMode=editable?"editor":"readonly";
  for(const id of ["guideMeta","guideMessage","guideContent"])add(id);
  if(editable){add("guideEditor",["hidden"]);add("guideEdit");add("guideCancel");add("guideSave",["hidden"]);add("guideEditActions",["hidden"]);}
  if(withRefresh)add("guideRefresh");
  const window={addEventListener(type,handler){(windowListeners[type]??=[]).push(handler);}};
  window.window=window;
  const context={window,document,Intl,Date,Number,Math,Object,Error,AbortController,
    localStorage:{getItem(key){if(storageBlocked)throw Error("blocked");return storage.get(key)??null;},setItem(key,value){if(storageBlocked)throw Error("blocked");storage.set(key,value);}},
    fetch(url,options){if(!fetchImpl)throw new Error("fetchImpl missing");return fetchImpl(url,options);},
    setTimeout(fn){const id=++timerId;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);},console};
  Object.assign(window,context);
  vm.createContext(context);
  vm.runInContext(fs.readFileSync("web/shared/guide.js","utf8"),context);
  return {context,document,elements,timers,windowListeners,view,setFetch(fn){fetchImpl=fn;},runTimers(){for(const fn of [...timers.values()])fn();}};
}

const guideDocument=(title="标题")=>({revision:`rev-${title}`,updated_at:"2026-09-25T00:00:00Z",sections:[
  {id:"first",title:"第一类",topics:[{id:"first-topic",title,body:"第一段正文"}]},
  {id:"second",title:"第二类",topics:[{id:"second-topic",title:"第二条",body:"第二段正文"}]},
]});
const response=payload=>({ok:true,status:200,json:async()=>payload});
const abortError=()=>Object.assign(new Error("aborted"),{name:"AbortError"});
const settle=async()=>{for(let index=0;index<12;index+=1)await Promise.resolve();};

async function testReadTimeoutRecoveryAndReentry(){
  const h=createHarness({editable:false,withRefresh:false});
  h.view.classList.remove("hidden");
  let calls=0;
  h.setFetch((_url,options)=>{calls+=1;return new Promise((_resolve,reject)=>options.signal.addEventListener("abort",()=>reject(abortError())));});
  h.context.window.OptionsGuide.activate();
  assert.strictEqual(calls,1);
  h.runTimers();await settle();
  assert(h.elements.get("guideMessage").textContent.includes("请求超时"),"hanging GET must time out visibly");
  assert.strictEqual(h.timers.size,0,"GET timeout timer must be cleared");
  h.setFetch(async()=>{calls+=1;return response(guideDocument("恢复"));});
  for(const handler of h.windowListeners.online||[])handler();
  await settle();
  assert.strictEqual(calls,2,"online must retry a visible guide that never loaded successfully");
  h.context.window.OptionsGuide.activate();await settle();
  assert.strictEqual(calls,3,"non-editing guide reentry must revalidate an already loaded document");
}

async function testCorrectSectionFocus(){
  const h=createHarness();
  h.setFetch(async()=>response(guideDocument()));
  h.context.window.OptionsGuide.activate();await settle();
  h.elements.get("guideEdit").dispatch("click");
  let groups=h.elements.get("guideEditor").querySelectorAll(".guide-edit-section");
  const firstAdd=groups[0].querySelectorAll("button").find(node=>node.textContent==="新增条目");
  firstAdd.dispatch("click");
  groups=h.elements.get("guideEditor").querySelectorAll(".guide-edit-section");
  const firstInputs=groups[0].querySelectorAll("input"),secondInputs=groups[1].querySelectorAll("input");
  assert.strictEqual(h.document.activeElement,firstInputs[firstInputs.length-1],"new topic must focus its own section");
  assert.notStrictEqual(h.document.activeElement,secondInputs[secondInputs.length-1],"new topic focus leaked to the final section");
}

async function testSaveBodyTimeoutKeepsDraftWithoutRetry(){
  const h=createHarness();
  h.setFetch(async()=>response(guideDocument()));
  h.context.window.OptionsGuide.activate();await settle();
  h.elements.get("guideEdit").dispatch("click");
  const firstInput=h.elements.get("guideEditor").querySelectorAll("input")[0];
  firstInput.value="保留的修改";firstInput.dispatch("input");
  const requests=[];
  h.setFetch((_url,options)=>{requests.push(options);return Promise.resolve({ok:true,status:200,json:()=>new Promise((_resolve,reject)=>options.signal.addEventListener("abort",()=>reject(abortError()))) });});
  h.elements.get("guideSave").dispatch("click");
  assert.strictEqual(requests.length,1);
  await settle();
  h.runTimers();await settle();
  assert.strictEqual(h.elements.get("guideMessage").textContent,"保存结果尚未确认，草稿已保留。请另开本机页面核对已保存内容，不要刷新当前编辑页。","hanging PUT body must report an uncertain result, retained draft, and safe verification path");
  assert(!h.elements.get("guideEditor").classList.contains("hidden"),"save timeout must keep editing mode");
  assert.strictEqual(h.elements.get("guideSave").disabled,false);assert.strictEqual(h.elements.get("guideCancel").disabled,false);
  await settle();assert.strictEqual(requests.length,1,"timed-out PUT must not be retried automatically");
  h.setFetch(async(_url,options)=>{requests.push(options);return response(guideDocument("保留的修改"));});
  h.elements.get("guideSave").dispatch("click");await settle();
  assert.strictEqual(JSON.parse(requests[1].body).sections[0].topics[0].title,"保留的修改","manual retry must retain the draft");
}

async function testConflictKeepsDraft(){
  const h=createHarness();
  h.setFetch(async()=>response(guideDocument()));
  h.context.window.OptionsGuide.activate();await settle();
  h.elements.get("guideEdit").dispatch("click");
  const firstInput=h.elements.get("guideEditor").querySelectorAll("input")[0];
  firstInput.value="冲突时保留的修改";firstInput.dispatch("input");
  let requests=0;
  h.setFetch(async()=>{requests+=1;return{ok:false,status:409,json:async()=>({error:"revision conflict"})};});
  h.elements.get("guideSave").dispatch("click");await settle();
  assert.strictEqual(requests,1,"conflicted PUT must not retry automatically");
  assert.strictEqual(h.elements.get("guideMessage").textContent,"保存冲突：说明已被其他页面更新，草稿已保留。请另开本机页面读取最新版本，在新页面合并需要保留的修改后保存；不要刷新当前编辑页。","409 must explain the retained draft and safe merge path");
  assert.strictEqual(firstInput.value,"冲突时保留的修改","409 must leave the visible draft unchanged");
  assert(!h.elements.get("guideEditor").classList.contains("hidden"),"409 must keep editing mode visible");
  assert.strictEqual(h.elements.get("guideSave").disabled,false);assert.strictEqual(h.elements.get("guideCancel").disabled,false);
}

async function testRememberTopic(){
  const storage=new Map();
  const load=async options=>{const h=createHarness({editable:false,storage,...options});h.setFetch(async()=>response(guideDocument()));h.context.window.OptionsGuide.activate();await settle();return h;};
  let h=await load();let content=h.elements.get("guideContent"),first=content.children[0].children[1],second=content.children[1].children[1];
  first.open=true;first.dispatch("toggle");second.open=true;second.dispatch("toggle");first.dispatch("toggle");
  assert(!first.open&&second.open);assert.strictEqual(storage.get("btc-options-mobile-guide-topic"),JSON.stringify(["second","second-topic"]));
  h=await load();content=h.elements.get("guideContent");second=content.children[1].children[1];assert(second.open,"reload must restore the same topic");
  const oldSecond=second;h.context.window.OptionsGuide.activate();await settle();oldSecond.open=false;oldSecond.dispatch("toggle");assert.strictEqual(storage.get("btc-options-mobile-guide-topic"),JSON.stringify(["second","second-topic"]),"detached toggle must not clear saved topic");second=h.elements.get("guideContent").children[1].children[1];
  second.open=false;second.dispatch("toggle");h=await load();assert.strictEqual(h.elements.get("guideContent").querySelectorAll("details[open]").length,0,"closing topic must persist");
  storage.set("btc-options-mobile-guide-topic",'deleted-topic');h=await load();assert.strictEqual(h.elements.get("guideContent").querySelectorAll("details[open]").length,0);
  h=await load({storageBlocked:true});first=h.elements.get("guideContent").children[0].children[1];first.open=true;first.dispatch("toggle");assert(first.open);
}

async function main(){await testRememberTopic();await testReadTimeoutRecoveryAndReentry();await testCorrectSectionFocus();await testSaveBodyTimeoutKeepsDraftWithoutRetry();await testConflictKeepsDraft();console.log("Guide timeout, conflict recovery, draft and section focus: PASS");}
main().catch(error=>{console.error(error);process.exitCode=1;});

