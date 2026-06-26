---
name: autoresearch-paper
description: Turn a paragraph-level research brief — topic + target venue + reference materials — into a publication-grade academic paper by orchestrating a Mavis agent team, an evidence-anchored plan.yaml, and a per-task watchdog. Use when the user says "帮我把这个课题写成论文", "autoresearch 写 paper", "从课题到发表", or wants a multi-day, multi-agent research-and-writing pipeline that they can pause and resume. Targets Mavis / MiniMax Code environments with `mavis team plan`, `mavis session new`, `mavis cron`, and `mavis hook` available. Does not replace human authorship of novel scientific claims; the human owns novelty, and the skill produces the structured work that surrounds it.
metadata:
  short-description: Brief-to-paper pipeline with Mavis agent team and watchdog
---

# Autoresearch Paper

Turn a paragraph-level brief into a publication-grade academic paper through a
fully orchestrated Mavis agent team, an evidence-anchored plan, and a
per-task watchdog. The user never writes `plan.yaml`, never schedules a cron,
and never registers a hook — the skill does all of that.

## What this skill is

This is the **runner** counterpart of `karpathy-autoresearch-adapter`. That
adapter decides whether a project has a real evaluator and produces an
adaptation plan. This skill assumes the evaluator and adaptation already
exist (or the topic is fresh-theory / simulation-based) and runs the actual
research-to-paper loop end to end.

```
user input (3 paragraphs)
   │
   ├── ① topic          what to study
   ├── ② target venue   where to publish (arxiv / 顶会 / SCI Q1)
   └── ③ materials      optional: papers, notes, datasets, prior art
   │
   ▼
[skill internal — user sees nothing]
   │
   ├─ parse → tier   (arxiv | conference | journal-q1)
   ├─ generate plan.yaml (literature → gap → method → expt → write-iter1 → write-iter2 → pkg)
   ├─ create <topic>-wd agent + cron + hooks
   ├─ /mavis-team plan run
   ├─ watchdog patrol (hourly cron + per-task last_seen)
   └─ deliver: paper.tex + reviewer-readiness self-check
```

## When to use

Use when the user wants a **multi-hour to multi-day** research-and-writing
pipeline that they can stop, inspect, and resume, and they accept that the
deliverable is a structured draft to refine, not a final camera-ready PDF.

Do **not** use when:

- The user wants a single short document (use `paper-deconstruction` for
  reading one paper, `academic-writing-storytelling` for writing advice).
- The user wants a slide deck (use `pv-forecast-pptx` or similar).
- The topic is outside the skill's evaluator assumptions (no measurable
  outcome, no possibility of running an experiment or simulator) — fall
  back to a plain prompt and warn that the watchdog has nothing to grade.
- The environment lacks `mavis team plan` or `mavis cron` — abort and tell
  the user.

## Trigger words

Chinese / English mix is fine; examples:

- "帮我把这个课题写成论文 / 写成 paper"
- "autoresearch / 跑一遍自动研究"
- "从课题到发表 / 端到端跑一个 paper pipeline"
- "/autoresearch-paper …"
- "UAV paper / drone paper / 路径规划 paper" (after the user has stated a topic)

When the user expresses any of the above AND the workspace shows they have
reference materials (PDFs, notes, datasets, GitHub repos), treat it as a
trigger.

## ❌ DON'T — anti-patterns to avoid

These are things this skill must **never** do. Violating any of them risks
destroying user state (Mavis agents, crons, hooks) without consent, or
producing output the user cannot trust.

| # | Anti-pattern | Why it's forbidden |
|---|---|---|
| ❌-1 | **Auto-spawn the agent team without user "go"** | A multi-day team run registers crons, hooks, and 4-5 agents. Wrong topic / wrong tier = hours of cleanup work. The two confirmations (tier + plan preview) are mandatory gates. |
| ❌-2 | **Auto-abort the plan when the watchdog flags an issue** | The watchdog is advisory. Only the human owner can decide to abort a running plan. The skill surfaces the recommendation; the user types `/autoresearch-paper abort` explicitly. |
| ❌-3 | **Silently overwrite an existing watchdog agent / cron / hook** | Re-running `bootstrap-watchdog.sh` may hit a name collision. Detect it, log "already exists — skipping", and never overwrite. If the user wants a fresh setup, they delete first. |
| ❌-4 | **Edit `last_seen.jsonl` or `out/*` from inside the watchdog** | The watchdog is a **read-only patrol agent**. It reads plan state and writes only `watchdog-log.md`. It must never touch research outputs or heartbeat files. |
| ❌-5 | **Invent a fourth tier** | Tier set is fixed: `arxiv` / `conference` / `journal-q1`. If none fits (e.g. workshop, demo track, public talk), downgrade to `arxiv` with a warning — never invent. |
| ❌-6 | **Skip the Channel B fallback when Channel A misses** | "I don't see a clear venue, let me just pick conference" — that's guessing. Always go to `ask_user` with 3 options + Others, never auto-pick. |
| ❌-7 | **Show raw `plan.yaml` to the user before they confirm the plan preview** | The user never edits the YAML, but they DO need to see the task graph + watchdog config and approve. Showing raw YAML without a human-readable summary = no confirmation possible. |
| ❌-8 | **Run `mavis team plan abort` from the skill body** | Abort is destructive. The skill surfaces the recommendation in chat; the user types the command. |
| ❌-9 | **Promise a "camera-ready PDF" or "submission to <venue>"** | The skill produces a structured draft + `next-steps.md`. It does not submit, does not produce camera-ready LaTeX, and does not replace human authorship of novel claims. Overpromising here is a recurring failure mode for autonomous paper pipelines. |
| ❌-10 | **Run the plan on a topic that has no measurable evaluator without warning the user** | Conference and journal tiers assume an experiment/simulator/benchmark. Pure theory papers must be downgraded to `arxiv` with a warning, or the watchdog has nothing to grade. |

## Default mode: confirm before spawning the team

The skill must never auto-spawn a multi-day agent team without confirmation.
Always do **two confirmations** in order:

1. 🔴 **STOP · TIER CONFIRMATION.** After parsing the brief, show the user the
   inferred tier (`arxiv` | `conference` | `journal-q1`), the plan task count,
   the estimated agent count, and the wall-clock estimate. **Do not proceed to
   plan generation until the user explicitly confirms** ("yes" / "confirm" /
   "go" / "change to <other-tier>"). User silence or ambiguity = treat as
   "not yet confirmed".
2. 🔴 **STOP · PLAN PREVIEW.** After generating `plan.yaml`, show the task
   graph (titles + one-line descriptions + dependencies) and the watchdog
   configuration. **Do not call `mavis team plan run` until the user
   explicitly says "go"**. The user can also reply "modify" — in that case
   revise plan.yaml and re-show the preview, never silently proceed.

Only on explicit "go" does the skill create the watchdog agent, schedule
the cron, register the hooks, and call `mavis team plan run`. Any other
user reply (including ambiguous / partial / question-only) → stay in
confirm-mode and ask again.

## The 7-step main flow

### Step 1 — Collect inputs

**INPUT:** free-form user message (1–3 paragraphs, or empty if invoked via slash command with no body).
**OUTPUT:** parsed brief `{topic, target_venue, materials}` in memory. Empty `materials` is allowed.

Ask for the three paragraphs in this order:

```
① 课题    "想研究什么?一两句话讲清楚问题与切口。"
② 目标    "发哪?arxiv / 顶会(IROS/ICRA/CVPR/NeurIPS...)/ SCI Q1?"
③ 素材    "手头有什么参考资料?贴文本 / 给路径 / 空也行。"
```

If the user provides everything in one paragraph, do not split — accept it
as a single free-form brief and parse internally.

### Step 2 — Tier detection (two-channel fallback)

**INPUT:** parsed `target_venue` string from Step 1.
**OUTPUT:** `tier ∈ {arxiv, conference, journal-q1}` + channel used (`A` or `B`).

**Channel A — keyword match.** Scan paragraph ② against `references/goal-keywords.md`.
On a hit, return the tier directly. On a miss, go to Channel B.

**Channel B — `ask_user` fallback.** Present exactly three options:

- `arxiv` — preprint, novelty check only, 2 agents, 1–2 days
- `conference` — IROS / ICRA / CVPR / NeurIPS / TRO-grade, 4–5 agents, 1–2 weeks
- `journal-q1` — SCI Q1 / Nature 子刊, 3–4 agents, 3–7 days

If the user picks one, persist it as `<tier>` and proceed. If the user
picks "Other", treat the brief as `conference` by default and ask one
follow-up: "哪本会/刊?我据此调子领域模板。"

### Step 3 — Generate `plan.yaml` (user never sees the file)

**INPUT:** `{topic, tier, materials}` from Steps 1–2.
**OUTPUT:** `<scratchpad>/autoresearch/<slug>/plan.yaml` (valid YAML, 4 / 8 / 8+ tasks depending on tier).

Read `references/plan-template-<tier>.md` and `references/task-prompt-snippets.md`,
then synthesize `plan.yaml` in `<scratchpad>/autoresearch/<slug>/plan.yaml`.
The plan must include:

- a literature-review task (always first, blocks everything)
- a gap-analysis task (always second)
- a method-design task (defines the experiment, simulator, or theory scaffold)
- an implementation task (depends on method)
- an experiment task (depends on implementation, with evaluator gate)
- a write-iter1 task (uses `paper-deconstruction` + `academic-writing-storytelling`)
- a write-iter2 task (incorporates ablation + reviewer-style self-critique)
- a package task (final paper.tex + figures + bibliography + reviewer-readiness.md)

Tier-specific adjustments:

- `arxiv`: skip write-iter2, merge package into write-iter1.
- `conference`: full 8-task graph, plus an optional rebuttal-preview task.
- `journal-q1`: full 8-task graph with deeper experiment task (more seeds,
  longer wall-clock, ablation as a separate task).

### Step 4 — Bootstrap the watchdog (fully scripted)

**INPUT:** `<topic-slug>`, `<tier>`, `<plan-dir>` (Step 3 output).
**OUTPUT:** registered `mavis` agent + cron + hook; written `<plan-dir>/WATCHDOG.md`. Idempotent (already-exists is OK).

🔴 **STOP — never reach Step 4 without the Step-3 "go" confirmation.** The
`bootstrap-watchdog.sh` script immediately registers a cron and a hook
that affect the user's Mavis namespace; running it without user consent
is irreversible cleanup work.

The skill runs `references/bootstrap-watchdog.sh` with three arguments:

```
references/bootstrap-watchdog.sh <topic-slug> <tier> <agent-prompt-file>
```

The script does, in order:

1. `mavis session new <agent-name> --title "<topic> paper watchdog"` to
   create the per-topic watchdog agent. The agent name follows
   `<topic-slug>-wd` (e.g. `uav-coverage-wd`). The `-wd` suffix (not
   `-paper-watchdog`) keeps the agent name within the daemon's 20-char
   limit while still being recognizable in `mavis agent list`.
2. `mavis cron create <agent-name> <agent-name>-liveness --schedule "0 * * * *"`
   to schedule hourly liveness checks.
3. `mavis hook create first-action-last-seen.json` to enforce per-task
   `last_seen` heartbeat on first action.
4. Writes a `WATCHDOG.md` into the plan directory describing what to do
   when liveness times out, when last_seen goes stale, and when the user
   pings the watchdog manually.

The watchdog agent's system prompt comes from
`references/watchdog-prompt-template.md` with placeholders for topic, tier,
expected wall-clock, and known evaluator signal.

### Step 4.5 — Engine ceiling reality check (long-running compute)

**INPUT:** `<plan-dir>` + list of tasks expected to exceed 30 min wall-clock
(installing heavy deps on aarch64, full-physics-simulator experiment sweeps,
multi-cell ablations, fault-ladder runs).
**OUTPUT:** explicit per-task daemon pattern instructions shipped in the
producer's task prompt; no plan.yaml `timeout_ms` change required.

The plan engine kills an individual worker session at **30 min wall-clock** —
**regardless of `plan.yaml timeout_ms`** (the field is decorative, not
honored). This is independent of the Rescue Layer, which only handles
plan-level pauses. Any task expected to exceed 30 min must use the daemon
pattern below; otherwise the producer is silently killed mid-output and the
data is lost.

**Pattern — platform-portable daemon launch + 4-file checkpoint + cron poll:**

🔴 **STOP — `setsid` is Linux-only.** macOS (darwin) does NOT ship `setsid`
(it's a util-linux package command). On darwin the daemon will fail to
launch with "command not found" and the engine cap will hit before any
work runs. Use the **macOS-compatible form** below. Auto-detect platform
at task-prompt generation time:

```bash
# Producer session (~5 min of wall-clock):
SSHPASS='...' sshpass -e ssh orin_agx@host 'bash -s' << 'EOF'
mkdir -p /home/orin_agx/<run> && cd /home/orin_agx/<run>
echo $$ > run.pid

# Detect platform (Linux has setsid; macOS doesn't):
if command -v setsid >/dev/null 2>&1; then
    # Linux / WSL: setsid creates a new session (detach from controlling TTY)
    nohup setsid bash -c "python cell_runner.py > run.log 2>&1; echo EXIT=\$? > exit.code; date +%s > checkpoint.json" \
        > /dev/null 2>&1 &
else
    # macOS (darwin): no setsid; nohup + disown is sufficient (detach from
    # controlling TTY + ignore SIGHUP). Verified on darwin: PID alive, cron
    # can monitor. Equivalent alt: `( cmd & )` subshell fork.
    nohup bash -c "python cell_runner.py > run.log 2>&1; echo EXIT=\$? > exit.code; date +%s > checkpoint.json" \
        > /dev/null 2>&1 &
    disown
fi

sleep 3
pgrep -f cell_runner.py | head -3
EOF
# Then immediately exit with deliverable.md (GATE: PARTIAL is fine):
# - daemon_pid, kicked_off_at, checkpoint_file paths
# - estimated_completion, daemon_log_tail
# - platform detected: linux / darwin
```

**Producer-side alternative when on macOS host (not Jetson):** Python's
`os.setsid()` works on darwin too — if the launcher script is Python
instead of bash, prefer `python3 -c "import os; os.setsid(); os.execvp(...)"`.
Don't reach for `setsid` from a `bash` shell on darwin.

The daemon writes `run.pid`, `run.log`, `exit.code`, `checkpoint.json` so a
subsequent producer session (or the next retry of the same task) can `pgrep`,
`tail run.log`, `cat checkpoint.json` to learn progress without owning the
work. The cron self-reminder (`mavis cron create` with `--every 5m`) catches
`exit.code` non-zero or `checkpoint.json` finalization and triggers the next
producer session.

🔴 **STOP — never put a >30 min command in a foreground SSH call.** A 90-min
`mavis team plan extend-timeout` extends only the producer session wall-clock
ceiling; it does NOT raise the 30-min cap. The daemon is the only way to do
work that exceeds the cap.

**Cleanup (CRITICAL — prevents Jetson resource leaks):**

- Producer must `rm run.pid` and `rm checkpoint.json` after `cat`-ing the
  final results. Leaving them confuses the next retry.
- Verify `pgrep -f cell_runner.py` returns empty before exit. If still
  alive, `kill -TERM <pid>` (single process, not process group — don't `pkill -KILL`).
- Add `<plan-dir>/cleanup.sh` to the deliverables so future retries can
  rerun cleanup idempotently.
- Stale crons set by the producer (`baseline-pyflyt-poll`,
  `t4-cell27-poll`) MUST be deleted via `mavis cron delete <agent> <cron>`
  before the producer exits; otherwise they keep firing and pollute logs.

🔴 **STOP — LOCKFILE discipline.** Before kicking off a daemon, write
`<run>/lock` (`echo $$ > lock`). The next producer session reads it; if
present, the daemon is already running — do NOT launch a duplicate. Remove
the lock only after `exit.code` is written.

**Pre-flight checklist before launching the full daemon (Producer exit ≤ 5 min):**

🔴 **STOP — do NOT over-test in the producer session.** The producer
session itself has a 30-min wall-clock cap, the same as any worker.
Tempting to "dry-run 3-5 times to validate the daemon" burns the entire
budget on validation — the cap hits before the real sweep launches.

**Rule of thumb:**

- **1 dry-run (≤ 8 cells) is enough** to validate daemon code + checkpoint
  files. After that, **immediately launch the full sweep + exit** the
  producer session in ≤ 5 min from session start.
- Do NOT run a 2nd dry-run "just to be safe".
- Do NOT pre-aggregate on partial dry-run data (the aggregator will wait
  for data that never comes if the launch never happens).
- Do NOT write the aggregator script before the daemon has launched — the
  aggregator slot is a separate cron-reminded session.

**Pre-flight checklist (all 5 must be true before launching the full daemon):**

1. ✅ Corruption module / cache built (`<run>/corruption_module.pyc` or
   equivalent warm-cache present on target machine).
2. ✅ Daemon launcher script tested **once** (≤ 8 cells ok).
3. ✅ Lockfile / progress.json / `exit.code` paths defined and reachable
   via `pgrep`, `cat`, `tail` from the producer session.
4. ✅ Aggregator slot ready: a separate cron-registered session
   (e.g. `<slug>-aggregator`) can be invoked later without producer
   involvement.
5. ✅ `mavis cron self <name> --every 5m --prompt "..."` registered to
   catch `exit.code` non-zero / `checkpoint.json` finalization.

→ Once all 5 are checked, launch the full daemon and **exit the producer
session within 5 min**. Let the cron poll the daemon.

**Anti-pattern (what burned the V2M-Harness T6.5 first attempt):**

```python
# WRONG: producer spent 30 min cap on dry-runs, never launched real sweep
for size in [8, 50, 600]:
    run_dry_sweep(size)        # each "for safety" burns ~5-10 min
launch_full_sweep()            # never reached — cap hit first
```

```python
# CORRECT: 1 dry-run, then launch + exit
run_dry_sweep(8)               # ≤ 5 min, validates infra only
launch_full_sweep_in_background()
write_deliverable_partial(daemon_pid, checkpoint_paths)
exit_producer_session()        # total ≤ 5 min from session start
# Cron polls daemon; next producer session reads exit.code when ready
```

See **FM-16** for the failure-mode encoding.

**Model-based pipelines: pre-load the model once (4× speedup vs per-cell reload):**

For model-based cell pipelines (VGGT-Ω / DUSt3R / SAM / DINO / NeRF /
Gaussian Splatting / any NN inference), do **NOT** reload the model
inside the per-cell loop. The standard anti-pattern:

```python
# WRONG: model reload every cell (~5s × N cells = N× reload cost)
for cell in cells:
    model = load_model()       # 5s reload every cell
    result = model.infer(cell)
```

Correct pattern:

```python
# CORRECT: load once at daemon startup, pass to every cell
model = load_model()           # ONCE, pre-load (5s)
device = get_device()
for cell in cells:
    result = model.infer(cell, model=model, device=device)
    save_result(cell, result)
```

**Impact:** ~43 cells/min in-process vs ~10 cells/min per-cell reload
(4× speedup). Bonus: keeps memory stable (no model churn — important on
MPS / shared GPUs). Implementation: patch `l2_execute()` to accept
`preloaded_model` and `preloaded_device` kwargs; the daemon loads once
at startup and passes them to every cell.

The skip-if-exists check on `<cell>.jsonl` is also a hidden trap: see
**FM-17** for the pretty-printed JSON `splitlines()[0]` bug that breaks
auto-resume. Apply both fixes (preload + correct skip-check) **before**
launching the full sweep, not after.

### Step 5 — Run the team

**INPUT:** validated `<plan-dir>/plan.yaml` (Step 3) + Step-4 watchdog resources + user "go".
**OUTPUT:** `<plan-id>` (printed to user), dashboard URL. Skill enters observe mode.

Call `mavis team plan run --plan <scratchpad>/autoresearch/<slug>/plan.yaml`
and capture the plan id. Print the plan id and the dashboard URL back to
the user. The skill is now in **observe mode**.

### Step 5.5 — Verifier spot-check recipe

**INPUT:** verifier session inspecting a producer's `<plan-dir>/out/*` artifacts.
**OUTPUT:** explicit PASS/FAIL verdict grounded in numerical evidence, not
producer self-claims.

The producer's self-reported GATE: PASS is not sufficient. The verifier
**must independently re-measure** three categories of artifacts. Apply all
three — skipping any one invites the regressions that bit V6 plan_e7ae7abe:

**Category A — JSONL / result files (do NOT spot-check 1 cell):**

```bash
# 1. Schema validation across ALL files, not just one cell
for f in out/results-raw-*/cell_*.jsonl; do
    head -1 "$f" | python3 -c "import json,sys; json.loads(sys.stdin.read())" || echo "BAD_JSON: $f"
done

# 2. Record count vs expected
expected=$(grep "expected_records\|n_per_cell" plan.yaml | head -1)
wc -l out/results-raw-*/*.jsonl  # sum should match

# 3. Error rate — any record containing ERROR or TypeError FAILS
grep -c '"ERROR"\|"TypeError"' out/results-raw-*/*.jsonl  # must be 0

# 4. Field completeness — verify ALL required fields present in ALL rows
python3 -c "
import json, glob, sys
required = ['scenario_id','fault_step','recovery_status','seed','success','completion_time']
for f in glob.glob('out/results-raw-*/*.jsonl'):
    for i, line in enumerate(open(f)):
        rec = json.loads(line)
        missing = [k for k in required if k not in rec]
        if missing: print(f'{f}:{i} MISSING {missing}')
"
```

A single ERROR record or missing field across the whole run = FAIL, unless
explicitly classified as "out-of-scope" with reason in the verifier report.

**Category B — LaTeX (4-pass compile + pdftotext grep, NOT binary PDF grep):**

```bash
# 1. 4-pass compile (NOT 3-pass — bibtex needs its own pass)
cd out/package && pdflatex -interaction=nonstopmode paper.tex && \
    bibtex paper && \
    pdflatex -interaction=nonstopmode paper.tex && \
    pdflatex -interaction=nonstopmode paper.tex

# 2. Visible [?] markers in RENDERED TEXT (compressed PDFs fool raw grep)
pdftotext paper.pdf - | grep -cF '[?]'   # must be 0

# 3. BibTeX warnings (catches missing entries before they become visible [?])
grep -E "Warning--I didn't find a database entry" paper.blg
# 0 hits = PASS

# 4. Cross-reference resolution (no ?? in any rendered page)
pdftotext paper.pdf - | grep -cF '??'   # must be 0
```

A verifier that only checks "pdflatex exit 0" misses bib-regression. Always
run all 4 checks.

**Category C — Verifier independence:**

The verifier MUST NOT run in the same worker session as the producer it is
verifying. If Mavis agent routing forces same-context reuse, the verifier
**must still use a fresh context** — artifact-only inputs (read the files)
plus a command transcript, never live agent continuation of the producer's
session. This avoids the "I just wrote this, it must be good" optimism
bias that empirical SkillLens LLM-as-judge studies measure at ~46.4%
accuracy.

🔴 **STOP — never reuse the producer's session for verification.** If the
runtime doesn't offer a fresh session, fall back to `codex exec -m gpt-5.5`
with `--skip-git-repo-check` and feed it the producer's `deliverable.md`
plus the artifact paths; never `mavis communication send` a "verify this"
prompt back into the producer's own session.

### Step 6 — Observe and patrol

**INPUT:** `<plan-id>` from Step 5; user turns while plan runs.
**OUTPUT:** status snapshots + relayed watchdog findings; user commands `/autoresearch-paper {status|pause|resume}` honored.

The skill stays open during the run. Every user turn, check:

- `mavis team plan status <plan-id>` for overall progress.
- `<scratchpad>/autoresearch/<slug>/last_seen.jsonl` for per-task heartbeat.
- The watchdog's hourly cron — if it fires while the skill is active,
  relay the watchdog's recommendation to the user.

The skill exposes three user-facing commands:

- `/autoresearch-paper status` — show plan progress + last_seen.
- `/autoresearch-paper pause` — call `mavis team plan pause <plan-id>`.
- `/autoresearch-paper resume` — call `mavis team plan resume <plan-id>`.

If the watchdog reports an abort-worthy condition, surface it to the user
and ask before taking destructive action. 🛑 **STOP — never auto-abort.**
The user owns the abort decision; the skill only surfaces recommendations.

🔴 **STOP · ABORT GATE.** Before calling `mavis team plan abort`, the
skill **must** show the user: (a) the abort-worthy finding verbatim,
(b) the proposed alternative actions (`steer` / `manual_retry` /
`override_accept` / `nudge`), and (c) the expected wall-clock to recover
vs. abort+restart. Only proceed with abort after explicit user
confirmation. The watchdog's recommendation is advisory; the human
owner is the only entity with destructive-action authority.

🔴 **STOP · WORKSPACE ISOLATION.** Before Step 5 (`mavis team plan run`),
verify `<scratchpad>/autoresearch/<slug>/` exists and is writable. If the
scratchpad path is on a read-only mount or its parent directory was
created by a different user, surface the error and **do not** call
`mavis team plan run` — the plan engine will fail mid-task with cryptic
permission errors that are hard to recover from.

### Step 7 — Deliver

**INPUT:** finished plan (or user manual end); `<plan-dir>/out/*` from worker agents.
**OUTPUT:** chat summary (tier, wall-clock vs estimate, watchdog steer/abort counts, top-3 next-steps) + paths to `paper.tex` and `reviewer-readiness.md`.

When the plan finishes (or the user manually ends it), the skill produces:

```
<scratchpad>/autoresearch/<slug>/out/
├── paper.tex                # main LaTeX source
├── figures/                 # all figures as standalone PDFs
├── bibliography.bib         # BibTeX
├── reviewer-readiness.md    # self-check: novelty, evidence, ablations, writing
├── change-log.md            # what each iter of writing changed
└── next-steps.md            # what a human should still do (camera-ready, R1)
```

The skill then summarizes:

- which tier was used and why
- total wall-clock vs estimate
- which tasks were auto-steered by the watchdog, and why
- the top three items in `next-steps.md`

The user reviews `paper.tex` and `reviewer-readiness.md` and decides whether
to invoke another iteration.

#### Step 7.5 — Page-budget fold regression guard (camera-ready)

**INPUT:** finished paper at 7-9 pages, ICRA / conference camera-ready
submission deadline pressing, proposal to trim prose or fold a dedicated
section.
**OUTPUT:** explicit dimension-regression calculation before any deletion;
waiver request fallback if the fold would push a reviewer-readiness
dimension below threshold.

🔴 **STOP — before deleting any dedicated section (§6 Limitations/Ethics,
§3 Method sub-section, etc.) to fit camera-ready page budget, run this
regression check.** V6 plan_e7ae7abe T10 retry-2 folded §6 into §5+§7
unthinkingly, regressing the Ethics dimension 6 → 4 — the verifier caught
it only on the second pass. Don't repeat.

##### Step 7.5.a — Wide-table 2-column span recipe (camera-ready)

Before folding any dedicated section, check whether a **wide LaTeX table**
is the actual culprit. A table with 8+ columns or packed numeric content
overruns the single-column width and visually crowds the surrounding body
text. The fix is **two-character** but easy to miss:

```latex
% Before (single column, may overflow):
\begin{table}[t]
  ... 8-column tabular ...
\end{table}

% After (spans both columns of IEEE 2-col layout):
\begin{table*}[t]
  ... 8-column tabular ...
\end{table*}
```

The `table*` (with asterisk) floats to the top of the next page (or
wherever `[t]` allows); the surrounding body text gets ~0.5 page of
breathing room. This is NOT a fold — the table keeps full content; only
the layout changes. Apply this **before** any fold-to-fit reflex.

**Trigger conditions** (any one → apply 2-column span):

- Table has ≥ 7 columns
- Table contains `\small` or `\footnotesize` (forced by overflow)
- pdflatex log shows `Overfull \hbox` warnings near a `\begin{table}`
- Body text around the table has visible justification stretch / hbox
  warnings cascading from the table

V6 plan_e7ae7abe Table IV (8-column ablation results) was converted
this way and gained ~0.5 page of body room without changing the
table content. See FM-15 for the failure-mode encoding.

```bash
# 1. Read the current 6-dim scores from reviewer-readiness.md
grep -A 1 "Ethics\|Limitations\|Reproducibility\|Clarity" reviewer-readiness.md | head -20

# 2. For each section you propose to fold, ask:
#    Which reviewer-readiness dimension depends on this section being dedicated?
#    - §6 Limitations/Broader Impact/Ethics → Dim 6 Ethics
#    - §3 Method sub-section → Dim 2 Evidence / Dim 1 Novelty
#    - §5 Discussion multi-voice → Dim 4 Clarity

# 3. If any dimension is at threshold (e.g., Ethics = 6) and the fold
#    would push it below, do NOT fold. Instead:
#    (a) Request waiver from venue program chairs (ICRA accepts 1-page
#        waivers for camera-ready, esp. for honest-disclosure sections)
#    (b) Restructure as short-paper / workshop track (4-page version)
#    (c) Move ethics discussion to supplementary material — but be aware
#        that supplementary does NOT count toward reviewer-readiness rubric
#    (d) Compress §5 multi-voice from 4 paragraphs to 2 (cut 200 words
#        without losing dimensions), THEN check if fold is still needed
```

The fold-to-fit reflex is dangerous because it's invisible until the
verifier scores. A 30-second pre-flight check saves a full retry cycle.

## Tier reference

| Tier | Trigger keywords (channel A) | Tasks | Agents | Wall-clock |
|---|---|---|---|---|
| `arxiv` | arxiv / 预印本 / preprint / working paper | 4 | 2 | 1–2 days |
| `conference` | IROS / ICRA / CVPR / NeurIPS / ICCV / ECCV / AAAI / KDD / ACL / EMNLP / TRO | 8 (+ optional rebuttal) | 4–5 | 1–2 weeks |
| `journal-q1` | SCI Q1 / Nature 子刊 / T-PAMI / IJRR / T-RO / JFR | 8 (deeper experiments) | 3–4 | 3–7 days |

The full keyword list lives in `references/goal-keywords.md` and is the
single source of truth. Update there, not here.

## Watchdog architecture

```
L0 (process substrate)   Mavis GUI / MiniMax Code.app (already running)
                          ↓
L1 (periodic patrol)     per-topic agent + cron
                          e.g. uav-coverage-wd
                             └─ cron: liveness (hourly)
                          Mavis GUI groups cron by agent → natural dashboard
                          ↓
L2 (business heartbeat)  per-task last_seen (hooks enforce first-action stamp)
                          ↓
mutual check             L1 sees last_seen stale → steer / abort / reopen
```

Zero new mechanisms. GUI + agent namespace + cron + hooks + steer/abort
all already exist; this skill only combines them. The user does not need
to know `mavis cron` syntax.

## Rescue Layer (v0.3.0+) — Local-LLM auto-judge + Pause/Stop

The default watchdog (L1 cron + L2 hook) is **read-only**: it can detect
stalls and emit findings, but cannot decide *what to do next*. When the
plan engine pauses awaiting an owner decision, the human is the only
entity that can unblock it. This is a single point of failure for
multi-day plans where the human sleeps, travels, or simply stops paying
attention.

v0.3.0 adds a **Rescue Layer** on top of the watchdog:

```
                    ┌──────────────────────────┐
                    │   plan engine (mavis)    │
                    └────────────┬─────────────┘
                                 │ paused > 10 min?
                                 ▼
   launchd (every 60s) ──► plan-rescue-daemon.py
                                 │
                                 │ call local_llm_judge.py (codex exec -m gpt-5.5)
                                 ▼
                     gpt-5.5 + xhigh reasoning
                                 │
                                 ▼
                     strict-JSON verdict
                  { accept | override_accept | manual_retry | cancel | nudge }
                                 │
                                 ▼
              mavis team plan decision / resume / cancel
```

The Rescue Layer auto-applies one of five verdicts:

| Verdict | Action |
|---|---|
| `accept` | mark latest producer attempt done; resume plan |
| `override_accept` | verifier complaint is format-only (e.g., "missing VERDICT: PASS line"); mark done; resume |
| `manual_retry` | small fixable issue; producer retries with the judge's hint |
| `cancel` | plan unrecoverable; abort cleanly, preserve all files |
| `nudge` | wait `wait_minutes` and re-check (no action) |

Honors user signals: `pause_requested.json` → skip auto-judge;
`stop_requested.json` → cancel immediately; `local_llm_disabled` →
fall back to nudge-only (no LLM calls).

### Components

The Rescue Layer ships as **skill-bundled scripts** in
`references/scripts/` of this skill (also mirrored at
`~/.mavis/agents/mavis/scripts/` for the running daemon to find them):

- `local_llm_judge.py` — wraps `codex exec -m gpt-5.5 -c model_reasoning_effort=xhigh`
  with retry, JSON-mode parsing, and graceful fallback when ChatGPT account
  rejects a model. ~250 lines.
- `plan-rescue-daemon.py` — patrols `~/.mavis/plans/*/state.json` every 60 s,
  calls `local_llm_judge.py` for paused plans older than 10 min, applies the
  verdict via `mavis team plan decision` + `resume`/`cancel`. ~400 lines.
- `pause-plan.sh` / `resume-plan.sh` / `stop-plan.sh` — write/delete signal
  files in the plan directory; the daemon reads them on its next patrol.

When this skill is installed on a fresh machine, `bootstrap-watchdog.sh`
copies the bundled scripts to `~/.mavis/agents/mavis/scripts/` (the
daemon's runtime path) so the user doesn't have to do it manually. The
skill itself stays self-contained — no external dependencies beyond the
local Codex CLI.

The daemon is **launchd-managed** (not mavis cron) to avoid spawning an LLM
session every 60 s — it runs as a pure Python process. The launchd plist
ships at `references/launchd/com.mavis.plan-rescue-daemon.plist`; the
bootstrap script copies + loads it on opt-in:

```xml
~/Library/LaunchAgents/com.mavis.plan-rescue-daemon.plist
  ProgramArguments: python3 ...plan-rescue-daemon.py --once
  StartInterval: 60
  RunAtLoad: true
```

### Pause / Stop mechanism

Single source of truth is the plan directory itself:

| Signal file | Written by | Effect |
|---|---|---|
| `pause_requested.json` | `pause-plan.sh <plan_id>` | Daemon skips auto-judge on next patrol |
| `resume_signal.json` | `resume-plan.sh <plan_id>` | Daemon calls `mavis team plan resume` |
| `stop_requested.json` | `stop-plan.sh <plan_id> [--reason <text>]` | Daemon cancels + status = `stopped_by_user` |
| `local_llm_disabled` | user (touch file) | Daemon falls back to nudge-only, no LLM calls |

The plan engine's internal workers are not directly controllable (they're
daemon-owned), so "pause" is a **soft pause**: active workers finish their
current cycle, the engine idles, and no new tasks are spawned until
`resume_signal.json` is observed.

### When to use the Rescue Layer

- Multi-day conference / journal-tier plans where the human owner sleeps
- Long experiment tasks (T6-style) where engine can pause on minor verifier
  hiccups that don't actually need human review
- Plans where a cheap model (gpt-5.5 + xhigh) can substitute for the owner
  on trivial decisions (e.g., "verifier says no VERDICT line — content is
  clearly correct, override_accept")

### When NOT to use the Rescue Layer

- arxiv-tier plans (cheap enough for human to babysit)
- Plans requiring novel scientific judgment (judge should defer to human)
- Plans where auto-cancel would be catastrophic (opt in `local_llm_disabled`)

### Failure modes for the Rescue Layer

| # | Trigger | First-line fix | Fallback |
|---|---|---|---|
| FM-7 | `local_llm_judge.py` exits non-zero (codex unavailable / model rejected) | Daemon emits `judge_failed` finding, falls back to `nudge` verdict, retries next cycle | If 5 cycles in a row fail, daemon writes `local_llm_disabled` automatically and escalates to user |
| FM-8 | `pause_requested.json` written but daemon never resumes | User runs `resume-plan.sh <plan_id>` manually; daemon observes `resume_signal.json` | Surface in `next-steps.md`: "paused at cycle N — run `resume-plan.sh` to continue" |
| FM-9 | `stop_requested.json` triggers cancel but plan engine has producer still running | Daemon kills the plan engine; in-flight producers exit on their own (no SIGKILL needed) | Verify `state.json` status = `"cancelled"` within 60 s; if not, `mavis team plan cancel <plan_id>` manually |
| FM-10 | Producer puts a >30 min command in a foreground SSH call (engine kills the session mid-output, data lost) | Refollow Step 4.5: `nohup + setsid + disown` daemon + 4-file checkpoint (`run.pid`/`run.log`/`exit.code`/`checkpoint.json`); write `cleanup.sh` for next retry. **macOS:** `setsid` is unavailable — use `nohup + disown` only, or Python `os.setsid()`; auto-detect platform. | If the producer's session is already dead, the next retry must read whatever files exist on the target machine (Jetson) — partial run logs are usually salvageable |
| FM-11 | LaTeX `[?]` markers visible in rendered PDF (cite in body but missing from `.bib`) | Run 4-pass pdflatex + bibtex; `pdftotext paper.pdf - \| grep -cF '[?]'` must return 0; check `paper.blg` for "Warning--I didn't find a database entry" | Manually grep paper.tex for `\cite{...}` keys, cross-reference against `bibliography.bib`; add missing entries by `\input` or copy from sibling skill's bib |
| FM-12 | Page-budget fold regresses a reviewer-readiness dimension below threshold (e.g., fold §6 Ethics → Dim 6 = 4) | Run Step 7.5 pre-flight check BEFORE deleting any dedicated section; compute dimension regression from the fold | Request venue waiver for 1-2 extra pages; restructure as short-paper track (4 pages); move content to supplementary (note: supplementary does NOT count toward reviewer-readiness rubric scoring) |
| FM-13 | Producer self-reports "all cells done" but JSONL contains ERROR / TypeError records hidden in raw counts | Run Category A verifier recipe: `head -1 schema` + `wc -l` + `grep -c '"ERROR"\|"TypeError"'` + field completeness check | If only a few cells errored, retry with cell-targeted fix (don't re-run the full sweep); if systematic, pause and ask user whether to patch the helper function |
| FM-14 | Verifier runs in same session context as producer (loses independence, ~46.4% accuracy per SkillLens) | Spawn fresh producer session via `mavis session new`; verifier reads only artifact files (no shared scratchpad memory) | Fallback: use `codex exec -m gpt-5.5 -c model_reasoning_effort=xhigh --skip-git-repo-check` with artifact paths as input |
| FM-15 | Wide LaTeX table overflows single column (8+ columns, packed content) and crowds body text | Convert `\begin{table}[t]` → `\begin{table*}[t]` to span both columns of the IEEE 2-column layout; `\end{table}` → `\end{table*}`; figure stays at `[t]` placement. The `table*` floats to top of next page (or wherever `[t]` allows) — usually buys ~0.5 page of breathing room in the body | If the wide table still doesn't fit (rare for IEEE 2-col), split it into two stacked narrow tables or move sub-tables to supplementary |
| FM-16 | Producer over-tests in the session (3+ dry-runs of 8/50/600 cells) — 30-min cap hits before the real full sweep launches; daemon infra is perfect but real work never runs | Follow Step 4.5 Pre-flight checklist: 1 dry-run (≤ 8 cells) validates infra, then **immediately launch the full sweep + exit the producer session in ≤ 5 min**. All 5 pre-flight items (corruption module / daemon tested / lockfile paths / aggregator slot / cron registered) must be true before launch — not "iteratively discovered during dry-runs" | If cap already hit, next producer session reads `<run>/checkpoint.json` and `<run>/exit.code` from the previous attempt (often partial work is salvageable); do NOT re-dry-run |
| FM-17 | Model-based cell pipeline reloads model per cell (~10 cells/min) instead of pre-loading once (~43 cells/min, 4× speedup) — caused by copy-pasted single-cell inference loop | Patch `l2_execute()` to accept `preloaded_model` and `preloaded_device` kwargs; daemon loads model **once** at startup and passes to every cell. Memory stays stable on MPS / shared GPU | If model is too large to keep resident (OOM at startup), fall back to per-N-cell reload (e.g. reload every 50 cells) instead of every cell; document the trade-off in `cleanup.sh` |
| FM-18 | Skip-if-exists check on `<cell>.jsonl` uses `path.read_text().splitlines()[0]` which fails on pretty-printed JSON (multi-line) — daemon re-runs every existing cell, ~5–10× slower than expected and lockup risk on long runs | Use `json.loads(path.read_text())` (full file) or `with open(path) as f: json.load(f)`. Pretty-printed JSON has `{\n  "cell_id": ...` so `splitlines()[0]` returns just `{` and json.loads chokes | Diagnostic when daemon is suspiciously slow despite skip-if-exists: `cat progress.json \| head -1` — if it's just `{` and not a JSON object, the producer is using `splitlines()[0]`; expected pace vs actual pace: 5× slower = red flag for broken skip-check |
| FM-19 | Harness / wrapper / agent-loop paper claims "B5 (full system) beats B0 (SOTA-tuned backbone)" when in fact B5 == B0 on SOTA path — the headline is the **preventive gain on stress baselines** (B5 vs B4), not "beats SOTA". Burying the null regresses Dim 4 Clarity and Dim 6 Ethics (overclaim). | See `reviewer-readiness-rubric.md` § "Honest framing for harness / wrapper papers": surface B5 == B0 honestly as "preserves SOTA performance" while surfacing the real win (B5 vs B4 stress baseline). Separate "no regression on SOTA path" from "preventive gain on stress path" as distinct §4.x subsections. | If the paper has already been written with the wrong framing, do NOT silently rewrite — add a §6.1 "Honest scope clarification" paragraph that re-frames the result with both null and positive findings. Update `reviewer-readiness.md` evidence quotes accordingly. |

## Environment constraints

- **Mac sleep = watchdog blind.** If the Mac sleeps, the hourly cron does
  not fire. The skill documents this trade-off in `WATCHDOG.md` and the
  user accepts it by default. If the user later wants hardened liveness,
  they can re-bootstrap with `--mode=hardened`, which adds a launchd
  `KeepAlive` plist — but this is an explicit opt-in.
- **Rescue Layer is launchd-managed, not cron-managed.** The
  `plan-rescue-daemon.py` is registered via `~/Library/LaunchAgents/` and
  fires every 60 s. Mac sleep does NOT prevent it (launchd resumes on
  wake), so the Rescue Layer is more reliable than the L1 hourly cron.
- **No cross-machine continuity.** Watchdog state lives on the user's Mac.
  Switching machines = resuming the run by hand on the new machine.
- **Evaluator dependency.** Conference and journal tiers assume the topic
  has either a real experiment, a simulator, or a public benchmark. For
  pure theory papers, fall back to `arxiv` tier with a warning.
- **Rescue Layer requires local Codex CLI.** The auto-judge uses
  `codex exec -m gpt-5.5 -c model_reasoning_effort=xhigh`. If Codex is not
  installed or the ChatGPT account does not have access to gpt-5.5, the
  Rescue Layer silently falls back to `nudge` and waits for the human.

## Deliverables the skill ships with

```
skills/autoresearch-paper/
├── SKILL.md                          # this file
├── README.md                         # human-facing usage
├── references/
│   ├── goal-keywords.md              # channel A keyword table
│   ├── tier-decision-tree.md         # channel A/B fallback logic
│   ├── plan-template-arxiv.md        # 4-task plan template
│   ├── plan-template-conference.md   # 8-task plan template
│   ├── plan-template-journal-q1.md   # 8-task deep-experiment template
│   ├── task-prompt-snippets.md       # per-task prompt fragments
│   ├── watchdog-prompt-template.md   # per-topic watchdog system prompt
│   ├── bootstrap-watchdog.sh         # one-shot agent + cron + hook setup
│   ├── first-action-last-seen.json   # hook config
│   ├── reviewer-readiness-rubric.md  # 6-dimension self-check
│   ├── scripts/                      # Rescue Layer scripts (skill-bundled)
│   │   ├── local_llm_judge.py        # gpt-5.5 + xhigh wrapper
│   │   ├── plan-rescue-daemon.py     # 60s patrol + 5 verdicts
│   │   ├── pause-plan.sh
│   │   ├── resume-plan.sh
│   │   └── stop-plan.sh
│   └── launchd/
│       └── com.mavis.plan-rescue-daemon.plist  # opt-in launchd installer
└── tests/
    └── e2e-uav-coverage.md           # end-to-end test scenario
```

References are read on demand. The skill must not load all of them
upfront — it pulls the ones it needs based on the tier.

## Failure modes the skill must handle

Every failure mode is encoded as a 3-part row — **trigger condition** (when
the failure happens) → **first-line fix** (what to try first) → **still
failing → fallback** (what to do when first-line also fails). The fallback
column is mandatory; never leave a row without an escalation path.

| # | Trigger condition | First-line fix | Still failing → fallback |
|---|---|---|---|
| FM-1 | `command -v mavis` returns non-zero at Step 4 (no `mavis` CLI on PATH) | Show install hint: "This skill needs the Mavis / MiniMax Code runtime. Install or activate it first." | 🛑 Abort entirely. Do not run Step 5. Surface the install URL and stop. |
| FM-2 | User picks "Other" in Channel B tier picker **3 times in a row** | Show examples of well-formed venues (`CVPR 2027`, `NeurIPS`, `T-RO`, etc.) | 🛑 Stop and ask the user to state the target venue in one sentence. Do not guess. |
| FM-3a | `plan.yaml` LLM output is malformed YAML (parse error, wrong indentation, fence residue) | Retry up to **3 attempts** total, each with stricter instruction: (1) "pure YAML only, no fences"; (2) "use 2-space indent, no tabs, no comments"; (3) "match the task-shape in `references/plan-template-<tier>.md` exactly". | 🛑 After 3 failed parses, do **not** ask the user to fix YAML by hand. Read `references/plan-template-<tier>.md`, **mechanically fill `{topic}` / `{slug}` / `{wall-clock}` placeholders**, and write a structurally valid `plan.yaml`. Surface the auto-generated plan with a "I generated this from the template — please edit" banner. |
| FM-3b | LLM **refused** to produce `plan.yaml` (policy / safety / scope rejection — not parse failure) | Do **not** retry with "try again". Read the refusal, classify it: scope mismatch, policy violation, or insufficient context. | **Skip the LLM entirely.** Read `references/plan-template-<tier>.md` directly, fill placeholders with the user's parsed brief (`{topic}`, `{target_venue}`, `{wall-clock_estimate}`), and write a complete `plan.yaml`. Tell the user: "I bypassed the LLM and used the template — your `target_venue` or topic may have triggered a refusal; review and edit." |
| FM-4 | `bootstrap-watchdog.sh` fails because agent/cron/hook already exists | Detect the conflict; the script already logs "already exists — skipping" | Suggest `<topic-slug>-<suffix>` (e.g. `-v2`) and re-run bootstrap. **Never silently overwrite** an existing agent/cron/hook. |
| FM-5 | Plan runtime exceeds estimated wall-clock (deadlock) | Show `mavis team plan status <plan-id>` output to the user | 🛑 Surface to user and recommend `/autoresearch-paper abort`. Do not auto-abort. |
| FM-6 | Hook `first-action-last-seen` never fires (no `last_seen.jsonl` written within 1 hour of plan start) | Verify the hook was registered: `mavis hook list \| grep first-action-last-seen-<slug>` | Manually create `<plan-dir>/last_seen.jsonl` with a placeholder line and warn the user the per-task staleness detection is degraded for this run. |

## Versioning

- 0.1.0 — initial draft; covers the 7-step flow, three tiers, watchdog
  bootstrap, and one e2e test scenario.
- 0.1.1 — naming and CLI surface alignment patch.
  - Agent suffix renamed from `-paper-watchdog` to `-wd` so the full
    agent name stays within the Mavis daemon's 20-char hard limit
    (validation error 40002). All references in SKILL.md,
    `references/watchdog-prompt-template.md`, and
    `tests/e2e-uav-coverage.md` updated accordingly.
  - `mavis cron trigger` and `mavis cron delete` documented and tested
    with the correct two-argument form `<agent-name> <cron-name>`
    (single-argument form was a v0.1.0 doc bug; never matched the CLI).
  - `bootstrap-watchdog.sh` already produces the correct names; this
    patch is doc/test-only.
- 0.2.0 — darwin-skill structural hardening (4 rounds, +7.0 net).
  - **R1 dim4** (+2.4): added 4 explicit 🔴/🛑 STOP markers at the
    implicit checkpoints (tier-confirm, plan-preview-go, Step-4 entry,
    never-auto-abort). Visual markers > prose for LLM scanning.
  - **R2 dim3** (+2.4): rewrote "Failure modes" from 5 bullet points
    to a 6-row if-then table (Trigger / First-line fix / Fallback).
    Added FM-6 (hook never fires). FM numbers cross-referenceable.
  - **R3 dim9** (+1.2): added independent `❌ DON'T — anti-patterns`
    section with 10 numbered anti-patterns + "Why forbidden" column.
    Placed before Default mode so LLM learns taboos before flow.
  - **R4 dim2** (+1.0): added **INPUT:** / **OUTPUT:** lines under
    each of the 7 Steps. No body changes, structural scaffolding only.
  - All rounds kept via `git commit`; no reverts needed. HL-4 triggered
    after R4 (R3+R4 连续 2 轮 Δ<2.0) → break.
- 0.2.1 — single-issue patch: FM-3 split.
  - **Why.** Track 1 independent-agent review (v0.2.0 release) flagged
    FM-3 as the **only actionable weakness** at 8.5/10. The single row
    conflated two failure shapes (malformed YAML parse error vs. policy
    refusal) which need different fix paths.
  - **FM-3a — malformed YAML.** Retry up to 3 attempts with progressively
    stricter instructions (fences → indent → template-shape match).
    Fallback is no longer "ask the user to fix YAML by hand"; instead,
    the skill **mechanically fills `references/plan-template-<tier>.md`**
    with `{topic}` / `{slug}` / `{wall-clock}` and writes a valid
    `plan.yaml`. User edits a working YAML, not garbage.
  - **FM-3b — policy refusal.** Do **not** retry. Skip the LLM entirely;
    the template-fill fallback is identical to FM-3a but the banner tells
    the user their topic/venue may have triggered the refusal so they
    can rephrase. This converts a hard stop into a recoverable step.
  - FM-4..FM-6 unchanged — keeping their numbers so any test/cross-ref
    to `FM-4` etc. does not need to be touched.
  - No structural changes to Steps 1-7, no DON'T-list change, no
    STOP-marker change. Dim-by-dim estimate: Δ +0.5 (FM table clarity).
    Below the HL threshold; no need for another darwin pass.
- 0.3.0 — Rescue Layer (Local-LLM auto-judge + Pause/Stop).
  - **Why.** Real plan (`uav-swarm-icra2027-v4` plan_cdefc387) hit
    `Engine auto-paused: max cycles reached` with **single L1 hourly cron
    + 1 hook** unable to rescue. Owner had to manually cancel + hand-write
    T7-T8. Multi-day plans need a decision proxy that doesn't sleep.
  - **New chapter: Rescue Layer.** `local_llm_judge.py` +
    `plan-rescue-daemon.py` + `pause/resume/stop-plan.sh` + launchd plist
    auto-judge paused plans via gpt-5.5 + xhigh reasoning and apply
    accept / override_accept / manual_retry / cancel / nudge verdicts.
    Honors user signal files (`pause_requested.json`,
    `resume_signal.json`, `stop_requested.json`, `local_llm_disabled`)
    so the human stays in control.
  - **3 new failure modes (FM-7, FM-8, FM-9)** covering judge failure,
    stale pause request, and stop-request mid-flight. Each has a clear
    fallback path so a stuck Rescue Layer doesn't compound the original
    problem.
  - **Environment constraint added:** "Rescue Layer requires local
    Codex CLI" — explicit dependency so users know the auto-judge silently
    degrades to nudge when gpt-5.5 is unavailable.
  - **Cross-cutting change:** "Mac sleep" constraint now distinguishes
    hourly cron (sleep-blind) from launchd (sleep-resilient). The
    Rescue Layer's launchd-managed daemon is the only reliable liveness
    mechanism under macOS sleep.
  - Backwards compatibility: v0.2.x plans without the Rescue Layer
    continue to work — the layer is opt-in via the launchd plist load.
    No changes to `bootstrap-watchdog.sh` (single-L1-cron path remains
    the default for non-rescue use cases).
- 0.3.1 — V6 evidence-driven: engine ceiling + verifier spot-check + 0% framing.
  - **Why.** plan_e7ae7abe (12-task UAV-Swarm real-PyFlyt ICRA 2027 plan,
    Jun 24-25 2026) ran end-to-end but exposed 3 specific skill weaknesses
    the Rescue Layer didn't address: (a) T2/T4/T9 each killed 3-6 times by
    the 30-min engine ceiling because plan.yaml `timeout_ms` is decorative;
    (b) T8 verifier approved GATE: PASS with `[?]` markers in rendered PDF
    (airsim/flightmare citations missing from `.bib`) and T4 retry-4 reported
    "27/27 cells" while 3 B3 PPO cells contained ERROR records; (c) T10 retry-2
    folded §6 Ethics into §5+§7 to hit ICRA 6-page limit, regressing Dim 6
    Ethics 6 → 4. Codex gpt-5.5 + xhigh judgment APPROVE-WITH-MODIFICATIONS,
    predicted score 86.44 → 91.31 with these edits.
  - **New section: Step 4.5 — Engine ceiling reality check.** Explicit
    statement that engine kills worker sessions at 30 min regardless of
    `plan.yaml timeout_ms`. Daemon pattern: `setsid + nohup + disown`
    with 4-file checkpoint (`run.pid`/`run.log`/`exit.code`/`checkpoint.json`),
    `cleanup.sh` for next retry, lockfile discipline to prevent duplicate
    Jetson runs. Multi-session retry cycle explicit.
  - **New section: Step 5.5 — Verifier spot-check recipe.** 3 categories
    of hard rules: (A) JSONL — `head -1 schema` validation across ALL
    files, `wc -l` record count, `grep -c '"ERROR"\|"TypeError"'` error
    rate, field completeness check via Python; (B) LaTeX — 4-pass pdflatex +
    bibtex compile, `pdftotext paper.pdf - | grep -cF '[?]'` must be 0,
    `paper.blg` "Warning--I didn't find a database entry" check, `??`
    cross-ref resolution; (C) Verifier independence — never reuse the
    producer's session; fallback to `codex exec -m gpt-5.5 -c
    model_reasoning_effort=xhigh --skip-git-repo-check`.
  - **New section: Step 7.5 — Page-budget fold regression guard.**
    Pre-flight check before deleting any dedicated section to fit
    camera-ready page limit. Compute dimension regression from the fold
    BEFORE cutting. If a dimension would push below threshold, prefer
    waiver request, short-paper track, or restructure over silent fold.
  - **5 new failure modes (FM-10 through FM-14).** FM-10: foreground SSH
    >30 min killed by engine (Step 4.5 pattern + 4-file checkpoint
    recovery). FM-11: LaTeX `[?]` markers visible in PDF (4-pass compile
    + pdftotext grep + paper.blg check). FM-12: page-budget fold regresses
    reviewer-readiness dimension (Step 7.5 pre-flight check; waiver /
    short-paper track fallback). FM-13: producer self-reports "all cells
    done" but JSONL contains ERROR / TypeError records hidden in raw
    counts (Category A verifier recipe; cell-targeted fix fallback).
    FM-14: verifier runs in same session context as producer (~46.4%
    accuracy per SkillLens empirical studies; fresh session or codex
    exec fallback).
  - **task-prompt-snippets.md propagation** (codex mod #4): the
    negative-result honest framing recipe goes into T6 anti-patterns,
    the page-budget fold regression guard into T8 anti-patterns, and the
    framing reminder into T10 packaging brief. Generated plans now
    inherit the recipes automatically.
  - **3 new test prompts (test-prompts.json id 4-6).** Derived from
    V6 friction: Jetson 25-min install + 45-min experiment (engine
    ceiling); 27 JSONL files / 585 rows / 3 ERROR + 2 missing bib
    entries (verifier recipe); ICRA 6-page + M_success=0 + fold
    proposal (page-budget guard + honest framing). Codex's 3 sharp
    prompts preserved verbatim.
  - Backwards compatibility: v0.3.0 plans continue to work. New steps
    (4.5, 5.5, 7.5) are additive — they apply when the corresponding
    trigger condition is hit. No changes to the Rescue Layer, plan
    templates, or bootstrap script.
- 0.4.0 — platform-portable daemon + producer discipline + harness-paper framing.
  - **Why.** Three independent evidence trails from real plans on 2026-06-26:
    (a) darwin producers hitting "setsid: command not found" because
    `setsid` is Linux-only (util-linux package, absent on macOS); the
    daemon never launched and the 30-min cap was wasted on a failed
    shell command. (b) producer sessions burning the entire 30-min cap
    on iterative dry-runs (8 + 50 + 600 cells) before launching the
    real 1760-cell full sweep, leaving the daemon infra perfect but the
    real work never executed. (c) Harness / wrapper paper framing
    pitfalls when B5 (full system) == B0 (SOTA-tuned baseline) on the
    SOTA path but B5 >> B4 (stress baseline) on stress — burying the
    null regresses Dim 4 Clarity and Dim 6 Ethics.
  - **Patch A — Platform-portable daemon launch.** Step 4.5 daemon
    pattern rewritten with `if command -v setsid` platform detection:
    Linux keeps `nohup setsid ...`, macOS falls back to `nohup ... &
    disown` (equivalent detach from controlling TTY + SIGHUP ignore).
    Producer-side alternative noted: Python `os.setsid()` works on both
    platforms. FM-10 first-line fix updated to call out the macOS
    fallback. **Net effect:** darwin producers can now launch the
    daemon cleanly without touching util-linux compatibility layers.
  - **Patch B — Producer over-test guard + Pre-flight checklist.** New
    "Pre-flight checklist before launching the full daemon" section
    after Step 4.5 LOCKFILE discipline. 5-item checklist
    (corruption module / daemon tested once / lockfile paths /
    aggregator slot / cron registered) with explicit "Producer exit
    ≤ 5 min" rule. Anti-pattern code block (3 dry-runs eating the cap)
    shown alongside the correct pattern (1 dry-run ≤ 8 cells → launch
    + exit). **Net effect:** daemon infra is validated in ≤ 5 min
    instead of consuming the entire 30-min budget on iterative
    validation.
  - **Patch C — Model preload for NN-based cell pipelines.** New
    "Model-based pipelines: pre-load the model once" section with
    correct / wrong code blocks. ~43 cells/min vs ~10 cells/min
    (4× speedup). Implementation hint: patch `l2_execute()` to accept
    `preloaded_model` and `preloaded_device` kwargs.
  - **Patch D — Honest framing for harness / wrapper papers.** New
    FM-19 + new rubric section "Honest framing for harness / wrapper /
    agent-loop papers" in `references/reviewer-readiness-rubric.md`.
    Two-distinct-findings pattern: B5 == B0 on SOTA path + B5 >> B4 on
    stress path. Maps back to rubric dimensions (Dim 2 / 4 / 6) and
    provides the abstract-vs-Table-IV coherence test.
  - **3 new failure modes (FM-16, FM-17, FM-18, FM-19).** FM-16:
    producer over-tests and cap hits before full sweep launches
    (Pre-flight checklist + 1 dry-run rule; partial checkpoint.json
    salvage fallback). FM-17: model reload per cell instead of
    pre-load (4× speedup recipe; per-N reload fallback if OOM).
    FM-18: skip-if-exists check uses `splitlines()[0]` which fails on
    pretty-printed JSON (use full-file `json.load`; diagnostic recipe
    for suspiciously slow daemon). FM-19: harness paper claims B5
    beats B0 when B5 == B0 on SOTA path (rubric section "Honest
    framing"; §6.1 reframe fallback if already written wrong).
  - **Cross-cutting change:** Step 4.5 is now the consolidated
    "long-running compute" reference — daemon pattern + LOCKFILE +
    Pre-flight + model preload all live there in priority order
    (pattern → discipline → checklist → NN-specific tuning). v0.3.1's
    Step 4.5 body is preserved verbatim; new sections append.
  - Backwards compatibility: v0.3.x plans continue to work. Patches
    are additive — existing producers that already use `nohup + setsid
    + disown` on Linux are unaffected; only darwin producers and new
    plans inherit the platform detection. No changes to plan
    templates, bootstrap script, or Rescue Layer scripts.
- Future versions will add: cross-machine resumption, hardened liveness
  mode, and an opt-in "human in the loop every task" mode.

## License

MIT.