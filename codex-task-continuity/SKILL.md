---
name: codex-task-continuity
description: Use when 用户询问还有哪些任务、想恢复之前的 Codex 工作、把想法放到待做/暂放/不要了、查看等待确认事项、查看已完成工作成果、生成每日任务摘要，或处理 Program needs-review/trash-candidates 未归属产物池。
---

# Codex Task Continuity

## 概要

本技能用于维护跨对话、跨 Agent、跨天的任务连续性。它管理未完成任务、未归属待确认产物和已完成工作索引，不负责移动文件、生成上下文压缩摘要或完整整理 Obsidian 知识库。

默认任务账本位置：

```text
~/.codex/task-ledger/
```

待确认产物池位置：

```text
~/.codex/task-ledger/pending-artifacts.json
~/.codex/task-ledger/pending-artifacts.md
```

已完成工作账本位置：

```text
~/.codex/work-ledger/work.jsonl
~/.codex/work-ledger/index.json
~/.codex/work-ledger/index.md
```

核心脚本位于本技能目录：

```text
scripts/task-ledger.py
scripts/task-continuity-hook.py
scripts/work-ledger.py
```

## 何时使用

- 用户问“我还有哪些任务”“昨天做到哪了”“哪些任务等我确认”。
- 用户问“之前实现过什么”“这个功能做到哪一步”“有哪些技能已经做完”。
- 用户说“这个放到待做”“先暂放”“这个不要了”“明天继续”。
- 需要把 `needs-review`、`trash-candidates`、artifact manifest 中未归属、未沉淀、可能是一时实验的遗留产物转成后续处理任务。
- 需要把已完成或阶段完成的功能、技能、Hook、自动化记录成可检索清单。
- 需要在 SessionStart、Stop、PreCompact 里读取或写入任务摘要。

不要用它替代项目管理系统、文件整理器或完整知识库整理流程。

## 状态规则

| 用户表达 | 状态 |
|---|---|
| 只是想法，未开始 | `idea` |
| 明确要做，尚未开始 | `todo` |
| 已开始，未完成 | `in_progress` |
| 等用户决定 | `waiting_user` |
| 缺信息或外部条件 | `blocked` |
| 产物需要判断去留 | `needs_review` |
| 隔离区候选待删除确认 | `cleanup_candidate` |
| 已完成 | `done` |
| 用户放弃 | `dropped` |
| 已归档，无需提醒 | `archived` |

## 常用命令

从技能目录执行：

```bash
python3 scripts/task-ledger.py add --title "任务标题" --next-action "下一步"
python3 scripts/task-ledger.py list --status todo,in_progress,waiting_user
python3 scripts/task-ledger.py update task_id --status done
python3 scripts/task-ledger.py digest --date YYYY-MM-DD
python3 scripts/task-ledger.py import-curator --needs-review-dir PATH --trash-candidates-dir PATH
python3 scripts/task-ledger.py import-artifacts --manifest PATH
python3 scripts/work-ledger.py add --title "完成事项" --summary "做了什么"
python3 scripts/work-ledger.py list
python3 scripts/work-ledger.py sync-obsidian
```

需要机器可读输出时加：

```bash
--format json
```

## Hook 使用边界

`task-continuity-hook.py` 支持：

- `Stop`：只提取显式标记的任务，例如 `TODO:`、`待办：`、`等待确认：`、`阻塞：`、`想法：`。
- `SessionStart`：每天最多打印一次当前未完成任务摘要，作为定时自动化的兜底。
- `DailyDigest`：生成当日任务摘要并打印，供 Codex 定时自动化调用；同时把 Program manifest、当前 `needs-review` 和 `trash-candidates` 中真正未归属的内容导入待确认产物池。输出使用 Markdown 卡片，产物包含稳定编号、内容概要、路径、选择原因和可回复操作短语。
- `PreCompact`：打印当前未完成任务摘要，供压缩上下文保留。

Hook 失败时必须继续主流程；不要因为任务记录失败中断用户当前工作。

默认启用策略：

- 不启用 `Stop`，避免每轮对话结束都写任务或制造噪声。
- 用 Codex recurring automation 每天固定时间调用 `DailyDigest`，把摘要发到配置中的目标线程。
- `SessionStart` 只在当天还没有展示过摘要时兜底提示一次。

每日摘要展示规则：

- 每天都运行，不区分工作日和周末。
- 默认北京时间每天 08:00 触发；自动化 `rrule` 使用 UTC `DTSTART:20260708T000000Z` 表示。
- 发送到创建自动化时绑定的 Codex 摘要归档线程；hook 当前不能识别 Codex UI 正在聚焦的其他对话，也不能自动投递到多个窗口。即使用户当时没看到，重启后仍可在该线程历史里查看。
- 摘要会展示在自动化绑定线程，并保存到 `~/.codex/task-ledger/digests/daily/YYYY-MM-DD.md`；旧版 `~/.codex/task-ledger/daily/YYYY-MM-DD.md` 只作为历史兼容清理目录。
- 每次生成摘要时会自动滚动归档：已结束周的 daily 合成 `digests/weekly/YYYY-MM-DD_to_YYYY-MM-DD.md` 后删除来源 daily；已结束月的 weekly/daily 合成 `digests/monthly/YYYY-MM.md` 后删除来源 weekly/daily。
- 摘要内容采用 Markdown 卡片；这不是原生 UI 组件。当前 hook API 不支持在消息中创建 Codex 原生文件卡片或按钮。
- “前日产物和待确认内容”展示的是待确认池中所有仍为 `pending` 的未归属候选，不只看昨天新增内容。
- 待确认池不是“修改过的文件清单”，也不是审计日志。已纳入工作流的 Skill、Hook、AGENTS、Codex 配置、Git tracked 源码、Obsidian 正式笔记和已记录到工作成果账本的内容，都不应进入待确认池。
- `/Users/dysania/program/codex-workflow-skills` 和 `/Users/dysania/program/skills` 是明确的正式源码根；目录自身即使是 Git 仓库根、近期没有提交或跨过周末，也不进入待确认池。
- 如果候选路径是某个本地 Git 仓库里的源码子目录，并且它存在于当前分支、其他本地分支或 Git 历史中，即使当前分支只残留 `__pycache__`、`.DS_Store` 等缓存，也应视为“分支/项目状态提醒”，不要进入待确认产物池。
- 新候选会进入 `pending-artifacts.json` 和 `pending-artifacts.md`；只要用户没有确认删除、暂放、归档或转待办，就会在后续摘要中继续出现。
- 顶级容器目录不应进入待确认池，例如 `/Users/dysania/program`、`/Users/dysania/program/tools`、`/Users/dysania/program/documents`、`/Users/dysania/program/env`、`/Users/dysania/program/AI`；这类路径只是组织空间，不是可删除或待归档产物。
- 明显临时过程截图会自动清理或移出待确认池，例如系统临时目录中的 `codex-clipboard-*.png`、未被 Obsidian 笔记引用的生成预览图。
- 只有缺少上述归属证据的项目样目录才进入 aging，默认经过 3 个工作日仍无归属才提醒；周六、周日不累计。适用对象例如拉下来试玩的开源项目、demo、带 `.git`、`README.md`、`package.json`、`pyproject.toml` 等标记的未知目录。可用 `CODEX_PENDING_PROJECT_AGING_DAYS` 调整工作日数。
- 每个待确认项都必须展示“内容”和“选择原因”：内容说明它是什么，选择原因说明它为什么被放入待确认池，例如来自会话产物记录、位于 `needs-review`、位于 `trash-candidates`、或项目样目录超过 aging 期。
- 产物操作短语用于用户后续回复，例如 `删除 A02`、`暂放 A02`、`移到待办 A02`；不会因为摘要生成而自动删除或移动文件。
- 已经由 `program-curator apply` 移动到 `needs-review` 或 `trash-candidates` 的内容，会通过对应目录进入摘要。
- “最近完成”读取 `~/.codex/work-ledger/index.json`，只展示最近少量完成项；完整历史看 `index.md` 或 Obsidian 镜像。

## 摘要留存策略

默认留存目录：

```text
~/.codex/task-ledger/digests/daily/
~/.codex/task-ledger/digests/weekly/
~/.codex/task-ledger/digests/monthly/
```

滚动规则：

- daily 是短期回看材料。
- weekly 是 daily 的滚动汇总；生成 weekly 后删除对应 daily。
- monthly 是 weekly 和剩余 daily 的滚动汇总；生成 monthly 后删除对应 weekly/daily。
- hook 只做事实汇总，不调用模型做语义压缩；需要更高质量的周/月复盘时，再由 Codex 读取这些文件后生成正式 Obsidian 周报/月报。

## 待确认池判定规则

应该进入待确认池：

- 一时起意生成的文档、原型、脚本或实验目录，尚未并入项目、Obsidian 或工作成果账本。
- 拉下来试玩的开源项目、参考实现或 demo，几天后仍没有继续推进或归类。
- `needs-review`、`trash-candidates` 中等待决定保留、归档、转项目或删除的内容。

不应该进入待确认池：

- 用户明确要求创建并已经沉淀的 Skill、Hook、自动化、CLI 或项目源码。
- `program/codex-workflow-skills`、`program/skills` 等明确的正式源码根及其内容。
- `.codex` 下的配置、hooks、skills、agents 文件。
- Git 已跟踪的源文件、测试文件、README、构建脚本等项目组成部分。
- 存在于本地 Git 当前分支、其他分支或历史里的源码子目录；这类路径代表未合并、切分支或项目迁移状态，不是待确认删除/归档产物。
- Obsidian 中已归档到正式 PARA 目录的笔记和资源。
- 已经直接加入 task ledger 的待办事项；它们应在“未完成任务”里展示。
- Program 顶级组织目录或项目容器目录，例如 `/Users/dysania/program`、`tools`、`documents`、`env`、`AI`。

可自动清理：

- 系统临时目录中的截图、剪贴板图片、调试预览图。
- Obsidian 附件目录中未被任何笔记引用、且文件名显示为生成预览或临时截图的图片。

延迟提醒：

- 缺少正式归属证据的项目样目录不会当天进入待确认池，默认等 3 个工作日；周末不计入。
- aging 只作用于目录候选；散落文档、总结、脚本仍可立即提醒。
- 这是为了避免“刚拉下来试玩的项目”当天或刚过周末就打扰用户，同时又能在连续若干工作日无后续时提醒确认去留。

## 已完成工作规则

`work-ledger.py` 记录已经完成或阶段性完成的工作。适合记录：

- 已实现的 Skill、Hook、自动化、CLI 或项目功能。
- 阶段完成但仍可能后续优化的能力。
- 一个长对话中多个独立功能的完成状态和使用方式。

不要记录：

- 纯概念问答。
- 没有落地实现、文档或明确产出的闲聊。
- 尚未完成的事项；这类继续放在 task ledger。

默认会同步 Obsidian：

```text
/Users/dysania/program/documents/obsidian_vault/03_Resources/Codex工作台/Codex 工作成果账本.md
```

## 联动方式

- 与 `program-workspace-governance`：只读取公开目录或 manifest，不调用其内部实现。
- 与上下文摘要卡片：只读取 task ledger，把未完成任务作为摘要补充。
- 与 Obsidian：只有中长期项目、关键决策和每日复盘需要回流；小任务不强制写入。

## 常见错误

- 不要把完整 transcript、大段日志、完整 diff 写进任务账本。
- 不要把没有明确下一步的普通聊天写成任务。
- 不要永久删除 `cleanup_candidate`，除非用户有明确授权。
- 不要把 token、Cookie、私钥、`.env` 值写入 ledger；脚本会做常见脱敏，但调用前仍应避免传入敏感文本。
