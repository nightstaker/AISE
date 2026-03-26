# Git 工作流程规范 - AISE 项目

## 📋 开发流程

### 1. 特性分支开发
- ✅ **每次开发前，从 main 分支创建特性分支**
- 命名格式：`feature/<描述>` 或 `fix/<描述>`
- 示例：`feature/task-dependency-verification`

```bash
# 确保 main 是最新的
git checkout main
git pull origin main

# 创建特性分支
git checkout -b feature/<描述>
```

### 2. 本地开发
- 使用 TDD（Test-Driven Development）方法
- 每次提交前在本地运行所有检查：
  - `ruff check src/ tests/`
  - `ruff format --check src/ tests/`
  - `pytest --tb=short -q`

### 3. PR 提交
- 提交 PR 到 main 分支
- 使用有意义的标题和描述
- 确保 PR 包含所有相关修改

### 4. PR 监控与修复
- ✅ **PR 提交后，持续检查 PR 状态**
- ✅ **如果有失败，直接修复**
- ✅ **待所有 CI 成功，且 PR 为 MERGEABLE 状态，则直接合并**

#### 检查 PR 状态
```bash
# 查看 PR 状态
gh pr view <PR 号> --json title,state,mergeable,mergeStateStatus

# 查看 CI runs
gh run list --limit 5 --branch <branch-name>

# 等待 CI 完成
gh run watch <run-id>
```

#### 修复 CI 失败
```bash
# 查看失败的 check details
gh run view <run-id> --log

# 本地重现并修复
cd /path/to/repo
ruff check src/ tests/
ruff format --check src/ tests/
pytest

# 修复后提交
# 如果是 formatting 问题，使用 ruff format 自动修复
ruff format src/ tests/

# 提交修复
git add -A
git commit --amend --no-edit  # 如果是最后一次提交的修复
git push -f origin <branch-name>
```

#### 合并 PR
```bash
# 确认 PR 状态
gh pr view <PR 号> --json title,state,mergeable,mergeStateStatus

# 检查 CI 状态
gh run list --limit 3 --branch <branch-name>

# 合并（使用 squash 策略）
gh pr merge <PR 号> --squash --delete-branch \
  --subject="<commit title>" \
  --body="<commit body>"

# 验证合并
gh pr view <PR 号> --json title,state,mergedAt
```

## 🔍 状态检查清单

### PR 合并前检查
- [ ] 所有本地检查通过（ruff check, ruff format, pytest）
- [ ] 所有 CI checks 成功
- [ ] PR 状态为 `MERGEABLE`
- [ ] mergeStateStatus 为 `CLEAN`

### PR 合并后检查
- [ ] PR 状态为 `MERGED`
- [ ] 特性分支已删除
- [ ] main 分支有最新的 commit

## 📝 最佳实践

1. **小步提交**：每个 PR 只做一件事，保持改动小
2. **TDD 方法**：先写测试，再写实现
3. **及时修复**：CI 失败时立即修复，不要拖延
4. **清晰描述**：commit message 和 PR description 要清晰
5. **定期清理**：删除已合并的本地特性分支

## 🚀 常用命令

```bash
# 创建特性分支
git checkout main && git pull && git checkout -b feature/<描述>

# 运行所有检查
ruff check src/ tests/ && ruff format --check src/ tests/ && pytest -q

# 修复 formatting
ruff format src/ tests/

# 推送并创建 PR
git push -u origin feature/<描述>
gh pr create --title "<标题>" --body "<描述>" --base main

# 检查 PR 状态
gh pr view <PR 号>

# 查看 CI 状态
gh run list --branch feature/<描述>

# 合并 PR
gh pr merge <PR 号> --squash --delete-branch --subject "<标题>" --body "<描述>"
```

---

*创建时间：2026-03-26*
*适用于：AISE 项目迭代开发*
