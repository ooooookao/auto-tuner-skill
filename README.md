# Auto-Tuner

科研代码自动化调参 Skill for Claude Code。用户只需确认工作区和需求，agent 自动完成从参数搜索到架构优化的全部流程。

## 功能特点

- **全程自主**：用户只在开头确认一次工作区，之后自动执行直到出结果
- **并行调参**：默认 5 路并行，根据 GPU/内存动态调整（上限 8 路）
- **智能迭代**：粗搜 → 细搜 → 微调，每轮自动分析趋势缩小范围
- **架构回溯**：调参 10 轮无提升时自动诊断瓶颈、多源搜索（GitHub/论文/文档/博客）获取思路、修改网络架构、重新调参
- **故障熔断**：子 agent 失败自动重试→降级→记录；质量不达标自动降级处理
- **审查前置**：大纲自审 + 两轮审查制（粗调报硬伤，细调报细节）
- **状态增量**：每步写增量记录，阶段切换写快照，支持断点恢复
- **自动放弃**：满足条件时主动停止并生成报告，不死磕

## 适用场景

- 深度学习训练（PyTorch/TensorFlow）
- 传统机器学习（scikit-learn 等）
- 数值模拟、图像处理 pipeline
- 任何需要反复调参达标指标的科研实验

## 安装

```bash
git clone https://github.com/ooooookao/auto-tuner-skill.git ~/.claude/skills/auto-tuner
```

## 使用方式

```
帮我调参，项目在 /path/to/project/ 下，目标是心脏分割 dice >= 0.9
```

## 文件结构

```
auto-tuner/
├── SKILL.md                              ← 入口：全局规则 + 工作流导航 + checklist（每次必读）
├── steps/
│   ├── step0-workspace.md                ← 工作区确认（Step 0 执行时读）
│   ├── step1-planning.md                 ← 项目理解 + 参数规划（Step 1 执行时读）
│   ├── step2-tuning.md                   ← 并行调参执行（Step 2 执行时读）
│   ├── step3-optimization.md             ← 迭代优化 + 架构回溯（Step 3 执行时读）
│   └── step4-report.md                   ← 达标报告（Step 4 执行时读）
├── references/
│   ├── failure-recovery.md               ← 故障熔断规则（遇到故障时读）
│   ├── github-search.md                  ← GitHub 搜索策略（架构回溯时读）
│   ├── cost-tracking.md                  ← token 消耗估算（生成报告时读）
│   ├── review-checklist.md               ← 审查维度 + 两轮制（审查时读）
│   ├── state-management.md               ← 增量/快照/断点恢复（状态管理时读）
│   ├── user-choices.md                   ← 用户选择策略（Step 1 数据集选择时读）
│   ├── report_template.md                ← 报告模板（生成报告时读）
│   └── results_schema.md                 ← results.json 格式（写结果时读）
├── evals/
│   └── evals.json
└── README.md
```

### 设计原则

**模块化分层**：SKILL.md 只放全局规则和工作流导航（~115 行），详细内容按需读取 step 文件。如果一段内容不是每次执行都需要，就不放在 SKILL.md 里。

**工作流内联 checklist**：SKILL.md 的工作流图中每步标注 ✓ 最低要求，即使 agent 不读 step 文件也不会跑偏。

**故障熔断**：子 agent 调用失败重试 3 次→降级执行→记录；质量不达标自动降级处理。

**审查前置 + 两轮制**：大纲自审在调参前发现问题；粗调报硬伤，细调报细节。

**语义边界触发**：每个搜索阶段完成时审查，兜底 15 轮强制触发。

**全程自主**：用户只在 Step 0 确认工作区 + Step 1 选择数据集策略，之后所有决策由 agent 自主完成。

**状态增量**：每步写 delta，阶段切换写 checkpoint，断点恢复读 checkpoint + deltas。

## 生成的文件

| 文件 | 说明 |
|------|------|
| `experiment/dataset_info.md` | 数据集分析记录 |
| `experiment/decision_log.md` | 每轮决策日志 |
| `experiment/progress.md` | 实时进度（用户可查看） |
| `experiment/results.json` | 每轮参数与指标汇总 |
| `experiment/failed_architectures.md` | 架构修改失败记录 |
| `experiment/degradation_log.md` | 降级事件记录 |
| `experiment/delta-step{N}.md` | 每步增量记录 |
| `experiment/checkpoint-phase{N}.md` | 阶段快照 |
| `experiment/checkpoints/` | 架构变更前的代码存档 |
| `experiment/report.md` | 最终报告 |

## 致谢

本 skill 的部分设计思路借鉴了 [huggingface/ml-intern](https://github.com/huggingface/ml-intern)：

- **死循环检测**：参考 ml-intern 的 Doom Loop Detector
- **研究子 Agent**：参考 ml-intern 的 Research Sub-agent 模式
- **上下文压缩**：参考 ml-intern 的 Context Compaction
- **完成守卫**：参考 ml-intern 的 Continuation Guard

## License

MIT
