# Program Workspace Governance 任务拆分

- [x] 任务 1：完成需求评审
  验收：用户确认 `spec.md` 中的范围、非目标、默认目录和预授权自动整理策略。

- [x] 任务 2：编写 `program-workspace-governance/SKILL.md`
  验收：frontmatter 中文描述只写触发条件；正文包含产物分类矩阵、Obsidian 路由、Hook 边界和安全规则。

- [x] 任务 3：治理评审
  验收：使用 `skill-governance-review` 判断是否写入全局 `AGENTS.md`、是否安装到全局、是否更新 Obsidian C 点。

- [x] 任务 4：实现 `program-artifact-tracker.py`
  验收：可从 Stop Hook stdin 和 transcript 生成 manifest；失败不阻塞；敏感信息脱敏。

- [ ] 任务 5：扩展 PreCompact 摘要卡片
  验收：卡片新增“本轮产物和归档建议”；无 manifest 时可降级；测试覆盖。

- [x] 任务 6：实现 `program-curator scan/plan/report`
  验收：只读扫描 `/Users/dysania/program`；跳过 secrets；输出 JSON 和 Markdown 计划。

- [x] 任务 7：实现 `program-curator apply`
  验收：按预授权策略自动移动低风险内容；只移动不永久删除；保护 Git 仓库根目录、tracked 文件和敏感路径；生成 move log；支持 dry-run。

- [ ] 任务 8：Obsidian 回流
  验收：Codex 变更记录到 `Codex 变更日志.md`；涉及 Skill 时更新 `Codex Skills 搜索索引.md`；Program 整理进度更新到项目页。

- [ ] 任务 9：最终验证
  验收：运行单元测试、Hook dry-run、CLI dry-run；检查 git diff；确认未修改无关项目和未记录敏感信息。

- [ ] 任务 10：联动任务提醒机制
  验收：`needs-review`、`trash-candidates` 和未完成产物能进入任务待办池，后续每日摘要提醒用户处理。
