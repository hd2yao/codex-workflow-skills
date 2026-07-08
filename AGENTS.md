# Project rules for `/Users/dysania/program/codex-workflow-skills`

These rules are additive to the global `~/.codex/AGENTS.md`.

## Repository role
- This directory is the source/workbench for Codex workflow skills.
- Use it for Codex, Program, Obsidian, hook, automation, cross-project default-entry, governance, task continuity, project audit, research workflow, and GitHub bootstrap skills.
- Do not put domain-only automations, web flow experiments, captcha helpers, ad report downloaders, or project-specific idea skills here; keep those in `/Users/dysania/program/skills`.

## Skill directory workflow
- Every new skill starts by creating a dedicated subdirectory in this repository root.
- The subdirectory name must use the skill slug exactly: `./<skill-slug>/`.
- Keep all files for a skill inside its own `./<skill-slug>/` directory.
- Do not write discovery, plan, review, validation, or handoff files to the repository root.

## Global installation
- A skill in this repository is intended to have a global installable copy when active.
- Edit the source directory here first, then sync the full skill directory to `~/.codex/skills/<skill-slug>/` after validation.
- Remove or archive the installed copy when a skill is merged into a parent skill, replaced, or no longer intended to be globally discoverable.
- Do not sync `.DS_Store`, `__pycache__`, run outputs, screenshots with private data, credentials, tokens, cookies, or `.env` values.

## Skill governance
- Before creating, updating, installing, archiving, renaming, removing, or promoting a skill, use `skill-governance-review`.
- If the change affects Codex itself, update Obsidian:
  - `/Users/dysania/program/documents/obsidian_vault/03_Resources/Codex工作台/Codex Skills 搜索索引.md`
  - `/Users/dysania/program/documents/obsidian_vault/03_Resources/Codex工作台/Codex 变更日志.md`
- Do not copy full skill bodies into global `AGENTS.md`; add only short routing rules when the skill is a default entry.

## Skill description style
- Write visible skill descriptions in Chinese.
- This rule applies to `SKILL.md` frontmatter `description` and agent-facing copy such as `short_description` or similar summary text.
- Describe triggering conditions and scope; do not spend the description on workflow details.
- Do not frame a skill as exclusive to a single AI Agent brand unless that exclusivity is technically required.

## Expected structure
- Each skill directory should contain `SKILL.md` as the final skill document.
- Use `./<skill-slug>/reviews/` for review round artifacts.
- Use `./<skill-slug>/artifacts/` for screenshots, verification notes, or other supporting materials when needed.
- Name working markdown files with the skill slug prefix when practical, for example:
  - `./<skill-slug>/<skill-slug>.discovery.md`
  - `./<skill-slug>/<skill-slug>.plan.v1.md`
  - `./<skill-slug>/reviews/round-01.review.md`

## Repository hygiene
- The repository root should stay readable; avoid scattering one-off workflow files outside the skill directory.
- If an existing skill is being updated, reuse its current `./<skill-slug>/` directory instead of creating a second container.
