import type { Question } from "@/lib/api/models";

/** HLD section 4: at most 4 questions per product. Phone cards and desktop form both go through this. */
export const MAX_QUESTIONS = 4;

export function limitQuestions(questions: Question[]): Question[] {
  return questions.slice(0, MAX_QUESTIONS);
}

export interface SwipeState {
  index: number;
  total: number;
  /** Currently selected option per question id. Starts at the AI's pick. */
  selected: Record<string, string>;
  /** Question ids the seller has moved past (kept or changed). */
  committed: string[];
  done: boolean;
}

export type SwipeAction =
  | { type: "select"; questionId: string; optionId: string }
  | { type: "next" }
  | { type: "back" };

export function aiPickId(q: Question): string {
  return (q.options.find((o) => o.is_ai_pick) ?? q.options[0]).id;
}

export function initSwipe(questions: Question[]): SwipeState {
  const qs = limitQuestions(questions);
  const selected: Record<string, string> = {};
  for (const q of qs) selected[q.id] = aiPickId(q);
  return { index: 0, total: qs.length, selected, committed: [], done: qs.length === 0 };
}

export function swipeReducer(state: SwipeState, action: SwipeAction, questions: Question[]): SwipeState {
  const qs = limitQuestions(questions);
  switch (action.type) {
    case "select": {
      const q = qs.find((x) => x.id === action.questionId);
      if (!q || !q.options.some((o) => o.id === action.optionId)) return state;
      return { ...state, selected: { ...state.selected, [action.questionId]: action.optionId } };
    }
    case "next": {
      if (state.done) return state;
      const q = qs[state.index];
      const committed = state.committed.includes(q.id) ? state.committed : [...state.committed, q.id];
      const index = state.index + 1;
      return { ...state, committed, index: Math.min(index, state.total - 1), done: index >= state.total };
    }
    case "back": {
      if (state.done) return { ...state, done: false, index: Math.max(state.total - 1, 0) };
      return { ...state, index: Math.max(state.index - 1, 0) };
    }
  }
}

export function currentQuestion(state: SwipeState, questions: Question[]): Question | undefined {
  return limitQuestions(questions)[state.index];
}

/** "Keep China and continue" when the AI's pick is selected; otherwise "Choose United Kingdom and continue". */
export function primaryLabel(q: Question, selectedId: string): string {
  const opt = q.options.find((o) => o.id === selectedId) ?? q.options[0];
  return opt.is_ai_pick ? `Keep ${opt.label} and continue` : `Choose ${opt.label} and continue`;
}

export type DragIntent = "keep" | "back" | "none";

export const DRAG_DISTANCE_PX = 80;
export const DRAG_VELOCITY_PX_PER_MS = 0.6;

/** Right swipe keeps the pick and continues; left swipe goes back. Vertical drags are scrolls and are ignored. */
export function classifyDrag(dx: number, dy: number, elapsedMs: number, canGoBack: boolean): DragIntent {
  if (Math.abs(dx) < Math.abs(dy) * 1.2) return "none";
  const velocity = Math.abs(dx) / Math.max(elapsedMs, 1);
  const far = Math.abs(dx) >= DRAG_DISTANCE_PX || (Math.abs(dx) >= 30 && velocity >= DRAG_VELOCITY_PX_PER_MS);
  if (!far) return "none";
  if (dx > 0) return "keep";
  return canGoBack ? "back" : "none";
}
