import json
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

class FrontendLogicTests(unittest.TestCase):
    def test_symbol_race_detail_restore_and_stale_ranking_gate(self):
        script=r'''
const logic=require("./web/us-equities/app.js");
const details=[{dataset:{detailId:"chain:A"},open:false},{dataset:{detailId:"ranking:A"},open:false}];
logic.restoreOpenDetails(new Set(["ranking:A"]),details);
const grouped=logic.groupContractRows([
  {strike:100,side:"CALL",contract_symbol:"STANDARD"},
  {strike:100,side:"CALL",contract_symbol:"ADJUSTED"},
  {strike:100,side:"PUT",contract_symbol:"PUT"}
],row=>row.strike);
const classification=[
  {strike:null,expiration_date:"2026-10-16",side:"CALL",contract_symbol:"MISSING"},
  {strike:0,expiration_date:"2026-10-16",side:"CALL",contract_symbol:"ZERO"},
  {strike:-1,expiration_date:"2026-10-16",side:"CALL",contract_symbol:"NEGATIVE"},
  {strike:100,expiration_date:"not-a-date",side:"CALL",contract_symbol:"BADTEXT"},
  {strike:100,expiration_date:"2026-02-31",side:"CALL",contract_symbol:"BADDATE"},
  {strike:100,expiration_date:"2026-10-16",side:"CALL",contract_symbol:"NORMAL"}
];
const result={
  same:logic.shouldCommitSnapshot("AAPL","AAPL"),
  race:logic.shouldCommitSnapshot("AAPL","SPCX"),
  ready:logic.rankingSnapshotHealthy({state:"ready",fetch_health:"healthy"}),
  stale:logic.rankingSnapshotHealthy({state:"stale",fetch_health:"stale"}),
  degraded:logic.rankingSnapshotHealthy({state:"degraded",fetch_health:"failed"}),
  open:details.map(item=>item.open),
  duplicateCalls:grouped.get(100).CALL.map(row=>row.contract_symbol),
  puts:grouped.get(100).PUT.length,
  unclassified:logic.unclassifiedRows(classification).map(row=>row.contract_symbol),
  normal:logic.groupableRows(classification).map(row=>row.contract_symbol)
};
process.stdout.write(JSON.stringify(result));
'''
        completed=subprocess.run(["node","-e",script],cwd=ROOT,text=True,capture_output=True,check=True,timeout=10)
        result=json.loads(completed.stdout)
        self.assertEqual({key:result[key] for key in ("same","race","ready","stale","degraded","open","duplicateCalls","puts")},
                         {"same":True,"race":False,"ready":True,"stale":False,"degraded":False,
                          "open":[False,True],"duplicateCalls":["STANDARD","ADJUSTED"],"puts":1})
        self.assertEqual(result["unclassified"],["MISSING","ZERO","NEGATIVE","BADTEXT","BADDATE"])
        self.assertEqual(result["normal"],["NORMAL"])

if __name__=="__main__": unittest.main()
