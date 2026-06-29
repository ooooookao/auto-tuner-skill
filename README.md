# Auto-Tuner

科研代码自动化调参 Skill for Claude Code。用户只需确认工作区和需求，agent 自动完成从参数搜索到架构优化的全部流程。

## 功能特点

- **全程自主，可随时介入**：用户确认工作区后自动执行，每 5 轮输出进度摘要，用户可随时中断调整方向
- **数据集全面分析**：调参前自动分析数据集（类别分布、质量、特征、可分性），生成报告+可视化，输出调参建议
- **并行调参**：根据 GPU 显存自动计算并行路数，动态调整（上限 8 路）
- **智能迭代**：粗搜 → 细搜 → 微调，每轮自动分析趋势缩小范围
- **参数重要性**：自动计算参数重要性（含交互检测），固定不重要的参数，集中火力调关键参数
- **提前终止**：训练 20%（有 warmup 时 30%）时检查趋势，明显不行的配置提前 kill，省 30-50% 时间
- **经验迁移**：跨项目积累调参经验，越用越聪明
- **自动修复**：代码有 bug 自动定位并修复，最多重试 3 次
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
│   ├── experience.md                     ← 经验迁移系统（Step 1 读，Step 4 写）
│   ├── review-checklist.md               ← 审查维度 + 两轮制（审查时读）
│   ├── state-management.md               ← 增量/快照/断点恢复（状态管理时读）
│   ├── state-schema.md                   ← state.json 状态机定义 + 状态转换表（路由决策用）
│   ├── results.schema.json               ← results.json JSON Schema 定义（写入时校验）
│   ├── config-generation.md              ← 框架识别 + 配置文件生成 + Optuna 集成（Step 2 配置生成时读）
│   └── dataset-analysis.md               ← 数据集全面分析规则（Step 1 数据集分析时读）
├── evals/
│   └── evals.json
├── examples/
│   └── cardiac-segmentation-example.md   ← 完整调参示例
└── README.md
```

### 设计原则

**模块化分层**：SKILL.md 只放全局规则和工作流导航（~80 行），详细内容按需读取 step 文件。

**调参主循环**：Step 2 是主控循环（执行→分析→决策→下一轮），Step 3 仅在架构回溯时从 Step 2 跳入。

**工作流内联 checklist**：每个 step 文件顶部有 ✓ 操作清单，agent 不读完整文件也能知道要做什么。

**故障熔断**：子 agent 调用失败重试 3 次→降级执行→记录；质量不达标自动降级处理。

**审查前置 + 语义边界**：大纲自审在调参前发现问题；每个搜索阶段完成时审查，兜底 15 轮强制触发。

**全程自主，可随时介入**：用户确认工作区后 agent 自主执行，每 5 轮输出进度摘要，用户可随时中断调整方向。

**经验积累**：每次调参结束后提取关键经验写入经验库，跨项目复用。

## 生成的文件

| 文件 | 说明 |
|------|------|
| `experiment/dataset_info.md` | 数据集分析摘要 |
| `experiment/dataset_analysis_report.md` | 数据集全面分析报告（含可视化） |
| `experiment/dataset_analysis/` | 数据集分析可视化图片 |
| `experiment/decision_log.md` | 每轮决策日志 |
| `experiment/progress.md` | 主状态文件（agent 位置 + 实时进度） |
| `experiment/results.json` | 每轮参数与指标汇总 |
| `experiment/failed_architectures.md` | 架构修改失败记录 |
| `experiment/degradation_log.md` | 降级事件记录 |
| `experiment/delta-step{N}.md` | 每步增量记录 |
| `experiment/checkpoint-phase{N}.md` | 阶段快照 |
| `experiment/checkpoints/` | 架构变更前的代码存档 |
| `experiment/report.md` | 最终报告 |
| `experiment/report.html` | 可视化 HTML 报告 |

## 致谢

本 skill 的部分设计思路借鉴了 [huggingface/ml-intern](https://github.com/huggingface/ml-intern)：

- **死循环检测**：参考 ml-intern 的 Doom Loop Detector
- **研究子 Agent**：参考 ml-intern 的 Research Sub-agent 模式
- **上下文压缩**：参考 ml-intern 的 Context Compaction
- **完成守卫**：参考 ml-intern 的 Continuation Guard

## License

MIT
