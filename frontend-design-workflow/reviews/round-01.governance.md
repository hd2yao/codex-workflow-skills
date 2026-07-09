# Skill 治理结论

- Skill：`frontend-design-workflow`
- 结论：写入全局 + 更新索引
- 理由：这是跨项目高频的前端 UI 入口型工作流，解决“给了参考项目/源码/截图仍做成泛化 AI UI”的默认流程问题；仅靠现有 `frontend-ui-guardrail` 和 `superdesign` 不足以覆盖参考拆解、视觉 DNA、当前差距、设计契约和截图返工闭环。
- 需要修改：
  - 新增源码目录：`/Users/dysania/program/codex-workflow-skills/frontend-design-workflow/`
  - 同步安装：`/Users/dysania/.codex/skills/frontend-design-workflow/`
  - 全局 `AGENTS.md` 增加 1 条短路由。
  - 更新 Obsidian `Codex Skills 搜索索引.md` 和 `Codex 变更日志.md`。
- 不需要修改：
  - 不全量安装 UIUX Pro Max、Impeccable 或 Claude Design Skill。
  - 不替换 `frontend-ui-guardrail`；新 skill 作为上层流程，guardrail 继续作为质量下限。
  - 不启用外部 hooks。
- 触发词建议：前端 UI 设计、UI 重构、仿照参考项目、参考截图、开源源码、设计系统、AI 味、审美泛化、布局遮挡、截图验收失败。
- 验证建议：
  - `quick_validate.py frontend-design-workflow`
  - `git diff --check`
  - 后续用 Codex Profile Switcher 做真实压力测试：同一参考项目和目标界面，验证是否产出参考拆解、设计契约和多视口截图返工。
