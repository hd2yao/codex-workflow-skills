# Codex 仓库收尾闭环实现计划

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` task-by-task, then use `superpowers:verification-before-completion` and `superpowers:finishing-a-development-branch` before delivery.

**Goal：** 让 DailyDigest 真实展示跨项目 Git/PR 收尾状态，并让 heartbeat 在严格证据门禁下自动完成 commit、PR 和 merge。

**Architecture：** 新增确定性只读扫描器，负责仓库/worktree/GitHub 元数据和稳定分类；`task-continuity-hook.py` 只负责把扫描结果写入日报与 JSON。Codex heartbeat Agent 再结合线程工具和项目验证证据做语义判断与写操作，Hook 不直接 merge。

**Tech Stack：** Python 标准库、Git CLI、GitHub CLI、Codex heartbeat automation、unittest。

---

## 推荐方案

### 组件与数据流

```text
Daily heartbeat
  -> DailyDigest hook
     -> repository-closure-audit.py --format json
        -> Git roots/worktrees/local branches
        -> optional gh PR metadata
        -> JSON + Markdown report
     -> DailyDigest Markdown + machine fields
  -> list_threads/read_thread（仅可行动 finding）
  -> fresh project verification
  -> guarded commit/push/PR/merge（最多 3 个）
  -> 展示收尾结果与剩余风险
```

### 扫描器

创建 `codex-task-continuity/scripts/repository-closure-audit.py`，公开这些可测试函数：

```python
discover_git_worktrees(roots) -> list[Path]
inspect_worktree(path, *, gh_client=None, today=None) -> dict
classify_findings(worktrees, *, recent_days=30) -> list[dict]
render_markdown(report) -> str
```

命令接口：

```bash
python3 scripts/repository-closure-audit.py \
  --root /Users/dysania/program \
  --include-github \
  --format json
```

扫描器只读，Git/GitHub 单点失败转为 warning。报告默认保存到：

```text
~/.codex/task-ledger/repository-closure/latest.json
~/.codex/task-ledger/repository-closure/latest.md
```

### DailyDigest 集成

修改 `task-continuity-hook.py`：

- 仅 `DailyDigest` 执行仓库扫描；`SessionStart` 复用当天已有报告，避免重复网络请求。
- 标题改为“账本已记录未完成”，添加解释句。
- 新增 `## Git / PR 收尾状态`。
- 最近成果显示 `updated_at` 日期，并改名为“最近成果记录”。
- JSON 新增：
  - `repository_closure_count`
  - `repository_closure_counts`
  - `repository_closure_findings`
  - `repository_closure_report_path`
  - `repository_closure_warnings`

### 自动收尾门禁

heartbeat prompt 对每个可行动 finding 按顺序检查：

1. 用 `list_threads/read_thread` 找到同项目近期线程；线程仍 active、最新 turn 无 final answer 或明确有剩余任务时停止。
2. 检查 `AGENTS.md`、README、计划和 Git diff，确认文件属于同一任务；不明 untracked 文件不自动 stage。
3. 运行 fresh verification；失败立即停止，不创建 PR。
4. dirty worktree 只有在文件范围、最终答复和验证三者一致时才 focused commit。
5. push 当前分支，创建或复用 PR；检查 mergeable、冲突、review 和 checks。
6. 无 blocker 时 `gh pr merge --merge --delete-branch`；更新本地默认分支并清理无 dirty 的已合并 worktree。
7. 每次最多处理 3 个仓库；其余保留到下一次摘要。

## 第一性原理评审

- 真实目标不是“每天自动 merge 一切”，而是让完成状态可证伪、让已经完成的工作不滞留。
- Git 状态可以确定性扫描；任务是否完成必须结合线程和验证，不能塞进纯 Hook 启发式。
- 自动写操作放在有 App/GitHub 工具和上下文判断能力的 heartbeat Agent，扫描器保持可测试、可回滚、只读。
- 旧仓库噪声通过最近时间、线程关联和每日动作上限控制，不让历史债务阻塞当天摘要。

## 变更文件

- Create: `codex-task-continuity/scripts/repository-closure-audit.py`
- Create: `codex-task-continuity/tests/repository_closure_audit_test.py`
- Modify: `codex-task-continuity/scripts/task-continuity-hook.py`
- Modify: `codex-task-continuity/tests/task_continuity_hook_test.py`
- Modify: `codex-task-continuity/SKILL.md`
- Modify: `codex-task-continuity/agents/openai.yaml`
- Runtime sync: `~/.codex/skills/codex-task-continuity/`, `~/.codex/hooks/`
- Automation update: `codex`
- Obsidian: `Codex Skills 搜索索引.md`, `Codex 变更日志.md`

## 测试和验证

- 临时 Git 仓库覆盖 clean、dirty、ahead、unmerged branch、外部 worktree。
- fake `gh` 覆盖 open/merged PR、未登录、超时和无 PR。
- Hook 测试覆盖新措辞、分类区块、JSON 字段、扫描失败降级。
- 全仓 49 项既有测试加新增测试全部通过。
- 真实 `/Users/dysania/program` dry run 验证关键 finding。
- 源码与全局安装副本 diff 为 0；真实 DailyDigest 用隔离 ledger 运行，不污染正式摘要状态。

## 风险和回滚

- 扫描耗时：限制命令 timeout，只对可行动仓库查 GitHub。
- 历史噪声：分类 legacy，Markdown 限量，完整结果放报告。
- 自动误提交：focused diff、线程映射、fresh verification、禁止默认 stage untracked。
- 自动误合并：mergeable/check/review 门禁，禁止 force 和冲突自动解决。
- 回滚：禁用 automation 中的自动收尾段即可保留只读日报；删除新脚本调用可恢复旧 DailyDigest。
