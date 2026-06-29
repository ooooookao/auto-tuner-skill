# 状态机：state.json

## 概述

`experiment/state.json` 是 agent 的**机器可读状态文件**，与 `progress.md`（人类可读）互补。

| 文件 | 读者 | 用途 | 更新方式 |
|------|------|------|----------|
| `state.json` | agent（程序化读取） | 决策路由、断点恢复、状态判断 | 覆盖写 |
| `progress.md` | 用户 + agent（人类阅读） | 进度跟踪、历史回顾 | 部分追加、部分覆盖 |

**核心原则**：agent 每次做路由决策前**必须读 state.json**，而不是从对话记忆中推断当前状态。

---

## Schema

```json
{
  "phase": "planning" | "tuning" | "optimization" | "reporting" | "completed" | "stopped",
  "round": 0,
  "architecture_version": 1,
  "search_stage": "coarse" | "fine" | "refine" | null,
  "best_config_id": null | "config-001",
  "best_metrics": {},
  "target_expr": "dice >= 0.90",
  "last_action": null | "step1_planning" | "generate_configs" | "run_experiments" | "analyze_results" | "architecture_search" | "generate_report" | "waiting_user",
  "next_action": "step1_planning" | "generate_configs" | "run_experiments" | "analyze_results" | "check_termination" | "architecture_search" | "generate_report" | "waiting_user",
  "stop_reason": null | "target_reached" | "too_many_rounds" | "user_stopped" | "budget_exhausted",
  "retry_count": 0,
  "consecutive_no_improvement": 0,
  "last_round_best_metric": null,
  "last_updated": "2026-06-29T12:00:00Z"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `phase` | string | ✅ | 当前大阶段。Step 1→`planning`, Step 2→`tuning`, Step 3→`optimization`, Step 4→`reporting`, 完成→`completed`, 放弃→`stopped` |
| `round` | integer | ✅ | 当前轮次数，从 1 开始。Step 1 为 0 |
| `architecture_version` | integer | ✅ | 架构版本号，从 1 开始。架构回溯后 +1 |
| `search_stage` | string\|null | ✅ | 粗搜/细搜/微调。Step 1 和 Step 3 刚完成时为 null |
| `best_config_id` | string\|null | ✅ | 全局最佳配置 ID |
| `best_metrics` | object | ✅ | 全局最佳指标，如 `{"dice": 0.89}` |
| `target_expr` | string | ✅ | 达标条件表达式，如 `"dice >= 0.90 且 loss < 0.10"` |
| `last_action` | string\|null | ✅ | 刚完成的动作 |
| `next_action` | string | ✅ | 下一步动作 — agent 读这个字段就知道该干什么（见下方"状态转换表"） |
| `stop_reason` | string\|null | ✅ | 停止原因，phase 不为 completed/stopped 时必为 null |
| `retry_count` | integer | ✅ | 当前故障重试计数，成功时归零 |
| `consecutive_no_improvement` | integer | ✅ | 连续无提升轮数（用于质量熔断和死循环检测） |
| `last_round_best_metric` | number\|null | ✅ | 上一轮最佳指标的数值，便于快速比较 |
| `last_updated` | string | ✅ | ISO 8601 时间戳 |

---

## 状态转换表

`next_action` 决定 agent 下一步做什么。agent 读取 state.json 后，根据 next_action 跳转到对应的逻辑块。

| 当前 next_action | 描述 | 完成后写入的 next_action |
|------------------|------|------------------------|
| `step1_planning` | Step 1 规划阶段 | `generate_configs` |
| `generate_configs` | 生成新一轮配置 | `run_experiments` |
| `run_experiments` | 并行运行实验 | `analyze_results` |
| `analyze_results` | 趋势分析 + 参数重要性 | `check_termination` |
| `check_termination` | 终止/审查/架构回溯判断 | 见下方"路由分支" |
| `architecture_search` | Step 3 架构回溯 | `generate_configs` |
| `generate_report` | Step 4 生成报告 | `completed` (或 `stopped`) |
| `waiting_user` | 等待用户输入（5 轮摘要/放宽目标等） | 用户回复后按指令设置 |
| `completed` | 正常完成 | —（终点） |
| `stopped` | 放弃停止 | —（终点） |

### check_termination 路由分支

```
check_termination
  ├── 达标 → next_action = "generate_report", 更新 phase/reason
  ├── 放弃 → next_action = "generate_report", phase = "stopped", stop_reason = ...
  ├── 架构回溯 → next_action = "architecture_search", phase = "optimization"
  ├── 审查触发 → 执行审查 → 继续下一轮 / fix → next_action = "generate_configs"
  └── 继续 → next_action = "generate_configs"
```

---

## 读写时机

### 读取（agent 必须先读 state.json 再决策）

| 时机 | 目的 |
|------|------|
| 每轮开始 | 读 next_action 知道该干什么 |
| 上下文压缩后 | 恢复当前状态，避免"我在哪"的混淆 |
| 断点恢复（新 session） | 重建完整状态，继续未完成的工作 |
| 每个 Bash/Agent 子任务启动前 | 确认当前 phase 没有被用户中断改变 |
| 用户中断后恢复 | 读取用户修改后的 state.json |

### 写入（每次状态变化后立即覆盖写）

| 事件 | 更新字段 |
|------|----------|
| Step 1 完成 | phase, next_action, target_expr, best_metrics |
| 生成配置 | round, search_stage, last_action, next_action |
| 实验完成 | best_config_id, best_metrics, last_round_best_metric, next_action |
| 趋势分析完成 | consecutive_no_improvement, last_action, next_action |
| 终止判断完成 | next_action, stop_reason (如需) |
| 架构回溯 | architecture_version (+1), search_stage, phase, next_action |
| 用户干预 | phase, next_action (根据用户指令) |
| 重试/熔断 | retry_count (归零或递增) |
| 报告生成 | phase, next_action (=completed/stopped), stop_reason |

**所有更新都是覆盖写**，不追加。state.json 始终反映最新状态。

---

## 初始化值

Step 1（1.0 初始化）时创建：

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

---

## 与 progress.md 的分工

| 维度 | state.json | progress.md |
|------|-----------|-------------|
| **读者** | agent（机器） | 用户 + agent（人类） |
| **格式** | JSON，严格类型 | Markdown，自由格式 |
| **更新方式** | 覆盖写 | 追加 + 覆盖顶部 |
| **用途** | 状态路由、断点恢复、程序化判断 | 进度追踪、历史对比、用户阅读 |
| **历史** | 不保留（只有当前状态） | 保留最近 N 轮摘要 |
| **可被用户编辑** | 可以，但 agent 下次读取时校验 | 可以，随意编辑 |
| **必须存在** | ✅ 缺少时 agent 无法确定状态 | ❌ 没有也能跑（但推荐有） |

**断点恢复流程**：
1. 读 state.json → 确定 next_action
2. 读 results.json → 获取完整历史数据
3. 读 progress.md → 获取人类友好摘要
4. 继续执行 next_action
