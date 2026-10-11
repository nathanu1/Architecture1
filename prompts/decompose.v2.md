---
id: decompose
version: 2
output: DecomposeOut
source: "Paper §4.3 p. 11 ('recursively decompose this again into 5–15 minute chunks'); Appendix A p. 21 (just-in-time); released v2/task_decomp_v3.txt (each subtask followed by '(duration in minutes: X, minutes left: Y)')"
scope: "The agent's identity, dynamic summary and the hour-level plan around the activity."
max_output_tokens: 900
effort: low
---
### system
{{system_role}}
### user
{{agent_summary}}

Today is {{day_label}}. {{first_name}}'s schedule around this time:
{{schedule_context}}

In 5-minute increments, list the smaller actions {{first_name}} does for "{{activity}}" from {{start}} to {{end}} (total duration in minutes: {{duration}}). Each action lasts {{min_minutes}} to {{max_minutes}} minutes. After each action, write how many of the {{duration}} minutes are left; the last action leaves 0.

Respond with JSON: {"tasks": [{"activity": "<what {{first_name}} is doing>", "duration_minutes": <int>, "minutes_left": <int>}, ...]}
