---
name: obsidian-memory-workflow
description: Use when work should read from or write to the user's Obsidian vault, long-term memory, project pages, daily notes, knowledge base, resource distillation, research reports, or follow-up records.
---

# Obsidian 记忆工作流

## 核心原则

Obsidian 是长期记忆母库、项目执行中枢和资源蒸馏工厂。只沉淀可复用事实，不把聊天噪声、日志和临时失败过程塞进 Vault。

## 必读入口

Vault 路径：

```text
/Users/dysania/program/documents/obsidian_vault
```

写入或整理前先读：

- `AGENTS.md`
- `README.md`
- 相关目录的 `_Index.md`
- 若涉及项目，再读对应项目页

## 分类路由

| 内容 | 位置 | 判断标准 |
|---|---|---|
| 未分类想法、链接、截图、临时捕获 | `00_Inbox/` | 还不知道归属 |
| 有目标、下一步、验收标准的事项 | `01_Projects/` | 可以推进和验收 |
| 长期责任域和原则 | `02_Areas/` | 需要长期维护 |
| 文章、视频、开源项目、参考资料、研究报告 | `03_Resources/` | 可复用但不一定要执行 |
| 完成、暂停、不再活跃内容 | `04_Archives/` | 暂时不推进 |
| 日报、周报、月报 | `05_Daily/` | 时间线和回顾入口 |
| 模板 | `06_Templates/` | 可复用结构 |
| 图片、PDF、音视频、导出附件 | `07_Attachments/` | 非 Markdown 附件 |

## 项目回流

中大型项目任务完成后，只把这些内容写回 Obsidian：

- 当前状态
- 关键决策
- 验证结果
- 风险和阻塞
- 下一步
- 相关仓库文件或报告链接

不要写入：

- secrets、token、Cookie、`.env` 值
- 完整代码 diff
- 大段终端日志
- 依赖、缓存、构建产物
- 无复用价值的临时尝试

## Resources 蒸馏

外部资料至少保留：

```yaml
type: source
source_platform:
source_url:
topic:
status: inbox
related_projects: []
```

蒸馏时输出：

- 三句摘要
- 关键洞察
- 可执行动作
- 可借鉴点
- 不建议照搬点
- 关联项目、主题或创作者

## Daily 回流

日报只写时间线：

- 今天推进了什么项目
- 今天吸收了什么资源
- 哪些内容需要回流

长期结论必须回流到项目页、资源页或 Area 页面，不长期留在日报里。

## 写入边界

- 批量移动、批量重命名、删除非示例内容前，先列计划和受影响文件。
- 保留 frontmatter、wikilinks、标题层级和索引语义。
- 新建笔记优先使用 `06_Templates/` 中的模板结构。
- 写完后检查链接、目录位置、敏感信息和是否需要更新 `_Index.md`。

## 与 Hook 的关系

Hook 只负责自动记录事实或生成候选摘要。是否进入 Obsidian，需要按本工作流判断和过滤。
