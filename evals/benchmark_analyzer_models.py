"""Compare analyzer models on the same labelled support queries.

Run with: .\\venv\\Scripts\\python.exe evals\\benchmark_analyzer_models.py
"""

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google import genai
from google.genai import types
from dotenv import load_dotenv

from rag.query_analyzer import QueryAnalysis, SYSTEM_PROMPT

CASES_PATH = ROOT / "evals" / "analyzer_model_cases.jsonl"
REPORTS_DIR = ROOT / "evals" / "reports" / "analyzer_models"
load_dotenv(ROOT / ".env")
FIELDS = (
    "query_type",
    "depends_on_history",
    "product_intent",
    "flow_intent",
    "order_id",
)
MODELS = (
    ("gemini-3-flash-preview", {"thinking_level": "minimal"}),
    ("gemini-3.1-flash-lite", {"thinking_level": "minimal"}),
    ("gemini-2.5-flash-lite", {"thinking_budget": 0, "temperature": 0}),
)


def load_cases():
    return [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def percentile(values, ratio):
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * ratio) - 1]


def run_case(client, case, model, options):
    thinking = types.ThinkingConfig(
        **{
            key: value
            for key, value in options.items()
            if key.startswith("thinking_")
        }
    )
    config_args = {
        "system_instruction": SYSTEM_PROMPT,
        "thinking_config": thinking,
        "max_output_tokens": 512,
        "response_mime_type": "application/json",
        "response_schema": QueryAnalysis,
    }
    if "temperature" in options:
        config_args["temperature"] = options["temperature"]

    contents = (
        f"RECENT CONVERSATION:\n{case.get('history', '')}\n\n"
        f"CURRENT CUSTOMER MESSAGE:\n{case['query']}"
    )
    started_at = time.perf_counter()
    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_args),
        )
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        parsed = response.parsed
        if parsed is None:
            return {"elapsed_ms": round(elapsed_ms, 2), "error": "empty parsed response"}
        actual = parsed.model_dump() if hasattr(parsed, "model_dump") else dict(parsed)
    except Exception as exc:
        return {
            "elapsed_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }

    expected = {
        "query_type": case["expected_route"],
        "depends_on_history": case["expected_history_dependent"],
        "product_intent": case["expected_product_intent"],
        "flow_intent": case["expected_flow_intent"],
        "order_id": case["expected_order_id"],
    }
    mismatches = {
        field: {"expected": expected[field], "actual": actual.get(field)}
        for field in FIELDS
        if actual.get(field) != expected[field]
    }
    return {
        "elapsed_ms": round(elapsed_ms, 2),
        "passed": not mismatches,
        "mismatches": mismatches,
        "actual": actual,
    }


def summarize(model, case_results):
    successful = [result for result in case_results if "error" not in result]
    latencies = [result["elapsed_ms"] for result in successful]
    passed = sum(result.get("passed", False) for result in successful)
    field_correct = {
        field: sum(field not in result.get("mismatches", {}) for result in successful)
        for field in FIELDS
    }
    return {
        "model": model,
        "completed": len(successful),
        "errors": len(case_results) - len(successful),
        "fully_correct": passed,
        "fully_correct_pct": round(passed / len(case_results) * 100, 1),
        "field_correct": field_correct,
        "latency_ms": {
            "mean": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "p50": round(percentile(latencies, 0.50), 2) if latencies else None,
            "p90": round(percentile(latencies, 0.90), 2) if latencies else None,
        },
    }


def main():
    cases = load_cases()
    if not cases:
        raise ValueError(f"No cases found in {CASES_PATH}")
    case_count = len(cases)

    client = genai.Client(api_key=os.environ["GENAI_API_KEY"])
    results_by_model = {model: [] for model, _ in MODELS}
    options_by_model = dict(MODELS)

    # Rotate model order per case so a warmed connection cannot favor one model.
    for case_index, case in enumerate(cases):
        rotated_models = MODELS[case_index % len(MODELS):] + MODELS[:case_index % len(MODELS)]
        print(f"[{case_index + 1:02d}/{case_count}] {case['id']}")
        for model, options in rotated_models:
            result = run_case(client, case, model, options)
            results_by_model[model].append({"id": case["id"], **result})
            status = "ERROR" if "error" in result else ("PASS" if result["passed"] else "FAIL")
            print(f"  {model}: {status} {result['elapsed_ms']:.0f} ms")

    summaries = [summarize(model, results_by_model[model]) for model, _ in MODELS]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report_path = REPORTS_DIR / f"analyzer-models-{timestamp}.json"
    report_path.write_text(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "case_count": len(cases),
                "models": summaries,
                "results": results_by_model,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nSummary")
    for summary in summaries:
        timing = summary["latency_ms"]
        print(
            f"{summary['model']}: {summary['fully_correct']}/{case_count} "
            f"({summary['fully_correct_pct']}%), p50={timing['p50']} ms, "
            f"p90={timing['p90']} ms, mean={timing['mean']} ms, "
            f"errors={summary['errors']}"
        )
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
