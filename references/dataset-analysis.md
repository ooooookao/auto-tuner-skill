# 数据集全面分析规则

本文档定义调参前数据集分析的维度、方法、输出格式。

---

## 分析维度

### A. 基础统计

| 检查项 | 方法 | 输出 |
|--------|------|------|
| 样本总量 | 统计各 split 文件数量 | 训练 N / 验证 N / 测试 N |
| 划分比例 | 计算比例 | 如 70% / 15% / 15% |
| 文件格式 | 抽样读取，检查扩展名 | npy / nii.gz / png / csv / ... |
| 维度 | 读取 shape | 如 (1, 256, 256) 或 (512, 512, 3) |
| 数据类型 | 检查 dtype | float32 / uint8 / int16 |
| 磁盘占用 | `du -sh` 统计 | 如 12.3 GB |

### B. 类别分布分析

| 检查项 | 方法 | 输出 |
|--------|------|------|
| 各类别样本数 | 统计每类样本数量 | 表格：类别名 / 数量 / 占比 |
| 类别不平衡比 | max_class / min_class | 如 15.3:1 |
| 每 split 分布 | 各 split 独立统计 | 3 张表格或对比表 |
| 语义分割任务 | 统计每类像素占比 | 表格：类别名 / 平均像素占比 |

**调参建议规则**：
- 不平衡比 > 10 → 建议 Focal Loss / 加权交叉熵 / 过采样
- 不平衡比 5-10 → 建议 class_weight / 数据增强少数类
- 不平衡比 < 5 → 标准 CE 即可
- 语义分割中某类像素占比 < 1% → 建议 Dice Loss 或 CE+Dice 组合

### C. 数据质量检查

| 检查项 | 方法 | 输出 |
|--------|------|------|
| 缺失值 | 检查 NaN/None/空字符串 | 按特征统计缺失比例 |
| 损坏文件 | 尝试读取所有文件，捕获异常 | 损坏文件列表 + 数量 |
| 重复样本 | 计算文件 hash（MD5/SHA256） | 重复组列表 + 数量 |
| 全零/全常数 | 检查是否所有像素/特征值相同 | 样本列表 |
| 异常值 | 数值超出合理范围（如像素 > 255） | 样本列表 + 异常描述 |
| shape 不一致 | 抽样检查所有文件 shape | 不一致文件列表 |

**抽样策略**：
- 损坏文件：全量检查（逐个读取，捕获异常）
- 重复检测：全量 hash 计算
- 异常值：抽样 10% 文件

### D. 特征分布分析

**数值型数据**（表格/向量）：

| 统计量 | 方法 |
|--------|------|
| 均值、标准差 | 逐特征计算 |
| 最小值、最大值 | 逐特征计算 |
| 分位数 | 25%、50%、75% |
| 偏度、峰度 | 分布形态 |

**图像数据**：

| 统计量 | 方法 |
|--------|------|
| 像素值范围 | 全局 min/max |
| 均值、标准差 | 逐通道计算（如 ImageNet: mean=[0.485,0.456,0.406]） |
| 亮度分布 | 灰度直方图 |
| 对比度 | 像素值标准差 |
| 分辨率分布 | 统计所有图片的 H×W |

**调参建议规则**：
- 像素值 0-255 → 需要归一化到 0-1 或标准化
- 各通道均值/标准差差异大 → 建议使用 dataset-specific 归一化而非 ImageNet 默认值
- 分辨率不一致 → 需要 resize 或 padding 策略

### E. 标注质量

| 检查项 | 方法 | 输出 |
|--------|------|------|
| 标注格式一致性 | 抽样检查标注文件结构 | 格式是否统一 |
| 标注-数据对应 | 验证每个标注文件有对应数据文件 | 缺失/多余列表 |
| 空标注 | 检查标注为空或全背景 | 数量 + 占比 |
| 极小目标 | 统计目标面积 < 阈值（如 10 像素） | 数量 + 占比 |
| 边缘截断 | 检查目标是否被图像边界截断 | 数量 |
| 标注值范围 | 检查标签值是否在合理范围 | 异常值列表 |

### F. 数据可分性初探

仅在样本量 ≥ 100 且为分类任务时执行：

| 检查项 | 方法 | 输出 |
|--------|------|------|
| 类间距离 | 抽样计算类中心欧氏距离 | 距离矩阵 |
| KNN 快速评估 | 5-fold KNN（K=5） | 准确率 |
| PCA 可视化 | 降维到 2D，按类别着色 | 散点图 |

---

### G. 医学 3D/4D 影像 Profile

针对 **3D/4D 医学影像（如 4D 心脏 CT、MR 运动重建、去伪影）** 的专项分析，在基础分析之外增加：

| 检查项 | 方法 | 输出 | 调参影响 |
|--------|------|------|----------|
| 患者级划分 | 检查 train/val/test 是否按患者 ID 划分，不同 phase 不跨 split | 泄漏样本数 | 防止同一患者不同 phase 泄漏，需按患者分组 |
| 体数据维度 | 读取 shape，确认 T×D×H×W 或 D×H×W | 维度统计、异常 shape 列表 | 决定 2D/2.5D/3D 网络、patch 大小 |
| Spacing / 方向矩阵 | 读取头信息（如 NIfTI/SimpleITK） | spacing 分布、方向一致性 | 是否需要重采样、各向异性处理 |
| HU / 强度范围 | 统计 HU 或强度 min/max/percentile | 窗宽窗位建议 | 归一化方式、clip 范围 |
| 心动 phase 分布 | 统计每个患者 phase 数量与缺失 | phase 数量分布 | 时间一致性 loss、序列模型 |
| 配准/运动场质量 | 检查 motion field 是否异常、是否有 identity 偏移 | 异常 field 数量 | 运动估计网络设计 |
| 伪影强度分层 | 按伪影严重程度分层统计 | 轻/中/重分布 | 采样策略、加权 loss |
| 配对数据对应 | 确认输入与目标严格对应（同一患者、同一 phase） | 不匹配列表 | 数据 loader 必须保证配对 |
| 时间一致性 | 计算相邻 phase 的像素/结构相似性 | 帧间差异分布 | 增加 temporal consistency loss |
| Patch overlap 与边界伪影 | 检查 inference 时 patch 拼接是否有边界效应 | 边界强度统计 | overlap、blend 策略 |
| 推理资源 | 估算整卷推理显存与时间 | GB / s | 是否需要 patch-based inference、模型轻量化 |

**推荐指标**（重建/去伪影任务）：
- 像素级：MAE、MSE、PSNR
- 结构级：SSIM、MS-SSIM
- 时间级：相邻 phase PSNR/SSIM、光流一致性
- 单患者多 phase 聚合：患者级均值/最差 phase 指标

**调参建议规则**：
- 患者级泄漏 > 0 → 必须重新划分数据，否则指标不可信。
- spacing 各向异性 > 2:1 → 优先重采样到各向同性或设计各向异性卷积。
- phase 数量不一致 → 使用可处理变长序列的模型，或插值到固定 phase。
- 伪影分布极不平衡 → 分层采样 + 加权 loss。
- 整卷推理显存不足 → 必须 patch-based inference + overlap，训练时也使用相同 patch 策略。

---

## 可视化

**前提**：检查 `python -c "import matplotlib"` 是否成功。失败则跳过可视化，用纯文字/表格替代。

**生成图片**（保存到 `{exp_dir}/dataset_analysis/`）：

| 图片 | 文件名 | 适用场景 |
|------|--------|----------|
| 类别分布柱状图 | `class_distribution.png` | 所有分类任务 |
| 特征分布直方图 | `feature_distributions.png` | 表格数据（抽样 top-8 特征） |
| 像素值分布 | `pixel_distribution.png` | 图像数据 |
| PCA 2D 散点图 | `pca_scatter.png` | 分类任务（抽样 1000 个样本） |

**绘图代码模板**（子 agent 使用）：

```python
import matplotlib.pyplot as plt
import numpy as np
import os

# 类别分布柱状图
def plot_class_dist(class_names, counts, save_path):
    plt.figure(figsize=(10, 6))
    plt.bar(class_names, counts)
    plt.xlabel('类别')
    plt.ylabel('样本数')
    plt.title('类别分布')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()

# PCA 散点图
def plot_pca(features_2d, labels, save_path):
    plt.figure(figsize=(10, 8))
    scatter = plt.scatter(features_2d[:, 0], features_2d[:, 1], c=labels, cmap='tab10', alpha=0.6, s=10)
    plt.colorbar(scatter)
    plt.xlabel('PC1')
    plt.ylabel('PC2')
    plt.title('PCA 可视化')
    plt.tight_layout()
    plt.savefig(save_path, dpi=150)
    plt.close()
```

---

## 报告结构

输出到 `{exp_dir}/dataset_analysis_report.md`，结构如下：

```markdown
# 数据集分析报告

## 概览
- 样本总量：...
- 划分：训练 N / 验证 N / 测试 N
- 格式：...
- 磁盘占用：...

## 类别分布
[表格 + 柱状图引用]

## 数据质量
[表格 + ⚠️ 警告]

## 特征分布
[统计表 + 直方图引用]

## 标注质量
[表格 + ⚠️ 警告]

## 数据可分性
[KNN 准确率 + PCA 散点图引用]

## 医学 3D/4D 影像分析（如适用）
[患者级划分 / spacing / phase / 伪影 / 时间一致性 / 推理资源]

## 调参建议
1. [建议1]
2. [建议2]
...

## ⚠️ 异常汇总
- [异常1]
- [异常2]
```

---

## 调参建议提取

分析完成后，将调参建议提取到 `experiment/decision_log.md`：

```markdown
## 数据集分析驱动的调参建议

基于数据集分析报告，提取以下调参建议：
1. [建议1] → 来源：[分析维度]
2. [建议2] → 来源：[分析维度]
```

这些建议在 Step 1 的自我辩论和参数扫描中作为输入。
