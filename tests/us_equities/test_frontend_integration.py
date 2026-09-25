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

    def test_shared_theme_key_and_market_tabs(self):
        for path in (ROOT / "web" / "desktop" / "app.js", ROOT / "web" / "mobile" / "mobile.js", WEB / "app.js"):
            self.assertIn("options-panel-theme", path.read_text(encoding="utf-8"))
        for path in (ROOT / "web" / "desktop" / "index.html", ROOT / "web" / "mobile" / "index.html", WEB / "index.html"):
            source = path.read_text(encoding="utf-8")
            self.assertIn('class="market-tabs"', source)
            self.assertIn("BTC", source)
            self.assertIn("美股", source)

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
