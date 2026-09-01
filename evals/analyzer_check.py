import json
import sys

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))

from rag.query_analyzer import analyze_query    

CASES_PATH = ROOT / "evals" / "analyzer_model_cases.jsonl"

FIELDS=(
    ("query_type","expected_route"),
    ("depends_on_history","expected_history_dependent"),
    ("product_intent","expected_product_intent"),
    ("flow_intent","expected_flow_intent"),
    ("order_id","expected_order_id"),
)

def load_cases():
    """Deploy kapisina giren vakalari dondurur.

    "gate": false olan vakalar atlanir. Bunlar hatali degil, modelin
    tutarsiz cevap verdigi sinir vakalar -- ayni girdide bazen SINGLE
    bazen MULTI_FACT donuyor. Kapiya konursa deploy'u rastgele bloke
    eder ve testin guvenilirligini yok eder. benchmark_analyzer_models
    bunlari test etmeye devam ediyor.
    """
    cases = [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [case for case in cases if case.get("gate", True)]
    
def run_case(case):
    
    try:
        analysis = analyze_query(case["query"],case.get("history",""))
    
    except Exception as exc:
        return case["id"], {"error": f"{type(exc).__name__}: {exc}"}
    
    mismatches = {}
    for field, expected_key in FIELDS:
        actual = getattr(analysis,field)
        # .get() degil: eksik bir beklenti alani sessizce None'a dusup
        # testi gecirmesin, KeyError ile bozuk vakayi hemen gostersin.
        expected = case[expected_key]
        if actual != expected:
            mismatches[field] = {"expected":expected,"actual":actual}

    return case["id"], mismatches
    
def main():
    cases = load_cases()
    if not cases:
        raise SystemExit(f"No cases found in {CASES_PATH}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(run_case,cases))

    failures = []
    for case_id, mismatches in results:
        if mismatches:
            failures.append((case_id,mismatches))

    for case_id, mismatches in failures:
        print(f"Case {case_id} failed: {mismatches}")

    passed = len(results) - len(failures)
    print(f"Passed {passed}/{len(results)} cases")

    if failures:
        print("REGRESSION DETECTED!")
        raise SystemExit(1)
    
if __name__ == "__main__":
    main()