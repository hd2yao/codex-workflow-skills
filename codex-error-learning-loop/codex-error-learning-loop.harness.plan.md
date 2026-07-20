# 周度 Harness 学习闭环实现方案

## 推荐方案

采用“静默观察 Hook + 结构化账本 + 周度 Agent 复盘 + 持久候选状态”四层架构。Hook 只捕捉显式纠正并记录；周度 Agent 读取上一自然周的项目活动、仓库处置、观察记录和已有能力索引，完成语义聚类与治理判断；用户看到独立周总结卡片。

## 第一性原理评审

- 用户真正需要的不是更多内部报告，而是可见、可追踪、能验证效果的改进闭环。
- 单次纠正信噪比不足，不能直接改变全局行为；跨独立线程重复才说明 Harness 存在系统性缺口。
- “生成文件”不等于“完成交付”；周总结必须实际投递，并包含候选后续状态。
- 改进对象不只包括 Skill，也可能是 Hook、Automation、工具、评测、上下文入口或局部规则。

## 架构和数据流

```text
Stop / PreCompact
  -> error-learning-hook.py（静默筛选、游标、去重）
  -> error-learning-ledger.py（observations）

每周一 Automation
  -> 上一周 activity / repository resolutions / operation changes
  -> observations + workflow pattern report + installed skills
  -> 第一性原理聚类 + 对抗式反例检查
  -> candidates 生命周期更新
  -> period-review 保存并渲染周总结
  -> 摘要归档线程可见投递
```

## 变更文件

- `codex-error-learning-loop/`：新增账本、Hook、hooks 配置、测试和 Skill 说明。
- `workflow-pattern-retrospector/`：支持上一自然周、已有 Skill 对照和候选增量状态。
- `codex-task-continuity/`：新增周总结结构化保存/渲染入口，原始拼接文件改称周归档。
- `~/.codex/hooks.json`：安装静默观察 Hook。
- `~/.codex/automations/`：新增周一 Harness 复盘 Automation。
- Obsidian Codex 工作台：同步变更日志和 Skills 索引。

## 测试和验证

- 观察 Hook：纠正命中、普通消息跳过、游标增量、幂等、脱敏、失败静默。
- 错误账本：记录、查询、候选状态机、跨线程门槛、周期范围。
- 流程复盘：上一自然周边界、已有能力映射、状态持续。
- 周总结：结构化保存、用户可见渲染、无内部路径、无原始 transcript。
- 集成：真实回填 2026-07-13 至 2026-07-19，验证归档线程收到独立卡片。

## 风险和回滚

- 误报：观察事件保持 `observed`，周度聚类前不触发改动。
- Hook 性能：按 transcript 字节游标增量读取，异常直接退出 0。
- 过拟合：独立线程门槛、治理门槛、回归场景和观察周期共同约束。
- 回滚：从全局 `hooks.json` 移除观察命令并停用周度 Automation；历史账本保留只读。

## 执行契约

- 先补失败测试，再写实现。
- 单线程普通纠错不能进入 `trial`。
- 用户周总结不得展示原始 transcript、内部 evidence 路径或候选 JSON。
- Hook 不打印提示，不修改 Skill，不调用网络。
- 周度 Automation 可自动记录和规划；实际 Skill 变更必须先治理、后测试，并使用独立可回滚提交。
