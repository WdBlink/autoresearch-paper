#!/usr/bin/env python3
"""Offline canonical Claude/MiniMax + sparse Codex checkpoint integration."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"


class ClaudeCutoverE2E(unittest.TestCase):
    def runtime(self, *args: str, check: bool = True) -> dict:
        proc = subprocess.run([sys.executable, str(RUNTIME), *args], cwd=ROOT, text=True, capture_output=True)
        if check and proc.returncode:
            self.fail(f"runtime failed ({proc.returncode})\nstdout={proc.stdout}\nstderr={proc.stderr}")
        return json.loads(proc.stdout or proc.stderr)

    def fake_codex(self, root: Path) -> Path:
        target = root / "codex-fake"
        target.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib,json,pathlib,sys\n"
            "a=sys.argv[1:]; out=pathlib.Path(a[a.index('--output-last-message')+1])\n"
            "p=sys.stdin.read(); r=json.loads(p[p.index('{'):]); rp=pathlib.Path.cwd()/'state'/'frontier'/'requests'/r['request_id']/'request.json'\n"
            "c=json.dumps(r['context_manifest'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()\n"
            "k={'CP-01':'plan_audit','CP-02':'evaluator_audit','CP-03':'pivot_advice','CP-04':'evidence_audit'}\n"
            "x={'schema_version':1,'request_id':r['request_id'],'plan_id':r['plan_id'],'checkpoint':r['checkpoint'],'checkpoint_subtype':r['checkpoint_subtype'],'request_sha256':hashlib.sha256(rp.read_bytes()).hexdigest(),'context_manifest_sha256':hashlib.sha256(c).hexdigest(),'status':'completed','response_kind':k[r['checkpoint']],'recommendation':'pivot' if r['checkpoint']=='CP-03' else 'accept','findings':[],'proposed_actions':[],'assumptions':[],'blockers':[],'model_id':'ignored','usage':{'input_tokens':0,'output_tokens':0},'completed_at':'2026-07-18T00:00:00Z'}\n"
            "out.write_text(json.dumps(x)); print(json.dumps({'usage':{'input_tokens':100,'output_tokens':50}}))\n"
        )
        target.chmod(0o755)
        return target

    def fake_claude(self, root: Path) -> Path:
        target = root / "claude-fake"
        target.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib,json,sys\n"
            "p=json.load(sys.stdin); out=[]\n"
            "contents={'evaluator':'#!/usr/bin/env python3\\nimport argparse,json\\np=argparse.ArgumentParser();p.add_argument(\"--evidence\");p.add_argument(\"--candidate\");a=p.parse_args();text=open(a.candidate).read();print(json.dumps({\"metric\":\"score\",\"value\":0.9 if \"pass\" in text else 0.1}))\\n','evidence':'{\"baseline\":0.5}\\n'}\n"
            "for d in p['artifact_outputs']:\n"
            " c=contents[d['artifact_id']]; out.append({'artifact_id':d['artifact_id'],'path':d['path'],'content':c,'sha256':hashlib.sha256(c.encode()).hexdigest()})\n"
            "json.dump({'structured_output':{'summary':'bounded','ok':True,'artifacts':out}},sys.stdout)\n"
        )
        target.chmod(0o755)
        return target

    def checkpoint(self, plan: Path, codex: Path, cp: str, rid: str, transition: str,
                   evidence: dict[str, Path], subtype: str | None = None) -> None:
        create = ["create-frontier-request", "--plan-dir", str(plan), "--plan-id", "plan_e2e",
                  "--checkpoint", cp, "--objective", f"audit {cp}", "--decision-required", transition,
                  "--max-input-tokens", "5000", "--max-output-tokens", "500", "--request-id", rid]
        if subtype:
            create += ["--checkpoint-subtype", subtype]
        for role, path in evidence.items():
            create += ["--artifact", f"{path}::{role}"]
        self.runtime(*create)
        self.runtime("send-frontier-request", "--plan-dir", str(plan), "--request-id", rid, "--codex-bin", str(codex))
        self.runtime("validate-frontier-response", "--plan-dir", str(plan), "--request-id", rid)
        self.runtime("apply-frontier-response", "--plan-dir", str(plan), "--request-id", rid,
                     "--dependent-transition", transition, "--controller-note", "controller consumed bounded audit")
        self.runtime("assert-transition", "--plan-dir", str(plan), "--plan-id", "plan_e2e", "--transition", transition)

    def test_complete_claude_target_without_mavis(self) -> None:
        self.assertIsNone(shutil.which("mavis"))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan = root / "plan"; (plan / "state").mkdir(parents=True); (plan / "control").mkdir()
            owned = plan / "ephemeral.tmp"; owned.write_text("owned")
            (plan / "resource_manifest.json").write_text(json.dumps({
                "schema_version":1,"plan_id":"plan_e2e","plan_dir":str(plan),"status":"created",
                "resources":[{"resource_id":"ephemeral","path":str(owned),"ephemeral":True,"run_scoped":True,"ownership_nonce":"nonce"}],
                "agents":[],"sessions":[],"crons":[],"hooks":[],"launchd":[],"local_processes":[],"remote_processes":[],"locks":[]}))
            codex=self.fake_codex(root); claude=self.fake_claude(root)
            self.runtime("init-policy","--plan-dir",str(plan),"--worker-model","MiniMax-M3-e2e","--worker-max-budget-usd","0.1","--frontier-model","gpt-frontier-e2e","--max-frontier-calls","4","--max-frontier-input-tokens","20000","--max-frontier-output-tokens","2000")

            brief=plan/"brief.md"; execution=plan/"execution.json"; risk=plan/"risk.json"
            for p in (brief,execution,risk): p.write_text("{}")
            self.checkpoint(plan,codex,"CP-01","far_cp01","approve_execution",{"normalized_brief":brief,"execution_plan":execution,"risk_budget":risk})

            evaluator=plan/"evaluator.py"; evidence=plan/"evidence.json"; task=plan/"task.json"
            output_schema={"type":"object","additionalProperties":False,"required":["summary","ok","artifacts"],"properties":{"summary":{"type":"string"},"ok":{"type":"boolean"},"artifacts":{"type":"array","items":{"type":"object","additionalProperties":False,"required":["artifact_id","path","content","sha256"],"properties":{"artifact_id":{"type":"string"},"path":{"type":"string"},"content":{"type":"string"},"sha256":{"type":"string"}}}}}}
            task.write_text(json.dumps({"schema_version":1,"task_id":"make-evaluator","instruction":"propose evaluator artifacts","inputs":[{"path":str(brief)}],"allowed_tools":[],"allowed_write_paths":[],"artifact_outputs":[{"artifact_id":"evaluator","path":str(evaluator),"content_field":"content","max_bytes":10000},{"artifact_id":"evidence","path":str(evidence),"content_field":"content","max_bytes":1000}],"completion_check":{"type":"output_schema","assertion":"valid"},"output_schema":output_schema}))
            worker=self.runtime("dispatch-worker","--plan-dir",str(plan),"--task-contract",str(task),"--claude-bin",str(claude))
            self.assertFalse(evaluator.exists())
            self.runtime("promote-worker-artifacts","--plan-dir",str(plan),"--worker-run-id",worker["run_id"])
            self.assertTrue(evaluator.exists())

            calibration=plan/"calibration.md"; calibration.write_text("pass")
            cp02={"evaluator":evaluator,"evidence_manifest":evidence}
            for role in ("metric_contract","baselines","seeds_splits","leakage_controls"):
                p=plan/f"{role}.json"; p.write_text("{}"); cp02[role]=p
            cp02["calibration_candidate"]=calibration
            self.checkpoint(plan,codex,"CP-02","far_cp02","freeze_evaluator",cp02)
            cal=self.runtime("run-evaluator","--plan-dir",str(plan),"--evaluator",str(evaluator),"--evidence",str(evidence),"--candidate",str(calibration),"--purpose","calibration")
            self.runtime("freeze-evaluator","--plan-dir",str(plan),"--execution-receipt",cal["execution_receipt"],"--operator","gte","--threshold","0.8")

            failed=[]
            for i,family in enumerate(("transformer","graph"),1):
                candidate=plan/f"fail-{i}.md"; candidate.write_text("fail")
                run=self.runtime("run-evaluator","--plan-dir",str(plan),"--evaluator",str(evaluator),"--evidence",str(evidence),"--candidate",str(candidate),"--purpose","candidate")
                verdict=self.runtime("record-evaluator-verdict","--plan-dir",str(plan),"--execution-receipt",run["execution_receipt"],"--candidate-id",f"fail-{i}")
                direction=plan/f"direction-{i}.json"; direction.write_text(json.dumps({"algorithm_family":family,"data_representation":"tokens","objective":"score","evaluator":"frozen","baseline_framing":"base","lineage":f"root-{i}","candidate_sha256":hashlib.sha256(candidate.read_bytes()).hexdigest()}))
                self.runtime("record-failure","--plan-dir",str(plan),"--class","scientific_no_improvement","--direction",str(direction),"--verdict",verdict["verdict_path"],"--source","evaluator")
                failed.append(Path(verdict["verdict_path"]))
            registry=plan/"direction-registry.json"; registry.write_text(json.dumps(json.loads((plan/"state"/"failure_state.json").read_text())["direction_registry"]))
            proposal=plan/"pivot.json"; proposal.write_text(json.dumps({"direction":{"algorithm_family":"diffusion","data_representation":"latent","objective":"score","evaluator":"frozen","baseline_framing":"base","lineage":"pivot","candidate_sha256":"0"*64}}))
            self.checkpoint(plan,codex,"CP-03","far_cp03","authorize_structural_pivot",{"failure_state":plan/"state"/"failure_state.json","direction_registry":registry,"pivot_proposal":proposal,"evaluator_verdict":failed[-1]})
            self.runtime("apply-structural-pivot","--plan-dir",str(plan),"--proposal",str(proposal))

            candidate=plan/"candidate.md"; candidate.write_text("pass")
            run=self.runtime("run-evaluator","--plan-dir",str(plan),"--evaluator",str(evaluator),"--evidence",str(evidence),"--candidate",str(candidate),"--purpose","candidate")
            verdict=self.runtime("record-evaluator-verdict","--plan-dir",str(plan),"--execution-receipt",run["execution_receipt"],"--candidate-id","accepted")
            contract=plan/"state"/"evaluator_contract.json"; verdict_path=Path(verdict["verdict_path"])
            cp04={"candidate":candidate,"evaluator_contract":contract,"evaluator_verdict":verdict_path}
            for role in ("claim_evidence_map","raw_result_manifest","baselines","uncertainty_robustness"):
                p=plan/f"final-{role}.json"; p.write_text("{}"); cp04[role]=p
            self.checkpoint(plan,codex,"CP-04","far_cp04","start_writing",cp04,"prewriting_final_evidence")
            gate=self.runtime("check-writing-gate","--plan-dir",str(plan),"--tier","conference","--verdict",str(verdict_path))
            self.assertTrue(gate["ok"])

            key=root/"key"; key.write_bytes(b"k"*32); key.chmod(0o600)
            waiver=self.runtime("create-human-action","--plan-dir",str(plan),"--plan-id","plan_e2e","--action","waive_acceptance","--key-file",str(key),"--expires-in","300","--record-id","har_waiver","--reason","human review","--candidate",str(candidate),"--tier","conference")
            pending=self.runtime("check-writing-gate","--plan-dir",str(plan),"--tier","conference","--waiver",waiver["record_path"],check=False)
            self.assertFalse(pending["ok"])
            waiver_receipt=self.runtime("apply-human-action","--plan-dir",str(plan),"--record",waiver["record_path"],"--key-file",str(key),"--expected-action","waive_acceptance")["receipt"]
            waived=self.runtime("check-writing-gate","--plan-dir",str(plan),"--tier","conference","--waiver",waiver_receipt["waiver_path"])
            self.assertEqual(waived["source"],"applied_waiver_receipt")
            cleanup=self.runtime("create-human-action","--plan-dir",str(plan),"--plan-id","plan_e2e","--action","cleanup_resource","--key-file",str(key),"--expires-in","300","--record-id","har_cleanup","--resource-id","ephemeral")
            receipt=self.runtime("apply-human-action","--plan-dir",str(plan),"--record",cleanup["record_path"],"--key-file",str(key),"--expected-action","cleanup_resource")["receipt"]
            token=hashlib.sha256(f"plan_e2e\0{owned.resolve()}\0nonce".encode()).hexdigest()
            self.runtime("remove-resource","--plan-dir",str(plan),"--resource-id","ephemeral","--ownership-token",token,"--authorization",receipt["authorization_path"])
            self.assertFalse(owned.exists())


if __name__ == "__main__": unittest.main()
