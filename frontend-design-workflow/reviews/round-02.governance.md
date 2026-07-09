# Skill 治理结论 Round 02

- Skill：`frontend-design-workflow`
- 结论：继续写入全局 + 更新索引/变更日志
- 理由：本轮不是新增入口，而是增强同一个前端 UI 默认入口；新增 Design Lock、截图评分门禁和三层设计记忆，直接解决跨轮 UI 漂移和“代码能跑但视觉失败”的问题。
- 需要修改：
  - 更新 `SKILL.md`：加入设计记忆、Design Lock、组件来源层、Visual Verdict、Fix 循环。
  - 更新调研摘要，记录 StyleSeed、21st.dev Magic MCP、Visual Verdict、Browser QA 的采纳判断。
  - 同步全局安装副本。
  - 更新 Obsidian Skills 搜索索引和 Codex 变更日志。
- 不需要修改：
  - 不创建 `ui-master` 等多个子 skill。
  - 不默认安装或启用 StyleSeed、21st.dev Magic MCP、Visual Verdict、Browser QA。
  - 不更改全局路由规则；现有 `frontend-design-workflow` 入口仍然足够。
- 触发词建议：沿用现有触发词，新增 Design Lock、视觉评分、截图门禁、Visual Verdict、设计漂移、跨轮 UI。
- 验证建议：
  - `quick_validate.py frontend-design-workflow`
  - `git diff --check`
  - 在 Codex Profile Switcher 上执行一次真实 UI 重构压力测试。
