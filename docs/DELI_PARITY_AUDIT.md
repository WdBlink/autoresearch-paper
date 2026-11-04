# Deli 流程与工程细节逐项审计

审计基线是本分支提交 `613e4e702c5b13f0c8a0a6d94da0537d8e110e9f`。
本轮审计用于纠正“知识已加载”被误写成“完整实现已验证”的判断，并为正在补齐的代码
指出具体完成条件。最终以本轮补齐后的源码、测试和回执为准，基线缺口不是新要求的替代品。

当前预算/问答契约已在后续修订中简化：选刊、首次计划预算及增额必须取得真实用户答复；
资源上限只在顶层 `budget`，默认 `{}` 无隐藏任务总上限，也不新增付费授权。
下表 D39–D41 对原 Deli 强制转向、文件上限及 15轮/30分钟/五次实验的描述是历史迁移记录，
当前实现将其保留为检查点/工作量建议，不作为停止门槛。准确现行规则见
[问答契约](../foundation/references/user-input.md)和[预算与退出](../foundation/references/budget.md)。

本 Skill 的目标是从问题、材料和实验推进研究，证据成熟后再产出论文。基线以 `paper`
子命令为总入口的产品表述不满足当前用户要求；本轮 canonical Skill 已将 `/autoresearch`
设为默认研究流程，`write` 为证据成熟后的阶段，原经典循环转为 `iterate` 辅助协议。本文件不把通用指标循环、主观判断、研究验收和期刊选择混成一个分数。

## 读取范围与状态含义

D 指 `/Users/wdblink/.codex/skills/deli-autoresearch/`。本轮读取其 `SKILL.md`、
`PROVENANCE.md` 和全部十五份 `references/*.md`，并检查四个脚本的公开命令、关键验证/
状态/恢复实现及四个测试文件的全部测试条目。精确字节身份由 `foundation/provenance.json`
记录；“逐项”指下列可观察条款，不承诺复制每一行实现或作者私有运行环境。

- **机械实现**：现有确定性代码能检查相应条件，且下列测试确实针对该行为。
- **宿主方法**：知识实际随阶段加载，宿主必须读原件执行判断；结构/hash 检查不能证明判断正确。
- **有依据适配**：保留目的、明确改变了实现/适用范围，不能称逐字或接口完全等价。
- **基线缺口**：`613e4e7` 尚无相应实现或行为回归；表内给出本轮补齐落点。必须由实际代码/测试关闭。

所有本文提及的测试按文件和函数名定位。列出测试不是自动宣称它已运行，更不是对真实
科研效果、多模型独立性或长时无人值守的证明。验收记录见文末。

## 输入、目标与选刊校准

| ID | 精确来源条款 | 基线实际实现与程度 | 缺口/适配及本轮完成条件 | 验证定位 |
| --- | --- | --- | --- | --- |
| D01 | D `SKILL.md:15`，`framework-original.md:24`；先读已有项目、复用成果、按scope持续工作 | `planning.intake` 和 `Controller.read_material` 检查材料hash/真实读span；`knowledge/intake.md` 加载已知结果/失败/授权 | 机械绑定+宿主判断；材料命令不是运行指令。不能因移植技能自动启动研究或收费调用 | `test_planning.IntakeTests`；`test_runtime` 精确Brief；`test_integration` 原始证据变更 |
| D02 | D `SKILL.md:17`；scope/angle/audience、类型、语言、格式、资源、验收 | 基线 Brief 硬检 question/venue/direction/type/resources/逐项清单；知识未逐项列全选题维度 | 已补入 intake 的选题与研究主线方法。缺值影响执行时需具体处理，不能声称已有自动研究选题执行器 | intake context加载；实际Brief字段与可行性测试。scope/angle/audience 的科学充分性仍需宿主 |
| D03 | D `SKILL.md:18`，`venue-calibration.md:22`；先确定venue/方向/预算/类型再写正文 | 基线 init 要求venue，venue→plan→write顺序；无“寻找比较期刊”执行入口 | **基线缺口**：候选journal比较、选择依据、用户已有选择/自主选择授权与后续profile一致性。本轮由 planning 候选/选择合同及CLI补齐；这是用户新增，不冒称Deli原文有自动selector | 新增候选遗漏/选择理由/选定目标不一致/无授权选择负例；尚不能由venue字段非空替代 |
| D04 | D `venue-calibration.md:41`；同venue同track同方向、默认8–15、最近两届 | 基线只要求三篇或sampling_limitations；校验同venue/方向理由/年份/重复PDF | **基线缺口**：8–15采样政策、时间窗与偏离具体说明。样本数经验不是期刊硬门，软件fixture不足不等于真实校准 | 基线 `test_missing_acceptance_evidence_or_direction_fails`；本轮8/15边界与偏离测试 |
| D05 | D `venue-calibration.md:43`、`:50`、`:114`；录用证明与原PDF身份 | 基线每sample必须有HTTPS来源/内容hash的acceptance_evidence；同一PDF不能多计 | 机械证据绑定+宿主核验来源。更严格拒绝无证明样本可接受，但不把“文件存在/HTTPS”当已证实录用；arXiv目标按预印本身份处理 | `test_missing_acceptance_evidence_or_direction_fails`、`test_fixture_must_not_be_mislabelled_real_venue_evidence` |
| D06 | D `venue-calibration.md:69`；measure/profile/design-template/check-plan/check-realize | 本地 `vendor/deli-local/scripts/venue_profile.py` 原样保留，planning导入纯函数；基线calibrate可调用但用户CLI没有完整可见子入口 | **基线缺口**：从研究入口能取得/执行样本测量、空白逐visual设计记录、聚合及检查的实际命令。独立helper可运行不等于新主线接好 | vendor `test_profile_and_plan_check_roundtrip`；planning实际PDF校准；本轮CLI外cwd测量/profile/realize链 |
| D07 | D `venue-calibration.md:94`、`:106`；pdfinfo总页数、References正文基准、caption/面板警告 | helper `measure_pdf/measure_text`、`build_profile`真实执行并将输出与stored文件比对 | 已机械复用。正文页基准混合只告警不代表可直接推导篇幅惯例；图表/子面板识别有启发式局限，要回PDF | vendor页数/caption/面板/编号/混合基准测试；planning `test_fake_measurement_or_stale_official_template_fails` |
| D08 | D `venue-calibration.md:118`；逐篇每张图/表的类型、claim、placement、notes及版面 | 基线design数组可少填，只聚合type/placement，未强制所有实测编号对应；“knowledge说要读”不等于检查完成 | **基线缺口**：实测caption集合→逐visual编号→问题/支持主张→统计单位/布局→PDF读证据的完整覆盖，缺/重复/错编号拒绝。本轮由planning补齐 | 新增漏一图、重复编号、空claim/notes、只填泛type、未读PDF反例；真实视觉理解仍属宿主 |
| D09 | D `venue-calibration.md:148`；median/p25/p75预算带、常见形态、question≠claim、must数据 | 基线原样helper `budget_band/check_plan`；snapshot与Brief visual IDs关联 | 机械实现+主张语义由宿主；依据计划或数据变化重做相关检查，不凑图型或硬造数量 | vendor `test_out_of_band_count_*` / `test_dominant_venue_pattern_must_be_covered` / `test_question_equal_claim_is_error`；planning冻结计划 |
| D10 | D `venue-calibration.md:32`、`:108`；官方page_budget与样本口径 | 基线校验官方规则/模板hash和class/options，但未计算官方页数硬限及refs/appendix口径 | **基线缺口**：page budget基准随profile/plan/write/review传播，会议硬限与期刊习惯分开；本轮planning补齐，禁止用混合正文口径放行 | 新增页数超限、base混合、不含refs/appendix边界、官方规则与习惯混淆测试 |
| D11 | D `codex-runtime.md:17`；模板实际编译、日志/字体/引用、最终PDF | `planning.write`固定官方class/options与依赖，`build_tex/rebuild_package`干净构建；导出含软件/源包/zip | 基线机械构建已接，宿主仍必须实际读PDF页面，不能以build=视觉pass | `test_planning` TemplateTests，`test_unresolved_citations_do_not_produce_an_accepted_pdf`，integration rebuild/export，installation删source后fixture |

## 文献、结构、实验与图表

| ID | 精确来源条款 | 基线实际实现与程度 | 缺口/适配及本轮完成条件 | 验证定位 |
| --- | --- | --- | --- | --- |
| D12 | D `literature.md:8`；多词召回、taxonomy查询、snowball和候选库存 | `science._validate_literature`保存search/candidates、primary spans、inclusion、用途和hard negatives；知识包含滚雪球和真实gap | 机械记录与实际检索工具由宿主。20–30检索词/200–500候选是综述经验，按批准scope/时间而非凑数 | `test_literature_preserves_purpose_baseline_and_hard_negative`、`test_registered_source_is_not_read_evidence`；真实检索未由fixture证明 |
| D13 | D `literature.md:15`、`:27`，`codex-runtime.md:50`；LQS/A–D/unknown | 基线知识只概述维度，catalog未强制完整LQS或引用深度schema | 已补阶段知识中的五维权重/7和5参考线/unknown/用途深度。按任务需要保存score inputs和深度，不将声望加权作为科学真值；自动LQS完整算法未迁移 | knowledge加载；任何研究采用LQS需具体输入/映射与缺项检测；不声称runtime已自动给文献评分 |
| D14 | D `literature.md:34`、`SKILL.md:175`；正式录用升级、每20条及时核验 | 基线包括source primary_checked和evidence文件，未有二十条核验节拍、BibTeX/引用计划关联 | **基线缺口**：citation batches/checkpoints、尾批核验、key→题名/作者/年/venue/DOI/arXiv→支持claim→原文证据、变化后重验；本轮runtime/交付合同补齐 | 新增21条未分批/漏key/旧版本/尾批缺失/不支持引用负例；primary_checked字符串不能独立证明来源真实 |
| D15 | D `paper-writing.md:55`，`codex-runtime.md:49`；80引用、每页三引用、新近/录用比例、taxonomy两篇 | 未机械强塞数量；最终included sources要求read及primary evidence，knowledge保留适用性 | 有依据适配：这些属于历史长综述阈值，写入task scope时才能成为本项目门；真实空白不造引用，关键反例不因分数丢弃。核验率不为假引用开后门 | literature/read-span负例和G1真实逐项判断；不宣称满足历史全部数量配额 |
| D16 | D `structure.md:8`、`:26`、`:33`、`:39`；章节功能、taxonomy、形式claim、比较已有综述 | 基线write有assertions/数字/范围校验；知识仅概述保真，未逐项保留结构方法 | 已补 `write.md` 结构与taxonomy/claim/既有综述比较方法。按真实论文/venue组织，不机械9章、MECE空格、theorem或固定段落模式 | `test_initial_draft_with_evidence_bound_numbers_passes` 与因果/显著/保真负例只检查部分内容；结构科学质量仍宿主审阅 |
| D17 | D `experiment.md:8`；claim/假说、独立/依赖/控制变量、预定统计 | `science._design/_experiment`检查冻结设计及可选evaluation hash、完整run集合/原始记录、暴露角色 | 机械实现覆盖当前受支持数据模型；方法优劣、效力分析、测量是否回答问题须由实际研究判断 | `test_frozen_design_cannot_change_after_results`、`test_evaluator_bytes_are_frozen`、`test_holdout_selection_and_seed_only_pairing_are_blocked` |
| D18 | D `experiment.md:17`；API/GPU真实执行、job/模型/config/seed/原始证据 | 扩展typed local actions render/compile/copy/validate，实验由宿主已授权工具执行并交记录 | 有依据适配：不复制不存在的Deli API/集群执行器；不能称fixture跑了真实科学API/GPU。远程作业ID/费用/未知态需实际执行器回执 | `test_raw_record_must_match_reported_measurement`、`test_operation_failure_cannot_become_scientific_negative`；fixture model_calls=0/remote_jobs=0 |
| D19 | D `experiment.md:23`，`codex-runtime.md:52`；天花板/地板/未显著/意外、最多五次 | 基线检查不明效果和完整结果；未机械追踪设计迭代上限/原因；knowledge已有不追显著 | **工程政策缺口**由本轮round/预算记录补；统计方案变化保留exploratory，不照字面“多跑直到显著/五次接受最好”。新假说另验，不自动消除承诺 | 新增预算/停止/设计变更记录测试；现有`test_missing_run_does_not_become_success_only_subset` |
| D20 | D `experiment.md:31`，`codex-runtime.md:101`；config/results/statistics/findings+summary，数据与排版分工 | 当前science raw→records→statistics→render链，artifact closure；摘要/finding质量仍host | 机械部分已接；无run不能填预测值，摘要要含purpose/results/limitations且保留负面/提前停止 | `test_failed_and_stopped_runs_count_with_penalty_and_summary`、`test_artifact_references_are_closed` |
| D21 | D `experimental-figures.md:7`、`:20`；问题选图、统计单位、配对、CI/SD/SE、全分母 | `science._statistics`按case配对并case内平均seed，支持均值+SD/SE/探索性normalCI，未支持估计器拒绝 | 机械已接当前限定；广泛图型和统计学知识加载不等于已支持bootstrap/任意模型/ECDF等。扩展时保留真实单位和失败口径 | `test_real_records_are_paired_at_case_level`、`test_wrong_denominator_is_blocked`、`test_unknown_estimator_does_not_fall_back_to_mean`、interval测试 |
| D22 | D `experimental-figures.md:32`、`:39`、`:47`；配色/轴/案例/精确表/最终PDF及证据链 | `_table/_svg/_pdf`和render trace数值sidecars重算，manuscript assertions/不利结果检查；无自动视觉理解 | 机械数值与版本检查+宿主实际页面审阅。不得假称已验证所有布局、色觉、语义/定性案例 | `test_plotting_values_caption_and_image_are_all_checked`、`test_pdf_is_recomputed_and_deterministic_when_matplotlib_is_available`、不利结果/数字关系测试 |
| D23 | D `figures.md:18`、`:31`；booktabs/mean±std/10pt/固定配色/固定数量 | 本地codex-runtime已明确修正；基线不硬编码多数旧风格 | 有依据适配：选真实venue模板和可读尺寸；覆盖率等目标型按实际目标，不一律bold最大；没有重复不造误差条 | venue/统计renderer测试只证明其实现；具体模板和PDF仍实查 |
| D24 | D `academic-prose.md:11`、`:24`、`:35`、`:42`；研究关系/读者顺序/局限/保真 | `science._validate_write`检查assertions值/单位/分母/条件/范围，revision facts，负结果与小样本披露；knowledge实际加载 | 机械覆盖部分关系，读者是否理解和引用语义需host。已补E01–E14方法索引，不能把示例数字和事实搬入稿 | `test_revision_fidelity_checks_relationships`、`test_prose_must_contain_bound_number_not_only_a_correct_sidecar`、`test_causal_and_significance_assertions_are_not_approved_from_descriptive_data` |
| D25 | D `academic-prose-examples.md:7`及E01–E14；按问题选例、读反例、保留事实 | 基线未载完整案例方法，仅概括相应几类；外部原文引用未复制 | 完整本地原则和E01–E14案例已按来源hash原样保留；write/review context加载完整原则和按需选定的最多两则完整案例；不为“人类化”全文反复改写，不用检测器验收 | context含索引；本地examples效果未在读者实验验证，不能声称全部案例效果已实证 |

## 评审、逐项交付与轮次工程

| ID | 精确来源条款 | 基线实际实现与程度 | 缺口/适配及本轮完成条件 | 验证定位 |
| --- | --- | --- | --- | --- |
| D26 | D `paper-writing.md:9`、`:30`；选题/草稿/深改/精修与弱点路由 | 八阶段主线+rewind/revise_orders可返工，knowledge说明回literature/experiment/figures/write | 有依据适配为研究证据先于write，不照旧Iter7才实验。已补原阶段目的/路由，不能把review→write重跑称全部research重跑 | `test_rework_versions_orders_without_changing_approved_obligations`、`test_rewind_preserves_history_and_invalidates_later_binding` |
| D27 | D `review.md:8`、`:18`、`:25`；R1–R5、独立评分/中位数、不同模型、防膨胀 | 基线一位declared reviewer与producer分离、逐项checks；未强制3–5角色/异模型或计算中位数 | 宿主方法+有依据适配；已补角色/评分/回归说明。若采用评分必须真实身份/逐维理由/中位数，不能捏造独立性或凑unresolved。fixture不证明真人/多模型审阅 | `test_binding_and_reviewer_identity_are_checked`；真实独立执行记录另验。历史评分不是外部接受 |
| D28 | D `SKILL.md:179`、`paper-writing.md:49`、`checkpoint.py:452`；逐门报告及G5阻塞 | 基线要求G1–G5/R6 pass与bound证据，survey G2有approved scope N/A；未读报告内容即可字符串pass | **基线缺口**：每门实测项/依据/失败/范围/当前版本的结构报告和历史regression；科学结论仍host，不拿file存在替逐门检查 | 本轮新增假的pass/缺测量/不适用无scope/旧report负例；现有integration缺项及高分不可覆盖 |
| D29 | D `plan-compliance.md:24`、`:39`、`:54`、`:87`、`:115`；R6输入、五类偏离、兑现率分母 | `planning.review_plan/review`用frozen snapshot、当前plan、PDF做机械audit，逐项r6 reason/location；基线只允许全fulfilled | 机械+host；已披露偏离不是fulfilled、未披露/缺快照阻塞。可以披露但仍不满足必交合同；改要求需要真授权，不能只让R6“解释合理” | `test_r6_omitted_item_and_rewritten_plan_fail_despite_total_score`、`test_r6_uses_bound_original_snapshot`；vendor计划改写/数字/旋转编号测试 |
| D30 | D `SKILL.md:105`、`:167`、`:180`，`codex-runtime.md:90`；每轮首次快照 | 基线只在plan提交时冻结一次，prepare_round不是轮前snapshot | **基线缺口**：begin-round保存本轮plan/起始证据、round ID/次数，结束判断绑定同快照，不能事后造“轮前” | 本轮新增两轮分别快照、途中计划变更、无快照R6与回放保护测试 |
| D31 | D `deliverable-contract.md:33`、`:85`、`:130`；批准清单、render、coverage、依赖、绑定 | `check_brief/check_orders/bind`覆盖每个ID、producer、typed actions、当前hash和manuscript literal insertion；重复visual asset拒绝 | 机械主要已接；本分支formal contract全部项视必交，optional探索放非必交outline，不可声称所有Deli optional/priority接口原样兼容 | `test_work_order_omission_unknown_action_and_coverage`、`test_fixture_identity_and_duplicate_visual_binding_are_rejected`、decoy/comments拒绝 |
| D32 | D `deliverable-contract.md:140`，`deliverable_contract.py:533`；逐项语义请求/增量复用/完整cross_check | 当前bind digest/checks覆盖所有批准ID、当前evidence hash与rationale，review前bind/稿插入校验 | 机械binding+host语义；当前全量review比Deli增量更保守，不能称已实现按未变项自动选择review。缺项/错绑/陈旧/内容unmet均阻塞 | `test_missing_or_stale_item_cannot_be_hidden_by_overall_pass`、`test_binding_and_reviewer_identity_are_checked` |
| D33 | D `deliverable-contract.md:154`、`deliverable_contract.py:709`；rerun/negative/revise_brief | 当前失败attempt/negative记录、revise_orders supersedes、原Brief不能削弱，改scope新run | 有依据适配；需记录原失败与新task原因。负结果只能通过原requirement审阅，不是自动豁免；范围修订不能伪造human receipt | negative/operation failure用例；`test_rework_versions_orders_without_changing_approved_obligations` |
| D34 | D `deliverable-contract.md:213`；未完成稿首页banner、完成情况/阻塞项 | 基线finalize拒绝缺项，但write阶段可生成无banner的非final PDF | **基线缺口**：草稿语义/首页标记、阻塞项与状态，最终包才可移除。开发fixture不等于真实draft评审 | vendor `test_a_draft_without_the_banner_is_rejected`仅测旧helper；本轮新入口缺banner及draft不能finalize负例 |
| D35 | D `SKILL.md:63`、`:182`，`checkpoint.py:23`、`:464`；八类交付证据 | 基线finalize有TeX/PDF/assets/全部已提交证据/clean build/zip，未强制bib/jsonl/verification/revision/snapshot八角色 | **基线缺口**：完整paper的八角色映射及真实类型/非空/hash/引用一致；research-only/局部修订按批准范围列角色，不能为过门临时缩减 | 本轮每角色缺失/空文件/错格式/声明passed不含产物/批准局部scope正例；旧checkpoint八角色回归不直接算新入口通过 |
| D36 | D `checkpoint.md:7`、`checkpoint.py:17`；唯一集成者、append-only发现/方向/日志 | 一个`.paper/control.json`由lock+atomic写，history/rounds/receipts保存原判断，rewrite不覆盖历史 | 已适配单ledger，不能再启动Deli多账本；未知老schema不热迁移，原分支/原运行仍原版读取 | `test_exact_approval_and_no_history_reset`、rewind/invalidation、idempotence测试 |
| D37 | D `checkpoint.md:23`、`checkpoint.py:331`；prepare绑定任务/状态/规则/证据，非空/zero-progress | 基线prepare/apply hash绑定，不同op参数冲突；prepare拒空证据 | 部分已机械实现；Deli允许早期零证据no_progress而不允许有进展/完成，可明确needs_input，不能逼宿主造占位证据 | `test_round_binding_idempotence_staleness_and_structural_pivot`；新增零证据/no-progress与verified拒绝 |
| D38 | D `checkpoint.py:427`、`tests/test_checkpoint.py:313`；稳定finding ID/revises、修订不计新发现 | 基线仅单finding claim/limitations/validation，duplicate claim拒绝，无finding ID与revision chain | **基线缺口**：稳定ID、原findings保留、revises已存在、计数不膨胀；语义重复仍host判断 | 本轮新增重复ID/修订不存在/修改结论不重计/回放不重复测试 |
| D39 | D `checkpoint.py:322`、`:317`，`SKILL.md:169`；last_seen≠last_progress，stale2 pivot/stale4 attention | 基线stale2 pivot、重复direction ID拒绝；未有last_seen/last_progress、attention字段 | **基线缺口**：begin只更新存活、实际验证进展才更新时间、四次attention。不能拿heartbeat做科研进度 | 原source `test_begin_only_updates_liveness` / `test_stall_pivot_attention_and_regression`；本轮新入口相同可观察回归 |
| D40 | D `SKILL.md:168`，`framework-original.md:111`；每轮≤5大文件、新TeX≤300行、迭代间验证 | 基线未有round文件/行数或异常说明检查 | **基线工程政策缺口**：登记轮内变更/验证与偏离理由，已有长文件不机械拆；不是给本仓库Python模块套300行 | 本轮5/6文件、生成TeX300/301、既有大文件说明、无validation不可verified回归 |
| D41 | D `SKILL.md:171`、`framework-original.md:80`；五次实验、15轮/30min、精修停滞预算 | 基线无session预算或phase score history，upstream迭代budget不能替论文轮次 | **基线工程政策缺口**：用户预算优先、记录实际预算/停止原因及phase目的，达到上限不等于质量通过；没有真实score不计算0.3 | 本轮实际轮数/时间/用户覆盖/停滞stop、stopped不变complete回归 |
| D42 | D `checkpoint.py:88`、`:121`，`tests/test_checkpoint.py:301`；结构大小上限、raw streaming hash | 基线read_json/read_bytes整体读，file_hash不流式 | **基线工程缺口**：结构JSON明确边界、raw不截断且stream hash，未知/超限返回具体错误 | 本轮超界JSON/大raw hash/NaN重复key/空白source；现有duplicate与nonfinite测试 |
| D43 | D `checkpoint.py:99`、`:138`，`tests/test_checkpoint.py:292`；路径/输出冲突/未知hardlink/原子写 | 基线拒absolute/.. /symlink、固定输出新版本、atomic+fsync；未拒未知hardlink | **基线工程缺口**：controller状态和产物hardlink边界，防外部别名误覆盖；单ledger无须仿造Deli原atomic-alias兼容 | 现有path/symlink/overwrite测试；本轮hardlink state/artifact与输出覆盖负例 |
| D44 | D `checkpoint.py:218`、`:533`，`tests/test_checkpoint.py:103`；已有历史缺state不清零、pending恢复冲突 | 基线init只检查control.json；有unknown attempt时拒重放/reconcile保留历史，export hash检测 | **基线工程缺口**：有controller历史/export却缺state要恢复而不是重置；单文件原子提交替代多文件pending，但须证明中断后恰好一次及不覆盖新证据 | `test_uncertain_effects_require_reconciliation_and_are_not_replayed`、`test_reconciliation_rechecks_previous_outputs_and_pure_validation`；本轮orphan state保护 |
| D45 | D `codex-runtime.md:30`，`framework-original.md:84`；L0/L1/L2、guardian权限与宿主依赖 | 本扩展无daemon/watchdog，不以timer存活代替进度 | 有依据不部署：原文没有L0执行代码，开发请求无常驻授权；只保留begin/last_seen与真实宿主native调度指引。不能宣称72h或三层可靠运行已验证 | 软件测试不证明休眠/退出/跨会话守护；本轮状态/恢复回归只覆盖本地边界 |
| D46 | D `framework-original.md:98`，`codex-runtime.md:9`；fresh context/目标探索/独立验证/资源调度 | upstream fork-and-flush + exploration request/worktrees/select/promote，原子scope排除ledger | 已机械适配fresh checkout与选优seam；实际fresh Agent/leadership由host，非OS sandbox。不能因写了文件说Agent已跑 | `test_schedule_and_early_replacement`、`test_fresh_worktrees_and_real_best_commit_promotion`；真实模型分叉未由离线验证 |
| D47 | D `SKILL.md:183`，`PROVENANCE.md:25`，`framework-original.md:129`；作者结果/自评/私有实现边界 | provenance区分本地增量与公开协议，六份本地helper/test原样hash固定，不复制Deli第三方整页 | 有依据不迁移作者生产结果、私有registry/API/72h事迹为本项目事实；不把其所有原文重新许可。方法适配不豁免本地自有增量融合 | provenance逐文件hash/目标hash校验；fixture明确software、0paid/remote、非独立模型审阅 |

## 基线缺口与本轮关闭记录

上面47行的“基线缺口”均描述提交 `613e4e7`，不是本轮补齐后的未完成清单。
当前检查分开记录实现、真实软件回归和宿主判断。代码/数据结构可以检查要求是否存在、
版本是否匹配、数值是否可复算；官方来源真实性、研究价值、视觉理解和语义审阅仍需
宿主实际读取材料，不能由本节测试或知识文件加载替代。

### 默认研究入口和规划校准

| 对应项 | 实际落点 | 实际检查/测试 | 当前结论 |
| --- | --- | --- | --- |
| D02/D03/D26 | canonical `.claude/skills/autoresearch/SKILL.md`、主 `autoresearch.md`、`iterate.md`；`scripts/research.py` | `test_workflow_v2.test_main_skill_enters_research_and_writing_remains_late`；核对真实Skill文案和CLI help | `/autoresearch` 默认整条研究路径，写作在证据之后；经典循环/编排作为辅助，已移除默认paper子命令入口 |
| D03 | `Controller.init/confirm_venue/set_contract/approve`，`venue_tools.comparison_report/validate_selection` | `test_undecided_venue_is_researched_before_the_final_contract`、`test_draft_can_record_a_real_wait_before_final_approval`；planning两个venue选择反例 | 未选venue可先进行只读intake/候选调查，真实选择后校准并形成具体合同，再批准实验；fixture核对选刊记录、历史draft与最终批准时序 |
| D04 | `venue_tools.sampling_report`、`planning.calibrate` | `test_eight_to_fifteen_is_the_actual_default`、`test_conference_sampling_names_the_recent_editions`、`test_exact_journal_dates_resolve_the_two_year_boundary`、old sample/fixture exception | 默认8–15、会议近两届/期刊明确截至日期的近两年窗口及偏差说明已结构接线；不是所有研究硬凑样本数 |
| D06/D08 | `Controller.tool` 的 compare/design-template/calibrate/publish/snapshot/audit/citation-check；`venue_tools.design_template/validate_design` | planning每visual集合、面板实测/语义、8份不同实际TeX→PDF样本正例；`test_snapshot_tool_and_lost_ledger_do_not_reset_history` | 用户入口可实际调用确定性工具，每图表/面板对应实测记录；内容理解仍由宿主，不以相等总数替逐项覆盖 |
| D10/D11 | `venue_tools.page_budget_report`、`planning.check_calibrated_plan/write`、构建器 | `test_page_budget_preserves_official_reference_appendix_rule`、`test_sample_habits_cannot_become_official_hard_limits`；template class/options及真实PDF测量/重建测试 | 官方要求、样本习惯及references/appendix计页口径传递；模板依赖和实际构建受检查。官方解释与最终页面仍需实际阅读 |

本知识审计独立运行 `test_planning.py`，33项通过，输出在
`/tmp/autoresearch-deli-parity-planning-tests.log`。它包含实际PDF测量及合成样本，
不证明真实期刊调研或录用状态的语义真实性。

### 引用、章节、八角色与质量门

| 对应项 | 实际落点 | 实际检查/测试 | 当前结论 |
| --- | --- | --- | --- |
| D13/D14 | `science._bib_entries/_citation_state`、`Controller.tool(citation-check)` | science引用计划/核验必需、身份/claim绑定、source变化过期、官方录用升级、LQS unknown/算术、每20条ordered batch与最终尾项核验 | BibTeX→citation plan→身份/原文→claim→批次记录机械链已接。文本/身份字段匹配不自动证明外部原件可信或主张语义正确 |
| D16/D24/D25/D40 的稿件部分 | `science._source_bundle/_sections/_validate_write` | section唯一ownership/实际claim位置、引用keys闭包、300行/既有大稿baseline例外、source-bounded survey与revision保真测试 | 稿件结构/版本关联、部分事实关系和行数受检查；taxonomy科学质量、十四类案例是否改善读者理解仍按宿主方法实查 |
| D28/D29 | `Controller.check_reviews`、`planning.review_plan/review` | 主控制器核对每门 reason/非空hash-bound evidence、当前requirement checks、G2不适用与批准scope；planning的R6原快照/遗漏/改写反例 | G1–G5/R6的当前证据和理由不能缺省；总分不豁免缺项。实际专业判断不冒称自动验证，R6也不替代逐项交付合同 |
| D35 | `science.validate_delivery/_validate_delivery`、`Controller.finalize` | science八角色/snapshot闭包/初稿不造revision历史；workflow最终packet包含全部八角色；finalizer重新调用该检查并干净构建 | source/pdf/bibliography/citation_plan/citation_verification/review/revision/snapshot本体及当前版本闭包已接。角色文件存在不等同真实独立科学审阅 |

本知识审计独立运行较早的同轮 `test_science.py` 46项通过，输出在
`/tmp/autoresearch-deli-parity-science-tests.log`。之后science_checks报告新增尾项回归后的
47项通过。尾项疑点的反例为
`test_final_tail_citation_requires_individual_identity_and_claim_verification`：二十一条中
前二十条有batch、全部逐条已核验的正例通过，末条身份或claim未解决时拒绝。整20条
批次节拍与最终全部引用逐条核验是不同条件；该疑点不是原有漏检漏洞，不应虚称修复。

### 每轮、状态、停止与恢复

| 对应项 | 实际落点 | 实际检查/测试 | 当前结论 |
| --- | --- | --- | --- |
| D19/D30 | `Controller.begin_round/prepare_round/apply_round` | `test_round_start_captures_plan_before_changes_and_reads_are_not_progress`、`test_r6_round_report_must_be_real_and_bind_both_plan_versions` | 每轮起点有真实计划/文本资产快照，不能只复用初始frozen plan；途中承诺变化要有绑定该round及两版plan hash的实际R6报告 |
| D37/D39 | durable `pending_round`、state/rules/evidence/current-document指纹、独立judgment通道 | `test_round_prepare_cannot_be_forged_or_applied_after_workload_changes`、`test_cli_judgment_channel_is_excluded_from_workload_but_cannot_be_an_artifact`、`test_heartbeat_does_not_invalidate_prepared_research_evidence` | prepare请求必须由当前controller实际签发记录；重算摘要不能伪造请求。判断通道不混入工作负载/产物；仅存活更新不冒充进展也不使原证据失效 |
| D37 | 零证据/no_progress与draft等待 | `test_draft_can_record_a_real_wait_before_final_approval`、round无进展正例 | 真实缺输入可在无最终批准和无虚构证据时记录等待；不能以此记录verified progress或跳过批准 |
| D38 | finding稳定ID/`revises`/append-only历史/总计数 | `test_finding_revision_keeps_identity_and_does_not_invent_limitations` | 修订有既有ID链，不重复计新发现；允许真实空limitations，避免为字段造局限。结论是否语义重复仍由宿主核对 |
| D39/D41 | `rounds.policy/stop_reasons`、begin/apply/execute/rewind边界 | `test_session_stop_four_stale_attention_and_finding_revisions`、`test_experiment_limit_applies_even_when_caller_uses_a_later_stage`、`test_round_budget_cannot_be_reopened_by_rewind` | stale2结构pivot和stale4 attention、session/experiment预算及后期停止已接；rewind或换stage不能绕过相同预算，停止不成为complete |
| D40 | `rounds.documents/workload` 与apply | `test_round_workload_limits_new_tex_and_scientific_code`、science的既有大稿例外 | 支持文本资产包括科研Python/JSON/YAML/CSV/shell等，不仅TeX。六个大文件需具体偏差说明；新增TeX超300行拒绝继续，既有大稿保留需说明，不机械拆稿 |
| D42/D43 | `read_json`16MiB、流式`file_hash`/工作负载扫描、路径及link保护 | `test_structured_input_size_and_hard_links_are_refused`；原路径/symlink/覆盖/重复JSON/NaN反例，核对实际流式代码 | 结构化输入有边界，raw文件指纹不靠一次性全部读内存；未知hardlink、越界和symlink拒绝。未声称做过通用吞吐/内存benchmark |
| D44 | 唯一controller的`checkpoint.json` durable最新副本、load一致性、recover | `test_snapshot_tool_and_lost_ledger_do_not_reset_history`、`test_recovery_keeps_post_export_rounds_and_pending_judgment`、draft后lost-controller恢复 | 丢失control不允许init清零；recover读取最新checkpoint，保留导出后的round/operation及pending请求，不把旧export当最新运行状态。未解决效果仍待对账，不盲重放 |
| D34 | `Controller.draft_preview`、真实PDF水印、非final路径/状态 | `test_draft_preview_is_marked_and_lost_controller_can_recover`实际pdftotext读到DRAFT并核对not_delivered | review draft与最终包区分，水印和bound数量可验证。具体科学未满足内容仍需从当前要求/绑定/review上下文读取并随交付说明，不能把通用pending文字当逐项诊断 |

本知识审计独立运行 `test_workflow_v2.py`，实际17项全部通过，耗时12.235秒，
输出在 `/tmp/autoresearch-deli-parity-workflow-v2-tests.log`。本次suite包含真实的完整
离线研究fixture、选刊准备→合同批准→八角色最终包、真实PDF水印、轮次故障和恢复。

另以构造的时间/轮次状态直接调用 `rounds.stop_reasons`，六项检查通过：默认三十分钟
停止、用户较长policy覆盖、超过十二次精修、连续两次已声明小增益、已声明目标分数、
缺分数时不捏造小增益。这是规则探针，不是等待三十分钟的真实科研运行，也不是模拟
得分效果验证。

## 关闭结论与保留边界

基线所列工程缺口已分别有当前落点和上述证据；不再用“阶段知识已加载”作为其唯一
完成依据。后续整库/分发检查以主集成最终同版本回执为准，本审计不借用旧46项结果
宣称新入口已经全库通过。

保留为宿主的部分是有意分工：选题/venue fit、官方来源真伪、每图表的语义与视觉
理解、统计方案是否回答研究问题、引用是否真正支持主张、独立审阅的真实执行和
科研主张有效性。它们已进入正确阶段方法及证据合同，但软件fixture不能证明它们已在
真实项目执行。真实付费模型、远程计算、期刊投稿、跨模型评审和长期无人值守均未由
这些测试触发或证明；原文作者的私有实现、生产统计和模拟分数也未转成当前事实。


### 完整写作材料的最后补齐

`foundation/references/writing/academic-prose.md` 和 `academic-prose-examples.md`
为用户本地自有增量的原样副本，并更新了 provenance 的 copied_verbatim/目标路径。
`writing.guidance` 在 write/review 自动加载完整原则和索引，`context --writing-case E07`
加载完整正反例，最多一次两例。`test_complete_local_prose_guidance_and_selected_cases_are_available`
以及完整fixture中的E07加载断言验证了实际接线。它们是教学规则，未将示例数字/事实当本稿结果。

`draft-preview` 现在还返回 missing_requirement_ids、pending review、未决效果、当前过期证据
与round checkpoint blockers；这些是实际结构/版本诊断，不能代替针对科学主张的独立意见。


### 最终集成回执

本轮当前 `foundation/tests` 全部120项通过；8份真实生成PDF的规划测试包含在内，
另有从未定venue开始的两类完整fixture。新source-synthesis端到端测试证明综述可以用
核验来源主张/证据图表到最终八角色导出，无需虚构实验；其不适用阶段不消耗实验轮。
实验轮预算也计入同一round中已经完成的experiment步骤，不能靠反复rewind延后计数。

所有生成分发、安装映射、来源hash及六套上游回归的实际结果和跳过分支见
[VALIDATION.md](VALIDATION.md)。其中主入口提问接口映射曾被原installer断言捕获，
修复后18/18通过。没有用删除原测试来宣称入口迁移完成。
