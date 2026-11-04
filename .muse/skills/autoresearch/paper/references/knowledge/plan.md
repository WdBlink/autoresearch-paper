# Plan：冻结承诺并分解为可检查工作

Use [production.md](../production.md): probe the actual interpreter/dependencies and generate the `experiment-template` recording envelope before freezing a scientific evaluator. WorkOrders use registered `export_image` and `prepare_tex` policies when needed. Dataset identities, seeds, method choices and their scientific justification remain task parameters.

本阶段结合 Deli 本地逐项交付合同和 R6 计划快照、PaperFlow 的 WorkOrder/typed action，以及上游 Autoresearch 的 plan 子命令。下述字段含义按本分支 runtime contract，不代表复刻 PaperFlow 的 LangGraph 或 Deli 记账器。

## 输入及冻结

读取完整 Brief、venue/profile/template、材料证据和可行性。核对用户看到的每个要求已进入 `deliverable_plan`。每个稳定 requirement ID 要回答具体问题、规定必要内容与证据，并给出可判定验收；不要把“有一张图”当成图的内容要求。

在实际工作前冻结计划快照，保留批准 Brief 的哈希、当前计划和每轮开始版本。控制器是状态的唯一写者，模型不能直接改控制文件或旧回执。计划快照不是后期从成稿逆向生成的副本。

## 任务与动作

- `WorkOrder.requirement_ids` 覆盖全部当前承诺，未知 ID、遗漏 ID、过期 Brief、非法依赖必须在执行前拒绝。一个实验可以支持多图；不是一项要求就永久创建一个 Agent。
- 每个工作单有生产者、依赖、输入/输出、明确作用域与 typed actions。只调用已注册能力及其真实参数，不把任意生成的 Python/JS 作为脚本执行。宿主执行研究判断；确定性能力负责可复算工作。
- 工具权限是可做的上界，不是已发生效果的证据。外部动作必须在其前置科学/资源结果出来后重新判断，审计任务 completed 不等于 GO。
- 每个实验先把 claim、比较对象、变量/控制、指标方向、统计单位、样本/失败分母、分割暴露、停止/重试规则和负结果处置写清。先做最小可测任务，不把“跑不显著再加样本”当方案。
- 为每张图表写问题、候选主张、数据、比较单位、区间/失败口径、形态选择理由和稿件位置。计划的是证据与论证，不是图型配额。

## 轮次、停滞与分叉

一轮结束按实际证据区分 verified progress、no progress 与 regression；心跳、换措辞或同一发现重述不清零停滞。使用当前控制器的 prepare/apply，而不并行启动 Deli `checkpoint.py` 第二套账本。两个停滞轮后继续需要结构性转向，说明改变了什么假设、搜索空间或证据路径；保留已尝试方向与负面结果。

Autoresearch 指标循环保留 Modify/Verify/Keep-or-Discard，任务编排循环保留 predicate/units/plateau 语义。fork-and-flush 从当前最佳版本提供 fresh-context 多分支，按预算节点/早停滞条件及编排 plateau 的不同触发策略执行。其分支 metric 只决定候选保留，不能授予论文验收、修改原评价器、删掉失败记录或自动扩大算力。资源共享时顺序执行分支，所有分支计入实际预算。

## 修改、失败与交接

执行方法和顺序的常规调整在范围内进行；删除比较、降低证据标准或缩减必交义务需显式修订和真实范围授权。保留原承诺与 added/removed/changed 及原因。结果不支持假说时仍保留调查义务，不能通过重命名图号或改计划把缺项消掉。

交给 literature/experiment 的是冻结计划、所有 requirement IDs、可执行工作单和统计设计；review 将同时读取轮前快照、现计划与成稿。未覆盖承诺、计划中的 must 数据仍待补、执行条件无法满足时返回具体阻塞，不进入写作凑内容。

## 每轮的工程约束与来源适用性

Deli 的 Topic→Draft→Deep Improvement→Sprint 提供轮次组织经验；本分支按研究证据依赖组织 intake、venue、plan、literature、experiment、figures、write、review。具体先后随真实输入，不能为复刻旧 Iter 1–6 先写结论、再于 Iter 7 做实验。论文后期仍保留 review→按缺陷路由→修复→编译→重新评审闭环。

每轮首次操作先保存现计划快照和版本；登记本轮处理文件/起始证据，结束时提交验证与 R6 使用的实际材料。初始 frozen plan 不能替代每轮快照，成稿后补拍快照也不能证明轮前承诺。文件、规则、任务或证据变化后旧判断不能重用。中断恢复先对账上一轮和实际效果，不从零初始化。

Deli 本地默认每轮最多处理五个大文件、生成单个 `.tex` 不超过三百行；它们是降低上下文和重写风险的工程护栏，不是科学验收阈值。已有大文件不为行数无关拆分。需要偏离时记录文件、原因和检查，不用删除证据或缩小用户要求满足护栏。

默认工程停止政策来自 Deli 的单会话十五轮或三十分钟、实验设计迭代五次、精修两轮增益不超过 0.3 或超过十二轮；当前用户预算/执行要求优先。只有实际采用了模拟评分才有“分数增益”，不可填造分数触发停止。到预算上限只说明 stopped 与真实结果，不能因此完成质量门。四次连续停滞标 attention；attention 是具体状态和原因，不自动对外发消息或调用未授权服务。
