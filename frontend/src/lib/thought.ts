/** What a resident is doing in their head, in a few plain words, from the kind of question the model is answering for them. */
const THOUGHTS: Record<string, string> = {
  day_plan: "is planning the day",
  hourly_schedule: "is planning the day",
  previous_day: "is thinking back on yesterday",
  decompose: "is working out what to do next",
  replan: "is rearranging the day",
  choose_location: "is deciding where to go",
  action_grounding: "is getting started",
  reaction: "has noticed something",
  talk_decision: "is deciding whether to say hello",
  interaction_context: "is remembering",
  dialogue_turn: "is finding the words",
  conversation_summary: "is thinking the conversation over",
  conversation_appraisal: "is thinking the conversation over",
  reflection_questions: "is reflecting",
  reflection_insights: "is reflecting",
  summary_aspect: "is taking stock",
  importance: "is taking it in",
  importance_batch: "is taking it in",
  player_chat: "is thinking of a reply",
  resident_request: "is making a wish",
};

export const thought = (task: string | undefined): string => THOUGHTS[task ?? ""] ?? "is thinking";
