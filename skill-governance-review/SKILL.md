---
name: skill-governance-review
description: Use when a skill is created, updated, renamed, removed, installed, archived, or when deciding whether a skill should be globally discoverable or only manually invoked.
---

# Skill 治理评审

## 核心原则

不要把每个 Skill 都写进全局 `AGENTS.md`。全局规则只放入口型工作流、长期偏好和安全边界；普通 Skill 靠 frontmatter `description` 自动发现，或由用户手动点名。

## 先读

评审前读取：

- 目标 `SKILL.md`
- `/Users/dysania/.codex/AGENTS.md`
- 如涉及长期记录，读取 Obsidian 的 `03_Resources/Codex工作台/Codex Skills 搜索索引.md`

## 决策矩阵

| 结论 | 适用情况 | 动作 |
|---|---|---|
| 写入全局 `AGENTS.md` | 入口型工作流、跨项目默认行为、安全/隐私边界、强偏好 | 只写短入口，不复制完整流程 |
| 写入项目 `AGENTS.md` | 只对某个仓库或某类项目有效 | 不污染全局 |
| 只更新 Obsidian 索引 | 值得记住，但不该默认触发 | 更新 Skills 搜索索引和变更日志 |
| 仅保留手动调用 | 低频、专业、触发词已经足够清楚 | 不改 `AGENTS.md` |
| 归档或不安装 | 一次性、重复、过重、已被替代 | 移出活跃技能目录或不安装 |

## 必查问题

- 这个 Skill 是否跨项目常用？
- 它是不是入口型流程，而不是普通工具？
- 如果只靠 `description`，未来 Agent 能否正确触发？
- 写进全局后，会不会让所有任务变重？
- 是否与已有 Skill 重复或冲突？
- 是否需要同步到 Obsidian Skills 搜索索引？
- 是否需要在 Codex 变更日志记录？
- 是否需要补充压力场景或人工验证？

## 输出格式

```markdown
## Skill 治理结论

- Skill：
- 结论：写入全局 / 写入项目 / 只更新索引 / 手动调用 / 归档
- 理由：
- 需要修改：
- 不需要修改：
- 触发词建议：
- 验证建议：
```

## 写入规则

- 需要改全局 `AGENTS.md` 时，只加 1-3 条短规则或入口。
- 不把 Skill 正文复制进 `AGENTS.md`。
- 新增、改名、删除或显著更新 Skill 后，更新 Obsidian 的 Skills 搜索索引。
- Codex 自身规则、Hook、Skill 或插件变化，要记录到 Codex 变更日志。

## 常见错误

- 把一次性项目经验做成全局 Skill。
- Skill 描述写了流程细节，导致 Agent 不读正文。
- 为了“记得住”把所有 Skill 名都塞进 `AGENTS.md`。
- 新 Skill 建完后没有更新可搜索索引，过几周忘记它存在。
