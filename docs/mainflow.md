User speaks
   ↓
ASR → transcript + Speaker Diariazation
   ↓
LLM → intent = "schedule meeting"
   ↓
Orchestrator:
   → call Scheduling Agent
   ↓
Scheduling Agent:
   → check calendar API
   → resolve conflict
   ↓
LLM:
   → confirm with user
   ↓
Action Agent:
   → create meeting
   → send email