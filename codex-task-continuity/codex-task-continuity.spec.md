# Codex Task Continuity Spec

## 背景和目标

用户的工作经常横跨多个 Codex 对话、多个 Agent 和多天推进。很多任务不是一次性完成：有的只是讨论出想法，有的实现一半，有的等待用户确认，有的需要第二天继续，有的和 Program 产物整理中的 `needs-review`、`trash-candidates` 有关联。

目标是建立一个可独立使用的任务连续性组件，让 Codex 能记录、汇总和提醒：

- 哪些任务只是想法，还没有实施。
- 哪些任务已经开始但没有完成。
- 哪些任务等待用户确认。
- 哪些任务需要第二天继续。
- 哪些整理候选需要保留、待办、归档或永久删除。

## 模块定位

`codex-task-continuity` 是任务状态和提醒组件，不负责文件整理，不负责生成压缩摘要，不负责项目归档。

它可以独立安装使用，也可以和以下组件联动：

- `context-summary-card`：读取任务账本，在压缩摘要中显示当前未完成任务。
- `program-workspace-governance`：读取 `needs-review`、`trash-candidates`、move log，把待处理文件转成任务。
- Obsidian：把长期任务、项目下一步和每日摘要回流到 PARA 结构。

## 用户场景

1. 用户问了一个想法，但没有开始实现，希望记录为 `idea`。
2. 用户让 Codex 开始做功能，但对话中断或压缩，希望后续能恢复。
3. 多个 Agent 同时跑任务，用户需要知道哪些完成、哪些卡住、哪些等待确认。
4. 第二天用户想知道“我现在还有哪些任务可以继续做”。
5. `program-workspace-governance` 把文件放进 `needs-review`，需要后续提醒用户处理。
6. `trash-candidates` 中的隔离内容需要定期询问是否永久删除。

## 范围

- 新增任务账本，记录跨会话任务状态。
- 新增任务提取 Hook，从会话结束和压缩摘要中提取未完成事项。
- 新增每日摘要生成器，按天输出待办、等待确认、阻塞、隔离区处理建议。
- 新增查询 Skill，使用户问“我还有什么任务”时能读取账本并给出可继续任务。
- 与 `program-workspace-governance` 通过文件协议联动，不直接依赖其内部实现。

## 非目标

- 不替代完整项目管理软件。
- 不自动决定业务优先级，只给建议排序。
- 不永久删除 `trash-candidates`，除非后续策略明确授权。
- 不记录完整聊天、完整 diff、大段日志或敏感信息。
- 不要求必须启用 `program-workspace-governance` 或 `context-summary-card`。

## 数据模型

任务状态：

```text
idea
todo
in_progress
waiting_user
blocked
needs_review
cleanup_candidate
done
dropped
archived
```

任务字段：

```json
{
  "id": "task_YYYYMMDD_slug",
  "title": "任务标题",
  "status": "todo",
  "source": {
    "session_id": "",
    "thread_id": "",
    "transcript_path": "",
    "created_at": ""
  },
  "project": {
    "name": "",
    "path": "",
    "obsidian_page": ""
  },
  "artifacts": [],
  "next_action": "",
  "blocker": "",
  "remind_on": "",
  "updated_at": "",
  "tags": []
}
```

建议保存位置：

```text
~/.codex/task-ledger/tasks.jsonl
~/.codex/task-ledger/index.json
~/.codex/task-ledger/daily/YYYY-MM-DD.md
~/.codex/task-ledger/artifacts/
```

## 联动协议

输入：

- `context-summary-card` 生成的摘要卡片路径。
- `program-workspace-governance` 生成的 artifact manifest。
- `program-curator` 生成的 move log、`needs-review` 记录和 `trash-candidates` 记录。
- Codex transcript 中的用户意图、未完成任务、等待确认项。

输出：

- task ledger JSONL。
- daily digest Markdown。
- 可选 Obsidian 回流候选。
- 给 SessionStart 或用户查询使用的任务摘要。

## 验收标准

- 能从合成 transcript 中提取 `idea`、`todo`、`in_progress`、`waiting_user`。
- 能把 `needs-review` 和 `trash-candidates` 转成任务。
- 能生成每日摘要。
- 用户询问“我还有哪些任务”时，能按状态和项目输出可继续任务。
- 能独立运行，不依赖另外两个组件。
- 敏感信息不会进入 task ledger。

## 待确认问题

1. 每日摘要是否需要自动定时生成，还是在 SessionStart / 用户查询时生成。
2. `trash-candidates` 多久提醒一次是否永久删除。
3. 用户说“放到待做”时，默认状态是 `todo` 还是 `idea`。
4. 是否需要优先级字段，例如 `P0/P1/P2`。
