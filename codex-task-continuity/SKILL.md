---
name: codex-task-continuity
description: 当用户询问还有哪些任务、想恢复之前的 Codex 工作、管理待做或等待确认事项、目标因外部条件暂停后的监控与续作、查看已完成成果、生成每日摘要或语义周报、检查项目周期任务是否正常运行，或需要检查本地仓库中未提交改动、未合并分支、worktree 与 PR 收尾状态时使用。
---

# Codex 任务连续性

## 概要

本技能用于维护跨对话、跨 Agent、跨天的任务连续性。它管理未完成任务、外部条件等待后的监控与续作、未归属待确认产物、已完成工作索引，以及本地 Git / PR 的待收尾事实；不负责无证据地推断条件满足、生成上下文压缩摘要或完整整理 Obsidian 知识库。

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

跨任务操作日志位置：

```text
~/.codex/operation-ledger/events.jsonl
```

仓库收尾审计位置：

```text
~/.codex/task-ledger/repository-closure/latest.json
~/.codex/task-ledger/repository-closure/latest.md
~/.codex/task-ledger/repository-closure/ignore.json
~/.codex/task-ledger/repository-closure/resolutions/YYYY-MM-DD.json
```

核心脚本位于本技能目录：

```text
scripts/task-ledger.py
scripts/task-continuity-hook.py
scripts/work-ledger.py
scripts/repository-closure-audit.py
scripts/recurring-task-audit.py
scripts/repository-action-budget.py
```

## 何时使用

- 用户问“我还有哪些任务”“昨天做到哪了”“哪些任务等我确认”。
- 用户问“之前实现过什么”“这个功能做到哪一步”“有哪些技能已经做完”。
- 用户说“这个放到待做”“先暂放”“这个不要了”“明天继续”。
- 目标需要等待定时任务、CI、审批、额度恢复或其他外部状态，并要求条件满足后自动继续或提醒恢复。
- 用户问“哪些分支还没合并”“有没有代码没提交”“这些任务真的都完成了吗”。
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
python3 scripts/task-ledger.py record-activity --date YYYY-MM-DD --thread-id THREAD_ID --title "任务标题" --status delivered_pending_trial --summary "交付结果" --next-action "真实试用"
python3 scripts/task-ledger.py list-activity --date YYYY-MM-DD
python3 scripts/task-ledger.py track-follow-up --thread-id THREAD_ID --title "目标" --goal "最终目标" --wait-condition "等待条件" --resume-mode auto --resume-action "条件满足后的动作" --monitor-automation-id AUTOMATION_ID --next-check-at ISO_TIME
python3 scripts/task-ledger.py update-follow-up FOLLOW_UP_ID --last-checked-at ISO_TIME --next-check-at ISO_TIME
python3 scripts/task-ledger.py list-follow-ups --status watching,ready,needs_attention
python3 scripts/task-ledger.py record-repository-resolution --date YYYY-MM-DD --finding-id RC-ID --repository REPO --status completed --summary "已合并并清理" --next-action "无需操作"
python3 scripts/task-ledger.py list-repository-resolutions --date YYYY-MM-DD
python3 scripts/task-ledger.py import-curator --needs-review-dir PATH --trash-candidates-dir PATH
python3 scripts/task-ledger.py import-artifacts --manifest PATH
python3 scripts/work-ledger.py add --title "完成事项" --summary "做了什么"
python3 scripts/work-ledger.py list
python3 scripts/work-ledger.py sync-obsidian
python3 scripts/repository-closure-audit.py --root /Users/dysania/program --include-github --format json
python3 scripts/recurring-task-audit.py --root /Users/dysania/program --format json
python3 scripts/repository-action-budget.py show
python3 scripts/period-review.py --previous-week --stdout
```

需要机器可读输出时加：

```bash
--format json
```

## Hook 使用边界

`task-continuity-hook.py` 支持：

- `Stop`：只提取显式标记的任务，例如 `TODO:`、`待办：`、`等待确认：`、`阻塞：`、`想法：`。
- `SessionStart`：每天最多打印一次当前未完成任务摘要，作为定时自动化的兜底；若当天已有仓库收尾报告则直接复用，避免重复网络读取。
- `DailyDigest`：生成当日任务摘要并打印，供 Codex 定时自动化调用；先执行只读仓库收尾审计，再把 Program manifest、当前 `needs-review` 和 `trash-candidates` 中真正未归属的内容导入待确认产物池。输出使用 Markdown 卡片，产物包含稳定编号、内容概要、路径、选择原因和可回复操作短语。
- `DailyDigest` 同时读取 active follow-up，校验绑定 Automation 是否存在、ACTIVE、投递到原线程且按时回写，并展示等待条件、恢复动作、关联周期任务和安全并行工作。
- 每日自动化在调用 `DailyDigest` 前，必须使用 `list_threads` / `read_thread` 读取前一自然日实际活跃任务，并通过 `record-activity` 写入精简活动记录；Hook 不保存完整 transcript。
- 如果线程索引超时或读取失败，Hook 使用操作日志中的昨日项目/任务活跃事件作为降级证据，并从关联上下文卡片提取最近的助手进展；它仍明确标为“仅确认活跃、未推断完成”，不能退化成空白日报或把进展伪装成完成结论。
- `PreCompact`：打印当前未完成任务摘要，供压缩上下文保留。

Hook 失败时必须继续主流程；不要因为任务记录失败中断用户当前工作。

默认启用策略：

- 不启用 `Stop`，避免每轮对话结束都写任务或制造噪声。
- 用 Codex recurring automation 每天固定时间调用 `DailyDigest`，把摘要发到配置中的目标线程。
- 用独立的每周自动化在周一日报完成后运行纠偏聚合、流程复盘和 `period-review.py`，把语义周报发到摘要归档任务。不要把周级成长复盘塞进日报。
- `SessionStart` 只在当天还没有展示过摘要时兜底提示一次。

每日摘要展示规则：

- 每天都运行，不区分工作日和周末。
- 默认北京时间每天 08:00 触发；自动化 `rrule` 使用 UTC `DTSTART:20260708T000000Z` 表示。
- 发送到创建自动化时绑定的 Codex 摘要归档线程；hook 当前不能识别 Codex UI 正在聚焦的其他对话，也不能自动投递到多个窗口。即使用户当时没看到，重启后仍可在该线程历史里查看。
- 摘要会展示在自动化绑定线程，并保存到 `~/.codex/task-ledger/digests/daily/YYYY-MM-DD.md`；旧版 `~/.codex/task-ledger/daily/YYYY-MM-DD.md` 只作为历史兼容清理目录。
- 每次生成摘要时会自动滚动归档：已结束周的 daily 拼接成内部“周归档” `digests/weekly/YYYY-MM-DD_to_YYYY-MM-DD.md` 后删除来源 daily；已结束月的 weekly/daily 拼接成内部“月归档”后删除来源文件。归档不是用户可见的语义周报。
- 用户可见的每周工作总结保存到 `digests/reviews/weekly/YYYY-MM-DD_to_YYYY-MM-DD.md`，按项目合并一周进展并展示完成/待试用、继续推进、周期任务、Codex 工作流变更、跨任务根因、Harness 成长候选和仅在确需时的用户操作。
- 周报只分析上一自然周（周一至周日）；原始日报、context card、报告路径和内部编号仅作证据，不进入用户卡片。
- 摘要内容采用 Markdown 卡片；这不是原生 UI 组件。当前 hook API 不支持在消息中创建 Codex 原生文件卡片或按钮。
- “账本已记录未完成”为 0，只表示 task ledger 当前没有活动记录，不能证明所有 Codex 对话和仓库工作都已完成；必须同时查看 Git / PR 收尾状态和相关任务上下文。
- “昨日实际工作与后续”是日报第一主区块，来源是前一自然日实际活跃的 Codex 任务，而不是最近若干条 work ledger。状态区分 `completed`、`delivered_pending_trial`、`research_pending_implementation`、`in_progress`、`waiting_user` 和 `blocked`。
- 昨日工作必须以准确项目名为第一识别信息，每项只展示状态、昨日结果和下一步；线程标题只作辅助。上下文卡片原文、证据路径和内部报告入口不进入用户卡片。
- 活动账本缺失时，操作日志中的 `context_compacted` 事件按线程去重后成为降级活动，并从其上下文卡片“最近助手进展”提取至多两条短证据；Skill、Hook、Automation 和 Plugin 的已核实新增/更新/移除事件进入“昨日成果与系统变更”。
- “等待条件与续作监控”来自结构化 follow-up，不从任意对话文本或 Automation prompt 猜测。外部条件进入等待前必须登记；自动续作绑定原线程的 ACTIVE heartbeat，并在每次检查后回写检查时间、下一检查和证据。
- 单个 gate 等待不是整个目标 `blocked`。存在不污染等待证据、分支或业务状态的并行工作时，记录 `parallel_action` 并继续执行；所有安全轨道都无法推进时才标记全局阻塞。
- 确定性且不需要业务选择的时间/状态条件默认 `resume_mode=auto`；只能通知或需要人工决策时分别使用 `notify`、`manual`。Automation 缺失、停用、投递线程不匹配或逾期未回写时，日报必须提示处理。
- 已开发、测试或部署但尚未真实使用的成果必须标为“已交付待试用”，并给出最小试运行步骤；调研结论尚未应用时标为“调研完成待实施”。
- 历史 work ledger 只作为内部 JSON 字段保留，不在每日日报展示旧条目或索引链接；昨日成果必须来自昨日活动或操作日志证据。
- “周期任务运行状态”读取项目 `.codex/continuity.json`。只有计划时间、调度器状态、退出码以及结构化状态或成功日志的新鲜度一致时才报告正常；证据过期必须报告延迟，明确失败证据报告失败。
- “仓库收尾”只展示当日最终处置：已处理、近期开发暂不合并、需要关注。没有处置记录时最多展示 3 个优先候选，并写清项目、分支、当前阶段、准确原因和下一步；不得把“证据不足”、RC 编号或“详见报告”作为用户结论。
- 仓库自动化先关联精确项目任务，再按仓库而非 finding 消耗每日动作预算；同一仓库的分支推送、合并和清理应尽量在一个动作批次内完成。只读分析、任务交接和忽略不占写预算。
- 最近活动超过 15 天且没有近期任务继续证据时，默认优先自动收尾；近期仍在开发则保留分支并明确暂缓到什么条件。15 天只改变优先级，不允许 force push、猜测冲突、绕过测试或仓库保护。
- 非本人项目、只读镜像或明确不再管理的仓库写入 `repository-closure/ignore.json`；忽略项必须在 fetch 前跳过，不产生扫描警告或日报条目。
- “前日产物和待确认内容”展示的是待确认池中所有仍为 `pending` 的未归属候选，不只看昨天新增内容。
- 待确认池不是“修改过的文件清单”，也不是审计日志。已纳入工作流的 Skill、Hook、AGENTS、Codex 配置、Git tracked 源码、Obsidian 正式笔记和已记录到工作成果账本的内容，都不应进入待确认池。
- `/Users/dysania/program/codex-workflow-skills` 和 `/Users/dysania/program/skills` 是明确的正式源码根；目录自身即使是 Git 仓库根、近期没有提交或跨过周末，也不进入待确认池。
- 如果候选路径是某个本地 Git 仓库里的源码子目录，并且它存在于当前分支、其他本地分支或 Git 历史中，即使当前分支只残留 `__pycache__`、`.DS_Store` 等缓存，也应视为“分支/项目状态提醒”，不要进入待确认产物池。
- 即使项目尚未初始化 Git，只要候选是带 README、构建标记或明确源码结构的项目内部文件，也视为正式项目内容；不能一边识别为项目源码，一边继续提供删除/暂放/转待办操作。
- 新候选会进入 `pending-artifacts.json` 和 `pending-artifacts.md`；只要用户没有确认删除、暂放、归档或转待办，就会在后续摘要中继续出现。
- 顶级容器目录不应进入待确认池，例如 `/Users/dysania/program`、`/Users/dysania/program/tools`、`/Users/dysania/program/documents`、`/Users/dysania/program/env`、`/Users/dysania/program/AI`；这类路径只是组织空间，不是可删除或待归档产物。
- 系统临时根目录 `/tmp`、`/private/tmp` 和当前 Python 临时根本身也是容器，不进入待确认池；其中满足临时图片规则的文件可直接清理。
- 明显临时过程截图会自动清理或移出待确认池：Python 临时目录、`/tmp`、`/private/tmp` 和微信 `RWTemp` 下的 PNG/JPEG/GIF/WebP 图片不依赖文件名直接删除；未被 Obsidian 笔记引用且名称显示为预览/截图的生成附件也会清理。
- 只有缺少上述归属证据的项目样目录才进入 aging，默认经过 3 个工作日仍无归属才提醒；周六、周日不累计。适用对象例如拉下来试玩的开源项目、demo、带 `.git`、`README.md`、`package.json`、`pyproject.toml` 等标记的未知目录。可用 `CODEX_PENDING_PROJECT_AGING_DAYS` 调整工作日数。
- 每个待确认项都必须展示“内容”和“选择原因”：内容说明它是什么，选择原因说明它为什么被放入待确认池，例如来自会话产物记录、位于 `needs-review`、位于 `trash-candidates`、或项目样目录超过 aging 期。
- 产物操作短语用于用户后续回复，例如 `删除 A02`、`暂放 A02`、`移到待办 A02`；不会因为摘要生成而自动删除或移动文件。
- 已经由 `program-curator apply` 移动到 `needs-review` 或 `trash-candidates` 的内容，会通过对应目录进入摘要。
- `~/.codex/work-ledger/index.md` 继续供自动化内部检索，但不进入用户日报；昨日成果必须由昨日活动或操作日志证据提供。

## 仓库收尾审计

`repository-closure-audit.py` 是确定性、只读扫描器。它发现配置根目录下的 Git checkout，并通过 `git worktree list` 补入登记在外部的 worktree；默认只收集状态和计数，不读取或输出工作文件内容。

扫描事实包括：

- tracked / untracked 改动计数、当前分支、detached 状态、upstream，以及分别相对默认分支和 upstream 的 ahead / behind。
- 默认分支基准、尚未进入基准的本地分支、已经合并但仍占用的 worktree。
- 提交可达、tree 等价和 patch 等价证据；用于识别普通 merge、部分 squash 后的内容等价和干净 detached worktree。
- 使用 `--include-github` 时读取开放 PR 的 draft、merge state、review 与 checks 元数据。
- 每项发现生成稳定 `RC-...` 内部编号，并记录 `workflow_stage`、最近活动、`age_days`、处置方向和下一步。编号只用于账本关联，不向用户展示。
- 默认 15 天为近期窗口；超过窗口的仓库进入优先自动收尾队列。手动扫描可用 `--recent-days` 调整窗口。

自动化执行前先应用持久忽略，再对纳管仓库执行 `fetch --prune`。日报使用默认分支比较判断是否已集成，使用 upstream 比较判断是否已推送保存；两个口径不得混用。脏 worktree 表示处在“整理未提交改动”阶段，不等于未知状态；对应任务应继续提交、测试和合并，近期仍活跃时才明确暂缓。

## 周期任务声明

项目在仓库根的 `.codex/continuity.json` 声明周期任务。每项包含：

- `schedule`：`daily` 或 `weekly`、本地时间、时区和宽限时间。
- `runner`：当前支持 `launchd` label，用于读取加载状态、运行次数和最后退出码。
- `evidence`：白名单 JSON 路径与 JSON Pointer、日志 glob 和成功标记。

审计结果状态：

| 状态 | 含义 |
|---|---|
| `success` | 存在覆盖最近计划时间的新鲜成功状态或成功日志 |
| `overdue` | 已过宽限期，但没有覆盖最近计划时间的新鲜证据 |
| `failed` | 最近计划运行已有失败状态或非零退出证据 |
| `unknown` | 仍在宽限期或证据不足，不能推断成功或失败 |

项目业务状态文件仍是事实源；日报不会因为 LaunchAgent“已加载”就推断业务运行成功。

## 续作监控状态

| 状态 | 含义 |
|---|---|
| `watching` | 等待条件尚未满足，监控继续；若有并行动作，目标仍可推进。 |
| `ready` | 条件已有证据满足，应恢复原线程中的后续动作。 |
| `needs_attention` | 监控失效、逾期或证据异常，需要修复监控或人工判断。 |
| `completed` | 恢复动作和目标均已完成，不再提醒。 |
| `cancelled` | 用户取消续作，不再提醒。 |

周期任务健康和目标续作是两层事实：前者回答“任务是否运行成功”，后者回答“哪个目标依赖它、条件满足后做什么、由谁恢复”。日报必须同时展示，不能用周期任务成功替代目标后续。

可用环境变量：

```text
CODEX_REPOSITORY_SCAN_ROOTS
CODEX_REPOSITORY_CLOSURE_DIR
CODEX_REPOSITORY_CLOSURE_INCLUDE_GITHUB
CODEX_REPOSITORY_CLOSURE_TIMEOUT_SECONDS
```

多个扫描根目录使用系统路径分隔符连接。单个仓库的 Git 或 `gh` 读取失败只生成警告，不能中断其他仓库或主任务。

## 自动提交、PR 与合并边界

仓库扫描器和 Hook 始终只读。只有每日 recurring automation 中运行的 Agent 才能根据扫描结果、相关 Codex 任务上下文和仓库证据执行写操作。

自动收尾必须同时满足：

1. 能定位到相关任务或对话，且已有明确完成结论，没有遗留实现步骤或等待用户选择。至少同时满足“线程项目目录或 cwd 与 worktree 一致”以及“最终答复中的分支、改动文件、commit 或验证证据之一与扫描事实一致”；只靠标题相似不算关联成功。
2. 改动文件与该任务范围能够一一对应；未知 untracked 文件不得默认加入提交。
3. 在当前 HEAD 上重新执行最快相关验证并通过，再做 focused diff review。
4. 当前分支不是默认分支、不是 detached HEAD，没有冲突、没有要求 force push 或重写历史。
5. 远端仓库和 GitHub 登录身份匹配；PR 可创建或复用，且不存在 changes requested、失败检查或不可合并状态。
6. 准备合并的 PR 不是仍需讨论的 draft，merge state 清晰，所需检查和评审均已满足。

满足全部门槛后，可依次执行 focused commit、push、创建或复用 PR，并直接使用 merge commit 合并。用户已授权此类高置信收尾不需要逐次再次确认。

仓库决策顺序：

1. fresh `fetch --prune` 并确定默认分支。
2. 工作区干净且提交已可达、tree/patch 等价或已有 merged PR：移除对应 worktree，删除本地分支；确认无开放 PR 后可删除远端分支。
3. 工作区干净且有唯一提交：若尚未推送，先 push 创建远端保存点；通过线程、测试和 PR 门槛后继续集成，否则保留远端分支并在日报说明后续，不要求用户先做保存操作。
4. 分支相对默认分支和 upstream 都有分叉：允许先 push 保存，不自动 rebase、force 或猜测冲突处理。
5. 干净 detached HEAD 已包含于默认分支则清理 worktree；含唯一提交则创建救援分支并 push。
6. 未知 tracked/untracked 改动、冲突、安全敏感文件、验证失败或业务决策缺失，才作为真正需要用户参与的阻塞。

写操作预算由 `repository-action-budget.py` 管理，初始为 3。连续 7 次有实际处理项、成功率不低于 90%、无风险事件、运行时间和 API 余量健康时按 `3 -> 5 -> 8 -> 10` 提升；冲突、误操作、明显低成功率、超时或 API 压力触发回退。无处理项不累计成长，预算不限制只读扫描。

合并或清理后必须重新扫描，用稳定发现编号确认状态已消失。只有存在精确关联项时才更新 task/work ledger，避免重复记录。

出现以下任一情况就停止集成写操作，只在日报报告下一步：任务仍未完成、上下文无法对应、测试失败、脏改动范围不明、冲突、认证不匹配、PR 检查/评审未通过、需要 force、历史遗留分支无法证明仍有效、仓库禁止 merge commit、要求 merge queue 或分支保护策略无法由当前安全流程满足。不得绕过仓库保护、自动解决冲突或把“有提交”当成“任务已完成”。已获授权的高置信合并分支清理不再重复询问。

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

- 系统临时目录中的截图、剪贴板图片、唤醒测试图和调试预览图；覆盖 Python 临时目录、`/tmp` 与 `/private/tmp`，不要求文件名包含 `codex-clipboard`。
- Obsidian 附件目录中未被任何笔记引用、且文件名显示为生成预览或临时截图的图片。
- 项目目录、正式素材目录或 Obsidian 已引用附件中的图片不自动删除。

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
- 不要在已经判断“属于正式项目源码/文档”后仍把同一条目留在待确认区。
- 不要在昨日有操作日志证据时继续重复展示几天前的固定成果列表。
- 不要把一个等待 gate 写成整个目标停止；不要创建 heartbeat 后却不登记 follow-up，也不要只报告周期任务成功而漏掉依赖它的目标。
- 不要永久删除 `cleanup_candidate`，除非用户有明确授权。
- 不要把 token、Cookie、私钥、`.env` 值写入 ledger；脚本会做常见脱敏，但调用前仍应避免传入敏感文本。
