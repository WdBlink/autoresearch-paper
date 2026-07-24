#!/usr/bin/env python3
"""Offline closed Claude/MiniMax + sparse Codex conformance integration."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "references" / "scripts" / "harness-runtime.py"
RUNNER = ROOT / "references" / "scripts" / "run-claude-harness.py"
WORKFLOW = ROOT / "references" / "canonical-conformance-workflow.json"


class ClaudeCutoverE2E(unittest.TestCase):
    def runtime(self, *args: str, check: bool = True) -> dict:
        proc = subprocess.run([sys.executable, str(RUNTIME), *args], cwd=ROOT, text=True, capture_output=True)
        if check and proc.returncode:
            self.fail(f"runtime failed ({proc.returncode})\nstdout={proc.stdout}\nstderr={proc.stderr}")
        return json.loads(proc.stdout or proc.stderr)

    def fake_codex(self, root: Path) -> tuple[Path, Path]:
        target, counter = root / "codex-fake", root / "codex-count"
        target.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib,json,pathlib,sys\n"
            f"counter=pathlib.Path({str(counter)!r});counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1')\n"
            "a=sys.argv[1:];out=pathlib.Path(a[a.index('--output-last-message')+1]);p=sys.stdin.read();r=json.loads(p[p.index('{'):]);rp=pathlib.Path.cwd()/'state'/'frontier'/'requests'/r['request_id']/'request.json';c=json.dumps(r['context_manifest'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode();k={'CP-01':'plan_audit','CP-02':'evaluator_audit','CP-03':'pivot_advice','CP-04':'evidence_audit'};x={'schema_version':1,'request_id':r['request_id'],'plan_id':r['plan_id'],'checkpoint':r['checkpoint'],'checkpoint_subtype':r['checkpoint_subtype'],'request_sha256':hashlib.sha256(rp.read_bytes()).hexdigest(),'context_manifest_sha256':hashlib.sha256(c).hexdigest(),'status':'completed','response_kind':k[r['checkpoint']],'recommendation':'pivot' if r['checkpoint']=='CP-03' else 'accept','findings':[],'proposed_actions':[],'assumptions':[],'blockers':[],'model_id':'ignored','usage':{'input_tokens':0,'output_tokens':0},'completed_at':'2026-07-18T00:00:00Z'};out.write_text(json.dumps(x));print(json.dumps({'usage':{'input_tokens':100,'output_tokens':50}}))\n"
        )
        target.chmod(0o755)
        return target, counter

    def fake_claude(self, root: Path) -> tuple[Path, Path]:
        target, counter = root / "claude-fake", root / "claude-count"
        target.write_text(
            "#!/usr/bin/env python3\n"
            "import hashlib,json,pathlib,sys\n"
            f"counter=pathlib.Path({str(counter)!r});counter.write_text(str(int(counter.read_text())+1) if counter.exists() else '1')\n"
            "p=json.load(sys.stdin);out=[];contents={'evaluator':json.dumps({'schema_version':1,'kind':'declarative-evaluator-v1','operation':'read_finite_number','metric':'score','source':'candidate','json_path':['score']}),'evidence':'{\"baseline\":0.5}\\n','article':'# illicit\\n','paper_deliverable':'# Final paper\\n\\nController-promoted after the writing gate.\\n'}\n"
            "for d in p['artifact_outputs']:\n c=contents[d['artifact_id']];out.append({'artifact_id':d['artifact_id'],'path':d['path'],'content':c,'sha256':hashlib.sha256(c.encode()).hexdigest()})\n"
            "json.dump({'structured_output':{'summary':'bounded','ok':True,'artifacts':out}},sys.stdout)\n"
        )
        target.chmod(0o755)
        return target, counter

    def prepare(self, root: Path) -> tuple[Path, Path, Path, Path]:
        plan = root / "plan"
        (plan / "state").mkdir(parents=True)
        (plan / "control").mkdir()
        owned = plan / "ephemeral.tmp"
        owned.write_text("owned")
        (plan / "resource_manifest.json").write_text(json.dumps({
            "schema_version": 1, "plan_id": "plan_e2e", "plan_dir": str(plan), "status": "created",
            "resources": [{"resource_id": "ephemeral", "path": str(owned), "ephemeral": True,
                           "run_scoped": True, "ownership_generation": "generation-1"}],
            "agents": [], "sessions": [], "crons": [], "hooks": [], "launchd": [],
            "local_processes": [], "remote_processes": [], "locks": [],
        }))
        codex, codex_counter = self.fake_codex(root)
        claude, claude_counter = self.fake_claude(root)
        self.runtime(
            "init-policy", "--plan-dir", str(plan), "--worker-model", "MiniMax-M3-e2e",
            "--worker-max-budget-usd", "0.1", "--frontier-model", "gpt-frontier-e2e",
            "--max-frontier-calls", "7", "--max-frontier-input-tokens", "40000",
            "--max-frontier-output-tokens", "3000",
        )

        intermediate = plan / "artifacts" / "intermediate" / "make-evaluator"
        evaluator, evidence = intermediate / "evaluator.json", intermediate / "evidence.json"
        brief = plan / "normalized-brief.md"
        brief.write_text("bounded brief")
        task = plan / "task.json"
        output_schema = {"type":"object","additionalProperties":False,"required":["summary","ok","artifacts"],"properties":{"summary":{"type":"string"},"ok":{"type":"boolean"},"artifacts":{"type":"array","items":{"type":"object","additionalProperties":False,"required":["artifact_id","path","content","sha256"],"properties":{"artifact_id":{"type":"string"},"path":{"type":"string"},"content":{"type":"string"},"sha256":{"type":"string"}}}}}}
        task.write_text(json.dumps({
            "schema_version":1,"task_id":"make-evaluator","instruction":"propose evaluator artifacts",
            "inputs":[{"path":str(brief)}],"allowed_tools":[],"allowed_write_paths":[],
            "artifact_outputs":[
                {"artifact_id":"evaluator","path":str(evaluator),"content_field":"content","max_bytes":10000,
                 "capability":{"class":"research-intermediate"}},
                {"artifact_id":"evidence","path":str(evidence),"content_field":"content","max_bytes":1000,
                 "capability":{"class":"research-intermediate"}},
            ],"completion_check":{"type":"output_schema","assertion":"valid"},"output_schema":output_schema,
        }))
        paths: dict[str, Path] = {
            "normalized_brief": brief, "execution_plan": plan / "execution.json",
            "risk_budget": plan / "risk.json", "metric_contract": plan / "metric-contract.json",
            "calibration_candidate": plan / "calibration.md", "failure_candidate_1": plan / "fail-1.md",
            "failure_candidate_2": plan / "fail-2.md", "direction_1": plan / "direction-1.json",
            "direction_2": plan / "direction-2.json", "pivot_proposal": plan / "pivot.json",
            "dispute_record": plan / "dispute.json", "final_candidate": plan / "final-candidate.json",
            "baselines": plan / "baselines.json", "seeds_splits": plan / "seeds.json",
            "leakage_controls": plan / "leakage.json", "claim_evidence_map": plan / "claims.json",
            "raw_result_manifest": plan / "raw-results.json", "uncertainty_robustness": plan / "robustness.json",
        }
        for key in ("execution_plan","risk_budget","baselines","seeds_splits","leakage_controls","claim_evidence_map","raw_result_manifest","uncertainty_robustness"):
            paths[key].write_text("{}")
        paths["metric_contract"].write_text(json.dumps({"schema_version":1,"metric":"score","operator":"gte","threshold":0.8}))
        paths["calibration_candidate"].write_text('{"score":0.9}')
        paths["failure_candidate_1"].write_text('{"score":0.1}')
        paths["failure_candidate_2"].write_text('{"score":0.1}')
        for index, family in ((1,"transformer"),(2,"graph")):
            candidate = paths[f"failure_candidate_{index}"]
            paths[f"direction_{index}"].write_text(json.dumps({
                "algorithm_family":family,"data_representation":"tokens","objective":"score",
                "evaluator":"frozen","baseline_framing":"base","lineage":f"root-{index}",
                "candidate_sha256":hashlib.sha256(candidate.read_bytes()).hexdigest(),
            }))
        paths["pivot_proposal"].write_text(json.dumps({"direction":{
            "algorithm_family":"diffusion","data_representation":"latent","objective":"score",
            "evaluator":"frozen","baseline_framing":"base","lineage":"pivot",
        }}))
        paths["dispute_record"].write_text(json.dumps({
            "candidate_id":"canonical_failure_2","resolution":"accept","rationale":"bounded evidence reconciled",
        }))
        paths["final_candidate"].write_text('{"score":0.9}')

        figure_dir = plan / "out" / "figures"
        figure_dir.mkdir(parents=True)
        method_spec = plan / "method-figure-spec.md"
        render_script = figure_dir / "render-method.py"
        method_spec.write_text("# Frozen method\ninput -> evaluator -> decision\n")
        render_script.write_text("print('deterministic fixture renderer')\n")
        expected_figure_ids = [f"fig-method-{index}" for index in range(1, 5)]
        figure_records: list[dict[str, str]] = []
        for figure_id in expected_figure_ids:
            vector = figure_dir / f"{figure_id}.pdf"
            preview = figure_dir / f"{figure_id}.png"
            review = figure_dir / f"{figure_id}.review.json"
            figure_manifest = figure_dir / f"{figure_id}.manifest.json"
            vector.write_bytes(
                f"%PDF-1.4\n% {figure_id} fixture\n%%EOF\n".encode()
            )
            preview.write_bytes(b"\x89PNG\r\n\x1a\n" + figure_id.encode())
            review.write_text(json.dumps({
                "schema_version": 1,
                "figure_id": figure_id,
                "reviewed_at": "2026-07-24T16:10:00+08:00",
                "reviewer_kind": "human",
                "reviewer_identity": "human-e2e-fixture",
                "independent_of_renderer": True,
                "decision": "PASS",
                "reviewed_outputs": [
                    {
                        "path": f"out/figures/{figure_id}.pdf",
                        "sha256": hashlib.sha256(vector.read_bytes()).hexdigest(),
                    },
                    {
                        "path": f"out/figures/{figure_id}.png",
                        "sha256": hashlib.sha256(preview.read_bytes()).hexdigest(),
                    },
                ],
            }, indent=2) + "\n")
            figure_manifest.write_text(json.dumps({
                "schema_version": 1,
                "figure_id": figure_id,
                "figure_kind": "method_schematic",
                "generation": {
                    "mode": "deterministic",
                    "capability": "deterministic-local-renderer",
                    "capability_revision": "fixture-renderer-v1",
                },
                "inputs": [
                    {
                        "path": "method-figure-spec.md",
                        "sha256": hashlib.sha256(method_spec.read_bytes()).hexdigest(),
                        "role": "render_spec",
                        "purpose": "Frozen method structure.",
                    },
                    {
                        "path": "out/figures/render-method.py",
                        "sha256": hashlib.sha256(render_script.read_bytes()).hexdigest(),
                        "role": "render_script",
                        "purpose": "Deterministic local renderer.",
                    },
                ],
                "transformations": [],
                "renderer": {
                    "identity": "fixture-local-renderer",
                    "version": "1",
                    "source_revision": "fixture-renderer-v1",
                    "command": ["python3", "out/figures/render-method.py"],
                    "random_seed": 0,
                },
                "outputs": [
                    {
                        "path": f"out/figures/{figure_id}.pdf",
                        "sha256": hashlib.sha256(vector.read_bytes()).hexdigest(),
                        "role": "manuscript",
                        "media_type": "application/pdf",
                    },
                    {
                        "path": f"out/figures/{figure_id}.png",
                        "sha256": hashlib.sha256(preview.read_bytes()).hexdigest(),
                        "role": "preview",
                        "media_type": "image/png",
                    },
                ],
                "provenance": {
                    "plan_id": "plan_e2e",
                    "created_at": "2026-07-24T16:00:00+08:00",
                    "research_authority": {
                        "kind": "method_spec",
                        "path": "method-figure-spec.md",
                        "sha256": hashlib.sha256(method_spec.read_bytes()).hexdigest(),
                    },
                    "claim_ids": [],
                },
                "independent_review": {
                    "receipt": {
                        "path": f"out/figures/{figure_id}.review.json",
                        "sha256": hashlib.sha256(review.read_bytes()).hexdigest(),
                    },
                    "reviewer_kind": "human",
                    "reviewer_identity": "human-e2e-fixture",
                    "independent_of_renderer": True,
                    "decision": "PASS",
                    "ai_quality_score_used_as_authority": False,
                },
            }, indent=2) + "\n")
            figure_records.append({
                "figure_id": figure_id,
                "manifest": str(figure_manifest.relative_to(plan)),
                "sha256": hashlib.sha256(figure_manifest.read_bytes()).hexdigest(),
            })
        figure_requirements = plan / "state" / "figure-requirements.json"
        figure_requirements.write_text(json.dumps({
            "schema_version": 1,
            "plan_id": "plan_e2e",
            "tier": "conference",
            "expected_figure_ids": expected_figure_ids,
        }, indent=2) + "\n")
        figure_inventory = plan / "state" / "figure-inventory.json"
        figure_inventory.write_text(json.dumps({
            "schema_version": 1,
            "plan_id": "plan_e2e",
            "required_figures": figure_records,
        }, indent=2) + "\n")

        key = root / "human.key"
        key.write_bytes(b"k" * 32)
        key.chmod(0o600)
        paper = plan / "artifacts" / "paper" / "paper.md"
        writer_task = plan / "writer-task.json"
        writer_schema = output_schema
        writer_task.write_text(json.dumps({
            "schema_version":1,"task_id":"write-paper","instruction":"propose the final paper after authorization",
            "inputs":[{"path":str(paths["final_candidate"])}],"allowed_tools":[],"allowed_write_paths":[],
            "artifact_outputs":[{"artifact_id":"paper_deliverable","path":str(paper),"content_field":"content",
                                 "max_bytes":100000,"capability":{"class":"paper-deliverable"}}],
            "completion_check":{"type":"output_schema","assertion":"valid"},"output_schema":writer_schema,
        }))
        inputs = {
            "plan_id":"plan_e2e","codex_bin":str(codex),"claude_bin":str(claude),"task_contract":str(task),
            "evaluator":str(evaluator),"evidence_manifest":str(evidence),
            **{name:str(path) for name,path in paths.items()},
            "figure_requirements": str(figure_requirements),
            "figure_inventory": str(figure_inventory),
            "writer_task_contract":str(writer_task),
        }
        inputs_path = plan / "canonical-inputs.json"
        inputs_path.write_text(json.dumps(inputs, indent=2))
        return plan, inputs_path, claude_counter, codex_counter

    def authorize(self, root: Path, plan: Path, *, bind: bool = True, suffix: str = "canonical") -> Path:
        key = root / "human.key"
        binding: list[str] = []
        if bind:
            proposal_path = plan / "control" / "human_authorization_required.json"
            proposal = json.loads(proposal_path.read_text())
            binding = ["--authorization-proposal", str(proposal_path),
                       "--prepared-operation-id", proposal["prepared_operation_id"]]
        stop = self.runtime(
            "create-human-action", "--plan-dir", str(plan), "--plan-id", "plan_e2e", "--action", "stop",
            "--key-file", str(key), "--expires-in", "3600", "--record-id", f"har_{suffix}_stop",
            "--reason", "workflow complete", *binding,
        )
        cleanup = self.runtime(
            "create-human-action", "--plan-dir", str(plan), "--plan-id", "plan_e2e", "--action", "cleanup_resource",
            "--key-file", str(key), "--expires-in", "3600", "--record-id", f"har_{suffix}_cleanup",
            "--resource-id", "ephemeral", *binding,
        )
        owned = plan / "ephemeral.tmp"
        token = hashlib.sha256(f"plan_e2e\0{owned.resolve()}\0generation-1".encode()).hexdigest()
        bundle = plan / "human-actions.json"
        bundle.write_text(json.dumps({
            "schema_version":1,"key_file":str(key),"stop_record":stop["record_path"],
            "cleanup_actions":[{"record":cleanup["record_path"],"resource_id":"ephemeral","ownership_token":token}],
        }))
        return bundle

    def complete(self, root: Path, plan: Path, inputs: Path) -> subprocess.CompletedProcess[str]:
        argv = [sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW), "--inputs", str(inputs)]
        waiting = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(waiting.returncode, 3, waiting.stderr)
        self.assertEqual(json.loads(waiting.stdout)["status"], "AWAITING_HUMAN_AUTHORIZATION")
        bundle = self.authorize(root, plan)
        return subprocess.run([*argv, "--human-actions", str(bundle)], cwd=ROOT, text=True, capture_output=True)

    def test_complete_packaged_workflow_without_mavis(self) -> None:
        self.assertIsNone(shutil.which("mavis"))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, inputs, claude_counter, codex_counter = self.prepare(root)
            paper = plan / "artifacts" / "paper" / "paper.md"
            self.assertFalse(paper.exists())
            env = {**os.environ, "PATH": "/usr/bin:/bin"}
            proc = self.complete(root, plan, inputs)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["workflow_kind"], "claude-research-conformance-v1")
            self.assertEqual(len(result["completed_steps"]), 41)
            self.assertEqual({item["type"] for item in result["terminal_artifacts"]}, {
                "workflow_journal","evaluator_contract","evaluator_verdict","structural_pivot",
                "figure_gate","writing_gate_audit","paper_deliverable","cleanup_receipt",
            })
            self.assertEqual(claude_counter.read_text(), "2")
            self.assertEqual(codex_counter.read_text(), "5")
            manifest = json.loads(Path(result["terminal_manifest"]).read_text())
            for item in manifest["artifacts"]:
                self.assertEqual(item["sha256"], hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest())
                if item["type"] != "workflow_journal":
                    self.assertEqual(Path(item["path"]).name, item["sha256"])
                    self.assertIn("terminal_snapshots", Path(item["path"]).parts)
                    self.assertEqual(Path(item["path"]).stat().st_mode & 0o222, 0)
                    self.assertIn("source_path", item)
            journal = Path(result["journal"])
            self.assertEqual(manifest["journal_sha256"], hashlib.sha256(journal.read_bytes()).hexdigest())
            paper.write_text("producer path changed after manifest validation\n")
            again = subprocess.run(
                [sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW),
                 "--inputs", str(inputs), "--human-actions", str(plan / "human-actions.json")],
                cwd=ROOT, text=True, capture_output=True, env=env,
            )
            self.assertEqual(again.returncode, 0, again.stderr)
            again_result = json.loads(again.stdout)
            paper_snapshot = next(item for item in again_result["terminal_artifacts"] if item["type"] == "paper_deliverable")
            self.assertNotEqual(paper_snapshot["path"], str(paper))
            self.assertNotEqual(hashlib.sha256(paper.read_bytes()).hexdigest(), paper_snapshot["sha256"])
            self.assertEqual(hashlib.sha256(Path(paper_snapshot["path"]).read_bytes()).hexdigest(), paper_snapshot["sha256"])
            self.assertEqual(claude_counter.read_text(), "2")
            self.assertEqual(codex_counter.read_text(), "5")

    def test_runner_reconciles_success_after_prepared_journal_interruption(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, inputs, claude_counter, codex_counter = self.prepare(root)
            argv = [
                sys.executable, str(RUNNER), "--plan-dir", str(plan),
                "--workflow", str(WORKFLOW), "--inputs", str(inputs),
            ]
            crashed = subprocess.run(
                [*argv, "--simulate-crash-after-step", "cp01_send"],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(crashed.returncode, 2)
            self.assertIn("simulated runner crash", crashed.stderr)
            self.assertEqual(codex_counter.read_text(), "1")
            resumed = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(resumed.returncode, 3, resumed.stderr)
            bundle = self.authorize(root, plan)
            completed = subprocess.run([*argv, "--human-actions", str(bundle)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(codex_counter.read_text(), "5")
            self.assertEqual(claude_counter.read_text(), "2")

    def test_output_capabilities_and_namespaces_gate_dispatch_and_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs, _, _ = self.prepare(root)
            argv = [sys.executable, str(RUNNER), "--plan-dir", str(plan),
                    "--workflow", str(WORKFLOW), "--inputs", str(inputs),
                    "--simulate-crash-after-step", "cp01_apply"]
            self.assertEqual(subprocess.run(argv, cwd=ROOT, capture_output=True).returncode, 2)
            destination = plan / "article" / "submission.md"
            declaration = {"artifact_id":"article","path":str(destination),
                           "content_field":"content","max_bytes":1000}
            task = json.loads((plan / "task.json").read_text())
            task.update({"task_id":"early-paper","artifact_outputs":[declaration]})
            contract = plan / "early-paper-task.json"; contract.write_text(json.dumps(task))
            rejected = subprocess.run([sys.executable, str(RUNTIME), "dispatch-worker",
                "--plan-dir", str(plan), "--task-contract", str(contract), "--claude-bin", "/bin/false"],
                cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("capability", rejected.stderr)
            for index, declaration_override in enumerate((
                {**declaration, "capability":{"class":"paper-deliverable"}},
                {**declaration, "path":str(plan / "safe.bin"),
                 "capability":{"class":"research-intermediate"}},
                {**declaration, "path":str(plan / "artifacts" / "intermediate" / "sibling" / "x.md"),
                 "capability":{"class":"research-intermediate"}},
            )):
                task["artifact_outputs"] = [declaration_override]
                alias_contract = plan / f"early-paper-alias-{index}.json"
                alias_contract.write_text(json.dumps(task))
                alias_rejected = subprocess.run([sys.executable, str(RUNTIME), "dispatch-worker",
                    "--plan-dir", str(plan), "--task-contract", str(alias_contract), "--claude-bin", "/bin/false"],
                    cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(alias_rejected.returncode, 2)
            run_id = "cwr_" + "a" * 32
            run_dir = plan / "state" / "worker_runs" / run_id; run_dir.mkdir(parents=True)
            content = "# illicit article\n"; digest = hashlib.sha256(content.encode()).hexdigest()
            result = run_dir / "result.json"; result.write_text(json.dumps({"result":{"artifacts":[{
                "artifact_id":"article","path":str(destination),"content":content,"sha256":digest}]}}))
            status = {"schema_version":1,"run_id":run_id,"status":"COMPLETED",
                      "contract_path":str(contract),"contract_sha256":hashlib.sha256(contract.read_bytes()).hexdigest(),
                      "result_path":str(result),"result_sha256":hashlib.sha256(result.read_bytes()).hexdigest()}
            (run_dir / "status.json").write_text(json.dumps(status))
            rejected = subprocess.run([sys.executable, str(RUNTIME), "promote-worker-artifacts",
                "--plan-dir", str(plan), "--worker-run-id", run_id], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertFalse(destination.exists())
            claude_bin = json.loads(inputs.read_text())["claude_bin"]
            for field in ("class", "path"):
                dispatched = self.runtime(
                    "dispatch-worker", "--plan-dir", str(plan), "--task-contract", str(plan / "task.json"),
                    "--claude-bin", claude_bin,
                )
                status_path = plan / "state" / "worker_runs" / dispatched["run_id"] / "status.json"
                drifted = json.loads(status_path.read_text())
                if field == "class":
                    drifted["artifact_outputs"][0]["capability"]["class"] = "paper-deliverable"
                else:
                    drifted["artifact_outputs"][0]["path"] = str(
                        plan / "artifacts" / "intermediate" / "sibling" / "evaluator.json"
                    )
                status_path.write_text(json.dumps(drifted))
                drift_rejected = subprocess.run([
                    sys.executable, str(RUNTIME), "promote-worker-artifacts", "--plan-dir", str(plan),
                    "--worker-run-id", dispatched["run_id"],
                ], cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(drift_rejected.returncode, 2)
                self.assertIn("frozen artifact capability or path", drift_rejected.stderr)

    def test_writing_gate_consumers_revalidate_authority_and_candidate_input(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs_path, _, _ = self.prepare(root)
            inputs = json.loads(inputs_path.read_text())
            stopped = subprocess.run([
                sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW),
                "--inputs", str(inputs_path), "--simulate-crash-after-step", "writing_gate",
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(stopped.returncode, 2, stopped.stderr)
            original_path = next((plan / "state" / "writing_gates").glob("*.json"))
            original = json.loads(original_path.read_text())
            other_candidate = plan / "other-writer-candidate.json"
            other_candidate.write_text('{"score":0.2}')
            forged = {**original,
                      "candidate_path":str(other_candidate.resolve()),
                      "candidate_sha256":hashlib.sha256(other_candidate.read_bytes()).hexdigest()}
            body = {key:value for key,value in forged.items() if key not in {"checked_at","decision_sha256"}}
            forged["decision_sha256"] = hashlib.sha256(json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            ).encode()).hexdigest()
            forged_path = original_path.with_name(f"{forged['decision_sha256']}.json")
            forged_path.write_text(json.dumps(forged))
            with (plan / "state" / "writing_gate_audit.jsonl").open("a") as handle:
                handle.write(json.dumps(forged, sort_keys=True) + "\n")
            forged_dispatch = subprocess.run([
                sys.executable, str(RUNTIME), "dispatch-worker", "--plan-dir", str(plan),
                "--task-contract", inputs["writer_task_contract"], "--claude-bin", inputs["claude_bin"],
                "--writing-gate-receipt", str(forged_path),
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(forged_dispatch.returncode, 2)
            self.assertIn("complete authority chain", forged_dispatch.stderr)

            writer = json.loads(Path(inputs["writer_task_contract"]).read_text())
            writer["inputs"] = [{"path":str(other_candidate)}]
            mismatched_contract = plan / "mismatched-writer-task.json"
            mismatched_contract.write_text(json.dumps(writer))
            mismatched_dispatch = subprocess.run([
                sys.executable, str(RUNTIME), "dispatch-worker", "--plan-dir", str(plan),
                "--task-contract", str(mismatched_contract), "--claude-bin", inputs["claude_bin"],
                "--writing-gate-receipt", str(original_path),
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(mismatched_dispatch.returncode, 2)
            self.assertIn("exact authorized candidate", mismatched_dispatch.stderr)

    def test_initial_human_actions_cannot_bypass_durable_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs, _, _ = self.prepare(root)
            stale = self.authorize(root, plan, bind=False, suffix="stale")
            argv = [sys.executable, str(RUNNER), "--plan-dir", str(plan),
                    "--workflow", str(WORKFLOW), "--inputs", str(inputs)]
            first = subprocess.run([*argv, "--human-actions", str(stale)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(first.returncode, 3, first.stderr)
            self.assertTrue((plan / "control" / "human_authorization_required.json").is_file())
            self.assertTrue((plan / "ephemeral.tmp").is_file())
            self.assertFalse((plan / "state" / "human_authorization_boundaries" / "canonical_research_conformance.json").exists())
            rejected = subprocess.run([*argv, "--human-actions", str(stale)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("not bound", rejected.stderr)
            journal = json.loads((plan / "state" / "canonical_flows" / "canonical_research_conformance.json").read_text())
            self.assertEqual(journal["status"], "AWAITING_HUMAN_AUTHORIZATION")

    def test_replaced_authorization_proposal_cannot_be_rebound(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs, _, _ = self.prepare(root)
            argv = [sys.executable, str(RUNNER), "--plan-dir", str(plan),
                    "--workflow", str(WORKFLOW), "--inputs", str(inputs)]
            self.assertEqual(subprocess.run(argv, cwd=ROOT, capture_output=True).returncode, 3)
            proposal_path = plan / "control" / "human_authorization_required.json"
            journal_path = plan / "state" / "canonical_flows" / "canonical_research_conformance.json"
            journal = json.loads(journal_path.read_text())
            original_hash = hashlib.sha256(proposal_path.read_bytes()).hexdigest()
            self.assertEqual(journal["authorization_proposal_sha256"], original_hash)
            self.assertEqual(journal["authorization_prepared_operation_id"],
                             json.loads(proposal_path.read_text())["prepared_operation_id"])
            proposal_path.chmod(0o644)
            replacement = json.loads(proposal_path.read_text())
            replacement["required_actions"] = ["replacement_binding"]
            proposal_path.write_text(json.dumps(replacement))
            rebound = self.authorize(root, plan, suffix="replacement")
            rejected = subprocess.run([*argv, "--human-actions", str(rebound)], cwd=ROOT,
                                      text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("proposal bytes changed", rejected.stderr)
            self.assertEqual(json.loads(journal_path.read_text())["status"], "AWAITING_HUMAN_AUTHORIZATION")
            self.assertTrue((plan / "ephemeral.tmp").exists())

    def test_zero_resource_plan_completes_with_stop_only_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs_path, _, _ = self.prepare(root)
            manifest_path = plan / "resource_manifest.json"
            manifest = json.loads(manifest_path.read_text()); manifest["resources"] = []
            manifest_path.write_text(json.dumps(manifest))
            (plan / "ephemeral.tmp").unlink()
            argv = [
                sys.executable, str(RUNNER), "--plan-dir", str(plan),
                "--workflow", str(WORKFLOW), "--inputs", str(inputs_path),
            ]
            waiting = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(waiting.returncode, 3, waiting.stderr)
            proposal_path = plan / "control" / "human_authorization_required.json"
            proposal = json.loads(proposal_path.read_text())
            key = root / "human.key"
            stop = self.runtime(
                "create-human-action", "--plan-dir", str(plan), "--plan-id", "plan_e2e",
                "--action", "stop", "--key-file", str(key), "--expires-in", "3600",
                "--record-id", "har_zero_stop", "--reason", "workflow complete",
                "--authorization-proposal", str(proposal_path),
                "--prepared-operation-id", proposal["prepared_operation_id"],
            )
            bundle = plan / "zero-human-actions.json"
            bundle.write_text(json.dumps({
                "schema_version":1, "key_file":str(key), "stop_record":stop["record_path"],
                "cleanup_actions":[],
            }))
            done = subprocess.run([*argv, "--human-actions", str(bundle)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            boundary = json.loads((
                plan / "state" / "human_authorization_boundaries" / "canonical_research_conformance.json"
            ).read_text())
            self.assertEqual(boundary["cleanup_results"], [])

    def test_missing_terminal_artifact_never_persists_completed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs, _, _ = self.prepare(root)
            argv = [sys.executable, str(RUNNER), "--plan-dir", str(plan),
                    "--workflow", str(WORKFLOW), "--inputs", str(inputs)]
            self.assertEqual(subprocess.run(argv, cwd=ROOT, capture_output=True).returncode, 3)
            bundle = self.authorize(root, plan)
            crashed = subprocess.run([*argv, "--human-actions", str(bundle),
                "--simulate-crash-after-step", "await_human"], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(crashed.returncode, 2)
            (plan / "artifacts" / "paper" / "paper.md").unlink()
            rejected = subprocess.run([*argv, "--human-actions", str(bundle)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2)
            journal_path = plan / "state" / "canonical_flows" / "canonical_research_conformance.json"
            self.assertNotEqual(json.loads(journal_path.read_text())["status"], "COMPLETED")
            self.assertFalse(journal_path.with_name("canonical_research_conformance.terminal-manifest.json").exists())

    def test_runner_rejects_incomplete_or_arbitrary_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan = root / "plan"
            plan.mkdir()
            workflow = json.loads(WORKFLOW.read_text())
            workflow["steps"].pop()
            bad = root / "bad-workflow.json"
            bad.write_text(json.dumps(workflow))
            inputs = root / "inputs.json"
            inputs.write_text("{}")
            proc = subprocess.run(
                [sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(bad), "--inputs", str(inputs)],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("canonical workflow is incomplete", proc.stderr)
            canonical = json.loads(WORKFLOW.read_text())
            mutations = []
            changed_arg = json.loads(json.dumps(canonical)); changed_arg["steps"][0]["args"]["max_output_tokens"] = 499; mutations.append(changed_arg)
            changed_ref = json.loads(json.dumps(canonical)); changed_ref["steps"][1]["args"]["request_id"] = "far_other"; mutations.append(changed_ref)
            changed_terminal = json.loads(json.dumps(canonical)); changed_terminal["terminal_artifacts"][5]["path"] = "${input.final_candidate}"; mutations.append(changed_terminal)
            changed_input = json.loads(json.dumps(canonical)); changed_input["required_inputs"][0] = "other_plan_id"; mutations.append(changed_input)
            for index, mutation in enumerate(mutations):
                mutated = root / f"mutated-{index}.json"
                mutated.write_text(json.dumps(mutation))
                rejected = subprocess.run(
                    [sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(mutated), "--inputs", str(inputs)],
                    cwd=ROOT, text=True, capture_output=True,
                )
                self.assertEqual(rejected.returncode, 2)
                self.assertIn("closed template", rejected.stderr)

    def test_threshold_provenance_comes_only_from_cp02_metric_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, inputs_path, _, _ = self.prepare(Path(td))
            inputs = json.loads(inputs_path.read_text())
            metric = Path(inputs["metric_contract"])
            metric.write_text(json.dumps({"schema_version":1,"metric":"score","operator":"gte","threshold":0.95}))
            crashed = subprocess.run([
                sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW),
                "--inputs", str(inputs_path), "--simulate-crash-after-step", "freeze_evaluator",
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(crashed.returncode, 2)
            frozen = json.loads((plan / "state" / "evaluator_contract.json").read_text())
            self.assertEqual(frozen["threshold"], 0.95)
            self.assertEqual(frozen["metric_contract_sha256"], hashlib.sha256(metric.read_bytes()).hexdigest())
            independent = subprocess.run([
                sys.executable, str(RUNTIME), "freeze-evaluator", "--plan-dir", str(plan),
                "--execution-receipt", frozen["calibration_execution_sha256"],
                "--threshold", "0.0",
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(independent.returncode, 2)

    def test_same_direction_on_new_candidate_counts_one_distinct_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            plan, inputs_path, _, _ = self.prepare(Path(td))
            inputs = json.loads(inputs_path.read_text())
            first = json.loads(Path(inputs["direction_1"]).read_text())
            second_candidate = Path(inputs["failure_candidate_2"])
            first["candidate_sha256"] = hashlib.sha256(second_candidate.read_bytes()).hexdigest()
            Path(inputs["direction_2"]).write_text(json.dumps(first))
            proc = subprocess.run([
                sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW),
                "--inputs", str(inputs_path), "--simulate-crash-after-step", "failure_record_2",
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 2)
            state = json.loads((plan / "state" / "failure_state.json").read_text())
            self.assertEqual(state["scientific_no_improvement_count"], 2)
            self.assertEqual(len(state["distinct_scientific_fingerprints"]), 1)
            entry = next(iter(state["direction_registry"].values()))
            self.assertEqual(len(entry["outcomes"]), 2)

    def test_two_cp03_cycles_have_independent_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plan, inputs_path, _, _ = self.prepare(root)
            first = self.complete(root, plan, inputs_path)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertFalse(self.runtime("pivot-eligibility", "--plan-dir", str(plan))["eligible"])
            inputs = json.loads(inputs_path.read_text())
            evaluator, evidence = Path(inputs["evaluator"]), Path(inputs["evidence_manifest"])
            latest_verdict: Path | None = None
            for index, family in ((3, "kernel"), (4, "causal")):
                candidate = plan / f"cycle2-fail-{index}.md"
                candidate.write_text('{"score":0.1}')
                run = self.runtime(
                    "run-evaluator", "--plan-dir", str(plan), "--evaluator", str(evaluator),
                    "--evidence", str(evidence), "--candidate", str(candidate), "--purpose", "candidate",
                )
                verdict = self.runtime(
                    "record-evaluator-verdict", "--plan-dir", str(plan),
                    "--execution-receipt", run["execution_receipt"], "--candidate-id", f"cycle2-{index}",
                )
                latest_verdict = Path(verdict["verdict_path"])
                direction = plan / f"cycle2-direction-{index}.json"
                direction.write_text(json.dumps({
                    "algorithm_family":family,"data_representation":"tokens","objective":"score",
                    "evaluator":"frozen","baseline_framing":"base","lineage":f"cycle2-{index}",
                    "candidate_sha256":hashlib.sha256(candidate.read_bytes()).hexdigest(),
                }))
                self.runtime(
                    "record-failure", "--plan-dir", str(plan), "--class", "scientific_no_improvement",
                    "--direction", str(direction), "--verdict", str(latest_verdict), "--source", "cycle2",
                )
                if index == 3:
                    self.assertFalse(self.runtime("pivot-eligibility", "--plan-dir", str(plan))["eligible"])
            proposal = plan / "pivot-cycle-2.json"
            proposal.write_text(json.dumps({"direction":{
                "algorithm_family":"symbolic","data_representation":"graph","objective":"score",
                "evaluator":"frozen","baseline_framing":"base","lineage":"cycle2-pivot",
            }}))
            args = [
                "create-frontier-request","--plan-dir",str(plan),"--plan-id","plan_e2e","--checkpoint","CP-03",
                "--attempt","2","--objective","second structural pivot","--decision-required","authorize_structural_pivot",
                "--max-input-tokens","15000","--max-output-tokens","500","--request-id","far_canonical_cp03_cycle2",
                "--artifact",f"{plan/'state'/'failure_state.json'}::failure_state",
                "--artifact",f"{plan/'state'/'failure_state.json'}::direction_registry",
                "--artifact",f"{proposal}::pivot_proposal",
                "--artifact",f"{latest_verdict}::evaluator_verdict",
            ]
            self.runtime(*args)
            codex = inputs["codex_bin"]
            for command in ("send-frontier-request", "validate-frontier-response"):
                extra = ("--codex-bin", codex) if command.startswith("send") else ()
                self.runtime(command, "--plan-dir", str(plan), "--request-id", "far_canonical_cp03_cycle2", *extra)
            self.runtime(
                "apply-frontier-response", "--plan-dir", str(plan), "--request-id", "far_canonical_cp03_cycle2",
                "--dependent-transition", "authorize_structural_pivot", "--controller-note", "cycle two accepted",
            )
            self.runtime("apply-structural-pivot", "--plan-dir", str(plan), "--proposal", str(proposal))
            self.assertEqual(len(list((plan / "state" / "structural_pivots").glob("pivot_*.json"))), 2)
            self.assertEqual(len(list((plan / "state" / "frontier" / "transitions" / "authorize_structural_pivot").glob("far_*.json"))), 2)

    def test_pivot_state_commit_recovers_receipt_through_operation_journal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs_path, _, _ = self.prepare(root)
            argv = [
                sys.executable, str(RUNNER), "--plan-dir", str(plan),
                "--workflow", str(WORKFLOW), "--inputs", str(inputs_path),
            ]
            fault = subprocess.run(
                argv, cwd=ROOT, text=True, capture_output=True,
                env={**os.environ, "HARNESS_FAULT_AFTER_PIVOT_STATE": "1"},
            )
            self.assertEqual(fault.returncode, 2, fault.stderr)
            state = json.loads((plan / "state" / "failure_state.json").read_text())
            self.assertEqual(state["pivot_epoch"], 1)
            self.assertEqual(list((plan / "state" / "structural_pivots").glob("*.json")), [])
            waiting = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(waiting.returncode, 3, waiting.stderr)
            pivots = list((plan / "state" / "structural_pivots").glob("*.json"))
            self.assertEqual(len(pivots), 1)
            audit = [json.loads(line) for line in (plan / "state" / "structural_pivot_audit.jsonl").read_text().splitlines()]
            self.assertEqual(len(audit), 1)
            bundle = self.authorize(root, plan)
            done = subprocess.run([*argv, "--human-actions", str(bundle)], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(done.returncode, 0, done.stderr)

    def test_pivot_receipt_recovery_rejects_unrelated_state_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs_path, _, _ = self.prepare(root)
            argv = [
                sys.executable, str(RUNNER), "--plan-dir", str(plan),
                "--workflow", str(WORKFLOW), "--inputs", str(inputs_path),
            ]
            fault = subprocess.run(
                argv, cwd=ROOT, text=True, capture_output=True,
                env={**os.environ, "HARNESS_FAULT_AFTER_PIVOT_STATE": "1"},
            )
            self.assertEqual(fault.returncode, 2, fault.stderr)
            state_path = plan / "state" / "failure_state.json"
            drifted = json.loads(state_path.read_text())
            drifted["runtime_stall_count"] = drifted.get("runtime_stall_count", 0) + 1
            state_path.write_text(json.dumps(drifted))
            rejected = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("recovery identity mismatch", rejected.stderr)
            self.assertEqual(list((plan / "state" / "structural_pivots").glob("*.json")), [])

    def test_declarative_evaluator_and_nonfinite_values_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs_path, _, _ = self.prepare(root)
            inputs = json.loads(inputs_path.read_text())
            stopped = subprocess.run([
                sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW),
                "--inputs", str(inputs_path), "--simulate-crash-after-step", "worker_promote",
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(stopped.returncode, 2, stopped.stderr)
            evaluator = Path(inputs["evaluator"])
            spec = json.loads(evaluator.read_text()); spec["source"] = "evidence"
            evaluator.write_text(json.dumps(spec))
            unrelated = subprocess.run([
                sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW),
                "--inputs", str(inputs_path),
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(unrelated.returncode, 2)
            self.assertIn("must equal 'candidate'", unrelated.stderr)
            self.assertFalse((plan / "state" / "evaluator_contract.json").exists())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs_path, _, _ = self.prepare(root)
            inputs = json.loads(inputs_path.read_text())
            metric = Path(inputs["metric_contract"])
            metric.write_text('{"schema_version":1,"metric":"score","operator":"gte","threshold":Infinity}')
            invalid_metric = subprocess.run([
                sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW), "--inputs", str(inputs_path),
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(invalid_metric.returncode, 2)
            self.assertFalse((plan / "state" / "evaluator_contract.json").exists())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs_path, _, _ = self.prepare(root)
            inputs = json.loads(inputs_path.read_text())
            promoted = subprocess.run([
                sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW), "--inputs", str(inputs_path),
                "--simulate-crash-after-step", "worker_promote",
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(promoted.returncode, 2)
            manifest_before = hashlib.sha256((plan / "resource_manifest.json").read_bytes()).hexdigest()
            Path(inputs["evaluator"]).chmod(0o644)
            Path(inputs["evaluator"]).write_text('#!/usr/bin/env python3\nopen("state/controller.json","w").write("owned")\n')
            blocked = subprocess.run([
                sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW), "--inputs", str(inputs_path),
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("strict JSON", blocked.stderr)
            self.assertEqual(manifest_before, hashlib.sha256((plan / "resource_manifest.json").read_bytes()).hexdigest())
            self.assertFalse((plan / "state" / "controller.json").exists())

    def test_stateful_operation_faults_reconcile_without_duplicate_effects(self) -> None:
        for command in ("dispatch-worker", "run-evaluator", "freeze-evaluator", "record-evaluator-verdict", "send-frontier-request"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as td:
                root = Path(td); plan, inputs, claude_counter, codex_counter = self.prepare(root)
                argv = [sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW), "--inputs", str(inputs)]
                env = {**os.environ, "HARNESS_FAULT_AFTER_HANDLER": command}
                fault = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, env=env)
                self.assertEqual(fault.returncode, 2, fault.stderr)
                waiting = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(waiting.returncode, 3, waiting.stderr)
                bundle = self.authorize(root, plan)
                done = subprocess.run([*argv, "--human-actions", str(bundle)], cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(claude_counter.read_text(), "2")
                self.assertEqual(codex_counter.read_text(), "5")
        for command in ("apply-human-action", "remove-resource"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as td:
                root = Path(td); plan, inputs, _, _ = self.prepare(root)
                argv = [sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW), "--inputs", str(inputs)]
                waiting = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(waiting.returncode, 3, waiting.stderr)
                bundle = self.authorize(root, plan)
                env = {**os.environ, "HARNESS_FAULT_AFTER_HANDLER": command}
                fault = subprocess.run([*argv, "--human-actions", str(bundle)], cwd=ROOT, text=True, capture_output=True, env=env)
                self.assertEqual(fault.returncode, 2, fault.stderr)
                done = subprocess.run([*argv, "--human-actions", str(bundle)], cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertFalse((plan / "ephemeral.tmp").exists())

    def test_canonical_writer_is_blocked_by_missing_empty_incomplete_or_stale_figure_inventory(self) -> None:
        for mode in ("missing", "empty", "incomplete", "stale-output"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                plan, inputs_path, _, _ = self.prepare(root)
                inputs = json.loads(inputs_path.read_text())
                inventory = Path(inputs["figure_inventory"])
                if mode == "missing":
                    inventory.unlink()
                elif mode == "empty":
                    body = json.loads(inventory.read_text())
                    body["required_figures"] = []
                    inventory.write_text(json.dumps(body))
                elif mode == "incomplete":
                    body = json.loads(inventory.read_text())
                    body["required_figures"].pop()
                    inventory.write_text(json.dumps(body))
                else:
                    (plan / "out" / "figures" / "fig-method-1.pdf").write_bytes(
                        b"%PDF-1.4\n% changed after review\n%%EOF\n"
                    )
                proc = subprocess.run([
                    sys.executable,
                    str(RUNNER),
                    "--plan-dir",
                    str(plan),
                    "--workflow",
                    str(WORKFLOW),
                    "--inputs",
                    str(inputs_path),
                ], cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertIn("figure", proc.stderr.lower())
                self.assertFalse(
                    (plan / "artifacts" / "paper" / "paper.md").exists(),
                    "writer artifact must not exist before the complete figure gate",
                )

    def test_waiver_requires_cp04_for_exact_candidate_contract_and_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); plan, inputs_path, _, _ = self.prepare(root)
            inputs = json.loads(inputs_path.read_text())
            stopped = subprocess.run([
                sys.executable, str(RUNNER), "--plan-dir", str(plan), "--workflow", str(WORKFLOW),
                "--inputs", str(inputs_path), "--simulate-crash-after-step", "final_verdict",
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(stopped.returncode, 2, stopped.stderr)
            verdict = plan / "state" / "evaluator_verdicts" / "canonical_final.json"
            contract = plan / "state" / "evaluator_contract.json"
            candidate_a = Path(inputs["final_candidate"])
            candidate_b = plan / "other-candidate.json"; candidate_b.write_text('{"score":0.9}')
            figure_gate = self.runtime(
                "check-figure-gate",
                "--plan-dir", str(plan),
                "--inventory", inputs["figure_inventory"],
                "--requirements", inputs["figure_requirements"],
            )
            figure_gate_path = Path(figure_gate["gate_receipt"])

            def cp04(request_id: str, candidate: Path) -> None:
                roles = {
                    "candidate": candidate, "claim_evidence_map": Path(inputs["claim_evidence_map"]),
                    "evaluator_contract": contract, "evaluator_verdict": verdict,
                    "raw_result_manifest": Path(inputs["raw_result_manifest"]),
                    "baselines": Path(inputs["baselines"]),
                    "uncertainty_robustness": Path(inputs["uncertainty_robustness"]),
                    "figure_gate": figure_gate_path,
                }
                argv = [
                    "create-frontier-request", "--plan-dir", str(plan), "--plan-id", "plan_e2e",
                    "--checkpoint", "CP-04", "--checkpoint-subtype", "prewriting_final_evidence",
                    "--objective", "audit final evidence", "--decision-required", "start_writing",
                    "--max-input-tokens", "5000", "--max-output-tokens", "500", "--request-id", request_id,
                ]
                for role, path in roles.items(): argv.extend(["--artifact", f"{path}::{role}"])
                self.runtime(*argv)
                self.runtime("send-frontier-request", "--plan-dir", str(plan), "--request-id", request_id, "--codex-bin", inputs["codex_bin"])
                self.runtime("validate-frontier-response", "--plan-dir", str(plan), "--request-id", request_id)
                self.runtime("apply-frontier-response", "--plan-dir", str(plan), "--request-id", request_id,
                             "--dependent-transition", "start_writing", "--controller-note", "accepted")

            cp04("far_wrong_candidate", candidate_b)
            key = root / "human.key"
            created = self.runtime(
                "create-human-action", "--plan-dir", str(plan), "--plan-id", "plan_e2e",
                "--action", "waive_acceptance", "--key-file", str(key), "--expires-in", "300",
                "--record-id", "har_exact_waiver", "--reason", "human negative-result review",
                "--candidate", str(candidate_a), "--verdict", str(verdict), "--tier", "conference",
            )
            applied = self.runtime(
                "apply-human-action", "--plan-dir", str(plan), "--record", created["record_path"],
                "--key-file", str(key), "--expected-action", "waive_acceptance",
            )
            blocked = subprocess.run([
                sys.executable, str(RUNTIME), "check-writing-gate", "--plan-dir", str(plan),
                "--tier", "conference", "--waiver", applied["waiver_path"],
                "--figure-gate-receipt", str(figure_gate_path),
            ], cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(blocked.returncode, 20)
            cp04("far_exact_candidate", candidate_a)
            accepted = self.runtime(
                "check-writing-gate", "--plan-dir", str(plan), "--tier", "conference",
                "--waiver", applied["waiver_path"],
                "--figure-gate-receipt", str(figure_gate_path),
            )
            self.assertEqual(accepted["transition_request_id"], "far_exact_candidate")


if __name__ == "__main__":
    unittest.main()
