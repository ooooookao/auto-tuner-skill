# 配置生成策略

本文档定义如何为不同类型的项目生成调参配置文件。

---

## 框架识别

Step 1 参数扫描时，自动识别项目类型：

| 识别方式 | 匹配条件 | 项目类型 |
|----------|----------|----------|
| `import torch` 或 `from torch` | 代码中存在 | PyTorch |
| `import tensorflow` 或 `import keras` | 代码中存在 | TensorFlow/Keras |
| `from sklearn` 或 `import sklearn` | 代码中存在 | scikit-learn |
| `import xgboost` / `import lightgbm` | 代码中存在 | XGBoost/LightGBM |
| 存在 `.yaml`/`.json` 配置文件 + 训练脚本读取配置 | 配置驱动 | 配置驱动型（通用） |
| 以上均不匹配 | — | 自定义脚本 |

**识别结果记入 `experiment/dataset_info.md`**，后续配置生成按此类型选择策略。

---

## 配置生成方法

### PyTorch 项目

**典型特征**：有 `train.py` 或类似入口脚本，参数通过 argparse、YAML 配置文件或代码常量传入。

**生成策略**：
1. 检查项目是否使用配置文件（搜索 `*.yaml`、`*.json`、`*.cfg`）
2. **有配置文件** → 复制模板配置，按参数表修改对应字段，保存到 `experiment/round-N/config-NNN.yaml`
3. **无配置文件（argparse）** → 生成启动脚本 `experiment/round-N/run-config-NNN.sh`，内容为 `python train.py --lr 0.001 --batch_size 16 ...`
4. **代码常量** → 复制源码到 `experiment/round-N/config-NNN/`，用 Edit 工具修改常量值

**并行运行**：每组配置启动一个 Agent（方式 A），prompt 中包含配置文件路径和运行命令。

### TensorFlow/Keras 项目

**生成策略**：同 PyTorch，额外注意：
- Keras 的 `model.compile()` 参数（optimizer、loss）通常在代码中
- 如果使用 `tf.flags` 或 `absl.flags`，通过命令行参数传入
- 如果使用 `json` 配置，同 PyTorch 配置文件方式

### scikit-learn 项目

**典型特征**：参数直接传给模型构造函数（如 `RandomForestClassifier(n_estimators=100)`）。

**生成策略**：
1. 生成参数覆盖脚本 `experiment/round-N/config-NNN.py`，内容为字典：
   ```python
   params = {
       "n_estimators": 200,
       "max_depth": 10,
       "min_samples_split": 5
   }
   ```
2. 训练脚本读取此字典并传给模型
3. 如果原项目不方便修改，生成 wrapper 脚本：复制 train.py → 替换参数常量 → 保存到 `experiment/round-N/`

**并行运行**：轻量实验用 Bash 后台（方式 B），耗时长用 Agent 并行（方式 A）。

### XGBoost/LightGBM 项目

**生成策略**：同 scikit-learn，额外注意：
- 参数字典包含 `num_boost_round`、`early_stopping_rounds` 等训练参数
- 使用 `xgb.train(params, dtrain, num_boost_round=N)` 的 API 格式

### 数值模拟 / 配置驱动型项目

**典型特征**：参数通过独立配置文件（YAML/JSON/TOML/INI）传入，训练/模拟脚本读取配置文件。

**生成策略**：
1. 找到配置文件模板（通常是项目根目录下的默认配置）
2. 复制模板到 `experiment/round-N/config-NNN.yaml`
3. 按参数表修改对应字段
4. 运行命令指向新配置文件：`python simulate.py --config experiment/round-N/config-NNN.yaml`

### 自定义脚本（Fallback）

**当项目类型不在上述列表中时**，使用通用策略：

1. **分析参数传入方式**：读训练脚本，找到参数定义位置（argparse/配置文件/代码常量）
2. **选择最简单的方式**：优先用命令行参数 > 配置文件 > 代码复制
3. **生成配置**：按最简单方式生成配置文件或启动脚本
4. **记录决策**：在 `experiment/decision_log.md` 中记录选择的配置方式和原因

**不要因为"类型不在列表中"就卡住**——任何项目都有参数传入方式，找到它并生成配置即可。

---

## 配置生成与采样策略的关系

配置生成（本文件）负责"怎么写配置文件"，采样策略（step2-tuning.md 的"配置生成策略"表）负责"选什么参数值"。

两者独立：
1. 采样策略决定参数值：随机采样 / 扰动采样 / 精细扰动
2. 配置生成把参数值写入项目能读取的配置文件

---

## Optuna 集成（可选）

如果环境中安装了 Optuna（`python -c "import optuna"` 成功），可以使用 Optuna 替代手动采样：

### 检测方法

```bash
python -c "import optuna; print(optuna.__version__)" 2>/dev/null
```

成功 → 使用 Optuna 模式。失败 → 使用默认的手动采样模式。

### Optuna 模式下的配置生成

1. 定义 `objective(trial)` 函数，其中用 `trial.suggest_float()`、`trial.suggest_int()` 声明参数空间
2. 运行 `study.optimize(objective, n_trials=N)`，Optuna 自动选择参数值
3. 每个 trial 的参数通过 `trial.params` 获取，按上述框架类型写入配置文件
4. 提前终止：在 `objective` 中调用 `trial.report()` + `trial.should_prune()`，配合 `HyperbandPruner`

### Optuna 与手动采样的关系

| 场景 | 使用 Optuna | 使用手动采样 |
|------|------------|-------------|
| 环境有 Optuna | ✓ TPE 采样 + Pruner 提前终止 | 作为 fallback |
| 环境无 Optuna | — | ✓ 随机/扰动/精细采样 |
| 需要自定义搜索空间 | ✓ Define-by-Run 灵活定义 | 需要手动实现 |
| 参数重要性 | ✓ `optuna.importance` | Step 2 手动计算 |

**降级链**：Optuna TPE → 趋势分析 + 扰动采样 → 随机采样。详见 `failure-recovery.md`。

---

## 进度监控（提前终止用）

Step 2 的提前终止逻辑（训练到 20% 时检查）需要获取训练进度。各框架实现方式：

| 框架 | 进度获取方式 | 实现 |
|------|-------------|------|
| PyTorch | `current_epoch / total_epochs` | 在训练循环中打印进度，agent 从日志读取 |
| TensorFlow/Keras | `on_epoch_end` callback | 训练脚本内置 callback 输出进度 |
| sklearn | `warm_start` + 手动迭代 | 分阶段训练，每阶段记录指标 |
| 自定义脚本 | 从日志/输出文件读取 | 搜索训练日志中的进度标记（如 "Epoch 5/100"） |

**通用方案**：在 Agent prompt 中要求训练脚本每 N% 打印一次进度（如 `print(f"Progress: {epoch}/{total_epochs}")`），agent 从日志文件读取进度并在 20% 时检查指标。如果训练脚本不输出进度，agent 在启动训练后等待预估时间的 20% 再做第一次检查。
