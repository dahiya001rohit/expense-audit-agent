# Expense Audit Agent

An AI-powered expense report auditor built with Python, FastAPI, and the Groq API (`llama-3.3-70b-versatile`). It checks every line item in an expense report against company policy and returns a structured JSON verdict with per-item flags, severity levels, and approval requirements.

> Scaffolded with [Claude Code](https://claude.ai/code).

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure your API key

```bash
cp .env.example .env
# Edit .env and add your Groq API key
```

Get a free Groq API key at [console.groq.com](https://console.groq.com).

### 3. Run the batch auditor (generates output files)

```bash
python agent.py
```

This audits the three sample reports and writes results to `output/`:
- `output/audit_ER-2024-0153.json` — Marcus Williams (Sales)
- `output/audit_ER-2024-0184.json` — Rachel Foster (Marketing)
- `output/audit_ER-2024-0220.json` — Patricia Gomez (Business Development)

### 4. Run the API server

```bash
uvicorn main:app --reload
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/reports` | List all report IDs and employee names from sample data |
| `POST` | `/audit` | Audit any expense report JSON in the request body |
| `POST` | `/audit/{report_id}` | Audit a sample report by ID |

### Example: audit a report by ID

```bash
curl -X POST http://localhost:8000/audit/ER-2024-0153
```

Interactive API docs available at `http://localhost:8000/docs`.

---

## How It Works

```
expense_reports.json
       |
       v
  audit_report()
       |
       +-- Loads policy.txt once at module import
       +-- Builds a system prompt: role + full policy text + output schema
       +-- Sends report JSON to Groq (llama-3.3-70b-versatile, temp=0.1)
       +-- Strips any ```json fences from the response
       +-- Parses and returns structured audit JSON

audit_report_safe() wraps the above with a try/catch that returns a
NEEDS_REVIEW result instead of crashing on malformed LLM output.
```

**Policy rules checked (non-exhaustive):**
- First-class flights -> always REJECTED
- Hotel over domestic ($250/night) or international ($350/night) limits
- Meals over per-diem caps ($75 domestic / $100 international per day)
- Client meals over $100/person or missing attendee documentation
- Alcohol with no clients present
- Missing receipts for items over $25
- Software subscriptions without IT approval
- Events/tickets without VP pre-approval
- Gifts to government officials -> always REJECTED
- Expenses older than 90 days -> not reimbursable
- Reports submitted more than 30 days after expense date -> WARNING
- Per diem and actual meal receipts claimed on the same trip

---

## Hardest Design Decision: Rules in Code vs. Rules in Prompt

The central design question was: **where do the policy rules live?**

**Option A - Rules in code:** Parse the expense report in Python, apply explicit if/else checks per rule, and use the LLM only for summarisation.

- Pros: Deterministic, fast, unit-testable, no tokens spent on rule evaluation.
- Cons: Brittle. Every policy update requires a code change. Complex conditions (e.g. "per diem OR actual - not both on the same trip") require non-trivial logic across multiple line items. Edge cases need explicit handling.

**Option B - Rules in prompt (chosen):** Embed the full `policy.txt` text in the system prompt and let the LLM reason over the report holistically.

- Pros: Policy changes are just text file edits - no code change needed. The LLM handles cross-item reasoning naturally (e.g. detecting the per diem + receipt conflict across two line items). Nuanced language ("only reimbursable when clients present") is understood without encoding it as logic.
- Cons: Non-deterministic - the model could miss a rule or hallucinate a flag. Harder to unit-test. Full policy text costs tokens on every call.

**Why Option B wins here:** Expense policy is business logic that changes frequently, has ambiguous edge cases, and requires cross-item reasoning. The LLM handles all three better than hand-written rules. The cost is a modest token overhead and some non-determinism, mitigated by `temperature=0.1` and explicit per-rule enumeration in the system prompt.

---

## What I'd Do With More Time

1. **Confidence scoring** - Ask the LLM to include a `confidence` field per flag so borderline calls can be routed to human review automatically.

2. **Policy versioning** - Store policy snapshots with effective dates so historical reports are audited against the policy in force at submission time.

3. **Structured output / tool use** - Use Groq's JSON mode or function-calling to enforce the output schema at the API level, eliminating the need for the `_strip_fence` workaround.

4. **Caching** - Cache audit results by `(report_id, policy_hash)` so re-running the same report against the same policy does not incur an extra API call.

5. **A/B testing verdicts** - Run two models and compare verdicts to catch inconsistencies, flagging those for human review.

6. **Webhook / async flow** - For large batch runs, process reports async with a job queue and push results to a webhook instead of blocking per request.

---

## Project Structure

```
Groq Agent/
+-- agent.py              # Core audit logic + batch runner
+-- main.py               # FastAPI server
+-- policy.txt            # Company expense policy (source of truth)
+-- data/
|   +-- expense_reports.json   # Sample expense reports
+-- output/               # Generated audit results (git-ignored)
+-- .env                  # Your API key (not committed)
+-- .env.example          # Template
+-- .gitignore
+-- requirements.txt
+-- README.md
```
