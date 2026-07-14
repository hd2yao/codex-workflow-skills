# codex-task-continuity 仓库收尾治理评审

## 结论

- 决策：更新现有 `codex-task-continuity`，不创建新的同主题 Skill。
- 安装范围：保持为高频全局工作流 Skill；源码验证后同步完整目录到 `~/.codex/skills/codex-task-continuity/`。
- 自动化范围：更新现有每日 heartbeat，不创建重复定时任务。
- 全局规则：不修改 `~/.codex/AGENTS.md`。现有“独立回滚单元及时提交”和“远端交付时 push / PR / merge”规则已经成立；具体扫描、上下文关联和自动收尾门槛属于 Skill 与自动化职责。
- 长期记录：更新 Obsidian 的 `Codex Skills 搜索索引.md` 和 `Codex 变更日志.md`。

## 边界与重叠检查

| 能力 | 责任入口 | 本次处理 |
|---|---|---|
| 跨天任务、每日摘要、成果账本 | `codex-task-continuity` | 扩展 Git / PR 收尾事实与日报解释 |
| 单项目正式证据审计 | `project-status-auditor` | 保持按需，不用于每日全盘扫描 |
| 单分支实现完成后的合并选择 | `superpowers:finishing-a-development-branch` | 复用其验证与集成边界，不复制成新 Skill |
| GitHub 仓库初始化 | `github-project-bootstrap` | 不变 |
| 重复流程候选发现 | `workflow-pattern-retrospector` | 已提供重复证据，只输出候选 |

## 风险门槛

- Hook 与扫描器只读；代码写入仅由每日 heartbeat Agent 在全部证据门槛满足时执行。
- 用户已授权满足门槛的自动 merge 无需逐次确认，但没有授权 force、自动解冲突、删除脏 worktree、猜测任务范围或提交未知 untracked 文件。
- task ledger 为 0 只代表账本没有活动记录，不构成“所有对话和项目均已完成”的证据。
- 历史遗留分支、失败检查、changes requested、draft 讨论、认证不匹配和无法关联上下文均停止自动写操作。

## 描述与可发现性

- frontmatter 描述改为中文，覆盖任务连续性、每日摘要和未提交/未合并/worktree/PR 收尾触发词。
- 新增 `agents/openai.yaml`，显示名、短描述和默认提示均为中文，并显式引用 `$codex-task-continuity`。
- 不把流程正文复制到全局规则，只在 Skill、自动化和 Obsidian 索引保留各自必要信息。

## GREEN 压力测试收敛

更新后的独立 Agent 能正确判断“账本 0 不能证明全部完成”，并按五类状态应用六组自动收尾门槛。压力测试暴露并已补齐：

- 默认 30 天历史窗口与 `--recent-days` 调整入口。
- 脏 worktree 与 PR 并存时，证据不足优先阻断写操作。
- 线程 cwd / 项目路径加分支、文件、commit 或验证事实的双重关联要求。
- 合并后重扫、按稳定编号确认、只对精确关联账本项做幂等回写。
- 本地 worktree 与本地分支不自动删除。
- merge queue、禁止 merge commit 或无法满足的分支保护策略一律停止并报告。
