# Codex 仓库收尾闭环执行契约

## Intent Lock

- 本次只解决：DailyDigest 无法发现 Git/PR 未收尾状态，以及已完成工作长期停留在本地分支的问题。

## Scope Fence

- 范围内：只读扫描、日报呈现、线程关联门禁、自动 commit/push/PR/merge、安装与索引同步。
- 范围外：继续未完成业务实现、批量清理所有历史分支、改写 Git 历史、处理非 GitHub 发布流程。

## Approved Behavior

- 必须满足：证据充分且 fresh verification 通过时自动 merge，无需再次询问用户。
- 明确不改变：未完成、dirty 不明、测试失败、冲突或认证失败时保留现状。

## Design Constraints

- 架构约束：Hook 只读；写操作由 heartbeat Agent 调用正式工具。
- 接口约束：扫描 JSON 字段稳定，单仓库失败不能让 DailyDigest 失败。
- 数据约束：不读取或记录 `.env`、token、Cookie、私钥、账号密码。
- 依赖约束：只用 Python 标准库、Git、可选 `gh`，不新增第三方运行依赖。

## Task Batches

- Batch 1：基线失败、扫描器 TDD、focused commit。
- Batch 2：DailyDigest contract TDD、Skill 元数据、focused commit。
- Batch 3：自动化 prompt、全局同步、真实 dry run、Obsidian 回流、PR/merge。

## Test Obligations

- 必须验证：发现/分类、稳定 ID、超时降级、摘要措辞、JSON contract、真实 dry run、全仓回归。
- 边界情况：detached worktree、无 origin、无默认分支、gh 未登录、PR 冲突、old dirty repo、untracked-only。
- 回归敏感区域：pending artifact 过滤、日报滚动归档、SessionStart 去重、成果账本展示。

## Review Gates

- 实现前：spec/plan/tasks/contract 一致，旧 Skill 基线失败证据完成。
- 实现中：每个行为先 RED 后 GREEN，每批 focused diff review + commit。
- 实现后：fresh 全仓测试、真实只读扫描、源码/安装副本 diff、PR mergeability/checks。

## Auto-Merge Hard Gates

自动写操作必须同时满足：

1. 相关线程有明确 final answer，且没有剩余任务/阻塞声明。
2. 仓库文件范围能映射到该任务；未知 untracked 默认不 stage。
3. fresh verification exit code 0，输出无失败。
4. 分支不是默认分支，不是 detached HEAD，不需要 force-push。
5. PR mergeable，review/checks 无 blocker，base 与远端最新状态一致。
6. 单次运行尚未达到 3 个仓库动作上限。

任何一项不满足，必须停止写操作并报告。

## Rewind Triggers

- 回到 spec：用户要求自动继续未完成业务或覆盖非 GitHub 远端。
- 回到 plan/contract：扫描需要读取 Codex 私有数据库、自动化工具能力与假设不符、动作无法做到可回滚。
- 暂停并报告：测试连续失败、发现 secrets 风险、merge conflict、GitHub 认证不匹配、被扫描项目出现并发修改。
