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

### Step 5 — Run the team

**INPUT:** validated `<plan-dir>/plan.yaml` (Step 3) + Step-4 watchdog resources + user "go".
**OUTPUT:** `<plan-id>` (printed to user), dashboard URL. Skill enters observe mode.

Call `mavis team plan run --plan <scratchpad>/autoresearch/<slug>/plan.yaml`
and capture the plan id. Print the plan id and the dashboard URL back to
the user. The skill is now in **observe mode**.

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
- Future versions will add: cross-machine resumption, hardened liveness
  mode, and an opt-in "human in the loop every task" mode.

## License

MIT.