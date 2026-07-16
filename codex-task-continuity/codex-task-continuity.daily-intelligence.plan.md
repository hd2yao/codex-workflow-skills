# Codex 每日连续性增强 Plan

1. 扩展 task ledger，保存前一日线程活动并供 DailyDigest 读取。
2. 新增周期任务审计器和项目声明格式，接入 DailyDigest。
3. 给 `ya-fundmind` 添加声明并验证 daily/weekly 实际状态。
4. 修正仓库比较字段，增加有界动态动作预算。
5. 更新 Skill、自动化 prompt、全局安装副本和 Obsidian 记录。
6. 重跑测试与当日日报，核对漏召回和周期状态。

## 续作监控增强

7. 在 task ledger 中新增独立 follow-up 状态，避免把“一个 gate 等待”错误等同于整个任务 `blocked`。
8. DailyDigest 读取 follow-up，校验绑定 Automation 的 ACTIVE 状态、目标线程和下次检查回写，并关联项目周期任务证据。
9. 每日摘要展示等待条件、恢复动作、并行轨道和用户操作；监控失效或逾期时升级提醒。
10. 更新全局入口规则与每日自动化：目标进入外部等待前必须登记 follow-up；确定性条件默认绑定自动续作，没有安全自动检查时才要求人工恢复。
11. 登记 YA FundMind V2 的 3 次 post-RC 运行观察门，保留 22:15 heartbeat，并明确前端 worktree 是并行轨道。

## 执行契约

- Intent Lock：只补齐跨任务等待、监控和恢复闭环，不修改 YA FundMind 业务代码、scheduler 计划或 RC 证据。
- Scope Fence：修改 task ledger、DailyDigest、相关测试、Skill/全局规则、两项现有 Automation 和长期记录。
- Approved Behavior：可观察且无业务选择的条件默认自动续作；监控只证明已登记和已检查，不能伪造条件满足或任务完成。
- Test Obligations：覆盖 follow-up 幂等更新、Automation 健康/失效/逾期、周期任务关联、并行轨道和日报文案。
- Rewind Trigger：如果必须读取完整 transcript、解析任意 Automation prompt 或修改项目业务状态才能判断，则停止自动推断，只登记人工续作。
