# `conversation_appraisal@v1`

> Example from run `examples-appraisal` (offline smoke with social appraisal (MOCK)), settings that differ from the defaults: `social.appraisal=llm`. Inputs are exactly what the model was sent in that state; outputs show the format only, not model behavior.

* Template: [`prompts/conversation_appraisal.v1.md`](../conversation_appraisal.v1.md) · SHA-256 `cafb983e56f39faa934f1edccb8b9f193da9023ff99e40b363cfeba7b08489e5`
* Source: Research extension (docs/research_platform.md, social memory). Not in the paper or the released code. Modeled on the relationship-closeness update of Humanoid Agents (Wang, Chiu & Chiu, EMNLP 2023 demo), asked from one participant's point of view after a conversation.
* Information scope: One participant's own view: its name, the partner's name and the transcript both of them heard. Nothing from the partner's memory.
* Output model: `AppraisalOut` · max output tokens 200 · effort low
* Calls in this run: 2 (ok 2; 0 repair attempts)

## Output schema

```json
{
  "additionalProperties": false,
  "description": "One participant's appraisal of a conversation (social memory extension): -2..2.",
  "properties": {
    "valence": {
      "type": "integer"
    },
    "reason": {
      "type": "string"
    }
  },
  "required": [
    "valence",
    "reason"
  ],
  "type": "object"
}
```

## Smallest successful call

Ledger call 234 · scope `examples-appraisal` · sim time 2023-02-13T08:17:00 · agent `sam_moore` · model `mock-llm-v1` · status `ok` · tokens 297 in / 15 out (estimated)

**System**

```text
You are one component of a research simulation of believable characters, reproducing the generative agents architecture (Park et al., UIST 2023). Use only the information in the request; do not invent facts about the world or other characters. Reply with JSON that matches the requested schema and nothing else.
```

**User**

```text
Conversation between Sam Moore and Wolfgang Schulz:
Sam Moore: Hi Wolfgang! Did you hear? I am telling people that I am running for the upcoming local mayor election.
Wolfgang Schulz: Oh, also: I am close with Ayesha Khan, who is a classmate in one of my classes and a dormmate.
Sam Moore: Oh, also: I am thinking of running in the upcoming local mayor election.
Wolfgang Schulz: Glad to hear it.
Sam Moore: It was good talking to you, Wolfgang. See you around!

From Sam Moore's point of view only, how did this conversation leave Sam Moore feeling about Wolfgang Schulz? Rate it on a five-point scale: -2 (much worse, a real conflict), -1 (somewhat worse), 0 (unchanged, routine), 1 (somewhat better), 2 (much better, a meaningful positive exchange). Base the rating only on what was said.

Respond with JSON: {"valence": <-2 | -1 | 0 | 1 | 2>, "reason": "<one sentence>"}
```

**Raw output**

```json
{"valence": 1, "reason": "A pleasant, informative chat."}
```

**Validated output**

```json
{
  "valence": 1,
  "reason": "A pleasant, informative chat."
}
```

No call for this task needed a repair in this run.
