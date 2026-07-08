# codex-error-learning-loop 治理评审

## Skill 治理结论

- Skill：`codex-error-learning-loop`
- 结论：新增为全局可发现的 Codex 工作流 Skill；同步 Obsidian 索引和 Codex 变更日志；暂不写入全局 `AGENTS.md`
- 理由：这是跨项目高频工作流能力，处理用户纠错、范围漂移、上下文污染、搜索漏召回和验证声明不实等问题；但它应由明确纠错信号触发，不应让所有任务默认进入复盘流程。
- 需要修改：新增源码目录 `codex-error-learning-loop/`；验证后同步到 `~/.codex/skills/codex-error-learning-loop/`；更新 `Codex Skills 搜索索引.md` 和 `Codex 变更日志.md`。
- 不需要修改：不改全局 `AGENTS.md`，不接 Hook，不自动写长期记忆，不安装外部 `darwin-skill`。
- 触发词建议：`你理解错了`、`不是这个项目`、`你发散了`、`应该先问我`、`反复返工`、`验证声明不实`、`搜索漏了`、`纠错账本`。
- 验证建议：检查 frontmatter 和 `agents/openai.yaml`；用 3 个场景人工校验：需求误读、跨项目误改、搜索漏召回。
