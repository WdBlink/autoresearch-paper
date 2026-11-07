# Get started with Autoresearch Paper

## Install

Clone the repository and install the skill for your host. This example uses Codex.

```sh
git clone https://github.com/WdBlink/autoresearch-paper.git
cd autoresearch-paper
bash scripts/install.sh --codex --global
```

For another host, use `--claude`, `--opencode`, `--pi`, or `--muse` in place of
`--codex`. To install in one research project, run the installer by its absolute
path from that project directory and pass `--local`.

Claude Code also supports the plugin marketplace.

```text
/plugin marketplace add WdBlink/autoresearch-paper
/plugin install autoresearch@autoresearch-paper
```

## Start a research run

Open a new session in the research project. Invoke `$autoresearch` in Codex or
`/autoresearch` in Claude Code with the research question and the paths to the
available materials.

```text
$autoresearch Use the dataset and draft brief in this project to design a study
of whether the intervention improves the primary outcome.
```

The skill compares venues using official requirements and asks you to choose
a target. It reads representative accepted papers to plan figures and tables.
Review the concrete research plan and answer the budget question before new
experiments begin. The final delivery includes a compiled PDF, editable
manuscript sources, and supporting evidence.

The controller requires Python 3.10 or newer. PDF measurement uses Poppler.
Manuscript compilation uses TeX. Statistical PDF plots use Matplotlib.

## Use the engineering commands

Invoke `$autoresearch iterate` in Codex or `/autoresearch:iterate` in Claude Code
to optimize a mechanical metric. Use `--auto` with the main command to enter
predicate orchestration. See the [command guides](README.md) for the available
commands and the [research workflow](../README.md) for the main stages.
