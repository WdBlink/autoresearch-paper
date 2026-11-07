<div align="center">

# Autoresearch Paper guides

![Version](https://img.shields.io/badge/version-3.0.0-blue.svg)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](../LICENSE)

</div>

---

Start with the [research workflow](../README.md) and [installation guide](getting-started.md).
The command guides below cover auxiliary engineering work.

---

## Quick Start

```bash
git clone https://github.com/WdBlink/autoresearch-paper.git
cd autoresearch-paper
bash scripts/install.sh --codex --global
```

---

## Guide Index

| Guide | Description |
|-------|-------------|
| [Getting Started](getting-started.md) | Installation, first run, core concepts |
| [/autoresearch --auto](autoresearch-orchestrator.md) | Select and run an engineering pipeline against a success predicate |
| [/autoresearch:iterate](autoresearch.md) | Optimize a metric through verified changes |
| [/autoresearch:plan](autoresearch-plan.md) | One-shot wizard — Goal → Scope, Metric, Verify |
| [/autoresearch:debug](autoresearch-debug.md) | Autonomous bug-hunting with scientific method |
| [/autoresearch:fix](autoresearch-fix.md) | Error crusher — tests, types, lint, build |
| [/autoresearch:security](autoresearch-security.md) | STRIDE + OWASP + red-team security audit |
| [/autoresearch:ship](autoresearch-ship.md) | 8-phase shipping workflow |
| [/autoresearch:scenario](autoresearch-scenario.md) | Scenario explorer — 12 dimensions |
| [/autoresearch:predict](autoresearch-predict.md) | 5 expert personas debate before you act |
| [/autoresearch:learn](autoresearch-learn.md) | Autonomous documentation engine |
| [/autoresearch:reason](autoresearch-reason.md) | Adversarial refinement with blind judges |
| [/autoresearch:probe](autoresearch-probe.md) | 8 personas interrogate requirements to saturation |
| [/autoresearch:improve](autoresearch-improve.md) | Research ICP challenges, discover improvements, generate PRDs |
| [/autoresearch:evals](autoresearch-evals.md) | Analyze results TSV — trends, plateaus, checkpoints |
| [/autoresearch:regression](autoresearch-regression.md) | Stability gate — baseline diff, STABLE/UNSTABLE verdict before you push |
| [Chains & Combinations](chains-and-combinations.md) | Multi-command pipelines with all 14 commands |
| [Examples by Domain](examples-by-domain.md) | Real-world examples: software, sales, marketing, DevOps, ML, HR |
| [Advanced Patterns](advanced-patterns.md) | Guards, MCP, CI/CD, evals checkpoints, transform.sh |
| [Hooks Reference](hooks.md) | 9 auto-firing hooks: safety gates, context injection, notifications |
| **[Scenario Guides](scenario/)** | **Real-world scenario walkthroughs** |

---

## Quick Decision Guide

| I want to... | Use |
|--------------|-----|
| Run a research project | `/autoresearch <research question>` |
| Orchestrate an engineering task | `/autoresearch --auto <goal>` |
| Improve a mechanical metric | `/autoresearch:iterate` |
| Don't know what metric to use | `/autoresearch:plan` |
| Requirements are unclear — surface hidden constraints | `/autoresearch:probe` |
| Run a security audit | `/autoresearch:security` |
| Ship a PR / deployment / release | `/autoresearch:ship` |
| Hunt all bugs in a codebase | `/autoresearch:debug` |
| Fix all errors (tests, types, lint) | `/autoresearch:fix` |
| Debug then auto-fix | `/autoresearch:debug --fix` |
| Check if something is ready to ship | `/autoresearch:ship --checklist-only` |
| Explore edge cases for a feature | `/autoresearch:scenario` |
| Generate test scenarios | `/autoresearch:scenario --format test-scenarios` |
| Get expert opinions before starting | `/autoresearch:predict` |
| Debate an architecture decision | `/autoresearch:reason --domain software` |
| Generate docs for a new codebase | `/autoresearch:learn --mode init` |
| Update existing docs after changes | `/autoresearch:learn --mode update` |
| Discover what to build next for your ICP | `/autoresearch:improve` |
| Analyze loop results, detect plateaus | `/autoresearch:evals` |
| Verify a change is safe to push (catch regressions) | `/autoresearch:regression` |
| Gate, auto-fix, then ship in one chain | `/autoresearch:regression --predict --evals --fix --ship` |
| Optimize without breaking existing tests | `/autoresearch:iterate` with `Guard: npm test` |
| Bound any looping command | Add `Iterations: N` inline |

---

[Autoresearch Paper repository](https://github.com/WdBlink/autoresearch-paper)
