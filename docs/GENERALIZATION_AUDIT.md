# 真实试跑修复回收：主 Skill 与课题适配的边界

2026-11-04。审计起点为 `563fe7e`：上一次真实研究已交付，但当时只有委托授权和部分
指南进入核心；路径处理、媒体导出、索引、评审包拼装及交付串联仍主要写在 kNN 示例里。
本次将这些稳定步骤接入主入口，并保留原研究的冻结结果与历史运行时。

## 主流程现在调用核心实现

主入口是 `.claude/commands/autoresearch.md`，Codex 副本为
`.agents/skills/autoresearch/autoresearch.md`。`context.production_steps` 和
`paper/references/production.md` 指向已存在的执行接口，不要求日常 Agent 重写脚本。

| 试跑暴露的问题 | 当前核心责任位置 | 默认消费者 |
| --- | --- | --- |
| JSON 输入混淆 cwd/run 路径 | `foundation/scripts/research.py:input_json` | 所有公共 JSON 输入参数；歧义时要求绝对路径 |
| prepare 后写日志使摘要改变 | 公共 CLI trace；`Controller.prepare_round/apply_round` | CLI 自记外部日志、保存保留目录请求；apply 默认用实际签发请求 |
| 逐图记录索引写死篇数和总数 | `production.reading_index`、`planning.venue` | `venue-calibrate --publish` 生成并在接受时重算；链接可随包迁移 |
| 输入下载与缺依赖临时处理 | `production.fetch_sources/environment` | intake/venue/plan 的来源与实际解释器探针；不自动安装或猜列 |
| 异常丢失运行终态 | `lib.experiments.ExperimentRecorder` 和生成的记录模板 | 从冻结 design 派生完整网格，保留 attempted/failed/stopped；普通异常不能变成科学零分 |
| 最后分数完成后的操作失败仍可能被接纳 | `science._experiment` | 明确失败的 execution_status 阻止统计，即使所有 score 已存在 |
| 通用表注暗示独立性、无失败仍解释惩罚值 | `science._caption/_pdf` | 所有核心 statistics 渲染；SD 与 CI、可行分数范围分开 |
| DPI 对象不能序列化、规格写死 | `production.export_image`、注册动作 `export_image` | 由当前 venue/task 传入模式、DPI、尺寸、大小；实际数据归一化并复核像素 |
| 阅读与投稿格式、副本浮动体、链接边框 | `production.prepare_tex`、注册动作 `prepare_tex` | 显式选择保留/删除图、内联输入、图注位置、链接边框及边界标记 |
| 只用一种渲染方式漏看 PDF 链接框 | `production.inspect_pdf` | Poppler 含注释渲染，辅以可用的字体 span/链接对象；不会自报已视觉审阅 |
| 外部库警告混入 JSON stdout | 公共 CLI 输出边界、当前 PyMuPDF 导入 | 第三方诊断进入 stderr；调用方能严格解析 stdout |
| 复合姓及内部元数据进入参考文献 | `production.bibliography`、`science._bib_authors` | 用显式 given/family 或 JATS；检查器理解 BibTeX 逗号顺序，不要求人工改造已核验身份 |
| 年精度被迫编码成某一天 | `science.publication_bounds` | 直接接受年份；按时间区间判断是否可称 prospective，不伪造发布日期 |
| 评审包写死两个 reviewer、9 项、R2 | `lib.reviewing`、`prepare-review/assemble-review` | 当前合同生成待审模板、复制已绑定 hash、计算 R6 和完整八角色快照；独立判断由实际 reviewer 提供 |
| 逐项绑定和最终关闭需要临时循环 | `bind-all`、`deliver` | 批量绑定按子操作恢复；实际最终判断之后程序连续 apply、重建、导出和核验 |
| 返工前手工保存基准 | `rewind --preserve`、`revision-record` | 控制器复制受影响的已接受基准，再按实际 before/after/reason 生成版本记录 |
| ZIP 只核对目录、导出 runtime 少协议 | `finalize/verify_export` | 新包包含 upstream 协议；核验 ZIP 全文件集合、CRC 和字节 hash |

`reviewing` 不选择 reviewer 数量，不返回虚构的 pass。它检查实际身份、请求摘要、每项
语义判断和未关闭 finding；再从接受阶段推导 source/PDF/BibTeX/引用计划与核验路径。
它不会从文件名猜“哪个 R2 是最终版”，也不制造初稿或修订历史。

`lib.client` 是 Python 适配的薄传输层。示例中的 `control.py`、`index.py`、
`finish_figures.py`、`review_packet.py`、`deliver.py` 已改成核心调用桥，不再维护
一套路径解析、计数、hash 拼装或交付编排。

## 继续留在课题适配中的内容

8 个 UCI 数据集及 Seeds 原始列映射、20% MCAR、5 个种子、两条 kNN/逻辑回归流程、
其预定统计口径、具体论文、图表布局和 S01 的阅读纠正都是这项研究的事实。
它们保留在案例和原证据中，不作为新研究的默认数据、模型、图表数、评审数或修订文件名。
`table_presentation.py` 只用于核对历史稿；其通用表注修复已直接进入核心 renderer。

核心代码中没有该课题名、数据集名、DOI、`context-review-r2`、固定 9 项或 80 次的分支。
现有两条件 paired-case 数值接口仍是明确的适配范围；非实证研究继续走已支持的来源综合
路径。不能把这个数值适配器宣称为所有科研设计的唯一统计协议。

## 实际验证的范围

1. **原真实材料重放**：通过安装态 `.agents/skills/autoresearch/paper/scripts/research.py`
   从 `/tmp` 调用核心 `artifact`。8 篇得到 53 图/54 表/475 分面或分块；另一组 2 篇
   得到 15 图/5 表/37 分块。重算原 80 条结果，统计对象与旧版相等，数值表主体字节相等。
   依据原来已执行的真实独立评审组装 9 项包；故意改旧 binding 后拒绝，已成功的包未覆盖。
   另从真实 JATS 姓名组件重建 17 条引用的 BibTeX，保留旧计划与核验身份，通过原引用
   合同校验。首次脱离接受历史单验时缺少 JATS 证据声明，被正确拒绝；补入原控制器本就
   提供的接受历史后通过，未放宽校验。真实 HTTPS PDF 下载与原 hash 相同，第二次调用
   校验后复用缓存。
   这是原证据的工程重放，没有新增实验或冒称新一轮科学评审。
2. **独立前向使用**：新上下文只拿主 Skill 与最少原材料，不读取 examples。在另一工作
   目录处理 3 篇真实论文：10 图/18 表/22 分面；导出 RGB 300dpi 与灰度 600dpi 两种图，
   保持各自原像素。无嵌图、表格内联副本编译成功，从 ZIP 移位后再次构建成功。实际
   查看原稿及副本的问题页；15 个原输入 hash 保持。没有新写工程算法。
3. **前向发现后的定点回归**：旧库导入曾污染 stdout。修复后，无 `--out` 兜底也能严格
   `json.loads(stdout)`，stderr 为空，返回产物 hash 匹配。没有把这次定点检查写成又完整
   跑了一遍前向任务。
4. **不同形状与失败验证**：默认集成 fixture 现在实际走 reading-index、bind-all、
   prepare/assemble-review 和 deliver；4 项交付、1 篇样本。记录器另用 3 case/1 seed
   的网格测试普通异常、协议定义的测量失败及最后分数后的失败。检查陈旧判断、未关闭
   finding、透明度丢弃、来源中途失败、包含文件变更及 ZIP 额外成员都不能伪装为成功。

前向使用中的源稿副本保持作者原文；因此原稿“图已嵌入”的编辑声明也会被原样保留。
格式工具不代替作者修订这句话，也不由此认定副本投稿合规。完整写作/评审仍须核对实际
变体的文字、图注及身份声明。部分材料操作可直接使用系统编译工具；完整主流程的编译
由注册的 `compile_tex` 动作负责。

实际记录位于 `runs/generalization-20261104/`：`replay-v2/common/RESULT.json`、
`forward-use/REPORT.md`、`forward-use/REGRESSION.json` 及 `checks/`。
仅声称上述覆盖；没有重新运行整个新课题、外部人类审阅或取得新的科学接收结果。
本轮单独使用一次独立上下文执行者，模型 token/费用无可用计量，不报告性能提升比例。

最终执行 `bash scripts/test-paper.sh`：核心 140 项通过；Deli helper 109 项中 105 通过、
4 项可选依赖跳过。维护/分发检查 53/53；上游 342 个基线路径完整、315 个原样、27 个
已声明补丁；Skill 格式与 diff 检查通过。这些软件检查与上面的真实材料、真实前向使用
分别报告，不以合成 fixture 冒充新的研究或科学评审。

## 历史状态和分发

旧研究、回执和原 ZIP 不覆盖。其 563fe7e 运行时已固定保存在
`runs/runtime-pins/563fe7e/`；若要读取该旧 `.paper` 状态，用这个旧实现，不静默改
implementation hash。新主 CLI 的纯导出核验和状态自由 artifact 操作不需要迁移旧状态。
新能力同步到 Claude、Codex、OpenCode、Muse、pi 及插件分发；不修改个人全局技能配置。
