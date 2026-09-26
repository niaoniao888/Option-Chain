"use strict";
const apiPath=path=>{const pathname=globalThis.location?.pathname||"",index=pathname.lastIndexOf("/bitcoin/");return `${index<0?"":pathname.slice(0,index)}${path}`;};

const state = { snapshot: null, selectedExpiry: null, selectedStrike: null, strikeGroup: null, receivedPerf: 0, localError: null, expiryKey: null, strikeKey: null, activeCount: 0, chainSignature: null, priceSignature: null, rankingSignature: null, contractsCache: null, generationKey: null, nextBoundaryPerf: Infinity, requestInFlight: false, pollTimer: null, pendingMarketUpdate:false, priceSide:"CALL", rankingSide:"CALL", rankingRange:"LT3", rankingSortKey:"annualized_pct", rankingSortDirection:"desc", rankingPage:1 };
const interaction = {pointerDown:false, pendingRender:false};
const $ = (id) => document.getElementById(id);
const setText = (id,value) => {const node=$(id);if(node.textContent!==value)node.textContent=value;};
const fmtNum = (v, digits = 2) => Number.isFinite(v) ? v.toLocaleString("zh-CN", {minimumFractionDigits: digits, maximumFractionDigits: digits}) : "—";
const shanghai = (isoOrMs, dateOnly = false) => {
  if (isoOrMs == null) return "—";
  const date = new Date(isoOrMs);
  if (!Number.isFinite(date.getTime())) return "—";
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone:"Asia/Shanghai",year:"numeric",month:"2-digit",day:"2-digit",
    ...(dateOnly ? {} : {hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false}),
  }).formatToParts(date).filter(part=>part.type!=="literal").map(part=>[part.type,part.value]));
  const day = `${parts.year}-${parts.month}-${parts.day}`;
  return dateOnly ? day : `${day} ${parts.hour}:${parts.minute}:${parts.second}`;
};
const dataTime = isoOrMs => {
  const value = shanghai(isoOrMs);
  return value === "—" ? value : value.slice(5);
};
const moneyClass = (v) => (v || "").toLowerCase();
const yieldText = (v) => Number.isFinite(v) ? `${fmtNum(v, 2)}%` : "—";
const timeValueText = value => !Number.isFinite(value) ? "—" : (value === 0 ? "0.00" : (Math.abs(value) < 0.01 ? `${value < 0 ? "-" : ""}&lt;0.01` : fmtNum(value,2)));
const markReference = contract => Number.isFinite(contract?.mark_annualized_pct) ? ` · Mark ${fmtNum(contract.mark_annualized_pct,1)}%` : "";
const contractAnnualContent = contract => {
  if (contract?.open_interest === 0) return "—";
  if (contract?.time_value_status === "negative" || contract?.time_value_status === "zero") {
    const label=contract.time_value_status === "negative" ? "Bid &lt; 内在价值" : "Bid = 内在价值";
    return `<span class="tv-warning">${label}<small>TV ${timeValueText(contract.time_value)}${markReference(contract)}</small></span>`;
  }
  return yieldText(contract?.annualized_pct);
};
const contractPeriodContent = contract => OptionsPeriodReturn.render(contract, state.snapshot?.index_price);
const priceEligibleContract = contract => contract.remaining_seconds>0 && contract.side===state.priceSide && contract.time_value_status!=="negative" && contract.open_interest!==0 && Number.isFinite(contract.annualized_pct);
const probabilityText = (contract) => {
  if (contract?.open_interest === 0) return "—";
  if (contract?.probability_display_state === "settling") return "结算中";
  const value = contract?.exercise_probability_pct;
  if (!Number.isFinite(value)) return "—";
  if (value < 0.1) return "&lt;0.1%";
  if (value > 99.9) return "&gt;99.9%";
  return `${fmtNum(value, 1)}%`;
};
const remainingText = (seconds) => {
  if (!Number.isFinite(seconds)) return "—";
  const safe = Math.max(0, seconds);
  if (safe > 259200) return `${Math.floor(safe / 86400)}天`;
  const completeHours = Math.floor(safe / 3600);
  return `${Math.floor(completeHours / 24)}天${completeHours % 24}小时`;
};
const THEME_KEY = "options-panel-theme";

function applyTheme(theme, persist = false) {
  const selected = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = selected;
  document.querySelectorAll("[data-theme-choice]").forEach(button => {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === selected));
  });
  if (persist) {
    try { localStorage.setItem(THEME_KEY, selected); } catch (_) { /* Storage may be disabled. */ }
  }
}

function initialTheme() {
  try { return localStorage.getItem(THEME_KEY) === "dark" ? "dark" : "light"; }
  catch (_) { return "light"; }
}

function currentServerMs() {
  return state.snapshot.server_time_ms + Math.max(0, performance.now() - state.receivedPerf);
}

function currentContracts() {
  return state.contractsCache || rebuildContractsCache();
}

function secondsToDisplayBoundary(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return Infinity;
  const unit = seconds > 259200 ? 86400 : 3600;
  const remainder = seconds % unit;
  return remainder > 0.05 ? remainder : 0.05;
}

function rebuildContractsCache() {
  const now = currentServerMs();
  let nextBoundarySeconds = Infinity;
  const contracts = state.snapshot.contracts.map(c => {
    const seconds = Math.max(0, (c.expiry_ms - now) / 1000);
    if (seconds > 0) {
      nextBoundarySeconds = Math.min(nextBoundarySeconds, seconds, secondsToDisplayBoundary(seconds));
      for (const boundaryDays of [60,30,7,3]) {
        const untilBoundary = seconds - boundaryDays * 86400;
        if (untilBoundary >= 0) nextBoundarySeconds = Math.min(nextBoundarySeconds, Math.max(0.05, untilBoundary));
      }
      if (Number.isFinite(c.exercise_probability_pct) && seconds > 1800) nextBoundarySeconds = Math.min(nextBoundarySeconds, seconds - 1800);
    }
    const probabilityState = seconds <= 0 ? "expired" : (Number.isFinite(c.exercise_probability_pct) && seconds <= 1800 ? "settling" : c.probability_display_state);
    return {...c, remaining_seconds: seconds, annualized_pct: seconds <= 0 ? null : c.annualized_pct,
      period_return_pct: seconds <= 0 ? null : c.period_return_pct,
      time_value_status: seconds <= 0 ? "expired" : c.time_value_status,
      mark_time_value: seconds <= 0 ? null : c.mark_time_value,
      mark_annualized_pct: seconds <= 0 ? null : c.mark_annualized_pct,
      annualized_unavailable_reason: seconds <= 0 ? "expired" : c.annualized_unavailable_reason,
      exercise_probability_pct: seconds <= 0 ? null : c.exercise_probability_pct,
      probability_display_state: probabilityState};
  });
  state.contractsCache = contracts;
  state.nextBoundaryPerf = Number.isFinite(nextBoundarySeconds) ? performance.now() + Math.max(0, nextBoundarySeconds * 1000) : Infinity;
  return contracts;
}

function renderStatus(s) {
  setText("indexPrice",fmtNum(s.index_price, 0));
  setText("fetchedAt",s.fetched_at ? dataTime(s.fetched_at) : "尚无成功数据");
  const elapsed = Math.floor(Math.max(0, performance.now() - state.receivedPerf) / 1000);
  setText("countdown",`${Math.max(0, s.next_refresh_seconds - elapsed)} 秒`);
  const baseAge = Number.isFinite(s.status.age_seconds) ? s.status.age_seconds : Infinity;
  const localAge = baseAge + Math.max(0, performance.now() - state.receivedPerf) / 1000;
  const localStale = localAge >= 120;
  const statusError=["degraded","error"].includes(s.status.status)||localStale||Boolean(state.localError||s.status.market_error||s.status.catalog_error||s.status.mark_warning);
  const statusHealthy=s.status.status==="healthy"&&!statusError;
  setText("health",statusHealthy?"正常":statusError?"异常":"等待");
  const healthClass=`pill${statusHealthy?" healthy":statusError?" error":""}`;if($("health").className!==healthClass)$("health").className=healthClass;
  const errors = [s.status.market_error, s.status.catalog_error, s.status.mark_warning].filter(Boolean);
  if (state.localError) errors.unshift(state.localError);
  if (localStale && s.fetched_at) errors.unshift(`行情已超过 ${Math.floor(localAge)} 秒未成功更新`);
  if(interaction.pendingRender&&state.pendingMarketUpdate)errors.push(interaction.pointerDown?"已获取新行情，操作结束后更新表格":"已获取新行情，取消文字选择后更新表格");
  setText("notice",errors.join("；"));
  $("notice").classList.toggle("hidden", errors.length === 0);
}

function renderExpiryOptions(contracts) {
  const expiries = [...new Set(contracts.filter(c => c.remaining_seconds > 0).map(c => c.expiry_ms))].sort((a,b)=>a-b);
  const selectionChanged = !expiries.includes(state.selectedExpiry);
  if (selectionChanged) {
    const cutoff = currentServerMs() + 15 * 86400 * 1000;
    state.selectedExpiry = expiries.filter(expiry => expiry <= cutoff).at(-1) ?? expiries[0] ?? null;
  }
  const key = expiries.join(",");
  if (state.expiryKey !== key || selectionChanged) {
    $("expiryButtons").innerHTML = expiries.map(ms=>`<button type="button" data-expiry="${ms}" aria-pressed="${ms===state.selectedExpiry}">${shanghai(ms,true)}</button>`).join("") || '<span class="expiry-empty">—</span>';
    state.expiryKey = key;
  }
}

function renderStrikeOptions(contracts) {
  const strikes = [...new Set(contracts.filter(priceEligibleContract).map(c => c.strike))].sort((a,b)=>a-b);
  const spot = state.snapshot.index_price;
  const validSpot = Number.isFinite(spot) && spot > 0;
  const selectionChanged = !strikes.includes(state.selectedStrike);
  if (selectionChanged) {
    state.selectedStrike = strikes.length
      ? (validSpot
        ? strikes.reduce((best, value) => {
            const distance=Math.abs(value-spot), bestDistance=Math.abs(best-spot);
            return distance<bestDistance || (distance===bestDistance && value<best) ? value : best;
          })
        : strikes[0])
      : null;
  }
  const groups=[...new Set(strikes.map(strikeGroupFor))];
  if(!groups.includes(state.strikeGroup)||selectionChanged)state.strikeGroup=state.selectedStrike===null?groups[0]||null:strikeGroupFor(state.selectedStrike);
  setText("currentStrike",state.selectedStrike===null?"—":fmtNum(state.selectedStrike,0));
  const currentLabel=$("currentStrikeLabel"),currentTone=!validSpot||!Number.isFinite(state.selectedStrike)||state.selectedStrike===spot?"neutral":state.selectedStrike<spot?"below":"above";
  const currentClass=`current-strike ${currentTone}-spot`;if(currentLabel.className!==currentClass)currentLabel.className=currentClass;
  const groupStrikes=strikes.filter(value=>strikeGroupFor(value)===state.strikeGroup);
  const membership=validSpot?groupStrikes.map(value=>value<spot?"L":value===spot?"E":"H").join(""):"N";
  const key = `${strikes.join(",")}|${state.strikeGroup}|${state.selectedStrike}|${membership}`;
  if (state.strikeKey !== key || selectionChanged) {
    $("strikeGroupButtons").innerHTML=groups.map(value=>`<button type="button" data-strike-group="${value}" aria-pressed="${value===state.strikeGroup}">${fmtNum(value/10000,0)}万</button>`).join("")||'<span class="strike-empty">—</span>';
    const strikeButton=(value,relation,label=fmtNum(value,0))=>`<button type="button" class="strike-${relation}" data-strike="${value}" aria-pressed="${value===state.selectedStrike}"${relation==="at"?` aria-label="平值 ${fmtNum(value,0)}"`:""}>${label}</button>`;
    if(validSpot){
      const below=groupStrikes.filter(value=>value<spot).map(value=>strikeButton(value,"below"));
      const at=groupStrikes.filter(value=>value===spot).map(value=>strikeButton(value,"at",`${fmtNum(value,0)} · 平值`));
      const above=groupStrikes.filter(value=>value>spot).map(value=>strikeButton(value,"above"));
      $("strikeButtons").innerHTML=`<div class="strike-option-row strike-below-row"><span class="strike-row-label">${at.length?"低于 / 等于现价":"低于现价"}</span><div class="strike-option-list">${below.concat(at).join("")||'<span class="strike-empty">—</span>'}</div></div><div class="strike-option-row strike-above-row"><span class="strike-row-label">高于现价</span><div class="strike-option-list">${above.join("")||'<span class="strike-empty">—</span>'}</div></div>`;
    }else{
      $("strikeButtons").innerHTML=`<div class="strike-option-row strike-neutral-row"><span class="strike-row-label">行权价</span><div class="strike-option-list">${groupStrikes.map(value=>strikeButton(value,"neutral")).join("")||'<span class="strike-empty">—</span>'}</div></div>`;
    }
    state.strikeKey = key;
  }
}

function strikeGroupFor(value){return Math.floor(Number(value)/10000)*10000;}

function renderExpiryDetail() {
  const remaining = state.selectedExpiry ? (state.selectedExpiry-currentServerMs())/1000 : null;
  $("expiryDetail").textContent = state.selectedExpiry
    ? `到期时间：${shanghai(state.selectedExpiry).slice(0,16)} · 剩余 ${remainingText(remaining)}`
    : "没有未到期合约";
}

function contractCells(c, side) {
  if (!c) return `<td class="${side}-side probability-column side-empty">—</td><td class="${side}-side period-column side-empty">—</td><td class="${side}-side annual-column side-empty">—</td>`;
  const annual = contractAnnualContent(c);
  const period = contractPeriodContent(c);
  const probability = `<strong class="probability-line">${probabilityText(c)}</strong>`;
  const annualCell = `<td class="${side}-side annual-column ${moneyClass(c.moneyness)}"><strong class="yield">${annual}</strong></td>`;
  const periodCell = `<td class="${side}-side period-column ${moneyClass(c.moneyness)}"><strong>${period}</strong></td>`;
  const probabilityCell = `<td class="${side}-side probability-column ${moneyClass(c.moneyness)}">${probability}</td>`;
  return side === "call" ? probabilityCell + periodCell + annualCell : annualCell + periodCell + probabilityCell;
}

function spotDivider(spot) {
  return `<tr class="spot-divider"><td class="call-side divider-line"></td><td class="call-side divider-line"></td><td class="call-side divider-line"></td><td class="strike-cell"><span id="spotMarker" class="spot-badge">现价 <b>${fmtNum(spot,0)}</b></span></td><td class="put-side divider-line"></td><td class="put-side divider-line"></td><td class="put-side divider-line"></td></tr>`;
}

function strikeCell(strike, spot, atSpot) {
  const validSpot = Number.isFinite(spot) && spot > 0;
  const relative = validSpot ? (strike / spot - 1) * 100 : null;
  const position = !validSpot ? "no-spot" : (atSpot ? "at-spot" : (strike < spot ? "below-spot" : "above-spot"));
  const relativeClass = relative == null || Math.abs(relative) < 1e-12 ? "relative-flat" : (relative < 0 ? "relative-negative" : "relative-positive");
  const relativeText = relative == null ? "" : `<span class="strike-relative ${relativeClass}" title="行权价距当前 BTC/USDT 的百分比，不是年化收益率">${relative>=0?"+":""}${fmtNum(relative,2)}%</span>`;
  const marker = atSpot ? `<span id="spotMarker" class="spot-badge inline">现价 <b>${fmtNum(spot,0)}</b></span>` : "";
  return `<td class="strike-cell ${position}"><span class="strike-value">${fmtNum(strike,0)}</span>${relativeText}${marker}</td>`;
}

function renderChain(contracts) {
  const selected = contracts.filter(c => c.expiry_ms === state.selectedExpiry && c.remaining_seconds > 0);
  const byStrike = new Map();
  for (const c of selected) {
    if (!byStrike.has(c.strike)) byStrike.set(c.strike, {});
    byStrike.get(c.strike)[c.side] = c;
  }
  const entries = [...byStrike.entries()].sort((a,b)=>a[0]-b[0]);
  const spot = state.snapshot.index_price;
  const validSpot = Number.isFinite(spot) && spot > 0;
  const rows = [];
  if (validSpot && entries.length && spot < entries[0][0]) rows.push(spotDivider(spot));
  entries.forEach(([strike,sides], index) => {
    const call = sides.CALL, put = sides.PUT;
    const atSpot = validSpot && strike === spot;
    rows.push(`<tr class="data-row">${contractCells(call,"call")}${strikeCell(strike,spot,atSpot)}${contractCells(put,"put")}</tr>`);
    const nextStrike = entries[index+1]?.[0];
    if (validSpot && !atSpot && strike < spot && nextStrike != null && nextStrike > spot) rows.push(spotDivider(spot));
  });
  if (validSpot && entries.length && spot > entries[entries.length-1][0]) rows.push(spotDivider(spot));
  $("chainBody").innerHTML = rows.join("") || '<tr><td colspan="7" class="empty">当前到期日没有可展示的活跃合约</td></tr>';
  renderExpiryDetail();
}

function expiryRangeMatches(seconds, range) {
  if (!Number.isFinite(seconds) || seconds <= 0) return false;
  const days = seconds / 86400;
  if (range === "LT3") return days < 3;
  if (range === "3_7") return days >= 3 && days < 7;
  if (range === "7_30") return days >= 7 && days < 30;
  if (range === "30_60") return days >= 30 && days <= 60;
  if (range === "GT60") return days > 60;
  return false;
}

function filteredRankingContracts(contracts) {
  const side=state.rankingSide, range=state.rankingRange, key=state.rankingSortKey, direction=state.rankingSortDirection;
  const rows=contracts.filter(c=>c.time_value_status==="positive" && Number.isFinite(c.annualized_pct) && expiryRangeMatches(c.remaining_seconds,range) && c.side===side);
  const sortableValue = contract => key === "exercise_probability_pct" && contract.probability_display_state === "settling" ? null : contract[key];
  return rows.sort((a,b)=>{
    const av=sortableValue(a), bv=sortableValue(b), aMissing=av==null||typeof av==="number"&&!Number.isFinite(av), bMissing=bv==null||typeof bv==="number"&&!Number.isFinite(bv);
    if(aMissing!==bMissing)return aMissing?1:-1;
    if(!aMissing){const comparison=typeof av==="string"?av.localeCompare(bv,"en"):av-bv;if(comparison)return direction==="asc"?comparison:-comparison;}
    return String(a.symbol).localeCompare(String(b.symbol),"en");
  });
}

function rankingStrikeCell(contract) {
  const spot=state.snapshot.index_price, valid=Number.isFinite(spot)&&spot>0;
  if(!valid)return `<span>${fmtNum(contract.strike,0)}</span><small class="rank-relative relative-flat">—</small>`;
  const relative=(contract.strike/spot-1)*100, cls=Math.abs(relative)<1e-12?"relative-flat":relative>0?"relative-positive":"relative-negative";
  return `<span>${fmtNum(contract.strike,0)}</span><small class="rank-relative ${cls}">${relative>=0?"+":""}${fmtNum(relative,2)}%</small>`;
}

function updateRankingSortHeaders() {
  document.querySelectorAll("#rankingHead [data-sort]").forEach(button=>{
    const active=button.dataset.sort===state.rankingSortKey;
    button.closest("th").setAttribute("aria-sort",active?(state.rankingSortDirection==="asc"?"ascending":"descending"):"none");
    button.querySelector(".sort-arrow").textContent=active?(state.rankingSortDirection==="asc"?"▲":"▼"):"";
  });
}

function paginationItems(current,total){
  if(total<=5)return Array.from({length:total},(_,index)=>index+1);
  const pages=new Set([1,total,current-1,current,current+1]);
  if(current<=2)pages.add(3);
  if(current>=total-1)pages.add(total-2);
  const sorted=[...pages].filter(page=>page>=1&&page<=total).sort((a,b)=>a-b),items=[];
  sorted.forEach((page,index)=>{if(index&&page-sorted[index-1]>1)items.push("ellipsis");items.push(page);});
  return items;
}

function renderRanking(contracts) {
  const rows=filteredRankingContracts(contracts);
  const totalPages=Math.max(1,Math.ceil(rows.length/10));
  state.rankingPage=Math.min(Math.max(1,state.rankingPage),totalPages);
  const pageRows=rows.slice((state.rankingPage-1)*10,state.rankingPage*10);
  $("rankingBody").innerHTML = pageRows.map(c=>`<tr><td>${shanghai(c.expiry_ms,true)}</td><td>${rankingStrikeCell(c)}</td><td>${contractPeriodContent(c)}</td><td class="yield">${yieldText(c.annualized_pct)}</td><td><strong class="probability-line">${probabilityText(c)}</strong></td></tr>`).join("") || '<tr><td colspan="5" class="empty">没有符合条件且买一时间价值为正的合约</td></tr>';
  $("rankingPages").innerHTML=paginationItems(state.rankingPage,totalPages).map(item=>item==="ellipsis"?'<span class="page-ellipsis" aria-hidden="true">…</span>':`<button type="button" data-page="${item}" ${item===state.rankingPage?'aria-current="page"':""} aria-label="第 ${item} 页">${item}</button>`).join("");
  $("rankingPrev").disabled=state.rankingPage<=1;
  $("rankingNext").disabled=state.rankingPage>=totalPages;
  updateRankingSortHeaders();
}

function renderPriceYield(contracts) {
  const side=state.priceSide;
  $("priceAnnualHead").innerHTML=`<span class="nowrap-label">${side==="CALL"?"Covered Call":"Sell Put"}</span><br>年化`;
  const rows=contracts.filter(c=>priceEligibleContract(c)&&c.strike===state.selectedStrike)
    .sort((a,b)=>a.expiry_ms-b.expiry_ms).map(c=>`<tr><td>${shanghai(c.expiry_ms,true)}</td><td><strong class="yield">${contractAnnualContent(c)}</strong></td><td>${contractPeriodContent(c)}</td><td><strong class="probability-line">${probabilityText(c)}</strong></td><td class="remaining-time">${remainingText(c.remaining_seconds)}</td></tr>`);
  $("priceYieldBody").innerHTML=rows.join("")||`<tr><td colspan="5" class="empty">当前行权价没有未到期的 ${side==="CALL"?"Call":"Put"} 合约</td></tr>`;
}

function pageHasTextSelection() {
  const selection = window.getSelection?.();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0 || !String(selection)) return false;
  return document.body.contains(selection.anchorNode) || document.body.contains(selection.focusNode);
}

function renderingProtected() {
  return interaction.pointerDown || pageHasTextSelection();
}

function tableGenerationSignature(contracts) {
  const availability = contracts.map(c=>`${c.symbol}:${c.remaining_seconds>0?1:0}:${c.probability_display_state}:${remainingText(c.remaining_seconds)}`).join("|");
  return `${state.snapshot.fetched_at}|${state.snapshot.catalog_fetched_at}|${state.snapshot.index_price}|${availability}`;
}

function filterSignature() {
  return [state.rankingSide,state.rankingRange,state.rankingSortKey,state.rankingSortDirection,state.rankingPage].join("|");
}

function rankingResultSignature(contracts) {
  return filteredRankingContracts(contracts).map(c=>c.symbol).join(",");
}

function rankingSignatureFor(contracts){return `${tableGenerationSignature(contracts)}|${filterSignature()}|${rankingResultSignature(contracts)}`;}

function renderRankingControlChange(){if(!state.snapshot)return;const contracts=currentContracts();renderRanking(contracts);state.rankingSignature=rankingSignatureFor(contracts);}

function setRankingSort(key){
  const allowed=new Set(["symbol","expiry_ms","remaining_seconds","strike","period_return_pct","annualized_pct","exercise_probability_pct"]);
  if(!allowed.has(key))return;
  if(state.rankingSortKey===key)state.rankingSortDirection=state.rankingSortDirection==="asc"?"desc":"asc";
  else{state.rankingSortKey=key;state.rankingSortDirection="asc";}
  state.rankingPage=1;
  renderRankingControlChange();
}

function bindSegmentedFilter(id,stateKey){
  $(id).addEventListener("click",event=>{
    const button=event.target.closest("button[data-value]");
    if(!button||state[stateKey]===button.dataset.value)return;
    state[stateKey]=button.dataset.value;
    state.rankingPage=1;
    $(id).querySelectorAll("button[data-value]").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));
    renderRankingControlChange();
  });
}

function render() {
  if (!state.snapshot) {
    if (state.localError) {
      $("notice").textContent=state.localError;
      $("notice").classList.remove("hidden");
      $("health").textContent="错误 / 无法连接";
      $("health").className="pill error";
    }
    return true;
  }
  if (renderingProtected()) { interaction.pendingRender = true; renderStatus(state.snapshot); return false; }
  interaction.pendingRender = false;
  state.pendingMarketUpdate=false;
  renderStatus(state.snapshot);
  if (!state.contractsCache || performance.now() >= state.nextBoundaryPerf) rebuildContractsCache();
  const contracts = currentContracts();
  renderExpiryOptions(contracts);
  renderStrikeOptions(contracts);
  const baseSignature = tableGenerationSignature(contracts);
  const chainSignature = `${baseSignature}|${state.selectedExpiry}`;
  const priceSignature = `${baseSignature}|${state.selectedStrike}|${state.priceSide}`;
  const rankingSignature = rankingSignatureFor(contracts);
  if (chainSignature !== state.chainSignature) { renderChain(contracts); state.chainSignature = chainSignature; }
  else renderExpiryDetail();
  if (priceSignature !== state.priceSignature) { renderPriceYield(contracts); state.priceSignature = priceSignature; }
  if (rankingSignature !== state.rankingSignature) { renderRanking(contracts); state.rankingSignature = rankingSignatureFor(contracts); }
  state.activeCount = contracts.filter(c=>c.remaining_seconds>0).length;
  return true;
}

function renderLightweight() {
  if (!state.snapshot) return render();
  renderStatus(state.snapshot);
  if (renderingProtected()) return false;
  renderExpiryDetail();
  return true;
}

function flushPendingRender() {
  if (interaction.pendingRender && !renderingProtected()) render();
}

function releasePointer() {
  interaction.pointerDown = false;
  setTimeout(flushPendingRender, 0);
}

function schedulePoll(delay=5000){
  if(state.pollTimer!==null)clearTimeout(state.pollTimer);
  state.pollTimer=setTimeout(loadSnapshot,delay);
}

async function loadSnapshot() {
  if (state.requestInFlight) return;
  if(state.pollTimer!==null){clearTimeout(state.pollTimer);state.pollTimer=null;}
  state.requestInFlight = true;
  const controller=new AbortController();
  const timeoutId=setTimeout(()=>controller.abort(),4000);
  try {
    const response=await fetch(apiPath("/api/snapshot"),{cache:"no-store",signal:controller.signal});
    if(!response.ok) throw new Error(`HTTP ${response.status}`);
    const snapshot=await response.json();
    const generationKey=`${snapshot.market_generation_ms ?? snapshot.fetched_at}|${snapshot.catalog_fetched_at}`;
    const generationChanged=generationKey!==state.generationKey;
    state.snapshot=snapshot;
    state.receivedPerf=performance.now();
    state.localError=null;
    if(generationChanged){state.generationKey=generationKey;state.contractsCache=null;state.pendingMarketUpdate=true;render();}
    else renderLightweight();
  } catch(error) {
    state.localError=`无法读取本地缓存：${error.message}`;
    renderLightweight();
  } finally {
    clearTimeout(timeoutId);
    state.requestInFlight=false;
    schedulePoll();
  }
}

function resumePolling(){
  interaction.pointerDown=false;
  if(!state.requestInFlight){
    if(state.pollTimer!==null){clearTimeout(state.pollTimer);state.pollTimer=null;}
    loadSnapshot();
  }
  flushPendingRender();
}

document.querySelectorAll(".tab").forEach(button=>button.addEventListener("click",()=>{
  document.querySelectorAll(".tab").forEach(b=>b.classList.toggle("active",b===button));
  ["chain","price","ranking"].forEach(view=>$(view+"View").classList.toggle("hidden",button.dataset.view!==view));
}));
document.querySelectorAll("[data-theme-choice]").forEach(button=>button.addEventListener("click",()=>applyTheme(button.dataset.themeChoice,true)));
applyTheme(initialTheme());
$("expiryButtons").addEventListener("click",event=>{
  const button=event.target.closest("button[data-expiry]");
  if (!button) return;
  state.selectedExpiry=Number(button.dataset.expiry);
  $("expiryButtons").querySelectorAll("button").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));
  render();
});
$("strikeButtons").addEventListener("click",event=>{const button=event.target.closest("button[data-strike]");if(!button)return;state.selectedStrike=Number(button.dataset.strike);$("strikeButtons").querySelectorAll("button[data-strike]").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));render();});
$("strikeGroupButtons").addEventListener("click",event=>{const button=event.target.closest("button[data-strike-group]");if(!button||state.strikeGroup===Number(button.dataset.strikeGroup))return;state.strikeGroup=Number(button.dataset.strikeGroup);state.strikeKey="";render();});
$("priceSideFilter").addEventListener("click",event=>{const button=event.target.closest("button[data-value]");if(!button||state.priceSide===button.dataset.value)return;state.priceSide=button.dataset.value;$("priceSideFilter").querySelectorAll("button[data-value]").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));render();});
bindSegmentedFilter("sideFilter","rankingSide");
bindSegmentedFilter("expiryRange","rankingRange");
$("rankingHead").addEventListener("click",event=>{const button=event.target.closest("button[data-sort]");if(button)setRankingSort(button.dataset.sort);});
$("rankingPrev").addEventListener("click",()=>{if(state.rankingPage>1){state.rankingPage-=1;renderRankingControlChange();}});
$("rankingNext").addEventListener("click",()=>{state.rankingPage+=1;renderRankingControlChange();});
$("rankingPages").addEventListener("click",event=>{const button=event.target.closest("button[data-page]");if(!button)return;state.rankingPage=Number(button.dataset.page);renderRankingControlChange();});
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
loadSnapshot();
setInterval(()=>{
  if (!state.snapshot) return;
  if(performance.now()>=state.nextBoundaryPerf) render();
  else renderLightweight();
},1000);

