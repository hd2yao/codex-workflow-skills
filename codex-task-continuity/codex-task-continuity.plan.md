# Codex Task Continuity 实现方案

## 推荐方案

采用三层结构：

```text
codex-task-continuity Skill
  -> 用户查询和任务状态判断入口

task-continuity Hook
  -> Stop / PreCompact / SessionStart 时记录或展示任务

task-ledger CLI
  -> add/list/update/digest/import，维护本地任务账本
```

该组件独立运行。与其他组件联动时，只读写稳定文件协议。

## 第一性原理评审

- 真实目标：让用户不会忘记跨对话、跨天、跨 Agent 的未完成任务。
- 最小可用结果：本地任务账本 + 每日摘要 + 查询入口。
- 真实约束：不能把聊天噪声和敏感信息写进长期账本；不能强依赖某个项目或 Hook；多 Agent 并发需要可合并。
- 更简单路径：只靠 PreCompact 摘要不够，因为它是会话级；只靠 Obsidian 不够，因为任务状态需要频繁变更；只靠 Hook 不够，因为用户需要主动查询和修改任务。

## 架构和数据流

### 1. Skill 层

目标文件：

```text
codex-task-continuity/SKILL.md
```

触发：

- “我还有哪些任务？”
- “昨天做到哪了？”
- “哪些任务等待我确认？”
- “把这个放到待做”
- “这个先暂放”
- “这个不要了”

职责：

- 读取 task ledger。
- 按状态、项目、日期和下一步归类。
- 将用户口头决策写回 ledger。
- 需要长期沉淀时调用 `obsidian-memory-workflow`。

### 2. Hook 层

建议 Hook：

```text
~/.codex/hooks/task-continuity.py
```

触发：

- `Stop`：提取本轮新任务、未完成项、等待确认项。
- `PreCompact`：把当前任务状态写入摘要卡片或追加任务摘要。
- `SessionStart`：展示最近未完成任务摘要。

Hook 原则：

- 只写 task ledger 和 digest 候选。
- 失败不阻塞主流程。
- 不做文件移动，不修改项目代码。

### 3. CLI 层

建议脚本：

```text
codex-task-continuity/scripts/task-ledger.py
```

命令：

```bash
task-ledger add
task-ledger list
task-ledger update
task-ledger digest
task-ledger import-artifacts
task-ledger import-curator
```

关键行为：

- `add`：新增任务。
- `list`：按状态和项目列任务。
- `update`：修改状态、下一步、提醒日期。
- `digest`：生成每日摘要。
- `import-artifacts`：从会话 manifest 导入任务。
- `import-curator`：从 `needs-review`、`trash-candidates`、move log 导入任务。

### 4. 与 Program Governance 联动

读取：

```text
~/.codex/program-governance/artifacts/
/Users/dysania/program/_inbox/needs-review/
/Users/dysania/program/_archive/trash-candidates/
```

转换：

| 来源 | 任务状态 | 下一步 |
|---|---|---|
| `needs-review` | `needs_review` | 判断保留、归档、转项目或丢弃 |
| `trash-candidates` | `cleanup_candidate` | 判断永久删除或恢复 |
| artifact manifest 未处理项 | `todo` 或 `waiting_user` | 继续执行或确认 |
| move log 回滚候选 | `needs_review` | 判断是否恢复 |

### 5. 与 Obsidian 联动

写入规则：

- Daily 摘要可写入 `05_Daily/`。
- 正式项目下一步写入对应 `01_Projects/` 项目页。
- 想法类任务可进入 `00_Inbox/ideas/`。
- Codex 自身任务写入 `03_Resources/Codex工作台/`。

不写入：

- 完整 transcript。
- 大段日志。
- 完整 diff。
- 敏感信息。

## 测试和验证

- 单元测试：任务状态转换、去重、更新、摘要生成。
- Hook dry-run：合成 transcript 生成 task ledger。
- Import 测试：合成 `needs-review` 和 `trash-candidates` 生成任务。
- 并发测试：两个 Hook 同时写入不会损坏 JSONL。
- 敏感信息测试：token、`.env`、Cookie 不进入 ledger。

## 风险和回滚

| 风险 | 缓解 |
|---|---|
| 任务账本噪声过多 | 只记录有下一步或需要用户决策的事项 |
| 多 Agent 写冲突 | 追加 JSONL + 文件锁 + 定期 compact index |
| 用户被提醒打扰 | SessionStart 摘要限制条数，daily digest 可手动触发 |
| 与整理组件耦合过重 | 只读取公开 manifest 和目录，不调用内部函数 |
| 隐私泄露 | 脱敏和跳过敏感路径 |

回滚：

- 移除 Hook 配置。
- 保留 `tasks.jsonl` 作为普通文本备份。
- 删除自动生成的 daily digest。
- 不影响 `program-workspace-governance` 和 `context-summary-card`。
