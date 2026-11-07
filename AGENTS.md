# Autoresearch Paper

Use the main `autoresearch` skill for research projects. Read
`.claude/skills/autoresearch/SKILL.md` and `.claude/commands/autoresearch.md`.
The same workflow covers intake, venue calibration, research planning,
experiments, writing, independent review, and verified delivery.

## Research runs

- Use `context` to load the current stage and its evidence requirements.
- Ask the user for venue and budget decisions through the host's input tool.
- Keep frozen research plans, evaluators, and run evidence outside metric-loop rollback.
- Follow `foundation/references/runtime-contract.md` for run state and recovery.

## Engineering commands

Use `autoresearch iterate` for a bounded metric loop. Define the goal, edit
scope, metric, verification command, and any regression guard. Make one
change per iteration. Commit it, verify the metric and guard, keep or revert
the change, and log the result. Use `autoresearch --auto` for predicate
orchestration. The [command guides](guide/README.md) list auxiliary commands.

## Maintain the skill

- Edit command and skill instructions in `.claude/`.
- Edit the research controller, its references, and tests in `foundation/`.
- Run `bash scripts/transform.sh` to update the installed distributions.
- Run `bash scripts/test-paper.sh` for the research workflow and use the
  relevant shell suites in `tests/` for packaging and engineering commands.
- Preserve source attribution and the copyright notices in `LICENSE`.

See the [installation guide](guide/getting-started.md) and
[contribution guide](CONTRIBUTING.md).
