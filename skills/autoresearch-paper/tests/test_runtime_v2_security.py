#!/usr/bin/env python3
"""Fail-closed regression matrix for the Claude Code Harness v2 contracts."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"
RUNNER = ROOT / "references" / "scripts" / "run-claude-harness.py"


class RuntimeV2Security(unittest.TestCase):
    def call(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run([sys.executable, str(RUNTIME), *args], cwd=ROOT, text=True, capture_output=True)
        if check and proc.returncode:
            self.fail(f"failed: {args}\n{proc.stdout}\n{proc.stderr}")
        return proc

    def plan(self, root: Path, plan_id: str = "plan_v2") -> Path:
        plan = root / plan_id; (plan / "state").mkdir(parents=True); (plan / "control").mkdir()
        (plan / "resource_manifest.json").write_text(json.dumps({
            "schema_version":1,"plan_id":plan_id,"plan_dir":str(plan),"status":"running","resources":[],
            "agents":[],"sessions":[],"crons":[],"hooks":[],"launchd":[],"local_processes":[],"remote_processes":[],"locks":[]}))
        self.call("init-policy","--plan-dir",str(plan),"--worker-model","MiniMax-M3-test","--worker-max-budget-usd","0.1","--frontier-model","frontier-test","--max-frontier-calls","4","--max-frontier-input-tokens","20000","--max-frontier-output-tokens","2000")
        return plan

    def cp01(self, plan: Path) -> dict[str, Path]:
        values = {}
        for role in ("normalized_brief","execution_plan","risk_budget"):
            path=plan/f"{role}.json"; path.write_text("{}"); values[role]=path
        return values

    def fake_codex(self, root: Path, *, status: str = "completed", blockers: bool = False,
                   critical: bool = False, malformed: bool = False) -> Path:
        target = root / f"codex-{status}-{int(blockers)}-{int(critical)}-{int(malformed)}"
        target.write_text(
            "#!/usr/bin/env python3\nimport hashlib,json,pathlib,sys\n"
            "a=sys.argv[1:];o=pathlib.Path(a[a.index('--output-last-message')+1]);p=sys.stdin.read();r=json.loads(p[p.index('{'):]);rp=pathlib.Path.cwd()/'state'/'frontier'/'requests'/r['request_id']/'request.json';c=json.dumps(r['context_manifest'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()\n"
            + ("o.write_text('{bad');print(json.dumps({'usage':{'input_tokens':10,'output_tokens':5}}));sys.exit(0)\n" if malformed else
            f"k={{'CP-01':'plan_audit','CP-02':'evaluator_audit','CP-03':'pivot_advice','CP-04':'evidence_audit'}};x={{'schema_version':1,'request_id':r['request_id'],'plan_id':r['plan_id'],'checkpoint':r['checkpoint'],'checkpoint_subtype':r['checkpoint_subtype'],'request_sha256':hashlib.sha256(rp.read_bytes()).hexdigest(),'context_manifest_sha256':hashlib.sha256(c).hexdigest(),'status':'{status}','response_kind':k[r['checkpoint']],'recommendation':'accept','findings':[{{'severity':'critical','claim':'bad','evidence':[r['context_manifest'][0]['sha256']]}}] if {critical!r} else [],'proposed_actions':[],'assumptions':[],'blockers':['blocked'] if {blockers!r} else [],'model_id':'ignored','usage':{{'input_tokens':0,'output_tokens':0}},'completed_at':'2026-07-18T00:00:00Z'}};o.write_text(json.dumps(x));print(json.dumps({{'usage':{{'input_tokens':10,'output_tokens':5}}}}))\n"))
        target.chmod(0o755)
        return target

    def create_cp01(self, plan: Path, request_id: str) -> None:
        args=["create-frontier-request","--plan-dir",str(plan),"--plan-id",plan.name,"--checkpoint","CP-01","--objective","audit","--decision-required","approve_execution","--max-input-tokens","5000","--max-output-tokens","500","--request-id",request_id]
        for role,path in self.cp01(plan).items(): args += ["--artifact",f"{path}::{role}"]
        self.call(*args)

    def approve_cp01(self, plan: Path, root: Path, request_id: str = "far_approve") -> None:
        self.create_cp01(plan,request_id); codex=self.fake_codex(root)
        self.call("send-frontier-request","--plan-dir",str(plan),"--request-id",request_id,"--codex-bin",str(codex))
        self.call("validate-frontier-response","--plan-dir",str(plan),"--request-id",request_id)
        self.call("apply-frontier-response","--plan-dir",str(plan),"--request-id",request_id,"--dependent-transition","approve_execution","--controller-note","approved")

    def test_top_level_runner_rejects_ad_hoc_command_lists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=self.plan(root)
            workflow=root/"workflow.json"; workflow.write_text(json.dumps({
                "schema_version":1,"flow_id":"arbitrary","steps":[
                    {"id":"status","command":"run-patrol","args":{"stale_seconds":60}}
                ]
            }))
            inputs=root/"inputs.json"; inputs.write_text("{}")
            proc=subprocess.run([
                sys.executable,str(RUNNER),"--plan-dir",str(plan),"--workflow",str(workflow),
                "--inputs",str(inputs),
            ],text=True,capture_output=True)
            self.assertEqual(proc.returncode,2)
            self.assertIn("canonical workflow requires exactly",proc.stderr)

    def test_frontier_semantic_failures_and_malformed_raw_pause(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for index,kwargs in enumerate(({"status":"refused"},{"blockers":True},{"critical":True})):
                plan=self.plan(root/f"p{index}"); rid=f"far_bad_{index}"; self.create_cp01(plan,rid)
                self.call("send-frontier-request","--plan-dir",str(plan),"--request-id",rid,"--codex-bin",str(self.fake_codex(root/f"p{index}",**kwargs)))
                invalid=self.call("validate-frontier-response","--plan-dir",str(plan),"--request-id",rid,check=False)
                self.assertEqual(invalid.returncode,2); self.assertEqual(json.loads((plan/"state"/"frontier"/"requests"/rid/"status.json").read_text())["state"],"PAUSED")
            plan=self.plan(root/"malformed"); self.create_cp01(plan,"far_malformed")
            malformed=self.call("send-frontier-request","--plan-dir",str(plan),"--request-id","far_malformed","--codex-bin",str(self.fake_codex(root/"malformed",malformed=True)),check=False)
            self.assertEqual(malformed.returncode,2); status=json.loads((plan/"state"/"frontier"/"requests"/"far_malformed"/"status.json").read_text())
            self.assertEqual(status["state"],"PAUSED"); self.assertEqual(status["failure"],"malformed_durable_response")

    def test_response_drift_is_rechecked_at_apply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=self.plan(root); rid="far_drift"; self.create_cp01(plan,rid); codex=self.fake_codex(root)
            self.call("send-frontier-request","--plan-dir",str(plan),"--request-id",rid,"--codex-bin",str(codex)); self.call("validate-frontier-response","--plan-dir",str(plan),"--request-id",rid)
            response=plan/"state"/"frontier"/"requests"/rid/"response.json"; response.chmod(0o644); value=json.loads(response.read_text()); value["assumptions"]=["mutated"]; response.write_text(json.dumps(value))
            proc=self.call("apply-frontier-response","--plan-dir",str(plan),"--request-id",rid,"--dependent-transition","approve_execution","--controller-note","x",check=False)
            self.assertEqual(proc.returncode,2); self.assertFalse((plan/"state"/"frontier"/"transitions"/"approve_execution.json").exists())

    def test_acceptance_dispute_consumer_requires_and_consumes_cp04(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=self.plan(root); resolution=plan/"dispute.json"
            resolution.write_text(json.dumps({"candidate_id":"candidate","resolution":"accept","rationale":"evidence reconciled"}))
            blocked=self.call("resolve-acceptance-dispute","--plan-dir",str(plan),"--resolution",str(resolution),check=False)
            self.assertEqual(blocked.returncode,2)
            evidence={"dispute_record":resolution}
            for role in ("evaluator_contract","evaluator_verdict","candidate"):
                p=plan/f"{role}.json"; p.write_text("{}"); evidence[role]=p
            args=["create-frontier-request","--plan-dir",str(plan),"--plan-id",plan.name,"--checkpoint","CP-04","--checkpoint-subtype","acceptance_dispute","--objective","resolve","--decision-required","resolve_acceptance_dispute","--max-input-tokens","5000","--max-output-tokens","500","--request-id","far_dispute"]
            for role,path in evidence.items(): args += ["--artifact",f"{path}::{role}"]
            self.call(*args); codex=self.fake_codex(root)
            self.call("send-frontier-request","--plan-dir",str(plan),"--request-id","far_dispute","--codex-bin",str(codex)); self.call("validate-frontier-response","--plan-dir",str(plan),"--request-id","far_dispute")
            self.call("apply-frontier-response","--plan-dir",str(plan),"--request-id","far_dispute","--dependent-transition","resolve_acceptance_dispute","--controller-note","accepted")
            applied=json.loads(self.call("resolve-acceptance-dispute","--plan-dir",str(plan),"--resolution",str(resolution)).stdout)
            self.assertTrue(applied["ok"])
            replay=json.loads(self.call("resolve-acceptance-dispute","--plan-dir",str(plan),"--resolution",str(resolution)).stdout)
            self.assertTrue(replay["idempotent"])
            args2=["create-frontier-request","--plan-dir",str(plan),"--plan-id",plan.name,"--checkpoint","CP-04","--checkpoint-subtype","acceptance_dispute","--objective","resolve again","--decision-required","resolve_acceptance_dispute","--max-input-tokens","5000","--max-output-tokens","500","--request-id","far_dispute_again"]
            for role,path in evidence.items(): args2 += ["--artifact",f"{path}::{role}"]
            self.call(*args2); self.call("send-frontier-request","--plan-dir",str(plan),"--request-id","far_dispute_again","--codex-bin",str(codex)); self.call("validate-frontier-response","--plan-dir",str(plan),"--request-id","far_dispute_again")
            self.call("apply-frontier-response","--plan-dir",str(plan),"--request-id","far_dispute_again","--dependent-transition","resolve_acceptance_dispute","--controller-note","accepted again")
            second=json.loads(self.call("resolve-acceptance-dispute","--plan-dir",str(plan),"--resolution",str(resolution)).stdout)
            self.assertEqual(second["frontier_request_id"],"far_dispute_again")
            self.assertNotEqual(second["resolution_receipt"],applied["resolution_receipt"])

    def test_worker_escape_malformed_output_and_identifier_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=self.plan(root); self.approve_cp01(plan,root)
            outside=root/"outside.txt"; contract=plan/"escape.json"
            contract.write_text(json.dumps({"schema_version":1,"task_id":"escape","instruction":"x","inputs":[],"allowed_tools":[],"allowed_write_paths":[],"artifact_outputs":[{"artifact_id":"x","path":str(outside),"content_field":"content","max_bytes":10}],"completion_check":{"type":"output_schema","assertion":"valid"},"output_schema":{"type":"object","additionalProperties":False,"required":["artifacts"],"properties":{"artifacts":{"type":"array","items":{"type":"object"}}}}}))
            proc=self.call("dispatch-worker","--plan-dir",str(plan),"--task-contract",str(contract),"--claude-bin",str(root/"none"),check=False)
            self.assertEqual(proc.returncode,2); self.assertFalse(outside.exists())
            bad_id=self.call("inspect-worker","--plan-dir",str(plan),"--worker-run-id","../escape",check=False); self.assertEqual(bad_id.returncode,2)
            malformed=root/"claude-malformed"; malformed.write_text("#!/bin/sh\nprintf 'not-json'"); malformed.chmod(0o755)
            contract_data=json.loads(contract.read_text()); contract_data["artifact_outputs"]=[]; contract.write_text(json.dumps(contract_data))
            bad=self.call("dispatch-worker","--plan-dir",str(plan),"--task-contract",str(contract),"--claude-bin",str(malformed),check=False)
            self.assertEqual(bad.returncode,2); statuses=list((plan/"state"/"worker_runs").glob("*/status.json")); self.assertEqual(json.loads(statuses[-1].read_text())["status"],"FAILED")

    def test_concurrent_frontier_send_has_one_transport_claim(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=self.plan(root); rid="far_concurrent"; self.create_cp01(plan,rid)
            counter=root/"counter"; fake=root/"codex-concurrent"
            fake.write_text(
                "#!/usr/bin/env python3\nimport hashlib,json,pathlib,sys,time\n"
                f"counter=pathlib.Path({str(counter)!r}); counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1');time.sleep(.3)\n"
                "a=sys.argv[1:];o=pathlib.Path(a[a.index('--output-last-message')+1]);p=sys.stdin.read();r=json.loads(p[p.index('{'):]);rp=pathlib.Path.cwd()/'state'/'frontier'/'requests'/r['request_id']/'request.json';c=json.dumps(r['context_manifest'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode();x={'schema_version':1,'request_id':r['request_id'],'plan_id':r['plan_id'],'checkpoint':'CP-01','checkpoint_subtype':None,'request_sha256':hashlib.sha256(rp.read_bytes()).hexdigest(),'context_manifest_sha256':hashlib.sha256(c).hexdigest(),'status':'completed','response_kind':'plan_audit','recommendation':'accept','findings':[],'proposed_actions':[],'assumptions':[],'blockers':[],'model_id':'x','usage':{'input_tokens':0,'output_tokens':0},'completed_at':'2026-07-18T00:00:00Z'};o.write_text(json.dumps(x));print(json.dumps({'usage':{'input_tokens':10,'output_tokens':5}}))\n")
            fake.chmod(0o755)
            argv=[sys.executable,str(RUNTIME),"send-frontier-request","--plan-dir",str(plan),"--request-id",rid,"--codex-bin",str(fake)]
            first=subprocess.Popen(argv,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE); second=subprocess.Popen(argv,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            one=first.communicate(); two=second.communicate(); self.assertEqual(first.returncode,0,one); self.assertEqual(second.returncode,0,two)
            self.assertEqual(counter.read_text(),"1"); ledger=json.loads((plan/"state"/"frontier"/"budget.json").read_text()); self.assertEqual(ledger["reserved_calls"],1)

    def test_human_action_crash_rolls_forward_and_l0_rejects_bare_stop(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=self.plan(root); key=root/"key"; key.write_bytes(b"k"*32); key.chmod(0o600)
            created=json.loads(self.call("create-human-action","--plan-dir",str(plan),"--plan-id",plan.name,"--action","pause","--key-file",str(key),"--expires-in","300","--record-id","har_crash").stdout)
            crash=self.call("apply-human-action","--plan-dir",str(plan),"--record",created["record_path"],"--key-file",str(key),"--simulate-crash-after","mutation",check=False); self.assertEqual(crash.returncode,2)
            recovered=json.loads(self.call("apply-human-action","--plan-dir",str(plan),"--record",created["record_path"],"--key-file",str(key)).stdout); self.assertTrue(recovered["recovered"])
            (plan/"control"/"stop_requested.json").write_text('{"action":"stop"}')
            guard=subprocess.run([sys.executable,str(ROOT/"references"/"scripts"/"plan-l0-guard.py"),"--plan-dir",str(plan),"--once"],text=True,capture_output=True)
            self.assertEqual(guard.returncode,0); self.assertEqual(json.loads(guard.stdout)["action"],"invalid_stop_authority")

    def test_aggregate_cleanup_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan=self.plan(Path(td)); proc=subprocess.run(["bash",str(ROOT/"references"/"scripts"/"cleanup-plan-resources.sh"),str(plan),"--mode","cleanup","--dry-run"],text=True,capture_output=True)
            self.assertEqual(proc.returncode,2); self.assertIn("aggregate cleanup is disabled",proc.stderr)

    def test_request_id_reuse_requires_identical_canonical_request(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=self.plan(root); request_id="far_collision"
            self.create_cp01(plan,request_id)
            same=self.call(
                "create-frontier-request","--plan-dir",str(plan),"--plan-id",plan.name,
                "--checkpoint","CP-01","--objective","audit","--decision-required","approve_execution",
                *sum((["--artifact",f"{path}::{role}"] for role,path in self.cp01(plan).items()),[]),
                "--max-input-tokens","5000","--max-output-tokens","500","--request-id",request_id,
            )
            self.assertTrue(json.loads(same.stdout)["idempotent"])
            collision=self.call(
                "create-frontier-request","--plan-dir",str(plan),"--plan-id",plan.name,
                "--checkpoint","CP-01","--objective","different audit","--decision-required","approve_execution",
                *sum((["--artifact",f"{path}::{role}"] for role,path in self.cp01(plan).items()),[]),
                "--max-input-tokens","5000","--max-output-tokens","500","--request-id",request_id,
                check=False,
            )
            self.assertEqual(collision.returncode,2)
            self.assertIn("request_id collision",collision.stderr)

    def test_promotion_requires_authority_then_recovers_valid_partial_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=self.plan(root); self.approve_cp01(plan,root)
            legacy_id="cwr_"+"a"*32; legacy_dir=plan/"state"/"worker_runs"/legacy_id; legacy_dir.mkdir(parents=True)
            legacy_target=plan/"legacy-root.txt"; legacy_content="legacy"
            legacy_decl=[{"artifact_id":"legacy","path":str(legacy_target),"content_field":"content","max_bytes":100}]
            legacy_contract=plan/"legacy-task.json"; legacy_contract.write_text(json.dumps({"artifact_outputs":legacy_decl}))
            legacy_result=legacy_dir/"result.json"; legacy_result.write_text(json.dumps({"result":{"artifacts":[{
                "artifact_id":"legacy","path":str(legacy_target),"content":legacy_content,
                "sha256":hashlib.sha256(legacy_content.encode()).hexdigest()}]}}))
            (legacy_dir/"status.json").write_text(json.dumps({"schema_version":1,"run_id":legacy_id,
                "status":"COMPLETED","contract_path":str(legacy_contract),
                "contract_sha256":hashlib.sha256(legacy_contract.read_bytes()).hexdigest(),
                "result_path":str(legacy_result),"result_sha256":hashlib.sha256(legacy_result.read_bytes()).hexdigest()}))
            denied=self.call("promote-worker-artifacts","--plan-dir",str(plan),"--worker-run-id",legacy_id,check=False)
            self.assertEqual(denied.returncode,2); self.assertFalse(legacy_target.exists())
            run_id="cwr_"+"b"*32; run_dir=plan/"state"/"worker_runs"/run_id; run_dir.mkdir(parents=True)
            task_id="recovery"; namespace=plan/"artifacts"/"intermediate"/task_id
            first,second=namespace/"first.txt",namespace/"second.txt"
            contents=("first-content","second-content")
            declarations=[]; proposals=[]
            for index,(target,content) in enumerate(zip((first,second),contents),1):
                digest=hashlib.sha256(content.encode()).hexdigest()
                canonical = str(target.resolve())
                declarations.append({"artifact_id":f"a{index}","path":canonical,"content_field":"content",
                                     "max_bytes":100,"capability":{"class":"research-intermediate"}})
                proposals.append({"artifact_id":f"a{index}","path":canonical,"content":content,"sha256":digest})
            contract=plan/"promotion-task.json"; contract.write_text(json.dumps({"task_id":task_id,"artifact_outputs":declarations}))
            result=run_dir/"result.json"; result.write_text(json.dumps({"result":{"artifacts":proposals},"artifact_outputs":declarations}))
            (run_dir/"status.json").write_text(json.dumps({
                "schema_version":1,"run_id":run_id,"status":"COMPLETED","contract_path":str(contract),
                "contract_sha256":hashlib.sha256(contract.read_bytes()).hexdigest(),"result_path":str(result),
                "result_sha256":hashlib.sha256(result.read_bytes()).hexdigest(),"task_id":task_id,
                "artifact_outputs":declarations,"output_capability_class":"research-intermediate",
            }))
            namespace.mkdir(parents=True)
            second.write_text("conflict")
            blocked=self.call("promote-worker-artifacts","--plan-dir",str(plan),"--worker-run-id",run_id,check=False)
            self.assertEqual(blocked.returncode,2); self.assertFalse(first.exists()); self.assertEqual(second.read_text(),"conflict")
            second.unlink()
            crashed=self.call(
                "promote-worker-artifacts","--plan-dir",str(plan),"--worker-run-id",run_id,
                "--simulate-crash-after","1",check=False,
            )
            self.assertEqual(crashed.returncode,2,crashed.stderr); self.assertTrue(first.exists(),crashed.stderr); self.assertFalse(second.exists())
            self.assertFalse((run_dir/"promotion-receipt.json").exists())
            recovered=self.call("promote-worker-artifacts","--plan-dir",str(plan),"--worker-run-id",run_id)
            self.assertTrue(json.loads(recovered.stdout)["ok"]); self.assertTrue(second.exists())
            self.assertEqual(json.loads((run_dir/"promotion-journal.json").read_text())["phase"],"COMMITTED")

    def test_cleanup_authorization_is_single_generation_and_crash_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=self.plan(root); owned=plan/"owned.tmp"; owned.write_text("generation-one")
            manifest=json.loads((plan/"resource_manifest.json").read_text()); manifest["resources"]=[{
                "resource_id":"owned","path":str(owned),"ephemeral":True,"run_scoped":True,
                "ownership_generation":"g1",
            }]; (plan/"resource_manifest.json").write_text(json.dumps(manifest))
            key=root/"key"; key.write_bytes(b"k"*32); key.chmod(0o600)
            created=json.loads(self.call(
                "create-human-action","--plan-dir",str(plan),"--plan-id",plan.name,"--action","cleanup_resource",
                "--key-file",str(key),"--expires-in","300","--record-id","har_cleanup_g1","--resource-id","owned",
            ).stdout)
            applied=json.loads(self.call(
                "apply-human-action","--plan-dir",str(plan),"--record",created["record_path"],
                "--key-file",str(key),"--expected-action","cleanup_resource",
            ).stdout)
            token1=hashlib.sha256(f"{plan.name}\0{owned.resolve()}\0g1".encode()).hexdigest()
            cleanup_operation="op_"+"7"*64
            crash=self.call(
                "remove-resource","--plan-dir",str(plan),"--resource-id","owned","--ownership-token",token1,
                "--authorization",applied["authorization_path"],"--simulate-crash-after","unlink",
                "--operation-id",cleanup_operation,check=False,
            )
            self.assertEqual(crash.returncode,2); self.assertFalse(owned.exists())
            recovered=json.loads(self.call(
                "remove-resource","--plan-dir",str(plan),"--resource-id","owned","--ownership-token",token1,
                "--authorization",applied["authorization_path"],"--simulate-crash-after","unlink",
                "--operation-id",cleanup_operation,
            ).stdout)
            self.assertTrue(recovered["recovered"]); self.assertTrue(recovered["operation_reconciled"])
            fresh_cleanup_operation="op_"+"8"*64
            fresh_cleanup=self.call(
                "remove-resource","--plan-dir",str(plan),"--resource-id","owned","--ownership-token",token1,
                "--authorization",applied["authorization_path"],"--operation-id",fresh_cleanup_operation,
                check=False,
            )
            self.assertEqual(fresh_cleanup.returncode,2)
            self.assertIn("operation identity mismatch",fresh_cleanup.stderr)
            self.assertEqual(json.loads((
                plan/"state"/"runtime_operations"/f"{fresh_cleanup_operation}.json"
            ).read_text())["phase"],"PREPARED")
            owned.write_text("generation-one")
            replay=self.call(
                "remove-resource","--plan-dir",str(plan),"--resource-id","owned","--ownership-token",token1,
                "--authorization",applied["authorization_path"],check=False,
            )
            self.assertEqual(replay.returncode,2); self.assertTrue(owned.exists())
            manifest["resources"][0]["ownership_generation"]="g2"; (plan/"resource_manifest.json").write_text(json.dumps(manifest))
            created2=json.loads(self.call(
                "create-human-action","--plan-dir",str(plan),"--plan-id",plan.name,"--action","cleanup_resource",
                "--key-file",str(key),"--expires-in","300","--record-id","har_cleanup_g2","--resource-id","owned",
            ).stdout)
            applied2=json.loads(self.call(
                "apply-human-action","--plan-dir",str(plan),"--record",created2["record_path"],
                "--key-file",str(key),"--expected-action","cleanup_resource",
            ).stdout)
            token2=hashlib.sha256(f"{plan.name}\0{owned.resolve()}\0g2".encode()).hexdigest()
            self.call(
                "remove-resource","--plan-dir",str(plan),"--resource-id","owned","--ownership-token",token2,
                "--authorization",applied2["authorization_path"],
            )
            self.assertFalse(owned.exists())

    def test_human_action_journal_binds_originating_operation_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); plan=self.plan(root); key=root/"key"
            key.write_bytes(b"k"*32); key.chmod(0o600)
            created=json.loads(self.call(
                "create-human-action","--plan-dir",str(plan),"--plan-id",plan.name,"--action","pause",
                "--key-file",str(key),"--expires-in","300","--record-id","har_bound_pause",
            ).stdout)
            original_operation="op_"+"4"*64
            applied=json.loads(self.call(
                "apply-human-action","--plan-dir",str(plan),"--record",created["record_path"],
                "--key-file",str(key),"--expected-action","pause","--operation-id",original_operation,
            ).stdout)
            self.assertTrue(applied["ok"])
            repeated=json.loads(self.call(
                "apply-human-action","--plan-dir",str(plan),"--record",created["record_path"],
                "--key-file",str(key),"--expected-action","pause","--operation-id",original_operation,
            ).stdout)
            self.assertTrue(repeated["operation_reconciled"])
            fresh_operation="op_"+"5"*64
            rejected=self.call(
                "apply-human-action","--plan-dir",str(plan),"--record",created["record_path"],
                "--key-file",str(key),"--expected-action","pause","--operation-id",fresh_operation,
                check=False,
            )
            self.assertEqual(rejected.returncode,2)
            self.assertIn("operation identity mismatch",rejected.stderr)
            self.assertEqual(json.loads((plan/"state"/"controller.json").read_text())["status"],"paused")
            self.assertEqual(json.loads((
                plan/"state"/"runtime_operations"/f"{fresh_operation}.json"
            ).read_text())["phase"],"PREPARED")


if __name__ == "__main__": unittest.main()
