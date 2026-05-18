import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from agent import audit_report_safe

app = FastAPI(title="Expense Audit Agent", version="1.0.0")

_BASE = Path(__file__).parent
_DATA_PATH = _BASE / "data" / "expense_reports.json"
_OUTPUT_PATH = _BASE / "output"
_OUTPUT_PATH.mkdir(exist_ok=True)

with open(_DATA_PATH) as f:
    _raw = json.load(f)

REPORTS: dict = (
    {r["report_id"]: r for r in _raw} if isinstance(_raw, list) else _raw
)

_VERDICT_KEY = {
    "APPROVED": "approved",
    "APPROVED_WITH_FLAGS": "approved_with_flags",
    "NEEDS_REVIEW": "needs_review",
    "REJECTED": "rejected",
}


def _save_audit(result: dict) -> None:
    report_id = result.get("report_id", "UNKNOWN")
    out_file = _OUTPUT_PATH / f"audit_{report_id}.json"
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/reports")
def list_reports():
    return [
        {
            "report_id": rid,
            "employee": r.get("employee_name", r.get("employee", "")),
            "department": r.get("department", ""),
        }
        for rid, r in REPORTS.items()
    ]


# Must be registered before /audit/{report_id} so "history" isn't consumed as a param
@app.get("/audit/history/{report_id}")
def audit_history(report_id: str):
    out_file = _OUTPUT_PATH / f"audit_{report_id}.json"
    if not out_file.exists():
        raise HTTPException(status_code=404, detail=f"No saved audit for '{report_id}'")
    with open(out_file) as f:
        return json.load(f)


@app.post("/audit")
async def audit_any(request: Request):
    report = await request.json()
    result = audit_report_safe(report)
    _save_audit(result)
    return result


# Must be registered before /audit/{report_id} so "batch" isn't consumed as a param
@app.post("/audit/batch")
async def audit_batch(request: Request):
    body = await request.json()

    if isinstance(body, list):
        report_ids = body
    elif isinstance(body, dict):
        report_ids = body.get("report_ids", [])
    else:
        report_ids = []

    if not report_ids:
        report_ids = list(REPORTS.keys())

    results = []
    stats = {"approved": 0, "approved_with_flags": 0, "needs_review": 0, "rejected": 0}

    for rid in report_ids:
        if rid not in REPORTS:
            continue
        result = audit_report_safe(REPORTS[rid])
        _save_audit(result)
        results.append(result)
        key = _VERDICT_KEY.get(result.get("verdict", ""))
        if key:
            stats[key] += 1

    return {"total": len(results), **stats, "results": results}


@app.post("/audit/{report_id}")
def audit_by_id(report_id: str):
    if report_id not in REPORTS:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
    result = audit_report_safe(REPORTS[report_id])
    _save_audit(result)
    return result
