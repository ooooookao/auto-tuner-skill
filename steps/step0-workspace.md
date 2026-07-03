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
- [ ] 询问用户选择执行模式（autonomy_mode）：`full` 全程自主 / `interactive` 关键节点询问
- [ ] 询问用户是否自动配置工作区权限（见下方）
- [ ] 自动检测工作区外的数据集/输出/环境路径，一并配置权限
- [ ] 技能扫描：检查可用 skill，记录到 `{exp_dir}/available_skills.md`

**Step 0 之后，agent 按 `autonomy_mode` 执行。**
- `full` 模式：后续数据分析深度、数据集子集选择、目标放宽等节点均使用默认策略，不再询问用户。
- `interactive` 模式：在上述节点暂停并等待用户选择。

无论哪种模式，用户都可随时中断并调整方向。

---

## 执行模式选择

确认工作区路径后，询问用户选择执行模式，并写入 `state.json` 的 `autonomy_mode` 字段：

```
请选择本次调参的执行模式：
- full（全程自主）：agent 在数据分析深度、数据集子集、目标放宽等节点使用默认策略，不再询问。适合你已经明确目标、希望少被打扰。
- interactive（交互模式）：agent 在上述关键节点暂停并等待你的选择。适合想掌控方向或第一次运行该项目。
```

**默认推荐 `full`。** 用户未明确选择时，按 `full` 执行。

---

## 工作区权限配置

确认工作区并选定 `autonomy_mode` 后，询问用户是否自动配置权限：

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
