# 本地科研知识迁移矩阵

本分支以 `uditgoenka/autoresearch@7bddd056dfd0b0ded8360588d8101b1ecb5c0baa`
的完整仓库为根目录基础。`foundation/` 是其新增 `paper` 子命令，经过现有
transform/install 路径分发到各宿主 Skill 的 `paper/`。旧 autoresearch-paper
代码保留在原分支与 Git 历史，本分支不以旧运行时加 third_party 快照充当重建。

## 盘点口径与来源身份

本轮沿 Deli 的 PROVENANCE、全部领域 references、四个本地脚本的接口及对应测试，
以及较新 `/Users/wdblink/AI/paperflow` 的 Skill、protocol、intake、requirements、
effects、typed actions、venue/template、review、finalizer 和关联回归案例盘点。
`/Users/wdblink/AI/agents/paperflow` 属另一个较旧工作树，不能代表本轮最新增量。

- Deli 公开协议基线为 `559037a14161eb43ed343d5595ab1406dce13109`。公开模块仅作方法比较，
  本分支未复制其整份未识别标准许可证的原文/HTML，也未重新许可。
- Deli 的投稿校准、实验图表、R6、交付合同、论文表达及 checkpoint 是用户本地增量。
  当前 PROVENANCE 记载 2026-10-18 重构、2026-10-20 venue 校准；后续未单独标日期的文件
  以本轮实际 SHA-256 固定，不捏造提交日期。
- 新 PaperFlow 的 HEAD 是 `1bd8934a876d87c071b3b5e51a1728708c406d0c`（2026-10-04），
  被使用文件包含大量未提交增量，因此每个文件都记录真实 hash 和 dirty 状态。
  迁移的是领域方法和合同约束，未把此 HEAD 冒充全部被读内容，也未复制其图运行时。
- LLM-Wiki 页面是本地总结及推断。迁移其可检验的问题与证据边界，不宣称运行了
  RIDAR、SciΠvot、ScholarCatalyst 或复现其作者结果。

精确的 51 项来源路径、版本、hash、身份和使用方式见
[`foundation/provenance.json`](../foundation/provenance.json)。各行 D/P/W 路径分别相对
Deli Skill、较新 PaperFlow 根目录、LLM-Wiki 根目录；文件 hash 以该 JSON 为准。

## 逐项迁移

`Controller.context` 实际返回当前阶段知识全文、知识 hash、上游命令协议、
批准 Brief、已接收输入 hash、要求及动作合同。它不只返回文件名。
所有阶段知识均在 `foundation/references/knowledge/`，由宿主执行领域判断，
由 `planning.validate`、`science.validate` 和控制器检查可机械验证的约束。

| ID | 来源/版本 | 新架构落点与实际加载 | 接线/验证证据 | 状态及限度 |
| --- | --- | --- | --- | --- |
| K01 投稿校准 | D `venue-calibration.md`、`venue_profile.py` 与测试，用户本地 10 月增量；P `venue.py` / `venue_template.py` | `venue.md` → `planning.calibrate/venue`（纯函数复用 `vendor/deli-local` 原样 helper）；官方规则、模板、同方向样本/acceptance evidence、真实 PDF 测量、design records、profile/计划校验 | `test_planning` 的实际 PDF 测量、伪造 measurements、模板 hash 改变、缺录用依据/方向、不正确 fixture 身份用例；完整 fixture venue→plan→review | 已接线；样本数量不足和 caption 启发式要披露，软件样本不是已录用论文 |
| K02 实验设计与记录 | D `experiment.md` 方法及本地 `codex-runtime.md` / `checkpoint.md`；P feasibility/experiments 方法 | `plan.md`、`experiment.md` → `science._design/_experiment/_validate_experiment`；冻结协议、变量、claim、真实每次 run/原始记录/摘要 | `test_science` 的冻结设计、原始测量不符、漏 run、失败/提前停止保留、错误分母、holdout/seed-only pairing、冻结 evaluator；fixture 保留负结果 | 已接线；本次数值适配器使用配对 case 的均值路径，未知统计方案明确拒绝 |
| K03 图表统计与证据链 | D `experimental-figures.md` 本地增量；P `evidence_assets.py` 方法 | `figures.md` → `science._statistics/render_statistics/_validate_figures`；raw→集合/变换→sidecar→图表→caption→claim | `test_science` 的 SVG/TeX 标签、PDF 可复算、数值/图注/图像改变、分母与失败、覆盖闭包；fixture 生成实际统计图/表并入 PDF | 已接线；广泛图型知识按阶段加载；自动 renderer 只支持已声明统计路径，不伪造不支持图型 |
| K04 计划冻结与 R6 | D `plan-compliance.md` / `plan_audit.py` 与测试，本地新增 | `plan.md`、`review.md` → `Controller.commit` 的 frozen plan，`planning.plan_snapshot/review_plan/review`（纯函数复用本地 plan_audit）；轮前快照、现计划、成稿三件材料 | `test_planning` 的遗漏条目、事后改计划和原快照绑定；fixture 中 R6 与 G1–G5 均携带证据 | 已接线；语义披露充分性由真实 reviewer 判断，总分不能覆盖偏离 |
| K05 逐项交付合同 | D `deliverable-contract.md` / `deliverable_contract.py` / tests；P `requirements.py` / tests | `intake.md`、`plan.md`、`review.md`、`delivery.md` → 本地 item-validator 及 `check_brief/Controller.check_orders/bind/check_reviews/finalize` | `test_runtime` 任务覆盖与未知动作；完整 fixture 的 requirement→work order→typed action→绑定→逐项 review→export；缺项/过期/错绑负例由 runtime 集成回归覆盖 | 已接线；结构及 hash 检查不代替语义审阅 |
| K06 学术表达与保真 | D `academic-prose.md` / `academic-prose-examples.md` 用户本地增量 | `write.md` → `science._validate_write`；读者顺序、真实动作、主张范围、数值/引用关系核对进入写作及审阅上下文 | `test_science` 的因果/显著措辞、删除不利结果、单位/条件/分母、正文必须含被核对数字、revision fidelity；fixture 有真实 TeX/PDF | 已接线；未声称经过读者实验，未复制案例事实作为当前论文结果 |
| K07 checkpoint/轮次/恢复 | D `checkpoint.md` / `checkpoint.py` / tests，本地实现 | `plan.md`、`delivery.md` → `Controller.prepare_round/apply_round/operation/record/rewind/reconcile`；只维护一份 paper ledger | `test_runtime` 的精确批准、历史不重置、证据过期、幂等/停滞/结构 pivot；fixture 与 runtime 恢复故障注入 | 已适配同一状态所有者；不启动 Deli 原账本，原格式不冒称可直接续跑 |
| K08 完整 intake | P Skill/protocol、`docs/intake.md`、`intake_reading.py` 与 evidence closure tests，HEAD+dirty hash | `intake.md`、`venue.md` → `planning.intake`、`Controller.read_material`；材料 coverage、真实 read spans、依据、路线比较、feasibility/resources，官方/观察/unknown 分开 | `test_planning` 部分读取、伪 quote、metadata-only、改变材料与无依据选型；fixture intake | 已接线；controller 实际返回 span 和字节，仍不证明模型理解 |
| K09 可执行逐项闭环 | P `requirements.py`、`scripted_work.py`、`docs/brief-deliverable-contract.md` 与 tests | `plan.md`、`review.md`、`delivery.md` → `Controller.execute/_action/bind/check_reviews/finalize`；typed actions 不执行任意生成程序 | fixture 实际 render/compile/copy/validation 后每项绑定和 review；源码保留覆盖未知/遗漏工作单、陈旧/缺失 binding 与 requirement checks 的回归入口 | 已接线；身份依据来自实际宿主，fixture reviewer 是接口数据 |
| K10 操作失败/不确定/GO 语义 | P `work_effects.py`、`execution_gates.py`、ledger/protocol、effect dependency tests | `experiment.md`、`plan.md`、`delivery.md` → `Controller.execute/reconcile/ready`；外部不明先对账，终态失败与负科研结果区分 | `test_science` unknown outcome；runtime 的丢终态回执/重放拒绝/对账故障注入；fixture 无模型/远程作业 | 已适配；未移植 PaperFlow 的全部远程 GateSpec/服务或 credential store |
| K11 分层与渐进披露 | W `ResearchStudio设计模式拆解与Workflow-Skill工程化模板-2026.md`（9 月更新） | 九阶段知识 → `Controller.context`；宿主执行、知识判断、确定性验证分别负责 | fixture-report 的九阶段 knowledge hashes 和实际加载；delivery context 在最终状态返回；transform/install 随上游 Skill 分发 | 已加载；导航文字不等于子 Agent 已运行，context 隔离也不是 OS 沙箱 |
| K12 科研诚信/纠偏 | W IntoTheUnknown（10-16）、SciΠvot（10-19）、RIDAR（10-24） | `experiment.md`、`review.md`；冻结评价器、结果/协议一致、全分母/失败、避免继承假设、数字追溯 | `test_science` 冻结设计/评价器、raw mismatch、漏 run、holdout、unsupported causal claim；fixture 保留 adverse/stopped | 已转为加载规则及可判定检查；未部署论文里的 LLM 违规检测或宣称其准确率 |
| K13 科研启发检索/回顾偏差 | W `科研启发文献检索评测与回顾偏差.md`（10-04） | `literature.md` → `science._validate_literature`；问题形成时间、候选首次可见、用途/困难负例/朴素基线 | `test_science` purpose/baseline/hard-negative、unknown spans、prospective postdated sources、仅登记不算阅读 | 已接线；不证明引文真正产生灵感或消除作者回顾偏差 |
| K14 文献身份、LQS、A/B/C/D | D `literature.md` 和本地 codex 适配 | `literature.md`；检索/核验/引用深度、unknown 输入、真实 gap、录用升级 | stage context；literature packet 检查核验和实际阅读/用途；G1 独立审阅 | 已加载；不把声望/总分/数量当科学有效性的替代 |
| K15 G1–G5 与 weakness routing | D `paper-writing.md` / `review.md` 方法及本地适配，P review/finalizer | `review.md` → `Controller.check_reviews`，按缺陷回 literature/experiment/figures/write | 最终要求各适用门及 R6 证据；fixture 按阶段与逐项合同检查后再 finalizer | 已接线；历史模拟分数不是外部接受，未知/未检查不能 pass |
| K16 旧知识的适用性修正 | D `codex-runtime.md` / `figures.md` / `structure.md` / academic examples | `venue.md`、`figures.md`、`write.md`；venue 预算替固定数量、真实统计单位替统一 mean±std、保真替自动 hedge | venue/science/prose 负例与 knowledge 加载 | 已加载；不照搬 50 页综述配额、必须凑 unresolved 或主观分数标尺 |
| K17 资源、成本与隐私 | P Skill/protocol/feasibility，D 本地 runtime 适配 | `intake.md`、`experiment.md`、`delivery.md`；实际授权/设备/unknown usage、私有材料范围和发布边界 | fixture 标 model_calls=0、remote_jobs=0；intake resources 结构检查；授权仍由真实宿主提供 | 已加载；无全局模型配置/凭证迁移，无云服务或后台研究启用 |
| U01 上游小入口与子命令 | 完整 MIT 上游 revision，所有 342 文件为基础 | 根目录 `.claude` 为 canonical，`paper.md` 新子命令，`scripts/transform.sh` / `sync-paper.py` 分发 | upstream 与 extension install/transform tests；各副本从 canonical 生成 | 已适配；并非旧工程的外挂快照 |
| U02 hooks/rollback/两类循环 | 上游 hooks、metric core、`orchestrate.sh` | 原子命令继续使用原协议；paper context 同时提供 plan/core/reason；论文 ledger 保留独立权限边界 | upstream test-hooks/test-orchestrator；论文工作不以 keep 授予 acceptance | 已保留；非 Claude 宿主的 hooks 能力按实际上游宿主适配披露 |
| U03 fork-and-flush | 上游 `fork-and-flush.md` 与 plateau verdict | `exploration.trigger/request/create_worktrees/select/promote`，从最佳 commit fresh contexts 分叉、择优 | `test_exploration` 固定/early schedule、真实隔离 worktrees 与最佳 commit promotion | 已接线机械 seam；宿主创建/继续 fresh-context agent，离线测试不证明真实模型表现 |

## 验证材料与科学边界

最终整合运行 `foundation/tests` 的 67 项测试，全部通过，含真实安装后删除临时
source checkout 再执行完整 fixture、同 Brief 的版本化返工、逐动作效果对账、
两份稿件错配、Unicode Git 路径、引用解析和来源包重建等回归。原始输出保存在
`runs/verification/foundation-tests.log`。原样本地 helper 的独立回归为 105 项通过，
4 项旧 checkpoint 集成测试明确不适用；新账本恢复由本分支的集成测试覆盖。

可复现入口为 `bash scripts/test-paper.sh`。完整同版本软件回执在
`runs/software-fixture-20261104-final/fixture-report.json`，含九阶段实际加载的知识 hash、
16 次计划运行与失败/提前停止/负结果、零模型调用、零远程任务、PDF/TeX/ZIP 和导出
manifest。其 `independent_model_review` 明确为 `not performed`；不能把脚本化 reviewer
packet 当作真实独立科学评审。早期样例因单次 TeX 编译未解析引用而被此版本替代，
现已完整构建并回归拒绝未解析引用。最终验证范围及剩余边界见 [VALIDATION.md](VALIDATION.md)。

## 不迁移的具体项目

未复制 Deli 私有 search_agent/call_api/registry/守护实现，因为公开源没有可运行代码；
按现有宿主能力执行相同任务。未迁移固定页数/图数/误差条/措辞和模拟评分硬指标，因用户
新增方法已经明确修正其适用范围。未迁移 PaperFlow browser UI、模型/凭证存储、graph
checkpoint、ER-LA/MPS/CUDA 服务和项目专用诊断器；它们不是可直接移植的论文知识，导入
会引入另一个执行所有者或未授权资源。相应通用方法（真实效果账、数据分母、官方模板、
统计图源链、逐项验收）已经进入本扩展，而不是以基础设施不同跳过知识融合。

既有运行和旧资产保留原执行版本。新格式没有承诺旧会话/检查点热迁移，未知版本拒绝
而非猜测重放。真实科研效果、跨模型评审、外部投稿与长时无人运行均不由离线软件验收证明。
