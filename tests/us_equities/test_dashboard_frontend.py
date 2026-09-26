import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

class FrontendHelperTests(unittest.TestCase):
    def test_detail_body_is_lazy_and_escapes_current_values(self):
        script = r'''
const assert=require('assert'),h=require('./web/us-equities/app.js');
const first={contract_symbol:'<old>',bid:1,ask:2,contract_metadata:{metadata_fetched_at:'2026-09-25T00:00:00Z',deliverables:[{symbol:'<tag>'}]}};
const closed=h.detail(first,'chain:<old>','<b>summary</b>');
assert(closed.includes('<summary'));assert(!closed.includes('detail-body'));assert(!closed.includes('Bid / Ask'));
const updated={...first,contract_symbol:'<new>',bid:3,contract_metadata:{...first.contract_metadata,multiplier:'<script>'}};
const body=h.detailBodyHtml(updated);
assert(body.includes('&lt;new&gt;'));assert(body.includes('&lt;script&gt;'));assert(body.includes('合约资料获取'));assert(!body.includes('<script>'));
'''
        subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True)

    def test_chain_formatter_fixed_term_signature_and_local_boundary_timer(self):
        script = r'''
const assert=require('assert'),h=require('./web/us-equities/app.js');
const row={contract_symbol:'C',side:'CALL',strike:100,bid:1,ask:2,period_return_pct:1.25,annualized_pct:20,exercise_probability_pct:50,calculation_status:'calculated',ranking_eligible:true,close_reference_eligible:false,remaining_seconds:3.0001*86400,expires_at_utc:'2026-09-28T12:00:08.640Z'};
const cell=h.metricCell([row],'chain','period_return_pct',(_value,whole)=>whole===row?'ROW_OK':'ROW_MISSING');
assert(cell.includes('ROW_OK'));assert(!cell.includes('ROW_MISSING'));
const divider=h.spotDividerHtml(200);assert.equal((divider.match(/<td/g)||[]).length,7);assert.equal(h.shouldAppendSpotDivider(3,true,false),true);assert.equal(h.shouldAppendSpotDivider(3,true,true),false);assert.equal(h.shouldAppendSpotDivider(0,true,false),false);
const snapshot={state:'ready',fetch_health:'healthy',mode:'live',market_status:'OPEN',server_time:'2026-09-25T00:00:00Z',fetched_age_seconds:0,contracts:[row]};
const filter={side:'CALL',bucket:'3_7'};
const before=h.projectionSignature(snapshot,'ranking',null,null,filter);
const afterSnapshot={...snapshot,contracts:[{...row,remaining_seconds:2.9999*86400}]};
const after=h.projectionSignature(afterSnapshot,'ranking',null,null,filter);
assert.notEqual(before,after);
const now=Date.parse('2026-09-25T00:00:00Z');
let timerCallback=null,timerDelay=null,networkRequests=1,localProjects=0;
const quoteBoundary={...snapshot,contracts:[{...row,quote_valid_until_utc:new Date(now+2000).toISOString()}]};
const timer=h.armLocalBoundary(quoteBoundary,now,null,(callback,delay)=>{timerCallback=callback;timerDelay=delay;return 7},()=>{localProjects+=1});
assert.equal(timer,7);assert.equal(timerDelay,2001);assert.equal(networkRequests,1);
timerCallback();assert.equal(localProjects,1);assert.equal(networkRequests,1);
'''
        subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True)

    def test_version_merge_and_local_time_gates(self):
        script = r'''
const assert=require('assert'),h=require('./web/us-equities/app.js');
const base={snapshot_version:'boot:1',server_time:'2026-09-24T20:00:00Z',fetched_at:'2026-09-24T19:58:01Z',next_refresh_seconds:60,fetched_age_seconds:0,state:'ready',fetch_health:'healthy',market_status:'OPEN',market_status_valid_until_utc:'2026-09-24T21:00:00Z',contracts:[{contract_symbol:'C',calculation_status:'calculated',annualized_pct:12,period_return_pct:1,exercise_probability_pct:60,expires_at_utc:'2026-09-25T20:00:00Z',quote_valid_until_utc:'2026-09-24T20:00:02Z',ranking_eligible:true,close_reference_eligible:false}]};
const merged=h.mergeSnapshotPayload(base,{unchanged:true,snapshot_version:'boot:1',server_time:'2026-09-24T20:00:01Z',state:'degraded',fetch_health:'failed',mode:'unavailable'});
assert.strictEqual(merged.contracts,base.contracts);assert.equal(merged.state,'degraded');
assert.equal(h.mergeSnapshotPayload(null,{unchanged:true}),null);
const exact=h.projectSnapshotAt({...base,fetched_at:'2026-09-24T20:00:00Z'},Date.parse('2026-09-24T20:00:02Z'));
assert.equal(exact.contracts[0].ranking_eligible,true);assert.equal(exact.mode,'live');
const late=h.projectSnapshotAt({...base,fetched_age_seconds:120},Date.parse('2026-09-24T20:00:00Z'));
assert.equal(late.fetch_health,'stale');assert.equal(late.mode,'unavailable');assert.equal(late.contracts[0].ranking_eligible,false);
const expired=h.projectSnapshotAt({...base,fetched_at:'2026-09-25T19:59:00Z'},Date.parse('2026-09-25T20:00:00Z'));
assert.equal(expired.contracts[0].calculation_status,'expired');assert.equal(expired.contracts[0].annualized_pct,null);assert.equal(expired.contracts[0].exercise_probability_pct,null);
const closed={...base,market_status:'CLOSED',fetched_at:'2026-09-24T20:00:00Z',contracts:[{...base.contracts[0],quote_valid_until_utc:'2026-09-24T19:59:00Z',close_reference_eligible:true}]};
assert.equal(h.projectSnapshotAt(closed,Date.parse('2026-09-24T20:00:01Z')).mode,'close_reference');
const transitioned=h.projectSnapshotAt({...closed,market_status_valid_until_utc:'2026-09-24T20:00:01Z'},Date.parse('2026-09-24T20:00:01Z'));
assert.equal(transitioned.mode,'unavailable');assert.equal(transitioned.contracts[0].close_reference_eligible,false);
assert.equal(h.snapshotRequestUrl('BRK.B','boot:1'),'/api/v1/us-equities/snapshot?symbol=BRK.B&if_version=boot%3A1');
assert.equal(h.snapshotRequestUrl('SPCX','boot:2','acceptance-0123456789abcdef0123456789abcdef',false,9),'/api/v1/us-equities/snapshot?symbol=SPCX&if_version=boot%3A2&client_id=acceptance-0123456789abcdef0123456789abcdef&active=0&activity_seq=9');
assert.equal(h.projectedServerNow(1000,10,510),1500);
const clonedStorage=new Map([['us-options-client-id','cloned'],['us-options-activity-seq','99']]);global.sessionStorage={getItem:key=>clonedStorage.get(key)??null,setItem:(key,value)=>clonedStorage.set(key,value)};let uuid=0;const firstId=h.createTabClientId(()=>`00000000-0000-4000-8000-${String(++uuid).padStart(12,'0')}`),secondId=h.createTabClientId(()=>`00000000-0000-4000-8000-${String(++uuid).padStart(12,'0')}`);assert.notEqual(firstId,secondId);assert(![firstId,secondId].includes('cloned'));const firstDoc={activitySeq:0},secondDoc={activitySeq:0};assert.deepEqual([h.nextActivitySequence(firstDoc),h.nextActivitySequence(firstDoc),h.nextActivitySequence(secondDoc)],[1,2,1]);assert.equal(clonedStorage.get('us-options-activity-seq'),'99');
assert.equal(h.snapshotCommitAllowed(3,2,'A','A',true),true);assert.equal(h.snapshotCommitAllowed(2,2,'A','A',true),false);assert.equal(h.snapshotCommitAllowed(3,2,'A','B',true),false);assert.equal(h.snapshotCommitAllowed(3,2,'A','A',false),false);
assert.deepEqual([h.pollVisibilityAction(true,false),h.pollVisibilityAction(false,true),h.pollVisibilityAction(false,false)],['pause','defer','poll']);
assert.equal(h.nextLocalBoundaryMilliseconds({...base,fetched_age_seconds:119.5},Date.parse(base.server_time)),500);
const countdown=h.projectSnapshotAt({...base,fetched_at:'2026-09-24T20:00:00Z'},Date.parse(base.server_time)+5000);
assert.equal(countdown.next_refresh_seconds,55);
'''
        subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True)

    def test_stock_names_and_fetch_status(self):
        script = """const assert=require('assert');const h=require('./web/us-equities/app.js');
        assert.equal(h.stockLabel('AAPL'),'AAPL（苹果）');
        assert.equal(h.stockLabel('GOOG'),'GOOG（谷歌）');
        assert.equal(h.stockLabel('UNLISTED'),'UNLISTED');
        assert.equal(h.stockLabel('APPL'),'APPL');
        assert.deepEqual(h.fetchHealthDisplay({fetch_health:'healthy'}),{label:'正常',tone:'ok'});
        assert.equal(h.fetchHealthDisplay({state:'degraded',fetch_health:'healthy'}).tone,'error');
        for (const [health,tone] of [['failed','error'],['stale','warning'],['awaiting_configuration','neutral'],['waiting_for_first_snapshot','neutral'],['unknown','neutral']])assert.equal(h.fetchHealthDisplay({fetch_health:health}).tone,tone);
        """
        subprocess.run(['node','-e',script],cwd=ROOT,check=True,capture_output=True)

    def test_sort_paging_terms_strike_groups_and_modes(self):
        script = r'''
const h=require('./web/us-equities/app.js');
const desc=h.sortRowsNullLast([{v:null,id:'n'},{v:2,id:'b'},{v:5,id:'a'}],'v','desc').map(x=>x.id);
const asc=h.sortRowsNullLast([{v:null,id:'n'},{v:2,id:'b'},{v:5,id:'a'}],'v','asc').map(x=>x.id);
const probability=h.sortRowsNullLast([{exercise_probability_pct:null,id:'n'},{exercise_probability_pct:33.1,id:'b'},{exercise_probability_pct:86.7,id:'a'}],'exercise_probability_pct','desc').map(x=>x.id);
const priceDelta=h.nextPriceSort({key:'expiration_date',direction:'asc'},'delta');
const priceDeltaAgain=h.nextPriceSort(priceDelta,'delta');
process.stdout.write(JSON.stringify({desc,asc,probability,page:h.paginateRows(Array.from({length:23},(_,i)=>i),2),
 terms:[2.99,3,6.99,7,29.99,30,60,60.01].map(h.termBucket),groups:h.strikeGroups([4,1,3,2],2),
 close:h.rowRankingEligible({close_reference_eligible:true},'close_reference'),conflict:h.guideConflictDecision(409),
 live:h.rowRankingEligible({ranking_eligible:true},'live'),custom:h.presetForRange('1','9'),
 metrics:[h.hasDisplayMetric({annualized_pct:null,period_return_pct:null,delta:null}),h.hasDisplayMetric({annualized_pct:0,period_return_pct:null,delta:null})],
 display:h.displayableRows([{strike:1,delta:0,exercise_probability_pct:null},{strike:2,delta:null,exercise_probability_pct:0}]).map(x=>x.strike),
 remaining:[0,59*60,3600,2*86400+5*3600,3*86400,3*86400+1,8*86400].map(h.remainingText),
 month:h.addCalendarMonths('2026-08-31',6),split:h.splitExpiries(['2027-02-28','2027-03-01'],'2026-08-31'),
 chinaDates:['2026-01-16T21:00:00Z','2026-03-13T20:00:00Z','2026-11-27T18:00:00Z','bad','2026-09-25T20:00:00'].map(h.chinaExpiryDate),
 groupLabels:[h.strikeGroupLabel([100]),h.strikeGroupLabel([100,109])],
 priceSorts:[priceDelta,priceDeltaAgain,h.nextPriceSort(priceDeltaAgain,'remaining_seconds')],
 partition:h.partitionStrikes([102,99,100,101],100),missingSpot:h.partitionStrikes([102,99,100],null),
 rawEquality:h.partitionStrikes([100],100.0000001),selectedAcrossSpot:[100,h.partitionStrikes([99,100,101],99.5),h.partitionStrikes([99,100,101],100.5)],
 relative:[h.strikeRelativePct(90,100),h.strikeRelativePct(110,100),h.strikeRelativePct(100,100),h.strikeRelativePct(null,100),h.strikeRelativePct(100,0)],
 sessionDates:['2026-09-24','bad',null].map(h.sessionMonthDay),
 pollMs:[h.cachePollMilliseconds(null),h.cachePollMilliseconds({refresh_policy:{cache_poll_seconds:2.5}}),h.cachePollMilliseconds({refresh_policy:{cache_poll_seconds:0}}),h.cachePollMilliseconds({refresh_policy:{cache_poll_seconds:61}})],
 expiryDisplay:h.expiryDisplay('2026-09-25',[{expiration_date:'2026-09-25',expires_at_utc:'bad'},{expiration_date:'2026-09-25',expires_at_utc:'2026-09-25T20:00:00Z'}])}));'''
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["desc"], ["a", "b", "n"])
        self.assertEqual(payload["asc"], ["b", "a", "n"])
        self.assertEqual(payload["probability"], ["a", "b", "n"])
        self.assertEqual(payload["page"]["rows"], list(range(10, 20)))
        self.assertEqual(payload["terms"], ["LT3","3_7","3_7","7_30","7_30","30_60","30_60","GT60"])
        self.assertEqual(payload["groups"], [[1,2],[3,4]])
        self.assertTrue(payload["close"] and payload["live"])
        self.assertEqual(payload["conflict"], "preserve_draft")
        self.assertEqual(payload["custom"], "CUSTOM")
        self.assertEqual(payload["metrics"], [False, True])
        self.assertEqual(payload["display"], [2])
        self.assertEqual(payload["remaining"], ["已到期","59分钟","1小时","2天5小时","3天0小时","3天","8天"])
        self.assertEqual(payload["month"], "2027-02-28")
        self.assertEqual(payload["split"], {"near":["2027-02-28"],"far":["2027-03-01"],"cutoff":"2027-02-28"})
        self.assertEqual(payload["chinaDates"], ["2026-01-17","2026-03-14","2026-11-28","—","—"])
        self.assertEqual(payload["expiryDisplay"], "2026-09-26")
        self.assertEqual(payload["groupLabels"], ["100", "100–109"])
        self.assertEqual(payload["priceSorts"], [
            {"key":"delta","direction":"desc"}, {"key":"delta","direction":"asc"},
            {"key":"remaining_seconds","direction":"asc"}])
        self.assertEqual(payload["partition"], {
            "spotAvailable":True,"lower":[99,100],"higher":[101,102],"atMoney":100,"all":[99,100,101,102]})
        self.assertEqual(payload["missingSpot"], {
            "spotAvailable":False,"lower":[],"higher":[],"atMoney":None,"all":[99,100,102]})
        self.assertEqual(payload["rawEquality"]["atMoney"], None)
        self.assertEqual(payload["rawEquality"]["lower"], [100])
        self.assertEqual(payload["selectedAcrossSpot"][0], 100)
        self.assertIn(100, payload["selectedAcrossSpot"][1]["higher"])
        self.assertIn(100, payload["selectedAcrossSpot"][2]["lower"])
        self.assertAlmostEqual(payload["relative"][0], -10)
        self.assertAlmostEqual(payload["relative"][1], 10)
        self.assertEqual(payload["relative"][2:], [0,None,None])
        self.assertEqual(payload["sessionDates"], ["09-24","日期未知","日期未知"])
        self.assertEqual(payload["pollMs"], [5000,2500,5000,5000])

    def test_hidden_entries_and_chain_layout_are_not_rendered(self):
        html = (ROOT / "web" / "us-equities" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "web" / "us-equities" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "us-equities" / "style.css").read_text(encoding="utf-8")
        self.assertNotIn('id="unclassifiedPanel"', html)
        self.assertNotIn('class="fixed-guide"', html)
        self.assertNotIn('class="method"', html)
        self.assertNotIn('id="snapshotMeta"', html)
        self.assertNotIn("renderUnclassified", app)
        self.assertIn("width:1050px", css)
        self.assertEqual(html.count("data-price-sort="), 5)
        price_row = app.split("function renderPrice(", 1)[1].split("</tr>", 1)[0]
        self.assertEqual(price_row.count("<td"), 5)
        self.assertNotIn('data-side-filter="ALL"', html)
        self.assertIn('id="priceHead"', html)
        self.assertIn('aria-pressed="true">Call', html)
        self.assertNotIn("1–10", html)
        self.assertNotIn('id="strikeMin"', html)
        self.assertNotIn('id="strikeMax"', html)
        self.assertNotIn('id="yieldMin"', html)
        self.assertNotIn("单股年化排行", html)
        self.assertNotIn('data-sort="contract_symbol"', html)
        self.assertNotIn('$("strikeMin")', app)
        self.assertNotIn('$("strikeMax")', app)
        self.assertNotIn('$("yieldMin")', app)
        self.assertIn('colspan="6"', app)
        self.assertIn("if(!state.initialized)await initializeApp()", app)
        self.assertIn("finally{schedulePoll()}", app)
        self.assertEqual(app.count("state.pollTimer=setTimeout"), 1)

    def test_mobile_preferences_expiry_menu_and_pagination_helpers(self):
        script = r'''
const h=require('./web/us-equities/app.js');
const rows=[
 {expiration_date:'2026-09-26',remaining_seconds:86400},
 {expiration_date:'2026-10-01',remaining_seconds:6*86400},
 {expiration_date:'2026-10-10',remaining_seconds:15*86400},
 {expiration_date:'2026-10-17',remaining_seconds:22*86400}
];
const invalid=h.normalizeStoredFilters({selectedExpiry:'bad',priceSide:'ALL',priceStrikes:{CALL:0,PUT:'2'},priceSort:{key:'secret',direction:'up'},rankingSort:{key:'bad',direction:'asc'},rankingPage:-2,termFilter:'CUSTOM'});
const migrated=h.normalizeStoredFilters({termFilter:'CUSTOM',rankingSort:{key:'delta',direction:'asc'}});
const valid=h.normalizeStoredFilters({selectedExpiry:'2026-10-10',priceSide:'PUT',priceStrikes:{CALL:148.5,PUT:150},priceSort:{key:'delta',direction:'desc'},rankingSort:{key:'strike',direction:'asc'},rankingPage:7,mobileView:'ranking'});
const store=new Map([
 ['us-options-filters:AAPL',JSON.stringify({mobileView:'price',selectedExpiry:'2026-10-10',priceSide:'PUT'})],
 ['us-options-filters:TSLA',JSON.stringify({mobileView:'ranking',selectedExpiry:'2026-10-17',priceSide:'CALL'})],
 ['us-options-mobile-view','guide']
]);
const getter=key=>store.get(key)??null;
const switched=[h.readStoredFiltersForSymbol('AAPL',getter).normalized,h.readStoredFiltersForSymbol('TSLA',getter).normalized,h.readStoredFiltersForSymbol('NVDA',getter).normalized];
const elements={sideFilter:{value:''},termFilter:{value:''},daysMin:{value:''},daysMax:{value:''},customMinWrap:{classList:{toggle(){}}},customMaxWrap:{classList:{toggle(){}}}};
global.document={getElementById:id=>elements[id]};
let actualLoads=0;for(const badGetter of[()=>JSON.stringify(true),()=>'{bad',()=>{throw new Error('blocked')}]){h.loadFilters(badGetter);actualLoads+=1;}
const classes=new Set(['hidden']),classList={contains:x=>classes.has(x),add:x=>classes.add(x),remove:x=>classes.delete(x),toggle(x,on){on?classes.add(x):classes.delete(x)}};
const menu={classList,style:{},optionAvailable:false,querySelector(selector){return selector==='button[role="option"]'&&this.optionAvailable?{}:null}};
const trigger={disabled:false,attrs:{},setAttribute(k,v){this.attrs[k]=v},getBoundingClientRect(){return{bottom:100}}},picker={getBoundingClientRect(){return{top:50}}};
global.window={innerHeight:600};global.document={documentElement:{clientHeight:600},getElementById:id=>({menu,trigger,picker}[id])};
h.togglePicker('menu','trigger','picker',()=>{});const emptyOpen=!classes.has('hidden');menu.optionAvailable=true;let otherClosed=0;h.togglePicker('menu','trigger','picker',()=>{otherClosed+=1});const filledOpen=!classes.has('hidden');
process.stdout.write(JSON.stringify({
 defaultExpiry:h.mobileExpiryDefault(rows.map(x=>x.expiration_date),rows),emptyExpiry:h.mobileExpiryDefault([],rows),invalid,valid,migrated,
 pages:[h.paginationItems(1,2),h.paginationItems(1,10),h.paginationItems(5,10),h.paginationItems(10,10)],
 rankingPages:[h.resolvedRankingPage(7,1,false,false),h.resolvedRankingPage(7,1,false,true),h.resolvedRankingPage(7,2,true,true)],switched,actualLoads,pickerState:{emptyOpen,filledOpen,disabled:trigger.disabled,otherClosed},
 blocked:[h.interactionBlocksRender(),h.interactionBlocksRender({expiryMenuOpen:true}),h.interactionBlocksRender({strikeMenuOpen:true}),h.interactionBlocksRender({pointerDown:true}),h.interactionBlocksRender({editing:true})],
 cutoff:h.chinaExpiryDateTime('2026-11-27T18:00:00Z'),period0:h.periodSummary({strike:100,period_return_pct:0},100),periodMissing:h.periodSummary({strike:100,period_return_pct:null},null)
}));'''
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=True)
        data = json.loads(result.stdout)
        self.assertEqual(data["defaultExpiry"], "2026-10-10")
        self.assertIsNone(data["emptyExpiry"])
        self.assertEqual(data["invalid"]["priceSide"], "CALL")
        self.assertEqual(data["invalid"]["priceStrikes"], {"CALL": None, "PUT": None})
        self.assertEqual(data["invalid"]["termFilter"], "LT3")
        self.assertEqual(data["migrated"]["termFilter"], "LT3")
        self.assertEqual(data["migrated"]["rankingSort"], {"key":"exercise_probability_pct","direction":"asc"})
        self.assertEqual(data["invalid"]["rankingPage"], 1)
        self.assertEqual(data["valid"]["selectedExpiry"], "2026-10-10")
        self.assertEqual(data["valid"]["priceStrikes"], {"CALL": 148.5, "PUT": 150})
        self.assertEqual(data["valid"]["rankingSort"], {"key": "strike", "direction": "asc"})
        self.assertEqual(data["valid"]["mobileView"], "ranking")
        self.assertEqual([(item["mobileView"], item["selectedExpiry"], item["priceSide"]) for item in data["switched"]], [("price","2026-10-10","PUT"),("ranking","2026-10-17","CALL"),("chain",None,"CALL")])
        self.assertEqual(data["actualLoads"], 3)
        self.assertEqual(data["pickerState"], {"emptyOpen":False,"filledOpen":True,"disabled":False,"otherClosed":1})
        self.assertEqual(data["pages"], [[1,2],[1,2,3,"ellipsis",10],[1,"ellipsis",4,5,6,"ellipsis",10],[1,"ellipsis",8,9,10]])
        self.assertEqual(data["rankingPages"], [7,1,2])
        self.assertEqual(data["blocked"], [False,True,True,True,True])
        self.assertEqual(data["cutoff"], "2026-11-28 02:00")
        self.assertIn("0.00%", data["period0"])
        self.assertIn("—", data["periodMissing"])

    def test_mobile_dom_css_and_refresh_protection_are_present(self):
        html = (ROOT / "web" / "us-equities" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "web" / "us-equities" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "us-equities" / "style.css").read_text(encoding="utf-8")
        guide = (ROOT / "web" / "us-equities" / "guide.js").read_text(encoding="utf-8")
        for node_id in ("mobileSymbol","mobilePrice","mobileDataTime","mobileRefresh","mobileValidation","expiryTrigger","expiryMenu","strikeTrigger","strikeMenu"):
            self.assertIn(f'id="{node_id}"', html)
        self.assertIn("width:592px", css)
        self.assertIn("width:540px", css)
        self.assertIn(".price-card{display:none}", css)
        self.assertIn("left:0;right:0", css)
        self.assertIn('menuOpen("expiryMenu")', app)
        self.assertIn('menuOpen("strikeMenu")', app)
        self.assertIn("if(expiries.length&&!expiries.includes(state.selectedExpiry))", app)
        self.assertIn('key="us-options-mobile-guide-open"', guide)
        self.assertIn('content.querySelectorAll("details[open]")', guide)


if __name__ == "__main__": unittest.main()

