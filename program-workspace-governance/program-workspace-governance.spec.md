# Program Workspace Governance Spec

## 背景和目标

`/Users/dysania/program` 已经同时承载长期项目、开源参考、实验代码、临时验证、生成文档和 Codex 对话产物。用户经常在非项目上下文中新开 Codex 对话，随后生成项目、总结文档、测试文件或临时实验。如果这些产物默认落在当前目录、已有项目目录或 `Documents/Codex` 临时目录，后续会难以判断：

- 哪些应该保留为正式项目。
- 哪些只是想法、草稿或实验。
- 哪些应该进入 Obsidian 长期记忆。
- 哪些应该归档或清理。
- 哪些 Codex 自身能力变化需要回流到 C 点。

目标是建立一套“先记录、再分类、按预授权策略自动整理”的机制，使 Codex 以后能主动管理 Program 工作区产物，但不擅自移动、删除或重命名受保护内容。

## 最新规则依据

- Codex 全局规则：`/Users/dysania/.codex/AGENTS.md`
- Skills 仓库规则：`/Users/dysania/program/codex-workflow-skills/AGENTS.md`
- Obsidian Vault：`/Users/dysania/program/documents/obsidian_vault`
- Vault 规则：`/Users/dysania/program/documents/obsidian_vault/AGENTS.md`
- Program 项目中枢：`/Users/dysania/program/documents/obsidian_vault/01_Projects/Program 项目整理/`
- Codex C 点：`/Users/dysania/program/documents/obsidian_vault/03_Resources/Codex工作台/`
- 现有摘要 Hook：`/Users/dysania/.codex/hooks/context-summary-card.py`

## 用户场景

1. 用户在无项目上下文中提出一个想法，Codex 讨论后创建了一个新原型或项目。
2. 用户要求 Codex 总结某个问题，输出 Markdown、报告、清单或研究文档。
3. 用户在已有项目里让 Codex 生成阶段总结，但文档本质上应该进入 Obsidian 项目页或 Resources。
4. 用户拉取或研究开源项目，但不希望它混入长期自有项目。
5. 用户让 Codex 做一次实验、测试、脚本验证，后续可能不保留。
6. Codex 自身发生 Skill、Hook、全局规则、插件或 MCP 变化，需要回流到 C 点。

## 范围

- 新增 `program-workspace-governance` Skill，用于指导 Codex 判断产物归属。
- 新增 `program-artifact-tracker` Hook，用于在会话结束或压缩前记录事实和候选产物。
- 扩展现有 PreCompact 摘要卡片，增加“本轮产物和归档建议”。
- 新增 `program-curator` CLI，用于只读扫描、分类、生成整理计划，并按预授权策略自动执行低风险移动。
- 将长期知识和项目状态回流到 Obsidian 的现有 PARA 结构。
- 将 Codex 自身能力变化回流到 C 点。

## 模块独立性约束

`program-workspace-governance` 必须能单独安装、单独使用、单独移植给他人，不依赖 `context-summary-card` 或后续 `codex-task-continuity` 才能工作。

与其他组件联动时，只通过稳定的文件协议和可选编排层通信：

- 输入：artifact manifest、task ledger、用户命令或 CLI 参数。
- 输出：整理计划、move log、Obsidian 回流候选、`needs-review` 和 `trash-candidates` 记录。
- 禁止：跨组件直接调用内部函数、共享不可见状态、要求其他组件必须同时启用。

后续新增组件时，只需要扩展编排层读取/写入的协议，不应修改本组件核心分类和整理逻辑。

## 非目标

- 不永久删除文件；删除候选只能移动到隔离归档区。
- 不自动批量移动、重命名受保护项目。
- 不读取、保存或输出 `.env`、token、私钥、Cookie、账号密码。
- 不把完整聊天记录、完整 diff、大段终端日志写入 Obsidian。
- 不替代 Git、README、项目内文档或现有 Obsidian 项目页。
- 不把每个临时实验都强制沉淀为长期知识。

## 产物路由规则

| 产物类型 | 默认去向 | 说明 |
|---|---|---|
| 未分类想法、草稿 | Obsidian `00_Inbox/ideas/` | 只保存可复用摘要，不保存聊天噪声 |
| 新项目或原型代码 | `/Users/dysania/program/_inbox/` 或用户指定项目路径 | 进入正式项目前先生成项目卡片和整理建议 |
| 总结文档 | Obsidian `00_Inbox/`、`03_Resources/研究报告/` 或对应项目页 | 根据是否可复用、是否项目相关判断 |
| 开源项目分析 | Obsidian `03_Resources/开源项目分析/` | 如决定复刻或产品化，再链接到 `01_Projects/` |
| 临时实验和测试 | `/Users/dysania/program/_inbox/experiments/` 或系统临时目录 | 默认不进入长期记忆 |
| 项目状态、关键决策、验证结果 | 对应 Obsidian 项目页 | 只写证据、结论、下一步 |
| Codex Skill/Hook/规则变化 | `03_Resources/Codex工作台/` | 更新变更日志；涉及 Skill 时更新搜索索引 |

## 预授权自动整理策略

用户已授权 Codex 在以下边界内自动执行整理，不需要逐次确认。

### 允许自动创建的受控目录

```text
/Users/dysania/program/_inbox/
/Users/dysania/program/_experiments/
/Users/dysania/program/_external/
/Users/dysania/program/_archive/
/Users/dysania/program/_archive/trash-candidates/YYYY-MM-DD/
/Users/dysania/program/_inbox/needs-review/
```

### 允许自动移动的内容

- Codex 本轮新生成的文件或目录。
- `/Users/dysania/Documents/Codex` 下的散落产物。
- `/Users/dysania/program` 下明显不属于已有项目的孤立文档、实验目录和临时产物。
- 明确属于某项目的 Codex 总结、报告、handoff，可进入项目已有 `docs/`、`reports/`、`artifacts/`，或写入 Obsidian 对应项目页。

### 禁止自动移动的内容

- 已有 Git 仓库根目录。
- Git 仓库中的 tracked 文件。
- `.env`、私钥、Cookie、账号配置、数据库文件、凭据相关文件。
- Obsidian Vault 中已有笔记的大规模结构、文件名和链接体系。

### 删除候选处理

- 不直接执行永久删除。
- 明显缓存、构建产物、临时垃圾只能移动到：

```text
/Users/dysania/program/_archive/trash-candidates/YYYY-MM-DD/
```

- 后续通过任务提醒机制定期询问是否永久删除。

### 不确定内容处理

分类置信度不够时，不再询问用户，自动移动到：

```text
/Users/dysania/program/_inbox/needs-review/
```

同时记录原因、来源路径、建议处理方式和关联会话。

### Obsidian 自动回流权限

允许自动写入：

- `00_Inbox/ideas/`
- `01_Projects/Program 项目整理/`
- `03_Resources/Codex工作台/Codex 变更日志.md`
- `03_Resources/Codex工作台/Codex Skills 搜索索引.md`

不允许自动大规模改写已有笔记结构，不批量重命名 Obsidian 文件。

## 验收标准

- Skill 能明确判断“新项目、总结文档、开源参考、临时实验、Codex 自身变化”的默认去向。
- Hook 在失败时不阻塞 Codex 主流程。
- Hook 输出只包含事实、候选路径和建议，不执行破坏性文件操作。
- PreCompact 卡片能显示本轮产物清单、建议归档位置和是否需要 Obsidian 回流。
- CLI 默认只读扫描，`apply` 必须读取明确计划，并只能执行预授权低风险移动。
- 所有实现都有测试覆盖：路径分类、敏感信息过滤、dry-run 计划、预授权移动、隔离归档和受保护路径拒绝。
- Obsidian 写入遵守 Vault `AGENTS.md`，不破坏 frontmatter、wikilinks 和索引语义。

## 约束和假设

- `/Users/dysania/program/documents/obsidian_vault` 是长期记忆权威位置。
- `/Users/dysania/program` 是代码、项目、实验和外部参考的主要工作区。
- Hook 只能做轻量事实记录，不依赖它完成知识整理。
- 自动分类可以触发预授权低风险移动；受保护内容和高风险动作必须拒绝或进入 `needs-review`。
- 当前 `~/.codex/hooks.json` 已接入 PreCompact 摘要卡片 Hook。

## 已确认默认策略

1. 接受创建受控目录：`_inbox/`、`_experiments/`、`_external/`、`_archive/`。
2. 新项目默认先进入 `/Users/dysania/program/_inbox/`，后续确认成熟后再升级为正式项目。
3. `Documents/Codex` 下历史对话产物纳入扫描。
4. `program-curator apply` 允许按预授权策略自动移动低风险内容。
5. Obsidian 回流允许自动写入指定入口，但不允许大规模重构 Vault。

## 后续仍需设计的问题

1. 任务提醒和待办池如何与 `needs-review`、`trash-candidates` 联动。
2. 多 Agent 并发时如何合并同一任务的状态。
3. 每日摘要由自动化定时触发，还是在新会话启动时生成。
