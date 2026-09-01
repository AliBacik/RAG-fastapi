import json
from datetime import datetime,timezone
import time

from pathlib import Path

from rag.adaptive_retriever import adaptive_retrieve_overlapped

from rag.retriever import retrieve

from rag.product_context import build_product_context

from rag.generator import generate_answer

from rag.product_context import verify_links

ANSWER_BASELINE_PATH = Path("evals/baseline/answer-baseline.json")

def load_cases():
    
    case_file = Path("evals/answer_cases.jsonl")
    
    file_text = case_file.read_text(encoding="utf-8")
    
    lines = file_text.splitlines()
    
    cases = [
        json.loads(line)
        for line in lines
        if line.strip()
    ]
    
    return cases


def find_missing_terms(answer,required_terms):
    
    answer_lower = answer.lower()
    
    missing_terms=[]
    
    for term in required_terms:
        if term.lower() not in answer_lower:
            missing_terms.append(term)
            
    
    return missing_terms


def find_forbidden_terms(answer,forbidden_terms):
    
    answer_lower = answer.lower()
    
    found_terms =[]
    
    for term in forbidden_terms:
        if term.lower() not in answer_lower:
            found_terms.append(term)
            
    return found_terms


def evaluate_case(case):
    
    started_at = time.perf_counter()
    
    contexts , analysis = adaptive_retrieve_overlapped(
        query = case["query"],
        retrieve_fn = retrieve,
        history = case.get("history",""),
    )
    
    product_data = build_product_context(analysis)
    
    answer=generate_answer(
        query = case["query"],
        contexts = contexts,
        history = case.get("history",""),
        product_data = product_data,
        
    )
    
    final_answer = verify_links(answer,product_data)
    
    elapsed_ms=(time.perf_counter()-started_at)*1000
    
    missing_terms=find_missing_terms(
        final_answer,
        case.get("must_include",[]),
    )
    
    forbidden_terms = find_forbidden_terms(
        final_answer,
        case.get("must_not_include",[])
    )
    
    actual_transfer = "[TRANSFER_TO_AGENT]" in final_answer
    
    expected_transfer = case.get("expects_transfer",False)
    
    transfer_is_correct = actual_transfer ==expected_transfer
    
    passed = (
        len(missing_terms)==0
        and len(forbidden_terms)==0
        and transfer_is_correct
    )
    
    return {
        "passed" : passed,
        "final_answer" : final_answer,
        "missing_terms" : missing_terms,
        "forbidden_terms": forbidden_terms,
        "actual_transfer": actual_transfer,
        "expected_transfer": expected_transfer,
        "route": analysis.query_type,
        "elapsed_ms": elapsed_ms,
    }


def save_report(case_reports):
    
    reports_dir = Path("evals/reports/answer")
    
    reports_dir.mkdir(parents=True,exist_ok=True)
    
    now = datetime.now(timezone.utc)
    
    passed_count = sum(report["passed"] for report in case_reports)
    
    latencies = [report["elapsed_ms"] for report in case_reports]
    
    report = {
        "created_at" : now.isoformat(),
        
        "total_cases" : len(case_reports),
        
        "passed_cases" : passed_count,
        
        "average_answer_eval_ms" : round(sum(latencies)/len(latencies),2),
        
        "cases" : case_reports,
    }
    
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    
    report_path = reports_dir / f"answer-{timestamp}.json"
    
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),
                           encoding="utf-8",)
    return report_path
    

def find_regressions(case_reports):
    
        baseline_text=ANSWER_BASELINE_PATH.read_text(encoding="utf-8")
        
        baseline_report = json.loads(baseline_text)
        
        baseline_by_id = {
            case["id"] : case
            for case in baseline_report["cases"]
        }
        
        regressions=[]
        
        for current_case in case_reports:
            baseline_case = baseline_by_id.get(current_case["id"])
            
            if baseline_case is None:
                continue
            
            if baseline_case["passed"] and not current_case["passed"]:
                
                regressions.append(current_case["id"])
                
        return regressions
    
    
    

cases = load_cases()

passed_count=0

case_reports=[]

for case in cases:
    
    evaluation = evaluate_case(case)
    
    print(f"\n--{case['id']}---")
    
    print(f"Route: {evaluation['route']}")
    
    print(f"Latency: {evaluation['elapsed_ms']:.0f} ms")
    
    if evaluation["passed"]:
        passed_count += 1
        print("PASS")
    
    else:
        print("FAIL")
        print("Missing terms:", evaluation["missing_terms"])
        print("Forbidden terms:", evaluation["forbidden_terms"])
        print(
            "Transfer expected/actual:",
            evaluation["expected_transfer"],
            evaluation["actual_transfer"],
        )

    # Gerçek müşterinin göreceği son cevabı inceleyebilmek için ekrana yazıyoruz.
    print("\nFinal answer:")
    print(evaluation["final_answer"])
    
    case_report = {
        "id" : case["id"],
        "passed":evaluation["passed"],
        "route":evaluation["route"],
        "elapsed_ms":round(evaluation["elapsed_ms"],2),
        "missing_terms": evaluation["missing_terms"],
        "forbidden_terms": evaluation["forbidden_terms"],
        "expected_transfer": evaluation["expected_transfer"],
        "actual_transfer": evaluation["actual_transfer"],
    }
    
    case_reports.append(case_report)


# Tüm vakalar bittiğinde genel başarı sonucunu gösteriyoruz.
print(f"\nSummary: {passed_count}/{len(cases)} passed")

report_path = save_report(case_reports)

print(f"Report saved: {report_path}")

regressions = find_regressions(case_reports)

if regressions:
    print("REGRESSION DETECTED:", regressions)
    
    raise SystemExit(1)

print("No regressions against answer baseline.")