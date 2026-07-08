---
name: program-workspace-governance
description: Use when 用户在 Program 工作区生成、扫描、整理、归档 Codex 产物、临时实验、总结文档、开源参考、项目候选，或需要判断文件应保留、待确认、隔离、回流 Obsidian。
---

# Program Workspace Governance

## 概要

本技能用于管理 `/Users/dysania/program` 中由 Codex、实验、开源参考和临时想法产生的散落、未归属产物。它可以独立使用，不依赖上下文摘要卡片或任务连续性组件。

核心脚本位于本技能目录：

```text
scripts/program-curator.py
scripts/program-artifact-tracker.py
```

## 何时使用

- 用户要求整理 Program 目录、Codex 产物、临时实验或散落文档。
- 用户在非项目对话中生成了项目、文档、报告、测试或原型。
- 需要判断一个文件应该进入 `_inbox`、`_experiments`、`_external`、`trash-candidates`、Obsidian 或现有项目。
- Codex Skill、Hook、全局规则或工作台结构发生变化，需要回流到 Obsidian 的 Codex 工作台。

不要用本技能去重新确认已经归属的正常工作成果，例如：

- 用户明确要求创建并后续使用的 Skill、Hook、自动化、CLI 或项目源码。
- `.codex` 下的配置、hooks、skills、agents 文件。
- Git tracked 源码、测试、README、构建脚本和项目内核心文件。
- 已经写入 Obsidian 正式目录或工作成果账本的内容。

## 默认路由

| 产物 | 默认去向 |
|---|---|
| 不确定文档、总结、报告 | `/Users/dysania/program/_inbox/needs-review/` |
| 临时实验、验证目录 | `/Users/dysania/program/_experiments/` |
| 开源参考、外部项目候选 | `/Users/dysania/program/_external/` |
| 缓存、构建产物、临时垃圾 | `/Users/dysania/program/_archive/trash-candidates/YYYY-MM-DD/` |
| Codex Skill/Hook/规则变化 | Obsidian `03_Resources/Codex工作台/` |
| 长期项目状态、关键决策 | 对应 Obsidian 项目页 |

待确认候选只针对“未归属内容”：例如一时起意的 demo、未融入工作流的脚本、没有后续的试玩项目、未放入项目页或资源库的总结文档。已纳入项目或工作流的文件不应再进入待确认清单。

项目样目录使用延迟提醒：拉下来试玩的开源项目、demo、带 `.git`、`README.md`、`package.json`、`pyproject.toml` 等标记的目录，默认放 3 天后仍无归属再进入每日待确认摘要。

## 安全边界

禁止自动移动：

- Git 仓库根目录。
- Git tracked 文件或目录。
- 已安装或源码中的 Skill、Hook、AGENTS、Codex 配置。
- `.env`、私钥、Cookie、账号配置、数据库文件、凭据相关文件。
- Obsidian Vault 中已有笔记的大规模结构。

禁止永久删除。删除候选只能移入 `trash-candidates`，后续由任务提醒机制再询问。

## 常用命令

从技能目录执行：

```bash
python3 scripts/program-curator.py scan --root /Users/dysania/program --format json
python3 scripts/program-curator.py plan --root /Users/dysania/program --output-dir /tmp/program-plan --format json
python3 scripts/program-curator.py apply --plan /tmp/program-plan/program-curator-plan-YYYY-MM-DD.json --format json
python3 scripts/program-curator.py report --root /Users/dysania/program
```

纳入历史 Codex 产物时：

```bash
python3 scripts/program-curator.py plan \
  --root /Users/dysania/program \
  --documents-codex /Users/dysania/Documents/Codex \
  --output-dir /tmp/program-plan \
  --format json
```

## Hook 边界

`program-artifact-tracker.py` 只做事实记录：

- 读取 Hook stdin 的 `session_id`、`cwd`、`transcript_path`。
- 从 transcript 中提取候选路径。
- 写入 manifest 和 Markdown 记录。
- 返回 `continue: true`，失败不阻塞主流程。

Hook 不移动文件、不写 Obsidian、不删除内容。

## Obsidian 回流

需要回流时，先读取 Vault 根目录 `AGENTS.md`。允许自动更新的 Codex 工作台入口：

```text
/Users/dysania/program/documents/obsidian_vault/03_Resources/Codex工作台/Codex 变更日志.md
/Users/dysania/program/documents/obsidian_vault/03_Resources/Codex工作台/Codex Skills 搜索索引.md
```

不要把完整 transcript、完整 diff、大段日志或敏感信息写入 Obsidian。

## 常见错误

- 不要把本技能当成永久删除工具。
- 不要扫描后直接移动受保护项目；受保护项必须 `skip`。
- 不要把不确定内容强行归类到正式项目；默认放 `needs-review`。
- 不要通过 Hook 执行整理动作；整理只由 `program-curator apply` 根据计划执行。
