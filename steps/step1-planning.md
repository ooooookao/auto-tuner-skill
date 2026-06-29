---
step: 1
title: 项目理解与参数规划
---

# Step 1：项目理解、参数规划与达标定义

**目的**：理解项目、分析数据集、设计调参框架、定义达标标准。
**前置**：Step 0 完成（工作区已确认、权限已配置）。
**输出**：`experiment/dataset_info.md`、`experiment/decision_log.md`、参数表、达标标准。

---

## 操作清单

- [ ] 1.0 初始化：创建 `{exp_dir}/` 目录，创建 `decision_log.md`（空模板）和 `progress.md`（空模板）
- [ ] 1.1 理解项目：提取目标、输入输出、评估指标、硬件资源
- [ ] 1.2 数据集全面分析：生成 dataset_analysis_report.md + 可视化图片
- [ ] 1.3 跑 baseline：估算单轮耗时
- [ ] 1.4 询问用户：子集 vs 全量
- [ ] 1.5 读取经验库：查找同类项目的历史经验（见 `references/experience.md`）
- [ ] 1.6 框架识别：检测项目使用的框架类型（PyTorch/TensorFlow/sklearn 等），记入 `experiment/dataset_info.md`（详见 `references/config-generation.md` 的"框架识别"章节）
- [ ] 1.7 自我辩论：选调参策略（参考历史经验），记录到 decision_log.md
- [ ] 1.8 参数扫描：识别可调参数，按类别整理（参考经验库中的参数范围）
- [ ] 1.9 达标定义：提取或推断达标标准
- [ ] 1.10 大纲自审：审查规划合理性（见 `references/review-checklist.md`）

---

## 1.0 初始化

创建 `{exp_dir}/` 目录及初始文件：

1. **`state.json`** — 机器可读状态机（agent 路由决策的依据）：
```json
{
  "phase": "planning",
  "round": 0,
  "architecture_version": 1,
  "search_stage": null,
  "best_config_id": null,
  "best_metrics": {},
  "target_expr": "",
  "last_action": null,
  "next_action": "step1_planning",
  "stop_reason": null,
  "retry_count": 0,
  "consecutive_no_improvement": 0,
  "last_round_best_metric": null,
  "last_updated": "<当前ISO时间>"
}
```
详见 `references/state-schema.md`。

2. **`decision_log.md`**：
```markdown
# 决策日志
```

3. **`progress.md`**：
```markdown
# 调参进度

## 当前状态
- **阶段**：未开始
- **轮次**：—
- **当前最佳**：—
- **下一步**：等待 Step 1 完成
```

4. **`results.json`**：空数组 `[]`

5. **经验库目录**：检查 `~/.claude/skills/auto-tuner/experience/` 是否存在，不存在则创建（含空 `index.md`）

---

## 1.1 理解项目

从对话中提取：
- 项目目标（做什么）
- 输入输出（数据格式、模型结构）
- 评估指标（dice/accuracy/loss 等）
- 达标标准（具体数值）
- 硬件资源（GPU 型号、显存大小）

信息不完整时只问缺失的部分，不重复确认已有信息。如果用户没有现成代码，先写代码再继续。

---

## 1.2 数据集分析

对数据集进行分析，生成报告 `{exp_dir}/dataset_analysis_report.md`。

详细分析规则见 `references/dataset-analysis.md`。

### 分析深度选择

给用户两个选项（不设超时，等待用户选择）：

| 深度 | 内容 | 耗时 |
|------|------|------|
| **快速** | 基础统计 + 数据质量 + 类别分布 | ~3 分钟 |
| **全面** | 快速 + 特征分布 + 标注质量 + 可分性 + 可视化 | ~10 分钟 |

默认建议"快速"，用户明确要求深入分析时才用"全面"。

### 快速分析（默认）

| 维度 | 子 agent | 检查内容 |
|------|----------|----------|
| 基础统计 | Agent A | 样本量、划分、格式、维度、磁盘占用 |
| 类别分布 | Agent A | 类别计数、不平衡比 |
| 数据质量 | Agent B | 缺失值、损坏文件、重复检测 |

### 全面分析（用户选择时）

额外包含：

| 维度 | 子 agent | 检查内容 |
|------|----------|----------|
| 特征分布 | Agent B | 数值/像素统计、分布直方图 |
| 标注质量 | Agent C | 标注一致性、空标注、极小目标 |
| 可分性 | Agent C | KNN 评估、PCA 散点图 |

### 子 agent prompt 模板

```
对项目 {project_path} 的数据集进行分析，将结果写入 {output_path}：

分析项：
{analysis_items}

数据路径：
{data_paths}

要求：
1. 输出 Markdown 表格 + 文字说明
2. 检查 matplotlib 可用性，可用则生成图片到 {exp_dir}/dataset_analysis/
3. 发现异常标注 ⚠️ 警告
4. 基于分析结果给出调参建议（loss 函数、数据增强、正则化等）
5. 用中文输出
```

### 协调与容错

- 等待方式：所有子 agent 启动后阻塞等待返回
- 超时：单个子 agent 超时 15 分钟，超时后标记为"未完成"，不阻塞其他
- 失败重试：适用 `references/failure-recovery.md` 的子 agent 重试规则（3 次→降级）
- 降级：子 agent 失败后，主 agent 自行完成该检查项（基于文件搜索和抽样读取）

### 汇总与输出

收集所有子 agent 结果后，主 agent：

1. 合并写入 `{exp_dir}/dataset_analysis_report.md`（结构见 `references/dataset-analysis.md` 的"报告结构"章节）
2. 提取调参建议，写入 `{exp_dir}/decision_log.md` 的"数据集分析驱动的调参建议"章节
3. 简要摘要写入 `{exp_dir}/dataset_info.md`（供后续步骤快速参考）

### 分析结果对调参的影响

| 发现 | 调参影响 |
|------|----------|
| 类别不平衡比 > 10 | loss 函数选择 Focal Loss / 加权 CE |
| 某类像素占比 < 1%（分割） | 使用 Dice Loss 或 CE+Dice 组合 |
| 数据量小（< 500） | 增强数据增强策略、降低模型复杂度 |
| 分辨率不一致 | 需要统一 resize/padding |
| 像素值未归一化 | 加入归一化步骤 |
| 大量重复样本 | 清理后再调参 |
| 标注质量差（空标注多） | 先修复标注再调参 |
| KNN 准确率很低 | 数据可分性差，可能需要更强的特征提取 |

---

## 1.3 Baseline 与数据集策略

先跑一次 baseline 估算单轮耗时。

然后给用户选项：
- **选项 A**：先用 10%-20% 子集快速调参找方向，最后 2-3 轮全量验证（快，省资源，但最终指标可能有偏差）
- **选项 B**：直接用全量数据集（结果可靠，但慢，耗资源）

等待用户回复，不设超时自动决策。

---

## 1.4 自我辩论设计调参框架

### 搜索策略选择指南

先根据项目特征选择搜索策略，再做自我辩论确认：

| 项目特征 | 推荐策略 | 降级链 | 理由 |
|----------|----------|--------|------|
| 参数 ≤ 5 个、评估成本低（<5min/轮） | 网格搜索 | 网格搜索（无降级） | 参数少时穷举可行 |
| 参数 > 5 个、有梯度（深度学习） | 贝叶斯搜索（Optuna TPE） | Optuna TPE → 扰动采样 → 随机采样 | 高维空间中贝叶斯效率远高于随机 |
| 参数 > 5 个、无梯度（传统 ML） | 随机搜索 → 扰动采样 | 随机采样（无进一步降级） | 无梯度信息时随机探索更稳健 |
| 评估成本高（>30min/轮） | 贝叶斯搜索 + 提前终止 | Optuna TPE + Pruner → 扰动采样 | 需要最大化每轮信息 gain |
| 不确定 / 混合类型 | 随机搜索起步 | 随机采样（无进一步降级） | 先探索再切换 |

降级触发条件详见 `references/failure-recovery.md`。

**Optuna 检测**：`python -c "import optuna" 2>/dev/null`，成功则优先使用 Optuna TPE + HyperbandPruner，失败则使用手动采样。Optuna 的使用方式详见 `references/config-generation.md`，降级链详见 `references/failure-recovery.md`。

### 自我辩论

根据项目特点和搜索策略选择结果，列出 2-3 种最合适的调参方案：

| 方案 | 搜索策略 | 优势 | 劣势 |
|------|----------|------|------|
| 方案1 | ... | ... | ... |
| 方案2 | ... | ... | ... |

选最优方案，记录到 `experiment/decision_log.md`。

---

## 1.5 参数扫描与达标定义

扫描代码识别可调参数，按类别整理：

| 类别 | 参数 | 当前值 | 建议范围 | 优先级 |
|------|------|--------|----------|--------|
| 核心参数 | learning_rate | ... | ... | 高 |
| 结构参数 | num_layers | ... | ... | 中 |
| 数据参数 | augmentation | ... | ... | 中 |
| 训练参数 | batch_size | ... | ... | 高 |

达标标准格式：
- **主要指标**（必须全部满足）：指标名 >= 目标值
- **次要指标**（尽量满足）：指标名 >= 目标值
- **终止条件**：达标 / 放弃条件

如果用户没给出具体数字，根据项目类型、baseline 指标、业界水平自行推断，在 decision_log.md 中说明依据。

---

## 1.6 大纲自审（审查前置）

参数规划完成后、开始调参前，先自审：

- [ ] 参数范围是否合理（不过宽也不过窄）
- [ ] 达标标准是否可达（基于 baseline 和业界水平）
- [ ] 调参策略是否适合项目特点
- [ ] 是否遗漏了重要参数
- [ ] 数据集策略是否合理

发现问题立即修正，不带着问题进入调参阶段。

---

## 故障处理

Step 1 专属故障：

| 场景 | 处理 |
|------|------|
| 数据集路径错误 | 检查路径是否存在，不存在则在 dataset_info.md 中记录 |
| 数据集损坏 | 记录损坏文件，排除后继续 |
| 代码有 bug 跑不通 | 自动修复流程（见下） |

### 自动代码修复流程

baseline 跑不通时，不等用户，自动修复。**修复前先备份**：

0. **备份**：将待修改的文件复制到 `{exp_dir}/checkpoints/pre-autofix/`（保留原始文件，修复失败时可恢复）
1. **读错误日志**：提取最后 20 行错误信息
2. **定位问题**：根据错误类型判断：
   - `ModuleNotFoundError` → 缺依赖，自动 `pip install`
   - `FileNotFoundError` → 路径问题，自动修正路径
   - `CUDA out of memory` → 自动降低 batch_size
   - `SyntaxError` / `IndentationError` → 自动修正语法
   - 其他 → **不自动修复**，记录到 decision_log.md，标记为"需用户介入"
3. **修复代码**：用 Edit 工具修改（仅限上述明确类型的修复，不做猜测性修改）
   - **禁止自动修改**：数据预处理逻辑、评估指标计算、损失函数定义、数据加载器。这些文件的修改必须在用户介入时由用户确认
4. **验证修复**：重新运行 baseline
5. **记录修复**：将 bug 和修复方案写入 `experiment/decision_log.md`
6. **更新参数表**：如果修复修改了参数默认值（如 batch_size 因 OOM 被降低），同步更新 1.8 参数扫描的参数表中的"当前值"和"建议范围"

最多自动修复 3 次。3 次仍失败 → **从备份恢复原始文件**，记录所有尝试过的修复，标记为"需用户介入"。

通用故障规则见 `references/failure-recovery.md`。

---

## 增量记录

完成后写 `experiment/delta-step1.md`：
- 项目目标和关键信息摘要
- 数据集关键特征
- baseline 指标和耗时
- 选定的调参策略
- 参数表摘要
- 达标标准
- 大纲自审结果
