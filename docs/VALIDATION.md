# 本分支软件验收

验证于 2026-11-04（Asia/Shanghai），环境为 macOS、Python 3.14.7、
Node v26.8.1、Matplotlib 3.11.0、TeX Live 2026 / pdfTeX 1.40.29。
可复现入口和实际范围如下。

| 检查 | 结果 |
| --- | --- |
| 完整上游 tree | 固定 `7bddd056dfd0b0ded8360588d8101b1ecb5c0baa`；342 路径齐全，326 原样，16 明确补丁，无缺失/模式变化 |
| 新论文扩展 | `foundation/tests` 67 项通过，包含端到端、安装独立性、重编译、逐项要求、返工和恢复故障注入 |
| 用户本地原样 helpers | 105 项通过，4 项旧 checkpoint 集成用例明确不适用；没有复制第二个状态机 |
| 上游 orchestrator | 391/391 |
| 上游 hooks | 267/267 |
| 上游 installer | 18/18；Muse CLI 未安装，其外部 validator 分支跳过 |
| 上游 regression | 65/65；manifest 的预期命令数适配为保留 14 命令并新增 paper |
| 上游 maintenance | 53/53 |
| pi extension | 81/81；未安装 pi-coding-agent types，类型检查分支跳过 |
| Skill 结构 | `quick_validate.py .agents/skills/autoresearch` 通过；上游顶层 version 改为受支持的 metadata.version |
| 来源身份 | 51 份来源 hash 核对，无漂移；6 个原样 helper/test 与来源字节一致 |

完整 fixture 位于私有、gitignored 的 `runs/software-fixture-20261104-final/`。
其 venue、样本、文献、研究问题均明确标为合成；实际运行固定本地 CPU 变换、
记录 16 次尝试，保留测量失败/提前停止及候选负结果，生成可重算统计图表、
实际编译两页 PDF，然后绑定每项义务、校验脚本化 review/R6、导出源码/证据/软件/ZIP，
再从导出目录完整重建 TeX 并核对 PDF 文本。模型调用和远程任务均为零。
独立科学 reviewer 未运行，身份字段仅验证接口，不宣称科学就绪或外部接受。

安装测试使用上游 installer 的临时 Codex 配置，随后删除临时源码 checkout，
单凭安装副本执行相同 fixture。没有更改用户实际安装、全局配置或活动研究目录。
Git 分叉测试在临时独立 repo 中创建真实工作树、产生候选提交并快进最佳版本，
同时验证第二轮可用、早触发替代后续节点、未知结果阻塞及 Scope/控制器路径保护。
没有声称已验证真实模型分叉效果或跨会话领导者交接。

独立审查发现并关闭了稿件双字段错配、R6 错 PDF、注释伪插入、越 Scope 晋升、
固定标签导致第二轮失败、冻结计划阻断返工、无关/不完整证据对账和 Unicode 路径
quoted 输出绕过。相应回归均已纳入上述 67 项。最后 PDF 抽查发现的未解析引用也已
修复：使用禁用用户 rc 的 latexmk 完整构建，或有限次安全 pdflatex，未解析引用拒绝。

验证只覆盖软件合同和已声明的配对 case 数值适配。任意实验接口、其他统计协议、
真实文献权威性、科学主张、语义保真和 PDF 视觉审阅需按实际研究与宿主能力完成。
旧活动运行不热迁移；未启动付费模型、远程算力、后台研究、GitHub fork、发布或投稿。
