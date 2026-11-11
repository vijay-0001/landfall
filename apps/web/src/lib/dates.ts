// Dates are ISO (YYYY-MM-DD) and always rendered in UTC so server and browser agree.
// There is deliberately no "now": the API supplies today's date, days_left and as_of.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = [
  "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December",
];

function parts(iso: string): { y: number; m: number; d: number } {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) throw new Error(`Not an ISO date: ${iso}`);
  return { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]) };
}

/** "29 Oct 2026" */
export function formatDate(iso: string): string {
  const { y, m, d } = parts(iso);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** "Oct 2026" */
export function formatMonthYear(iso: string): string {
  const { y, m } = parts(iso);
  return `${MONTHS[m - 1]} ${y}`;
}

/** "October 2026" */
export function formatMonthYearLong(iso: string): string {
  const { y, m } = parts(iso);
  return `${MONTHS_LONG[m - 1]} ${y}`;
}

/** "10 Nov" */
export function formatDayMonth(iso: string): string {
  const { m, d } = parts(iso);
  return `${d} ${MONTHS[m - 1]}`;
}

/** Whole days since the epoch for an ISO date, for chart x positions. */
export function dayNumber(iso: string): number {
  const { y, m, d } = parts(iso);
  return Math.round(Date.UTC(y, m - 1, d) / 86_400_000);
}

/** "02:04" in UTC from an ISO timestamp. */
export function formatTimeUtc(ts: string): string {
  const d = new Date(ts);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** "29 Oct 2026, 02:04 UTC" */
export function formatDateTimeUtc(ts: string): string {
  const d = new Date(ts);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${formatTimeUtc(ts)} UTC`;
}
