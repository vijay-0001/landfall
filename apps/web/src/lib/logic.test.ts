import { notIncludedHint } from "@/components/decision";
import { isNotCovered, originLabel, statusOf } from "@/components/ui";
import { describe, expect, it } from "vitest";
import type { Product, Question } from "@/lib/api/models";
import { bulkBlockReason, eligibleIds, sanitizeSelection } from "./bulk";
import { addMoney, formatMoney, toMinor } from "./money";
import { classifyDrag, initSwipe, limitQuestions, primaryLabel, swipeReducer } from "./swipe";

const p = (over: Partial<Product>): Product => ({
  id: "x", shop_id: "s", title: "t", description: "d", prices: { USD: "1.00" }, category: "ceramics", review_status: "not_reviewed",
  band: "high", question_count: 0, origin_uncertain: false, listing_changed: false, ...over,
});

describe("money (strings, never floats, never converted)", () => {
  it("parses and formats exactly", () => {
    expect(toMinor("7.60")).toBe(760);
    expect(formatMoney({ amount: "59.60", currency: "USD" })).toBe("$59.60");
    expect(formatMoney({ amount: "3.90", currency: "USD" }, { signed: true })).toBe("+$3.90");
    expect(addMoney({ amount: "38.00", currency: "USD" }, { amount: "14.00", currency: "USD" }, { amount: "7.60", currency: "USD" }).amount).toBe("59.60");
  });
  it("refuses to add across currencies", () => {
    expect(() => addMoney({ amount: "1.00", currency: "USD" }, { amount: "1.00", currency: "GBP" })).toThrow(/never converts/);
  });
});

describe("bulk accept is for the High band only", () => {
  it("blocks Check, Ask, open questions, reviewed and paused rows", () => {
    expect(bulkBlockReason(p({}))).toBeNull();
    expect(bulkBlockReason(p({ band: "check" }))).not.toBeNull();
    expect(bulkBlockReason(p({ band: "ask" }))).not.toBeNull();
    expect(bulkBlockReason(p({ question_count: 1 }))).not.toBeNull();
    expect(bulkBlockReason(p({ review_status: "accepted" }))).not.toBeNull();
    expect(bulkBlockReason(p({ paused_reason: "regulated" }))).not.toBeNull();
  });
  it("drops tampered selections", () => {
    const list = [p({ id: "a" }), p({ id: "b", band: "ask" })];
    expect(eligibleIds(list)).toEqual(["a"]);
    expect(sanitizeSelection(["a", "b", "zzz"], list)).toEqual(["a"]);
  });
});

const q = (id: string): Question => ({ id, trigger: "T2", text: id, options: [{ id: id + "1", label: "A", is_ai_pick: true }, { id: id + "2", label: "B", is_ai_pick: false }] });

describe("questions: at most 4, same on phone and desktop", () => {
  it("limits to four", () => expect(limitQuestions(["1", "2", "3", "4", "5", "6"].map(q))).toHaveLength(4));
  it("steps through, keeps the AI pick, goes back", () => {
    const qs = [q("a"), q("b")];
    let s = initSwipe(qs);
    expect(s.selected).toEqual({ a: "a1", b: "b1" });
    s = swipeReducer(s, { type: "select", questionId: "a", optionId: "a2" }, qs);
    s = swipeReducer(s, { type: "next" }, qs);
    expect(s.index).toBe(1);
    s = swipeReducer(s, { type: "next" }, qs);
    expect(s.done).toBe(true);
    s = swipeReducer(s, { type: "back" }, qs);
    expect(s.done).toBe(false);
    expect(primaryLabel(qs[0], "a1")).toBe("Keep A and continue");
    expect(primaryLabel(qs[0], "a2")).toBe("Choose B and continue");
  });
  it("classifies drags: right keeps, left goes back, vertical is a scroll", () => {
    expect(classifyDrag(120, 5, 300, true)).toBe("keep");
    expect(classifyDrag(-120, 5, 300, true)).toBe("back");
    expect(classifyDrag(-120, 5, 300, false)).toBe("none");
    expect(classifyDrag(10, 200, 300, true)).toBe("none");
  });
});

describe("statusOf", () => {
  const base = { id: "p", shop_id: "s", title: "t", description: "d", prices: { GBP: "1", USD: "1", EUR: "1" }, category: "ceramics", review_status: "not_reviewed", question_count: 0, origin_uncertain: false } as never;
  it("never says Recommended for a product that has no recommendation", () => {
    expect(statusOf({ ...(base as object), band: null } as never).label).toBe("No recommendation yet");
    expect(statusOf({ ...(base as object), band: "high" } as never).label).toBe("Recommended");
    expect(statusOf({ ...(base as object), band: "high", listing_changed: true } as never).label).toBe("Changed: review again");
  });
});

describe("origin and coverage labels", () => {
  it("names any country, not only the register's, and never shows the code for an uncovered product as a code", () => {
    expect(originLabel("IS")).toBe("Iceland");
    expect(originLabel("other")).toBe("A country Landfall does not price yet");
    expect(originLabel("CN", true)).toBe("China?");
    expect(originLabel(null)).toBe("–");
    expect(isNotCovered("none")).toBe(true);
    expect(isNotCovered("6912.00.44.00")).toBe(false);
  });
});

describe("notIncludedHint", () => {
  it("tells the seller what Not included means for each reason", () => {
    expect(notIncludedHint("No priced national line for this code yet")).toMatch(/cannot price duty here yet/);
    expect(notIncludedHint("The rate register does not cover this origin yet")).toMatch(/does not price goods from this origin yet/);
    expect(notIncludedHint("Order value is above the low-value limit for flat-duty entry")).toMatch(/check out normally/);
    expect(notIncludedHint(null)).toMatch(/check out normally/);
  });
});
