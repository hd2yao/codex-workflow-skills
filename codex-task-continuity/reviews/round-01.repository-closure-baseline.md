# Round 01 · 仓库收尾基线失败

## 测试场景

让独立 Agent 仅使用未修改的 `codex-task-continuity` 生成每日摘要，并确认 `/Users/dysania/program` 是否还有未完成、未提交、未合并、未建 PR 或未 merge 的 Codex 工作。

约束：只读，不提供主线程的预期结论，不读取完整 transcript。

## 旧 Skill 的自然行为

- 能读取 task ledger、work ledger、pending artifacts 和既有 DailyDigest。
- 能复述“未完成任务 0”和最近 5 条 `completed`。
- 默认不能从 Skill 工作流判断活跃对话、dirty 内容归属、分支、worktree、PR、CI 或 merge 状态。
- 需要脱离 Skill 自行扫描 Git/GitHub 才能发现真实缺口。

## 观察到的失败

1. 任务账本只有 1 条 `done` 和 1 条 `dropped`，因此“0”只是没有登记活跃任务。
2. 成果账本有 16 条 `completed` 和 1 条 `partial`；`partial` 被最近 5 条 `completed` 挤出日报。
3. 33 个 checkout 中有 15 个 dirty 工作区，旧 Skill 不会展示。
4. `ya-fundmind` M6 worktree 有 2 个提交、1 个修改和 2 个未跟踪测试，明确做到一半，日报仍为 0。
5. `agent-tools` 有已提交但未 push/PR/merge 的功能分支，旧 Skill 不会展示。
6. GitHub 至少有 3 个长期 open/draft PR，旧 Skill 不会展示。

## 基线结论

旧 Skill 不能满足“每日摘要证明项目真实完成状态”的需求。需要新增确定性 Git/worktree/PR 扫描和机器可读 finding；线程语义与自动写操作仍应留给有上下文和正式工具能力的 heartbeat Agent。

这份基线只记录失败证据，不包含新实现答案。
