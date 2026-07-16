---
name: codex-thread-health-guard
description: 当 Codex 线程上下文过长、任务执行明显吃力、上下文污染、反复返工、用户多次纠错、阶段完成准备进入新阶段，或 PreCompact/摘要提示需要干净接续时使用；用于判定是否高风险并在高风险时主动创建新线程继续。
---

# Codex Thread Health Guard

用于判断当前 Codex 线程是否已经不适合继续承载任务。只在高风险时迁移；中低风险继续当前线程，避免打断任务。已安装时，`SessionStart` hook 会在恢复/打开高风险线程时注入提醒；真正创建新线程仍由 agent 调用 Codex App 工具完成。

## 快速判定

先运行脚本生成可审查结果：

```bash
python3 /Users/dysania/program/codex-workflow-skills/codex-thread-health-guard/scripts/thread-health-guard.py --format json --pack-output /tmp/codex-continuation-pack.md
```

脚本默认检查最近更新的线程；这在后台摘要或其他线程刚更新后可能不准。hook 会优先使用输入里的 `session_id`；手动调用时，如果当前线程候选明显不对，先列出最近线程让用户选择，或传 `--thread-id`。

高风险主要有两类：

- 极端长上下文：`tokens_used >= 1,000,000` 或 context card 已有 4 张及以上，即使暂时没有污染信号，也默认应接续到干净新线程。
- 上下文压力明显，同时污染或吃力明显：`tokens_used` 很高、已有多张 context card，且出现用户多次纠错/重置范围、多个项目目标混杂、测试/命令/验证反复失败，或最新指令与旧计划冲突。
- 阶段切换明确：当前 milestone/阶段已完成并 commit，接下来进入 M2/M3、review、重构、UI 等新工作单元。

普通长线程不要只因为一次报错就迁移；极端长线程优先切干净线程，避免继续继承压缩噪声。阶段切换要有“完成/提交/交接/下一阶段”一类明确信号。

## 主动提醒 Hook

安装副本包含：

```text
scripts/thread-health-guard-hook.py
hooks.json
```

该 hook 用于 `SessionStart`：恢复或打开线程时，如果当前线程高风险且无迁移阻断项，会向上下文注入系统提醒，要求 agent 先创建干净新线程。hook 不直接调用 `create_thread`，避免在命令行 hook 中绕过 Codex App 权限和线程工具。

批量检查最近线程：

```bash
python3 /Users/dysania/program/codex-workflow-skills/codex-thread-health-guard/scripts/thread-health-guard.py --scan-recent 20 --format markdown
```

## 高风险动作

当脚本返回 `risk_level: "high"` 且 `should_create_new_thread: true`：

1. 读取 `continuation_pack_path`，把 pack 作为新线程初始 prompt 的主体。
2. 调用 `list_projects`，优先选择与来源线程 `cwd` 或 `workspace_hint` 匹配的当前项目；匹配不到时使用 projectless target。
3. 调用 `create_thread` 创建干净新线程。不要 fork 完整历史，因为目标是摆脱污染上下文。
4. 调用 `set_thread_title`，标题使用脚本返回的 `suggested_title`，格式必须保留来源提示：

   ```text
   接续: <原线程标题> [from <源线程短ID>]
   ```

5. 当前线程停止继续执行同一任务，只回复新线程已创建、thread id、来源线程和标题。

新线程 prompt 末尾追加：

```text
请先阅读 docs/HANDOFF.md、README.md、当前 git status/diff、项目测试脚本和最近 commit 记录。你是在干净新线程中接手上一个 Codex 线程继续推进；不要重新设计已完成阶段。先确认你理解的当前目标、已有进展、风险和下一步，然后继续执行。不要假设完整旧线程都在上下文里；需要细节时读取 pack 中列出的 rollout 或 context card。
```

如果项目没有 `docs/HANDOFF.md`，新线程先用 pack、README、git 状态和测试脚本接手；不要临时要求旧线程补大段聊天摘要。

## 分支动作

- 清理污染或阶段交接：用 `create_thread` 创建干净新线程，只带 compact continuation pack 和事实文件读取顺序。
- 并行探索替代方案：用 `fork_thread` 或 CLI `/fork`，因为这类任务需要保留完整分叉上下文。
- 临时旁路提问：优先用 side/subagent，不要打断主线程。

## 中低风险动作

- `medium`：继续当前线程；必要时提示“如果后续继续返工或上下文继续变乱，再开新线程”。
- `finish_current_closure_before_migration`：先完成当前命令、验证、提交或局部修复，再重新检查是否迁移。
- `low`：不提示迁移。
- `unknown`：说明健康检查失败原因；不要凭空创建新线程。

## 安全边界

- 不把完整 transcript 大段贴回当前线程。
- 不记录或输出 secrets、tokens、Cookie、私钥、`.env` 值。
- 有命令仍在运行、关键编辑未收敛、或任务马上可完成时，不迁移；先收敛当前可验证状态。
- `create_thread` 不可用时，只保存 continuation pack 并告诉用户路径。
