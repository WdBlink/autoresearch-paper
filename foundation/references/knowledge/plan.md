# Plan：冻结承诺并分解为可检查工作

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
