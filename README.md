# Auto-Tuner

科研代码自动化调参 Skill for Claude Code。用户只需确认工作区和需求，agent 自动完成从参数搜索到架构优化的全部流程。

## 功能特点

- **全程自主**：用户只在开头确认一次工作区，之后自动执行直到出结果
- **并行调参**：默认 5 路并行，根据 GPU/内存动态调整（上限 8 路）
- **智能迭代**：粗搜 → 细搜 → 微调，每轮自动分析趋势缩小范围
- **架构回溯**：调参 10 轮无提升时自动诊断瓶颈、搜索 GitHub 同类解决方案获取思路、修改网络架构、重新调参
- **失败记录**：每次架构修改失败都会记录原因和参考来源，避免重复踩坑
- **技能联动**：自动扫描可用 skill，执行过程中按需调用其他 skill 提效
- **自动放弃**：满足条件时主动停止并生成报告，不死磕
- **数据集优化**：大数据集可先用子集快速探索方向，再用全量数据精调

## 适用场景

- 深度学习训练（PyTorch/TensorFlow）
- 传统机器学习（scikit-learn 等）
- 数值模拟、图像处理 pipeline
- 任何需要反复调参达标指标的科研实验

## 安装

### 方式一：从 GitHub 安装

```bash
# 克隆到 Claude Code skills 目录
git clone https://github.com/ooooookao/auto-tuner-skill.git ~/.claude/skills/auto-tuner
```

### 方式二：手动安装

下载本仓库，将 `SKILL.md`、`references/`、`evals/` 放到 `~/.claude/skills/auto-tuner/` 目录下。

## 使用方式

在 Claude Code 中直接描述你的调参需求即可，skill 会自动触发：

```
帮我调参，项目在 /path/to/project/ 下，目标是心脏分割 dice >= 0.9
```

```
我的模型 accuracy 只有 0.65，需要达到 0.85，代码在 train.py 里
```

```
跑实验，希望所有指标都达标
```

### 关键词触发

以下关键词会自动触发此 skill：调参、超参搜索、hyperparameter tuning、参数优化、跑实验、达标、dice、accuracy、loss 等。

## 工作流程

```
阶段零：确认工作区 + 配置权限 + 技能扫描（用户唯一参与点）
  │
阶段一：项目理解、参数规划与达标定义
  ├── 理解项目（从对话提取信息）
  ├── 数据集确认 + 跑 baseline + 询问是否用子集
  ├── 自我辩论选调参策略
  └── 参数扫描 + 达标定义
  │
阶段二：并行调参执行
  ├── 建目录 + 检测硬件
  ├── 5 路并行（动态调整）
  └── 单轮流程 + results.json + progress.md
  │
阶段三：迭代优化
  ├── 分析决策（排名 → 趋势 → 缩范围）
  ├── 粗搜 → 细搜 → 微调
  ├── 架构回溯（10 轮无提升触发）
  │   ├── 存档当前最优
  │   ├── 诊断瓶颈
  │   ├── 搜索 GitHub 同类方案获取思路
  │   ├── 自主选方案 + 修改架构
  │   └── 新架构调满 10 轮再判定
  └── 放弃机制（3 架构穷尽 / 50 轮上限 / 20 轮停滞）
  │
阶段四：达标报告
```

## 生成的文件

调参过程中会在工作区生成以下文件：

| 文件 | 说明 |
|------|------|
| `experiment/dataset_info.md` | 数据集分析记录 |
| `experiment/decision_log.md` | 每轮决策日志 |
| `experiment/progress.md` | 实时进度（用户可查看） |
| `experiment/results.json` | 每轮参数与指标汇总 |
| `experiment/failed_architectures.md` | 架构修改失败记录 |
| `experiment/checkpoints/` | 架构变更前的代码存档 |
| `experiment/report.md` | 最终报告 |

## 依赖

- Claude Code 环境
- `update-config` skill（用于配置工作区权限）

## 致谢

本 skill 的部分设计思路借鉴了 [huggingface/ml-intern](https://github.com/huggingface/ml-intern)：

- **死循环检测**：参考 ml-intern 的 Doom Loop Detector，检测调参过程中参数组合过于相似的情况并强制跳出
- **研究子 Agent**：参考 ml-intern 的 Research Sub-agent 模式，用独立上下文做 GitHub 搜索，避免撑爆主 agent 的 context
- **结构化研究输出**：参考 ml-intern 的研究输出格式，架构方案评估采用结构化表格
- **上下文压缩**：参考 ml-intern 的 Context Compaction，长调参流程中定期压缩旧轮次信息
- **完成守卫**：参考 ml-intern 的 Continuation Guard，确保 agent 不会中途放弃未完成的调参任务
- **通知机制**：参考 ml-intern 的 Notification Gateway，调参完成时通知用户
- **成本追踪**：参考 ml-intern 的 Telemetry 系统，在报告中记录 token 消耗和费用

## License

MIT
