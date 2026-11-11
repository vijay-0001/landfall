import type { TimeMachinePoint } from "@/lib/api/models";
import { toMinor } from "@/lib/money";

const ts = (iso: string) => Date.parse(`${iso}T00:00:00Z`);

export interface ChartGeometry {
  past: string;
  future: string;
  dots: { x: number; y: number; label: string | null }[];
  marker: { x: number; y: number };
  yTicks: { y: number; label: number }[];
  xTicks: { x: number; label: string }[];
}

/** Pure step-chart geometry for the share image (server rendered SVG; no client JS). */
export function stepGeometry(points: TimeMachinePoint[], selectedIdx: number, w: number, h: number, pad = { l: 64, r: 24, t: 20, b: 36 }): ChartGeometry {
  const vals = points.map((p) => toMinor(p.buyer_total.amount) / 100);
  const lo = Math.floor((Math.min(...vals) - 1) / 5) * 5;
  const hi = Math.ceil((Math.max(...vals) + 1) / 5) * 5;
  const t0 = ts(points[0].date), t1 = ts(points[points.length - 1].date);
  const X = (iso: string) => pad.l + ((ts(iso) - t0) / Math.max(t1 - t0, 1)) * (w - pad.l - pad.r);
  const Y = (v: number) => pad.t + (1 - (v - lo) / Math.max(hi - lo, 1)) * (h - pad.t - pad.b);
  const seg = (list: TimeMachinePoint[]) => list.reduce((d, p, i) => {
    const x = X(p.date), y = Y(toMinor(p.buyer_total.amount) / 100);
    return i === 0 ? `M${x.toFixed(1)} ${y.toFixed(1)}` : `${d} H${x.toFixed(1)} V${y.toFixed(1)}`;
  }, "");
  const firstFuture = points.findIndex((p) => p.is_future);
  const pastPts = firstFuture === -1 ? points : points.slice(0, Math.max(firstFuture, 1));
  const futurePts = firstFuture === -1 ? [] : points.slice(Math.max(firstFuture - 1, 0));
  const yTicks = Array.from({ length: Math.floor((hi - lo) / 5) + 1 }, (_, i) => ({ y: Y(lo + 5 * i), label: lo + 5 * i }));
  const xTicks = points.filter((p) => /-(01|07)-01$/.test(p.date)).map((p) => ({ x: X(p.date), label: new Date(`${p.date}T00:00:00Z`).toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" }) }));
  const sel = points[selectedIdx];
  return {
    past: seg(pastPts), future: futurePts.length ? seg(futurePts) : "",
    dots: points.filter((p) => p.is_change_date).map((p) => ({ x: X(p.date), y: Y(toMinor(p.buyer_total.amount) / 100), label: p.label ?? null })),
    marker: { x: X(sel.date), y: Y(toMinor(sel.buyer_total.amount) / 100) },
    yTicks, xTicks,
  };
}

/** Index of the last point on or before an ISO date (the slider snaps to points). */
export function indexOnOrBefore(points: TimeMachinePoint[], iso: string): number {
  let best = 0;
  for (let i = 0; i < points.length; i++) if (points[i].date <= iso) best = i;
  return best;
}
