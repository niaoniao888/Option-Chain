"use strict";
fetch("./api/v1/modules",{cache:"no-store"}).then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json();}).then(modules=>{
  const root=document.getElementById("modules");root.textContent="";
  modules.forEach(item=>{const card=document.createElement("article"),title=document.createElement("h2"),text=document.createElement("p"),desktop=document.createElement("a"),mobile=document.createElement("a");title.textContent=item.title;text.textContent=`数据源：${item.provider}`;desktop.textContent="桌面版";desktop.href=item.desktop_path;mobile.textContent="手机版";mobile.href=item.mobile_path;card.append(title,text,desktop,document.createTextNode("　"),mobile);root.appendChild(card);});
}).catch(error=>{document.getElementById("modules").textContent=`模块读取失败：${error.message}`;});
