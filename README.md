# Autoresearch Paper

![Version](https://img.shields.io/badge/version-0.2.0-CC785C)

Turn a paragraph-level brief — topic, target venue, reference materials —
into a publication-grade academic paper through a fully orchestrated Mavis
agent team, an evidence-anchored plan, and a per-topic watchdog. The user
never writes `plan.yaml`, never schedules a cron, and never registers a
hook — the skill does all of that.

Part of WdBlink LLM Skills.

## What it does

```
you: 3 paragraphs (topic + target venue + materials)
skill: tier → plan.yaml → agents → cron + hooks → /mavis-team plan run
you: paper.tex + reviewer-readiness.md (and a watchdog that never sleeps)
```

Three tiers, with a 2-channel fallback for tier detection:

| Tier | When | Tasks | Wall-clock |
|---|---|---|---|
| `arxiv` | preprint, working paper, no venue gate | 4 | 1–2 days |
| `conference` | CVPR / NeurIPS / ICRA / IROS / ACL / ... | 8 (+ optional rebuttal) | 1–2 weeks |
| `journal-q1` | SCI Q1 / Nature 子刊 / T-PAMI / T-RO | 8 (deeper experiments) | 3–7 days |

## Install

### Mavis / MiniMax Code (recommended for this skill)

```bash
mkdir -p ~/.mavis/skills/autoresearch-paper
rsync -a skills/autoresearch-paper/ ~/.mavis/skills/autoresearch-paper/
```

After install, restart the Mavis daemon or reload skills; then
`/autoresearch-paper` is invokable from any MiniMax Code session.

### Codex / Claude Code (works, but loses Mavis-only features)

```bash
mkdir -p ~/.codex/skills/autoresearch-paper
rsync -a skills/autoresearch-paper/ ~/.codex/skills/autoresearch-paper/

mkdir -p ~/.claude/skills/autoresearch-paper
rsync -a skills/autoresearch-paper/ ~/.claude/skills/autoresearch-paper/
```

In Codex/Claude Code, the skill runs the agent team and the plan
generation, but the watchdog cron and `mavis`-specific hooks degrade
to "best effort" — the plan still completes, but the user has to
self-patrol because the cron will not fire.

### Requires

- `mavis` CLI on PATH (for full watchdog functionality)
- A workspace with at least 2 GB free (for plan artifacts and
  last_seen.jsonl growth)
- Mavis GUI / MiniMax Code.app running (for the watchdog cron to fire)

## Usage

```text
/autoresearch-paper

> 想研究风场干扰下无人机集群的能效覆盖路径规划,目标 CVPR 2027。
  手头有 3 篇 PDF,放在 ~/Downloads/uav-refs/。
```

The skill walks through 7 steps; you only need to interact at steps 1
(provide the 3 paragraphs) and 2 (confirm the tier). After that, the
skill confirms the plan preview, then runs the team.

During the run, three commands are exposed:

- `/autoresearch-paper status` — show plan progress + last_seen.
- `/autoresearch-paper pause` — pause the plan.
- `/autoresearch-paper resume` — resume a paused plan.

## Workflow

| Step | Description |
|------|-------------|
| Collect | Ask for topic, target venue, materials |
| Tier | Detect tier via keyword + `ask_user` fallback |
| Plan | Generate `plan.yaml` (user never sees the YAML, only the task graph) |
| Bootstrap | `bootstrap-watchdog.sh` creates per-topic watchdog agent + cron + hook |
| Run | `mavis team plan run` and capture plan id |
| Patrol | Hourly cron checks `last_seen.jsonl` and emits findings |
| Deliver | `paper.tex` + `reviewer-readiness.md` + `next-steps.md` |

## Boundary

The skill produces a structured draft — `paper.tex`, figures, a
reviewer-readiness self-check, and a `next-steps.md` listing what a
human still has to do. It does **not** produce a camera-ready PDF,
does **not** submit to any venue, and does **not** replace human
authorship of novel scientific claims. The user owns novelty; the
skill produces the work that surrounds it.

If the topic has no measurable evaluator (no experiment, no
simulator, no public benchmark), the skill downgrades to `arxiv`
tier with a warning, or refuses to start if the user insists on a
higher tier.

## Files

```
skills/autoresearch-paper/
├── SKILL.md
├── README.md
└── references/
    ├── goal-keywords.md              # tier keyword table
    ├── tier-decision-tree.md         # 2-channel fallback
    ├── plan-template-arxiv.md        # 4-task plan
    ├── plan-template-conference.md   # 8-task plan
    ├── plan-template-journal-q1.md   # 8-task deep plan
    ├── task-prompt-snippets.md       # per-task prompt fragments
    ├── watchdog-prompt-template.md   # per-topic watchdog system prompt
    ├── bootstrap-watchdog.sh         # agent + cron + hook setup
    ├── first-action-last-seen.json   # PostToolUse hook body
    └── reviewer-readiness-rubric.md  # 6-dimension scoring

tests/e2e-uav-coverage.md             # end-to-end test scenario
```

## Tests

See `tests/e2e-uav-coverage.md` for the full e2e scenario. It runs the
skill against a synthetic UAV coverage topic and asserts each layer
(tier detection, plan generation, watchdog bootstrap, plan execution,
deliverable) produces the expected artifacts.

## Mac sleep caveat

If your Mac sleeps, the hourly watchdog cron does not fire. The watchdog
resumes patrols on wake. If you need hardened liveness (continuous
patrol even during sleep), wait for `--mode=hardened` in a future
version, or run the watchdog on a non-Mac box.

## License

MIT