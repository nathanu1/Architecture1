# `importance_batch@v1`

> Example from run `examples-main` (offline two-day pilot (MOCK)), default architecture settings. Inputs are exactly what the model was sent in that state; outputs show the format only, not model behavior.

* Template: [`prompts/importance_batch.v1.md`](../importance_batch.v1.md) · SHA-256 `b1eb3135214bff193cbc5a8965441e001a1bc775661449eab089407e5c4d7b2d`
* Source: Same rating scale and per-kind anchors as importance@v1 (paper p. 9); batching the statements of one conversation, or the items of one plan, is our engineering choice (spec D-5)
* Information scope: The rating agent's own summary description and the memories of one batch (one conversation the agent took part in, or the agent's own plan).
* Output model: `ImportanceBatchOut` · max output tokens 400 · effort low
* Calls in this run: 82 (ok 82; 0 repair attempts)

## Output schema

```json
{
  "$defs": {
    "RatingItem": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string"
        },
        "rating": {
          "type": "integer"
        }
      },
      "required": [
        "id",
        "rating"
      ],
      "type": "object"
    }
  },
  "additionalProperties": false,
  "properties": {
    "ratings": {
      "items": {
        "$ref": "#/$defs/RatingItem"
      },
      "type": "array"
    }
  },
  "required": [
    "ratings"
  ],
  "type": "object"
}
```

## Smallest successful call

Ledger call 3070 · scope `examples-main` · sim time 2023-02-14T12:00:10 · agent `wolfgang_schulz` · model `mock-llm-v1` · status `ok` · tokens 454 in / 23 out (estimated)

**System**

```text
You are one component of a research simulation of believable characters, reproducing the generative agents architecture (Park et al., UIST 2023). Use only the information in the request; do not invent facts about the world or other characters. Reply with JSON that matches the requested schema and nothing else.
```

**User**

```text
Here is a brief description of Wolfgang Schulz.
Name: Wolfgang Schulz
Age: 21
Innate traits: Hardworking, passionate, dedicated
Learned traits: Wolfgang Schulz is a student at Oak Hill College studying chemistry and a student athlete. He is very dedicated to both his academics and his sport.
Currently: Wolfgang Schulz is training for his next competition and studying for his exams. He is also looking for ways to make his studies more efficient.
Lifestyle: Wolfgang Schulz goes to bed around 9pm, awakes up around 5am, eats dinner around 6pm.
Daily plan requirement: Wolfgang Schulz goes for a run at the part in the morning, studies during the day, and exercises at his room at night 
Current Date: Tuesday February 14

On the scale of 1 to 10, where 1 is purely mundane (e.g., routine morning greetings) and 10 is extremely poignant (e.g., a conversation about breaking up, a fight), rate the likely poignancy of each of the following conversation statements for Wolfgang Schulz. Rate each one independently.

1. Wolfgang Schulz said to Sam Moore: "Hi Sam! Did you hear? Klaus Mueller told me: Sam Moore told me: That sounds wonderful, I'd love to come to the party!. You should come!"
2. Sam Moore said to Wolfgang Schulz: "Wonderful, see you there, Wolfgang!"
3. Wolfgang Schulz had a conversation with Sam Moore. This is a conversation about a Valentine's Day party.

Respond with JSON: {"ratings": [{"id": "<the number shown>", "rating": <integer from 1 to 10>}, ...]} with one entry per item.
```

**Raw output**

```json
{"ratings": [{"id": "1", "rating": 8}, {"id": "2", "rating": 6}, {"id": "3", "rating": 6}]}
```

**Validated output**

```json
{
  "ratings": [
    {
      "id": "1",
      "rating": 8
    },
    {
      "id": "2",
      "rating": 6
    },
    {
      "id": "3",
      "rating": 6
    }
  ]
}
```

No call for this task needed a repair in this run.
