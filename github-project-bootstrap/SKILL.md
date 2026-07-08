---
name: github-project-bootstrap
description: 适用于用户想根据项目描述创建或复用本地项目，并需要在个人 GitHub 创建仓库、初始化或连接 git、排除敏感/生成物、完成首次提交和远端推送。
---

# GitHub 项目初始化

用这个 skill 把一段项目描述转成一个已命名的本地项目目录，或把已有项目安全连接到新建 GitHub 仓库。

开始时先说明：`我会用 github-project-bootstrap 根据项目描述生成仓库名，在你的个人 GitHub 创建仓库，并把本地项目目录连接到这个仓库。`

## 默认行为

- 仓库/项目名称：根据用户描述生成简洁的英文 kebab-case slug，通常 2-5 个词。
- GitHub 账号：默认不传 `--owner`，让 `gh` 使用当前已认证的个人账号；只有用户明确指定 owner 时才传入。
- 仓库可见性：默认 `private`；只有用户明确要求公开时才使用 `public`。
- 父目录：默认使用当前工作目录；如果用户指定路径，则使用用户给出的路径。
- 本地目录：`<parent-dir>/<repo-name>`。
- 新项目：创建 `README.md`，提交初始 commit，再创建远端和 push。
- 已有项目：只有用户明确要求复用时才使用 `--use-existing-dir`；如果需要提交现有项目文件，加 `--commit-existing-files`。
- 大文件保护：提交已有项目文件前默认阻止超过 20 MB 的 staged 文件；确需提交时才使用 `--allow-large-files`。

## 工作流

1. 确认已有项目描述。
   如果用户还没有提供项目描述，只问一个简短问题补齐。不要向用户索要 GitHub token、密钥或任何凭据。

2. 生成仓库名。
   只使用小写 ASCII 字母、数字和连字符。避免 `new-project`、`app`、`repo` 这类泛泛名称。如果用户描述不是英文，先把项目意图翻译成简短英文 slug，再运行脚本。

3. 先运行 dry-run。
   使用 [scripts/create_github_project.py](scripts/create_github_project.py)：

   ```bash
   python3 /Users/dysania/program/codex-workflow-skills/github-project-bootstrap/scripts/create_github_project.py \
     --description "PROJECT DESCRIPTION" \
     --repo-name "chosen-repo-name" \
     --parent-dir "/absolute/parent/dir" \
     --dry-run
   ```

4. 执行创建流程。
   如果 dry-run 计划符合用户请求，用同一条命令去掉 `--dry-run` 后执行。

   ```bash
   python3 /Users/dysania/program/codex-workflow-skills/github-project-bootstrap/scripts/create_github_project.py \
     --description "PROJECT DESCRIPTION" \
     --repo-name "chosen-repo-name" \
     --parent-dir "/absolute/parent/dir"
   ```

   公开仓库使用 `--visibility public`。只有用户明确要求组织账号或其他账号时才加 `--owner OWNER`。

   连接已有项目时使用：

   ```bash
   python3 /Users/dysania/program/codex-workflow-skills/github-project-bootstrap/scripts/create_github_project.py \
     --description "PROJECT DESCRIPTION" \
     --repo-name "existing-project-name" \
     --parent-dir "/absolute/parent/dir" \
     --use-existing-dir \
     --commit-existing-files
   ```

   这会补充默认 `.gitignore` 安全规则、`git add -A`、检查 staged 文件大小，再创建初始提交。不要为了绕过失败直接使用 `--allow-large-files`；先判断大文件是否是音视频、模型、缓存、运行产物或应走 Git LFS/本地 artifacts。

5. 验证结果。
   运行：

   ```bash
   git -C "/absolute/parent/dir/chosen-repo-name" status --short --branch
   git -C "/absolute/parent/dir/chosen-repo-name" remote -v
   gh repo view --json name,url,visibility,defaultBranchRef
   ```

   `gh repo view` 要在新项目目录中运行，这样它会读取已连接的 `origin` remote。

6. 汇报结果。
   包括生成的仓库名、本地项目绝对路径、GitHub URL、默认分支，以及初始 push 是否成功。

## 失败处理

- 如果缺少 `gh`，告诉用户需要安装 GitHub CLI，或改用可用的 GitHub connector fallback；不要编造凭据。
- 如果 `gh auth status` 失败，要求用户先运行 `gh auth login` 完成认证，然后停止。
- 如果本地目录已经存在，除非用户明确要求复用，否则停止。
- 如果 GitHub 上同名仓库已经存在，换一个更清晰的备用名称，或先询问用户是否要复用/改名。
- 如果 staged 文件超过默认 20 MB，先把生成物、本地数据、音视频、模型权重加入 `.gitignore` 或移出提交，再重试。
- 如果仓库创建成功但 push 失败，先验证 `origin`、分支、GitHub 仓库可见性，再直接重试 `git push -u origin <branch>`；不要重新创建仓库。
- 如果 HTTPS push 反复超时，检查是否仍有大对象在本地 git 历史中；必要时从提交中移除并清理不可达对象后再推送。

## 脚本说明

脚本只有在不使用 `--dry-run` 时才会执行这些真实动作：

- 检查 `git`、`gh` 和 `gh auth status`
- 检查目标 GitHub 仓库是否已经存在
- 创建项目目录
- 在 `main` 分支初始化 git
- 写入 `README.md`，除非用户传入 `--no-readme`
- 新项目默认只提交 `README.md`
- 已有项目配合 `--commit-existing-files` 时，会补 `.gitignore`、stage 全部未忽略文件、检查大文件、创建初始提交
- 运行 `gh repo create <repo> --private|--public --source <dir> --remote origin`
- 运行 `git push -u origin <branch>`

永远不要把 token、`.env` 值、私钥或凭据写入命令、代码或日志。
