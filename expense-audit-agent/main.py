import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from agent import audit_report_safe

app = FastAPI(title="Expense Audit Agent", version="1.0.0")

_DATA_PATH = Path(__file__).parent / "data" / "expense_reports.json"

with open(_DATA_PATH) as f:
    _raw = json.load(f)

REPORTS: dict = (
    {r["report_id"]: r for r in _raw} if isinstance(_raw, list) else _raw
)


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


@app.post("/audit")
async def audit_any(request: Request):
    report = await request.json()
    return audit_report_safe(report)


@app.post("/audit/{report_id}")
def audit_by_id(report_id: str):
    if report_id not in REPORTS:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found")
    return audit_report_safe(REPORTS[report_id])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
