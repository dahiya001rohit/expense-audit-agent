# Expense Audit Agent

An AI-powered expense report auditor built with **Python**, **FastAPI**, and the **Groq API** (`llama-3.3-70b-versatile`). It checks every line item against company policy and returns a structured JSON verdict with per-item flags, severity levels, approval routing, and a finance-manager summary.

> Scaffolded and iterated with [Claude Code](https://claude.ai/code).

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure your API key

```bash
cp .env.example .env
# Edit .env — set GROQ_API_KEY=your_key_here
```

Get a free key at [console.groq.com](https://console.groq.com).

### 3. Run the batch auditor

```bash
python agent.py
```

Audits three sample reports and writes results to `output/`:

| File | Employee | Expected verdict |
|------|----------|-----------------|
| `audit_ER-2024-0153.json` | Marcus Williams | REJECTED (first-class flight) |
| `audit_ER-2024-0184.json` | Rachel Foster | REJECTED (gift to govt official) |
| `audit_ER-2024-0220.json` | Patricia Gomez | REJECTED (expense >90 days old) |

### 4. Run the API server

```bash
uvicorn main:app --reload
```

Interactive docs at `http://localhost:8000/docs`.

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/reports` | List all report IDs + employee names |
| `GET` | `/audit/history/{report_id}` | Return a previously saved audit from `output/` |
| `POST` | `/audit` | Audit any expense report JSON (body = raw report) |
| `POST` | `/audit/batch` | Audit multiple reports; body = `["ER-...", ...]` or `{}` for all |
| `POST` | `/audit/{report_id}` | Audit a sample report by ID |

Every `POST /audit*` call auto-saves the result to `output/audit_{report_id}.json`.

### Examples

```bash
# Audit one report by ID
curl -X POST http://localhost:8000/audit/ER-2024-0153

# Retrieve a saved audit
curl http://localhost:8000/audit/history/ER-2024-0153

# Batch audit specific reports
curl -X POST http://localhost:8000/audit/batch \
  -H "Content-Type: application/json" \
  -d '["ER-2024-0153", "ER-2024-0184", "ER-2024-0220"]'

# Batch audit ALL reports
curl -X POST http://localhost:8000/audit/batch \
  -H "Content-Type: application/json" \
  -d '{}'
```

Batch response includes summary stats:

```json
{
  "total": 3,
  "approved": 0,
  "approved_with_flags": 0,
  "needs_review": 0,
  "rejected": 3,
  "results": [...]
}
```

---

## Architecture

```
 .env (GROQ_API_KEY)
        |
        v
   agent.py (module)
   +-----------------------------------------+
   | policy.txt  ──> loaded once at import   |
   |                                         |
   | audit_report(report)                    |
   |   1. Build system prompt                |
   |      (role + policy + few-shot          |
   |       examples + schema)               |
   |   2. POST to Groq API                   |
   |      model: llama-3.3-70b-versatile     |
   |      temp:  0.1                         |
   |   3. Strip ```json fences               |
   |   4. json.loads()                       |
   |   5. Inject audited_at + policy_version |
   |      (deterministic, not from LLM)      |
   |                                         |
   | audit_report_safe()                     |
   |   wraps above; returns NEEDS_REVIEW     |
   |   fallback on JSONDecodeError           |
   +-----------------------------------------+
        |
        v
   main.py (FastAPI)
   +-----------------------------------------+
   | Loads expense_reports.json at startup   |
   |                                         |
   | POST /audit        ──> audit + save     |
   | POST /audit/batch  ──> multi + stats    |
   | POST /audit/{id}   ──> audit + save     |
   | GET  /audit/history/{id} ──> read file  |
   | GET  /reports      ──> list reports     |
   | GET  /health       ──> {"status":"ok"}  |
   +-----------------------------------------+
        |
        v
   output/audit_{report_id}.json
```

---

## Output Format

Every audit result contains:

```json
{
  "report_id": "ER-2024-0153",
  "employee": "Marcus Williams",
  "department": "Engineering",
  "verdict": "REJECTED",
  "total_claimed": 2585.00,
  "total_approvable": 1245.00,
  "approval_required": "Payment blocked — policy violation",
  "audited_at": "2024-12-15T10:23:44.123456+00:00",
  "policy_version": "October 15, 2024",
  "flags": [
    {
      "item_description": "Flight LAX-SFO round trip (first class)",
      "amount": 1240.00,
      "date": "2024-11-20",
      "severity": "VIOLATION",
      "reason": "First-class airfare is never reimbursable.",
      "policy_section": "Section 3.1"
    }
  ],
  "summary": "This report contains a first-class flight booking which is prohibited under policy..."
}
```

**Verdict logic** (strict priority order):
- `REJECTED` — any flag is `VIOLATION`
- `NEEDS_REVIEW` — any flag is `WARNING`, no `VIOLATION`
- `APPROVED_WITH_FLAGS` — all flags are `INFO` only
- `APPROVED` — zero flags

---

## Hardest Design Decision: Rules in Code vs. Rules in Prompt

The core architectural question was where to put the policy rules: encoded in Python logic, or embedded in the LLM prompt.

**Option A — Rules in code.** Parse the report in Python, apply explicit `if/else` checks per rule (e.g. `if nightly_rate > 250 and is_domestic: flag(...)`), and use the LLM only for the summary sentence.

- Pros: Fully deterministic. Unit-testable. Zero extra tokens per rule. Sub-millisecond evaluation.
- Cons: Every policy change requires a code change and a deploy. Cross-item rules are painful — detecting "per diem AND actual receipts on the same trip" requires correlating multiple line items in code. Nuanced language ("only reimbursable when clients present") is surprisingly hard to encode correctly for all edge cases. The policy doc becomes a dead artifact that diverges from the code over time.

**Option B — Rules in prompt (chosen).** Embed the full `policy.txt` in the system prompt alongside few-shot examples, and let `llama-3.3-70b-versatile` reason over the full report holistically.

- Pros: Policy changes are text file edits — no code change, no deploy. The LLM handles cross-item reasoning naturally (it sees the whole report at once and can detect the per-diem conflict across two separate line items). Ambiguous language in the policy is understood as written, not over-simplified. Adding a new rule is one line in policy.txt.
- Cons: Non-deterministic — the model can miss a rule or produce a slightly different flag wording on each run. Latency is ~2–4 seconds per report vs microseconds for code checks. The entire policy text burns tokens on every call. Hard to unit-test (outputs vary).

**What I traded off:** Consistency and cost for flexibility and maintainability. The non-determinism is mitigated by `temperature=0.1`, explicit per-rule enumeration in the checklist, and concrete few-shot examples that anchor the model to the right severity classifications. The token cost is acceptable for a low-volume audit workload (expense reports are not high-frequency). For a high-volume system processing thousands of reports per minute, a hybrid approach — code for deterministic rules, LLM for ambiguous ones — would be the right call.

---

## What I'd Do With More Time

1. **Structured output validation** — Use Groq's JSON mode or Pydantic to enforce the output schema at the API level, making `_strip_fence` unnecessary and guaranteeing field types.

2. **Confidence scores per flag** — Ask the model to include a `confidence: 0.0–1.0` field on each flag. Flags below a threshold (e.g. 0.7) get routed to human review before rejection.

3. **Policy embedding cache** — Embed `policy.txt` with a text embedding model and cache the vector. On each audit, retrieve only the top-k relevant policy sections rather than sending the entire document. Cuts token cost by ~60% on large policies.

4. **Webhook notifications** — After saving an audit, POST a summary to a Slack webhook or email queue so finance managers are notified in real-time without polling the API.

5. **Audit trail + versioning** — Store `(report_id, policy_hash, model_version, audited_at)` in SQLite so re-auditing the same report against a new policy version produces a diff of changed verdicts.

6. **Async batch processing** — Move `POST /audit/batch` to a background task queue (Celery or asyncio) so large batches don't block the HTTP response.

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.11+ |
| API framework | FastAPI + Uvicorn |
| LLM | Groq API — `llama-3.3-70b-versatile` |
| Config | python-dotenv |
| Scaffolding | Claude Code (Anthropic) |

---

## Project Structure

```
expense-audit-agent/
├── agent.py              # Core audit logic + standalone batch runner
├── main.py               # FastAPI server + output auto-save
├── policy.txt            # Company expense policy (source of truth for LLM)
├── data/
│   └── expense_reports.json
├── output/               # Generated audit JSONs (git-ignored)
├── .env                  # GROQ_API_KEY (not committed)
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```
