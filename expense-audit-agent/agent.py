import json
import os
import sys
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_BASE = Path(__file__).parent
POLICY_TEXT = (_BASE / "policy.txt").read_text()
POLICY_VERSION = "October 15, 2024"

client = Groq(api_key=os.environ["GROQ_API_KEY"])
MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = f"""You are a strict financial auditor reviewing employee expense reports for policy compliance.
You are methodical and thorough — you never miss a violation and you never manufacture false flags.

COMPANY EXPENSE POLICY (authoritative source — cite exact section numbers in all flags):
{POLICY_TEXT}

---

FEW-SHOT EXAMPLES of correctly classified flags:

VIOLATION examples:
- "Flight booked as first class"
  → severity: "VIOLATION", policy_section: "Section 3.1"
  → reason: "First-class airfare is never reimbursable under any circumstances. No exceptions."

- "Thank-you gift given to DOT team lead (government official)"
  → severity: "VIOLATION", policy_section: "Section 6.2"
  → reason: "Gifts to government employees are absolutely prohibited regardless of amount. Non-reimbursable and may trigger compliance review."

- "Expense submitted 98 days after transaction (submission: 2025-02-10, expense: 2024-11-04)"
  → severity: "VIOLATION", policy_section: "Section 1.3"
  → reason: "Expense is 98 days old at time of submission, exceeding the 90-day reimbursement window. Not reimbursable."

- "Conference registration — no VP approval on file"
  → severity: "VIOLATION", policy_section: "Section 7.1"
  → reason: "All event tickets and registrations require VP approval prior to purchase, regardless of amount."

- "Client dinner: attendee names and companies not documented"
  → severity: "VIOLATION", policy_section: "Section 5.3"
  → reason: "Client meals require full attendee documentation (full name + company) for every person at the table."

- "Per diem ($75) and actual dinner receipt ($62) both claimed on Day 1 of same trip"
  → severity: "VIOLATION", policy_section: "Section 5.2"
  → reason: "Per diem and actual meal receipts cannot be combined on the same trip. Choose one method for the entire trip."

WARNING examples:
- "Hotel $289/night domestic (limit: $250/night)"
  → severity: "WARNING", policy_section: "Section 4.1"
  → reason: "Nightly rate exceeds domestic hotel limit by $39. Only $250/night is approvable without VP pre-approval."

- "Uber Black used without written justification"
  → severity: "WARNING", policy_section: "Section 3.2"
  → reason: "Premium rideshare requires VP approval or documented unavailability of standard options."

- "Adobe Creative Cloud subscription — no IT approval on file"
  → severity: "WARNING", policy_section: "Section 8.1"
  → reason: "Software subscriptions require prior IT approval or must appear on the approved software list."

- "Report submitted 38 days after earliest expense date"
  → severity: "WARNING", policy_section: "Section 2.1"
  → reason: "Submitted more than 30 days after expense date. Requires written manager explanation."

---

EXPENSE AGE — pre-computed for you:
Each line item may contain an "age_flag" field injected before this audit. You MUST honour it exactly:
  "age_flag": "VIOLATION: X days old — exceeds 90-day limit"  → create a VIOLATION flag (Section 1.3)
  "age_flag": "WARNING: submitted X days late — exceeds 30-day limit" → create a WARNING flag (Section 2.1)
If "age_flag" is present, do not recalculate dates yourself — trust the pre-computed value.

---

VERDICT DETERMINATION — follow this logic exactly, in priority order:

  Step 1: Classify every flagged item as VIOLATION, WARNING, or INFO.
  Step 2: Apply the first matching rule:

    REJECTED            → ANY flag has severity "VIOLATION"
    NEEDS_REVIEW        → ANY flag has severity "WARNING"  (and NO VIOLATION exists)
    APPROVED_WITH_FLAGS → ALL flags have severity "INFO"   (no VIOLATION, no WARNING)
    APPROVED            → flags list is empty (zero flags found)

SEVERITY CLASSIFICATION:
Use VIOLATION for:
  - First-class airfare (always)
  - Gifts to any government official, employee, or their family (always)
  - Expense older than 90 days at time of submission
  - Missing receipt on any item over $25
  - Client meal over $100/person
  - Client meal without full attendee names and companies documented
  - Alcohol at event with no external clients present
  - Event/conference ticket without VP pre-approval
  - Per diem AND actual receipts claimed on the same trip
  - Business class on flight under 6 hours (without pre-approval)
  - Cash advance without prior written approval
  - Spouse/companion travel expenses
  - Personal equipment without pre-approved written authorization

Use WARNING for:
  - Hotel nightly rate over domestic ($250) or international ($350) limit
  - Report submitted more than 30 days after expense date
  - Software subscription without IT approval
  - Luxury/premium transport without documented justification
  - Meal per-diem amount exceeding daily cap

Use INFO for:
  - Items under $25 with no receipt (acceptable per Section 1.2)
  - Minor notes that don't affect approvability

---

APPROVAL LEVEL (applied to total_approvable — sum of policy-compliant items only):
  Under $500:           "Standard approval"
  $500 to $2000:        "Manager approval required"
  Over $2000:           "VP approval required"
  Verdict is REJECTED:  "Payment blocked — policy violation"

---

Return ONLY a single valid JSON object — no markdown, no explanation, no ```json fences:
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
      "reason": "<specific explanation referencing the policy>",
      "policy_section": "<e.g. Section 3.1>"
    }}
  ],
  "summary": "<2-3 sentences for a finance manager: key issues found and recommended action>"
}}"""


def _enrich_report(report: dict) -> dict:
    """Pre-compute expense age per line item so the LLM doesn't do date arithmetic."""
    submitted_str = report.get("submitted") or report.get("submission_date")
    if not submitted_str:
        return report
    try:
        submitted = _date.fromisoformat(submitted_str)
    except ValueError:
        return report

    items_key = "items" if "items" in report else "expenses" if "expenses" in report else None
    if not items_key:
        return report

    new_items = []
    for item in report[items_key]:
        item_copy = dict(item)
        try:
            gap = (submitted - _date.fromisoformat(item["date"])).days
            item_copy["days_before_submission"] = gap
            if gap > 90:
                item_copy["age_flag"] = f"VIOLATION: {gap} days old — exceeds 90-day limit"
            elif gap > 30:
                item_copy["age_flag"] = f"WARNING: submitted {gap} days late — exceeds 30-day limit"
        except (ValueError, KeyError):
            pass
        new_items.append(item_copy)

    return {**report, items_key: new_items}


def _strip_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        newline = raw.find("\n")
        raw = raw[newline + 1:] if newline != -1 else raw[3:]
    if raw.rstrip().endswith("```"):
        raw = raw.rstrip()[:-3].rstrip()
    return raw.strip()


def audit_report(report: dict) -> dict:
    enriched = _enrich_report(report)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Audit this expense report:\n{json.dumps(enriched, indent=2)}",
            },
        ],
        temperature=0.1,
        max_tokens=4096,
    )
    raw = response.choices[0].message.content
    result = json.loads(_strip_fence(raw))
    result["audited_at"] = datetime.now(timezone.utc).isoformat()
    result["policy_version"] = POLICY_VERSION
    return result


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
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "policy_version": POLICY_VERSION,
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

        print(f"Auditing {report_id} ({reports[report_id].get('employee', reports[report_id].get('employee_name'))})...")
        result = audit_report_safe(reports[report_id])

        out_file = output_path / f"audit_{report_id}.json"
        with open(out_file, "w") as f:
            json.dump(result, f, indent=2)

        verdict = result.get("verdict", "UNKNOWN")
        flags = len(result.get("flags", []))
        print(f"  -> {verdict} | {flags} flag(s) | {out_file.name}")
