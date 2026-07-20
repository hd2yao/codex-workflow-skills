---
name: workflow-pattern-retrospector
description: 适用于用户要求自动或周期性复盘近期 Codex 工作、识别重复流程、判断哪些内容应沉淀为 Skill、模板、自动化、Hook、AGENTS 规则或 Obsidian 记录；默认只读摘要、日报、任务账本和工作成果账本，不读取完整 transcript，也不直接创建或删除技能。
---

# Workflow Pattern Retrospector

用于低成本发现“最近哪些工作反复出现，值得沉淀”。本 skill 只产出候选和证据，不直接创建、删除、归档或安装 skill。

核心原则：先用现有摘要和账本做轻量发现，持续记录周级状态；只有跨独立任务重复且有回归场景时，才交给 `skill-governance-review` 决定试运行形态。普通候选无需用户逐项确认。

## 默认输入

优先只读这些低成本材料：

- `~/.codex/task-ledger/digests/daily/`
- `~/.codex/task-ledger/digests/weekly/`
- `~/.codex/task-ledger/digests/monthly/`
- `~/.codex/context-cards/`
- `~/.codex/work-ledger/index.md`
- `~/.codex/task-ledger/pending-artifacts.md`
- Obsidian Codex 工作台的 `Codex 变更日志.md`

不要默认读取完整 transcript、完整 diff、大段日志或项目源码。只有用户明确要求深挖某个候选时，才读取更重材料。

`Codex Skills 搜索索引.md` 只在治理确认阶段读取，用于判断已有替代能力；不要把它当作重复流程证据，否则会因静态索引过大而制造噪声。

## 快速运行

从本 skill 目录运行：

```bash
python3 scripts/retrospect_workflows.py --days 30
```

默认输出到：

```text
~/.codex/workflow-pattern-reports/YYYY-MM-DD-workflow-patterns.md
```

需要直接在当前回复中展示时：

```bash
python3 scripts/retrospect_workflows.py --days 30 --stdout
```

每周自动复盘使用严格的上一自然周，并对照已安装 Skill：

```bash
python3 scripts/retrospect_workflows.py \
  --previous-week \
  --existing-skills-dir ~/.codex/skills \
  --stdout
```

候选生命周期保存到 `~/.codex/workflow-pattern-reports/candidates.json`。同一周幂等重跑不会增加 `weeks_seen`。

## 工作流

1. 自动周评审严格收集上一自然周；手动探索可收集最近 7-30 天摘要和账本。
2. 按关键词族识别重复候选，例如 skill 治理、线程迁移、项目审计、调研、GitHub 初始化、工作区整理。
3. 对候选打分，并与 `~/.codex/skills` 对照；已有能力标记为“更新已有能力”，不能建议重复创建。
4. 输出候选报告，分为：
   - 推荐沉淀
   - 建议合并或归档
   - 暂不处理
5. 持久化出现周期和处理方向，跨周继续监控。
6. 对任何“创建/更新/归档/安装 skill”的动作，必须先补回归场景并使用 `skill-governance-review`。

## 输出要求

报告必须包含：

- 时间范围和读取来源。
- 候选表：候选、建议形态、优先级、证据数、理由。
- 每个候选最多 3 条证据摘录。
- 明确写出“不自动创建、不自动删除、不自动改全局规则”。
- 下一步写明继续监控、更新已有能力或进入治理评审，不把“证据不足”当作结论。

## 不做什么

- 不把一次性任务自动做成 skill。
- 不因为出现一次相似表达就建议沉淀。
- 不自动修改 `AGENTS.md`、Obsidian、skill 目录或 hook。
- 不读取或输出 secrets、tokens、私钥、Cookie、`.env` 值。
- 不用本 skill 替代 `codex-thread-bridge`、`codex-task-continuity`、`program-workspace-governance` 或 `project-status-auditor`。
