import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_BASE = Path(__file__).parent
POLICY_TEXT = (_BASE / "policy.txt").read_text()

client = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = f"""You are a strict financial auditor reviewing employee expense reports for policy compliance.
You check every single line item against company policy and flag any issues precisely.

COMPANY EXPENSE POLICY (authoritative — cite section numbers in your flags):
{POLICY_TEXT}

Return ONLY a single valid JSON object with this exact structure — no markdown, no explanation, no ```json fences:
{{
  "report_id": "<string>",
  "employee": "<string>",
  "department": "<string>",
  "verdict": "<APPROVED|APPROVED_WITH_FLAGS|NEEDS_REVIEW|REJECTED>",
  "total_claimed": <number>,
  "total_approvable": <number>,
  "approval_required": "<string>",
  "flags": [
    {{
      "item_description": "<string>",
      "amount": <number>,
      "date": "<YYYY-MM-DD>",
      "severity": "<VIOLATION|WARNING|INFO>",
      "reason": "<string>",
      "policy_section": "<string>"
    }}
  ],
  "summary": "<2-3 sentence summary for a finance manager>"
}}

VERDICT RULES:
- APPROVED: All items within policy, no issues.
- APPROVED_WITH_FLAGS: Only INFO or WARNING flags, approvable with notes.
- NEEDS_REVIEW: One or more VIOLATION flags requiring human sign-off before payment.
- REJECTED: Contains per-policy prohibited items (first-class flights, gifts to government officials,
  expenses over 90 days old, unapproved cash advances). These cannot be approved at any level.

APPROVAL LEVEL RULES (based on total_approvable):
- Under $500: "Standard approval"
- $500 to $2000 inclusive: "Manager approval required"
- Over $2000: "VP approval required"
- If verdict is REJECTED, set approval_required to "Payment blocked — policy violation"

CHECKS TO ALWAYS PERFORM (non-exhaustive — use your judgment for edge cases too):
1. First-class flights -> VIOLATION (Section 3.1), remove from approvable
2. Hotel domestic > $250/night -> VIOLATION (Section 4.1), approvable up to limit only
3. Hotel international > $350/night -> VIOLATION (Section 4.1), approvable up to limit only
4. Daily meals domestic > $75/day -> VIOLATION (Section 5.1)
5. Daily meals international > $100/day -> VIOLATION (Section 5.1)
6. Client meal > $100/person -> VIOLATION (Section 5.3)
7. Client meal with no attendees documented -> VIOLATION (Section 5.3)
8. Alcohol without clients present -> VIOLATION (Section 5.4)
9. Missing receipt on item > $25 -> VIOLATION (Section 1.2)
10. Software subscription without IT approval -> WARNING (Section 8.1)
11. Expense date > 90 days before submission date -> VIOLATION (Section 1.3), not reimbursable
12. Report submitted > 30 days after expense date -> WARNING (Section 2.1)
13. Per diem AND actual meal receipts on same trip -> VIOLATION (Section 5.2)
14. Event/conference ticket without VP approval -> VIOLATION (Section 7.1)
15. Gift to government official -> PROHIBITED VIOLATION (Section 6.2), remove from approvable
16. Cash advance without prior approval -> VIOLATION (Section 9.1)
17. Spouse/companion travel expenses -> VIOLATION (Section 1.4)
18. Gifts over $100/recipient -> VIOLATION (Section 6.1)

TODAY'S DATE for age calculations: 2026-05-19
"""


def _strip_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        newline = raw.find("\n")
        raw = raw[newline + 1:] if newline != -1 else raw[3:]
    if raw.rstrip().endswith("```"):
        raw = raw.rstrip()[:-3].rstrip()
    return raw.strip()


def audit_report(report: dict) -> dict:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Audit this expense report:\n{json.dumps(report, indent=2)}",
            },
        ],
        temperature=0.1,
        max_tokens=4096,
    )
    raw = response.choices[0].message.content
    return json.loads(_strip_fence(raw))


def audit_report_safe(report: dict) -> dict:
    try:
        return audit_report(report)
    except json.JSONDecodeError as e:
        return {
            "report_id": report.get("report_id", "UNKNOWN"),
            "employee": report.get("employee_name", report.get("employee", "Unknown")),
            "department": report.get("department", "Unknown"),
            "verdict": "NEEDS_REVIEW",
            "total_claimed": 0,
            "total_approvable": 0,
            "approval_required": "Manual review required — audit system error",
            "flags": [
                {
                    "item_description": "Audit parsing error",
                    "amount": 0,
                    "date": "",
                    "severity": "WARNING",
                    "reason": f"LLM returned malformed JSON: {e}",
                    "policy_section": "N/A",
                }
            ],
            "summary": "Automated audit could not be completed. Manual review required.",
        }


if __name__ == "__main__":
    data_path = _BASE / "data" / "expense_reports.json"
    output_path = _BASE / "output"
    output_path.mkdir(exist_ok=True)

    with open(data_path) as f:
        raw_data = json.load(f)

    reports: dict = (
        {r["report_id"]: r for r in raw_data}
        if isinstance(raw_data, list)
        else raw_data
    )

    targets = ["ER-2024-0153", "ER-2024-0184", "ER-2024-0220"]

    for report_id in targets:
        if report_id not in reports:
            print(f"[SKIP] {report_id} not found in data", file=sys.stderr)
            continue

        print(f"Auditing {report_id} ({reports[report_id].get('employee_name')})...")
        result = audit_report_safe(reports[report_id])

        out_file = output_path / f"audit_{report_id}.json"
        with open(out_file, "w") as f:
            json.dump(result, f, indent=2)

        verdict = result.get("verdict", "UNKNOWN")
        flags = len(result.get("flags", []))
        print(f"  -> {verdict} | {flags} flag(s) | {out_file.name}")
