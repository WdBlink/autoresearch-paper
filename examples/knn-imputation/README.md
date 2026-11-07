# 一次真实的 research → paper 流程试跑

本例用于检查主 `$autoresearch` 入口的实际衔接。真实运行目录为
`runs/real-knn-20261104/`，数据、出版商全文、评审和交付包保持本地私有，
不随源码提交。它不是离线 fixture，也不代表期刊接收或外部专家审稿。

通用工程现已迁入主 Skill 的 `foundation/lib/production.py`、`experiments.py`、
`reviewing.py` 和公共 CLI。`control.py`、`index.py`、`finish_figures.py`、
`review_packet.py`、`deliver.py` 仅转调核心，不再实现另一套编排。
原 563fe7e 版本的精确脚本保留在历史提交和私有交付包中；当前这些桥接脚本的输入为
主流程规定的显式 packet，不再隐含读取某个 R2 文件。

研究问题是：对于缺失值输入的分类，先标准化再作 kNN 插补，与插补后再标准化，
在一个固定小样本集上有什么差异？选择 8 个 UCI 数据集、固定逻辑回归、
20% Bernoulli MCAR 和 5 个预先确定的配对种子，共 80 次主拟合。
真实数据与人为施加的缺失机制分别记录；合成数组只用于仪器控制。

## 本次实际证据

- 先依据官方材料比较 PLOS ONE 与 JMLR，再选 PLOS ONE；没有以范文篇幅冒充官方篇幅限制。
- 8 篇真实发表范文来自 2025–2026 年，53 图、54 表。每个图表记录问题、主张、
  证据位置、设计启示和局限；475 个分面或表格语义分块另作记录。
- 文献阅读由主 Agent 与真实原生子 Agent 完成，保存原 PDF/JATS、渲染页及逐项记录。
  自动提取不能代替视觉阅读；独立复核还纠正了主 Agent 对 S01 T13 加粗字体的误读。
- 80 次主拟合均完成，原始预测、40 组配对 split/mask、全部负结果均保留。
  独立 reviewer 重新计算全部分数，并额外复现 4 次真实拟合；额外拟合不计入主分母。
- 3 图、3 表、17 项已核验引用；内部阅读版与无嵌图的期刊格式版分别编译。
  Methods 与 artifact reviewer 均实际阅读完整 PDF，再对修订版复查。
- 宏平均变化约 +0.13 个百分点，5 个数据集为正、3 个为负。8 个数据集才是宏平均单位，
  40 次配对分割不是 40 个独立数据集。结论仅是固定条件下的描述性比较。

## 核心桥接与课题适配

| 文件 | 负责的机械工作 |
| --- | --- |
| `acquire.py` | 下载出版商 PDF/JATS、官方投稿规范及模板，保留来源 |
| `data.py` | 获取 8 个真实 UCI 数据集；Seeds API 不完整时用官方原始 ZIP |
| `prepare.py` | 构造本课题 intake、官方选刊比较和范文/图表计划骨架 |
| `control.py` | 导入核心 `lib.client`；路径解析和日志由公共 CLI 负责 |
| `evaluator.py` | 训练集拟合、配对 mask、真实预测与失败记录；拒绝覆盖原结果 |
| `assets.py` | 从全部结果生成案例表、配对变化图和宏汇总图 |
| `assets-v2.py` | 实际经过视觉修正的渲染器；旧版保留以核对修订 |
| `table_presentation.py` | 重放实际表注澄清；`--check` 与已评审定稿逐字节核对 |
| `finish_figures.py` | 转调核心 `image-export`，尺寸、DPI、模式由 packet 给出 |
| `literature.py` | 生成本课题文献登记、核验记录和 BibTeX |
| `manuscript.py` | 将真实作者片段与官方模板组装，调用受控编译 |
| `revise.py` | 根据实际 R0 报告回退并重放；保留冻结计划、旧稿和原始结果 |
| `revise_display.py` | 针对 R1 实际发现的跨页 URL 边框问题，生成不改正文的 R2 |
| `index.py` | 转调核心 `reading-index`；篇数、图表数取自实际输入 |
| `review_packet.py` | 转调核心 `assemble-review`；要求数、评审身份和版本均来自当前合同 |
| `deliver.py` | 转调核心 `deliver`；必须已有真实签发请求及对应宿主判断 |

数据集、80 次旧实验、特定绘图布局、正文片段及 S01/R0/R1 修订属于本课题的冻结记录。
其中的固定数字和修订文件名用于重现该研究，不是通用工作流配置。
新课题从主 Skill 的阶段 `production_steps` 调用核心工具，使用提供的实验记录器，
而不复制这里的历史评价器或修订脚本。通用表注已经直接修在核心统计 renderer 中。
研究判断、逐图逐表解释、实际写作与独立评审仍由宿主执行。

对新运行，应从主 Skill 读取当前阶段知识，依次使用公开命令：

```text
init → read-material / commit intake
venue-compare → ask-user venue → actual user answer → confirm-venue → venue-calibrate / commit venue
set-contract → approve → concrete plan → ask-user budget → actual user answer → confirm-budget → begin-round / commit plan
commit literature → execute / commit experiment
execute / commit figures → execute / commit write
bind-all → prepare-review → actual judgment → assemble-review / commit review
prepare-round → actual host judgment → deliver (apply, finalize, ZIP verification)
```

问答、单一预算与增额均遵循主流程的 [user-input](../../foundation/references/user-input.md)
和 [budget](../../foundation/references/budget.md) 契约。此例的历史运行不热迁移；
不能伪造答复来适配新入口。

精确 Brief、各阶段包、冻结 WorkOrder、实际调用及错误保存在本次私有运行目录；
轮次 request 和 decision 均放 `control/round-decisions/`，其后不改研究文件再 apply。
需要改已接受材料时使用 `rewind` 与新的版本/operation ID，不能直接重置控制状态。

本例的科学边界包括一个学习器、一个缺失率、目的性选择的 8 个数据集和原始行切分。
重复原始特征标签向量可能跨分区；这不支持新实体推广，也没有显著性、等效性或
普遍胜出的结论。作者、机构、利益冲突、公开归档地址及人类专家审阅仍待真实责任人补齐。
