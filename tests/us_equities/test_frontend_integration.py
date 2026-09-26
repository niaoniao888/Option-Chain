import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web" / "us-equities"


class UnifiedFrontendTests(unittest.TestCase):
    def run_node(self, script: str):
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8",
            capture_output=True, check=True, timeout=10,
        )
        return json.loads(result.stdout)

    def test_base_path_navigation_and_explicit_mobile_route(self):
        result = self.run_node(r'''
global.location={pathname:"/options/us-equities/desktop/"};
global.window={location:global.location,matchMedia:()=>({matches:false})};
const h=require("./web/us-equities/app.js");
const desktop={base:h.panelBasePath(),api:h.snapshotRequestUrl("AAPL"),btc:h.marketPath("bitcoin","desktop"),mobile:h.isMobileView()};
global.location.pathname="/options/us-equities/mobile/";
const mobile={base:h.panelBasePath(),us:h.marketPath("us-equities","mobile"),mobile:h.isMobileView()};
process.stdout.write(JSON.stringify({desktop,mobile,remembered:h.resolvedSymbol("GOOG",["SPCX","GOOG"]),fallback:h.resolvedSymbol("REMOVED",["SPCX","GOOG"])}));
''')
        self.assertEqual(result["desktop"], {
            "base": "/options",
            "api": "/options/api/v1/us-equities/snapshot?symbol=AAPL",
            "btc": "/options/bitcoin/desktop/",
            "mobile": False,
        })
        self.assertEqual(result["mobile"], {
            "base": "/options", "us": "/options/us-equities/mobile/", "mobile": True,
        })
        self.assertEqual(result["remembered"], "GOOG")
        self.assertEqual(result["fallback"], "SPCX")

    def test_public_page_is_read_only_and_admin_keeps_token_in_memory(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        app = (WEB / "app.js").read_text(encoding="utf-8")
        guide = (WEB / "guide.js").read_text(encoding="utf-8")
        admin = (WEB / "admin.js").read_text(encoding="utf-8")
        self.assertNotIn('id="watchlistForm"', html)
        self.assertNotIn('id="guideEdit"', html)
        self.assertNotIn('method:"POST"', app)
        self.assertNotIn('method:"DELETE"', app)
        self.assertNotIn('method:"PUT"', guide)
        self.assertIn('history.replaceState', admin)
        self.assertIn('Authorization:`Bearer ${token}`', admin)
        self.assertIn('"If-Match":watchRevision', admin)
        self.assertIn('"If-Match":guideDocument.revision', admin)
        self.assertIn('error.status===409', admin)

    def test_metadata_failure_keeps_complete_snapshot_and_recovers(self):
        result = self.run_node(r'''
const vm=require("vm"),fs=require("fs"),ctx={module:{exports:{}},console};vm.createContext(ctx);
vm.runInContext(fs.readFileSync("./web/us-equities/app.js","utf8"),ctx);
vm.runInContext(`state.initialized=true;state.symbol="GOOG";state.watchlist=["GOOG"];state.watchRevision="w1";state.sourceSnapshot={contracts:[{contract_symbol:"saved"}]};let calls=0;let failing=true;jsonFetch=async path=>{if(failing)throw new Error("temporary metadata timeout");return path.includes("watchlist")?{symbols:["GOOG"],revision:"w1"}:{};};loadSnapshot=async()=>{calls++};schedulePoll=()=>{};emptySnapshot=()=>{throw new Error("snapshot cleared")};`,ctx);
(async()=>{await vm.runInContext("pollLoop()",ctx);const failed=vm.runInContext("({rows:state.sourceSnapshot.contracts.length,warning:!!state.metadataError,calls})",ctx);vm.runInContext("failing=false",ctx);await vm.runInContext("pollLoop()",ctx);const recovered=vm.runInContext("({rows:state.sourceSnapshot.contracts.length,warning:!!state.metadataError,calls})",ctx);process.stdout.write(JSON.stringify({failed,recovered}));})();
''')
        self.assertEqual(result["failed"], {"rows": 1, "warning": True, "calls": 1})
        self.assertEqual(result["recovered"], {"rows": 1, "warning": False, "calls": 2})

    def test_guide_sync_is_single_flight_timeout_and_recovers(self):
        result = self.run_node(r'''
const nodes=new Map(),listeners={},timers=[],intervals=[];let calls=0,pending;
const element=()=>({textContent:"",firstChild:null,dataset:{},querySelectorAll:()=>[],contains:()=>false,appendChild(){},classList:{contains:()=>false}});
global.document={hidden:false,getElementById:id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)},addEventListener:(name,fn)=>listeners[name]=fn};
global.window={matchMedia:()=>({matches:false}),getSelection:()=>null,addEventListener:(name,fn)=>listeners[name]=fn};global.localStorage={getItem:()=>null};
global.setTimeout=fn=>{timers.push(fn);return timers.length};global.clearTimeout=()=>{};global.setInterval=fn=>{intervals.push(fn)};
global.fetch=(_url,options)=>{calls++;return new Promise((resolve,reject)=>{pending=resolve;options.signal.addEventListener("abort",()=>reject(Object.assign(new Error("aborted"),{name:"AbortError"})))})};
require("./web/us-equities/guide.js");
(async()=>{intervals[0]();listeners["us-guide-visible"]();const overlappingCalls=calls;timers[0]();await new Promise(setImmediate);const timeoutNotice=nodes.get("guideMessage").textContent;intervals[0]();pending({ok:true,json:async()=>({revision:"new",sections:[],updated_at:"built-in"})});await new Promise(setImmediate);process.stdout.write(JSON.stringify({overlappingCalls,calls,timeout:timeoutNotice.includes("超时"),recovered:nodes.get("guideMeta").textContent.includes("内置初稿")}));})();
''')
        self.assertEqual(result, {"overlappingCalls": 1, "calls": 2, "timeout": True, "recovered": True})

    def test_restored_ranking_filters_show_selected_buttons(self):
        result = self.run_node(r'''
const vm=require("vm"),fs=require("fs"),nodes={sideFilter:{value:""},termFilter:{value:""}};
const make=(key,value)=>{const b={dataset:{[key]:value},active:false};b.classList={toggle(_name,on){b.active=on}};return b};
const sides=[make("sideFilter","CALL"),make("sideFilter","PUT")],terms=[make("termFilter","LT3"),make("termFilter","7_30")];
const ctx={module:{exports:{}},console,document:{getElementById:id=>nodes[id],querySelectorAll:s=>s.includes("side-filter")?sides:terms}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync("./web/us-equities/app.js","utf8"),ctx);
vm.runInContext(`activateView=()=>{};state.symbol="AAPL";loadFilters(()=>JSON.stringify({sideFilter:"PUT",termFilter:"7_30",mobileView:"ranking"}))`,ctx);
process.stdout.write(JSON.stringify({sides:sides.map(x=>x.active),terms:terms.map(x=>x.active)}));
''')
        self.assertEqual(result, {"sides": [False, True], "terms": [False, True]})

    def test_shared_theme_key_and_market_tabs(self):
        for path in (ROOT / "web" / "desktop" / "app.js", ROOT / "web" / "mobile" / "mobile.js", WEB / "app.js"):
            self.assertIn("options-panel-theme", path.read_text(encoding="utf-8"))
        for path in (ROOT / "web" / "desktop" / "index.html", ROOT / "web" / "mobile" / "index.html", WEB / "index.html"):
            source = path.read_text(encoding="utf-8")
            self.assertIn('class="market-tabs"', source)
            self.assertIn("BTC", source)
            self.assertIn("美股", source)

    def test_three_market_views_have_no_guide_loader_and_accessible_theme_icons(self):
        for path in (ROOT / "web" / "desktop" / "index.html", ROOT / "web" / "mobile" / "index.html", WEB / "index.html"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn('data-view="guide"', source)
            self.assertNotIn('id="guideView"', source)
            self.assertNotIn('/guide.js', source)
            self.assertNotIn('/guide.css', source)
            self.assertIn('aria-label="浅色"', source)
            self.assertIn('aria-label="深色"', source)
            self.assertEqual(source.count('<svg '), 2)
            self.assertIn('market-shell.css?v=20260926-ui9', source)
            self.assertIn('>BTC期权</a>', source)
            self.assertIn('>美股期权</a>', source)

    def test_compact_market_status_has_only_three_public_states(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "web" / "shared" / "market-shell.css").read_text(encoding="utf-8")
        app = (WEB / "app.js").read_text(encoding="utf-8")
        for removed in ("modeLabel", "mobileSource", "validationDetail", "mobileValidationDetail"):
            self.assertNotIn(f'id="{removed}"', html)
            self.assertNotIn(f'$("{removed}")', app)
        self.assertNotIn('id="fetchHealth"', html)
        self.assertNotIn('$("fetchHealth")', app)
        self.assertNotIn("IEX / Indicative", html)
        self.assertNotIn("标准可计算", app)
        self.assertIn('.hero~main,.us-market main{max-width:2400px', css)
        self.assertIn('.us-market .mobile-status{grid-template-columns:repeat(2,minmax(0,1fr))', css)
        self.assertIn('.hero-status>div,.header-status>div+.header-status>div{border-left:1px solid var(--line);padding-left:14px}', css)
        self.assertIn('class="desktop-expiry-detail">到期时间：', app)
        self.assertIn('class="mobile-expiry-detail">到期时间：', app)

        result = self.run_node(r'''
const vm=require("vm"),fs=require("fs");
const ids=["marketStatus","dataTime","refreshCountdown","validationStatus","underlyingPrice","mobileSymbol","mobilePrice","mobileMarket","mobileDataTime","mobileRefresh","mobileValidation","mobilePending","rankingView","rankingCount","notice"];
const nodes=new Map(ids.map(id=>[id,{textContent:"",dataset:{},classList:{toggle(){}}}]));
const ctx={module:{exports:{}},console,document:{getElementById(id){if(!nodes.has(id))throw new Error(`unexpected node access: ${id}`);return nodes.get(id)}}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync("./web/us-equities/app.js","utf8"),ctx);
function render(status,mode){vm.runInContext(`state.symbol="AAPL";state.snapshot={market_status:${JSON.stringify(status)},mode:${JSON.stringify(mode)},state:"ready",fetch_health:"healthy",schedule_state:"waiting",next_refresh_seconds:5,fetched_at:"2026-09-26T06:07:08Z",contracts:[]};renderStatus()`,ctx);return{desktop:nodes.get("marketStatus").textContent,mobile:nodes.get("mobileMarket").textContent,time:nodes.get("dataTime").textContent,countdown:nodes.get("refreshCountdown").textContent,validation:nodes.get("validationStatus").textContent,tone:nodes.get("validationStatus").dataset.tone}}
process.stdout.write(JSON.stringify({open:render("OPEN","live"),closed:render("CLOSED","close_reference"),unknown:render("UNVERIFIED","unavailable")}));
''')
        self.assertEqual(result, {
            "open": {"desktop": "盘中", "mobile": "盘中", "time":"09-26 14:07:08", "countdown":"5秒", "validation":"正常", "tone":"ok"},
            "closed": {"desktop": "休市", "mobile": "休市", "time":"09-26 14:07:08", "countdown":"5秒", "validation":"正常", "tone":"ok"},
            "unknown": {"desktop": "未确认", "mobile": "未确认", "time":"09-26 14:07:08", "countdown":"5秒", "validation":"正常", "tone":"ok"},
        })

    def test_admin_boots_with_watchlist_document_without_shadowing_dom(self):
        result = self.run_node(r'''
const elements=new Map();
function node(){return{children:[],className:"",textContent:"",value:"",disabled:false,classList:{toggle(){}},append(...items){this.children.push(...items)},appendChild(item){this.children.push(item);return item},replaceChildren(...items){this.children=items},setAttribute(){}}}
global.document={getElementById(id){if(!elements.has(id))elements.set(id,node());return elements.get(id)},createElement(){return node()}};
global.location={hash:"#token="+"x".repeat(48),pathname:"/",search:""};global.history={replaceState(){}};
global.fetch=async path=>({ok:true,status:200,json:async()=>path==="/api/health"?{configured:true}:path==="/api/watchlist"?{revision:"w1",symbols:["AAPL"]}:{revision:"g1",updated_at:"built-in",sections:[{id:"personal",title:"个人笔记",topics:[{id:"notes",title:"观察",body:"正文"}]}]}});
require("./web/us-equities/admin.js");
setTimeout(()=>process.stdout.write(JSON.stringify({health:elements.get("health").textContent,watchRows:elements.get("watchlist").children.length,guideRows:elements.get("guide").children.length})),20);
''')
        self.assertEqual(result, {"health": "Alpaca 已配置", "watchRows": 1, "guideRows": 1})


if __name__ == "__main__":
    unittest.main()
