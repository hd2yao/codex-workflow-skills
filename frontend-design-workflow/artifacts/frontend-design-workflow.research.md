# frontend-design-workflow 调研摘要

日期：2026-07-09

## 结论

推荐新增轻量入口 `frontend-design-workflow`，不直接全量安装外部重型 skill。新入口负责把“参考项目/源码/截图 -> 视觉 DNA -> 当前项目差距 -> 设计契约 -> 实现 -> 截图验收”固化成默认流程。

直接采用：

- Anthropic `frontend-design` 的“两遍设计：plan -> critique -> build -> critique again”。
- Superdesign 的“现有 UI 先像素级复现，再 branch 变体”。
- UIUX Pro Max 的“查询式设计系统、Master + page override、设计 dials”思路。
- Impeccable 的“反 AI 味清单、critique/audit/polish 分离、检测与浏览器证据分离”。
- Microsoft `frontend-design-review` 的“三柱评审：frictionless insight-to-action / quality craft / trustworthy building”。
- Claude Design Skill 的“先确认输出/保真/变体/品牌上下文，真实浏览器验证 artifact”。

不建议直接采用：

- 不把 UIUX Pro Max 的大 CSV 知识库作为默认全局入口，会增加上下文和安装复杂度。
- 不默认启用 Impeccable hooks/命令体系，避免与现有 Codex 工作台规则冲突。
- 不把 Claude Design Skill 当作产品前端重构入口；它更适合 HTML artifact 和视觉探索。

## 用户例子校验

| 例子 | 状态 | 判断 |
|---|---|---|
| UIUX Pro Max | 部分符合 | 真实开源项目，GitHub `nextlevelbuilder/ui-ux-pro-max-skill`，MIT，v2.10.2，103k+ stars；适合查风格/字体/色彩/UX/技术栈规则，但默认全量安装过重。 |
| Claude Design / Claude Design Skill | 部分符合 | `jiji262/claude-design-skill` 是便携版 Claude Design 提示词，MIT，适合 HTML artifact、设计画布、原型和多变体；对产品前端重构需补源码/组件/截图闭环。 |
| Anthropic frontend-design | 符合子能力 | 官方 skill 解决泛化审美和 AI 模板感，强调主题、字体、结构和自我批评；不处理参考项目源码拆解。 |

## 候选清单

| 候选 | 来源 | 证据等级 | 匹配度 | 可借鉴点 | 不建议使用点 |
|---|---|---|---|---|---|
| Anthropic `frontend-design` | https://github.com/anthropics/skills | A | 高 | 主题 grounding、token plan、自我批评、避免模板默认 | 单文件偏审美指导，缺少参考源码和当前项目映射 |
| UIUX Pro Max | https://github.com/nextlevelbuilder/ui-ux-pro-max-skill | A | 高 | 搜索脚本、设计系统生成、Master/override、设计 dials、UX checklist | 默认全量安装和数据集太重，可能压过本项目组件约束 |
| Impeccable | https://github.com/pbakaus/impeccable | A | 高 | 命令路由、PRODUCT/DESIGN 上下文、反模式检测、critique/audit/polish | hooks 和命令体系重，不适合直接并入默认工作流 |
| Superdesign | https://github.com/superdesigndev/superdesign-skill | A | 高 | 先复现当前 UI，再 branch 变体；强调真实渲染分支和完整 UI 上下文 | 依赖 CLI/登录/画布工具，不能替代代码级验收 |
| Microsoft `frontend-design-review` | https://github.com/microsoft/skills | A | 中高 | 三柱评审、设计系统 compliance、quick checklist | 更偏评审，不完整覆盖参考项目到实现 |
| `jiji262/claude-design-skill` | https://github.com/jiji262/claude-design-skill | A | 中 | 工作流、品牌资产协议、输出格式、浏览器验证 | 更适合 HTML artifact，不宜直接用于项目代码重构 |
| `bergside/awesome-design-skills` | https://github.com/bergside/awesome-design-skills | A | 中 | DESIGN.md / SKILL.md 设计风格库 | 风格目录本身不是工作流 |

## 当前流程缺口

- `frontend-ui-guardrail` 能守住任务/信息/布局/风格/验收下限，但对“参考项目源码如何拆”不够细。
- `superdesign` 已有工具流程，但需要前置参考拆解和后置代码验收，否则会生成泛化变体。
- 当前缺少“视觉 DNA”结构化输出和“参考映射 -> 当前项目差距 -> 设计契约”的中间产物。

## 采用路线

P0：

- 新增 `frontend-design-workflow`，作为前端 UI 设计/重构/仿参考的默认入口。
- 更新全局 `AGENTS.md` 的短路由。
- 同步到 `~/.codex/skills`，更新 Obsidian 索引和变更日志。

P1：

- 用真实项目（例如 Codex Profile Switcher）做压力测试：同一参考项目、同一任务，新旧流程各跑一次，对比截图。
- 若反复需要自动检测 AI 味，再考虑引入轻量检测脚本或外部 Impeccable 的单次 audit，而不是启用 hooks。

P2：

- 若 UIUX Pro Max 的查询库稳定有价值，再独立评估是否安装为手动调用 skill。

## Round 02 补充判断

用户提供的二次分析整体可取，但应收敛成当前 skill 的增强版，而不是立刻拆成 6-7 个子 skill。

新增核对来源：

| 候选 | 来源 | 证据等级 | 采用判断 |
|---|---|---|---|
| StyleSeed | https://github.com/bitjaru/styleseed | A | 吸收 Design Lock、Quality Gate、反 AI 味规则；不全量安装或搬运其组件/规则库。 |
| 21st.dev Magic MCP | https://github.com/21st-dev/magic-mcp | A | 作为“组件来源层”概念；因需要 API key 和外部生成能力，不默认接入。 |
| Visual Verdict | https://github.com/vibeeval/vibecosystem/blob/main/skills/visual-verdict/SKILL.md | A | 吸收截图评分维度、PASS/REVISE/FAIL、迭代上限；抽象为工具无关流程。 |
| Browser QA / ECC | https://github.com/affaan-m/ECC/blob/main/skills/browser-qa/SKILL.md | A | 吸收真实浏览器验证、只读优先、安全边界、无 baseline 则 INCONCLUSIVE 的思想。 |

采纳进 `SKILL.md`：

- 三层设计记忆：全局 UI 规则、项目 `DESIGN.md`、页面 `VISUAL_ACCEPTANCE.md` / 截图历史。
- Design Lock：设计契约或项目 `DESIGN.md` 确认后，后续迭代必须说明保持/修改/废弃原因。
- Visual Verdict：布局、字体、色彩、响应式、交互状态、内容完整度、参考一致度、反 AI 味，默认 90 PASS / 70-89 REVISE / <70 FAIL。
- Fix 循环：每轮最多修 3 个最高影响问题，最多 5 轮；连续两轮提升不足时回到参考拆解或设计契约。
- 组件来源层：先项目内组件，再参考项目结构，最后外部组件来源；外部来源不决定整体视觉。

暂不采纳：

- 不拆 `ui-master / ui-brief / reference-analyzer / design-system / ui-implementer / visual-reviewer / ui-fixer` 多 skill 架构。当前还没经过真实项目压力测试，过早拆分会增加触发混乱。
- 不强制每次落盘 `PRODUCT_UI_BRIEF.md`、`REFERENCE_ANALYSIS.md`、`DESIGN.md`。小任务在聊天中输出；中大型或跨轮任务才落盘。
- 不默认接入 21st.dev Magic MCP、Visual Verdict 原 skill、Browser QA 原 skill 或 StyleSeed hooks。
