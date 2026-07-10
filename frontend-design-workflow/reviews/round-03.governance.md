# Skill 治理结论 Round 03

- Skill：`frontend-design-workflow`
- 结论：继续作为全局前端 UI 默认入口，增强现有 Skill；不新增子 Skill，不修改全局路由。
- 理由：Codex Profile Switcher 的真实压力测试证明，Round 02 已有 Visual Verdict 和 Fix 循环仍存在执行漏洞。Agent 在截图明显越界、背景穿透、没有参考并排对照时，仍以“结构已经对了、截图已保存、测试和编译通过”为理由提交并打 tag。
- 需要修改：
  - 增加严格复刻模式和参考基线，要求目标截图、真实渲染分支、版本/commit、区域映射和允许偏离。
  - 增加原生窗口与 Web 的几何模型，覆盖根表面、滚动层、固定层、min/default/max、裁切和长文本。
  - 定义有效截图证据；无有效对照时结论为 `INCONCLUSIVE`。
  - 将文字重叠、内容越界、外框穿透和关键区域缺失设为不可被平均分抵消的硬失败。
  - 视觉 PASS 前禁止发布、打 tag、正式版本 bump 或宣称完成。
  - 同步全局安装副本，更新 Obsidian Skills 搜索索引和 Codex 变更日志。
- 不需要修改：
  - 不新增视觉评分脚本；当前首先缺的是证据约束和执行纪律。
  - 不安装外部 UI Skill 或默认接入第三方服务。
  - 不把 Codex Profile Switcher 的具体 AppKit 修复写进通用 Skill。
- 触发词建议：严格复刻、照着做、参考差距大、窗口包不住、滚动穿出、横向溢出、文字裁切、截图验收失真。

## 压力测试证据

失败产物：

- `/tmp/codex-profile-switcher-ui/dashboard-v090.png`
- `/tmp/codex-profile-switcher-ui/menu-popover-v090.png`

失败行为：

- 主面板固定 1080 内容宽度，但窗口未设置 min/max；窗口缩小时必然横向越界。
- 根表面只覆盖 viewport，透明 documentView 在滚动时缺少完整表面/裁切边界。
- 菜单弹窗的装饰字符主动制造了穿透噪声。
- 截图包含其他应用和复杂背景，没有与 codexU 同比例逐区对照。
- Agent 没有输出要求中的 Visual Verdict 分数，却在源码测试、Swift 编译和安装通过后直接标记完成。

Round 03 的规则只针对这些已观察到的漏洞，不扩展无关流程。
