---
name: auto-tuner
description: >
  科研代码项目自动化调参 skill。适用于任何需要系统性调参的科研实验代码——深度学习训练、传统机器学习、数值模拟、图像处理 pipeline 等。
  当用户提到"调参"、"超参搜索"、"hyperparameter tuning"、"参数优化"、"跑实验"、"达标"、"dice"、"accuracy"、"loss"等关键词时触发。
  也适用于用户描述了一个实验目标（如"所有心脏部位 dice >= 0.9"）并希望 agent 自动迭代调参直到达标的情况。
  即使用户没有明确说"调参"，只要他们描述了一个需要反复实验才能达到指标的科研任务，也应触发此 skill。
  英文触发："tune hyperparameters"、"train model"、"run experiments"、"optimize parameters"、"reach target metrics"、"fine-tune"、"grid search"、"cross-validation"、"sweep"、"hyperparameter search"。
---

# 科研代码自动化调参

通过系统性参数搜索，让实验指标达到预设标准。**全程自主执行**，用户确认工作区后 agent 自动迭代，每 5 轮输出进度摘要，用户可随时介入调整方向。

---

## 工作流

```
Step 0 → steps/step0-workspace.md
  ✓ 确认工作区路径  ✓ 询问是否自动配置权限（细粒度）  ✓ 技能扫描

Step 1 → steps/step1-planning.md
  ✓ 理解项目  ✓ 数据集全面分析（报告+可视化）  ✓ baseline 耗时  ✓ 自我辩论选策略  ✓ 参数扫描  ✓ 达标定义
  ✓ 大纲自审（审查前置）

Step 2 → steps/step2-tuning.md          ← 调参主循环
  ✓ 并行执行  ✓ 趋势分析  ✓ 参数重要性  ✓ 死循环检测  ✓ 递进策略
  ✓ 审查触发  ✓ 终止/路由判断  ✓ 上下文压缩

Step 3 → steps/step3-optimization.md    ← 仅架构回溯时触发
  ✓ 存档  ✓ 诊断瓶颈  ✓ 多源搜索  ✓ 架构修改  ✓ 验证与回档

Step 4 → steps/step4-report.md
  ✓ 按模板生成报告  ✓ 架构变更历史（如有）  ✓ 写入经验库
```

**循环结构**：Step 2 是主循环（执行→分析→决策→下一轮），Step 3 仅在架构回溯时从 Step 2 跳入，完成后回到 Step 2。

每步执行时读取对应 step 文件。其他文件按需读取：
- 故障 → `references/failure-recovery.md`
- 数据集分析 → `references/dataset-analysis.md`
- 审查 → `references/review-checklist.md`
- 状态管理 → `references/state-management.md`
- 状态机 → `references/state-schema.md`（state.json 定义 + 状态转换表）
- results.json 校验 → `references/results.schema.json`（JSON Schema）
- 经验 → `references/experience.md`
- 配置生成 → `references/config-generation.md`（框架识别 + 配置文件生成 + Optuna 集成）

---

## 核心原则

1. **按模式执行，用户可随时介入**：Step 0 选择 `autonomy_mode`。`full` 模式全程自主，使用默认策略；`interactive` 模式在数据分析深度、数据集子集、目标放宽等节点询问用户。无论哪种模式，每 5 轮或阶段切换时输出进度摘要，用户可随时中断调整方向
2. **先跑通再调参**：代码有 bug 先修，不在坏代码上浪费时间
3. **记录一切**：每个决策写入 decision_log.md，每个失败写入 failed_architectures.md
4. **保守优先**：不确定时选风险最低的方案，后续可以迭代改进
5. **关键信息写文件**：不依赖对话记忆，上下文可压缩但文件不丢

## 工作区权限

Step 0 确认工作区后，询问用户是否自动配置权限。用户选"是" → 写入 `.claude/settings.json`（合并写入，不覆盖，细粒度 Bash 权限，不使用 `Bash(*)`）。详见 `steps/step0-workspace.md`。

---

## 故障熔断

子 agent 失败重试 3 次→降级→记录；质量不达标请求用户确认是否放宽标准。详见 `references/failure-recovery.md`。

## 审查机制

大纲自审（调参前）+ 语义边界审查（每个搜索阶段完成时）+ 兜底 15 轮强制触发。粗调报硬伤，细调报所有问题。详见 `references/review-checklist.md`。

## 状态管理

每步写 delta，阶段切换写 checkpoint，断点恢复读 checkpoint + deltas。详见 `references/state-management.md`。

---

## 生成的文件

以下 `{exp_dir}` 默认为 `experiment/`，若该目录已存在则在 Step 0 中由用户指定其他名称。

| 文件 | 说明 |
|------|------|
| `{exp_dir}/dataset_info.md` | 数据集分析摘要 |
| `{exp_dir}/dataset_analysis_report.md` | 数据集全面分析报告（含可视化） |
| `{exp_dir}/dataset_analysis/` | 数据集分析可视化图片 |
| `{exp_dir}/decision_log.md` | 每轮决策日志 |
| `{exp_dir}/state.json` | **机器可读状态机**，agent 路由决策依据（phase/round/next_action） |
| `{exp_dir}/results.json` | 每轮参数与指标汇总（严格遵循 references/results.schema.json） |
| `{exp_dir}/progress.md` | 人类可读进度（轮次对比 + 最佳排行榜，用户阅读用） |
| `{exp_dir}/failed_architectures.md` | 架构修改失败记录 |
| `{exp_dir}/degradation_log.md` | 降级事件记录 |
| `{exp_dir}/delta-step{N}.md` | 每步增量记录 |
| `{exp_dir}/checkpoint-phase{N}.md` | 阶段快照 |
| `{exp_dir}/checkpoints/` | 架构变更前的代码存档 |
| `{exp_dir}/report.md` | 最终报告（模板见 step4-report.md） |
| `{exp_dir}/report.html` | 可视化 HTML 报告（含图表，无依赖时为纯表格） |
