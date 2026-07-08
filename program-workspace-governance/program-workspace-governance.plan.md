# Program Workspace Governance 实现方案

## 推荐方案

采用四层架构：

```text
program-workspace-governance Skill
  -> 影响 Codex 未来如何判断产物去向

program-artifact-tracker Hook
  -> 在 Stop / PreCompact 时记录事实和候选产物

program-curator CLI
  -> 只读扫描、分类、生成计划、按预授权策略自动整理

Obsidian PARA / C 点
  -> 长期记忆、项目状态和 Codex 自身变化的权威索引
```

第一版仍优先做“规则、记录、计划”，但 `apply` 的目标状态改为按预授权策略自动执行低风险移动，不再逐次要求用户确认。

模块边界要求：本组件必须能独立运行。与 `context-summary-card`、`codex-task-continuity` 或后续组件的联动只通过文件协议和薄编排层完成，不共享内部实现。

## 第一性原理评审

- 真实目标：减少 Program 目录和 Codex 产物混乱，同时保留后续可检索性。
- 最小可用结果：Codex 能知道产物该放哪里，并在会话结束时留下可审计记录。
- 真实约束：不能自动误伤受保护项目；不能记录敏感信息；不能把 Obsidian 变成日志垃圾桶；不能永久删除用户内容。
- 更简单路径：只写 Skill 不够，因为历史产物不会被扫描；只写 Hook 不够，因为 Hook 不应决策和移动；只写 CLI 不够，因为新产物仍会乱放。

## 架构和数据流

### 0. 组件协作原则

- 单独使用：`program-workspace-governance` 可只提供 Skill + CLI，不依赖任何 Hook。
- 可选接入：启用 Hook 后，只增加事实记录和摘要，不改变 CLI 核心规则。
- 可移植：分享给他人时，可以不带 Obsidian C 点，只改配置中的 vault 路径或关闭 Obsidian 回流。
- 可扩展：新增组件只读写稳定协议文件，例如 manifest、task ledger、move log。

### 1. Skill 层

目标文件：

```text
program-workspace-governance/SKILL.md
```

职责：

- 判断新产物属于 Program 项目、实验、外部参考、Obsidian Inbox、Resources、项目页或 C 点。
- 指导 Codex 在生成文件前先选择目标路径。
- 要求中大型项目或关键结论使用 `obsidian-memory-workflow`。
- 要求创建或修改 Skill/Hook 时使用 `skill-governance-review`。

### 2. Hook 层

建议新增：

```text
~/.codex/hooks/program-artifact-tracker.py
```

建议配置：

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/Users/dysania/.codex/hooks/program-artifact-tracker.py"
          }
        ]
      }
    ]
  }
}
```

职责：

- 从 Hook stdin 获取 `session_id`、`transcript_path`、`cwd`。
- 解析 transcript 中出现的文件写入、路径、工具调用和最终消息。
- 记录本轮候选产物到 JSON manifest。
- 输出简短 `systemMessage`，提示候选归档位置和下一步。

建议输出目录：

```text
~/.codex/program-governance/artifacts/YYYY-MM-DD/<session-id>.json
~/.codex/program-governance/artifacts/YYYY-MM-DD/<session-id>.md
```

停止条件：

- transcript 不存在：输出错误提示，但 `continue: true`。
- 发现疑似 secret：记录风险标记，不复制原文。
- 无新增候选产物：只写最小 manifest。

### 3. PreCompact 扩展

扩展现有：

```text
~/.codex/hooks/context-summary-card.py
```

新增卡片小节：

```markdown
## 本轮产物和归档建议

- 候选文件：
- 建议去向：
- 是否需要 Obsidian 回流：
- 是否涉及 Codex C 点：
```

实现方式：

- 优先读取同 session 的 artifact manifest。
- 如果没有 manifest，基于 transcript 做轻量路径提取。
- 不执行移动，不写 Obsidian。

### 4. CLI 层

建议脚本：

```text
program-workspace-governance/scripts/program-curator.py
```

命令：

```bash
program-curator scan --root /Users/dysania/program
program-curator plan --root /Users/dysania/program
program-curator apply --plan <plan.json>
program-curator report
```

第一版只实现：

- `scan`：只读扫描项目和候选散落产物。
- `plan`：生成 Markdown + JSON 整理计划。
- `report`：输出统计和风险。

第二版再实现：

- `apply`：按预授权策略自动移动低风险内容；只移动不永久删除；写 move log。

### 4.1 预授权整理策略

允许自动创建：

```text
/Users/dysania/program/_inbox/
/Users/dysania/program/_experiments/
/Users/dysania/program/_external/
/Users/dysania/program/_archive/
/Users/dysania/program/_archive/trash-candidates/YYYY-MM-DD/
/Users/dysania/program/_inbox/needs-review/
```

允许自动移动：

- Codex 本轮新生成的文件或目录。
- `/Users/dysania/Documents/Codex` 下的散落产物。
- `/Users/dysania/program` 下明显不属于已有项目的孤立文档、实验目录和临时产物。
- 明确属于某项目的 Codex 总结、报告、handoff。

禁止自动移动：

- 已有 Git 仓库根目录。
- Git 仓库中的 tracked 文件。
- `.env`、私钥、Cookie、账号配置、数据库文件、凭据相关文件。
- Obsidian Vault 中已有笔记的大规模结构、文件名和链接体系。

不确定内容自动移动到：

```text
/Users/dysania/program/_inbox/needs-review/
```

删除候选只能移动到：

```text
/Users/dysania/program/_archive/trash-candidates/YYYY-MM-DD/
```

### 5. Obsidian 回流

落点：

```text
01_Projects/Program 项目整理/
03_Resources/Codex工作台/
00_Inbox/
03_Resources/开源项目分析/
03_Resources/研究报告/
```

规则：

- Program 扫描结果进入 `Program 项目整理`。
- Codex Skill/Hook/规则变化进入 C 点。
- 开源项目分析进入 Resources。
- 未分类想法先进入 Inbox。
- 日志、diff、临时失败过程不进入 Vault。

## 变更文件

第一阶段：

```text
program-workspace-governance/program-workspace-governance.spec.md
program-workspace-governance/program-workspace-governance.plan.md
program-workspace-governance/program-workspace-governance.tasks.md
program-workspace-governance/reviews/round-01.governance.md
```

后续实现阶段：

```text
program-workspace-governance/SKILL.md
program-workspace-governance/hooks.json
program-workspace-governance/scripts/program-artifact-tracker.py
program-workspace-governance/scripts/program-curator.py
program-workspace-governance/tests/
codex-context-summary-hook/scripts/context-summary-card.py
```

## 测试和验证

- 单元测试：路径分类、敏感信息过滤、manifest 生成、计划生成。
- 集成测试：用合成 transcript 模拟 Stop / PreCompact。
- Dry-run 验证：扫描 `/Users/dysania/program` 时不读取 `.env`，不移动文件。
- Apply 验证：合成文件可自动移动；Git tracked 文件、Git 仓库根目录、敏感路径必须拒绝。
- Obsidian 验证：检查 frontmatter、wikilinks、目标目录和是否需要更新索引。

## 风险和回滚

| 风险 | 缓解 |
|---|---|
| 自动移动误伤项目 | 保护 Git 仓库根目录和 tracked 文件；高风险内容进入 `needs-review` |
| Hook 阻塞 Codex | 所有异常返回 `continue: true` |
| Obsidian 被日志污染 | Hook 只写 manifest；长期回流由 Skill/CLI 判断 |
| secrets 被记录 | 脱敏规则 + 跳过 `.env`、私钥、Cookie |
| 隔离区无限增长 | 接入任务提醒机制，定期询问是否保留、待办、归档或永久删除 |
| 全局规则过重 | 只在最终 Skill 验证后写 1-2 条入口，不复制流程 |

回滚：

- 删除或移除 `~/.codex/hooks.json` 中新增 Hook 配置。
- 删除 `~/.codex/hooks/program-artifact-tracker.py`。
- 根据 move log 反向移动自动整理的文件。
- 保留 manifest 作为审计记录，必要时手动删除。
- Skill 未安装前不影响全局 Codex 行为。
