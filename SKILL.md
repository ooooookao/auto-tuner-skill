---
name: auto-tuner
description: >
  科研代码项目自动化调参 skill。适用于任何需要系统性调参的科研实验代码——深度学习训练、传统机器学习、数值模拟、图像处理 pipeline 等。
  当用户提到"调参"、"超参搜索"、"hyperparameter tuning"、"参数优化"、"跑实验"、"达标"、"dice"、"accuracy"、"loss"等关键词时触发。
  也适用于用户描述了一个实验目标（如"所有心脏部位 dice >= 0.9"）并希望 agent 自动迭代调参直到达标的情况。
  即使用户没有明确说"调参"，只要他们描述了一个需要反复实验才能达到指标的科研任务，也应触发此 skill。
---

# 科研代码自动化调参

通过系统性参数搜索，让实验指标达到预设标准。**全程自主执行**，用户只在开头确认一次工作区，之后等最终结果。

---

## 工作流

```
Step 0 → steps/step0-workspace.md
  ✓ 确认工作区路径  ✓ 配置权限  ✓ 技能扫描

Step 1 → steps/step1-planning.md
  ✓ 理解项目  ✓ 数据集记录  ✓ baseline 耗时  ✓ 自我辩论选策略  ✓ 参数扫描  ✓ 达标定义
  ✓ 大纲自审（审查前置）

Step 2 → steps/step2-tuning.md
  ✓ 环境准备  ✓ 并行执行  ✓ results.json  ✓ progress.md  ✓ 上下文压缩

Step 3 → steps/step3-optimization.md
  ✓ 趋势分析  ✓ 死循环检测  ✓ 架构回溯（条件触发）  ✓ 放弃判定

Step 4 → steps/step4-report.md
  ✓ 按模板生成报告  ✓ 架构变更历史（如有）  ✓ 成本记录
```

每步执行时读取对应 step 文件。其他文件按需读取：
- 故障 → `references/failure-recovery.md`
- 审查 → `references/review-checklist.md`
- 状态管理 → `references/state-management.md`
- 用户决策 → `references/user-choices.md`

---

## 核心原则

1. **全程自主**：用户只确认工作区，之后所有决策由 agent 自主完成
2. **先跑通再调参**：代码有 bug 先修，不在坏代码上浪费时间
3. **记录一切**：每个决策写入 decision_log.md，每个失败写入 failed_architectures.md
4. **保守优先**：不确定时选风险最低的方案，后续可以迭代改进
5. **关键信息写文件**：不依赖对话记忆，上下文可压缩但文件不丢

---

## 故障熔断总则

详细规则见 `references/failure-recovery.md`。核心要点：

- **子 agent 调用失败**：重试 3 次（间隔 0s/5s/15s）→ 主 agent 降级执行 → 结果仍走正常校验
- **质量熔断**：同一环节 3 次不达标 → 暂停，向用户报告，提供选项
- **降级事件**：记录到 `experiment/degradation_log.md`

---

## 审查前置总则

详细清单见 `references/review-checklist.md`。核心要点：

- **大纲自审**：参数规划完成后、开始调参前，先自审规划是否合理
- **两轮审查**：粗调只报严重问题（结构性硬伤），细调报所有问题（细节精修）
- 两轮用同一套维度，但通过标准不同

---

## 触发条件

- **语义边界触发**：每个搜索阶段（粗搜/细搜/微调）完成时审查，而非固定轮数
- **兜底机制**：超过 15 轮未审查时强制触发一次
- **架构回溯触发**：连续 10 轮无提升（< 0.01）且距达标 > 0.03

---

## 用户选择点

详细策略见 `references/user-choices.md`。以下场景必须给用户选项，不硬编码：

- 数据集子集 vs 全量（阶段一，10 分钟超时后默认全量）
- 审查结果处理：全部接受 / 部分接受 / 跳过 / 重调
- 熔断处理：继续 / 降低目标 / 换策略 / 停止

---

## 状态管理

详细规则见 `references/state-management.md`。核心要点：

- 每步产出增量记录：`experiment/delta-step{N}.md`
- 每个搜索阶段结束写全量快照：`experiment/checkpoint-phase{N}.md`
- 断点恢复：读最近 checkpoint + 之后的 deltas

---

## 生成的文件

| 文件 | 说明 |
|------|------|
| `experiment/dataset_info.md` | 数据集分析记录 |
| `experiment/decision_log.md` | 每轮决策日志 |
| `experiment/progress.md` | 实时进度（用户可查看） |
| `experiment/results.json` | 每轮参数与指标汇总（格式见 `references/results_schema.md`） |
| `experiment/failed_architectures.md` | 架构修改失败记录 |
| `experiment/degradation_log.md` | 降级事件记录 |
| `experiment/delta-step{N}.md` | 每步增量记录 |
| `experiment/checkpoint-phase{N}.md` | 阶段快照 |
| `experiment/checkpoints/` | 架构变更前的代码存档 |
| `experiment/report.md` | 最终报告（模板见 `references/report_template.md`） |
