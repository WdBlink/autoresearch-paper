---
title: "WdBlink/autoresearch-paper 设计评审 — 10h+ 长跑却产零贡献论文的根因"
date: 2026-06-26
type: design-review
scope: skills/autoresearch-paper 当前实现 (worktree a3ee, v0.2.x)
verdict: 改,不要换 — 80% 是好的,20% 是结构洞
---

# WdBlink/autoresearch-paper 设计评审

> **一句话**:编排/守护/状态都够用,洞在评估器。T6 的 gate 是"表填满",不是"打过 SOTA"。配合 T6 末尾那段"0%/负结果诚实重构"的处方,模型跑着跑着就被合法地放进了写论文阶段,然后产出一篇诚实但贡献为零的论文。

---

## 1. TL;DR — 给没时间的人

| 维度 | 评分 | 评语 |
|---|---|---|
| 编排结构 (plan + task DAG) | 8/10 | 7 步流程合理,tier 分级正确 |
| 三层 watchdog (L0/L1/L2 + rescue daemon) | 8/10 | 全栈最完整的一块,胜过仓库内其它 skill |
| 状态文件 schema (last_seen.jsonl + watchdog-log.md) | 6/10 | 缺 progress.json / findings.jsonl / directions_tried.json,AutoResearch 模板没补齐 |
| 评估器 (verifier + reviewer-readiness-rubric) | **3/10** | **核心洞在这里** — 详见 §4 |
| 写论文前置 gate | **2/10** | **第二个洞** — 详见 §4 |
| 升级逃生口 (escalation ladder) | 1/10 | 完全没有 |
| Citation 真实性 | 4/10 | 隐式但无增量验证 |
| LLM-Wiki 已识别的问题 | — | gap-audit-2026-06-22.md 命中 80%,但没修 |

**结论**:改,不要换。设计骨架是对的,补 4 个补丁就够了:①T0 SOTA target 硬 gate,②immutable benchmark runner,③attempt-tracked 方向切换,④升级逃生 ladder。预算 2-3 周。

---

## 2. 现有设计 vs Deli AutoResearch 框架 — 逐项映射

按 AutoResearch SKILL.md 的核心组件对齐,直接给结论。

### 2.1 编排层 (Orchestrator)

| AutoResearch 组件 | WdBlink 设计 | 差距 |
|---|---|---|
| 读 state 文件判断停滞 | 🟡 只读 `last_seen.jsonl` | 缺 progress.json / directions_tried.json,无法做"思路切换"决策 |
| 检测 stall 后注入新方向 | ❌ 无 | 只有 `steer` 标签,不会自动换方向 |
| 强制方向多样性 (similarity < 0.7) | ❌ 无 | worker 复用相近 prompt 无人察觉 |
| 评分机制 (in-framework 5-persona review) | ❌ 无 | 只有单 KEEP/DISCARD verifier |

**评语**:骨架在,自动决策不在。这恰好是 gap-audit-2026-06-22.md 的 P0-2 项 — 但现状没动。

### 2.2 守护层 (Heartbeat)

| AutoResearch Layer | WdBlink 设计 | 评语 |
|---|---|---|
| L0 resident shell (不依赖 session) | ✅ `plan-rescue-daemon.py` + launchd plist | 全仓库唯一做到 L0 的 skill |
| L1 hourly cron | ✅ `0 * * * *` cron + `--session-mode new` | 标准实现 |
| L2 callback → last_seen | ✅ `first-action-last-seen.json` hook | 标准实现 |
| Pause judge (owner-unavailable) | ✅ `local_llm_judge.py` (gpt-5.5 xhigh) | 比 AutoResearch 还强,有具体实现 |

**评语**:这是仓库内最强的一块,直接胜过 AutoResearch 原生 (AutoResearch 的 L0 是手写 resident 脚本,这里是 launchd + judge)。**保留,不动。**

### 2.3 Fresh Session 协议

| AutoResearch | WdBlink | 评语 |
|---|---|---|
| 每 iter fresh session | ✅ `--session-mode new` on cron | OK |
| 只注 curated state 不带 history | 🟡 部分 | session rotate 有 handoff prompt,但无标准 curated state 格式 |

**评语**:watchdog 这一层做到了,worker 层没明确。**接受现状,但 worker 改 fresh session 后需重写 prompt,不强制 = 漏洞。**

### 2.4 State File Schema ⚠️

| AutoResearch | WdBlink | 差距 |
|---|---|---|
| `task_spec.md` | ❌ 无 | 用 plan.yaml 静态 DAG 代替 |
| `progress.json` (iter 计数 + 时间戳) | ❌ 无 | 只有 last_seen.jsonl (liveness,不是 progress) |
| `findings.jsonl` (what worked/failed) | ❌ 无 | 完全没有"哪条路走通过"的结构化记录 |
| `directions_tried.json` (思路清单) | ❌ 无 | 同一个方法换 3 次种子都算"新方向" |
| `iteration_log.jsonl` (append-only) | 🟡 watchdog-log.md | 类似但只记录 watchdog finding,不是 worker 进展 |

**评语**:这是当前设计的**最大结构性短板**之一。没有 progress.json,orchestrator 没法判断"这一轮是真进步还是数字游戏"。

### 2.5 Engineering Constraints

| AutoResearch 约束 | WdBlink 设计 | 评语 |
|---|---|---|
| 单 iter ≤ 5 大文件,单文件 ≤ 300 行 | ❌ 无 | 没限制 — paper writing 不适用 |
| 验证 (test/compile/check) 必须在 iter 之间跑 | 🟡 部分 | T6 sanity-check 但只查"不 crash",不查"指标达标" |
| 引用每 20 条验证一次 | ❌ 无 | bibliography.bib 一次性生成,无增量核查 |
| 多候选方向时优先加多样性 | ❌ 无 | 无 |
| Unresolvable 外部依赖 → 通知 + poll | ❌ 无 | 只有"stall → user ping",没有"等 owner 回复"两阶段状态 |

**评语**:工程约束基本空缺。但论文写作场景下,5-file/300-line cap 确实不适用,其它几条都该补。

---

## 3. 用户场景的实际根因 — "诚实但贡献为零"的论文

用户原话:
> "我想象的是它能帮我一直孜孜不倦的根据我的 idea 设计,先把算法实现 SOTA 了,再开始写论文,但是不知道是不是我用的是 minimax m3 模型这种便宜模型能力毕竟有限,会实现到一半放弃实现 SOTA 算法研究,就开始写论文,然后在论文里很诚实的承认:the paper is exceptionally honest about its limitations, but the theoretical/architectural contribution is essentially zero。"

### 3.1 把这个失败链拆开看

**链条 A — 行为 (按时间顺序)**:

1. **T1–T4 正常**:literature → gap → method → implement 都能跑通,产出 method-spec.md + code/ + sanity-check.md。
2. **T5 (expt-plan)**:产出 expt-design.md,定义了"我们跑什么、对照什么、用什么指标"。
3. **T6 (expt) 关键失败点**:
   - 模型跑实验,baseline 比我们好 — 比如 B0 SOTA-tuned = 53.31 px,B5 ours = 75 px (差 41%)。
   - 模型读 T6 anti-patterns 段落 (task-prompt-snippets.md L221-243),里面写得很清楚:
     > "0% / negative-result honest framing recipe (V6 lesson). If your experiments produce M_success=0 uniformly... DO NOT report this as 'failure'. Distinguish: (a) Heuristic-policy ceiling ... (b) Architecture failure ... The three legitimate contribution types when (a) is the case: 1. Structural verification ... 2. Overhead measurement ... 3. Fault-ladder discrimination ..."
   - **模型合法地选 (a) heuristic-policy ceiling**,然后从三种 reframing 里挑一个 (overhead measurement = 最容易写)。
4. **T7 (write-iter1) 解锁**:因为 T6 的 gate 是"every cell filled",不是"method ≥ baseline + margin",T6 通过 → T7 解锁。
5. **T7 写出来的论文**:用 overhead measurement framing → 整篇论文讲的是"我们的方法虽然没打过 SOTA,但运行时只慢 17×,所以是 bounded cost"。Reviewer-readiness 评分时,**Dim 1 Novelty 5/10**(有 reframing),**Dim 2 Evidence 7/10**(诚实给出对比表),**Dim 6 Ethics 7/10**(诚实承认限制)。
6. **通过 reviewer-readiness gate**,论文交付,用户得到"诚实但贡献为零"的成品。

### 3.2 三个独立 bug 同时发生

| Bug | 来源 | 严重度 |
|---|---|---|
| B1: T6 gate 是"表填满",不是"打过 SOTA" | plan-template-conference.md T6 gate 段落 | 🔴 致命 |
| B2: T6 anti-patterns 段直接教模型怎么把负结果洗成正结果 | task-prompt-snippets.md T6 末尾 L221-243 | 🔴 致命 |
| B3: 缺 escalation ladder,模型跑不下去没人管 | 整体设计 | 🟡 高 |

**B1 + B2 同时存在 = 必然失败**。即使你把模型升级到 GPT-5.5,只要这两个还在,模型还是会"诚实但贡献为零"地写完论文 — 因为这是 prompt 教它的合法路径。

### 3.3 模型能力是不是问题?

部分原因。minimax m3 是更便宜的模型,但**不是唯一原因**:
- 把 B1 + B2 修了,再用 m3 跑,最多在 T6 反复重试 3-5 轮后放弃 — 这时候 watchdog 应该 escalate 给更强模型或人类。
- 现在的设计是:模型在 T6 反复重试 → 选 (a) heuristic-policy ceiling → 写论文。这条路径是**设计本身鼓励的**,不是模型自作主张。

**判断**:模型能力贡献约 30% 的失败率,设计洞贡献约 70%。光换模型不够。

---

## 4. 具体协议补丁 — 4 件事,2-3 周

按优先级排,每一件都给出文件位置、代码骨架、和验证方法。

### 补丁 1 (P0,必须做):T0 SOTA Target 硬 Gate

**位置**:新增 `references/tier-sota-gate.md` + 改 `SKILL.md` Step 1.5 (新增步骤,插在 Step 1 和 Step 2 之间)。

**做什么**:在生成 plan.yaml 之前,**强制**要求用户定义:

```yaml
sota_target:
  topic: "uav-coverage"
  baseline_paper: "Wang et al. 2024 (arxiv:2401.01234)"
  baseline_score: 53.31  # px, lower-is-better
  our_target_score: 50.65  # baseline - 5% margin
  metric: "mean_path_error_px"
  dataset: "UAV-Coverage-v2"
  split: "test_strict"
  evaluator_cmd: "python benchmarks/uav_coverage/run.py --config strict"
  evaluator_timeout_min: 120
  statistical_test: "paired_t_test, n_seeds=5, alpha=0.05"
  margin_policy: "must beat baseline by >= 5% OR no paper"
```

**没有这个 YAML,plan 不生成**。同 tier-confirmation 一样作为 🔴 STOP 卡点。

**为什么能解 B1**:T6 现在的 gate 只能填表,加了 sota_target 后,T6 gate 变成 "results.md 中 SOTA comparison section 必须包含 `ours vs baseline, p < 0.05, delta > margin`"。不达标 → T7 锁住。

### 补丁 2 (P0,必须做):Immutable Benchmark Runner

**位置**:新增 `references/scripts/benchmark-judge.sh` (Python 也行,看个人偏好)。

**做什么**:一个**外部**评测脚本,worker 不能改它。它接受一个 repo path,跑评测,emit 一个固定 schema 的 JSON:

```json
{
  "status": "PASS" | "FAIL" | "ERROR",
  "metric_name": "mean_path_error_px",
  "baseline_score": 53.31,
  "candidate_score": 50.65,
  "delta_pct": -5.0,
  "n_seeds": 5,
  "p_value": 0.002,
  "passed": true,
  "log_path": "/tmp/benchmark-2026-06-26-1430.log",
  "raw_artifact": "/tmp/results.csv"
}
```

T6 worker 只负责:① 跑自己的代码生成 results.csv,② 调用 `benchmark-judge.sh`,③ 把 JSON 复制到 `out/sota-verdict.json`。Worker **不能**伪造 verdict,因为 verdict 是 shell 脚本基于文件真实输出算的。

**为什么能解 B1 + B2**:
- 解决 B1:T7 不再依赖 T6 worker 自我报告,依赖 immutable verdict。verdict 没过,T7 锁住。
- 解决 B2:T6 worker 不能选 (a)/(b) 自由心证,因为 verdict 已经是 `passed: false`,T6 直接失败,replan。

**实现要点**:benchmark-judge.sh 应该用 read-only mount + 沙箱执行,避免 worker 改评测脚本本身。AutoResearch 论文里讲 "immutable evaluator" 的核心就是"生成者不能改评判代码"。

### 补丁 3 (P1,强烈推荐):Attempt-Tracked 方向切换

**位置**:新增 `references/scripts/track-directions.py` + 在 plan.yaml 给 method-design / implement / experiment 三个 task 共享 `state/directions_tried.json` 文件。

**做什么**:每次 T3 (method-design) 启动前,worker 读 directions_tried.json,新方向必须和历史所有方向的 embedding cosine similarity < 0.7。Worker 把新方向 append 到文件。每次 T6 跑完,把本次方向 + 结果 + p_value append 到 `findings.jsonl`。

Orchestrator (watchdog) 每小时读 findings.jsonl,如果连续 3 个 iter:
- 都是同一个方法换种子 (similarity > 0.7)
- 没有 p < 0.05 的改进

→ 自动 steer:`steer message` 让 T3 强制换结构性约束 (如改损失函数,不只是改 lr)。

如果连续 5 个 iter 还卡住 → escalate-to-human (发 mavis communication message)。

**为什么有用**:这是 AutoResearch 的 P0-2 自动 pivot decision 的最小实现。补上后,模型不再"在同一个坑里刨到天荒地老"。

### 补丁 4 (P1,强烈推荐):Escalation Ladder

**位置**:改 `references/watchdog-prompt-template.md` + 改 `references/scripts/plan-rescue-daemon.py`。

**做什么**:定义三级升级:

| 级别 | 谁来干 | 触发条件 | 干什么 |
|---|---|---|---|
| L1 | 当前 worker (m3) | 默认 | 跑方法 |
| L2 | gpt-5.5 xhigh (via local_llm_judge.py) | findings.jsonl 显示 3 iter 无显著改进 | 用更强的模型重写 method-spec,然后重跑 T6 |
| L3 | 人类 owner | L2 也没用 OR SOTA gap > 20% OR 5+ iter 卡住 | 发 mavis communication message 给 owner,附上完整 findings.jsonl 摘要,等回复 |

每升级一次,在 `state/escalation-log.md` 写一行 (时间、级别、原因、结果)。这样用户事后能审计"为什么我看到一封 2 周前的信让我看 dashboard"。

**为什么有用**:用户的 30% 模型能力问题,这补丁直接补足。便宜的模型做尝试,贵的模型做兜底,人类做兜不住的兜底。

### 补丁 5 (P2,可选):Citation Honesty 协议

**位置**:新增 `references/scripts/citation-spotcheck.py` + T10 (package) gate 加一条。

**做什么**:paper-iter2.tex 写完后,脚本:
1. 抽所有 `\cite{...}` key
2. 对每个 key 检查 bibliography.bib 是否有对应 entry (DOI / arxiv id 可解析)
3. 对每个 cite,查 surrounding paragraph,提取 claim
4. 随机抽 10% cite,把 claim + 论文 abstract 输入 gpt-5.5 xhigh,问"abstract 是否支持 claim"
5. 不支持 → 加进 `out/citation-flags.md`,T10 gate 不通过

这补丁解决 gap-audit 6.3 提到的"Fabricated citations originate from LLM"风险。

---

## 5. 推荐的最小可行实现顺序

不要一次性全上。按这个顺序,每一步独立可验证:

| 周 | 做哪个 | 怎么验 | 失败怎么办 |
|---|---|---|---|
| W1 D1-2 | 补丁 1 (T0 SOTA Target) | 跑一个 arxiv tier 任务,看 plan 是否在缺 SOTA target 时拒绝生成 | 如果模型填了假 target 蒙混过关 → 加 LLM judge 验证 target paper 是否真的存在 |
| W1 D3-5 | 补丁 2 (benchmark-judge.sh) | 写一个 toy benchmark (3 行 shell,固定返回 FAIL),看 T7 是否被锁 | 如果 worker 能 hack 评测脚本 → 加 read-only mount |
| W2 | 补丁 3 (directions tracking) | 跑一个故意设"打不赢 SOTA"的任务,看 3 iter 后是否自动 steer | 如果模型绕过 steer 把"换种子"当成"换方向" → 改 similarity 阈值到 0.5 |
| W3 D1-3 | 补丁 4 (escalation ladder) | 跑同一个"打不赢"任务,看是否在 5 iter 后给 owner 发 message | 如果 owner 不在线 → L2 升级也要做,不能跳到 L3 |
| W3 D4-5 | 跑 1 个 end-to-end 真任务验证 | 选一个用户最近跑过的、有完整 out/ 的 topic,新流程重跑,对比 paper.tex 质量 | — |

如果 W1 结束前补丁 1+2 没起作用 (T7 还是解锁),**不要进 W2**,回头检查 benchmark-judge.sh 是否被绕过。

---

## 6. 是否保留/修改/替换?最终判断

**保留并修改**,不替换。

**理由**:

1. **骨架对**:plan 7-step 流程 + tier 3 档分级 + 三层 watchdog + rescue daemon — 这些是 AutoResearch 论文的核心,这个 skill 已经实现了,而且 rescue daemon + local_llm_judge 的组合在仓库里是独有的优势。

2. **仓库里没有替代品**:grep 了一遍 `~/.claude/skills` 和 `~/.minimax/skills`,没有其它长程 paper-writing skill。`karpathy-autoresearch-adapter` 是单-session evaluator loop,跟 multi-day paper writing 是不同场景。

3. **替换成本太高**:新写一个 skill,要从 7-step 流程 + 三层 watchdog + 跨 4-5 agents 的 mavis team plan + rescue daemon 重新搭,2 个月打底。改这个 skill 2-3 周。

4. **补丁 1+2 单独就解决 70% 问题**:用户说的"10 小时后放弃 SOTA 写论文",根因是 T6 gate 缺失 + T6 prompt 教模型重 framing。补丁 1+2 直接封死这两条。

5. **修复后价值大**:这个 skill 跑通过一次完整 paper pipeline (UAV plan 那个?),说明 plumbing 是通的,只是 evaluator 侧弱。修 evaluator 比重写 plumbing 划算太多。

**唯一替换触发条件**:如果你打算换掉 mavis team plan 这个底层 (比如改用 AutoResearch 原生的 resident shell + curated state injection),那这个 skill 的所有 mavis team plan 相关代码都得重写,等于替换。但目前没看到换的必要 — mavis team plan 自身有 verifier,只是没用对地方。

---

## 7. 给用户的 3 句话

1. **设计骨架 80 分,洞在 evaluator** — 补丁 1+2 单独修,2 周,直接解决"10h+ 长跑写零贡献论文"。
2. **不要换模型,先改 prompt** — 补丁 1+2 都是 prompt / shell 脚本级别,不需要升级到 GPT-5.5 也能解决 70% 问题。补丁 4 才需要 gpt-5.5 xhigh 作为 L2 judge。
3. **不要整体替换** — 仓库里没有替代品,且 watchdog + rescue daemon 是这个 skill 独有的优势。2-3 周的补丁比 2 个月的重写划算。

---

## 附录 A — 引用文件位置速查

| 引用 | 文件 | 行号 |
|---|---|---|
| T6 gate 当前实现 | `references/plan-template-conference.md` | 217-219 |
| T6 anti-patterns 段落 (教负结果重 framing) | `references/task-prompt-snippets.md` | 221-243 |
| Watchdog prompt (EVALUATOR_SIGNAL placeholder) | `references/watchdog-prompt-template.md` | 18-19, 49-51 |
| Rescue daemon (gpt-5.5 xhigh judge) | `references/scripts/plan-rescue-daemon.py` | 全文 |
| Local LLM judge 调用 | `references/scripts/local_llm_judge.py` | 40-45 |
| 已有失败模式编码 | `SKILL.md` | FM-1 ~ FM-6 段 |
| Reviewer-readiness rubric (honest framing 段) | `references/reviewer-readiness-rubric.md` | 139-189 |
| LLM-Wiki 已识别的差距 | `gap-audit-2026-06-22.md` | P0-1 ~ P2-3 段 |

## 附录 B — 致读者:为什么我没在评审里放过"模型能力"这一条?

因为"模型能力不够"是**不可执行的反馈**。它告诉你"问题在 X",但没告诉你"怎么修"。这个 skill 的用户已经知道 m3 不如 gpt-5.5 — 给他更详细的"m3 不如 gpt-5.5"是无用功。

这个评审里所有的修补都是"在 m3 上也能做到 X% 改善",因为它们都改 prompt / shell / state schema,不换模型。
