#!/usr/bin/env python3
"""
Auto-Tuner Evals: 状态机决策逻辑 + 文件契约验证。

模拟 agent 的决策逻辑（非真实训练），用固定 mock 数据驱动状态机，
验证 state.json / results.json / routing 是否符合 skill 规范。

用法:
  python evals/run_evals.py              # 全部跑
  python evals/run_evals.py -v           # 详细输出
  python evals/run_evals.py --case=oom   # 只跑某个 case（子串匹配）
"""

import json
import os
import re
import sys
import traceback
from pathlib import Path

# Windows GBK console compatibility
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore

SKILL_DIR = Path(__file__).resolve().parent.parent
RESULTS_SCHEMA_PATH = SKILL_DIR / "references" / "results.schema.json"
STATE_SCHEMA_PATH = SKILL_DIR / "references" / "state-schema.md"
EVALS_JSON_PATH = SKILL_DIR / "evals" / "evals.json"

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

# ═══════════════════════════════════════════════════════════════════
#  Schema Validator
# ═══════════════════════════════════════════════════════════════════

HAS_JSONSCHEMA = False
try:
    from jsonschema import validate as jsonschema_validate, ValidationError
    HAS_JSONSCHEMA = True
except ImportError:
    pass


def validate_results_schema(data):
    """returns (ok: bool, message: str)"""
    if not HAS_JSONSCHEMA:
        return SKIP, "jsonschema not installed, skipped"
    if not RESULTS_SCHEMA_PATH.exists():
        return SKIP, f"schema not found at {RESULTS_SCHEMA_PATH}, skipped"
    try:
        with open(RESULTS_SCHEMA_PATH) as f:
            schema = json.load(f)
        jsonschema_validate(instance=data, schema=schema)
        return PASS, ""
    except ValidationError as e:
        return FAIL, str(e)[:300]


def validate_state_json(data):
    """Validate state.json has required fields and types."""
    required = ["phase", "round", "architecture_version", "next_action"]
    for field in required:
        if field not in data:
            return FAIL, f"missing required field: {field}"

    valid_phases = ["planning", "tuning", "optimization", "reporting", "completed", "stopped"]
    if data.get("phase") not in valid_phases:
        return FAIL, f"invalid phase: {data.get('phase')}"

    valid_next = [
        "step1_planning", "generate_configs", "run_experiments",
        "analyze_results", "check_termination", "architecture_search",
        "generate_report", "waiting_user", "completed", "stopped"
    ]
    if data.get("next_action") not in valid_next:
        return FAIL, f"invalid next_action: {data.get('next_action')}"

    if not isinstance(data.get("round"), int) or data["round"] < 0:
        return FAIL, f"round must be non-negative int, got {data.get('round')}"
    if not isinstance(data.get("architecture_version"), int) or data["architecture_version"] < 1:
        return FAIL, f"architecture_version must be positive int, got {data.get('architecture_version')}"
    if not isinstance(data.get("consecutive_no_improvement", 0), int):
        return FAIL, f"consecutive_no_improvement must be int"

    if data.get("phase") in ("completed", "stopped") and not data.get("stop_reason"):
        return FAIL, "terminal phase requires stop_reason"

    return PASS, ""


# ═══════════════════════════════════════════════════════════════════
#  Core State Machine Logic (mirrors state-schema.md + step2-tuning)
# ═══════════════════════════════════════════════════════════════════

def is_target_reached(state):
    """Check best_metrics >= _target_values for every key."""
    metrics = state.get("best_metrics") or {}
    target = state.get("_target_values") or {}
    if not target:
        return False
    for key, required in target.items():
        actual = metrics.get(key)
        if actual is None or actual < required:
            return False
    return True


def check_termination(state):
    """
    Step 2.5 termination routing.
    Returns (next_action, stop_reason), does NOT mutate state.
    """
    # 1. Target reached → report
    if is_target_reached(state):
        return "generate_report", "target_reached"

    round_num = state.get("round", 0)
    consecutive = state.get("consecutive_no_improvement", 0)
    distance = None
    target = state.get("_target_values") or {}
    metrics = state.get("best_metrics") or {}
    if target and metrics:
        for key, required in target.items():
            actual = metrics.get(key)
            if actual is not None:
                d = required - actual
                distance = d if distance is None else min(distance, d)

    # 2. Give up conditions
    if round_num >= 3 and state.get("architecture_version", 1) >= 4:
        return "generate_report", "too_many_architectures"
    if round_num >= 50:
        return "generate_report", "too_many_rounds"
    if round_num >= 15 and distance is not None and distance > 0.05:
        if state.get("best_metrics") == state.get("_best_15_rounds_ago"):
            return "generate_report", "stagnated"

    # 3. Architecture backtrack: consecutive 10+ rounds no improvement
    if consecutive >= 10 and distance is not None and distance > 0.03:
        return "architecture_search", None

    # Default: continue
    return "generate_configs", None


def simulate_round(state, round_metrics):
    """
    Advance state by one round of experiments.
    round_metrics: dict with keys:
        - best_metric: float (the primary metric value for this round)
        - metrics: dict of all metrics
        - search_stage: str or None (None = keep existing)
    Returns updated state (mutated in place for simplicity).
    """
    prev_round = state.get("round", 0)
    state["round"] = prev_round + 1
    state["last_action"] = "analyze_results"

    # Update best metrics
    current_best = state.get("best_metrics") or {}
    new_metrics = round_metrics.get("metrics", {})
    # Determine if new round's primary metric is better
    prev_primary = state.get("last_round_best_metric")
    new_primary = round_metrics.get("best_metric")

    # Update best global
    new_is_better = False
    if new_primary is not None:
        if prev_primary is None:
            new_is_better = True
        else:
            # Compare by taking the primary metric name from target
            target = state.get("_target_values") or {}
            for key in target:
                old_val = current_best.get(key)
                new_val = new_metrics.get(key)
                if new_val is not None and (old_val is None or new_val > old_val):
                    new_is_better = True
                    break
            if not new_is_better:
                # Fallback: compare primary
                new_is_better = new_primary > (prev_primary or 0)

    if new_is_better:
        state["best_metrics"] = new_metrics
        state["best_config_id"] = f"config-{state['round']:03d}"

    # Consecutive no improvement detection
    if prev_primary is not None and new_primary is not None:
        if new_primary <= prev_primary + 0.005:
            state["consecutive_no_improvement"] = state.get("consecutive_no_improvement", 0) + 1
        else:
            state["consecutive_no_improvement"] = 0
    else:
        state["consecutive_no_improvement"] = 0

    if new_primary is not None:
        state["last_round_best_metric"] = new_primary

    # Search stage transition
    new_stage = round_metrics.get("search_stage")
    if new_stage:
        state["search_stage"] = new_stage

    # Termination check
    next_action, stop_reason = check_termination(state)
    state["next_action"] = next_action
    if stop_reason:
        state["stop_reason"] = stop_reason
    if next_action == "generate_report":
        state["phase"] = "reporting"
    elif next_action == "architecture_search":
        state["phase"] = "optimization"
        state["architecture_version"] = state.get("architecture_version", 1) + 1
        state["search_stage"] = None

    return state


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
#  Test Cases
# ═══════════════════════════════════════════════════════════════════

def case_classification_success():
    """正常调参: planning → coarse → fine → target_reached → completed"""
    c = CheckResult("classification-success")

    state = {
        "phase": "tuning", "round": 0, "architecture_version": 1,
        "search_stage": "coarse", "best_config_id": None,
        "best_metrics": {}, "target_expr": "accuracy >= 0.90",
        "_target_values": {"accuracy": 0.90},
        "last_action": None, "next_action": "generate_configs",
        "stop_reason": None, "retry_count": 0,
        "consecutive_no_improvement": 0, "last_round_best_metric": None,
    }

    # Simulate 5 rounds: 0.78 → 0.83 → 0.87 → 0.89 → 0.91 (target reached)
    rounds = [
        {"best_metric": 0.78, "metrics": {"accuracy": 0.78}},
        {"best_metric": 0.83, "metrics": {"accuracy": 0.83}},
        {"best_metric": 0.87, "metrics": {"accuracy": 0.87}, "search_stage": "fine"},
        {"best_metric": 0.89, "metrics": {"accuracy": 0.89}},
        {"best_metric": 0.91, "metrics": {"accuracy": 0.91}},
    ]
    for i, rd in enumerate(rounds):
        simulate_round(state, rd)
        if state["next_action"] in ("generate_report", "completed", "stopped"):
            # mark remaining rounds as not run
            for j in range(i + 1, len(rounds)):
                pass  # not executed
            break

    # Simulate report generation
    if state["phase"] == "reporting":
        state["phase"] = "completed"
        state["next_action"] = "completed"

    # ── checks ──
    c.check("phase=completed", state["phase"] == "completed")
    c.check("next_action=completed", state["next_action"] == "completed")
    c.check("stop_reason=target_reached", state.get("stop_reason") == "target_reached")
    c.check("round=5", state["round"] == 5)
    c.check("architecture_version=1 (无回溯)", state["architecture_version"] == 1)
    c.check("best_metrics.accuracy >= 0.90", state.get("best_metrics", {}).get("accuracy", 0) >= 0.90)
    c.check("search_stage=fine", state.get("search_stage") == "fine")
    c.check("consecutive_no_improvement < 10 (无死循环)", state.get("consecutive_no_improvement", 0) < 10)

    # Validate state.json schema
    s_ok, s_msg = validate_state_json(state)
    c.check("state.json 字段合法", s_ok, s_msg)

    return c


def case_segmentation_architecture_fallback():
    """架构回溯: 连续 10 轮无提升 → architecture_version+1 → round 归零"""
    c = CheckResult("segmentation-architecture-fallback")

    state = {
        "phase": "tuning", "round": 10, "architecture_version": 1,
        "search_stage": "fine", "best_config_id": "config-015",
        "best_metrics": {"dice": 0.83},
        "target_expr": "dice >= 0.90", "_target_values": {"dice": 0.90},
        "last_action": "analyze_results", "next_action": "check_termination",
        "stop_reason": None, "retry_count": 0,
        "consecutive_no_improvement": 10, "last_round_best_metric": 0.83,
    }

    # Termination check should trigger architecture_search
    next_action, stop_reason = check_termination(state)

    c.check("路由判定=architecture_search", next_action == "architecture_search")
    c.check("stop_reason=None (非终止)", stop_reason is None)

    # Simulate Step 3 transition
    if next_action == "architecture_search":
        state["phase"] = "optimization"
        state["architecture_version"] += 1
        state["search_stage"] = None
        state["next_action"] = "architecture_search"

    c.check("phase → optimization", state["phase"] == "optimization")
    c.check("architecture_version → 2", state["architecture_version"] == 2)

    # Simulate Step 3 done → back to Step 2
    state["phase"] = "tuning"
    state["round"] = 0
    state["search_stage"] = "coarse"
    state["consecutive_no_improvement"] = 0
    state["next_action"] = "generate_configs"
    state["last_round_best_metric"] = None

    c.check("回到 Step2 后 phase=tuning", state["phase"] == "tuning")
    c.check("round 归零", state["round"] == 0)
    c.check("search_stage=coarse", state["search_stage"] == "coarse")
    c.check("consecutive_no_improvement 归零", state["consecutive_no_improvement"] == 0)
    c.check("next_action=generate_configs", state["next_action"] == "generate_configs")
    c.check("architecture_version=2 (已递增)", state["architecture_version"] == 2)

    # Should NOT give up
    c.check("stop_reason 仍为 None", state.get("stop_reason") is None)

    s_ok, s_msg = validate_state_json(state)
    c.check("state.json 字段合法", s_ok, s_msg)

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
    c.check("results.json schema 校验", schema_ok, schema_msg)

    # Field-level checks
    for entry in results:
        for cfg in entry["configs"]:
            cid = cfg["config_id"]
            c.check(f"{cid} completed + error_type=null",
                    cfg["status"] != "completed" or cfg["error_type"] is None)
            c.check(f"{cid} train_loss=null (sklearn)",
                    cfg["train_loss"] is None)
            c.check(f"{cid} val_loss=null (sklearn)",
                    cfg["val_loss"] is None)
            c.check(f"{cid} gpu_memory_gb=null (no GPU)",
                    cfg["gpu_memory_gb"] is None)
            c.check(f"{cid} params 含 kernel (非 DL 参数)",
                    "kernel" in cfg.get("params", {}))
            c.check(f"{cid} duration_min > 0", cfg["duration_min"] > 0)

    c.check("round_id 从 1 递增",
             all(r["round_id"] == i+1 for i, r in enumerate(results)))
    c.check("best_config_id 指向正确", results[0]["best_config_id"] == "config-002")
    c.check("resource_usage.gpu_utilization=None (no GPU)",
             results[0]["resource_usage"]["gpu_utilization"] is None)

    return c


def case_oom_recovery():
    """OOM → batch_size 减半 → 重试成功, error_type 记录正确"""
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
                },
                {
                    "config_id": "config-001-retry",
                    "params": {"learning_rate": 0.001, "batch_size": 16},
                    "metrics": {"accuracy": 0.82},
                    "train_loss": 0.45, "val_loss": 0.50,
                    "status": "completed", "duration_min": 8,
                    "gpu_memory_gb": 11.8,
                    "seed": 42, "commit_hash": "abc123",
                    "error_type": None,
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
                },
            ],
            "best_config_id": "config-002",
            "resource_usage": {"parallel_count": 2, "gpu_utilization": "89%"},
        }
    ]

    schema_ok, schema_msg = validate_results_schema(results)
    c.check("OOM 场景 results schema 校验", schema_ok, schema_msg)

    cfg_oom = results[0]["configs"][0]
    cfg_retry = results[0]["configs"][1]
    cfg_normal = results[0]["configs"][2]

    c.check("OOM config: error_type=OOM", cfg_oom["error_type"] == "OOM")
    c.check("OOM config: status=oom", cfg_oom["status"] == "oom")
    c.check("OOM config: batch_size=32 (原始值)", cfg_oom["params"]["batch_size"] == 32)
    c.check("OOM config: duration_min 记录实际运行时长", cfg_oom["duration_min"] > 0)
    c.check("OOM config: gpu_memory_gb 接近显存上限", cfg_oom["gpu_memory_gb"] > 20)

    c.check("重试 config: batch_size=16 (减半)", cfg_retry["params"]["batch_size"] == 16)
    c.check("重试 config: completed + error_type=null",
             cfg_retry["status"] == "completed" and cfg_retry["error_type"] is None)
    c.check("重试 config: seed 与原始一致 (可复现)", cfg_retry["seed"] == cfg_oom["seed"])
    c.check("重试 config: gpu_memory 下降 (23.5→11.8)",
             cfg_retry["gpu_memory_gb"] < cfg_oom["gpu_memory_gb"])

    c.check("正常 config: completed + error_type=null",
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
        "_target_values": {"dice_lv": 0.90, "dice_rv": 0.90},
        "last_action": "analyze_results", "next_action": "check_termination",
        "stop_reason": None, "retry_count": 0,
        "consecutive_no_improvement": 0, "last_round_best_metric": 0.915,
    }

    next_action, stop_reason = check_termination(state)

    c.check("next_action=generate_report (达标)", next_action == "generate_report")
    c.check("stop_reason=target_reached", stop_reason == "target_reached")

    # Simulate report generation
    state["phase"] = "completed"
    state["next_action"] = "completed"
    state["stop_reason"] = "target_reached"

    c.check("phase=completed", state["phase"] == "completed")
    c.check("round=1 (未额外递增)", state["round"] == 1)
    c.check("architecture_version=1", state["architecture_version"] == 1)
    c.check("未触发 architecture backtrack (轮次少)",
             state.get("consecutive_no_improvement", 0) < 10)
    c.check("best_metrics.dice_lv >= 0.90",
             state.get("best_metrics", {}).get("dice_lv", 0) >= 0.90)

    s_ok, s_msg = validate_state_json(state)
    c.check("state.json 字段合法", s_ok, s_msg)

    return c


def case_no_auto_relax_target():
    """禁止自动放宽目标: 3 次熔断后 target_expr 不变"""
    c = CheckResult("no-auto-relax-target")

    state = {
        "phase": "tuning", "round": 15, "architecture_version": 1,
        "search_stage": "fine", "best_config_id": "config-020",
        "best_metrics": {"dice": 0.83},
        "target_expr": "dice >= 0.90", "_target_values": {"dice": 0.90},
        "last_action": "analyze_results", "next_action": "check_termination",
        "stop_reason": None, "retry_count": 0,
        "consecutive_no_improvement": 3, "last_round_best_metric": 0.83,
    }

    original_target = state["target_expr"]
    original_values = dict(state["_target_values"])

    # Simulate 3 meltdowns — target_expr must NOT change
    for meltdown_num in range(1, 4):
        state["retry_count"] = meltdown_num
        c.check(f"第 {meltdown_num} 次熔断后 target_expr 不变",
                 state["target_expr"] == original_target)
        c.check(f"第 {meltdown_num} 次熔断后 target_values 不变",
                 state["_target_values"] == original_values)

    # After 3rd meltdown, should stop, but target still unchanged
    c.check("3 次熔断后 target_expr 仍不变", state["target_expr"] == original_target)
    c.check("3 次熔断后 target_values 不变",
             state["_target_values"] == original_values)

    return c


# ═══════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════

def main():
    all_cases = [
        ("Classification Normal", case_classification_success),
        ("Architecture Fallback", case_segmentation_architecture_fallback),
        ("Sklearn Lightweight", case_sklearn_lightweight),
        ("OOM Recovery", case_oom_recovery),
        ("Early Target Reached", case_early_target_reached),
        ("No Auto-Relax Target", case_no_auto_relax_target),
    ]

    filter_pattern = None
    verbose = False

    for arg in sys.argv[1:]:
        if arg == "-v":
            verbose = True
        elif arg.startswith("--case="):
            filter_pattern = arg.split("=", 1)[1].lower()
        elif arg.startswith("--filter="):
            filter_pattern = arg.split("=", 1)[1].lower()

    total_passed = 0
    total_failed = 0
    all_results = {}

    print(f"\n  Auto-Tuner Evals  |  {RESULTS_SCHEMA_PATH.name}")
    print(f"  {'jsonschema: OK' if HAS_JSONSCHEMA else 'jsonschema: NOT INSTALLED (pip install jsonschema)'}")
    print()

    for name, runner in all_cases:
        case_id = name.lower().replace(" ", "-")
        if filter_pattern and filter_pattern not in case_id:
            continue

        try:
            r = runner()
        except Exception as e:
            print(f"  [{FAIL}] {name}: exception — {e}")
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
                symbol_v = {"PASS": "[OK]", "FAIL": "[XX]", "SKIP": "[--]"}.get(status, "?")
                detail_str = f"  {detail}" if detail else ""
                print(f"      {symbol_v} {desc}{detail_str}")

    # Summary (total_failed was already counted; skipped not counted against)
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
