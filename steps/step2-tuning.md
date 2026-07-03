---
step: 2
title: 调参主循环
---

# Step 2：调参主循环

**目的**：执行参数搜索、收集结果、分析趋势、迭代优化，直到达标或放弃。
**前置**：Step 1 完成（参数规划、达标标准已定义）。
**输出**：`experiment/results.json`、`experiment/progress.md`。

**本 Step 是调参的核心循环**，包含执行和分析两个阶段。每轮循环：执行 → 分析 → 决策 → 下一轮。

---

## 操作清单

- [ ] 2.1 建立实验目录结构
- [ ] 2.2 检测 GPU/内存资源上限（按空闲显存计算，预留 15% 余量）
- [ ] 2.3 首次 1 路 baseline 测量真实峰值显存
- [ ] 2.4 生成第一轮配置
- [ ] 2.5 并行运行（路数由 free_memory×0.85 / peak_memory 决定，多卡隔离 CUDA_VISIBLE_DEVICES）
- [ ] 2.6 监控进度、收集结果
- [ ] 2.7 写入 results.json 和 progress.md
- [ ] 2.8 趋势分析 + 参数重要性（详见 2.4 节）
- [ ] 2.9 检查终止/审查/架构回溯条件
- [ ] 2.10 生成下一轮配置并继续，或跳 Step 4

---

## 调参主循环

```
┌─────────────────────────────────────────────────────┐
│                    Step 2 循环                        │
│                                                      │
│  生成配置 → 并行执行 → 收集结果 → 写 results.json     │
│       ↓                                              │
│  趋势分析 → 参数重要性 → 收敛/死循环检测              │
│       ↓                                              │
│  达标？ ──→ Yes ──→ Step 4（报告）                   │
│       ↓                                              │
│  放弃？ ──→ Yes ──→ Step 4（报告）                   │
│       ↓                                              │
│  架构回溯？ ──→ Yes ──→ Step 3（架构优化）           │
│       ↓                       ↓                      │
│  No ←────────────── 回到循环开头                      │
└─────────────────────────────────────────────────────┘
```

**核心原则**：Step 2 是主控循环，Step 3 只在需要架构变更时才介入。

---

## 2.1 环境准备

**必须**：每轮开始前先读 `experiment/state.json`，确认 `next_action` 为 `generate_configs`。
如果 next_action 不匹配，检查是否因用户干预或断点恢复改变了状态。

建立目录结构：`experiment/round-N/config-NNN/`

检测资源：
- GPU 型号和显存总量（`nvidia-smi`）
- 可用内存
- 磁盘空间

---

## 2.2 GPU/并行执行（实操指南）

### 资源检测

每轮开始前检测真实可用资源：

```bash
nvidia-smi --query-gpu=index,name,memory.total,memory.free,memory.used,utilization.gpu --format=csv
```

记录：
- 每张 GPU 的 `memory.free`（不是 `memory.total`）
- 当前利用率 / 是否有其他占用进程
- 系统空闲内存、CPU 核心数、磁盘剩余空间

### 单实验峰值测量

**首次执行必须先用 1 路 baseline 测量真实峰值显存**，不要直接按理论值或默认 5 路启动。

测量方法：
1. 取 Step 1 的默认/当前最佳配置，启动 1 个训练进程。
2. 在训练最密集阶段（通常第 1-2 个 epoch）读取 `nvidia-smi` 峰值。
3. 记录 `peak_gpu_memory_gb` 到 `experiment/hardware_profile.md`。

### 并行路数计算

基于**空闲显存**计算，而非总显存：

```
safe_memory_per_gpu_gb = free_memory_gb * 0.85
max_parallel_per_gpu   = floor(safe_memory_per_gpu_gb / peak_gpu_memory_gb)
total_parallel         = sum(max_parallel_per_gpu across all available GPUs)
upper_cap              = min(total_parallel, 8)
```

约束：
- 至少保留 15% 显存余量，防止显存碎片、CUDA 上下文和同时启动峰值。
- 多卡时按卡隔离：为每个子进程显式设置 `CUDA_VISIBLE_DEVICES`，不要让多个实验共享同一张卡。
- 如果单张卡空闲显存不足以跑 1 路（即使按 0.85 折算后），先尝试降低 batch_size / 减小输入尺寸，而不是跨卡拆分同一次实验。
- DataLoader 的 CPU 内存、磁盘 I/O 和临时文件竞争也会限制并行数。若出现 CPU 100% 或磁盘饱和，优先降路数而不是继续加卡。

### 启动扩容策略

```
第 1 次：1 路 baseline（测峰值 + 验代码）
第 2 次起：按上述公式计算并行路数
后续：动态监控，显存 >85% 时减 1 路，<50% 持续 2 分钟且 CPU/磁盘未饱和时加 1 路
```

### 多卡隔离与输出隔离

每个并行实验必须：
- 绑定指定 GPU：`CUDA_VISIBLE_DEVICES={gpu_index}`
- 写入独立目录：`experiment/round-N/config-NNN/`
- 使用独立 checkpoint、日志、tensorboard 目录，禁止多实验共享同名文件
- 结果文件独立：`experiment/round-N/config-NNN/result.json`

### 并行方式选择

决策树（在计算出的并行路数内选择执行方式）：

```
需要修改代码？ ──→ Yes ──→ 方式 C（Worktree 隔离）
       ↓ No
实验轻量（<5min）？ ──→ Yes ──→ 方式 B（Bash 后台）
       ↓ No
  ──→ 方式 A（Agent 并行，默认）
```

### 方式 A：Agent 并行（推荐，适用于独立实验）

每组配置用一个独立 Agent 执行，天然并行且上下文隔离：

```
单轮流程：
1. 生成 N 组配置（N ≤ 计算出的并行上限）
2. 为每组配置启动一个 Agent（background=true），prompt 包含：
   - 配置参数
   - 训练脚本路径和运行命令
   - 分配的 GPU index（CUDA_VISIBLE_DEVICES）
   - 结果输出路径（写到 experiment/round-N/config-NNN/result.json）
   - 超时时间
3. 所有 Agent 启动后，等待返回
4. 主 agent 串行收集各 Agent 的 result.json，合并到 results.json
5. 主 agent 更新 progress.md（只有主 agent 写 progress.md，子 agent 不写）
6. 决策记录写入 decision_log.md（只有主 agent 写，子 agent 不写）
```

**Agent prompt 模板**：
```
运行以下训练实验，将结果写到 {result_path}：
- 项目路径：{project_path}
- 分配 GPU：CUDA_VISIBLE_DEVICES={gpu_index}
- 修改参数：{param_changes}
- 运行命令：{run_command}
- 超时：{timeout}
- 结果格式：{"metrics": {...}, "status": "completed/failed/oom", "duration_min": N, "peak_gpu_memory_gb": N}
要求：
1. 启动后 30 秒内报告进程是否存活
2. 如果 OOM，降低 batch_size 50% 重试一次；仍失败则 status="oom"
3. 结果文件必须独立写入指定目录，不要覆盖其他实验的文件
```

### 方式 B：Bash 后台并行（适用于轻量实验）

直接用 Bash 的 `run_in_background` 并行运行多个训练进程，每进程绑定不同 GPU：

```bash
CUDA_VISIBLE_DEVICES=0 python train.py --config experiment/round-1/config-001.yaml --outdir experiment/round-1/config-001/ &
CUDA_VISIBLE_DEVICES=1 python train.py --config experiment/round-1/config-002.yaml --outdir experiment/round-1/config-002/ &
# ...按计算出的路数启动，每卡不超过 max_parallel_per_gpu
wait
```

### 方式 C：Worktree 隔离（适用于需要修改代码的实验）

Git 项目用 worktree 隔离不同配置的代码修改：

```
1. EnterWorktree 创建隔离环境
2. 在 worktree 中修改代码/参数
3. 绑定指定 GPU，运行训练
4. 收集结果后 ExitWorktree
```

### OOM 处理

| 场景 | 处理 |
|------|------|
| 单路 OOM | 该分支降低 batch_size 50% 重试，最多 2 次；同时记录峰值，必要时下调后续并行路数 |
| 多路同时 OOM | 立即暂停新启动，当前存活实验继续；下一轮按 free_memory * 0.80 重新计算 |
| 全部 OOM | 全局降低 batch_size 或减小输入尺寸，重新测峰值后再扩容 |
| 显存碎片导致 OOM | 减少每卡并行数，留出更大余量 |

**无 GPU 时**：CPU 模式下并行路数 = min(CPU 核心数 / 2, 内存允许路数, 8)，使用方式 B（Bash 后台）。内存允许路数 = (free_ram_gb * 0.7) / 单进程峰值内存。

---

## 2.3 单轮流程

```
生成 N 组配置（首轮：从 Step 1 参数表按粗搜范围随机采样 5-10 组；
       后续轮次：基于趋势分析，在最佳配置附近扰动采样，见下方"配置生成策略"）
  → 📝 更新 state.json：next_action="run_experiments", round=N, search_stage
  → 📝 更新 progress.md：本轮配置已生成
  → 并行运行（方式 A/B/C 选一，见上方决策树），每个子 agent 写结果到独立文件
  → 监控进度（检查进程是否存活、GPU 利用率）
  → 📝 主 agent 串行收集子 agent 结果，更新 progress.md
  → 中途检查（训练 20% 时，见"提前终止"——在训练中途触发，与下方 Gate 互不干扰）
  → 收集结果（等待所有分支完成或超时）
  → ⚠️ Gate：检查 results.json 数据完整性（所有分支已返回/超时/标记 failed）
  → 写入 results.json（格式见下方"results.json 格式"，严格遵循 results.schema.json）
  → 趋势分析 + 参数重要性（见 2.4 节）
  → ⚠️ Gate：确认分析已完成，再进入终止判断
  → 📝 更新 state.json：consecutive_no_improvement, best_metrics, last_action="analyze_results", next_action="check_termination"
  → 终止条件判断（见 2.5 节），更新 state.json 的 next_action
```

**Gate 说明**：Gate 是自动检查点（数据完整性 + 分析完成度），不是用户确认点。"全程自主"原则不变。

### 提前终止（Pruning）

优先使用 Optuna HyperbandPruner（如果环境有 Optuna）。手动 pruning 仅作为 fallback。

#### 最小观察要求

任何 pruning 决策前，必须满足：
- 至少观察到 **min(5, 总 epoch 的 25%)** 个 epoch。
- 有 warmup 时，首次检查点不得早于 warmup 结束后的第 2 个 epoch。
- 每个检查点必须基于 **同一训练进度** 的指标比较（例如都在第 5 个 epoch）。

#### 手动 pruning 规则

每个分支到达检查点时，按顺序判断：

1. **Hard fail**：OOM / 崩溃 / NaN loss → status="failed"，立即终止，不重试（本轮内）。
2. **Loss 发散**：连续 3 个 checkpoint 的验证 loss 单调上升（或训练 loss 爆炸 > 初始 10 倍）→ status="pruned"，原因 `loss_divergence`。
3. **同进度分位数比较**：
   - 收集所有**已完成到同一进度**的实验在该进度的指标。
   - 计算目标指标的当前分位数（越大越好用 ≥ 分位，越小越好用 ≤ 分位）。
   - 若连续 2 个 checkpoint 都处于最差 25% 分位，且无上升趋势 → status="pruned"，原因 `bottom_quartile`。
   - 禁止用固定阈值（如 0.1）跨配置比较早期指标。
4. **重建/生成任务双指标**：对于医学图像重建、去噪、生成等任务，必须同时检查：
   - 验证 loss（或 MAE/MSE）
   - 图像质量指标（PSNR、SSIM 等）
   只有两项都持续变差时才 pruning；单指标差但图像指标稳定则继续观察。
5. **慢启动保护**：
   - Cosine / Plateau / 大 warmup 调度下，前 30% epoch 指标波动不直接 pruning，只看 loss 是否发散。
   - 第 30% 后仍无提升，再触发分位数比较。

#### 检查点间隔

- 总 epoch ≤ 10：每 2 个 epoch 检查一次。
- 总 epoch 11-50：每 5 个 epoch 检查一次。
- 总 epoch > 50：每 10 个 epoch 检查一次。

#### 记录

提前终止的分支写入 results.json（status: "pruned"），包含：
- `prune_reason`：loss_divergence / bottom_quartile / user_stop / oom
- `prune_epoch`：终止 epoch
- `metrics_at_prune`：终止时的指标快照

被 pruning 的实验不计入正常统计，但参与分位数计算（避免重复探索已知差的方向）。

### 实验对比表

每轮在 `experiment/progress.md` 中追加一个对比表：

```markdown
## Round 3 对比（最佳：config-007，dice=0.89）

| 配置 | lr | batch_size | dice | loss | 趋势 | 状态 |
|------|-----|-----------|------|------|------|------|
| config-005 | 0.0005 | 16 | 0.87 | 0.13 | → | completed |
| config-006 | 0.0003 | 16 | 0.86 | 0.14 | ↓ | completed |
| config-007 | 0.0005 | 8 | 0.89 | 0.11 | ↑ | completed |
| config-008 | 0.001 | 16 | 0.82 | 0.18 | ↓ | pruned |

参数重要性：lr=高(0.45) | batch_size=中(0.22) | weight_decay=低(0.08)
```

---

## 2.4 趋势分析与收敛检测

每轮收集结果后执行（原 Step 3 的核心分析逻辑，合并到主循环中）：

### 参数重要性分析

从第 3 轮开始（至少积累 15 组 completed 实验后），每轮计算参数重要性。**样本不足时只报告趋势，不永久冻结任何参数。**

#### 优先方法

1. **Optuna fANOVA / permutation importance（推荐）**
   - 如果使用 Optuna，直接调用 `optuna.importance.get_param_importances(study)`。
   - 它自动处理混合类型和交互，优于简单相关。

2. **手动 fallback（无 Optuna 时）**
   - **数值参数**：Spearman 秩相关（对单调非线性更稳健）。报告样本数 n 和 |rho|。
   - **类别参数**：按类别分组统计目标指标均值/中位数，用 ANOVA 或 Kruskal-Wallis 检验 p 值判断是否有显著差异。
   - **交互检测**：用随机森林或基于条件分组的简化方法。只有在样本量 ≥ 30 时才尝试交互检测；否则只标记疑似交互。

#### 统计可靠性要求

- 每个参数的**有效样本数 ≥ 8** 才计算重要性。
- 报告置信区间或 p 值：Spearman 给出 p 值；分组统计给出 Kruskal-Wallis p 值。
- 重要性低（|rho| < 0.2 或 p > 0.1）**不表示参数无用**，可能是：
  - 搜索范围太窄
  - 参数只在特定组合下有效
  - 样本不足

#### 应用规则

| 情况 | 动作 |
|------|------|
| 样本 ≥ 15、fANOVA/permutation 显示重要性 < 0.05 | 标记为"低优先级"，缩小搜索范围，但不永久冻结 |
| 样本 ≥ 15、重要性 > 0.2 | 重点精细搜索 |
| 检测到显著交互 | 相关参数后续同时调整，不独立固定 |
| 样本 < 15 或 p 不显著 | 继续探索，不做冻结决策 |
| 最佳配置出现 | 至少用 2 个不同 seed 复现一次，再确认"收敛" |

#### 禁止行为

- 禁止仅因 |rho| < 0.1 就永久固定参数。
- 禁止在样本不足时将参数标为"不重要"。
- 禁止忽略类别变量的非连续性（不要用 Pearson）。

结果记入 `experiment/decision_log.md` 和 `experiment/progress.md`，包含：样本数、方法、top-3 参数、低优先级参数、疑似交互对。

### 死循环检测

- 连续 3 轮以上核心参数变化 < 5% → 判定为"疑似收敛"，不是死循环。
- 处理：
  1. 用 2 个不同 seed 复现当前最佳配置。
  2. 若复现结果稳定 → 缩小这些参数的搜索范围到 ±5%，进入微调阶段。
  3. 若复现结果波动大 → 扩大范围或换方向，避免虚假收敛。
- 不要"固定"参数后直接放弃探索；记录到 decision_log 并说明理由。

### 递进策略

| 阶段 | 范围 | 配置数 | 目标 |
|------|------|--------|------|
| 粗搜 | 大范围随机采样 | 5-10 | 找方向 |
| 细搜 | 围绕最佳缩小范围 | 3-5 | 收敛 |
| 微调 | 只动 1-2 个参数 | 2-3 | 精修 |

阶段切换时写快照到 `experiment/checkpoint-phase{N}.md`。

### 配置生成策略

每轮配置分两步：**选参数值** + **写配置文件**。

**第一步：选参数值**（采样策略）

| 阶段 | 策略 | 具体操作 |
|------|------|----------|
| 粗搜 | 随机采样 | 从 Step 1 参数表的建议范围中均匀随机采样 |
| 细搜 | 扰动采样 | 以最佳配置为基线，每个参数 ±10%-20% 范围内随机扰动 |
| 微调 | 精细扰动 | 仅动 1-2 个最重要参数，扰动范围 ±5% |

**去重**：采样后检查新配置是否与 results.json 中已有配置重复（所有参数值相同或差异 < 1%）。重复则重新采样，最多重试 3 次。连续 3 次采样到重复值 → 扩大扰动范围 ±5%。

**降级条件**：扰动采样连续 3 轮无提升（最佳指标变化 < 0.005）→ 回退到随机采样（参考 `references/failure-recovery.md` 降级规则）。

**第二步：写配置文件**（按项目类型生成）

按 Step 1 识别的项目类型，参考 `references/config-generation.md` 生成配置文件。核心流程：
1. 框架识别结果来自 `experiment/dataset_info.md`
2. 按对应框架的配置生成方法，将采样到的参数值写入配置文件
3. 配置文件保存到 `experiment/round-N/config-NNN/` 目录

**Optuna 模式**（可选）：如环境有 Optuna，用 `study.optimize()` 替代手动采样，自动选择参数值并生成配置。详见 `references/config-generation.md` 的"Optuna 集成"章节。

---

## 2.5 终止条件与路由

每轮分析完成后，按以下优先级判断下一步：

### 1. 达标 → Step 4

所有主要指标达到目标值。**更新 state.json**：`phase="reporting", next_action="generate_report", stop_reason="target_reached"`。跳到 Step 4 生成报告。

### 2. 放弃 → Step 4

**更新 state.json**：`phase="stopped", next_action="generate_report", stop_reason` 设为对应原因。跳到 Step 4 生成报告。

满足以下**任一**条件：
- 3 种以上架构各调满 10 轮，最佳指标仍距目标 > 0.05
- 跨所有架构累计 50 轮仍无突破（趋势向好可适当放宽）
- 最近 15 轮最佳指标变化 < 0.005（从最近一次重置事件算起：用户干预/熔断重置/架构回溯）

注：质量熔断（连续 3 轮无提升）会先触发"换策略→请求确认→停止"，放弃条件是独立的兜底机制。两者不冲突：熔断处理单阶段内的连续失败，放弃判断全局趋势。

### 3. 架构回溯 → Step 3

**触发**：连续 10 轮无明显提升（< 0.01）且距达标仍有差距（> 0.03）。

**更新 state.json**：`phase="optimization", next_action="architecture_search", architecture_version += 1`。

跳到 Step 3 执行架构优化，完成后回到 Step 2 继续调参。

### 4. 审查触发

- 粗搜完成 → 审查（粗调标准：只看结构性问题）
- 细搜完成 → 审查（细调标准：看所有问题）
- 兜底：超过 15 轮未审查 → 强制触发

审查清单见 `references/review-checklist.md`。审查发现问题立即修正。

### 5. 用户介入点

每 5 轮或每个阶段切换时，向用户发送进度摘要（通过 `experiment/progress.md` 的更新 + 终端输出）：

```
📊 调参进度 | Round 12 | 当前最佳 dice=0.89 (目标 0.90)
  最佳配置：lr=0.0005, bs=16, wd=0.01
  阶段：细搜 | 已耗时 2h15m | 连续 3 轮无提升
  下一步：继续细搜 lr 在 0.0003-0.0007 范围
  [用户可中断并输入新指令调整方向]
```

用户输入任何内容 → agent **先读 state.json**，暂停调参，读取用户指令，调整策略后更新 state.json（phase 不变，next_action 根据用户指令调整）再继续。
用户无输入 → 继续下一轮。

**用户可修改的内容**（显式支持）：

| 用户指令 | agent 处理 |
|----------|-----------|
| "lr 范围改成 0.0001-0.001" | 更新参数表，后续采样用新范围 |
| "目标改成 dice >= 0.95" | 更新达标标准，记录到 decision_log |
| "不要调 dropout" | 从参数表移除，后续不探索 |
| "batch_size 固定为 8" | 固定参数，不再变化 |
| "换 AdamW 优化器" | 修改代码/配置，记录到 decision_log |
| "停掉当前轮次" | 终止所有运行中的实验，跳到下一轮 |
| "回退到上一轮最佳" | 恢复到最佳 checkpoint，继续调参 |

用户输入不在上述列表中 → agent 按字面意思理解并执行，记录到 decision_log。

### 6. 继续下一轮

以上条件都不满足 → 自动生成下一轮配置（见 2.4 节"配置生成策略"），继续循环。

### 死循环检测 vs 质量熔断的优先级

两者都涉及"连续 N 次失败"，但机制不同：

| 机制 | 触发条件 | 动作 | 优先级 |
|------|----------|------|--------|
| 死循环检测 | 连续 3 轮核心参数变化 < 5% | 固定已收敛参数，换方向 | **优先触发** |
| 质量熔断 | 同环节连续 3 次不达标 | 换策略→请求确认→停止 | 兜底 |

**规则**：死循环检测先介入（参数层面），如果换方向后仍触发质量熔断（指标层面），再走熔断流程。

**计数器重置规则**（避免换方向后被旧计数器立即触发熔断）：
- 死循环检测换方向后 → 重置质量熔断计数器
- 用户干预修改参数范围/目标后 → 重置质量熔断计数器
- 放宽达标标准后 → 重置质量熔断计数器
- 架构回溯回到 Step 2 后 → 重置质量熔断计数器

---

## 2.6 Progress.md 与 State.json

**路由决策读 `state.json`，进度展示写 `progress.md`**。详见 `references/state-schema.md`。

`state.json` 是 agent 的**机器状态**（JSON，覆盖写），`progress.md` 是**人类可读进度**（Markdown，追加+覆盖顶部）。每次执行重大操作前必须读 `state.json` 确认 `next_action`，每次状态变化后立即更新两个文件。

### 文件结构

progress.md 由三部分组成：**当前状态**（覆盖写，始终在最顶部）+ **最佳排行榜**（覆盖写）+ **近期历史**（追加写，保留最近 5 轮）。

```markdown
# 调参进度

## 当前状态

| 项 | 值 |
|----|-----|
| 阶段 | 细搜（第 2 阶段） |
| 轮次 | Round 8，进行中 |
| 当前最佳 | dice=0.89 (目标 0.90) |
| 最佳配置 | config-023 (lr=0.0005, bs=16, wd=0.01, loss=CE+Dice) |
| 参数状态 | lr 已收敛(0.0003-0.0007)，batch_size 固定=16，weight_decay 搜索中 |
| 下一步 | 围绕 config-023 扰动采样 lr 和 weight_decay |
| 已耗时 | 2h15m | 总轮数 8 | 总实验数 37 |
| 最近用户干预 | 无 |
| 最近失败 | config-021 OOM (bs=32) |

## 最佳配置排行榜（Top 5）

| 排名 | 配置 | 阶段 | 轮次 | 核心参数 | 指标 |
|------|------|------|------|----------|------|
| 1 | config-023 | 细搜 | R7 | lr=0.0005, bs=16, wd=0.01 | dice=0.89 |
| 2 | config-034 | 细搜 | R7 | lr=0.0005, bs=16 | dice=0.89 |
| 3 | config-033 | 细搜 | R7 | lr=0.0005, bs=16, wd=0.005 | dice=0.88 |
| 4 | config-011 | 粗搜 | R3 | lr=0.0005, bs=16 | dice=0.87 |
| 5 | config-036 | 细搜 | R8 | lr=0.0004, bs=16, wd=0.008 | dice=0.88 |

---

## Round 8 | 进行中

**配置生成**：扰动采样，基于 config-023 ±15%

| 配置 | lr | bs | wd | dice | 状态 |
|------|-----|----|----|------|------|
| c036 | 0.0004 | 16 | 0.008 | 0.88 | ✅ |
| c037 | 0.0006 | 16 | 0.012 | 0.87 | ✅ |
| c038 | 0.0005 | 16 | 0.015 | — | ⏳ |

---

## Round 7 | 完成

**最佳**：config-023 (lr=0.0005, bs=16, dice=0.89)

| 配置 | lr | bs | dice | 状态 |
|------|-----|----|------|------|
| c031 | 0.0004 | 16 | 0.87 | ✅ |
| c034 | 0.0005 | 16 | 0.89 | ✅ 最佳 |
| c035 | 0.0003 | 16 | 0.85 | ✅ |

---

## [时间] 用户干预

- **用户指令**：不要调 dropout，先集中搞 lr 和 loss 函数
- **agent 调整**：从参数表中移除 dropout
- **影响**：后续轮次不再探索 dropout 空间

---
```

历史记录超过 5 轮时，将最早的轮次压缩为一行摘要移入 `results.json`（不在 progress.md 中累积）。

### 读取时机（必须）

| 时刻 | 读取目的 |
|------|----------|
| **每轮开始** | 读"当前状态"节，确认阶段、最佳配置、下一步计划 |
| 上下文压缩后 | 读全文件，恢复被压缩的上下文 |
| 断点恢复（新 session） | 读全文件，重建完整状态 |
| 用户中断后恢复 | 读全文件，了解中断前的状态 |
| 生成最终报告 | 读全文件，获取完整历程 |

### 更新时机（必须）

| 事件 | 操作 |
|------|------|
| 开始新一轮 | **覆盖**"当前状态"节，**追加**新轮次标题到历史 |
| 单个实验完成/失败/prune | **覆盖**"当前状态"中的"最近失败"，**追加**行到当前轮次表格 |
| 整轮结束 | **覆盖**"当前状态"节（更新最佳、参数状态、下一步） |
| 用户干预 | **覆盖**"当前状态"中的"最近用户干预"，**追加**干预记录到历史 |
| 阶段切换 | **覆盖**"当前状态"节（阶段、轮次重置），**追加**阶段切换记录 |
| 审查触发 | **追加**审查结果到历史 |
| 参数收敛/固定 | **覆盖**"当前状态"中的"参数状态" |

### 与 results.json 的分工

| 文件 | 职责 | 写入频率 |
|------|------|----------|
| progress.md | 当前状态 + 轮次摘要（最佳配置、指标、状态列） | 每个事件 |
| results.json | 完整数据（所有配置的全部参数、全部指标、耗时、显存） | 每轮结束 |

progress.md 的历史表格只保留摘要列（配置ID、关键参数、最佳指标、状态），不复制 results.json 的完整数据。需要详情时从 results.json 读取。

### 核心原则

- **"当前状态"节始终反映最新状态**，不累积，直接覆盖
- **历史记录只追加不删除**，保留完整历程
- **agent 不依赖对话记忆**，任何时候都能从 progress.md 重建上下文
- **用户可以随时打开 progress.md 看到最新进展**，无需翻历史

---

## 2.7 上下文管理

### 压缩触发时机

- **每 5 轮**：主动压缩早期轮次详情
- **阶段切换时**（粗搜→细搜、细搜→微调）：压缩上一阶段全部详情
- **累计超过 8 轮未压缩**：强制压缩（不管上下文是否变长）

### 压缩操作

将对话上下文中早期轮次的详细结果替换为一行摘要，同时确保文件中保留完整信息：

```
压缩前（对话中）：
  Round 1: config-001 lr=0.001 bs=8 dice=0.74 loss=0.15 status=completed ...
  Round 1: config-002 lr=0.0005 bs=16 dice=0.76 loss=0.13 status=completed ...
  Round 1: config-003 lr=0.0001 bs=8 dice=0.71 loss=0.18 status=pruned ...
  ...（5 组配置的完整详情）

压缩后（对话中）：
  Round 1 摘要：5 配置，最佳 config-002 (lr=0.0005, bs=16, dice=0.76)，1 组 pruned
```

### 压缩规则

| 内容 | 对话上下文 | 文件 |
|------|-----------|------|
| 最近 3 轮详情 | 保留完整 | 完整保留 |
| 更早轮次 | 压缩为 1 行摘要 | 完整保留在 results.json |
| 每轮最佳配置 | 始终保留 | 完整保留 |
| 失败配置详情 | 压缩为"为什么失败"一句话 | 完整保留在 results.json |
| 关键决策和发现 | 始终保留 | decision_log.md |
| 调试输出 | 删除 | 不写入 |

### 关键原则

**所有重要结论必须写入文件，不依赖对话记忆。** 压缩只影响对话上下文，不修改任何文件。如果后续需要某个已压缩轮次的详情，从 results.json 重新读取。

**压缩后必须读取 progress.md**（见 2.6 的读取时机表），从"当前状态"节恢复上下文。

---

## 2.8 通知

调参完成（达标或放弃）时，通过用户的 Claude Code 通知机制告知结果，附上报告路径和关键指标摘要。

---

## 故障处理

通用故障规则见 `references/failure-recovery.md`。

Step 2 专属补充：

| 场景 | 处理 |
|------|------|
| GPU 被其他进程占用 | 检测并等待释放，或降低并行路数 |
| 磁盘空间不足 | 清理旧轮次中间文件，保留结果摘要 |
| 训练代码报错 | 自动修复流程（同 step1：读日志→定位→修复→验证，最多 3 次） |

---

## 增量记录

每轮结束后追加到 `experiment/delta-step2.md`：
- 本轮配置数量和成功率
- 最佳指标和对应参数
- 资源使用情况
- 是否触发压缩
- 趋势分析结论
- 采样策略（随机/扰动/精细/Optuna TPE）
- 配置生成方式（框架类型 + 生成方法）
- Optuna 使用情况（如适用：trial 数、pruned 数、importance 排名）

---

## results.json 格式

**所有写入必须严格遵循 `references/results.schema.json`（JSON Schema 定义）**。字段名与 schema 一致（round_id 而非 round，config_id 而非 id，gpu_memory_gb 而非 memory_peak_gb）。写入后建议用简单规则自检：每个 config 对象必须包含 config_id、params、metrics、status、duration_min、error_type、attempt、retry_of 八个必填字段。

合法 status 值：`completed` / `failed` / `oom` / `pruned`。多轮写入前用 `python -c "import json; json.load(open('experiment/results.json'))"` 验证 JSON 完整性。**强烈建议每次写入后用 schema 正式校验**：

```bash
python -c "import json; from jsonschema import validate, FormatChecker; \
s=json.load(open('references/results.schema.json',encoding='utf-8')); \
d=json.load(open('experiment/results.json',encoding='utf-8')); \
validate(d, s, format_checker=FormatChecker()); print('results.json OK')"
```

**OOM 重试时的字段写法**（同一 config_id 多次执行，靠 attempt 区分）：

```json
{
  "config_id": "config-003",
  "params": {"learning_rate": 0.001, "batch_size": 32},
  "metrics": {},
  "status": "oom",
  "duration_min": 5,
  "gpu_memory_gb": 23.5,
  "seed": 44,
  "commit_hash": "a1b2c3d",
  "error_type": "OOM",
  "attempt": 1,
  "retry_of": null
},
{
  "config_id": "config-003",
  "params": {"learning_rate": 0.001, "batch_size": 16},
  "metrics": {"dice": 0.84},
  "status": "completed",
  "duration_min": 45,
  "gpu_memory_gb": 11.8,
  "seed": 44,
  "commit_hash": "a1b2c3d",
  "error_type": null,
  "attempt": 2,
  "retry_of": "config-003"
}
```

参考示例见 `examples/results.example.json`。

每轮调参结束后追加一条记录到 `experiment/results.json`（注意字段已更新为 schema 定义的标准名称）：

```json
[
  {
    "round_id": 1,
    "timestamp": "2024-01-15T10:30:00",
    "configs": [
      {
        "config_id": "config-001",
        "params": {"learning_rate": 0.001, "batch_size": 16},
        "metrics": {"dice_lv": 0.85, "dice_rv": 0.82, "dice_overall": 0.87, "loss": 0.15},
        "train_loss": 0.12,
        "val_loss": 0.15,
        "status": "completed",
        "duration_min": 45,
        "gpu_memory_gb": 6.2,
        "seed": 42,
        "commit_hash": null,
        "error_type": null,
        "attempt": 1,
        "retry_of": null
      }
    ],
    "best_config_id": "config-001",
    "resource_usage": {"parallel_count": 5, "gpu_utilization": "72%"}
  }
]
```

### 兼容性说明

旧版 results.json 使用 `round`、`id`、`memory_peak_gb`、`best_config` 等字段名。写入新数据时按 schema 标准名称写。读取时按"新字段优先，旧字段 fallback"原则兼容。迁移完成后不再支持旧字段名。
