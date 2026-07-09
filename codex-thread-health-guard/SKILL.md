---
name: codex-thread-health-guard
description: 当 Codex 线程上下文过长、任务执行明显吃力、上下文污染、反复返工、用户多次纠错，或 PreCompact/摘要提示需要干净接续时使用；用于判定是否高风险并在高风险时主动创建新线程继续。
---

# Codex Thread Health Guard

用于判断当前 Codex 线程是否已经不适合继续承载任务。只在高风险时迁移；中低风险继续当前线程，避免打断任务。

## 快速判定

先运行脚本生成可审查结果：

```bash
python3 /Users/dysania/program/codex-workflow-skills/codex-thread-health-guard/scripts/thread-health-guard.py --format json --pack-output /tmp/codex-continuation-pack.md
```

脚本默认检查最近更新的线程；如果当前线程候选明显不对，先列出最近线程让用户选择，或传 `--thread-id`。

高风险同时需要满足：

- 上下文压力明显：`tokens_used` 很高、已有多张 context card，或已接近/触发压缩。
- 污染或吃力明显：用户多次纠错/重置范围、多个项目目标混杂、测试/命令/验证反复失败，或最新指令与旧计划冲突。

不要只因为线程长就迁移；也不要只因为一次报错就迁移。

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
请先确认你理解的当前目标、已有进展、风险和下一步，然后继续推进。不要假设完整旧线程都在上下文里；需要细节时读取 pack 中列出的 rollout 或 context card。
```

## 中低风险动作

- `medium`：继续当前线程；必要时提示“如果后续继续返工或上下文继续变乱，再开新线程”。
- `low`：不提示迁移。
- `unknown`：说明健康检查失败原因；不要凭空创建新线程。

## 安全边界

- 不把完整 transcript 大段贴回当前线程。
- 不记录或输出 secrets、tokens、Cookie、私钥、`.env` 值。
- 有命令仍在运行、关键编辑未收敛、或任务马上可完成时，不迁移；先收敛当前可验证状态。
- `create_thread` 不可用时，只保存 continuation pack 并告诉用户路径。
