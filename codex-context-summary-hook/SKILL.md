---
name: codex-context-summary-hook
description: 当需要在 Codex 上下文压缩前保留跨项目会话摘要、追踪长任务上下文或回看压缩前决策时使用。
---

# Codex Context Summary Hook

## 概览

这个技能提供一个 Codex `PreCompact` Hook：压缩前读取本地 transcript，生成 Markdown 摘要卡片，并通过 `systemMessage` 在 Codex 中显示卡片路径和预览。

## 何时使用

- 长任务可能触发上下文压缩，需要压缩前留一张可回看的摘要卡片。
- 多项目工作时，希望摘要统一保存到 `~/.codex/context-cards/`。
- 需要本地、无网络、无 API key 的轻量摘要归档。

## 文件

- `scripts/context-summary-card.py`: Hook 主脚本。
- `tests/context_summary_card_test.py`: 解析、写卡片、脱敏行为的单元测试。
- `hooks.json`: 可合并到 `~/.codex/hooks.json` 的配置样例。

## 安装

```bash
mkdir -p ~/.codex/hooks
cp /Users/dysania/program/codex-workflow-skills/codex-context-summary-hook/scripts/context-summary-card.py ~/.codex/hooks/context-summary-card.py
chmod +x ~/.codex/hooks/context-summary-card.py
```

将 `hooks.json` 中的 `PreCompact` 配置合并到 `~/.codex/hooks.json`。默认卡片目录是 `~/.codex/context-cards/`；也可以用 `CODEX_CONTEXT_CARD_DIR` 指向其他跨项目目录。

## 验证

```bash
python -m unittest /Users/dysania/program/codex-workflow-skills/codex-context-summary-hook/tests/context_summary_card_test.py
```
