---
name: goal-keywords
description: Channel A tier-detection keyword table — maps target venue strings (CVPR/NeurIPS/arXiv/SCI Q1) to arxiv/conference/journal-q1 tiers. Single source of truth for SKILL.md Step 2.
---

# Goal Keywords — Channel A Tier Detection

Single source of truth for the keyword table that maps user-supplied target
venues to tiers. `SKILL.md` and `tier-decision-tree.md` both reference this
file. **Update here, not in SKILL.md.**

## Execution Procedure

```
detect_tier_by_keyword(target_venue) -> tier_hit_or_none

normalize target_venue
scan arxiv, conference, journal-q1 keyword groups
if multiple groups hit -> choose the highest-priority final target
if only reject-list terms hit -> return reject_reason
if no terms hit -> return none
```

## How this is used

The skill scans paragraph ② ("目标") of the user brief against the
per-tier keyword lists below. The first tier whose keyword list has a hit
wins. Case-insensitive substring match. Substrings may overlap (e.g.
"投稿 ICRA" still hits `conference`); the first listed tier in `priority`
order wins on conflict.

If nothing hits, fall back to Channel B (`ask_user`).

## Priority order

```
arxiv  <  conference  <  journal-q1
```

When the user's brief mentions multiple venues (e.g. "先投 arxiv 再投 CVPR"),
pick the **highest-priority tier** mentioned (CVPR → conference) and note
in the tier-confirmation message that arxiv-preprint is being treated as
an interim milestone, not the final target.

## `arxiv`

- arxiv
- arXiv
- 预印本
- preprint
- working paper
- 技术报告
- technical report
- 没指定 / 想先发出来再改

If the user explicitly says "不投稿 / 只是想写一篇总结 / 个人 blog", also
hit `arxiv` but warn in tier-confirmation that no venue gate is enforced.

## `conference`

Robotics, vision, NLP, ML, systems — full list kept loose because new
venues appear every year. Add to this list when a new venue becomes
relevant; do not gate on it.

### Robotics

- IROS, ICRA, RSS, TRO, ICAR, IEEE ROBIO, ACC, CDC, CASE, IAV, ISER,
  Humanoids, ICAPS, AAMAS

### Vision

- CVPR, ICCV, ECCV, WACV, BMVC, 3DV, ACCV

### NLP / IR / Speech

- ACL, EMNLP, NAACL, COLING, EACL, AACL, SIGIR, CIKM, WSDM, Interspeech,
  ICASSP, ASRU, SLT

### ML general

- NeurIPS, ICML, ICLR, AAAI, KDD, UAI, AISTATS, COLT, ALT, JMLR (conf)

### Systems / DB / HCI

- SOSP, OSDI, NSDI, EuroSys, ASPLOS, ISCA, MICRO, HPCA, VLDB, SIGMOD,
  OOPSLA, PLDI, POPL, CHI, UIST, CSCW, MobiCom, SenSys

## `journal-q1`

### Robotics

- IJRR, T-RO (IEEE Transactions on Robotics), JFR (Journal of Field
  Robotics), Robotics and Autonomous Systems, Autonomous Robots

### Vision / AI

- T-PAMI (IEEE TPAMI), IJCV, CVIU, Pattern Recognition, IEEE TIP

### ML general

- JMLR, Machine Learning Journal, Nature Machine Intelligence,
  Nature Communications (engineering), Science Robotics

### Other

- IEEE T-AC, Automatica, Annual Review of Control

## Hits that are NOT tiers (must reject)

These look like venues but are not, and the skill should not treat them as
a tier signal:

- "Google Scholar" — search engine, not venue.
- "h-index / 影响因子 / JCR Q1" — these describe journals but the user
  must still name a specific journal.
- "SCI" without a Q-tier — too vague; treat as miss → Channel B.
- "核心期刊" / "中文核心" — out of scope for this skill; the templates
  are LaTeX/English-centric. Warn and ask the user to confirm.

## Update protocol

When a new venue becomes relevant, add it to the matching tier list. When
a venue changes tier (e.g. a workshop becomes a full conference), update
the keyword and add a changelog entry:

```
## Changelog

- 2026-06-23 — initial draft, 3-tier scheme.
```
