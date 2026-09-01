import json
import time
from datetime import datetime , timezone
from pathlib import Path

from rag.adaptive_retriever import adaptive_retrieve_overlapped
from rag.retriever import retrieve

BASELINE_PATH = Path("evals/baseline/retrieval-baseline.json")

def load_cases():
    case_file = Path("evals/cases.jsonl")
    
    return [
        json.loads(line)
        for line in case_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    
    
def find_regressions(case_reports):
    baseline_text = BASELINE_PATH.read_text(encoding="utf-8")
    
    baseline_report = json.loads(baseline_text)
    
    baseline_by_id ={
        case["id"] : case
        for case in baseline_report["cases"]
    }
    
    regressions = []
    
    for current_case in case_reports:
        
        baseline_case = baseline_by_id.get(current_case["id"])
        
        if baseline_case is None:
            continue
        
        if baseline_case["passed"] and not current_case["passed"]:
            
            regressions.append(current_case["id"])
            
    return regressions


    

def group_found_in_results(group,results):
    for result in results:
        content = result["content"].lower()
        
        if all(term.lower() in content for term in group):
            return True
    
    return False


def save_report(case_reports):
    
    reports_dir = Path("evals/reports")
    
    reports_dir.mkdir(parents=True , exist_ok=True)
    
    now = datetime.now(timezone.utc)
    
    passed_count= sum(report["passed"] for report in case_reports)
    
    latencies = [report["elapsed_ms"] for report in case_reports]
    
    report = {
        "created_at" : now.isoformat(),
        
        "total_cases" : len(case_reports),
        
        "passed_cases" : passed_count,
        
        "average_adaptive_retrieval_ms": round(sum(latencies)/len(latencies),2),
        
        "cases" : case_reports,
    }
    
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    
    report_path = reports_dir / f"retrieval-{timestamp}.json"
    
    report_path.write_text(
        json.dumps(report,ensure_ascii=False,indent=2),
        encoding="utf-8"
    )
    
    return report_path


def evaluate_case(case):
    
    started_at= time.perf_counter()
    
    results, analysis = adaptive_retrieve_overlapped(
        query=case["query"],
        retrieve_fn=retrieve,
        history=case.get("history",""),
    )
    
    elapsed_ms = (time.perf_counter()-started_at)*1000
    
    routing_errors=[]
    
    if analysis.query_type != case["expected_route"]:
        
        routing_errors.append(
            f"route expected={case['expected_route']} actual={analysis.query_type}"
        )
        
    if analysis.depends_on_history != case["expected_history_dependent"]:
        
        routing_errors.append(
            "history dependance"
            f"expected={case['expected_history_dependent']}"
            f"actual={analysis.depends_on_history}"
        )
    
    missed_groups=[]
    
    for group in case["expected_groups"]:
        if not group_found_in_results(group,results):
            missed_groups.append(group)
            
    return {
        "passed": len(missed_groups) ==0 and len(routing_errors)==0,
        "missed_groups":missed_groups,
        "routing_errors" : routing_errors,
        "results":results,
        "analysis":analysis,
        "elapsed_ms":elapsed_ms
    }
    
cases = load_cases()
passed_count=0

case_reports=[]



for case in cases:
    evaluation = evaluate_case(case)
    print(f"\n--- {case['id']} ---")
    print(f"Route: {evaluation['analysis'].query_type}")
    print(f"History dependent: {evaluation['analysis'].depends_on_history}")
    print(f"Latency: {evaluation['elapsed_ms']:.0f} ms")

    if evaluation["passed"]:
        passed_count += 1
        print("PASS")
    else:
        print("FAIL")
        print("Missing groups:", evaluation["missed_groups"])
        print("Routing errors:", evaluation["routing_errors"])

    for index, result in enumerate(evaluation["results"], start=1):
        preview = " ".join(result["content"].split())[:160]
        print(f"{index}. {result['similarity']:.4f} | {preview}")
        
    
    case_report={
        "id" : case["id"],
        
        "passed" : evaluation["passed"],
        
        "route" : evaluation["analysis"].query_type,
        
        "history_dependent": evaluation["analysis"].depends_on_history,
        
        "elapsed_ms": round(evaluation["elapsed_ms"],2),
        
        "missed_groups": evaluation["missed_groups"],
        
        "routing_errors" :evaluation["routing_errors"],
        
        "retrieved_chunks":[
            {
                "id":result.get("id"),
                "similarity":round(result["similarity"],4),
            }
            
            for result in evaluation["results"]
        ],
    }
    
    case_reports.append(case_report)

print(f"\nSummary: {passed_count}/{len(cases)} passed")

report_path = save_report(case_reports)

print(f"Report saved:{report_path}")

regressions = find_regressions(case_reports)

if regressions:
    print("REGRESSION DETECTED: ",regressions)
    
    raise SystemExit(1)

print("No regressions against baseline.")
