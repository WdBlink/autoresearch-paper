# 用上游 Autoresearch 执行论文工作

本分支将完整上游作为根目录基础。`/autoresearch:paper` 或 `$autoresearch paper`
进入同一 Skill 中的新论文子命令。原有命令、helper、hooks 和迭代协议继续分发，
不是在旧科研运行时外面加一层调度器。`foundation/` 是新增源码，
`.claude/commands/autoresearch/paper.md` 是子命令协议，
`scripts/transform.sh` 是各平台副本的生成入口。

## 安装与入口

先在仓库运行 `bash scripts/transform.sh`，再使用上游 installer，例如：

```sh
bash scripts/install.sh --codex --global --config-dir /absolute/test-config --force
```

这是自定义测试目录示例；本任务没有更改当前安装或任何全局模型配置。
安装后的论文程序是 `skills/autoresearch/paper/scripts/paper.py`。
仓库入口为 `python3 scripts/paper.py --run /absolute/private-run --help`。
完整交接需要 Python 3.10+、TeX、Poppler；PDF 统计图需要 Matplotlib。
缺少实际能力时明确报错，不以文本检查替代 PDF/统计运行。

## 研究与写作交接

宿主准备真实 Brief，列出问题、venue、方向、论文类型、可用材料、路线、资源授权，
以及每一项必交图、表、章节与稿件。`init` 返回精确内容及 digest；宿主转达该版本
实际已有的人类批准后运行 `approve`。此接口不代替真实批准，也不伪造旧控制器签名。

`context` 按 intake→venue→plan→literature→experiment→figures→write→review→delivery
返回对应知识全文、上游协议、当前输入 hash 和逐项义务。宿主实际执行研究、阅读和
独立评审，确定性程序检查可判定的内容；参考正文不会变成操作权限。
完整字段、命令及适用性见 [`packets.md`](../foundation/references/packets.md)，
实验/图表/写作的具体数值接口见 [`science-packets.md`](../foundation/references/science-packets.md)。

三个用户本地 Deli helper 按来源原样保留，只复用测量、计划审计和 item validator
纯函数。其 CLI 账本不运行；checkpoint 的证据/轮次/pivot/幂等/恢复规则映射到同一
`.paper/control.json`。PaperFlow 的完整材料 intake、WorkOrder requirement IDs、
typed actions、binding、独立 requirement checks 与 finalizer 方法均接入该路径。

计划的科研承诺和原快照固定。返工用 `rewind` 保留旧回执，`revise-orders` 追加新工作单
和输出版本；它不能改变 Brief 的义务。成功工作单、失败任务、效果不明与科研负结果
分别保留。丢失终态时，相关动作、输入版本和预期输出逐项对账，不能凭无关文件把任务
标完成，也不能因已完成审计就宣布 GO。

逐项绑定使用实际稿件、当前资产/数据 hash 和插入位置。写作检查与导出使用同一份
TeX，R6 与最终审阅使用已接受的同一份 PDF。图表只在注释中出现不算插入；改变证据、
资产或绑定会使旧审阅失效。最终导出含 PDF、可编辑 TeX、证据、产生它们的软件、
manifest 和 ZIP，并从导出目录实际重编译检查 PDF 文本一致。

## 可复现的软件验证

```sh
python3 -m unittest discover -s foundation/tests -p 'test_*.py' -v
python3 foundation/vendor/deli-local/run-tests.py
python3 foundation/tests/run_fixture.py --run /absolute/new-software-fixture
python3 scripts/verify-baseline.py
```

fixture 的 venue、样本、文献和研究问题明确标为合成。它真实运行固定本地 CPU 程序，
保留 16 次计划运行中的测量失败/提前停止与负结果，生成统计图和表，实际编译论文，
再经过逐项绑定、脚本化 reviewer packet、R6 和导出/重新编译。模型调用和远程作业均为零。
它不是真实研究，也没有执行真实独立模型审阅。安装测试另在临时配置安装，再删除源
checkout，运行安装副本的同一 fixture，检查自包含分发。

核心反例包括材料未读/错误 span、假录用依据、模板错用、事后改计划、漏实验和分母、
holdout 选型、未知效果、统计/图像篡改、数值或分母漂移、删负例、漏交项、陈旧/错绑、
两份稿件错配、注释伪插入、返工死路、不相关证据对账，以及 Git 晋升越过 Scope。
完整上游 shell suites 按现有协议验证，原样 helper 的 4 个旧 checkpoint 集成用例
明确不适用于新单账本，其他 105 项运行；新账本另有真实恢复故障注入。

## 实质边界

自动数值适配目前支持独立 case 配对、case 内 seed 平均、均值/SD/SE/探索性 normal
95% CI。其他实验接口和统计方案必须明确适配；不得把真实项目强塞进 fixture。
来源确属官方、方案语义、主张成立、偏离是否合理、自由正文保真和最终 PDF 视觉质量
仍需真实领域审阅。身份字段和结构检查不能证明模型独立性或外部学术接受。

旧运行保持原版本和原权限边界。这里没有热迁移旧图 checkpoint、旧活动会话、
私有论文服务、云计算或凭证，也没有启动真实研究、付费模型、远程计算、后台研究、
GitHub 发布或投稿。上述边界与软件验收分别报告，不以 fixture 状态替代科学结论。
