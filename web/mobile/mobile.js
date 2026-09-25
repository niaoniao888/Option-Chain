"use strict";
const apiPath=path=>{const pathname=globalThis.location?.pathname||"",index=pathname.lastIndexOf("/bitcoin/");return `${index<0?"":pathname.slice(0,index)}${path}`;};

const state={snapshot:null,receivedPerf:0,selectedExpiry:null,expiryKey:"",selectedStrike:null,strikeKey:"",localError:null,activeCount:0,chainSignature:null,priceSignature:null,rankingSignature:null,contractsCache:null,generationKey:null,nextBoundaryPerf:Infinity,requestInFlight:false,pollTimer:null,pendingMarketUpdate:false,priceSide:"CALL",rankingSide:"CALL",rankingRange:"LT3",rankingSortKey:"annualized_pct",rankingSortDirection:"desc",rankingPage:1};
const interaction={pointerDown:false,pendingRender:false};
const $=id=>document.getElementById(id);
const setText=(id,value)=>{const node=$(id);if(node.textContent!==value)node.textContent=value;};
const fmt=(value,digits=2)=>Number.isFinite(value)?value.toLocaleString("zh-CN",{minimumFractionDigits:digits,maximumFractionDigits:digits}):"—";
const price=value=>Number.isFinite(value)&&value>0?fmt(value,value<10?4:2):"—";
const yieldText=value=>Number.isFinite(value)?`${fmt(value,2)}%`:"—";
const timeValueText=value=>!Number.isFinite(value)?"—":value===0?"0.00":Math.abs(value)<.01?`${value<0?"-":""}&lt;0.01`:fmt(value,2);
const markReference = contract => Number.isFinite(contract?.mark_annualized_pct) ? ` · Mark ${fmt(contract.mark_annualized_pct,1)}%` : "";
const contractAnnualContent=contract=>{if(contract?.open_interest===0)return"—";if(contract?.time_value_status==="negative")return'<span class="tv-warning">Bid &lt; 内在价值</span>';if(contract?.time_value_status==="zero"){const label="Bid = 内在价值";return`<span class="tv-warning">${label}<small>TV ${timeValueText(contract.time_value)}${markReference(contract)}</small></span>`;}return yieldText(contract?.annualized_pct);};
const contractPeriodContent = contract => OptionsPeriodReturn.render(contract, state.snapshot?.index_price);
const priceEligibleContract=contract=>contract.remaining_seconds>0&&contract.side===state.priceSide&&contract.time_value_status!=="negative" && contract.open_interest!==0 && Number.isFinite(contract.annualized_pct);
const probabilityText=contract=>{
  if(contract?.open_interest===0)return"—";
  if(contract?.probability_display_state==="settling")return"结算中";
  const value=contract?.exercise_probability_pct;
  if(!Number.isFinite(value))return"—";
  if(value<.1)return"&lt;0.1%";
  if(value>99.9)return"&gt;99.9%";
  return`${fmt(value,1)}%`;
};
const moneyText=value=>({OTM:"虚值",ITM:"实值",ATM:"平值"}[value]||"—");
const remainingText=seconds=>{
  if(!Number.isFinite(seconds))return"—";
  const safe=Math.max(0,seconds);
  if(safe>259200)return`${Math.floor(safe/86400)}天`;
  const completeHours=Math.floor(safe/3600);
  return`${Math.floor(completeHours/24)}天${completeHours%24}小时`;
};
const shanghai=(value,dateOnly=false)=>{
  if(value==null)return"—";
  const date=new Date(value);
  if(!Number.isFinite(date.getTime()))return"—";
  const parts=Object.fromEntries(new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",...(dateOnly?{}:{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false})}).formatToParts(date).filter(part=>part.type!=="literal").map(part=>[part.type,part.value]));
  const day=`${parts.year}-${parts.month}-${parts.day}`;
  return dateOnly?day:`${day} ${parts.hour}:${parts.minute}:${parts.second}`;
};
const dataTime=value=>{const formatted=shanghai(value);return formatted==="—"?formatted:formatted.slice(5);};

function setTheme(theme,persist=false){
  const selected=theme==="dark"?"dark":"light";
  document.documentElement.dataset.theme=selected;
  document.querySelector('meta[name="theme-color"]').content=selected==="dark"?"#101a2e":"#173763";
  document.querySelectorAll("[data-theme-choice]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.themeChoice===selected)));
  if(persist){try{localStorage.setItem("options-panel-theme",selected);}catch(_){}}
}
function initialTheme(){try{return localStorage.getItem("options-panel-theme")==="dark"?"dark":"light";}catch(_){return"light";}}
const MOBILE_UI_STATE_KEY="btc-options-mobile-ui-v1";
const priceSides=new Set(["CALL","PUT"]),rankingRanges=new Set(["LT3","3_7","7_30","30_60","GT60"]),rankingSortKeys=new Set(["expiry_ms","strike","period_return_pct","annualized_pct","exercise_probability_pct"]),rankingDirections=new Set(["asc","desc"]);
let rememberedExpiry=null,lastStrikeBySide={CALL:null,PUT:null},expiryRestorePending=false,strikeRestorePending={CALL:false,PUT:false},lastPersistedUiState=null;
const positiveNumber=value=>typeof value==="number"&&Number.isFinite(value)&&value>0?value:null;
function syncSegmented(id,value){$(id).querySelectorAll("button[data-value]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.value===value)));}
function mobileUiPayload(){return{selectedExpiry:rememberedExpiry,priceSide:state.priceSide,priceStrikes:{CALL:lastStrikeBySide.CALL,PUT:lastStrikeBySide.PUT},rankingSide:state.rankingSide,rankingRange:state.rankingRange,rankingSortKey:state.rankingSortKey,rankingSortDirection:state.rankingSortDirection,rankingPage:state.rankingPage};}
function persistMobileUiState(){const encoded=JSON.stringify(mobileUiPayload());if(encoded===lastPersistedUiState)return;try{localStorage.setItem(MOBILE_UI_STATE_KEY,encoded);lastPersistedUiState=encoded;}catch(_){}}
function restoreMobileUiState(){
  let saved=null;try{const raw=localStorage.getItem(MOBILE_UI_STATE_KEY);if(raw){saved=JSON.parse(raw);lastPersistedUiState=raw;}}catch(_){return;}
  if(!saved||typeof saved!=="object")return;
  rememberedExpiry=positiveNumber(saved.selectedExpiry);state.selectedExpiry=rememberedExpiry;
  if(priceSides.has(saved.priceSide))state.priceSide=saved.priceSide;
  if(saved.priceStrikes&&typeof saved.priceStrikes==="object")lastStrikeBySide={CALL:positiveNumber(saved.priceStrikes.CALL),PUT:positiveNumber(saved.priceStrikes.PUT)};
  state.selectedStrike=lastStrikeBySide[state.priceSide];
  if(priceSides.has(saved.rankingSide))state.rankingSide=saved.rankingSide;
  if(rankingRanges.has(saved.rankingRange))state.rankingRange=saved.rankingRange;
  if(rankingSortKeys.has(saved.rankingSortKey))state.rankingSortKey=saved.rankingSortKey;
  if(rankingDirections.has(saved.rankingSortDirection))state.rankingSortDirection=saved.rankingSortDirection;
  if(Number.isInteger(saved.rankingPage)&&saved.rankingPage>=1&&saved.rankingPage<=100000)state.rankingPage=saved.rankingPage;
  syncSegmented("priceSideFilter",state.priceSide);syncSegmented("sideFilter",state.rankingSide);syncSegmented("expiryRange",state.rankingRange);updateRankingSortHeaders();
}
restoreMobileUiState();
function nowMs(){return state.snapshot.server_time_ms+Math.max(0,performance.now()-state.receivedPerf);}
function contractsNow(){return state.contractsCache||rebuildContractsCache();}
function secondsToDisplayBoundary(seconds){if(!Number.isFinite(seconds)||seconds<=0)return Infinity;const unit=seconds>259200?86400:3600,remainder=seconds%unit;return remainder>.05?remainder:.05;}
function rebuildContractsCache(){const now=nowMs();let nextBoundarySeconds=Infinity;const contracts=state.snapshot.contracts.map(c=>{const seconds=Math.max(0,(c.expiry_ms-now)/1000);if(seconds>0){nextBoundarySeconds=Math.min(nextBoundarySeconds,seconds,secondsToDisplayBoundary(seconds));for(const boundaryDays of[60,30,7,3]){const untilBoundary=seconds-boundaryDays*86400;if(untilBoundary>=0)nextBoundarySeconds=Math.min(nextBoundarySeconds,Math.max(.05,untilBoundary));}if(Number.isFinite(c.exercise_probability_pct)&&seconds>1800)nextBoundarySeconds=Math.min(nextBoundarySeconds,seconds-1800);}const probabilityState=seconds<=0?"expired":(Number.isFinite(c.exercise_probability_pct)&&seconds<=1800?"settling":c.probability_display_state);return{...c,remaining_seconds:seconds,annualized_pct:seconds<=0?null:c.annualized_pct,period_return_pct:seconds<=0?null:c.period_return_pct,time_value_status:seconds<=0?"expired":c.time_value_status,mark_time_value:seconds<=0?null:c.mark_time_value,mark_annualized_pct:seconds<=0?null:c.mark_annualized_pct,annualized_unavailable_reason:seconds<=0?"expired":c.annualized_unavailable_reason,exercise_probability_pct:seconds<=0?null:c.exercise_probability_pct,probability_display_state:probabilityState};});state.contractsCache=contracts;state.nextBoundaryPerf=Number.isFinite(nextBoundarySeconds)?performance.now()+Math.max(0,nextBoundarySeconds*1000):Infinity;return contracts;}

function renderStatus(){
  const s=state.snapshot,elapsed=Math.max(0,performance.now()-state.receivedPerf)/1000;
  setText("indexPrice",fmt(s.index_price,0));
  setText("fetchedAt",s.fetched_at?dataTime(s.fetched_at):"尚无成功数据");
  setText("countdown",`${Math.max(0,Math.ceil(s.next_refresh_seconds-elapsed))} 秒`);
  const age=(Number.isFinite(s.status.age_seconds)?s.status.age_seconds:Infinity)+elapsed;
  const stale=age>=120,level=state.localError?"error":(stale&&s.status.status==="healthy"?"degraded":s.status.status);
  const labels={healthy:"正常",degraded:stale?"数据过期":"使用缓存",error:"错误"};
  const markOnly=Boolean(s.status.mark_warning)&&!stale&&!state.localError&&!s.status.market_error&&!s.status.catalog_error;
  setText("health",markOnly?"概率数据异常":(labels[level]||level));const healthClass=`pill ${level}`;if($("health").className!==healthClass)$("health").className=healthClass;
  const errors=[state.localError,s.status.market_error,s.status.catalog_error,s.status.mark_warning].filter(Boolean);
  if(stale&&s.fetched_at)errors.unshift(`行情已 ${Math.floor(age)} 秒未成功更新`);
  if(interaction.pendingRender&&state.pendingMarketUpdate)errors.push(interaction.pointerDown?"已获取新行情，操作结束后更新表格":"已获取新行情，取消文字选择后更新表格");
  setText("notice",errors.join("；"));$("notice").classList.toggle("hidden",!errors.length);
}

function renderExpiries(contracts){
  const values=[...new Set(contracts.filter(c=>c.remaining_seconds>0).map(c=>c.expiry_ms))].sort((a,b)=>a-b);
  if(expiryRestorePending&&state.selectedExpiry===null&&rememberedExpiry!==null)state.selectedExpiry=rememberedExpiry;
  if(!values.includes(state.selectedExpiry)){
    const cutoff=nowMs()+15*86400*1000;
    state.selectedExpiry=values.filter(expiry=>expiry<=cutoff).at(-1)??values[0]??null;
    if(values.length){expiryRestorePending=false;rememberedExpiry=state.selectedExpiry;persistMobileUiState();}else expiryRestorePending=true;
  }else expiryRestorePending=false;
  const duration=value=>{const hours=Math.max(0,(value-nowMs())/3600000);return hours<1?"不足1小时":hours<24?`${Math.floor(hours)}小时`:`${Math.floor(hours/24)}天`;};
  const key=`${values.map(value=>`${value}:${duration(value)}`).join(",")}|${state.selectedExpiry}`;
  if(key!==state.expiryKey){const menu=$("expiryMenu"),restoreFocus=!menu.classList.contains("hidden")&&menu.contains(document.activeElement);menu.innerHTML=values.map(value=>`<button type="button" role="option" data-expiry="${value}" aria-selected="${value===state.selectedExpiry}">${shanghai(value,true)}（剩余${duration(value)}）</button>`).join("")||'<span class="picker-empty">—</span>';$("expiryValue").textContent=state.selectedExpiry===null?"—":shanghai(state.selectedExpiry,true);state.expiryKey=key;if(!values.length){const wasOpen=!menu.classList.contains("hidden");closeExpiryMenu();if(wasOpen&&restoreFocus)$("expiryTrigger").focus?.();}else if(restoreFocus)focusSelectedOption(menu);}
}
function renderStrikes(contracts){
  const values=[...new Set(contracts.filter(priceEligibleContract).map(c=>c.strike))].sort((a,b)=>a-b);
  if(strikeRestorePending[state.priceSide]&&state.selectedStrike===null&&lastStrikeBySide[state.priceSide]!==null)state.selectedStrike=lastStrikeBySide[state.priceSide];
  const selectionChanged=!values.includes(state.selectedStrike);
  if(selectionChanged){
    const spot=state.snapshot.index_price;
    state.selectedStrike=values.length?(Number.isFinite(spot)&&spot>0?values.reduce((best,value)=>{const distance=Math.abs(value-spot),bestDistance=Math.abs(best-spot);return distance<bestDistance||(distance===bestDistance&&value<best)?value:best;}):values[0]):null;
    if(values.length){strikeRestorePending[state.priceSide]=false;lastStrikeBySide[state.priceSide]=state.selectedStrike;persistMobileUiState();}else strikeRestorePending[state.priceSide]=true;
  }else strikeRestorePending[state.priceSide]=false;
  const spot=state.snapshot.index_price;
  const relative=value=>Number.isFinite(spot)&&spot>0?(value/spot-1)*100:null;
  const label=value=>{const pct=relative(value);return Number.isFinite(pct)?`${fmt(value,0)}（${pct>0?"+":""}${fmt(pct,2)}%）`:fmt(value,0);};
  const tone=value=>{const pct=relative(value);return !Number.isFinite(pct)||pct===0?"neutral":pct>0?"positive":"negative";};
  const key=`${values.map(value=>`${label(value)}:${tone(value)}`).join(",")}|${state.selectedStrike}`;
  if(key!==state.strikeKey||selectionChanged){const menu=$("strikeMenu"),restoreFocus=!menu.classList.contains("hidden")&&menu.contains(document.activeElement);menu.innerHTML=values.map(value=>`<button type="button" role="option" data-strike="${value}" aria-selected="${value===state.selectedStrike}">${fmt(value,0)}<span class="strike-relative ${tone(value)}">${label(value).slice(fmt(value,0).length)}</span></button>`).join("")||'<span class="strike-empty">—</span>';$("strikeValue").textContent=state.selectedStrike===null?"—":fmt(state.selectedStrike,0);state.strikeKey=key;if(!values.length){const wasOpen=!menu.classList.contains("hidden");closeStrikeMenu();if(wasOpen&&restoreFocus)$("strikeTrigger").focus?.();}else if(restoreFocus)scrollSelectedStrikeOption();}
}
function closeStrikeMenu(){const menu=$("strikeMenu");menu.classList.add("hidden");$("strikeTrigger").setAttribute("aria-expanded","false");}
function closeExpiryMenu(){const menu=$("expiryMenu");menu.classList.add("hidden");$("expiryTrigger").setAttribute("aria-expanded","false");}
function placePickerMenu(menu,trigger,picker){const triggerRect=trigger.getBoundingClientRect(),pickerRect=picker.getBoundingClientRect(),viewportHeight=window.innerHeight||document.documentElement.clientHeight,below=Math.max(0,viewportHeight-triggerRect.bottom-8),above=Math.max(0,pickerRect.top-8),openUp=below<270&&above>below,available=openUp?above:below;menu.classList.toggle("open-up",openUp);menu.style.maxHeight=`${Math.max(0,Math.min(270,available-5))}px`;}
function focusSelectedOption(menu){const selected=menu.querySelector?.('button[aria-selected="true"]');if(!selected)return;const menuRect=menu.getBoundingClientRect(),optionRect=selected.getBoundingClientRect();menu.scrollTop=Math.max(0,menu.scrollTop+(optionRect.top-menuRect.top)-(menu.clientHeight-optionRect.height)/2);selected.focus?.();}
function toggleExpiryMenu(){const menu=$("expiryMenu"),opening=menu.classList.contains("hidden");if(!opening){closeExpiryMenu();return;}closeStrikeMenu();placePickerMenu(menu,$("expiryTrigger"),$("expiryPicker"));menu.classList.remove("hidden");$("expiryTrigger").setAttribute("aria-expanded","true");focusSelectedOption(menu);}
function handlePickerKeys(event,menuId,triggerId,closeMenu){const menu=$(menuId);if(event.key==="Escape"){closeMenu();$(triggerId).focus?.();event.preventDefault?.();return;}const buttons=[...menu.querySelectorAll("button")];if(!buttons.length||!["ArrowDown","ArrowUp","Home","End"].includes(event.key))return;event.preventDefault?.();const current=Math.max(0,buttons.indexOf(document.activeElement));const next=event.key==="Home"?0:event.key==="End"?buttons.length-1:event.key==="ArrowDown"?Math.min(buttons.length-1,current+1):Math.max(0,current-1);buttons[next].focus?.();}
function scrollSelectedStrikeOption(){const menu=$("strikeMenu"),selected=menu.querySelector?.('button[aria-selected="true"]');if(!selected)return;const menuRect=menu.getBoundingClientRect(),optionRect=selected.getBoundingClientRect();menu.scrollTop=Math.max(0,menu.scrollTop+(optionRect.top-menuRect.top)-(menu.clientHeight-optionRect.height)/2);selected.focus?.();}
function toggleStrikeMenu(){const menu=$("strikeMenu"),opening=menu.classList.contains("hidden");if(!opening){closeStrikeMenu();return;}closeExpiryMenu();const triggerRect=$("strikeTrigger").getBoundingClientRect(),pickerRect=$("strikePicker").getBoundingClientRect(),viewportHeight=window.innerHeight||document.documentElement.clientHeight,below=Math.max(0,viewportHeight-triggerRect.bottom-8),above=Math.max(0,pickerRect.top-8),openUp=below<270&&above>below,available=openUp?above:below;menu.classList.toggle("open-up",openUp);menu.style.maxHeight=`${Math.max(0,Math.min(270,available-5))}px`;menu.classList.remove("hidden");$("strikeTrigger").setAttribute("aria-expanded","true");scrollSelectedStrikeOption();}
function optionCells(contract,side){
  if(!contract)return'<td class="option-cell probability-column">—</td><td class="option-cell period-column">—</td><td class="option-cell annual-column">—</td>';
  const cls=(contract.moneyness||"").toLowerCase();
  const annual=contractAnnualContent(contract);
  const period=contractPeriodContent(contract);
  const annualCell=`<td class="option-cell annual-column ${cls}"><strong class="annual-only">${annual}</strong></td>`;
  const periodCell=`<td class="option-cell period-column ${cls}"><strong>${period}</strong></td>`;
  const probabilityCell=`<td class="option-cell probability-column ${cls}"><strong class="probability-line">${probabilityText(contract)}</strong></td>`;
  return side==="Call"?probabilityCell+periodCell+annualCell:annualCell+periodCell+probabilityCell;
}
function divider(spot){return`<tr class="spot-row"><td colspan="3"></td><td class="strike-cell"><span id="mobileSpot" class="spot-badge">现价 ${fmt(spot,0)}</span></td><td colspan="3"></td></tr>`;}
function renderChain(contracts){
  const selected=contracts.filter(c=>c.expiry_ms===state.selectedExpiry&&c.remaining_seconds>0),map=new Map();
  selected.forEach(c=>{if(!map.has(c.strike))map.set(c.strike,{});map.get(c.strike)[c.side]=c;});
  const entries=[...map.entries()].sort((a,b)=>a[0]-b[0]),spot=state.snapshot.index_price,valid=Number.isFinite(spot)&&spot>0,rows=[];
  if(valid&&entries.length&&spot<entries[0][0])rows.push(divider(spot));
  entries.forEach(([strike,sides],index)=>{const exact=valid&&strike===spot,relative=valid?(strike/spot-1)*100:null;rows.push(`<tr>${optionCells(sides.CALL,"Call")}<td class="strike-cell">${fmt(strike,0)}${relative==null?"":`<small class="${relative<0?"negative":"positive"}" title="行权价距 BTC/USDT 百分比">${relative>=0?"+":""}${fmt(relative,2)}%</small>`}${exact?`<span id="mobileSpot" class="spot-badge">现价 ${fmt(spot,0)}</span>`:""}</td>${optionCells(sides.PUT,"Put")}</tr>`);const next=entries[index+1]?.[0];if(valid&&!exact&&strike<spot&&next!=null&&next>spot)rows.push(divider(spot));});
  if(valid&&entries.length&&spot>entries[entries.length-1][0])rows.push(divider(spot));
  $("chainBody").innerHTML=rows.join("")||'<tr><td colspan="7">当前没有可展示合约</td></tr>';
  const remaining=state.selectedExpiry?(state.selectedExpiry-nowMs())/1000:null;
  $("expiryDetail").textContent=state.selectedExpiry?`到期时间：${shanghai(state.selectedExpiry).slice(0,16)}\n剩余 ${remainingText(remaining)}`:"没有未到期合约";
}

function expiryRangeMatches(seconds,range){if(!Number.isFinite(seconds)||seconds<=0)return false;const days=seconds/86400;if(range==="LT3")return days<3;if(range==="3_7")return days>=3&&days<7;if(range==="7_30")return days>=7&&days<30;if(range==="30_60")return days>=30&&days<=60;if(range==="GT60")return days>60;return false;}
function filteredRankingContracts(contracts){const side=state.rankingSide,range=state.rankingRange,key=state.rankingSortKey,direction=state.rankingSortDirection,rows=contracts.filter(c=>c.time_value_status==="positive"&&Number.isFinite(c.annualized_pct)&&expiryRangeMatches(c.remaining_seconds,range)&&c.side===side),sortableValue=c=>key==="exercise_probability_pct"&&c.probability_display_state==="settling"?null:c[key];return rows.sort((a,b)=>{const av=sortableValue(a),bv=sortableValue(b),am=av==null||typeof av==="number"&&!Number.isFinite(av),bm=bv==null||typeof bv==="number"&&!Number.isFinite(bv);if(am!==bm)return am?1:-1;if(!am){const comparison=typeof av==="string"?av.localeCompare(bv,"en"):av-bv;if(comparison)return direction==="asc"?comparison:-comparison;}return String(a.symbol).localeCompare(String(b.symbol),"en");});}
function rankingStrikeCell(c){const spot=state.snapshot.index_price,valid=Number.isFinite(spot)&&spot>0;if(!valid)return`<span>${fmt(c.strike,0)}</span><small class="rank-relative neutral">—</small>`;const relative=(c.strike/spot-1)*100,cls=Math.abs(relative)<1e-12?"neutral":relative>0?"positive":"negative";return`<span>${fmt(c.strike,0)}</span><small class="rank-relative ${cls}">${relative>=0?"+":""}${fmt(relative,2)}%</small>`;}
function updateRankingSortHeaders(){document.querySelectorAll("#rankingHead [data-sort]").forEach(button=>{const active=button.dataset.sort===state.rankingSortKey;button.closest("th").setAttribute("aria-sort",active?(state.rankingSortDirection==="asc"?"ascending":"descending"):"none");button.querySelector(".sort-arrow").textContent=active?(state.rankingSortDirection==="asc"?"▲":"▼"):"";});}
function paginationItems(current,total){if(total<=5)return Array.from({length:total},(_,index)=>index+1);const pages=new Set([1,total,current-1,current,current+1]);if(current<=2)pages.add(3);if(current>=total-1)pages.add(total-2);const sorted=[...pages].filter(page=>page>=1&&page<=total).sort((a,b)=>a-b),items=[];sorted.forEach((page,index)=>{if(index&&page-sorted[index-1]>1)items.push("ellipsis");items.push(page);});return items;}
function renderRanking(contracts){
  const rows=filteredRankingContracts(contracts);
  const emptyMarket=contracts.length===0,totalPages=Math.max(1,Math.ceil(rows.length/10)),previousPage=state.rankingPage;
  if(!emptyMarket){state.rankingPage=Math.min(Math.max(1,state.rankingPage),totalPages);if(state.rankingPage!==previousPage)persistMobileUiState();}
  const displayPage=emptyMarket?1:state.rankingPage,pageRows=rows.slice((displayPage-1)*10,displayPage*10);
  $("rankingCount").textContent=`合约：${rows.length}个`;
  $("rankingBody").innerHTML=pageRows.map(c=>`<tr><td class="compact-date">${shanghai(c.expiry_ms,true).replace("-","-<wbr>")}</td><td>${rankingStrikeCell(c)}</td><td>${contractPeriodContent(c)}</td><td class="yield">${yieldText(c.annualized_pct)}</td><td><strong class="probability-line">${probabilityText(c)}</strong></td></tr>`).join("")||'<tr><td colspan="5">没有符合条件且买一时间价值为正的合约</td></tr>';
  $("rankingPages").innerHTML=paginationItems(displayPage,totalPages).map(item=>item==="ellipsis"?'<span class="page-ellipsis" aria-hidden="true">…</span>':`<button type="button" data-page="${item}" ${item===displayPage?'aria-current="page"':""} aria-label="第 ${item} 页">${item}</button>`).join("");$("rankingPrev").disabled=emptyMarket||displayPage<=1;$("rankingNext").disabled=emptyMarket||displayPage>=totalPages;updateRankingSortHeaders();
}
function renderPriceYield(contracts){
  const side=state.priceSide;$("priceAnnualHead").innerHTML=`<span class="nowrap-label">${side==="CALL"?"Covered Call":"Sell Put"}</span><br>年化`;
  const rows=contracts.filter(c=>priceEligibleContract(c)&&c.strike===state.selectedStrike).sort((a,b)=>a.expiry_ms-b.expiry_ms).map(c=>`<tr><td class="compact-date">${shanghai(c.expiry_ms,true).replace("-","-<wbr>")}</td><td><strong>${contractAnnualContent(c)}</strong></td><td>${contractPeriodContent(c)}</td><td><strong class="probability-line">${probabilityText(c)}</strong></td><td class="remaining-time">${remainingText(c.remaining_seconds)}</td></tr>`);
  $("priceYieldBody").innerHTML=rows.join("")||`<tr><td colspan="5">当前行权价没有未到期的 ${side==="CALL"?"Call":"Put"} 合约</td></tr>`;
}
function pageHasTextSelection(){const selection=window.getSelection?.();if(!selection||selection.isCollapsed||selection.rangeCount===0||!String(selection))return false;return document.body.contains(selection.anchorNode)||document.body.contains(selection.focusNode);}
function renderingProtected(){return interaction.pointerDown||pageHasTextSelection();}
function tableGenerationSignature(contracts){const availability=contracts.map(c=>`${c.symbol}:${c.remaining_seconds>0?1:0}:${c.probability_display_state}:${remainingText(c.remaining_seconds)}`).join("|");return`${state.snapshot.fetched_at}|${state.snapshot.catalog_fetched_at}|${state.snapshot.index_price}|${availability}`;}
function filterSignature(){return[state.rankingSide,state.rankingRange,state.rankingSortKey,state.rankingSortDirection,state.rankingPage].join("|");}
function rankingResultSignature(contracts){return filteredRankingContracts(contracts).map(c=>c.symbol).join(",");}
function rankingSignatureFor(contracts){return`${tableGenerationSignature(contracts)}|${filterSignature()}|${rankingResultSignature(contracts)}`;}
function renderRankingControlChange(){if(!state.snapshot)return;const contracts=contractsNow();renderRanking(contracts);state.rankingSignature=rankingSignatureFor(contracts);}
function setRankingSort(key){const allowed=new Set(["symbol","expiry_ms","remaining_seconds","strike","period_return_pct","annualized_pct","exercise_probability_pct"]);if(!allowed.has(key))return;if(state.rankingSortKey===key)state.rankingSortDirection=state.rankingSortDirection==="asc"?"desc":"asc";else{state.rankingSortKey=key;state.rankingSortDirection="asc";}state.rankingPage=1;persistMobileUiState();renderRankingControlChange();}
function bindSegmentedFilter(id,stateKey){$(id).addEventListener("click",event=>{const button=event.target.closest("button[data-value]");if(!button||state[stateKey]===button.dataset.value)return;state[stateKey]=button.dataset.value;state.rankingPage=1;$(id).querySelectorAll("button[data-value]").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));persistMobileUiState();renderRankingControlChange();});}
function render(){if(!state.snapshot){if(state.localError){$("notice").textContent=state.localError;$("notice").classList.remove("hidden");$("health").textContent="错误";$("health").className="pill error";}return true;}if(renderingProtected()){interaction.pendingRender=true;renderStatus();return false;}interaction.pendingRender=false;state.pendingMarketUpdate=false;renderStatus();if(!state.contractsCache||performance.now()>=state.nextBoundaryPerf)rebuildContractsCache();const contracts=contractsNow();renderExpiries(contracts);renderStrikes(contracts);const base=tableGenerationSignature(contracts),chainSignature=`${base}|${state.selectedExpiry}`,priceSignature=`${base}|${state.selectedStrike}|${state.priceSide}`,rankingSignature=rankingSignatureFor(contracts);if(chainSignature!==state.chainSignature){renderChain(contracts);state.chainSignature=chainSignature;}else{const remaining=state.selectedExpiry?(state.selectedExpiry-nowMs())/1000:null;$("expiryDetail").textContent=state.selectedExpiry?`到期时间：${shanghai(state.selectedExpiry).slice(0,16)}\n剩余 ${remainingText(remaining)}`:"没有未到期合约";}if(priceSignature!==state.priceSignature){renderPriceYield(contracts);state.priceSignature=priceSignature;}if(rankingSignature!==state.rankingSignature){renderRanking(contracts);state.rankingSignature=rankingSignatureFor(contracts);}state.activeCount=contracts.filter(c=>c.remaining_seconds>0).length;return true;}
function renderLightweight(){if(!state.snapshot)return render();renderStatus();if(renderingProtected())return false;const remaining=state.selectedExpiry?(state.selectedExpiry-nowMs())/1000:null;$("expiryDetail").textContent=state.selectedExpiry?`到期时间：${shanghai(state.selectedExpiry).slice(0,16)}\n剩余 ${remainingText(remaining)}`:"没有未到期合约";return true;}
function flushPendingRender(){if(interaction.pendingRender&&!renderingProtected())render();}
function releasePointer(){interaction.pointerDown=false;setTimeout(flushPendingRender,0);}
function schedulePoll(delay=5000){if(state.pollTimer!==null)clearTimeout(state.pollTimer);state.pollTimer=setTimeout(load,delay);}
async function load(){if(state.requestInFlight)return;if(state.pollTimer!==null){clearTimeout(state.pollTimer);state.pollTimer=null;}state.requestInFlight=true;const controller=new AbortController(),timeoutId=setTimeout(()=>controller.abort(),4000);try{const response=await fetch(apiPath("/api/snapshot"),{cache:"no-store",signal:controller.signal});if(!response.ok)throw new Error(`HTTP ${response.status}`);const snapshot=await response.json(),generationKey=`${snapshot.market_generation_ms??snapshot.fetched_at}|${snapshot.catalog_fetched_at}`,generationChanged=generationKey!==state.generationKey;state.snapshot=snapshot;state.receivedPerf=performance.now();state.localError=null;if(generationChanged){state.generationKey=generationKey;state.contractsCache=null;state.pendingMarketUpdate=true;render();}else renderLightweight();}catch(error){state.localError=`行情服务连接失败：${error.message}`;renderLightweight();}finally{clearTimeout(timeoutId);state.requestInFlight=false;schedulePoll();}}
function resumePolling(){interaction.pointerDown=false;if(!state.requestInFlight){if(state.pollTimer!==null){clearTimeout(state.pollTimer);state.pollTimer=null;}load();}flushPendingRender();}

document.querySelectorAll("[data-theme-choice]").forEach(button=>button.addEventListener("click",()=>setTheme(button.dataset.themeChoice,true)));setTheme(initialTheme());
const mobileViews=["chain","price","ranking","guide"];
function initialView(){try{const view=localStorage.getItem("btc-options-mobile-view");return mobileViews.includes(view)?view:"chain";}catch(_){return "chain";}}
function activateView(view,persist=false){
  const selected=mobileViews.includes(view)?view:"chain";
  closeStrikeMenu();closeExpiryMenu();
  document.querySelectorAll(".tab").forEach(button=>button.classList.toggle("active",button.dataset.view===selected));
  mobileViews.forEach(name=>$(`${name}View`).classList.toggle("hidden",name!==selected));
  if(persist){try{localStorage.setItem("btc-options-mobile-view",selected);}catch(_){}}
  if(selected==="guide")window.OptionsGuide?.activate();
}
document.querySelectorAll(".tab").forEach(button=>button.addEventListener("click",()=>activateView(button.dataset.view,true)));
activateView(initialView());
$("expiryTrigger").addEventListener("click",toggleExpiryMenu);
$("expiryTrigger").addEventListener("keydown",event=>{if(event.key==="ArrowDown"&&$("expiryMenu").classList.contains("hidden")){event.preventDefault?.();toggleExpiryMenu();}});
$("expiryMenu").addEventListener("click",event=>{const button=event.target.closest("button[data-expiry]");if(!button)return;state.selectedExpiry=Number(button.dataset.expiry);rememberedExpiry=state.selectedExpiry;state.expiryKey="";persistMobileUiState();closeExpiryMenu();render();$("expiryTrigger").focus?.();});
$("expiryMenu").addEventListener("keydown",event=>handlePickerKeys(event,"expiryMenu","expiryTrigger",closeExpiryMenu));
$("strikeTrigger").addEventListener("click",toggleStrikeMenu);
$("strikeTrigger").addEventListener("keydown",event=>{if(event.key==="ArrowDown"&&$("strikeMenu").classList.contains("hidden")){event.preventDefault?.();toggleStrikeMenu();}});
$("strikeMenu").addEventListener("click",event=>{const button=event.target.closest("button[data-strike]");if(!button)return;state.selectedStrike=Number(button.dataset.strike);lastStrikeBySide[state.priceSide]=state.selectedStrike;persistMobileUiState();closeStrikeMenu();render();$("strikeTrigger").focus?.();});
$("strikeMenu").addEventListener("keydown",event=>handlePickerKeys(event,"strikeMenu","strikeTrigger",closeStrikeMenu));
$("priceSideFilter").addEventListener("click",event=>{const button=event.target.closest("button[data-value]");if(!button)return;closeStrikeMenu();if(state.priceSide===button.dataset.value)return;state.priceSide=button.dataset.value;state.selectedStrike=lastStrikeBySide[state.priceSide];state.strikeKey="";$("priceSideFilter").querySelectorAll("button[data-value]").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));persistMobileUiState();render();});
document.addEventListener("click",event=>{if(!$("strikePicker").contains?.(event.target))closeStrikeMenu();if(!$("expiryPicker").contains?.(event.target))closeExpiryMenu();});
document.addEventListener("keydown",event=>{if(event.key==="Escape"){closeStrikeMenu();closeExpiryMenu();}});
bindSegmentedFilter("sideFilter","rankingSide");
bindSegmentedFilter("expiryRange","rankingRange");
$("rankingHead").addEventListener("click",event=>{const button=event.target.closest("button[data-sort]");if(button)setRankingSort(button.dataset.sort);});
$("rankingPrev").addEventListener("click",()=>{if(state.rankingPage>1){state.rankingPage-=1;persistMobileUiState();renderRankingControlChange();}});
$("rankingNext").addEventListener("click",()=>{state.rankingPage+=1;persistMobileUiState();renderRankingControlChange();});
$("rankingPages").addEventListener("click",event=>{const button=event.target.closest("button[data-page]");if(!button)return;state.rankingPage=Number(button.dataset.page);persistMobileUiState();renderRankingControlChange();});
document.addEventListener("pointerdown",()=>{interaction.pointerDown=true;},true);
document.addEventListener("pointerup",releasePointer,true);
document.addEventListener("pointercancel",releasePointer,true);
document.addEventListener("pointermove",event=>{if(interaction.pointerDown&&event.buttons===0&&event.pointerType!=="touch")releasePointer();},true);
document.addEventListener("selectionchange",flushPendingRender,true);
window.addEventListener("blur",releasePointer);
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible")resumePolling();});
window.addEventListener("pageshow",resumePolling);
window.addEventListener("focus",resumePolling);
window.addEventListener("online",resumePolling);
load();setInterval(()=>{if(!state.snapshot)return;if(performance.now()>=state.nextBoundaryPerf)render();else renderLightweight();},1000);

