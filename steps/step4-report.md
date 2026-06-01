---
step: 4
title: 达标报告
---

# Step 4：达标报告

**目的**：生成最终报告，记录全部调参历程。
**前置**：达标或触发放弃条件。
**输出**：`experiment/report.md`。

---

## 操作清单

- [ ] 4.1 收集所有轮次结果
- [ ] 4.2 读取 `references/report-template.md` 按模板生成报告
- [ ] 4.3 包含架构变更历史（如有）
- [ ] 4.4 包含失败方案汇总（如有）
- [ ] 4.5 记录成本（token 消耗和费用）
- [ ] 4.6 写入经验库：提取关键经验到 `~/.claude/skills/auto-tuner/experience/`（见 `references/experience.md`）
- [ ] 4.7 通知用户报告已生成

---

## 报告内容

按 `references/report-template.md` 模板，必须包含：

1. **项目概况**：名称、目标、达标标准、总耗时、总轮数
2. **最佳配置**：参数表
3. **最佳指标**：目标值 vs 实际值，是否达标
4. **调参历程**：每轮关键发现
5. **参数敏感性分析**：各参数影响程度、最佳范围
6. **建议**：基于调参经验的建议

如有架构变更，额外包含：
7. **架构变更历史**：每次变更的原因、内容、前后对比
8. **失败方案汇总**：改了什么、为什么不行

---

## 成本记录

在报告末尾记录：
- 总调参轮数
- 每轮平均实验数
- 预估 token 消耗（基于轮数 × 每轮平均 token，参考 `references/cost-tracking.md`）
- 预估费用（基于模型定价）
- 总耗时（从开始到结束的墙钟时间）

---

## 可视化 HTML 报告

在生成 `experiment/report.md` 的同时，生成 `experiment/report.html` 可视化报告。

**依赖检查**：先检查用户环境是否有 matplotlib 或 plotly：
```bash
python -c "import matplotlib" 2>/dev/null && echo "matplotlib OK" || echo "no matplotlib"
python -c "import plotly" 2>/dev/null && echo "plotly OK" || echo "no plotly"
```

**有 matplotlib/plotly** → 生成完整可视化报告：
- 参数重要性柱状图
- 每轮最佳指标趋势图
- 参数-指标散点矩阵
- 对比表（HTML 表格）

**无依赖** → 生成纯 HTML 表格报告：
- 最佳配置表
- 每轮指标对比表
- 参数敏感性表
- 内联 CSS 样式，无需外部依赖

HTML 报告的数据来源与 report.md 完全相同（results.json + decision_log.md）。

---

## 通知

报告生成后，通过 Claude Code 通知机制告知用户：
- 报告路径：`experiment/report.md` + `experiment/report.html`
- 关键指标摘要：最佳指标 vs 目标值
- 是否达标
