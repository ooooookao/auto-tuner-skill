# 示例：心脏 CT 分割调参记录

这是一个完整的调参过程示例，展示 auto-tuner skill 的典型工作流程。

---

## 项目概况

- **项目**：心脏 CT 分割（U-Net + PyTorch）
- **硬件**：RTX 3090 24GB × 1
- **目标**：左心室 dice >= 0.90，右心室 dice >= 0.88，心肌 dice >= 0.85
- **Baseline**：dice_lv=0.72, dice_rv=0.65, dice_myo=0.60

---

## Step 0：工作区确认

```
用户：帮我调参，项目在 E:/project/cardiac_seg/，数据在 D:/datasets/cardiac_ct/，目标是心脏分割 dice >= 0.9

Agent：
1. 列出 E:/project/cardiac_seg/ 目录结构
2. 确认 train.py, config.yaml, dataset/ 存在
3. 发现数据在外部目录，一并配置权限
4. 通过 update-config 配置两个目录的完整权限
```

## Step 1：规划（耗时 ~5 分钟）

### 项目理解
- 读取 train.py 和 config.yaml
- 识别框架：PyTorch + monai
- 评估指标：Dice coefficient
- 硬件：RTX 3090 24GB

### 数据集检查
- 训练集：800 例，验证集：200 例
- 格式：NIfTI (.nii.gz)
- 类别：3 类（左心室、右心室、心肌）
- 类别不平衡：心肌占比 ~5%

### Baseline
- 运行 1 个 epoch 估算耗时：~8 分钟/epoch
- 用户选择：子集快速调参（先用 20% 数据）

### 参数规划

| 类别 | 参数 | 当前值 | 建议范围 | 优先级 |
|------|------|--------|----------|--------|
| 核心 | learning_rate | 0.001 | 0.0001-0.01 | 高 |
| 核心 | batch_size | 8 | 4-16 | 高 |
| 正则 | weight_decay | 0 | 0-0.1 | 中 |
| 正则 | dropout | 0 | 0-0.3 | 中 |
| 数据 | augmentation | None | [flip, rotate, elastic] | 中 |
| 损失 | loss_fn | CE | [CE, Dice, CE+Dice] | 高 |

### 自我辩论
- 方案 A：先调 lr + batch_size，再调正则化
- 方案 B：先换 loss 函数，再调其他参数
- 选择：方案 A（更稳妥，loss 函数变化太大）

---

## Step 2：调参过程（共 12 轮，耗时 ~3 小时）

### Round 1：粗搜（5 配置）

| 配置 | lr | batch_size | loss_fn | dice_lv | dice_rv | dice_myo | 状态 |
|------|-----|-----------|---------|---------|---------|----------|------|
| c001 | 0.001 | 8 | CE | 0.74 | 0.67 | 0.62 | completed |
| c002 | 0.0005 | 16 | CE | 0.76 | 0.69 | 0.64 | completed |
| c003 | 0.0001 | 8 | CE | 0.71 | 0.64 | 0.59 | pruned |
| c004 | 0.005 | 4 | CE | 0.68 | 0.61 | 0.55 | completed |
| c005 | 0.0005 | 8 | Dice | 0.78 | 0.72 | 0.67 | completed |

**关键发现**：lr=0.0005 最好，Dice loss 对小类别有帮助。

### Round 2：围绕最佳探索（5 配置）

| 配置 | lr | batch_size | loss_fn | weight_decay | dice_overall |
|------|-----|-----------|---------|-------------|-------------|
| c006 | 0.0005 | 16 | Dice | 0 | 0.79 |
| c007 | 0.0003 | 16 | Dice | 0.01 | 0.81 |
| c008 | 0.0008 | 8 | Dice | 0 | 0.77 |
| c009 | 0.0005 | 16 | Dice | 0.05 | 0.80 |
| c010 | 0.0005 | 8 | CE+Dice | 0.01 | 0.82 |

**关键发现**：CE+Dice 组合 loss 最佳，weight_decay=0.01 有帮助。

### Round 3-5：细搜

参数重要性分析：
- learning_rate: 高 (0.42)
- loss_fn: 高 (0.35)
- weight_decay: 中 (0.18)
- batch_size: 低 (0.08) → 固定为 16

Round 5 最佳：dice_lv=0.85, dice_rv=0.80, dice_myo=0.75

### Round 6-8：加入数据增强

| 配置 | augmentation | dice_overall | 变化 |
|------|-------------|-------------|------|
| c021 | flip+rotate | 0.86 | +0.01 |
| c022 | flip+rotate+elastic | 0.88 | +0.03 |
| c023 | flip+rotate+elastic+intensity | 0.87 | +0.02 |

关键发现：elastic 变形对心脏形状变化建模有帮助。

### Round 9-10：微调

dice_lv=0.89, dice_rv=0.86, dice_myo=0.82 — 距目标仍有差距。

---

## Step 3：架构回溯（触发于 Round 10）

### 触发条件
连续 10 轮无明显提升（最近 5 轮 dice 变化 < 0.01），距目标 dice_lv >= 0.90 差 0.01。

### 诊断
分析 loss 曲线：训练 loss 在下降但验证 loss 停滞 — **过拟合**。

### 搜索方案

子 agent 搜索结果：

| 方案 | 来源 | 预期收益 | 风险 |
|------|------|----------|------|
| 加 dropout | 常规正则化 | 减少过拟合 | 可能欠拟合 |
| 加 attention gate | nnUNet 论文 | 提升小目标分割 | 增加显存 |
| 换 deeper architecture | GitHub 高星项目 | 增加容量 | 训练变慢 |

自我辩论：选择 attention gate（小改动，针对性强）。

### 执行
- 存档到 `experiment/checkpoints/checkpoint-v1/`
- 在 U-Net 的 skip connection 加 attention gate
- 重新调参

### 结果
Round 11-12（新架构）：
- dice_lv=0.92 ✅, dice_rv=0.89 ✅, dice_myo=0.86 ✅

**达标！**

---

## Step 4：报告

生成 `experiment/report.md`，包含：
- 最佳配置表
- 参数敏感性分析
- 架构变更历史
- 调参历程总结
- 成本统计：~120,000 tokens，总耗时 3.5 小时

---

## 经验提取

写入 `experience/image-segmentation.md`：
1. CE+Dice 组合 loss 对类别不平衡的医学分割效果好
2. elastic 变形对器官形状变化建模有帮助
3. attention gate 对小目标分割有效，且改动小风险低
4. lr 在 0.0003-0.0008 范围内最稳定
