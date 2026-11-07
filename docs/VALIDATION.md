# 本分支软件验收

验证于 2026-11-04（Asia/Shanghai），环境为 macOS、Python 3.14.7、
Node v26.8.1、Matplotlib 3.11.0、TeX Live 2026 / pdfTeX 1.40.29。
本轮针对 Deli 的逐项复核及默认研究入口，不沿用最初基线的“67项通过”作为新增功能证据。

| 检查 | 结果 |
| --- | --- |
| 科研扩展 | `foundation/tests` 120 项通过；实际PDF采样、两类端到端、独立安装、逐项要求、引用、返工及恢复故障注入 |
| 用户本地原样 helpers | 109 项中105通过、4项旧 checkpoint 集成明确跳过；未启动第二个状态机 |
| 上游 orchestrator | 391/391 |
| 上游 hooks | 267/267 |
| 上游 installer | 18/18；Muse CLI 未安装，外部 validator 分支明确跳过 |
| 上游 regression | 65/65；15命令为默认研究、iterate和原有13个辅助命令 |
| 上游 maintenance | 53/53；各分发生成无漂移、release只准备不发布 |
| pi extension | 81/81；pi-coding-agent types 未安装，类型检查分支明确跳过 |
| Skill结构及来源 | quick_validate通过；52份来源hash无漂移，8个原样副本字节一致 |
| 静态检查 | Python编译与 `git diff --check` 通过 |

当前原始输出保存在 gitignored 的 `runs/deli-parity-20261104-verification/`。
首次安装回归发现主入口精简后漏掉 Muse 的原生提问工具映射；已补齐 canonical
Skill，并重新 transform/安装验证至18/18；未删除或放宽原断言。

## 完整离线样例

以下两份实际执行记录均从未定venue开始，经过只读材料/候选比较、真实软件fixture
选择回执、校准、形成具体合同并批准、文献、证据、图表、正文、review、轮次检查点，
最后导出和从导出副本重建TeX。九阶段知识均被实际加载。所有问题、venue、范文和
文献都明确标为合成；实际模型调用、远程任务均为零，独立科学review未执行。

- `runs/deli-parity-20261104-empirical/fixture-report.json`：固定本地CPU程序，16次计划
  尝试、独立case内seed平均、保留失败/提前停止/负结果、可复算数值图表、两页PDF。
- `runs/deli-parity-20261104-survey/fixture-report.json`：明确批准的非实验综述范围，
  experiment及G2有理由地不适用，核验来源主张、证据示意图和分类表，没有实测结果、
  冻结evaluator或人工拼凑的数值实验，实验轮计数为零。

每个最终包都实际含source/pdf/bibliography/citation_plan/citation_verification/review/
revision/snapshot八类角色，附生成软件、证据、manifest和ZIP。初稿revision明确为
initial_draft，没有捏造修订。重新编译检查PDF文本，引用可解析；逐项绑定图表插入及
当前版本。另抽取两份PDF的文本并查看首页栅格，确认引用、结果范围、图/表实际可见；
这只是软件fixture抽查，不冒称真实期刊的整稿视觉验收。

安装独立性测试在临时Codex配置安装、删除临时源码checkout，再只凭安装包执行完整
样例。本轮没有改用户实际安装、全局配置或活动研究。分叉测试在临时repo创建真实
worktrees并快进有验证证据的最佳commit；未验证真实模型分叉效果或跨会话交接。

## 缺口关闭与实质边界

47项来源对照、当前实现和反例见 [DELI_PARITY_AUDIT.md](DELI_PARITY_AUDIT.md)。
本轮独立复核还关闭prepare伪造/后改文件、R6虚假路径、预算阶段绕过、旧导出覆盖
最新checkpoint、draft等待错误要求最终批准和pi/Muse入口路由等问题，均有相应回归。
最新checkpoint与control是同一个状态所有者的durable副本/投影，不是另一个科研账本。

确定性数值适配支持配对独立case、case内seed平均、均值/SD/SE/探索性normal95%CI；
其他实验接口与统计协议仍须按研究适配，程序会明确拒绝。选题价值、官方来源真实性、
每图/面板的视觉语义、引用是否真正支持主张及独立专业审阅仍由宿主真实执行并留证。
结构、hash或声明reviewer名字不能证明这些科学工作已完成。

未知旧schema/旧活动运行不热迁移；未启动付费模型、远程算力、后台研究、投稿或发布。
