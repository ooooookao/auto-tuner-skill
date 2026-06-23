---
step: 0
title: 确认工作区
---

# Step 0：确认工作区与权限配置

**目的**：锁定项目路径、配置权限、扫描可用技能。
**前置**：无。
**输出**：权限已配置、`experiment/available_skills.md`。

---

## 操作清单

- [ ] 从对话中提取项目路径，若没有则询问用户
- [ ] 展示：路径、顶层文件列表、是否 Git 仓库，等待用户确认
- [ ] 检查 `experiment/` 目录是否已存在，若存在则询问用户是否使用其他名称（如 `auto-tuner-exp/`）
- [ ] 询问用户是否自动配置工作区权限（见下方）
- [ ] 自动检测工作区外的数据集/输出/环境路径，一并配置权限
- [ ] 技能扫描：检查可用 skill，记录到 `{exp_dir}/available_skills.md`

**这是用户唯一需要参与的环节。** 之后所有决策由 agent 自主完成。

---

## 工作区权限配置

确认工作区后，询问用户：

```
这个 skill 执行过程中会频繁使用 Bash（运行训练、检查 GPU 等）、Read/Write/Edit（读写代码和配置）、Agent（并行实验）。
要自动把这些工具的权限配好吗？配好后后续运行不会反复弹确认框。
权限随时可在 settings.json 中收回。
- 是，自动配置
- 不，逐个确认
```

**用户选"是"** → 读取 `.claude/settings.json`，合并写入 `permissions.allow`（细粒度，不用 `Bash(*)`）：
```json
{
  "permissions": {
    "allow": [
      "Bash(python *)",
      "Bash(pip *)",
      "Bash(nvidia-smi)",
      "Bash(nvidia-smi *)",
      "Bash(conda *)",
      "Bash(ls *)",
      "Bash(mkdir *)",
      "Bash(cp *)",
      "Bash(wc *)",
      "Bash(head *)",
      "Bash(tail *)",
      "Bash(cat *)",
      "Bash(echo *)",
      "Read({project_path}/**)",
      "Write({project_path}/**)",
      "Edit({project_path}/**)",
      "Glob(*)",
      "Grep(*)",
      "Agent(*)"
    ]
  }
}
```

其中 `{project_path}` 替换为实际项目路径。Write/Edit 限定在项目目录内，不覆盖其他文件。

同时检测工作区外的数据集/输出/环境路径，一并加入 Read/Write/Edit 权限。

**用户选"否"** → 正常运行，每个工具调用逐个确认。

---

## 技能扫描规则

- 检查当前环境中有哪些可用 skill
- 记录每个 skill 的名称和 description
- 后续执行任何阶段时，如果发现当前任务恰好有 skill 能提效，主动调用
- 不要局限于已知的 skill 用途，根据 description 判断是否对当前工作有帮助

---

## 故障处理

Step 0 专属故障：

| 场景 | 处理 |
|------|------|
| 用户提供的路径不存在 | 展示错误，请求正确路径 |
| 路径存在但无代码文件 | 询问用户是否需要先写代码 |

通用故障规则见 `references/failure-recovery.md`。

---

## 增量记录

完成后写 `experiment/delta-step0.md`：
- 确认的项目路径
- 是否 Git 仓库
- 检测到的外部路径
- 可用 skill 列表摘要
