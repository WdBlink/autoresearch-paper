# 主入口真实课题试跑：kNN 插补顺序

2026-11-04，本次真实课题已从主入口跑到内部审阅交付，最终状态 `delivery`、无 stale、
无未关闭轮次。两位原生独立 reviewer 的 R2 均通过，9/9 交付要求和 6/6 原图表承诺兑现。
这证明本课题的流程实际走通，不表示任意课题的一键完成或期刊接收。

本地运行 `runs/real-knn-20261104/`。通过主 `$autoresearch` 的
`scripts/research.py` 执行，未调用旧 autoresearch-paper Harness。
运行材料和 CLI 传输记录分别位于上述目录及同级 `real-knn-20261104-cli/`，均不进 Git。
本文记录真实流程证据，不把 fixture、编译成功或 reviewer 名称当作科学审查。

## 实际研究与证据

题目：*Scaling before or after k-nearest-neighbour imputation: a paired comparison
on eight public classification datasets*。

比较 `KNNImputer → StandardScaler → LogisticRegression` 和
`StandardScaler → KNNImputer → LogisticRegression`。8 个 UCI 真实数据集为
Iris、Wine、WDBC、Ionosphere、Sonar、Glass、Seeds、Banknote，150–1372 行、4–60 个特征。
对每个数据集使用 5 个预先固定的配对种子，70/30 分层行切分，训练/测试特征独立施加
20% Bernoulli MCAR；所有转换仅在训练集拟合。真实观测数据与人工缺失机制分别说明。

80 次主拟合全部完成，保留 80 份原始预测和 40 份配对 split/mask。
独立 reviewer 从预测重新计算全部分数，并对 WDBC/Glass 的一个种子、两条流程额外复现
4 次拟合，预测 CSV 相同。这 4 次是审计复现，不计入主实验分母。

先平均同一数据集的 5 个种子，再对 8 个数据集等权平均：baseline 84.716970%、
candidate 84.847635%，配对变化 **+0.130665 个百分点**，数据集变化的样本 SD 为
0.847497 个百分点。5 个数据集变化为正、3 个为负，负结果全部保留。
没有统计显著性、等效性、因果机制或普遍推荐结论。重复种子不是独立数据集；原始重复
特征标签向量可能跨行分区，因此也不声称新实体推广。

## 选刊和 8 篇范文

先保存官方 PLOS ONE 接收标准、投稿规范和原始 LaTeX 模板，及 JMLR author-info，
比较研究范围、贡献尺度、文章类型和可获得的直接范文。选择 PLOS ONE 作为格式与
研究表达的目标，不把选择等同于适合录用的保证。未查明的费用和处理时长明确为 unknown。
PeerJ 页面返回 JavaScript 外壳，未被当作已验证的候选证据。

官方规范没有篇幅、图数及 supporting-information 数量上限；样本的页数/图数/表数
分布只是设计参照。本课题预先规划 3 图 3 表，未为凑范文数量增加无证据图表。

| ID | 出版商 DOI | 日期 | 图 | 表 | 已记录分面/语义分块 |
| --- | --- | --- | ---: | ---: | ---: |
| S01 | 10.1371/journal.pone.0359843 | 2026-10-12 | 4 | 16 | 4 |
| S02 | 10.1371/journal.pone.0359577 | 2026-09-29 | 3 | 6 | 5 |
| S03 | 10.1371/journal.pone.0320105 | 2026-07-27 | 7 | 4 | 14 |
| S04 | 10.1371/journal.pone.0343619 | 2026-03-26 | 10 | 5 | 16 |
| S05 | 10.1371/journal.pone.0339580 | 2026-02-24 | 7 | 3 | 2 |
| S06 | 10.1371/journal.pone.0335852 | 2025-11-20 | 8 | 1 | 23 |
| S07 | 10.1371/journal.pone.0334125 | 2025-11-07 | 14 | 10 | 396 |
| S08 | 10.1371/journal.pone.0319784 | 2025-05-12 | 0 | 9 | 15 |
| 合计 | 8 篇，最近两个期刊年份 | | **53** | **54** | **475** |

475 包含复合图分面及表格语义分块，不是 475 张独立图片或 475 项独立科学结论。
逐项记录在 `venue/analysis/S01…S08.json/md`；原 PDF、JATS、元数据及发表证据在
`venue/samples/`，实际阅读页在 `venue/rendered/`。
每个图表均记录 question、claim、evidence、type、placement、design_takeaway、limitations，
复合图/表另保存分面记录。主 Agent 与原生子 Agent 实际查看渲染页；数量再与 JATS 对照。

这一步发现了自动提取的边界：未编号/大写分面漏检、图注边界、S05 T3 首次正文提及页
与实际表页不同、S07 F14 两个未运行空格。记录保留测量值和人工观察页，不伪造零值。
独立审查又纠正了主 Agent 将 S01 T13 的 XGB 读为加粗的错误；实际加粗的是 SVR。
S01 T14 的另一处数值与加粗排名不一致则仍保留。这说明阅读记录同样需要独立复核。

## 实际断点、处理及回归

| 位置 | 真实现象 | 处理及证据 |
| --- | --- | --- |
| 主入口授权 | 精确 Brief 人工批准不能真实表达用户已委托选题/选刊和完整执行 | 增加可选 `--authorization`，绑定原指令文件/hash/原句/scope，记录委托决策者；没有捏造用户逐字批准未见 Brief |
| 数据获取 | Seeds 官方 API 的 data_url、target_col 和维度不完整 | 保存原 API，以官方原始 ZIP 解析 7 特征+类别，保留原档/派生 CSV hash |
| 范文工具输入 | 第一次 design-template 缺 artifacts 被拒绝 | 补齐真实 PDF 声明，保留原拒绝；不放宽校验 |
| 范文理解 | 页码/分面启发式不能覆盖实际版面；主 Agent 也会误读 | 实际看页、结构化纠正、独立字体复核，保留旧记录与理由 |
| 环境 | 首次控制探针缺 pandas | 在隔离环境补足依赖；正式结果之前冻结环境，未当作实验结果 |
| 评价器 | 结果前独立审查发现异常路径缺少终态记录 | 冻结前修为逐槽记录 attempted/failed/stopped；4 个故障探针验证；操作失败不当作科学零分 |
| 轮次衔接 | prepare 后客户端把 response 写入研究文件，apply 因摘要改变被拒绝 | 传输日志移至 run 外；request 与 decision 均用保留控制目录；实际轮次重新通过 |
| 客户端路径 | 首次修订传入 run-relative `--packet`，而 CLI 该参数读文件系统路径 | 薄客户端明确归一化 JSON 输入路径，保留中间证据并从实际失败位置续跑成功 |
| 图表渲染 | 方法图箭头穿字；规范表脚注有通用口径歧义 | 保留原渲染器及图，版本化修订布局/表注；数值表主体字节不变，配对变化全保留 |
| TIFF 元数据 | Pillow IFDRational dpi 无法直接 JSON 序列化 | 导出清单将 dpi 转为实际 float；独立核对 RGB、300dpi、字节/像素和字体 |
| 引用 | 复合姓被 BibTeX 错拆、JMLR 定位缺失、内部校验注进入读者版 | 依据原 JATS 姓名分量修正 Van Calster；补官方卷期页；年精度说明保留在工程元数据 |
| 方法表述 | “标签从未传给插补器”不符合 Pipeline 实际接口 | 独立 spy 确认会传入但 KNNImputer 忽略；改为目标列未作为插补特征，未改实验 |
| 投稿和阅读 | 投稿规范要求不嵌图；正文评审又需看实际图 | 保留两份明确标识的 PDF 和独立 TIFF；修正 Fig1 图注首次引用顺序及 Results 浮动图位置 |
| PDF 显示 | R1 跨页 URL 的青色链接框压过页脚；PyMuPDF 未显示而 Poppler 显示 | 两位 reviewer 独立复核原 PDF Link/Border/Rect，R2 用 `hidelinks` 保留可点击链接、隐藏边框，再编译复查 |

真正改变 controller 的是委托授权记录；其余分别是输入错误、环境、客户端位置、课题
评价器、视觉阅读和输出格式的具体问题，不统称为核心引擎缺陷。所有返工使用
`rewind`、保留原冻结计划、追加 WorkOrder/新输出路径、重新绑定和实际复审。
文献/版面修订重新接受 experiment 阶段只是重验同一批证据，没有新增或筛选主实验。

## 验收与剩余边界

当前已实际运行的基础检查为 foundation 122 项通过、Deli helper 109 项中 105 通过、
4 项可选依赖跳过。它们用于保护修复；这次研究流程是否通畅主要由实际来源、实验、
PDF、原生独立审阅和最终导出证据判断。
维护检查另有 53/53 通过，使用排除私有 runs 的临时源码副本和模拟 Git/GitHub 工具；
没有真实推送或发布。上游基线验证 342 个路径全部存在，315 个字节不变、27 个为已声明补丁。

实际交付为 `delivery/export-real-knn.zip`，24,790,411 字节、466 个文件，包含 430 个
声明产物、34 个 runtime 软件文件以及 manifest/control。八类角色均已接受：源码、
PDF、BibTeX、引用计划、引用核验、独立审阅、真实修订身份和版本快照。
`software_fixture:false`，finalizer 返回 `internally_reviewed`；verify-export 返回 `verified`。
从复制出的导出资产实际重建了 TeX，重建 PDF 的提取文本与当前已审阅版完全一致。
对 ZIP 另核验了 CRC、无重复项、完整文件集合及全部逐文件字节 hash，均通过。

内部阅读版 `main-r2.pdf` 13 页；无嵌图期刊格式版 `submission-r2.pdf` 12 页，另附
3 份实际 RGB 300dpi TIFF。R0/R1 的 revise 报告及旧稿均保留，未被改写成 pass。
R1 的全部 25 页已逐页视读；R2 仅改变链接边框，实际视读 4 个受影响页面，并将
全部 25 页的文本、文字 geometry、无注释 raster 与 R1 逐页对照相等，两位 reviewer
均明确了证据复用范围，未冒称又完整视读一遍。

实际入口：

- 范文导航：`runs/real-knn-20261104/venue/analysis/INDEX.md`
- 当前内部稿：`runs/real-knn-20261104/delivery/export-real-knn/artifacts/manuscript/main-r2.pdf`
- 期刊格式稿：同目录 `submission-r2.pdf`
- 结构化审阅：`runs/real-knn-20261104/review/packet-r2.json`
- 交付清单：`runs/real-knn-20261104/delivery/export-real-knn/manifest.json`
- 断点时间线：`runs/real-knn-20261104/breakpoints.jsonl`

仍需宿主真实判断的环节是选题/选刊、文献支持范围、逐图解释、写作和科学评审。
脚本负责采集、计数、hash、配对实验、统计/制图、编译、逐项绑定、恢复与导出。
本次同模型家族的独立上下文 AI 评审不代表跨模型或人类专业审查。
作者身份、机构、资金与利益冲突、正式公开归档地址和外部投稿均未虚构或执行。

脚本边界及复用入口见 `examples/knn-imputation/README.md`。
