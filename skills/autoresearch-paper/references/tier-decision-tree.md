---
name: tier-decision-tree
description: Channel A (keyword) + Channel B (ask_user fallback) tier decision tree for SKILL.md Step 2. Handles repeated "Other" selections.
---

# Tier Decision Tree

Two-channel tier detection, with explicit failure handling for the "user
keeps refusing" case.

## Execution Procedure

```
decide_tier(target_venue, user_reply_count) -> tier_decision

call goal-keywords.detect_tier_by_keyword(target_venue)
if tier hit -> return tier with confirmation_required
if reject reason -> ask clarification, then Channel B
if no hit -> ask Channel B three-option question
if Other repeats 3 times -> block and ask for one venue sentence
```

## Channel A — keyword match

```
input: paragraph ② (target venue) from user brief
            │
            ▼
load references/goal-keywords.md
            │
            ▼
scan input (lowercased, strip punctuation) against
priority-ordered tier lists: arxiv < conference < journal-q1
            │
            ▼
  ┌─────────────────────────────────────┐
  │ tier hit found?                     │
  └─────────────────────────────────────┘
       │ yes                  │ no
       ▼                      ▼
return tier              go to Channel B
+ tier-confirmation msg
```

### Multiple venue mentions

User says: "先 arxiv,改完投 CVPR"

Action:
- Hit: both `arxiv` and `conference` keywords present.
- Tie-break: pick the **higher-priority tier** in the user's stated final
  intent. The phrase "改完投 CVPR" indicates CVPR is the real target.
- Tier-confirmation message must say: "Detected both arxiv and CVPR.
  Treating CVPR as the final target (tier = conference), with arxiv as
  an interim milestone. Confirm?"

### Reject list

If the input matches only the reject list (Google Scholar, h-index, SCI
without Q-tier, "中文核心"), do NOT fall back to Channel B silently.
Instead, send a one-line clarification:

> "你提到的 `[term]` 不是投稿渠道。你想发到哪?给我一个会议/期刊名,
> 或者我列 3 个常见档位让你选。"

Then go to Channel B.

## Channel B — `ask_user` fallback

Three options, in priority order:

```
Q: 你想发到哪里?这决定 plan 的工作量档位。
  1. arxiv 预印本      4 task / 2 agent / 1-2 天
  2. 顶会(IROS/ICRA/CVPR/NeurIPS…)  8 task / 4-5 agent / 1-2 周
  3. SCI Q1 期刊       8 task (实验更深) / 3-4 agent / 3-7 天
```

If the user picks `Other`:

```
Q: 你想发到哪本会/刊?(给我一个名字,我据此调子领域模板)
  [free text]
```

If the user enters free text:

- If it matches a known keyword → use that tier, confirm.
- If it does NOT match → tier = `conference` by default, log a warning
  in the plan directory, and proceed. The skill does not block on
  unknown venues because the worst case is "we did 8 tasks for a venue
  that only needed 4" — recoverable, not catastrophic.

## "User keeps refusing" failure mode

If the user picks `Other` in `ask_user` **three times in a row**, stop
the flow:

> "我连猜三次都没中。请用一句话告诉我目标会议或期刊名(全名或常见
> 缩写都行),例如 'CVPR 2027' 或 'IEEE T-RO'。如果你还没有目标,
> 输入 'arxiv',我按预印本档位跑。"

This blocks the skill until the user gives a usable answer or
explicitly says "stop".

## Output

Whichever channel resolves, the skill ends with:

```yaml
tier: <arxiv | conference | journal-q1>
tier_source: <channel-A-keyword | channel-A-multi-venue-tiebreak |
              channel-B-option-N | channel-B-freetext-defaulted>
tier_confirmed_by_user: false
```

`tier_confirmed_by_user` flips to `true` only after the tier-confirmation
step in Step 2 of the main flow (see `SKILL.md`). The plan generator
must refuse to run while `tier_confirmed_by_user: false`.
