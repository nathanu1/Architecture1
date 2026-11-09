---
id: conversation_appraisal
version: 1
output: AppraisalOut
source: "Research extension (docs/research_platform.md, social memory). Not in the paper or the released code. Modeled on the relationship-closeness update of Humanoid Agents (Wang, Chiu & Chiu, EMNLP 2023 demo), asked from one participant's point of view after a conversation."
scope: "One participant's own view: its name, the partner's name and the transcript both of them heard. Nothing from the partner's memory."
max_output_tokens: 200
effort: low
---
### system
{{system_role}}
### user
Conversation between {{agent_name}} and {{partner_name}}:
{{transcript}}

From {{agent_name}}'s point of view only, how did this conversation leave {{agent_name}} feeling about {{partner_name}}? Rate it on a five-point scale: -2 (much worse, a real conflict), -1 (somewhat worse), 0 (unchanged, routine), 1 (somewhat better), 2 (much better, a meaningful positive exchange). Base the rating only on what was said.

Respond with JSON: {"valence": <-2 | -1 | 0 | 1 | 2>, "reason": "<one sentence>"}
