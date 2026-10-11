---
id: reaction
version: 2
output: ReactionDecisionOut
source: "Paper §4.3.1 p. 11 (prompt with [Agent's Summary Description], time, status, observation, summary of relevant context, 'Should John react to the observation, and if so, what would be an appropriate reaction?'); wait option from released v2/decide_to_react_v1.txt. Whether to talk to another agent is asked first, separately (talk_decision), as plan.py _should_react calls lets_talk before lets_react."
scope: "The agent's dynamic summary, its own status, one perceived observation and the context summary built from its own memories."
max_output_tokens: 300
effort: low
---
### system
{{system_role}}
### user
{{agent_summary}}
It is {{now}}.
{{agent_name}}'s status: {{status}}
Observation: {{observation}}
Summary of relevant context from {{agent_name}}'s memory:
{{context}}
Should {{agent_name}} react to the observation, and if so, what would be an appropriate reaction?

Choose one decision:
- "continue": keep doing the current activity.
- "react": do something else now. Give the new activity and how many minutes it takes.
- "wait": wait until the situation changes. Give how many minutes to wait.

Respond with JSON: {"decision": "continue" | "react" | "wait", "reason": "<one sentence>", "new_activity": "<activity or null>", "duration_minutes": <int or null>}
