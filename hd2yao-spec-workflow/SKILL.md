---
name: hd2yao-spec-workflow
description: Use when a user asks for a feature, project plan, product or technical proposal, ambiguous implementation request, or multi-step change that may need clarification, Chinese spec/plan/tasks, execution contract, consistency review, or convergence before/after execution.
---

# HD2YAO 中文 Spec 工作流

## 核心原则

先判断复杂度，再选择最轻的足够流程。不要把小任务拖进重流程；也不要在需求不清时直接写代码。

本工作流吸收 Spec Kit / OpenSpec / Superpowers / spec-superflow 的可用部分，但保持本地轻量化：

- Spec Kit / OpenSpec：需求、方案、任务先结构化。
- Superpowers：执行、调试、审查、验证要有纪律。
- spec-superflow：中大型或高风险任务在规划和执行之间加执行契约。
- 本地偏好：中文产物、复杂度分流、少而精，不把所有任务都流程化。

## 复杂度路由

| 场景 | 做法 |
|---|---|
| 小修小改、明确问题、单文件或低风险 | 直接给 3-5 条短计划，执行，验证 |
| 需求模糊、目标不清、功能方案 | 先问一个关键问题，并给推荐默认选项；最多问 5 个高影响问题 |
| 中等功能、跨文件改动、需要用户评审 | 生成中文 spec/plan/tasks；在 plan 中加入轻量执行契约；确认后执行 |
| 高风险改动、迁移、权限、数据、安全、发布、公共 API、长期项目 | 生成 spec/plan/tasks 和独立执行契约；做一致性检查和对抗式评审；用户确认后执行 |

## 标准流程

按复杂度裁剪，不机械全跑：

```text
澄清目标
-> 写/更新中文 spec
-> 写/更新中文 plan
-> 写/更新中文 tasks
-> 必要时生成执行契约
-> 实现前 analyze 一致性检查
-> 用户确认中大型/高风险任务
-> 执行
-> 验证
-> converge 收敛检查
-> 必要时 Obsidian 回流
```

## 澄清规则

- 先读当前项目上下文，再问问题。
- 一次只问一个关键问题，优先给 2-3 个选项和推荐默认选项。
- 最多问 5 个会影响架构、数据、权限、验收、成本或回滚的问题。
- 低影响偏好不要卡住流程，可写入“假设”。
- 澄清完成后，复述目标、范围、非目标、验收标准，让用户能评审。

## 中文输出

- 面向用户评审的文档默认中文：`README.md`、`SPEC.md`、`PLAN.md`、`TASKS.md`、review、handoff、ADR。
- 代码、命令、API、错误信息、协议字段保留原文。
- 不要生成英文 plan 让用户无法评审。

## Spec 模板

中等及以上任务需要落盘时，优先使用项目已有目录；没有约定时用：

```text
specs/<slug>/
|-- spec.md
|-- plan.md
|-- tasks.md
`-- execution-contract.md   # 仅中大型或高风险任务需要
```

`spec.md` 至少包含：

```markdown
# <功能名> Spec

## 背景和目标
## 用户场景
## 范围
## 非目标
## 验收标准
## 约束和假设
## 待确认问题
```

要求：

- 验收标准尽量编号，例如 `AC-001`。
- 范围和非目标要能画出清晰边界。
- 对外行为、权限、数据、安全、性能、回滚相关内容必须写清楚。

`plan.md` 至少包含：

```markdown
# <功能名> 实现方案

## 推荐方案
## 第一性原理评审
## 架构和数据流
## 变更文件
## 测试和验证
## 风险和回滚
## 执行契约（中等任务可内嵌）
```

`tasks.md` 至少包含：

```markdown
# <功能名> 任务拆分

- [ ] T001 任务：...
  映射：AC-001
  验收：...
  验证：...
```

## 执行契约

执行契约是规划到实现的交接层，不是额外的长文档。它回答“实现阶段必须按什么约束做”。

中等任务：可以放在 `plan.md` 的 `## 执行契约`。

中大型或高风险任务：单独写 `execution-contract.md`。

模板：

```markdown
# <功能名> 执行契约

## Intent Lock
- 本次变更只解决：

## Scope Fence
- 范围内：
- 范围外：

## Approved Behavior
- 必须满足：
- 明确不改变：

## Design Constraints
- 架构约束：
- 接口约束：
- 数据约束：
- 依赖约束：

## Task Batches
- Batch 1：
- Batch 2：

## Test Obligations
- 必须验证：
- 边界情况：
- 回归敏感区域：

## Review Gates
- 实现前：
- 实现中：
- 实现后：

## Rewind Triggers
- 出现以下情况回到 spec：
- 出现以下情况回到 plan/contract：
- 出现以下情况暂停并询问用户：
```

生成或更新执行契约时，必须检查：

- 每个验收标准是否有任务或验证方式。
- 每个非目标是否没有被 plan/tasks 突破。
- 每个高风险点是否有测试、手动验证或替代证据。
- 范围、接口、数据、权限、安全或发布策略变化时，先更新契约再执行。

## 评审框架

第一性原理评审用于方案早期：

- 真实目标是什么？
- 最小可用结果是什么？
- 哪些约束是真的，哪些是旧习惯？
- 有没有更简单的路径？

对抗式评审用于实现前或发布前：

- 这个方案最可能在哪里失败？
- 边界条件、权限、数据、安全、成本是否覆盖？
- 测试能否证明验收标准？
- 回滚是否明确？

## 实现前 Analyze

实现前做轻量一致性检查。小任务可以口头检查；中大型或高风险任务必须写进 plan 或执行契约。

检查项：

- `spec -> tasks`：每个验收标准是否有对应任务或验证。
- `plan -> tasks`：每个关键设计决策是否有实现落点。
- `non-goals -> plan/tasks`：是否突破非目标。
- `risks -> tests/rollback`：风险是否有验证或回滚。
- `files -> scope`：变更文件是否在范围内。
- `open questions`：是否还有阻断执行的问题。

如果发现 Critical 问题，不进入实现；先回到 spec、plan 或执行契约。

## 执行规则

- 用户明确要求执行时，不要只输出方案；完成必要澄清后直接推进。
- 只在任务需要长期记忆或用户评审时落盘。
- 小任务不要强制生成 discovery、plan 多版本或 review 文件。
- 执行阶段以 spec/plan/tasks/执行契约为准，不以聊天里的临时想法扩大范围。
- 行为变更优先补测试；没有测试基础设施时，写清最快可行验证。
- TDD 适用于业务逻辑、权限、数据、迁移、API、计费、状态机和 bugfix；不要对所有小改动强制 TDD。
- 独立批次多、上下文大或可并行时，可使用子代理；否则当前 agent 直接小步执行。
- 实现完成前必须做最快相关验证；无法验证时说明原因和替代证据。
- 遇到 bug、测试失败或意外行为，先做根因分析；连续多次失败或发现设计假设错误时，回到 plan/contract。
- 完成后做 converge 收敛检查：对照验收标准、任务、非目标和实际变更，列出已满足、部分满足、未满足、超范围内容。
- converge 只追加剩余任务或记录差距，不重写原计划。
- 中大型项目若需要长期沉淀、项目页更新、日报/周报回流或知识库记录，完成后使用 `obsidian-memory-workflow` 处理。

## 避免

- 不要默认走旧的多轮 Claude 往返 review。
- 不要默认 push、PR、merge，除非用户目标包含远端交付。
- 不要把 loop engineering 概念写进普通任务流程。
- 不要把执行契约变成重复 spec/plan/tasks 的长文档；它只保留执行必须遵守的约束。
- 不要因为流程存在就让小任务变慢。
