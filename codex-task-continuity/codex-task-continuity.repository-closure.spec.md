# Codex 仓库收尾闭环 Spec

## 背景和目标

当前 DailyDigest 只汇总显式任务账本、成果账本和待确认产物，不能证明所有 Codex 任务已经完成。它不会扫描 Git 仓库、worktree、分支、PR，也不会把近期线程的实现状态与仓库证据对照，因此会出现“账本未完成为 0，但实际存在半成品或待合并分支”的误导。

本次目标是在现有 `codex-task-continuity` 中补齐跨项目 Git 收尾视图，并让每日自动化在证据充分时自动完成 commit、push、PR 和 merge；证据不足或风险门禁未满足时只报告，不强行修改。

## 用户场景

1. 每天查看摘要时，能区分“账本已记录未完成”和“Git/PR 真实收尾状态”。
2. 已实现、已验证但仍停留在本地分支的工作可以自动进入 PR 并 merge。
3. 仍有 dirty worktree、未完成测试、没有最终答复或存在冲突的工作继续保留，并在日报中说明下一步。
4. 历史遗留仓库、第三方 checkout 和无法关联线程的分支不会被误提交或误合并。

## 范围

- 在 `/Users/dysania/program` 下发现 Git 仓库，并补充 Git 注册的外部 worktree。
- 收集 dirty、未跟踪、upstream、ahead/behind、默认分支、未合并本地分支和 GitHub PR 状态。
- 生成稳定 finding ID、JSON 结果和 Markdown 报告。
- DailyDigest 新增 Git/PR 收尾区块，并输出机器可读字段。
- 修正摘要措辞，明确任务账本和成果账本都不是“今日全部任务完成证明”。
- 更新现有 heartbeat 自动化：先只读扫描，再结合近期线程和 fresh verification 决定是否自动收尾。
- 自动 merge 成功后记录结果；失败或不确定时保留分支和 worktree。

## 非目标

- 不让本地 Hook 单独推断任务语义或直接 merge。
- 不自动继续尚未完成的业务实现。
- 不 force-push，不自动解决 merge conflict，不删除含未提交改动的 worktree。
- 不自动处理非 GitHub 远端或当前认证账号无权限的仓库。
- 不把所有历史 dirty 仓库自动写成任务账本条目。

## 验收标准

- **AC-001**：DailyDigest 标题写明“账本已记录未完成”，并明确 0 不等于所有项目完成。
- **AC-002**：扫描器能发现根目录仓库、嵌套仓库和 Git 注册的外部 worktree，且不读取文件正文、`.env` 或凭据。
- **AC-003**：扫描器能稳定分类 dirty、clean-but-unmerged、open-PR、merged-cleanup 和 legacy/unknown，并提供稳定 finding ID。
- **AC-004**：GitHub CLI 不可用、未登录、超时或单仓库异常时，扫描继续并记录 warning。
- **AC-005**：DailyDigest JSON 包含 finding 数量、分类统计、报告路径和精简 finding；Markdown 按“进行中/证据不足、待集成、PR 待处理、历史遗留”展示。
- **AC-006**：成果记录显示状态日期；`partial` 不再被视觉上误解成当天全部完成。
- **AC-007**：自动 commit/PR/merge 仅在相关线程完成、文件范围可归属、fresh verification 通过、PR mergeable 且 checks 无阻塞时执行。
- **AC-008**：dirty、测试失败、线程仍 active/无最终答复、冲突、认证不匹配或旧任务无法归属时，不执行写操作并进入日报。
- **AC-009**：单次自动化最多收尾 3 个仓库，禁止 force、禁止删除未提交工作，失败不阻塞其余摘要。
- **AC-010**：源码、全局 Skill、`~/.codex/hooks`、自动化 prompt、Obsidian 索引和变更日志同步一致，并有回归验证。

## 约束和假设

- 默认扫描根由 `CODEX_REPOSITORY_SCAN_ROOTS` 或 `CODEX_PROGRAM_ROOT` 控制。
- Hook 只做确定性读取；线程语义和外部写操作由 Codex heartbeat Agent 完成。
- 自动 merge 授权来自用户本轮明确确认，但所有安全门禁仍必须满足。
- GitHub 远端状态使用当前已认证 `gh` 账号只读查询；任何 token 不进入日志、报告或账本。

## 待确认问题

- 无阻断问题；用户已明确允许通过门禁后自动 merge。
