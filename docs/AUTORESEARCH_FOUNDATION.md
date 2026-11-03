# Autoresearch 源码基线

本分支已直接把仓库根目录替换为 `uditgoenka/autoresearch` 的完整源码。
它不再运行旧 autoresearch-paper，也没有把上游旁置在 third_party 中。
论文能力通过上游新增 `paper` 子命令进入相同的入口、transform 和 installer。

- 上游地址：https://github.com/uditgoenka/autoresearch
- 固定版本：v2.3.0，`7bddd056dfd0b0ded8360588d8101b1ecb5c0baa`，2026-10-31。
- 完整 Git tree：342 个跟踪文件，路径、原 blob、执行位见
  [`upstream-manifest.json`](../foundation/upstream-manifest.json)。
- 原目标基线：`01b3f10ee7725ce04247b8ffc99e70b539bb67d4`，旧源码保留在 Git 历史。
  没有改写 main、创建 GitHub fork、迁移活动研究状态或覆盖其他工作树。
- 根目录保留上游 MIT LICENSE 和 Udit Goenka 版权。安装包也保留许可证。
  用户本地增量和方法来源另见 [`provenance.json`](../foundation/provenance.json)，
  未把 Deli 未识别标准许可的整份上游协议改为 MIT。

`python3 scripts/verify-baseline.py` 检查所有上游路径和模式，并报告本地补丁。
补丁范围由 [`upstream-patches.json`](../foundation/upstream-patches.json) 固定；
原始文件没有因为新子命令而丢失，改变的入口/脚本/manifest 和生成副本可审阅。

上游依然包含完整 classic metric loop、orchestrator、原有 14 个命令、hooks、
rollback、两个循环、单次 subjective dispatch 和 helper scripts。新增 paper
是第 15 个命令，源码为 `foundation/`，经过同一 transform 进入所有 Skill 分发。
它的阶段知识、typed local actions、单一 paper ledger、逐项交付/审阅与最终导出
已形成实际路径，见 [集成使用及验证](PAPER_INTEGRATION.md) 和
[逐项迁移矩阵](KNOWLEDGE_MIGRATION.md)。

上游实际术语是 fork-and-flush。原协议完整保留；paper 的机械接线还提供预算/停滞
触发、files-only 分支请求、真实 Git 工作树、基于验证证据的择优和受 Scope 约束的
快进晋升。每个 incumbent 用单独保护引用，使后续轮次能继续。Agent 的真实创建、
上下文隔离和领导者交接由宿主执行；离线测试没有证明真实模型表现。
