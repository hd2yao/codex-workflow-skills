# Codex 仓库收尾闭环任务拆分

- [x] **T001 基线失败证据**
  映射：AC-001、AC-002、AC-005
  验收：独立 Agent 使用旧 Skill 时无法发现真实 dirty/unmerged/PR 状态；记录具体漏项。
  验证：保存基线输出摘要到 review artifact 或提交说明。

- [x] **T002 扫描器 RED**
  映射：AC-002、AC-003、AC-004
  验收：临时 Git 仓库测试能表达 clean、dirty、ahead、worktree、PR 和 gh 失败场景，并因模块不存在失败。
  验证：`python3 -m unittest codex-task-continuity/tests/repository_closure_audit_test.py` 预期 FAIL。

- [x] **T003 扫描器 GREEN**
  映射：AC-002、AC-003、AC-004
  验收：最小只读扫描实现使 T002 全绿，生成稳定 JSON/Markdown。
  验证：focused test + `git diff --check`。

- [x] **T004 DailyDigest RED/GREEN**
  映射：AC-001、AC-005、AC-006
  验收：先新增摘要措辞、分类和 JSON contract 失败测试，再接入扫描器使其通过。
  验证：`python3 -m unittest codex-task-continuity/tests/task_continuity_hook_test.py`。

- [x] **T005 Skill 与自动收尾契约**
  映射：AC-007、AC-008、AC-009
  验收：`SKILL.md` 和 heartbeat prompt 明确线程、diff、verification、PR checks、动作上限和停止条件；禁止 force/冲突自动解决/未知 untracked 自动 stage。
  验证：Skill validator、自动化 view、压力场景复测。

- [x] **T006 真实 dry run 与回归**
  映射：AC-002 至 AC-010
  验收：真实扫描能识别当前已知关键仓库；全仓测试通过；不修改任何被扫描项目。
  验证：真实 JSON 报告、Git status 对比、全仓 unittest。

- [x] **T007 安装、回流与交付**
  映射：AC-010
  验收：同步全局 Skill/hook，更新 Obsidian 索引和变更日志；源码分支 push、PR 无 blocker 后自动 merge。
  验证：目录 diff、GitHub PR 状态、本地 main 与 origin/main 一致。
