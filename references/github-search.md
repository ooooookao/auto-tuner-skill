# 方案搜索策略

本文档定义架构回溯时搜索解决方案的策略。

---

## 搜索时机

仅在架构回溯 Step 3 时触发。调参阶段正常迭代不搜索。

---

## 搜索范围

不限于单一平台，哪里有有用信息就去哪里搜：

| 来源 | 适用场景 | 搜索工具 |
|------|----------|----------|
| GitHub | 找实现代码、开源项目 | `WebSearch`、`WebFetch` |
| 论文（arXiv/Scholar） | 找方法论、SOTA 结果 | `WebSearch` |
| 框架官方文档 | 找 API 用法、最佳实践 | `WebFetch` |
| HF Hub | 找预训练模型、数据集、Spaces | `WebFetch` |
| 技术博客/论坛 | 找实战经验、踩坑记录 | `WebSearch` |
| Stack Overflow | 找具体问题的解决方案 | `WebSearch` |

优先级：GitHub 实现 > 论文方法 > 文档最佳实践 > 博客经验。

---

## 搜索方式

spawn 一个研究子 agent（独立上下文，不污染主 agent context），让子 agent 执行多源搜索并返回结构化结果。

---

## 关键词组合

根据瓶颈类型选择搜索关键词：

| 瓶颈类型 | 搜索关键词模板 |
|----------|---------------|
| 欠拟合/容量不足 | `{task_type} improve model capacity {framework}` |
| 过拟合 | `{task_type} regularization small dataset {framework}` |
| 感受野不够 | `{task_type} multi-scale attention {framework}` |
| 梯度问题 | `{task_type} residual connection gradient flow {framework}` |
| 类别不平衡 | `{task_type} class imbalance loss function {framework}` |
| 收敛慢 | `{task_type} learning rate schedule convergence {framework}` |

其中：
- `task_type`：用户项目的任务类型（如 "medical image segmentation"、"point cloud classification"）
- `framework`：使用的框架（如 "pytorch"、"tensorflow"）

子 agent 应根据搜索结果质量动态调整关键词——如果第一轮搜不到好结果，换同义词或更宽泛的词重试。

---

## 结果筛选标准

| 来源 | 筛选标准 |
|------|----------|
| GitHub | 星标 > 100、最后更新 < 2 年、与当前框架兼容 |
| 论文 | 引用量高、近期发表、有实验结果 |
| 文档 | 官方文档、对应当前版本 |
| 博客/论坛 | 有代码示例、有实际效果验证 |

---

## 结果筛选

子 agent 返回结构化表格：

| 方案 | 来源 | 预期收益 | 风险 | 参考链接 |
|------|------|----------|------|----------|
| 方案1 | 仓库名/论文名 | 解决什么问题 | 可能的副作用 | URL |

筛选标准：
- 方案必须与当前瓶颈直接相关
- 优先选"小改动大效果"的方案
- 最多返回 3 个方案

---

## 子 agent 失败处理

重试和降级规则见 `failure-recovery.md` 的"子 agent 调用失败"段落。降级后结果仍走正常校验流程。

---

## 搜索结果利用

主 agent 收到子 agent 的结构化结果后：
1. 结合自身对项目的理解
2. 自我辩论评估各方案的适用性
3. 选最优解
4. 记录决策过程和参考来源到 `experiment/decision_log.md`
