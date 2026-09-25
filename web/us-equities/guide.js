"use strict";
(()=>{
  const view=document.getElementById("guideView");
  if(!view)return;
  const base=()=>{const match=(globalThis.location?.pathname||"").match(/^(.*)\/us-equities\/(?:desktop|mobile)\//);return match?match[1]:""};
  const mobile=()=>/\/us-equities\/mobile\/$/.test(globalThis.location?.pathname||"")||window.matchMedia?.("(max-width: 700px)").matches===true;
  const content=document.getElementById("guideContent"),meta=document.getElementById("guideMeta"),message=document.getElementById("guideMessage"),key="us-options-mobile-guide-open";
  let currentRevision=null,pendingPayload=null;
  const remembered=()=>{try{return localStorage.getItem(key)}catch(_){return null}};
  const remember=value=>{try{value?localStorage.setItem(key,value):localStorage.removeItem(key)}catch(_){}};
  const clear=node=>{while(node.firstChild)node.removeChild(node.firstChild)};
  const china=value=>value&&Number.isFinite(new Date(value).getTime())?new Intl.DateTimeFormat("zh-CN",{timeZone:"Asia/Shanghai",dateStyle:"medium",timeStyle:"short"}).format(new Date(value)):"—";
  const selecting=()=>{const selection=window.getSelection?.();return Boolean(selection&&!selection.isCollapsed&&content.contains(selection.anchorNode))};
  function render(payload){
    const openIds=new Set([...content.querySelectorAll("details[open]")].map(item=>item.dataset.guideTopic));clear(content);const openId=remembered();
    payload.sections.forEach(section=>{const group=document.createElement("section"),heading=document.createElement("h3");heading.textContent=section.title;group.appendChild(heading);section.topics.forEach(topic=>{const details=document.createElement("details"),summary=document.createElement("summary"),body=document.createElement("p"),id=`${section.id}:${topic.id}`;details.dataset.guideTopic=id;if(openIds.has(id)||(mobile()&&id===openId))details.open=true;summary.textContent=topic.title;body.textContent=topic.body;body.style.whiteSpace="pre-wrap";details.append(summary,body);details.addEventListener("toggle",()=>{if(!mobile())return;if(details.open){content.querySelectorAll("details[open]").forEach(other=>{if(other!==details)other.open=false});remember(id)}else if(remembered()===id)remember(null)});group.appendChild(details)});content.appendChild(group)});
    currentRevision=payload.revision;pendingPayload=null;
    meta.textContent=`个人文档 · ${payload.updated_at==="built-in"?"内置初稿":china(payload.updated_at)}`;
    message.textContent="公开面板只读；维护请使用本机管理页。";
  }
  async function load(showProgress=false){
    if(showProgress)message.textContent="正在读取个人文档…";
    try{
      const response=await fetch(`${base()}/api/v1/us-equities/options-guide`,{cache:"no-store"});
      const payload=await response.json();
      if(!response.ok)throw new Error(payload.error||`HTTP ${response.status}`);
      if(payload.revision===currentRevision){message.textContent="公开面板只读；维护请使用本机管理页。";return}
      if(selecting()){pendingPayload=payload;message.textContent="说明已更新；结束文字选择后自动显示最新版。";return}
      render(payload);
    }catch(error){message.textContent=`个人文档读取失败：${error.message}`}
  }
  document.getElementById("guideRefresh").onclick=()=>load(true);
  document.addEventListener("selectionchange",()=>{if(pendingPayload&&!selecting())render(pendingPayload)});
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)load()});
  window.addEventListener("us-guide-visible",()=>load());
  setInterval(()=>{if(!document.hidden)load()},5000);
  load(true);
})();
