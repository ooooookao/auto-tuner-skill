# results.json 格式

每轮调参结束后追加一条记录到 `experiment/results.json`：

```json
[
  {
    "round": 1,
    "timestamp": "2024-01-15T10:30:00",
    "configs": [
      {
        "id": "config-001",
        "params": {"learning_rate": 0.001, "batch_size": 16},
        "metrics": {"dice_lv": 0.85, "dice_rv": 0.82, "dice_overall": 0.87, "loss": 0.15},
        "status": "completed",
        "duration_min": 45,
        "memory_peak_gb": 6.2
      }
    ],
    "best_config": "config-001",
    "resource_usage": {"parallel_count": 5, "gpu_utilization": "72%"}
  }
]
```

字段说明：
- `params`：本轮尝试的所有参数及其值
- `metrics`：对应指标，字段名由 agent 根据项目定义
- `status`：completed / failed / oom
- `duration_min`：该配置运行耗时
- `memory_peak_gb`：峰值内存/显存占用
