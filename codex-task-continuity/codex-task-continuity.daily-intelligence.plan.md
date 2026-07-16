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

## 决策型日报重构

12. 将昨日工作改为项目优先的短卡片；活动采集正常路径和 Operation Ledger 降级路径都只保留可决策的结果与下一步，证据路径只留在 JSON。
13. 为仓库审计增加最后活动时间、明确阶段、处置优先级和持久忽略配置；`backend-cms-api` 作为非本人项目加入忽略。
14. 在 task ledger 增加当日仓库处置记录，保存已完成、近期开发暂缓、自动处理失败和忽略结果，供最终 DailyDigest 渲染。
15. 重写每日 Automation：先采集、关联项目任务、按仓库预算处理、记录结果、复扫，再展示最终卡片；不显示初始扫描和内部报告链接。
16. 超过 15 天且无近期任务的项目优先自动收尾；可精确关联任务时交回原任务执行或汇报，近期仍在开发则明确暂缓原因。
17. 重建 2026-07-16 摘要并执行首批高收益仓库动作，确认用户可一眼看到项目、结果、暂缓原因和确切失败步骤。

## 执行契约

- Intent Lock：只补齐跨任务等待、监控和恢复闭环，不修改 YA FundMind 业务代码、scheduler 计划或 RC 证据。
- Scope Fence：修改 task ledger、DailyDigest、相关测试、Skill/全局规则、两项现有 Automation 和长期记录。
- Approved Behavior：可观察且无业务选择的条件默认自动续作；监控只证明已登记和已检查，不能伪造条件满足或任务完成。
- Test Obligations：覆盖 follow-up 幂等更新、Automation 健康/失效/逾期、周期任务关联、并行轨道和日报文案。
- Rewind Trigger：如果必须读取完整 transcript、解析任意 Automation prompt 或修改项目业务状态才能判断，则停止自动推断，只登记人工续作。

## 决策型日报执行契约

- Intent Lock：日报是用户的决策与结果界面，不是内部审计报告的目录；用户不需要再打开内部文档理解发生了什么。
- Scope Fence：修改活动展示、仓库审计元数据、处置记录、DailyDigest、自动化 prompt、忽略配置和相关测试；不批量改写各业务仓库代码。
- Approved Behavior：项目名必须明确；可自动收尾直接执行；近期任务暂缓必须说明当前阶段；失败必须说明卡在哪一步及已完成到哪里。
- Activity Rule：以精确项目名为主键，每项摘要最多 3 行；隐藏 evidence 路径、上下文卡片原文、线程 UUID 和内部报告链接。
- Repository Rule：15 天是自动处置优先级，不是取消安全门；force、冲突、安全敏感改动和测试失败仍停止，并记录精确失败步骤。
- Budget Rule：写预算按仓库计算；同一仓库内多个已合并分支清理属于一个仓库动作批次。
- Test Obligations：覆盖项目优先短卡、文本上限、内部证据隐藏、明确仓库阶段、15 天优先级、忽略配置、处置记录和最终分组。
- Rewind Trigger：如果项目归属只能靠标题猜测、远端不属于当前用户、改动包含敏感文件或需要 force，则忽略或记录精确失败，不自动合并。
