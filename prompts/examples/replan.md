# `replan@v2`

> Example from run `examples-main` (offline two-day pilot (MOCK)), default architecture settings. Inputs are exactly what the model was sent in that state; outputs show the format only, not model behavior.

* Template: [`prompts/replan.v2.md`](../replan.v2.md) · SHA-256 `19d21a86a94a69d7a5db94ec729a32f4946d86b4a013a415217649903f62dc10`
* Source: Paper §4.3.1 p. 11 ('We then regenerate the agent's existing plan starting from the time when the reaction takes place'); released v2/new_decomp_schedule_v1.txt; actions written with the minutes left, as in v2/task_decomp_v3.txt
* Information scope: The agent's own schedule, the inserted action and the time; nothing about other agents beyond the inserted action's text.
* Output model: `DecomposeOut` · max output tokens 900 · effort low
* Calls in this run: 62 (ok 62; 0 repair attempts)

## Output schema

```json
{
  "$defs": {
    "TaskOut": {
      "additionalProperties": false,
      "properties": {
        "activity": {
          "type": "string"
        },
        "duration_minutes": {
          "type": "integer"
        },
        "minutes_left": {
          "type": "integer"
        }
      },
      "required": [
        "activity",
        "duration_minutes",
        "minutes_left"
      ],
      "type": "object"
    }
  },
  "additionalProperties": false,
  "properties": {
    "tasks": {
      "items": {
        "$ref": "#/$defs/TaskOut"
      },
      "type": "array"
    }
  },
  "required": [
    "tasks"
  ],
  "type": "object"
}
```

## Smallest successful call

Ledger call 1786 · scope `examples-main` · sim time 2023-02-13T18:20:40 · agent `wolfgang_schulz` · model `mock-llm-v1` · status `ok` · tokens 559 in / 69 out (estimated)

**System**

```text
You are one component of a research simulation of believable characters, reproducing the generative agents architecture (Park et al., UIST 2023). Use only the information in the request; do not invent facts about the world or other characters. Reply with JSON that matches the requested schema and nothing else.
```

**User**

```text
Name: Wolfgang Schulz
Age: 21
Innate traits: Hardworking, passionate, dedicated
Learned traits: Wolfgang Schulz is a student at Oak Hill College studying chemistry and a student athlete. He is very dedicated to both his academics and his sport.
Currently: Wolfgang Schulz is training for his next competition and studying for his exams. He is also looking for ways to make his studies more efficient.
Lifestyle: Wolfgang Schulz goes to bed around 9pm, awakes up around 5am, eats dinner around 6pm.
Daily plan requirement: Wolfgang Schulz goes for a run at the part in the morning, studies during the day, and exercises at his room at night 
Current Date: Monday February 13
Wolfgang Schulz is Hardworking, passionate, dedicated. Notably: Wolfgang Schulz keeps coming back to mayor; Wolfgang Schulz keeps coming back to election.
Wolfgang Schulz spends the day on the usual routine. Notably: Wolfgang Schulz keeps coming back to mayor; Wolfgang Schulz keeps coming back to election.
Wolfgang Schulz feels steady about recent progress. Notably: Sam Moore said to Wolfgang Schulz: "Hi Wolfgang! Did you hear? I am telling people that I am running for the upcoming local mayor election."; Wolfgang Schulz keeps coming back to mayor.

Here was Wolfgang's originally planned schedule from 18:18 to 19:00:
18:18 (14 min) have dinner (continuing)
18:32 (14 min) have dinner (making progress)
18:46 (14 min) have dinner (wrapping up)

At February 13, 2023, 6:20 pm, Wolfgang started something unplanned: "chatting with Maria Lopez" for 3 minutes, until 18:23.

Write Wolfgang's revised schedule from 18:23 to 19:00 (total duration in minutes: 37). Keep what still makes sense from the original plan. Each action lasts 5 to 15 minutes. After each action, write how many of the 37 minutes are left; the last action leaves 0.

Respond with JSON: {"tasks": [{"activity": "<what>", "duration_minutes": <int>, "minutes_left": <int>}, ...]}
```

**Raw output**

```json
{"tasks": [{"activity": "have dinner (continuing)", "duration_minutes": 13, "minutes_left": 24}, {"activity": "have dinner (making progress)", "duration_minutes": 12, "minutes_left": 12}, {"activity": "have dinner (wrapping up)", "duration_minutes": 12, "minutes_left": 0}]}
```

**Validated output**

```json
{
  "tasks": [
    {
      "activity": "have dinner (continuing)",
      "duration_minutes": 13,
      "minutes_left": 24
    },
    {
      "activity": "have dinner (making progress)",
      "duration_minutes": 12,
      "minutes_left": 12
    },
    {
      "activity": "have dinner (wrapping up)",
      "duration_minutes": 12,
      "minutes_left": 0
    }
  ]
}
```

No call for this task needed a repair in this run.
