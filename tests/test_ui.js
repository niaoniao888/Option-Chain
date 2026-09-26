"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

async function harness(path, rememberedView=null, storageBlocked=false, rememberedUi=null) {
  const stored=new Map([["btc-options-mobile-view",rememberedView]]);if(rememberedUi!==null)stored.set("btc-options-mobile-ui-v1",typeof rememberedUi==="string"?rememberedUi:JSON.stringify(rememberedUi));let guideActivations=0,storageWrites=0;
  const isMobile=path.endsWith("mobile.js");
  let now = 0;
  let fetchCalls = 0;
  let resolveFetch;
  let lastSignal;
  let timerId = 0;
  let selectedStrikeOptionFocused = false;
  let selectedExpiryOptionFocused = false;
  const timers = new Map();
  let selection = {isCollapsed:true, rangeCount:0, toString(){return "";}, anchorNode:null, focusNode:null};
  const nodes = new Map();
  const documentListeners = {};
  const windowListeners = {};
  const bodyNode = {};
  const body = {contains(node){return node === bodyNode;}};
  function element(id) {
    if (!nodes.has(id)) {
      let html = "";
      const classes = new Set((id.endsWith("View") && id !== "chainView") || id === "strikeMenu" || id === "expiryMenu" ? ["hidden"] : []);
      nodes.set(id, {
        id, value:"", textContent:"", className:"", mutations:0, listeners:{}, attributes:{}, focused:false,style:{},
        classList:{contains(value){return classes.has(value);},toggle(value,force){force ? classes.add(value) : classes.delete(value);},add(value){classes.add(value);},remove(value){classes.delete(value);}},
        addEventListener(type,handler){this.listeners[type]=handler;}, setAttribute(name,value){this.attributes[name]=String(value);}, querySelectorAll(){return[]},contains(node){return node===this},focus(){this.focused=true;},
        get innerHTML(){return html;}, set innerHTML(value){html=value;this.mutations+=1;},
      });
    }
    return nodes.get(id);
  }
  Object.assign(element("sideFilter"),{value:"CALL"});
  Object.assign(element("expiryRange"),{value:"LT3"});
  Object.assign(element("strikeButtons"),{
    clientWidth:200,scrollLeft:0,lastScrollLeft:null,
    getBoundingClientRect(){return{left:20,width:200}},
    querySelector(){return{getBoundingClientRect(){return{left:420,width:50}}}},
    scrollTo(options){this.lastScrollLeft=options.left;this.scrollLeft=options.left;},
  });
  Object.assign(element("strikeMenu"),{
    clientHeight:200,scrollTop:0,
    getBoundingClientRect(){return{top:100,height:200}},
    querySelector(){return{getBoundingClientRect(){return{top:300,height:44}},focus(){selectedStrikeOptionFocused=true;document.activeElement=element("strikeMenu");}}},
  });
  Object.assign(element("strikeTrigger"),{getBoundingClientRect(){return{top:416,bottom:455,height:39}}});
  Object.assign(element("strikePicker"),{getBoundingClientRect(){return{top:396,bottom:455,height:59}}});
  Object.assign(element("expiryMenu"),{
    clientHeight:200,scrollTop:0,
    getBoundingClientRect(){return{top:100,height:200}},
    querySelector(){return{getBoundingClientRect(){return{top:140,height:44}},focus(){selectedExpiryOptionFocused=true;document.activeElement=element("expiryMenu");}}},
  });
  Object.assign(element("expiryTrigger"),{getBoundingClientRect(){return{top:200,bottom:244,height:44}}});
  Object.assign(element("expiryPicker"),{getBoundingClientRect(){return{top:180,bottom:244,height:64}}});
  const tabButtons=["chain","price","ranking"].map(view=>({dataset:{view},listeners:{},classList:{toggle(){}},addEventListener(type,handler){this.listeners[type]=handler;}}));
  const document = {
    body, documentElement:{dataset:{}}, activeElement:null, visibilityState:"visible",
    getElementById:element, querySelectorAll(selector){return selector===".tab"?tabButtons:[]}, querySelector(){return{content:""}}, addEventListener(type,handler){documentListeners[type]=handler;},
  };
  class FakeAbortController {
    constructor(){const listeners=[];this.listeners=listeners;this.signal={aborted:false,addEventListener(type,handler){if(type==="abort")listeners.push(handler);}};}
    abort(){if(this.signal.aborted)return;this.signal.aborted=true;for(const handler of this.listeners)handler();}
  }
  const context = {document, Intl, Date, Number, Math, console, AbortController:FakeAbortController,innerHeight:700,
    localStorage:{getItem(key){if(storageBlocked)throw new Error("blocked");return stored.get(key)??null},setItem(key,value){if(storageBlocked)throw new Error("blocked");storageWrites+=1;stored.set(key,value);}},
    OptionsGuide:{activate(){guideActivations+=1;}},
    performance:{now(){return now}},
    fetch(_url,options={}){fetchCalls+=1;lastSignal=options.signal;return new Promise((resolve,reject)=>{resolveFetch=resolve;options.signal?.addEventListener("abort",()=>{const error=new Error("aborted");error.name="AbortError";reject(error);});});},
    setInterval(){}, setTimeout(fn){const id=++timerId;timers.set(id,fn);return id;}, clearTimeout(id){timers.delete(id);},
    addEventListener(type,handler){windowListeners[type]=handler;}, getSelection(){return selection;}};
  context.window = context;
  vm.createContext(context);
  const loader = isMobile ? "load" : "loadSnapshot";
  const source = fs.readFileSync("web/shared/period-return.js","utf8") + "\n" + fs.readFileSync(path,"utf8") + `\nglobalThis.__ui={state,interaction,render,renderRanking,renderPriceYield,renderLightweight,flushPendingRender,releasePointer,revealSelectedStrike:typeof revealSelectedStrike==="function"?revealSelectedStrike:null,strikeGroupFor:typeof strikeGroupFor==="function"?strikeGroupFor:null,closeStrikeMenu:typeof closeStrikeMenu==="function"?closeStrikeMenu:null,toggleStrikeMenu:typeof toggleStrikeMenu==="function"?toggleStrikeMenu:null,closeExpiryMenu:typeof closeExpiryMenu==="function"?closeExpiryMenu:null,toggleExpiryMenu:typeof toggleExpiryMenu==="function"?toggleExpiryMenu:null,rebuildContractsCache,secondsToDisplayBoundary,expiryRangeMatches,filteredRankingContracts,rankingStrikeCell,contractPeriodContent,priceEligibleContract,setRankingSort,paginationItems,remainingText,dataTime,loader:${loader}};`;
  vm.runInContext(source,context);
  const api = context.__ui;
  if(isMobile){
    const expected=!storageBlocked&&["chain","price","ranking"].includes(rememberedView)?rememberedView:"chain";
    for(const view of ["chain","price","ranking"])assert.strictEqual(element(`${view}View`).classList.contains("hidden"),view!==expected,"initial saved module must restore");
    assert.strictEqual(guideActivations,0,"removed guide must not activate its loader");
    for(const view of ["price","ranking","chain"]){tabButtons.find(b=>b.dataset.view===view).listeners.click();assert(!element(`${view}View`).classList.contains("hidden"));if(!storageBlocked)assert.strictEqual(stored.get("btc-options-mobile-view"),view);}
  }
  const snapshot = generation => ({
    fetched_at:`2026-09-25T00:0${generation}:00Z`, catalog_fetched_at:"2026-09-25T00:00:00Z",
    index_price:100000, server_time_ms:1_700_000_000_000, next_refresh_seconds:60,
    status:{status:"healthy",age_seconds:0,market_error:null,catalog_error:null,mark_warning:null},
    market_generation_ms:1_700_000_000_000+generation*60_000,
    contracts:[{symbol:"BTC-X",expiry_ms:1_700_000_000_000+2*86400*1000,side:"CALL",strike:110000,bid:500,open_interest:1,moneyness:"OTM",time_value:500,time_value_status:"positive",period_return_pct:.5,annualized_pct:12.34,annualized_calculated_at_ms:1_700_000_000_000+generation*60_000,exercise_probability_pct:23.95,probability_display_state:"normal"}],
  });
  if(isMobile&&rememberedUi&&typeof rememberedUi==="object"){
    const expectedValid=rememberedUi.priceSide==="CALL";
    if(!expectedValid){assert.strictEqual(api.state.priceSide,"CALL");assert.strictEqual(api.state.rankingSide,"CALL");assert.strictEqual(api.state.rankingRange,"LT3");assert.strictEqual(api.state.rankingSortKey,"annualized_pct");assert.strictEqual(api.state.rankingSortDirection,"desc");assert.strictEqual(api.state.rankingPage,1);return;}
    const expiryA=1_700_000_000_000+2*86400*1000,expiryB=1_700_000_000_000+4*86400*1000,base=snapshot(0).contracts[0];
    const rankingRows=Array.from({length:11},(_,index)=>({...base,symbol:`RESTORE-RANK-${index}`,side:"PUT",strike:91000+index,time_value_status:"positive",annualized_pct:index,remaining_seconds:3*86400+index,expiry_ms:1_700_000_000_000+(3*86400+index)*1000}));
    api.state.snapshot={...snapshot(0),contracts:[{...base,symbol:"RESTORE-CALL",strike:84500,expiry_ms:expiryA},{...base,symbol:"RESTORE-PUT",side:"PUT",strike:90000,expiry_ms:expiryA},...rankingRows]};api.state.receivedPerf=now;api.render();
    assert.strictEqual(api.state.selectedExpiry,expiryA,"saved expiry must restore when still available");assert.strictEqual(api.state.priceSide,"CALL");assert.strictEqual(api.state.selectedStrike,84500,"saved Call strike must restore");assert.strictEqual(api.state.rankingSide,"PUT");assert.strictEqual(api.state.rankingRange,"3_7");assert.strictEqual(api.state.rankingSortKey,"strike");assert.strictEqual(api.state.rankingSortDirection,"asc");assert.strictEqual(api.state.rankingPage,2,"valid saved ranking page must restore");
    const populatedSnapshot=api.state.snapshot;api.state.snapshot={...populatedSnapshot,contracts:[]};api.state.contractsCache=null;api.render();assert.strictEqual(api.state.rankingPage,2,"temporarily empty market must preserve restored ranking page");assert.strictEqual(JSON.parse(stored.get("btc-options-mobile-ui-v1")).rankingPage,2,"temporarily empty market must not overwrite stored ranking page");assert(element("rankingPrev").disabled&&element("rankingNext").disabled,"empty market must disable ranking pagination");api.state.snapshot=populatedSnapshot;api.state.contractsCache=null;api.render();assert.strictEqual(api.state.rankingPage,2,"ranking page must recover after market rows return");
    const writesAfterRender=storageWrites;api.renderLightweight();api.renderLightweight();assert.strictEqual(storageWrites,writesAfterRender,"lightweight one-second renders must not write UI state");
    element("priceSideFilter").listeners.click({target:{closest(){return{dataset:{value:"PUT"}};}}});assert.strictEqual(api.state.selectedStrike,90000,"saved Put strike must restore independently");api.state.snapshot={...api.state.snapshot,contracts:api.state.snapshot.contracts.filter(contract=>contract.symbol!=="RESTORE-PUT")};api.state.contractsCache=null;api.render();assert.strictEqual(api.state.selectedStrike,91010,"deleted saved strike must fall back to the nearest valid strike");element("priceSideFilter").listeners.click({target:{closest(){return{dataset:{value:"CALL"}};}}});assert.strictEqual(api.state.selectedStrike,84500,"switching back must restore saved Call strike");
    api.state.snapshot={...api.state.snapshot,contracts:api.state.snapshot.contracts.filter(contract=>contract.expiry_ms!==expiryA)};api.state.contractsCache=null;api.render();assert.notStrictEqual(api.state.selectedExpiry,expiryA,"deleted expiry must use existing fallback");assert(api.state.selectedExpiry!==null,"deleted expiry fallback must select a remaining expiry");
    api.state.snapshot={...api.state.snapshot,contracts:[{...base,symbol:"NONMATCHING",side:"CALL",strike:84500,expiry_ms:expiryB}]};api.state.contractsCache=null;api.render();assert.strictEqual(api.state.rankingPage,1,"nonempty market with no matching rows must clamp a restored page");assert.strictEqual(JSON.parse(stored.get("btc-options-mobile-ui-v1")).rankingPage,1,"clamped no-match ranking page must be persisted");
    const savedAfterFallback=JSON.parse(stored.get("btc-options-mobile-ui-v1"));api.state.snapshot={...api.state.snapshot,contracts:[]};api.state.contractsCache=null;api.render();const savedAfterEmpty=JSON.parse(stored.get("btc-options-mobile-ui-v1"));assert.strictEqual(savedAfterEmpty.selectedExpiry,savedAfterFallback.selectedExpiry,"empty snapshot must not erase remembered expiry");assert.deepStrictEqual(savedAfterEmpty.priceStrikes,savedAfterFallback.priceStrikes,"empty snapshot must not erase per-side strikes");
    return;
  }
  const tableMutations = () => element("chainBody").mutations + element("priceYieldBody").mutations + element("rankingBody").mutations;
  let before;
  api.state.snapshot=snapshot(0); api.state.receivedPerf=now; api.render();
  if(isMobile){
    for(const view of ["price","ranking"]){
      tabButtons.find(b=>b.dataset.view===view).listeners.click();
      api.state.snapshot=snapshot(1);api.state.contractsCache=null;api.render();api.renderLightweight();
      assert(!element(`${view}View`).classList.contains("hidden"),"market update must not reset the module");
    }
    tabButtons.find(b=>b.dataset.view==="chain").listeners.click();api.state.snapshot=snapshot(0);api.state.contractsCache=null;api.render();
  }

  assert.strictEqual(element("fetchedAt").textContent,"09-25 08:00:00",`${path}: data time format must omit year and timezone suffix`);
  assert(element("chainBody").innerHTML.includes("12.34%"),`${path}: did not use service annualized value`);
  assert(element("chainBody").innerHTML.includes("0.50%"),`${path}: did not display service period return`);
  const sharedPeriodMarkup=context.OptionsPeriodReturn.render(snapshot(0).contracts[0],snapshot(0).index_price);
  for(const id of ["chainBody","priceYieldBody","rankingBody"]){assert(element(id).innerHTML.includes(sharedPeriodMarkup),`${path}: ${id} must use the same shared period markup for the same contract`);}
  assert(sharedPeriodMarkup.includes("\u20070.50%"),`${path}: Call income must reserve the sign space`);
  const sharedSource=fs.readFileSync("web/shared/period-return.js","utf8");
  assert(!fs.readFileSync(path,"utf8").includes("const contractPeriodText"),`${path}: duplicated period formatter must not return`);

  if(isMobile){
    assert(element("strikeMenu").innerHTML.includes('110,000<span class="strike-relative positive">（+10.00%）</span>'),"strike menu must show signed relative price");
    const short=snapshot(0);short.contracts[0].expiry_ms=short.server_time_ms+5*3600000;api.state.snapshot=short;api.state.contractsCache=null;api.render();assert(element("expiryMenu").innerHTML.includes('（剩余5小时）'),"sub-day expiry must show hours");
    short.contracts[0].expiry_ms=short.server_time_ms+1800000;api.state.contractsCache=null;api.render();assert(element("expiryMenu").innerHTML.includes('（剩余不足1小时）'),"sub-hour expiry must not show zero hours");
    api.state.snapshot={...snapshot(0),index_price:120000};api.state.contractsCache=null;api.render();assert(element("strikeMenu").innerHTML.includes('110,000<span class="strike-relative negative">（-8.33%）</span>'),"strike relative price must update with index");
    api.state.snapshot=snapshot(0);api.state.contractsCache=null;api.render();
  }
  const periodBase=snapshot(0).contracts[0];
  for(const side of ["CALL","PUT"]){
    api.state.priceSide=side;
    const valid={...periodBase,side,remaining_seconds:86400,time_value_status:"positive",open_interest:2,annualized_pct:6.08};
    assert(api.priceEligibleContract(valid),`${path}: valid ${side} must remain visible`);
    for(const value of [null,undefined,NaN,Infinity,"6.08"]){assert(!api.priceEligibleContract({...valid,annualized_pct:value}),`${path}: blank/invalid ${side} annual must be hidden`);}
    assert(!api.priceEligibleContract({...valid,open_interest:0}),`${path}: zero OI annual dash must be hidden`);
    assert(api.priceEligibleContract({...valid,annualized_pct:0}),`${path}: numeric zero must not be treated as missing`);
  }
  api.state.priceSide="CALL";

  const callPeriod=api.contractPeriodContent({...periodBase,side:"CALL",strike:110000,period_return_pct:1.25}),putPeriod=api.contractPeriodContent({...periodBase,side:"PUT",strike:90000,period_return_pct:-1.25}),flatPeriod=api.contractPeriodContent({...periodBase,strike:100000,period_return_pct:0});
  assert(callPeriod.includes('class="period-distance positive"')&&callPeriod.includes('>+10.00%</span>')&&callPeriod.includes(`title="单期收益">\u20071.25%`),`${path}: Call positive distance/period lines missing`);
  assert(!putPeriod.includes('period-distance')&&putPeriod.includes(`title="单期收益">-1.25%`),`${path}: Put must show only premium period return`);
  assert(flatPeriod.includes('class="period-distance neutral"')&&flatPeriod.includes('>0.00%</span>')&&flatPeriod.includes(`title="单期收益">\u20070.00%`),`${path}: zero distance/period lines missing`);
  assert.strictEqual(api.contractPeriodContent({...periodBase,open_interest:0}),"—",`${path}: zero OI period cell must be one dash`);assert.strictEqual(api.contractPeriodContent(null),"—",`${path}: missing contract period cell must be one dash`);
  api.state.snapshot={...snapshot(0),index_price:"100000"};assert(api.contractPeriodContent(periodBase).includes('title="行权价距现价">—</span>')&&api.contractPeriodContent(periodBase).includes(`title="单期收益">\u20070.50%</span>`),`${path}: invalid spot must keep original period line`);api.state.snapshot=snapshot(0);assert(api.contractPeriodContent({...periodBase,strike:0}).includes('title="行权价距现价">—</span>'),`${path}: nonpositive strike must not show a distance`);api.state.snapshot={...snapshot(0),index_price:Number.MIN_VALUE};assert(api.contractPeriodContent({...periodBase,strike:Number.MAX_VALUE}).includes('title="行权价距现价">—</span>'),`${path}: nonfinite relative result must render a dash`);api.state.snapshot=snapshot(0);
  for(const id of ["chainBody","priceYieldBody","rankingBody"]){assert(element(id).innerHTML.includes('title="行权价距现价"')&&element(id).innerHTML.includes(`title="单期收益"`),`${path}: ${id} did not use the shared two-line period cell`);}
  if(isMobile){assert(element("expiryMenu").innerHTML.includes("2023-11-17（剩余2天）"),"expiry option must include whole remaining days");assert.strictEqual(element("expiryValue").textContent,"2023-11-17",`${path}: compact expiry trigger did not show selection`);assert(element("expiryMenu").innerHTML.includes('data-expiry=')&&element("expiryMenu").innerHTML.includes('aria-selected="true"'),`${path}: compact expiry options were not rendered`);element("expiryTrigger").listeners.click();assert(!element("expiryMenu").classList.contains("hidden")&&element("expiryTrigger").attributes["aria-expanded"]==="true",`${path}: compact expiry menu did not open`);assert(selectedExpiryOptionFocused,`${path}: compact expiry menu did not focus its selection`);selectedExpiryOptionFocused=false;const expiryExpanded=snapshot(0);expiryExpanded.contracts.push({...expiryExpanded.contracts[0],symbol:"BTC-LATER",expiry_ms:expiryExpanded.contracts[0].expiry_ms+86400000});api.state.snapshot=expiryExpanded;api.state.contractsCache=null;api.render();assert(!element("expiryMenu").classList.contains("hidden")&&selectedExpiryOptionFocused,`${path}: option-set refresh lost focus from an open expiry menu`);documentListeners.click({target:{}});assert(element("expiryMenu").classList.contains("hidden"),`${path}: outside click did not close compact expiry menu`);}
  const negativeSnapshot=snapshot(1);
  negativeSnapshot.contracts[0].time_value=-.001;
  negativeSnapshot.contracts[0].time_value_status="negative";
  negativeSnapshot.contracts[0].annualized_pct=null;
  negativeSnapshot.contracts[0].period_return_pct=null;
  negativeSnapshot.contracts[0].mark_time_value=-100;
  negativeSnapshot.contracts[0].mark_annualized_pct=-1.2166666667;
  api.state.snapshot=negativeSnapshot; api.state.contractsCache=null; api.render();
  assert(element("chainBody").innerHTML.includes("Bid &lt; 内在价值"),`${path}: negative time value reason was not displayed`);
  if(isMobile){assert(!element("chainBody").innerHTML.includes("TV ")&&!element("chainBody").innerHTML.includes("Mark "),"mobile negative TV warning must contain only the Bid label");}else{
  assert(element("chainBody").innerHTML.includes("TV -&lt;0.01"),`${path}: tiny negative TV was rounded to zero or inserted as unsafe markup`);
  assert(element("chainBody").innerHTML.includes(" · Mark -1.2%"),`${path}: mark reference was not displayed`);
  }
  assert(!element("rankingBody").innerHTML.includes("BTC-X"),`${path}: nonpositive bid TV leaked into ranking`);
  const zeroSnapshot=snapshot(2);
  zeroSnapshot.contracts[0].time_value=0;
  zeroSnapshot.contracts[0].time_value_status="zero";
  zeroSnapshot.contracts[0].annualized_pct=null;
  zeroSnapshot.contracts[0].period_return_pct=null;
  api.state.snapshot=zeroSnapshot; api.state.contractsCache=null; api.render();
  assert(element("chainBody").innerHTML.includes("Bid = 内在价值") && element("chainBody").innerHTML.includes("TV 0.00"),`${path}: zero time value reason was not displayed`);
  api.state.contractsCache=null; api.state.snapshot=snapshot(0); api.render();
  const day=86400;
  assert(api.expiryRangeMatches(.5*day,"LT3")&&api.expiryRangeMatches(3*day-1,"LT3")&&!api.expiryRangeMatches(3*day,"LT3"),`${path}: <3 day boundary`);
  assert(api.expiryRangeMatches(3*day,"3_7")&&api.expiryRangeMatches(7*day-1,"3_7")&&!api.expiryRangeMatches(3*day-1,"3_7")&&!api.expiryRangeMatches(7*day,"3_7"),`${path}: 3-7 day boundary`);
  assert(api.expiryRangeMatches(7*day,"7_30")&&!api.expiryRangeMatches(30*day,"7_30"),`${path}: 7-30 day boundary`);
  assert(api.expiryRangeMatches(30*day,"30_60")&&api.expiryRangeMatches(60*day,"30_60")&&!api.expiryRangeMatches(60*day+1,"30_60"),`${path}: 30-60 day boundary`);
  assert(api.expiryRangeMatches(60*day+1,"GT60")&&!api.expiryRangeMatches(60*day,"GT60")&&!api.expiryRangeMatches(0,"LT3"),`${path}: >60 or expired boundary`);
  for(const seconds of[1,3*day-1,3*day,7*day-1,7*day,30*day-1,30*day,60*day,60*day+1])assert.strictEqual(["LT3","3_7","7_30","30_60","GT60"].filter(range=>api.expiryRangeMatches(seconds,range)).length,1,`${path}: positive term ${seconds} must match exactly one range`);
  api.state.rankingRange="3_7";api.state.rankingSortKey="annualized_pct";api.state.rankingSortDirection="desc";const midRows=Array.from({length:11},(_,index)=>({...snapshot(0).contracts[0],symbol:`MID-${index}`,remaining_seconds:3*day+index,annualized_pct:index}));assert.deepStrictEqual(Array.from(api.filteredRankingContracts(midRows),c=>c.annualized_pct),[10,9,8,7,6,5,4,3,2,1,0],`${path}: 3-7 day rows must keep selected sorting`);api.state.rankingPage=1;api.renderRanking(midRows);assert.strictEqual((element("rankingBody").innerHTML.match(/<tr>/g)||[]).length,10,`${path}: 3-7 day first page must paginate at ten rows`);assert(element("rankingPages").innerHTML.includes('data-page="2"'),`${path}: 3-7 day result did not expose second page`);
  api.state.rankingRange="7_30";
  const filterContracts=[
    {...snapshot(0).contracts[0],symbol:"POS",remaining_seconds:7*day,time_value_status:"positive"},
    {...snapshot(0).contracts[0],symbol:"NEG",remaining_seconds:8*day,time_value_status:"negative"},
  ];
  assert.deepStrictEqual(Array.from(api.filteredRankingContracts(filterContracts),c=>c.symbol),["POS"],`${path}: ranking helper must apply range and exclude nonpositive TV`);
  assert.strictEqual(api.state.rankingRange,"7_30",`${path}: filter selection was not preserved after render`);
  api.state.rankingRange="LT3";
  const rankRows=Array.from({length:11},(_,index)=>({...snapshot(0).contracts[0],symbol:`BTC-${String(index).padStart(2,"0")}`,remaining_seconds:2*day,strike:100000+(10-index)*100,period_return_pct:index,annualized_pct:index,exercise_probability_pct:index===10?null:index,probability_display_state:index===9?"settling":"normal"}));
  rankRows[0].moneyness="ITM";
  api.state.rankingPage=1;api.state.rankingSortKey="annualized_pct";api.state.rankingSortDirection="desc";api.renderRanking(rankRows);
  assert.strictEqual((element("rankingBody").innerHTML.match(/<tr>/g)||[]).length,10,`${path}: first ranking page must contain 10 rows`);
  assert(element("rankingPages").innerHTML.includes('data-page="1"')&&element("rankingPages").innerHTML.includes('data-page="2"'),`${path}: 11 rows must create two clickable pages`);
  api.state.rankingPage=2;api.renderRanking(rankRows);assert.strictEqual(api.state.rankingPage,2,`${path}: refresh should preserve a valid page`);assert.strictEqual((element("rankingBody").innerHTML.match(/<tr>/g)||[]).length,1,`${path}: second ranking page must contain one row`);
  api.renderRanking(rankRows.slice(0,3));assert.strictEqual(api.state.rankingPage,1,`${path}: refresh must clamp an out-of-range page`);
  api.state.rankingPage=2;
  element("rankingHead").listeners.click({target:{closest(){return{dataset:{sort:"strike"}};}}});
  assert.strictEqual(api.state.rankingPage,1,`${path}: sorting must reset page`);assert.strictEqual(api.state.rankingSortKey,"strike");assert.strictEqual(api.state.rankingSortDirection,"asc");
  element("rankingHead").listeners.click({target:{closest(){return{dataset:{sort:"strike"}};}}});assert.strictEqual(api.state.rankingSortDirection,"desc",`${path}: repeated header click must toggle direction`);
  element("rankingHead").listeners.click({target:{closest(){return{dataset:{sort:"annualized_pct"}};}}});assert.strictEqual(api.state.rankingSortKey,"annualized_pct");assert.strictEqual(api.state.rankingSortDirection,"asc",`${path}: switching back to annualized must start ascending`);
  element("rankingHead").listeners.click({target:{closest(){return{dataset:{sort:"annualized_pct"}};}}});assert.strictEqual(api.state.rankingSortDirection,"desc",`${path}: repeated annualized click must toggle descending`);
  api.state.rankingSortKey="exercise_probability_pct";api.state.rankingSortDirection="asc";
  const probabilityOrder=Array.from(api.filteredRankingContracts(rankRows),c=>c.symbol);assert(probabilityOrder.indexOf("BTC-10")>probabilityOrder.indexOf("BTC-08")&&probabilityOrder.indexOf("BTC-09")>probabilityOrder.indexOf("BTC-08"),`${path}: missing and settling probability must sort last`);
  api.state.rankingSortDirection="desc";const probabilityDesc=Array.from(api.filteredRankingContracts(rankRows),c=>c.symbol);assert(probabilityDesc.indexOf("BTC-10")>probabilityDesc.indexOf("BTC-00")&&probabilityDesc.indexOf("BTC-09")>probabilityDesc.indexOf("BTC-00"),`${path}: missing probability must remain last when descending`);
  api.state.rankingSortKey="strike";api.state.rankingSortDirection="asc";const strikeOrder=Array.from(api.filteredRankingContracts(rankRows),c=>c.strike);assert.deepStrictEqual(strikeOrder,[...strikeOrder].sort((a,b)=>a-b),`${path}: strike sorting must use raw numbers`);
  assert(api.rankingStrikeCell({...rankRows[0],strike:110000}).includes("relative-positive")||api.rankingStrikeCell({...rankRows[0],strike:110000}).includes('class="rank-relative positive"'),`${path}: strike above index must be red class`);
  assert(api.rankingStrikeCell({...rankRows[0],strike:90000}).includes("relative-negative")||api.rankingStrikeCell({...rankRows[0],strike:90000}).includes('class="rank-relative negative"'),`${path}: strike below index must be green class`);
  api.state.rankingPage=2;element("sideFilter").listeners.click({target:{closest(){return{dataset:{value:"PUT"}};}}});assert.strictEqual(api.state.rankingPage,1,`${path}: filter change must reset page`);assert.strictEqual(api.state.rankingSide,"PUT",`${path}: direction segment did not update state`);
  api.state.rankingPage=2;element("expiryRange").listeners.click({target:{closest(){return{dataset:{value:"GT60"}};}}});assert.strictEqual(api.state.rankingPage,1,`${path}: expiry segment must reset page`);assert.strictEqual(api.state.rankingRange,"GT60",`${path}: expiry segment did not update state`);
  api.state.rankingSide="CALL";api.state.rankingRange="LT3";api.state.contractsCache=rankRows;api.state.rankingPage=1;element("rankingPages").listeners.click({target:{closest(){return{dataset:{page:"2"}};}}});assert.strictEqual(api.state.rankingPage,2,`${path}: clicking a page number did not navigate`);
  assert.deepStrictEqual(Array.from(api.paginationItems(1,1)),[1],`${path}: one-page pagination`);
  assert.deepStrictEqual(Array.from(api.paginationItems(1,11)),[1,2,3,"ellipsis",11],`${path}: first-page pagination window`);
  assert.deepStrictEqual(Array.from(api.paginationItems(6,11)),[1,"ellipsis",5,6,7,"ellipsis",11],`${path}: middle pagination window`);
  assert.deepStrictEqual(Array.from(api.paginationItems(11,11)),[1,"ellipsis",9,10,11],`${path}: final pagination window`);
  assert.strictEqual(api.remainingText(2*day+5*3600),"2天5小时",`${path}: remaining time must omit plus sign`);
  assert.strictEqual(api.secondsToDisplayBoundary(259200),0.05,`${path}: exact 3-day boundary must update promptly`);
  assert.strictEqual(api.secondsToDisplayBoundary(3600),0.05,`${path}: exact hour boundary must update promptly`);
  const dual=snapshot(0),base=dual.contracts[0];
  dual.contracts=[
    {...base,symbol:"CALL-90",strike:90000,side:"CALL",annualized_pct:11.11,expiry_ms:base.expiry_ms},
    {...base,symbol:"CALL-110",strike:110000,side:"CALL",annualized_pct:22.22,expiry_ms:base.expiry_ms+1000},
    {...base,symbol:"PUT-105",strike:105000,side:"PUT",annualized_pct:33.33,expiry_ms:base.expiry_ms},
    {...base,symbol:"PUT-110",strike:110000,side:"PUT",annualized_pct:44.44,expiry_ms:base.expiry_ms+1000},
    {...base,symbol:"PUT-EXPIRED",strike:100000,side:"PUT",expiry_ms:dual.server_time_ms,remaining_seconds:0,annualized_pct:99.99},
  ];
  api.state.snapshot=dual;api.state.contractsCache=null;api.state.selectedStrike=null;api.state.strikeKey="";api.state.priceSide="CALL";api.render();
  assert.strictEqual(api.state.selectedStrike,90000,`${path}: nearest strike tie must choose lower value`);
  if(isMobile){
    const options=element("strikeMenu").innerHTML;
    assert(options.includes('data-strike="90000" aria-selected="true"')&&options.indexOf('data-strike="90000"')<options.indexOf('data-strike="110000"'),`${path}: mobile strike menu must be ordered and select nearest spot`);
    assert.strictEqual(element("strikeValue").textContent,"90,000",`${path}: mobile trigger did not show selected strike`);
    element("strikeTrigger").listeners.click();assert(!element("strikeMenu").classList.contains("hidden")&&element("strikeTrigger").attributes["aria-expanded"]==="true",`${path}: trigger did not open custom menu`);assert.strictEqual(element("strikeMenu").scrollTop,122,`${path}: opening menu did not scroll selected option into view`);assert(selectedStrikeOptionFocused,`${path}: opening strike menu did not focus the selected option`);let menuHeight=Number.parseInt(element("strikeMenu").style.maxHeight,10),opensUp=element("strikeMenu").classList.contains("open-up"),menuBottom=opensUp?396-5:455+5+menuHeight,menuTop=opensUp?menuBottom-menuHeight:455+5;assert(menuTop>=0&&menuBottom<=context.innerHeight,`${path}: adaptive menu exceeded viewport`);
    selectedStrikeOptionFocused=false;dual.contracts.push({...base,symbol:"CALL-120",strike:120000,side:"CALL",expiry_ms:base.expiry_ms});api.state.snapshot={...dual,fetched_at:"2026-09-25T00:09:00Z"};api.state.contractsCache=null;api.render();assert(!element("strikeMenu").classList.contains("hidden")&&selectedStrikeOptionFocused,`${path}: option-set refresh lost focus from an open strike menu`);
    element("strikeTrigger").listeners.click();assert(element("strikeMenu").classList.contains("hidden"),`${path}: repeated trigger did not close menu`);
    element("strikeTrigger").listeners.click();document.activeElement=element("strikeMenu");element("strikeTrigger").focused=false;api.state.snapshot={...dual,contracts:dual.contracts.filter(contract=>contract.side!=="CALL"),fetched_at:"2026-09-25T00:09:30Z"};api.state.contractsCache=null;api.state.strikeKey="";api.render();assert(element("strikeMenu").classList.contains("hidden")&&element("strikeTrigger").focused,`${path}: empty option refresh did not close the strike menu and restore trigger focus`);api.state.snapshot=dual;api.state.contractsCache=null;api.state.strikeKey="";api.state.selectedStrike=null;element("strikeTrigger").focused=false;api.render();
    let strikeArrowPrevented=false;element("strikeTrigger").listeners.keydown({key:"ArrowDown",preventDefault(){strikeArrowPrevented=true;}});assert(strikeArrowPrevented&&!element("strikeMenu").classList.contains("hidden"),`${path}: ArrowDown did not open strike menu`);element("strikeMenu").listeners.keydown({key:"Escape",preventDefault(){}});assert(element("strikeMenu").classList.contains("hidden")&&element("strikeTrigger").focused,`${path}: strike menu Escape did not close and restore trigger focus`);element("strikeTrigger").focused=false;
    context.innerHeight=300;element("strikeTrigger").getBoundingClientRect=()=>({top:128,bottom:172,height:44});element("strikePicker").getBoundingClientRect=()=>({top:108,bottom:172,height:64});element("strikeTrigger").listeners.click();menuHeight=Number.parseInt(element("strikeMenu").style.maxHeight,10);menuTop=172+5;menuBottom=menuTop+menuHeight;assert(!element("strikeMenu").classList.contains("open-up")&&element("strikeMenu").style.maxHeight==="115px"&&menuBottom<=context.innerHeight,`${path}: extremely short downward menu exceeded viewport`);element("strikeTrigger").listeners.click();
    context.innerHeight=400;element("strikeTrigger").getBoundingClientRect=()=>({top:240,bottom:284,height:44});element("strikePicker").getBoundingClientRect=()=>({top:220,bottom:284,height:64});element("strikeTrigger").listeners.click();menuHeight=Number.parseInt(element("strikeMenu").style.maxHeight,10);menuBottom=220-5;menuTop=menuBottom-menuHeight;assert(element("strikeMenu").classList.contains("open-up")&&element("strikeMenu").style.maxHeight==="207px"&&menuTop>=0&&menuBottom<=context.innerHeight,`${path}: upward menu used trigger geometry or exceeded viewport`);element("strikeTrigger").listeners.click();context.innerHeight=700;element("strikeTrigger").getBoundingClientRect=()=>({top:416,bottom:455,height:39});element("strikePicker").getBoundingClientRect=()=>({top:396,bottom:455,height:59});
    element("strikeTrigger").listeners.click();documentListeners.keydown({key:"Escape"});assert(element("strikeMenu").classList.contains("hidden"),`${path}: Escape did not close menu`);
    element("strikeTrigger").listeners.click();documentListeners.click({target:{}});assert(element("strikeMenu").classList.contains("hidden"),`${path}: outside click did not close menu`);
    element("strikeTrigger").listeners.click();tabButtons.find(button=>button.dataset.view==="ranking").listeners.click();assert(element("strikeMenu").classList.contains("hidden"),`${path}: switching view did not close menu`);
  }else{
    assert.strictEqual(api.strikeGroupFor(39999),30000,`${path}: 39999 group boundary`);assert.strictEqual(api.strikeGroupFor(40000),40000,`${path}: 40000 group boundary`);
    assert.strictEqual(api.state.strikeGroup,90000,`${path}: default group must contain nearest strike`);
    assert(element("strikeGroupButtons").innerHTML.indexOf('data-strike-group="90000"')<element("strikeGroupButtons").innerHTML.indexOf('data-strike-group="110000"'),`${path}: strike groups must be numeric ordered`);
    assert(element("strikeButtons").innerHTML.includes('data-strike="90000" aria-pressed="true"'),`${path}: selected strike must be highlighted in expanded group`);
    assert.strictEqual(element("currentStrike").textContent,"90,000",`${path}: current strike label missing`);
    assert(element("currentStrikeLabel").className.includes("below-spot"),`${path}: strike below raw spot must be green-classed`);api.state.snapshot={...dual,index_price:90000};api.state.contractsCache=null;api.render();assert(element("currentStrikeLabel").className.includes("neutral-spot"),`${path}: strike equal to raw spot must be neutral-classed`);api.state.snapshot={...dual,index_price:89999.9};api.state.contractsCache=null;api.render();assert(element("currentStrikeLabel").className.includes("above-spot"),`${path}: strike above raw spot must be red-classed`);api.state.snapshot={...dual,index_price:"90000"};api.state.contractsCache=null;api.render();assert(element("currentStrikeLabel").className.includes("neutral-spot"),`${path}: invalid raw spot must be neutral-classed`);api.state.snapshot=dual;api.state.contractsCache=null;api.render();
    element("strikeGroupButtons").listeners.click({target:{closest(){return{dataset:{strikeGroup:"110000"}};}}});
    assert.strictEqual(api.state.selectedStrike,90000,`${path}: expanding a group must not change selected strike`);
    assert.strictEqual(element("currentStrike").textContent,"90,000",`${path}: group browsing obscured actual selected strike`);
    assert(element("strikeButtons").innerHTML.includes('data-strike="110000"'),`${path}: group click did not reveal its second-level strikes`);
    const grouped={...dual,index_price:104000.25,contracts:[100000,103000,104000,105000,109000].map((strike,index)=>({...base,symbol:`GROUP-${strike}`,strike,side:"CALL",expiry_ms:base.expiry_ms+index}))};
    api.state.snapshot=grouped;api.state.contractsCache=null;api.state.selectedStrike=null;api.state.strikeGroup=null;api.state.strikeKey="";api.render();
    let groupedHtml=element("strikeButtons").innerHTML,belowHtml=groupedHtml.split('strike-above-row')[0],aboveHtml=groupedHtml.split('strike-above-row')[1];
    assert(belowHtml.indexOf('data-strike="100000"')<belowHtml.indexOf('data-strike="103000"')&&belowHtml.indexOf('data-strike="103000"')<belowHtml.indexOf('data-strike="104000"'),`${path}: below-spot strikes must stay ascending`);
    assert(aboveHtml.indexOf('data-strike="105000"')<aboveHtml.indexOf('data-strike="109000"'),`${path}: above-spot strikes must stay ascending`);
    const keptStrike=api.state.selectedStrike,keptGroup=api.state.strikeGroup;
    const groupedMutations=element("strikeButtons").mutations;api.state.snapshot={...grouped,index_price:104000.5,fetched_at:"2026-09-25T00:09:10Z"};api.state.contractsCache=null;api.render();assert.strictEqual(element("strikeButtons").mutations,groupedMutations,`${path}: same-membership spot tick rebuilt strike buttons`);
    api.state.snapshot={...grouped,index_price:103999.75,fetched_at:"2026-09-25T00:09:20Z"};api.state.contractsCache=null;api.render();groupedHtml=element("strikeButtons").innerHTML;belowHtml=groupedHtml.split('strike-above-row')[0];aboveHtml=groupedHtml.split('strike-above-row')[1];
    assert(!belowHtml.includes('data-strike="104000"')&&aboveHtml.includes('data-strike="104000"'),`${path}: crossing raw spot must move the strike between rows`);
    assert.strictEqual(api.state.selectedStrike,keptStrike,`${path}: spot crossing must preserve selected strike`);assert.strictEqual(api.state.strikeGroup,keptGroup,`${path}: spot crossing must preserve expanded ten-thousand group`);
    api.state.snapshot={...grouped,index_price:104000,fetched_at:"2026-09-25T00:09:30Z"};api.state.contractsCache=null;api.render();groupedHtml=element("strikeButtons").innerHTML;belowHtml=groupedHtml.split('strike-above-row')[0];
    assert(belowHtml.includes("低于 / 等于现价")&&belowHtml.includes('data-strike="104000"')&&belowHtml.includes('>104,000 · 平值</button>'),`${path}: exact raw spot match must append a priced at-the-money button to the first row`);
    api.state.snapshot={...grouped,index_price:"104000",fetched_at:"2026-09-25T00:09:40Z"};api.state.contractsCache=null;api.render();groupedHtml=element("strikeButtons").innerHTML;
    assert(groupedHtml.includes("strike-neutral-row")&&!groupedHtml.includes("strike-below-row")&&!groupedHtml.includes("strike-above-row"),`${path}: invalid spot must use one neutral sequence`);assert(groupedHtml.indexOf('data-strike="100000"')<groupedHtml.indexOf('data-strike="109000"'),`${path}: neutral strike sequence must stay ascending`);
    api.state.snapshot=dual;api.state.contractsCache=null;api.state.selectedStrike=90000;api.state.strikeGroup=90000;api.state.strikeKey="";api.render();
  }
  const filterBase={...base,side:"CALL",expiry_ms:base.expiry_ms,remaining_seconds:86400,time_value_status:"positive"};
  const priceFilterSnapshot={...dual,index_price:83000,contracts:[
    {...filterBase,symbol:"MIXED-NEG",strike:80000,time_value_status:"negative",annualized_pct:null,period_return_pct:null},
    {...filterBase,symbol:"MIXED-OK",strike:80000,expiry_ms:base.expiry_ms+1000,annualized_pct:55.55,period_return_pct:5.55},
    {...filterBase,symbol:"ALL-NEG",strike:82500,time_value_status:"negative",annualized_pct:null,period_return_pct:null},
    {...filterBase,symbol:"ZERO-TV",strike:83000,time_value_status:"zero",time_value:0,annualized_pct:0,period_return_pct:null},
    {...filterBase,symbol:"MISSING-TV",strike:84000,time_value_status:undefined,annualized_pct:null,period_return_pct:null},
    {...filterBase,symbol:"EXPIRED",strike:85000,expiry_ms:dual.server_time_ms,remaining_seconds:0},
    {...filterBase,symbol:"WRONG-SIDE",strike:86000,side:"PUT"},
  ]};
  api.state.snapshot=priceFilterSnapshot;api.state.contractsCache=null;api.state.priceSide="CALL";api.state.selectedStrike=82500;api.state.strikeKey="";api.render();
  const filterOptions=isMobile?element("strikeMenu").innerHTML:element("strikeGroupButtons").innerHTML+element("strikeButtons").innerHTML;
  assert.strictEqual(api.state.selectedStrike,83000,`${path}: filtered-out selection must fall back to nearest eligible strike`);
  assert(filterOptions.includes('data-strike="80000"')&&filterOptions.includes('data-strike="83000"')&&!filterOptions.includes('data-strike="84000"'),`${path}: valid and zero annual candidates must remain selectable; missing annual must be removed`);
  assert(!filterOptions.includes('data-strike="82500"')&&!filterOptions.includes('data-strike="85000"')&&!filterOptions.includes('data-strike="86000"'),`${path}: all-negative, expired or wrong-side candidates leaked into price strikes`);
  assert(element("priceYieldBody").innerHTML.includes("Bid = 内在价值"),`${path}: zero-TV price row was removed`);
  api.state.selectedStrike=80000;api.state.strikeKey="";api.render();assert(element("priceYieldBody").innerHTML.includes("55.55%")&&!element("priceYieldBody").innerHTML.includes("Bid &lt; 内在价值"),`${path}: negative expiry row leaked into a mixed eligible strike`);
  api.state.snapshot={...priceFilterSnapshot,contracts:priceFilterSnapshot.contracts.filter(contract=>contract.time_value_status==="negative")};api.state.contractsCache=null;api.state.strikeKey="";api.render();assert.strictEqual(api.state.selectedStrike,null,`${path}: all-negative price set must clear selection`);assert(!(isMobile?element("strikeMenu").innerHTML:element("strikeGroupButtons").innerHTML+element("strikeButtons").innerHTML).includes("data-strike="),`${path}: all-negative price set must clear strike options`);
  api.state.snapshot=dual;api.state.contractsCache=null;api.state.selectedStrike=90000;api.state.strikeGroup=90000;api.state.strikeKey="";api.state.priceSide="CALL";api.render();
  assert(element("priceYieldBody").innerHTML.includes("11.11%")&&!element("priceYieldBody").innerHTML.includes("33.33%"),`${path}: Call price view mixed Put rows`);
  const rankingSideBefore=api.state.rankingSide,rankingPageBefore=api.state.rankingPage;
  if(isMobile)element("strikeTrigger").listeners.click();
  element("priceSideFilter").listeners.click({target:{closest(){return{dataset:{value:"PUT"}};}}});
  if(isMobile)assert(element("strikeMenu").classList.contains("hidden"),`${path}: direction switch did not close strike menu`);
  assert.strictEqual(api.state.priceSide,"PUT",`${path}: price direction did not switch`);
  assert.strictEqual(api.state.rankingSide,rankingSideBefore,`${path}: price direction changed ranking direction`);
  assert.strictEqual(api.state.rankingPage,rankingPageBefore,`${path}: price direction changed ranking page`);
  assert.strictEqual(api.state.selectedStrike,105000,`${path}: invalid strike did not fall back within selected direction`);
  assert.strictEqual(element("priceAnnualHead").innerHTML,'<span class="nowrap-label">Sell Put</span><br>年化',`${path}: Put heading must remain a two-line structure after dynamic render`);
  assert(element("priceYieldBody").innerHTML.includes("33.33%")&&!element("priceYieldBody").innerHTML.includes("99.99%"),`${path}: Put price view included wrong direction or expired row`);
  api.state.selectedStrike=110000;api.state.strikeKey="";api.state.contractsCache=null;api.state.snapshot={...dual,fetched_at:"2026-09-25T00:10:00Z"};api.render();
  assert.strictEqual(api.state.selectedStrike,110000,`${path}: valid strike selection was not preserved across refresh`);
  if(isMobile)assert(element("strikeMenu").classList.contains("hidden")&&!element("strikeTrigger").focused,`${path}: background refresh reopened menu or stole focus`);
  assert((element("priceYieldBody").innerHTML.match(/<td(?:\s|>)/g)||[]).length===5,`${path}: price row must have five columns`);
  assert(/<td class="remaining-time">[^<]+<\/td><\/tr>$/.test(element("priceYieldBody").innerHTML),`${path}: remaining time must be the final price column`);
  if(isMobile){element("strikeMenu").listeners.click({target:{closest(){return{dataset:{strike:"105000"}};}}});assert.strictEqual(api.state.selectedStrike,105000,`${path}: mobile custom option did not change strike`);assert(element("strikeMenu").classList.contains("hidden")&&element("strikeTrigger").focused,`${path}: option selection did not close menu and return focus`);}else{element("strikeButtons").listeners.click({target:{closest(){return{dataset:{strike:"110000"}};}}});assert.strictEqual(api.state.selectedStrike,110000,`${path}: clicking a second-level strike did not change selection`);}
  before=tableMutations(); api.renderLightweight();
  assert.strictEqual(tableMutations(),before,`${path}: lightweight tick rebuilt a table`);
  before=tableMutations();
  api.state.snapshot=snapshot(1); api.render();
  assert(tableMutations()>before, `${path}: no-selection update must render`);
  selection={isCollapsed:false,rangeCount:1,toString(){return"selected";},anchorNode:bodyNode,focusNode:bodyNode};
  api.interaction.pointerDown=true; api.state.pendingMarketUpdate=true; api.state.snapshot=snapshot(2); before=tableMutations(); api.render();
  assert.strictEqual(tableMutations(),before,`${path}: selection changed DOM`);
  assert.strictEqual(element("fetchedAt").textContent,"09-25 08:02:00",`${path}: selected table blocked new data time`);
  assert(element("notice").textContent.includes("操作结束后更新表格"),`${path}: pending table generation was not disclosed during pointer drag`);
  const countdownBefore=element("countdown").textContent;now+=1000;api.renderLightweight();assert.notStrictEqual(element("countdown").textContent,countdownBefore,`${path}: selected table froze countdown`);
  api.state.localError="连接暂时失败";api.renderLightweight();
  assert(element("notice").textContent.includes("连接暂时失败")&&element("health").className.includes("error"),`${path}: selection blocked failure status update`);
  assert.strictEqual(tableMutations(),before,`${path}: failure status update changed selected tables`);
  api.state.localError=null;api.renderLightweight();
  assert.strictEqual(element("health").textContent,"正常",`${path}: selection blocked recovered status update`);
  assert.strictEqual(tableMutations(),before,`${path}: recovered status update changed selected tables`);
  documentListeners.pointermove({buttons:0,pointerType:"mouse"});
  assert.strictEqual(api.interaction.pointerDown,false,`${path}: lost pointerup was not recovered by buttons=0 movement`);
  api.renderLightweight();assert(element("notice").textContent.includes("取消文字选择后更新表格"),`${path}: selected-text pending notice was not updated`);
  assert.strictEqual(tableMutations(),before,`${path}: pointerup with selection changed DOM`);
  selection={isCollapsed:true,rangeCount:0,toString(){return"";},anchorNode:null,focusNode:null};
  api.flushPendingRender();
  assert(tableMutations()>before,`${path}: clearing selection did not flush latest data`);
  api.interaction.pointerDown=true; api.state.snapshot=snapshot(3); before=tableMutations(); api.render();
  api.releasePointer();
  api.flushPendingRender();
  assert(tableMutations()>before,`${path}: pointer cancel/release did not recover`);

  // The script starts one request. A second call while it is pending must not overlap.
  assert.strictEqual(fetchCalls,1,`${path}: initial request count`);
  api.loader();
  assert.strictEqual(fetchCalls,1,`${path}: overlapping request was started`);
  const abortTimer = [...timers.values()].find(fn=>String(fn).includes("controller.abort"));
  assert(abortTimer,`${path}: request timeout was not scheduled`);
  abortTimer();
  assert.strictEqual(lastSignal.aborted,true,`${path}: hung request was not aborted`);
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(api.state.requestInFlight,false,`${path}: abort rejection did not release inflight guard`);
  assert.strictEqual([...timers.values()].filter(fn=>fn===api.loader).length,1,`${path}: abort did not leave exactly one poll timer`);
  api.interaction.pointerDown=true;
  windowListeners.focus();
  assert.strictEqual(api.interaction.pointerDown,false,`${path}: focus recovery did not release stale pointer state`);
  assert.strictEqual(fetchCalls,2,`${path}: focus did not immediately recover polling`);
  windowListeners.online();windowListeners.pageshow();documentListeners.visibilitychange();
  assert.strictEqual(fetchCalls,2,`${path}: recovery events overlapped an in-flight request`);
  resolveFetch({ok:false,status:503});
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  assert.strictEqual(api.state.requestInFlight,false,`${path}: recovery request did not release inflight guard`);
  assert.strictEqual([...timers.values()].filter(fn=>fn===api.loader).length,1,`${path}: recovery scheduled duplicate poll timers`);
  const retry=[...timers.values()].find(fn=>fn===api.loader);retry();
  assert.strictEqual(fetchCalls,3,`${path}: scheduled polling did not continue after recovery failure`);
  // Default expiry uses an exact 15-day window; valid user selections survive polling.
  selection={isCollapsed:true,rangeCount:0,toString(){return "";}};
  api.interaction.pointerDown=false;
  const expiryBase=snapshot(0), dayMs=86400*1000;
  const showExpiries=(offsets,selected=null)=>{
    api.state.snapshot={...expiryBase,contracts:offsets.map((offset,index)=>({...expiryBase.contracts[0],symbol:`EXPIRY-${index}`,expiry_ms:expiryBase.server_time_ms+offset}))};
    api.state.receivedPerf=now;api.state.contractsCache=null;api.state.selectedExpiry=selected;api.render();
    return api.state.selectedExpiry;
  };
  const dates=[-dayMs,0,dayMs,7*dayMs,15*dayMs,15*dayMs+1000,30*dayMs];
  assert.strictEqual(showExpiries(dates),expiryBase.server_time_ms+15*dayMs,`${path}: default must select latest expiry <=15 days`);
  assert.strictEqual(showExpiries([dayMs,7*dayMs,15*dayMs+1000]),expiryBase.server_time_ms+7*dayMs,`${path}: must exclude expiry one second beyond 15 days`);
  assert.strictEqual(showExpiries(dates,expiryBase.server_time_ms+dayMs),expiryBase.server_time_ms+dayMs,`${path}: refresh must preserve manual near expiry`);
  assert.strictEqual(showExpiries(dates,expiryBase.server_time_ms+30*dayMs),expiryBase.server_time_ms+30*dayMs,`${path}: refresh must preserve manual far expiry`);
  assert.strictEqual(showExpiries(dates,expiryBase.server_time_ms-dayMs),expiryBase.server_time_ms+15*dayMs,`${path}: expired selection must use new default`);
  assert.strictEqual(showExpiries([20*dayMs,30*dayMs]),expiryBase.server_time_ms+20*dayMs,`${path}: empty 15-day window falls back to nearest available expiry`);
  assert.strictEqual(showExpiries([-dayMs,0]),null,`${path}: expired-only catalog must have no selection`);
}

async function main() {
for (const path of ["web/desktop/app.js","web/mobile/mobile.js"]) await harness(path);
for(const view of ["price","ranking","guide","invalid"])await harness("web/mobile/mobile.js",view);
await harness("web/mobile/mobile.js","ranking",true);
await harness("web/mobile/mobile.js","price",false,{selectedExpiry:1_700_000_000_000+2*86400*1000,priceSide:"CALL",priceStrikes:{CALL:84500,PUT:90000},rankingSide:"PUT",rankingRange:"3_7",rankingSortKey:"strike",rankingSortDirection:"asc",rankingPage:2});
await harness("web/mobile/mobile.js","chain",false,{selectedExpiry:"bad",priceSide:"BAD",priceStrikes:{CALL:-1,PUT:"90000"},rankingSide:"BAD",rankingRange:"BAD",rankingSortKey:"BAD",rankingSortDirection:"BAD",rankingPage:0});
const desktop = fs.readFileSync("web/desktop/index.html","utf8");
const mobile = fs.readFileSync("web/mobile/index.html","utf8");
const desktopJs = fs.readFileSync("web/desktop/app.js","utf8");
const mobileJs = fs.readFileSync("web/mobile/mobile.js","utf8");
const desktopCss = fs.readFileSync("web/desktop/style.css","utf8");
const mobileCss = fs.readFileSync("web/mobile/mobile.css","utf8");
const guideJs = fs.readFileSync("web/shared/guide.js","utf8");
const guideCss = fs.readFileSync("web/shared/guide.css","utf8");
assert((desktop.match(/<th/g)||[]).length >= 20 && desktop.includes('id="priceAnnualHead"><span class="nowrap-label">Covered Call</span><br>年化'));
assert((mobile.match(/<th/g)||[]).length >= 20 && mobile.includes('id="priceAnnualHead"><span class="nowrap-label">Covered Call</span><br>年化'));
assert(desktopJs.includes('colspan="7"') && desktopJs.includes('colspan="5"'));
assert(mobileJs.includes('colspan="7"') && mobileJs.includes('colspan="5"'));
for(const html of [desktop,mobile]){assert(html.includes('id="priceSideFilter"'));assert((html.match(/<col class="price-/g)||[]).length===2&&html.includes('<col class="metric-annual"><col class="metric-period"><col class="metric-prob"><col class="price-remaining">'));assert(html.includes('<th>行权概率</th><th>剩余时间</th>'));}
assert(desktop.includes('id="strikeGroupButtons"')&&desktop.includes('id="strikeButtons"')&&desktop.includes('id="currentStrike"')&&!desktop.includes('id="strikeSpotValue"')&&!desktop.includes('id="strikeSelect"'));
assert(desktop.includes('id="currentStrikeLabel" class="current-strike"')&&!/<section id="priceView"[\s\S]*?<h2>价格年化<\/h2>/.test(desktop));
for(const html of[desktop,mobile]){const priceSection=html.slice(html.indexOf('<section id="priceView"'),html.indexOf('<section id="rankingView"'));assert(priceSection.includes('id="priceSideFilter"')&&!/<span>方向<\/span>[\s\S]*?id="priceSideFilter"/.test(priceSection),"price direction label must be removed while buttons remain");}
assert(mobile.includes('id="strikeTrigger"')&&mobile.includes('id="strikeMenu" class="strike-menu hidden"')&&!mobile.includes('<select id="strikeSelect"')&&!mobile.includes('id="strikeButtons"')&&!mobile.includes('id="strikeGroupButtons"'));
assert(mobile.includes('id="expiryTrigger"')&&mobile.includes('id="expiryMenu" class="picker-menu expiry-menu hidden"')&&!mobile.includes('id="expirySelect"'));
assert(mobile.includes('<h1 class="btc-price">BTC：<strong id="indexPrice">—</strong></h1>')&&mobile.includes('<section class="top-status" aria-label="数据状态">')&&!mobile.slice(mobile.indexOf("<main>"),mobile.indexOf('<div id="notice"')).includes('class="status"'));
for(const id of["fetchedAt","countdown","health"])assert.strictEqual((mobile.match(new RegExp(`id="${id}"`,"g"))||[]).length,1,`mobile ${id} must remain unique after moving status into the header`);
assert(!desktop.includes("data-probability-symbol") && !mobile.includes("data-probability-symbol"));
assert(!desktopJs.includes("probabilityDetails") && !mobileJs.includes("probabilityDetails"));
assert(desktopJs.includes('c.time_value_status==="positive" && Number.isFinite(c.annualized_pct)') && mobileJs.includes('c.time_value_status==="positive"&&Number.isFinite(c.annualized_pct)'));
assert(!desktopJs.includes('key==="annualized_pct"?"desc":"asc"')&&!mobileJs.includes('key==="annualized_pct"?"desc":"asc"'));
assert(desktopCss.includes(':root[data-theme="dark"]') && mobileCss.includes(':root[data-theme="dark"]'));
for(const obsolete of ["daysMin","daysMax","strikeMin","strikeMax","yieldMin","moneyFilter","sortFilter"]){assert(!desktop.includes(obsolete)&&!mobile.includes(obsolete)&&!desktopJs.includes(obsolete)&&!mobileJs.includes(obsolete),`obsolete ranking filter remains: ${obsolete}`);}
for(const html of [desktop,mobile]){assert(html.includes('<title>BTC 期权看板</title>')&&html.includes(html===mobile?'<h1 class="btc-price">BTC：<strong id="indexPrice">—</strong></h1>':'<h1>BTC 期权看板</h1>'));assert(html.includes('<span>数据时间</span><b id="fetchedAt">等待数据</b>')&&html.includes('<span>校对状态</span><b id="health"'));assert(html.includes('id="sideFilter" class="segmented-filter" role="group"')&&html.includes('aria-pressed="true" data-value="CALL"'));assert(html.includes('id="expiryRange" class="segmented-filter" role="group"')&&html.includes('data-value="LT3"')&&html.includes('data-value="3_7"')&&html.includes('data-value="GT60"'));assert(!html.includes('<select id="sideFilter"')&&!html.includes('<select id="expiryRange"')&&!html.includes('role="radio"'));assert(html.includes('id="rankingPrev"')&&html.includes('id="rankingNext"')&&html.includes('id="rankingPages"'));assert((html.match(/data-sort=/g)||[]).length===5);assert(!html.includes('data-sort="symbol"')&&!html.includes('data-sort="remaining_seconds"')&&!html.includes('class="rank-symbol"')&&!html.includes('class="rank-remaining"'));assert(!html.includes("（中国）")&&!html.includes("最近成功获取")&&!html.includes("健康状态")&&!html.includes(">状态<"));}
assert(!desktop.includes("<th>方向</th>")&&!mobile.includes("<th>方向</th>"));
assert(!mobile.includes('<details class="filter-box">')&&mobile.includes('<div class="filter-box"><div id="filters">'));
assert(desktop.includes('<th aria-sort="descending"><button type="button" class="sort-button" data-sort="annualized_pct">')&&mobile.includes('<th aria-sort="descending"><button type="button" class="sort-button" data-sort="annualized_pct">'));
assert(!desktopJs.includes("（中国）")&&!mobileJs.includes("（中国）"));
assert(!desktopJs.includes("天＋")&&!mobileJs.includes("天＋"));
assert(!desktop.includes("按行权价比较各到期日")&&!mobile.includes("同一行权价按到期日"));
for(const html of [desktop,mobile]){assert(!html.includes('data-view="guide"')&&!html.includes('id="guideView"')&&!html.includes('/guide.js')&&!html.includes('/guide.css'));assert(!html.includes('class="calculation-notes"')&&!html.includes('<summary>单期收益率</summary>'));}
for(const html of [desktop,mobile]){assert(!html.includes('data-guide-mode="readonly"')&&!html.includes('id="guideEdit"')&&!html.includes('id="guideSave"')&&!html.includes('id="guideCancel"')&&!html.includes('id="guideRefresh"'));}
assert(desktopJs.includes('["chain","price","ranking"]')&&mobileJs.includes('["chain","price","ranking"]'));
assert(guideJs.includes('fetch(apiPath("/api/options-guide"), {...options, signal:controller.signal})')&&guideJs.includes('const apiPath=path=>'));
assert(guideJs.includes('nodes.meta.textContent = `更新于 ${updatedText(guide.updated_at)}`')&&!guideJs.includes('版本 ${guide.revision}'));
assert(guideJs.includes('return `${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`'));
assert(guideJs.includes('error?.status === 409')&&guideJs.includes('保存冲突')&&guideJs.includes('JSON.stringify({sections})'));
assert(guideJs.includes('async function requestGuide(options = {})')&&guideJs.includes('const REQUEST_TIMEOUT_MS = 8000')&&guideJs.includes('payload = await response.json()'));
assert(guideJs.includes('nodes.save?.classList.toggle("hidden", !enabled)'));
const saveGuideSource=guideJs.slice(guideJs.indexOf("async function saveGuide"),guideJs.indexOf('nodes.refresh?.addEventListener'));
assert(saveGuideSource.includes('`保存失败：${error.message}`')&&!/catch \(error\) \{[^}]*state\.draft/s.test(saveGuideSource),"failed save must show the backend reason and preserve the editable draft");
assert(guideJs.includes('title.maxLength = 100')&&guideJs.includes('body.maxLength = 6000')&&guideJs.includes('topics.length <= 1'));
assert(guideJs.includes('body.textContent = topic.body')&&guideJs.includes('summary.textContent = topic.title')&&!guideJs.includes('innerHTML'));
assert(guideCss.includes('white-space:pre-wrap')&&guideCss.includes('@media(max-width:350px)')&&mobileCss.includes('nav{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px}')&&!mobileCss.includes('@media(max-width:390px){nav{grid-template-columns:repeat(2,minmax(0,1fr))}'));
assert((mobile.match(/<span class="nowrap-label">Covered Call<\/span><br>年化/g)||[]).length===2);
assert(mobileCss.includes(".chain th.annual-column{font-size:clamp(11px,2.8vw,12px)") && mobileCss.includes(".tv-warning{display:block;max-width:100%;white-space:normal;overflow-wrap:anywhere;color:var(--green);font-size:clamp(11px,2.8vw,12px)"));
assert(desktopCss.includes("max-width:2400px") && desktopCss.includes(".chain-table{width:1200px;min-width:1200px;max-width:1200px"));
assert(desktopCss.includes(".ranking-table{width:850px;min-width:850px;table-layout:fixed;margin-inline:auto}"));
assert(desktopCss.includes("col.metric-annual{width:210px}") && desktopCss.includes("col.metric-prob{width:150px}"));
assert(!desktopCss.includes(".chain-table{width:980px") && !mobileCss.includes(".chain{width:770px") && mobileCss.includes("max-height:65vh"));
assert(mobileCss.includes(".chain th:nth-child(2){background:var(--soft)}"),"mobile second sticky header must be opaque");
assert(mobileCss.includes(".chain{width:592px;min-width:592px;max-width:592px") && mobileCss.includes(".chain{width:540px;min-width:540px;max-width:540px"));
assert(mobileCss.includes("position:sticky;left:0;right:0") && mobileCss.includes(".chain th.strike-cell{top:0;z-index:9}"));
assert(mobileJs.includes('<td colspan="3"></td><td class="strike-cell">') && !mobileJs.includes('<td colspan="7"><span id="mobileSpot"'));
assert(mobileCss.includes(".chain td.annual-column .annual-only,.chain td.period-column strong{display:block;max-width:100%;white-space:normal;overflow-wrap:anywhere;word-break:break-word}"));
assert(desktopCss.includes('.segmented-filter button[aria-pressed="true"]')&&mobileCss.includes('.segmented-filter button[aria-pressed="true"]'));
assert(desktopCss.includes('.strike-option-row{display:grid')&&desktopCss.includes('button.strike-below{background:#e8f7ef')&&desktopCss.includes('button.strike-above{background:#ffeded')&&desktopCss.includes(':root[data-theme="dark"] .strike-buttons button.strike-below'));
assert(!desktopCss.includes(".strike-spot")&&fs.readFileSync('web/shared/period-return.css','utf8').includes('font-variant-numeric:tabular-nums'));
assert(mobileCss.includes('@media(max-width:350px){.ranking-pagination{flex-wrap:nowrap;gap:1px}')&&mobileCss.includes('.ranking-pagination .page-arrow{flex:0 0 30px;min-width:30px}'));
assert(desktopCss.includes('.price-yield-table{width:min(725px,100%);min-width:620px;max-width:725px;margin-inline:auto}')&&mobileCss.includes('.price-yield-table,.ranking-table{width:100%;min-width:0;max-width:none;margin-inline:0;table-layout:fixed'));
assert(desktopCss.includes('#sideFilter{width:190px;max-width:100%}')&&mobileCss.includes('#sideFilter{width:160px;max-width:100%}')&&mobileCss.includes('min-width:56px;min-height:44px'));
assert(desktopCss.includes('.strike-buttons{display:flex;flex-wrap:wrap;align-items:center')&&desktopCss.includes('overflow:visible')&&desktopCss.includes('.price-controls{display:grid;gap:12px;width:100%')&&desktopCss.includes('.strike-group-buttons button[aria-pressed="true"]{background:#dce9ff')&&mobileCss.includes('.strike-menu{position:absolute;right:0')&&mobileCss.includes('max-height:270px')&&mobileCss.includes('min-height:44px'));
assert(desktopCss.includes('.strike-group-buttons{display:flex;flex-wrap:wrap')&&desktopCss.includes('.filters{grid-template-columns:190px minmax(0,1fr)')&&desktopCss.includes('.current-strike.below-spot{color:var(--green)}')&&desktopCss.includes('.current-strike.above-spot{color:var(--red)}'));
assert(mobileCss.includes('.price-controls{display:flex;align-items:flex-end;justify-content:flex-start')&&mobileCss.includes('.price-side-filter{width:136px')&&mobileCss.includes('.compact-picker,.strike-picker{position:relative;display:grid;justify-items:start'));
assert(mobileCss.includes('.top-status{display:grid;grid-template-columns:1.45fr .8fr 1fr')&&mobileCss.includes('padding:calc(8px + env(safe-area-inset-top))')&&mobileCss.includes('.expiry-picker>button>span:first-child{margin-left:0;margin-right:auto;text-align:left}')&&mobileCss.includes('.expiry-menu button{text-align:left}'));
assert(mobileCss.includes('.price-yield-table col.price-date{width:22%}')&&mobileCss.includes('.ranking-table col.rank-date{width:22%}')&&mobileCss.includes('.compact-date{white-space:normal!important;overflow-wrap:normal;word-break:keep-all'));
assert((mobileJs.match(/replace\("-","-<wbr>"\)/g)||[]).length===2,"mobile five-column dates need one deliberate YYYY-/MM-DD break opportunity");
assert(mobileJs.includes('$("strikeTrigger").addEventListener("keydown"')&&mobileJs.includes('handlePickerKeys(event,"strikeMenu","strikeTrigger",closeStrikeMenu)')&&mobileJs.includes('selected.focus?.()'),"strike picker must share the expiry picker keyboard and focus path");
assert(guideJs.includes('nodes.refresh?.addEventListener')&&(guideJs.match(/if \(nodes\.refresh\)/g)||[]).length>=4,"mobile guide must load without a refresh button");
assert(!desktopJs.includes('revealSelectedStrike')&&!desktop.includes('行权价区间（仅展开）')&&!desktop.includes('具体行权价（点击后切换）')&&desktop.includes('id="currentStrikeLabel" class="current-strike">当前行权价：'));
assert(desktopCss.includes(':root[data-theme="dark"] .strike-buttons button[aria-pressed="true"]{background:#315f9e')&&mobileCss.includes(':root[data-theme="dark"] .strike-menu button[aria-selected="true"]{background:#315f9e'));
assert(desktopCss.includes('.status-grid{grid-template-columns:260px 220px 220px;justify-content:start}')&&desktop.indexOf('id="fetchedAt"')<desktop.indexOf('id="countdown"')&&desktop.indexOf('id="countdown"')<desktop.indexOf('id="health"'));
console.log("UI strategy tables, guide loading/editing boundaries and narrow-screen layout: PASS");
}

main().catch(error=>{console.error(error);process.exitCode=1;});

