#!/usr/bin/env python3
"""
Auto-Tuner Evals: 状态机决策逻辑 + 文件契约验证。

模拟 agent 的决策逻辑（非真实训练），用固定 mock 数据驱动状态机，
验证 state.json / results.json / routing 是否符合 skill 规范。

用法:
  python evals/run_evals.py                        # 全部跑
  python evals/run_evals.py -v                     # 详细输出
  python evals/run_evals.py --case=classification  # 只跑单个场景
  python evals/run_evals.py --ci                   # CI 模式（无 jsonschema = FAIL）
"""

import json
import sys
import traceback
from copy import deepcopy
from pathlib import Path

# Windows GBK console compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore

SKILL_DIR = Path(__file__).resolve().parent.parent
RESULTS_SCHEMA_PATH = SKILL_DIR / "references" / "results.schema.json"
STATE_SCHEMA_PATH = SKILL_DIR / "references" / "state.schema.json"

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

# ═══════════════════════════════════════════════════════════════════
#  Schema Validator
# ═══════════════════════════════════════════════════════════════════

HAS_JSONSCHEMA = False
FormatChecker = None
try:
    from jsonschema import validate as jsonschema_validate, ValidationError
    from jsonschema import FormatChecker as _FormatChecker
    FormatChecker = _FormatChecker
    HAS_JSONSCHEMA = True
except ImportError:
    pass

CI_MODE = False  # set by --ci flag


def validate_results_schema(data):
    """returns (status: str, message: str)"""
    if not HAS_JSONSCHEMA:
        if CI_MODE:
            return FAIL, "jsonschema not installed (CI mode: FAIL)"
        return SKIP, "jsonschema not installed, skipped"
    if not RESULTS_SCHEMA_PATH.exists():
        return FAIL, f"schema not found at {RESULTS_SCHEMA_PATH}"
    try:
        with open(RESULTS_SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        kwargs = {"format_checker": FormatChecker()} if FormatChecker else {}
        jsonschema_validate(instance=data, schema=schema, **kwargs)
        return PASS, ""
    except ValidationError as e:
        return FAIL, str(e)[:400]
    except Exception as e:
        return FAIL, f"unexpected error: {e}"


def validate_state_schema(data):
    """returns (status: str, message: str)"""
    if not HAS_JSONSCHEMA:
        if CI_MODE:
            return FAIL, "jsonschema not installed (CI mode: FAIL)"
        return SKIP, "jsonschema not installed, skipped"
    if not STATE_SCHEMA_PATH.exists():
        return FAIL, f"state.schema.json not found at {STATE_SCHEMA_PATH}"
    try:
        with open(STATE_SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        kwargs = {"format_checker": FormatChecker()} if FormatChecker else {}
        jsonschema_validate(instance=data, schema=schema, **kwargs)
        return PASS, ""
    except ValidationError as e:
        return FAIL, str(e)[:400]


# ═══════════════════════════════════════════════════════════════════
#  Core State Machine Logic — all PURE functions (no mutation)
# ═══════════════════════════════════════════════════════════════════

TARGET_OPERATORS = {
    ">=": lambda actual, target: actual >= target,
    "<=": lambda actual, target: actual <= target,
}


def is_target_reached(state):
    """
    Check all target_conditions are met.
    target_conditions format:
      [{"metric": "dice", "operator": ">=", "value": 0.90},
       {"metric": "loss", "operator": "<=", "value": 0.10}]
    """
    conditions = state.get("target_conditions") or []
    if not conditions:
        return False
    metrics = state.get("best_metrics") or {}
    for cond in conditions:
        actual = metrics.get(cond["metric"])
        if actual is None:
            return False
        op_fn = TARGET_OPERATORS.get(cond["operator"])
        if not op_fn or not op_fn(actual, cond["value"]):
            return False
    return True


def compute_worst_distance(state):
    """
    Compute the maximum *normalized* distance to target.
    Used for architecture backtrack: if the worst unment condition
    is still close, backtrack is unnecessary.
    Returns float >= 0 (0 = all targets met).
    """
    conditions = state.get("target_conditions") or []
    metrics = state.get("best_metrics") or {}
    distances = []
    for cond in conditions:
        actual = metrics.get(cond["metric"])
        if actual is None:
            distances.append(1.0)  # no data = maximum distance
            continue
        if cond["operator"] == ">=":
            deficit = max(0.0, cond["value"] - actual) / max(cond["value"], 1e-8)
        elif cond["operator"] == "<=":
            deficit = max(0.0, actual - cond["value"]) / max(cond["value"], 1e-8)
        else:
            continue
        distances.append(deficit)
    return max(distances) if distances else 0.0


def is_metric_better(new_val, old_val, operator=">="):
    """
    Compare two metric values respecting the target operator direction.
    For ">=" (higher is better): returns True if new > old.
    For "<=" (lower is better): returns True if new < old.
    Always returns False when values are equal (no regression is not improvement).
    """
    if operator == ">=":
        return new_val > old_val
    elif operator == "<=":
        return new_val < old_val
    return new_val > old_val  # fallback


def check_termination(state):
    """
    Step 2.5 termination routing.
    Pure function: returns (next_action, stop_reason), does NOT mutate state.
    """
    # 1. Target reached → report
    if is_target_reached(state):
        return "generate_report", "target_reached"

    round_num = state.get("round", 0)
    consecutive = state.get("consecutive_no_improvement", 0)
    distance = compute_worst_distance(state)

    # 2. Give up conditions
    if round_num >= 3 and state.get("architecture_version", 1) >= 4:
        return "generate_report", "too_many_architectures"
    if round_num >= 50:
        return "generate_report", "too_many_rounds"
    if consecutive >= 15 and distance > 0.05:
        return "generate_report", "stagnated"

    # 3. Architecture backtrack: consecutive 10+ rounds no improvement
    if consecutive >= 10 and distance > 0.03:
        return "architecture_search", None

    # Default: continue
    return "generate_configs", None


def simulate_round(state, round_metrics):
    """
    Pure function: returns NEW state after one round of experiments.
    Does NOT mutate input state.

    round_metrics: dict with keys:
        - best_metric: float (primary metric value for this round)
        - metrics: dict of all metrics
        - search_stage: str or None (None = keep existing)
    """
    new_state = deepcopy(state)
    prev_round = new_state.get("round", 0)
    new_state["round"] = prev_round + 1
    new_state["last_action"] = "analyze_results"

    new_metrics = round_metrics.get("metrics", {})
    prev_primary = new_state.get("last_round_best_metric")
    new_primary = round_metrics.get("best_metric")

    # Determine if this round improves the global best
    new_is_better = False
    if new_primary is not None:
        if prev_primary is None:
            new_is_better = True
        else:
            conditions = new_state.get("target_conditions") or []
            current_best = new_state.get("best_metrics") or {}
            for cond in conditions:
                old_val = current_best.get(cond["metric"])
                new_val = new_metrics.get(cond["metric"])
                if new_val is not None and (old_val is None or is_metric_better(new_val, old_val, cond["operator"])):
                    new_is_better = True
                    break
            if not new_is_better:
                # Fallback: derive operator from first target condition
                primary_op = conditions[0]["operator"] if conditions else ">="
                new_is_better = is_metric_better(new_primary, prev_primary, primary_op)

    if new_is_better:
        new_state["best_metrics"] = new_metrics
        new_state["best_config_id"] = f"config-{new_state['round']:03d}"

    # Consecutive no improvement detection
    if prev_primary is not None and new_primary is not None:
        if new_primary <= prev_primary + 0.005:
            new_state["consecutive_no_improvement"] = new_state.get("consecutive_no_improvement", 0) + 1
        else:
            new_state["consecutive_no_improvement"] = 0
    else:
        new_state["consecutive_no_improvement"] = 0

    if new_primary is not None:
        new_state["last_round_best_metric"] = new_primary

    # Search stage transition
    new_stage = round_metrics.get("search_stage")
    if new_stage:
        new_state["search_stage"] = new_stage

    # Termination check
    next_action, stop_reason = check_termination(new_state)
    new_state["next_action"] = next_action
    if stop_reason:
        new_state["stop_reason"] = stop_reason
    if next_action == "generate_report":
        new_state["phase"] = "reporting"
    elif next_action == "architecture_search":
        new_state["phase"] = "optimization"
        new_state["architecture_version"] = new_state.get("architecture_version", 1) + 1
        new_state["search_stage"] = None

    return new_state


def trigger_quality_meltdown(state):
    """
    Pure function: first half of quality meltdown protocol.
    Increments retry_count and returns routing decision.
    NEVER modifies target_expr or target_conditions.

    Returns (new_state, requires_user_input: bool).

    retry_count=1 → change strategy, continue
    retry_count=2 → wait for user
    retry_count>=3 → stop
    """
    new_state = deepcopy(state)
    new_state["retry_count"] += 1
    mc = new_state["retry_count"]

    if mc == 1:
        new_state["next_action"] = "generate_configs"
        new_state["last_action"] = "quality_meltdown_1"
        return new_state, False

    if mc == 2:
        new_state["next_action"] = "waiting_user"
        new_state["last_action"] = "quality_meltdown_2_waiting"
        return new_state, True

    # mc >= 3
    new_state["phase"] = "stopped"
    new_state["next_action"] = "generate_report"
    new_state["stop_reason"] = "quality_meltdown"
    new_state["last_action"] = "quality_meltdown_3"
    return new_state, False


def resolve_quality_meltdown(state, response):
    """
    Pure function: handle user response after meltdown count=2.
    Does NOT increment retry_count — only sets routing.
    """
    new_state = deepcopy(state)
    if response in ("reject", "timeout"):
        new_state["next_action"] = "generate_configs"
    elif response == "confirm":
        # User explicitly set new targets in state
        new_state["next_action"] = "generate_configs"
    new_state["last_action"] = "quality_meltdown_2_resolved"
    return new_state, False


# ═══════════════════════════════════════════════════════════════════
#  Test Result Collector
# ═══════════════════════════════════════════════════════════════════

class CheckResult:
    def __init__(self, case_name):
        self.case_name = case_name
        self.checks = []
        self.passed = 0
        self.skipped = 0
        self.failed = 0

    def check(self, description, condition_or_status, detail=""):
        if condition_or_status in (PASS, FAIL, SKIP):
            status = condition_or_status
            ok = status == PASS
            skip = status == SKIP
        else:
            ok = bool(condition_or_status)
            status = PASS if ok else FAIL
            skip = False
        if ok:
            self.passed += 1
        elif skip:
            self.skipped += 1
        else:
            self.failed += 1
        self.checks.append((status, description, detail))
        return ok

    def summary(self):
        total = self.passed + self.failed + self.skipped
        s = f"{self.case_name}: {self.passed}/{total} passed"
        if self.skipped:
            s += f" ({self.skipped} skipped)"
        return s

    def ok(self):
        return self.failed == 0


# ═══════════════════════════════════════════════════════════════════
#  Test Cases  —  case_id 必须与 evals.json 中的 id 一致
# ═══════════════════════════════════════════════════════════════════

def case_classification_success():
    """正常调参: planning → coarse → fine → target_reached → completed"""
    c = CheckResult("classification-success")

    state = {
        "phase": "tuning", "round": 0, "architecture_version": 1,
        "search_stage": "coarse", "best_config_id": None,
        "best_metrics": {}, "target_expr": "accuracy >= 0.90",
        "target_conditions": [{"metric": "accuracy", "operator": ">=", "value": 0.90}],
        "last_action": None, "next_action": "generate_configs",
        "stop_reason": None, "retry_count": 0,
        "consecutive_no_improvement": 0, "last_round_best_metric": None,
        "last_updated": "2026-06-29T00:00:00Z",
    }

    rounds = [
        {"best_metric": 0.78, "metrics": {"accuracy": 0.78}},
        {"best_metric": 0.83, "metrics": {"accuracy": 0.83}},
        {"best_metric": 0.87, "metrics": {"accuracy": 0.87}, "search_stage": "fine"},
        {"best_metric": 0.89, "metrics": {"accuracy": 0.89}},
        {"best_metric": 0.91, "metrics": {"accuracy": 0.91}},
    ]

    s = state
    for rd in rounds:
        s = simulate_round(s, rd)
        if s["next_action"] in ("generate_report", "completed", "stopped"):
            break

    # Simulate report generation
    if s["phase"] == "reporting":
        s["phase"] = "completed"
        s["next_action"] = "completed"

    # ── checks ──
    c.check("phase=completed", s["phase"] == "completed")
    c.check("next_action=completed", s["next_action"] == "completed")
    c.check("stop_reason=target_reached", s.get("stop_reason") == "target_reached")
    c.check("round=5", s["round"] == 5)
    c.check("architecture_version=1 (无回溯)", s["architecture_version"] == 1)
    c.check("best_metrics.accuracy >= 0.90", s.get("best_metrics", {}).get("accuracy", 0) >= 0.90)
    c.check("search_stage=fine", s.get("search_stage") == "fine")
    c.check("consecutive_no_improvement < 10", s.get("consecutive_no_improvement", 0) < 10)

    s_ok, s_msg = validate_state_schema(s)
    c.check("state.schema.json 校验", s_ok, s_msg)

    # Verify pure function: original state was NOT mutated
    c.check("simulate_round 纯函数: 原始 state 未变异",
             state["round"] == 0 and state["phase"] == "tuning")

    return c


def case_segmentation_architecture_fallback():
    """架构回溯: 连续 10 轮无提升 → architecture_version+1 → round 归零"""
    c = CheckResult("segmentation-architecture-fallback")

    state = {
        "phase": "tuning", "round": 10, "architecture_version": 1,
        "search_stage": "fine", "best_config_id": "config-015",
        "best_metrics": {"dice": 0.83},
        "target_expr": "dice >= 0.90",
        "target_conditions": [{"metric": "dice", "operator": ">=", "value": 0.90}],
        "last_action": "analyze_results", "next_action": "check_termination",
        "stop_reason": None, "retry_count": 0,
        "consecutive_no_improvement": 10, "last_round_best_metric": 0.83,
        "last_updated": "2026-06-29T12:00:00Z",
    }

    # check_termination is pure — original state unchanged
    next_action, stop_reason = check_termination(state)

    c.check("路由判定=architecture_search", next_action == "architecture_search")
    c.check("stop_reason=None (非终止)", stop_reason is None)

    # Simulate Step 3 transition (build new state, don't mutate original)
    s = deepcopy(state)
    if next_action == "architecture_search":
        s["phase"] = "optimization"
        s["architecture_version"] += 1
        s["search_stage"] = None
        s["next_action"] = "architecture_search"

    c.check("phase → optimization", s["phase"] == "optimization")
    c.check("architecture_version → 2", s["architecture_version"] == 2)

    # Simulate Step 3 done → back to Step 2
    s2 = deepcopy(s)
    s2["phase"] = "tuning"
    s2["round"] = 0
    s2["search_stage"] = "coarse"
    s2["consecutive_no_improvement"] = 0
    s2["next_action"] = "generate_configs"
    s2["last_round_best_metric"] = None

    c.check("回到 Step2 后 phase=tuning", s2["phase"] == "tuning")
    c.check("round 归零", s2["round"] == 0)
    c.check("search_stage=coarse", s2["search_stage"] == "coarse")
    c.check("consecutive_no_improvement 归零", s2["consecutive_no_improvement"] == 0)
    c.check("next_action=generate_configs", s2["next_action"] == "generate_configs")
    c.check("architecture_version=2 (已递增)", s2["architecture_version"] == 2)
    c.check("stop_reason 仍为 None", s2.get("stop_reason") is None)

    s_ok, s_msg = validate_state_schema(s2)
    c.check("state.schema.json 校验", s_ok, s_msg)

    # Pure function verification
    c.check("check_termination 纯函数: 原始 state 未变异",
             state["round"] == 10 and state["phase"] == "tuning")

    return c


def case_sklearn_lightweight():
    """轻量 sklearn: results 字段合规、无 GPU、无 loss"""
    c = CheckResult("sklearn-lightweight")

    results = [
        {
            "round_id": 1,
            "timestamp": "2026-06-29T10:00:00Z",
            "configs": [
                {
                    "config_id": "config-001",
                    "params": {"C": 1.0, "gamma": 0.1, "kernel": "rbf"},
                    "metrics": {"accuracy": 0.85, "f1": 0.84},
                    "train_loss": None, "val_loss": None,
                    "status": "completed", "duration_min": 2,
                    "gpu_memory_gb": None,
                    "seed": 42, "commit_hash": None, "error_type": None,
                },
                {
                    "config_id": "config-002",
                    "params": {"C": 10.0, "gamma": 0.01, "kernel": "rbf"},
                    "metrics": {"accuracy": 0.88, "f1": 0.87},
                    "train_loss": None, "val_loss": None,
                    "status": "completed", "duration_min": 3,
                    "gpu_memory_gb": None,
                    "seed": 43, "commit_hash": None, "error_type": None,
                },
            ],
            "best_config_id": "config-002",
            "resource_usage": {"parallel_count": 4, "gpu_utilization": None},
        }
    ]

    schema_ok, schema_msg = validate_results_schema(results)
    c.check("results.schema.json 校验", schema_ok, schema_msg)

    for entry in results:
        for cfg in entry["configs"]:
            cid = cfg["config_id"]
            c.check(f"{cid} completed + error_type=null",
                    cfg["status"] != "completed" or cfg["error_type"] is None)
            c.check(f"{cid} train_loss=null (sklearn)", cfg["train_loss"] is None)
            c.check(f"{cid} val_loss=null (sklearn)", cfg["val_loss"] is None)
            c.check(f"{cid} gpu_memory_gb=null (no GPU)", cfg["gpu_memory_gb"] is None)
            c.check(f"{cid} params 含 kernel", "kernel" in cfg.get("params", {}))
            c.check(f"{cid} duration_min > 0", cfg["duration_min"] > 0)

    c.check("round_id 从 1 递增",
             all(r["round_id"] == i+1 for i, r in enumerate(results)))
    c.check("best_config_id 指向正确", results[0]["best_config_id"] == "config-002")
    c.check("resource_usage.gpu_utilization=None (no GPU)",
             results[0]["resource_usage"]["gpu_utilization"] is None)

    return c


def case_oom_recovery():
    """OOM → batch_size 减半 → 重试成功, error_type/attempt/retry_of 记录正确"""
    c = CheckResult("oom-recovery")

    results = [
        {
            "round_id": 1,
            "timestamp": "2026-06-29T11:00:00Z",
            "configs": [
                {
                    "config_id": "config-001",
                    "params": {"learning_rate": 0.001, "batch_size": 32},
                    "metrics": {},
                    "train_loss": None, "val_loss": None,
                    "status": "oom", "duration_min": 5,
                    "gpu_memory_gb": 23.5,
                    "seed": 42, "commit_hash": "abc123",
                    "error_type": "OOM",
                    "attempt": 1, "retry_of": None,
                },
                {
                    "config_id": "config-001",
                    "params": {"learning_rate": 0.001, "batch_size": 16},
                    "metrics": {"accuracy": 0.82},
                    "train_loss": 0.45, "val_loss": 0.50,
                    "status": "completed", "duration_min": 8,
                    "gpu_memory_gb": 11.8,
                    "seed": 42, "commit_hash": "abc123",
                    "error_type": None,
                    "attempt": 2, "retry_of": "config-001",
                },
                {
                    "config_id": "config-002",
                    "params": {"learning_rate": 0.0005, "batch_size": 16},
                    "metrics": {"accuracy": 0.85},
                    "train_loss": 0.38, "val_loss": 0.42,
                    "status": "completed", "duration_min": 8,
                    "gpu_memory_gb": 12.1,
                    "seed": 43, "commit_hash": "abc123",
                    "error_type": None,
                    "attempt": 1, "retry_of": None,
                },
            ],
            "best_config_id": "config-002",
            "resource_usage": {"parallel_count": 2, "gpu_utilization": "89%"},
        }
    ]

    schema_ok, schema_msg = validate_results_schema(results)
    c.check("results.schema.json 校验", schema_ok, schema_msg)

    cfg_oom = results[0]["configs"][0]
    cfg_retry = results[0]["configs"][1]
    cfg_normal = results[0]["configs"][2]

    # OOM config
    c.check("OOM: error_type=OOM", cfg_oom["error_type"] == "OOM")
    c.check("OOM: status=oom", cfg_oom["status"] == "oom")
    c.check("OOM: batch_size=32 (原始值)", cfg_oom["params"]["batch_size"] == 32)
    c.check("OOM: duration_min 记录实际运行时长", cfg_oom["duration_min"] > 0)
    c.check("OOM: gpu_memory_gb 接近显存上限", cfg_oom["gpu_memory_gb"] > 20)
    c.check("OOM: attempt=1", cfg_oom.get("attempt") == 1)
    c.check("OOM: retry_of=None", cfg_oom.get("retry_of") is None)

    # Retry config
    c.check("重试: batch_size=16 (减半)", cfg_retry["params"]["batch_size"] == 16)
    c.check("重试: completed + error_type=null",
             cfg_retry["status"] == "completed" and cfg_retry["error_type"] is None)
    c.check("重试: seed 与原始一致 (可复现)", cfg_retry["seed"] == cfg_oom["seed"])
    c.check("重试: gpu_memory 下降 (23.5→11.8)",
             cfg_retry["gpu_memory_gb"] < cfg_oom["gpu_memory_gb"])
    c.check("重试: metrics 非空 (completed)", len(cfg_retry["metrics"]) >= 1)
    c.check("重试: attempt=2", cfg_retry.get("attempt") == 2)
    c.check("重试: retry_of 指向 config-001", cfg_retry.get("retry_of") == "config-001")

    # Normal config
    c.check("正常: completed + error_type=null",
             cfg_normal["status"] == "completed" and cfg_normal["error_type"] is None)
    c.check("best_config_id 指向正常 config (非 retry)",
             results[0]["best_config_id"] == "config-002")

    return c


def case_early_target_reached():
    """Round 1 达标 → 直接 report, round 不递增"""
    c = CheckResult("early-target-reached")

    state = {
        "phase": "tuning", "round": 1, "architecture_version": 1,
        "search_stage": "coarse", "best_config_id": "config-003",
        "best_metrics": {"dice_lv": 0.92, "dice_rv": 0.91},
        "target_expr": "dice_lv >= 0.90 AND dice_rv >= 0.90",
        "target_conditions": [
            {"metric": "dice_lv", "operator": ">=", "value": 0.90},
            {"metric": "dice_rv", "operator": ">=", "value": 0.90},
        ],
        "last_action": "analyze_results", "next_action": "check_termination",
        "stop_reason": None, "retry_count": 0,
        "consecutive_no_improvement": 0, "last_round_best_metric": 0.915,
        "last_updated": "2026-06-29T12:00:00Z",
    }

    # check_termination is pure
    next_action, stop_reason = check_termination(state)

    c.check("next_action=generate_report (达标)", next_action == "generate_report")
    c.check("stop_reason=target_reached", stop_reason == "target_reached")

    # Simulate report generation (new state)
    s = deepcopy(state)
    s["phase"] = "completed"
    s["next_action"] = "completed"
    s["stop_reason"] = "target_reached"

    c.check("phase=completed", s["phase"] == "completed")
    c.check("round=1 (未额外递增)", s["round"] == 1)
    c.check("architecture_version=1", s["architecture_version"] == 1)
    c.check("未触发 architecture backtrack (轮次少)",
             s.get("consecutive_no_improvement", 0) < 10)
    c.check("best_metrics.dice_lv >= 0.90",
             s.get("best_metrics", {}).get("dice_lv", 0) >= 0.90)

    s_ok, s_msg = validate_state_schema(s)
    c.check("state.schema.json 校验", s_ok, s_msg)

    # Verify check_termination is pure
    c.check("check_termination 纯函数: 原始 state 未变异",
             state["phase"] == "tuning" and state["next_action"] == "check_termination")

    return c


def case_no_auto_relax_target():
    """
    禁止自动放宽目标: trigger_quality_meltdown + resolve_quality_meltdown 不修改 target。
    使用 trigger→trigger→resolve→trigger 路径验证 retry_count 正确递增。
    """
    c = CheckResult("no-auto-relax-target")

    # ── Scenario: 3 consecutive meltdowns ──
    state = {
        "phase": "tuning", "round": 15, "architecture_version": 1,
        "search_stage": "fine", "best_config_id": "config-020",
        "best_metrics": {"dice": 0.83},
        "target_expr": "dice >= 0.90",
        "target_conditions": [{"metric": "dice", "operator": ">=", "value": 0.90}],
        "last_action": "analyze_results", "next_action": "check_termination",
        "stop_reason": None, "retry_count": 0,
        "consecutive_no_improvement": 3, "last_round_best_metric": 0.83,
        "last_updated": "2026-06-29T14:00:00Z",
    }

    original_expr = state["target_expr"]
    original_conditions = deepcopy(state["target_conditions"])

    # ── Phase 1: trigger (retry_count 0→1) — change strategy ──
    s1, needs_input = trigger_quality_meltdown(state)
    c.check("1st trigger: target_expr 不变", s1["target_expr"] == original_expr)
    c.check("1st trigger: target_conditions 不变",
             s1["target_conditions"] == original_conditions)
    c.check("1st trigger: retry_count=1", s1["retry_count"] == 1)
    c.check("1st trigger: next_action=generate_configs",
             s1["next_action"] == "generate_configs")
    c.check("1st trigger: 不需用户输入", not needs_input)

    # ── Phase 2: trigger again (retry_count 1→2) — wait for user ──
    s2, needs_input = trigger_quality_meltdown(s1)
    c.check("2nd trigger: target_expr 不变", s2["target_expr"] == original_expr)
    c.check("2nd trigger: target_conditions 不变",
             s2["target_conditions"] == original_conditions)
    c.check("2nd trigger: retry_count=2", s2["retry_count"] == 2)
    c.check("2nd trigger: next_action=waiting_user", s2["next_action"] == "waiting_user")
    c.check("2nd trigger: 需要用户输入", needs_input)

    # ── Resolve: user rejects — resolve does NOT increment retry_count ──
    s2_resolved, _ = resolve_quality_meltdown(s2, "reject")
    c.check("resolve reject: target_expr 仍不变",
             s2_resolved["target_expr"] == original_expr)
    c.check("resolve reject: next_action=generate_configs",
             s2_resolved["next_action"] == "generate_configs")
    c.check("resolve reject: retry_count 未变 (仍为2)",
             s2_resolved["retry_count"] == 2)

    # Resolve timeout → same as reject
    s2_timeout, _ = resolve_quality_meltdown(s2, "timeout")
    c.check("resolve timeout: target_expr 仍不变",
             s2_timeout["target_expr"] == original_expr)
    c.check("resolve timeout: retry_count 未变 (仍为2)",
             s2_timeout["retry_count"] == 2)

    # ── Phase 3: trigger third time (retry_count 2→3) — stop ──
    s3, needs_input = trigger_quality_meltdown(s2_resolved)
    c.check("3rd trigger: target_expr 仍不变", s3["target_expr"] == original_expr)
    c.check("3rd trigger: target_conditions 不变",
             s3["target_conditions"] == original_conditions)
    c.check("3rd trigger: retry_count=3", s3["retry_count"] == 3)
    c.check("3rd trigger: phase=stopped", s3["phase"] == "stopped")
    c.check("3rd trigger: next_action=generate_report",
             s3["next_action"] == "generate_report")
    c.check("3rd trigger: stop_reason=quality_meltdown",
             s3["stop_reason"] == "quality_meltdown")
    c.check("3rd trigger: 不需用户输入", not needs_input)

    # Final: all meltdowns done, target_conditions still original
    c.check("最终 target_conditions 不变", s3["target_conditions"] == original_conditions)
    c.check("最终 target_expr 不变", s3["target_expr"] == original_expr)

    # Pure function verification: original state unchanged
    c.check("trigger_quality_meltdown 纯函数: 原始 state 未变异",
             state["retry_count"] == 0 and state["phase"] == "tuning")

    return c


def case_stagnation_continuous_improvement():
    """
    回归测试: 15 轮持续提升但不达标 → 不得 stagnated。
    旧逻辑 round_num >= 15 会误判，应改为 consecutive_no_improvement >= 15。
    """
    c = CheckResult("stagnation-continuous-improvement")

    state = {
        "phase": "tuning", "round": 0, "architecture_version": 1,
        "search_stage": "coarse", "best_config_id": None,
        "best_metrics": {}, "target_expr": "accuracy >= 0.90",
        "target_conditions": [{"metric": "accuracy", "operator": ">=", "value": 0.90}],
        "last_action": None, "next_action": "generate_configs",
        "stop_reason": None, "retry_count": 0,
        "consecutive_no_improvement": 0, "last_round_best_metric": None,
        "last_updated": "2026-06-29T00:00:00Z",
    }

    s = state
    for i in range(15):
        # Each round improves by 0.01 (beyond the 0.005 threshold)
        metric = 0.70 + (i * 0.01)
        s = simulate_round(s, {"best_metric": metric, "metrics": {"accuracy": metric}})
        if s["phase"] == "reporting":
            break

    c.check("phase != stopped (15轮连续提升不中断)", s["phase"] != "stopped")
    c.check("stop_reason != stagnated", s.get("stop_reason") != "stagnated")
    c.check("round >= 15", s["round"] >= 15)

    if s["phase"] != "reporting":
        c.check("consecutive_no_improvement == 0 (每轮提升)",
                 s.get("consecutive_no_improvement", -1) == 0)

    # Pure function verification
    c.check("simulate_round 纯函数: 原始 state 未变异",
             state["round"] == 0 and state["phase"] == "tuning")

    return c


# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════

CASE_REGISTRY = [
    # (case_id, display_name, runner)  — case_id matches evals.json
    ("classification-success",          "Classification Normal",      case_classification_success),
    ("segmentation-architecture-fallback", "Architecture Fallback",   case_segmentation_architecture_fallback),
    ("sklearn-lightweight",             "Sklearn Lightweight",        case_sklearn_lightweight),
    ("oom-recovery",                    "OOM Recovery",              case_oom_recovery),
    ("early-target-reached",            "Early Target Reached",      case_early_target_reached),
    ("no-auto-relax-target",            "No Auto-Relax Target",     case_no_auto_relax_target),
    ("stagnation-continuous-improvement", "Stagnation Regression",  case_stagnation_continuous_improvement),
]


def main():
    global CI_MODE

    filter_pattern = None
    verbose = False

    for arg in sys.argv[1:]:
        if arg == "-v":
            verbose = True
        elif arg == "--ci":
            CI_MODE = True
        elif arg.startswith("--case="):
            filter_pattern = arg.split("=", 1)[1].lower()

    total_passed = 0
    total_failed = 0
    all_results = {}

    print()
    print(f"  Auto-Tuner Evals  |  --ci={'ON' if CI_MODE else 'OFF'}")
    print(f"  jsonschema: {'OK' if HAS_JSONSCHEMA else 'NOT INSTALLED (pip install jsonschema)'}")
    print()

    for case_id, display_name, runner in CASE_REGISTRY:
        if filter_pattern and filter_pattern not in case_id and filter_pattern not in display_name.lower():
            continue

        try:
            r = runner()
        except Exception as e:
            print(f"  [{FAIL}] {display_name}: exception — {e}")
            traceback.print_exc()
            total_failed += 1
            continue

        total_passed += r.passed
        total_failed += r.failed
        all_results[case_id] = r

        symbol = "[OK]" if r.ok() else "[XX]"
        print(f"  {symbol} {r.summary()}")

        if not r.ok():
            for status, desc, detail in r.checks:
                if status == FAIL:
                    detail_str = f"  — {detail}" if detail else ""
                    print(f"       {desc}{detail_str}")

        if verbose:
            for status, desc, detail in r.checks:
                sym_map = {"PASS": "[OK]", "FAIL": "[XX]", "SKIP": "[--]"}
                sym_v = sym_map.get(status, "?")
                detail_str = f"  {detail}" if detail else ""
                print(f"      {sym_v} {desc}{detail_str}")

    # Summary
    total = total_passed + total_failed
    total_skipped = sum(r.skipped for r in all_results.values())
    print()
    if total_failed == 0:
        msg = f"  [OK] ALL PASS: {total_passed}/{total}"
        if total_skipped:
            msg += f" ({total_skipped} skipped)"
        print(msg)
        return 0
    else:
        print(f"  [XX] {total_passed}/{total} passed, {total_failed} failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
