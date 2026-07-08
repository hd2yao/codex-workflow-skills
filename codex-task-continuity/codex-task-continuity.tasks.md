# Codex Task Continuity 任务拆分

- [x] 任务 1：确认任务连续性规格
  验收：用户确认状态模型、保存位置、Hook 触发点和每日摘要方式。

- [x] 任务 2：编写 `codex-task-continuity/SKILL.md`
  验收：能指导 Codex 查询任务、更新状态、处理“放到待做/暂放/不要了”等用户指令。

- [x] 任务 3：实现 `task-ledger.py`
  验收：支持 `add/list/update/digest/import-artifacts/import-curator`，并有单元测试。

- [x] 任务 4：实现 `task-continuity-hook.py` Hook
  验收：支持 Stop / PreCompact / SessionStart dry-run；失败不阻塞。

- [ ] 任务 5：接入 Program Governance
  验收：能从 `needs-review`、`trash-candidates`、artifact manifest 和 move log 生成任务。

- [ ] 任务 6：接入摘要卡片
  验收：PreCompact 摘要中可显示未完成任务、等待确认和清理候选。

- [ ] 任务 7：Obsidian 回流
  验收：每日摘要、正式项目下一步、Codex 自身任务能按规则写入对应 Vault 位置。

- [ ] 任务 8：治理评审
  验收：用 `skill-governance-review` 判断是否写入全局短入口、是否安装全局、是否更新 C 点索引。

- [ ] 任务 9：最终验证
  验收：单元测试、Hook dry-run、CLI dry-run、敏感信息扫描、并发写入测试通过。
