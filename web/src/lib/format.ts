/**
 * Numbers as the app writes them, for the few figures the API sends as numbers.
 *
 * Most arrive as text the provider already wrote; a planning figure — a week's
 * projection, a trade's effect — arrives as a number so it can be sorted and
 * compared, and is written here, once, rather than by each card that shows it.
 * A minus sign is the typographic one, which lines up with the plus.
 */

/** "+1.6", "−0.4": a change, always signed. */
export function signed(value: number, digits = 1): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;
}

/** "+1.5 pts": a change in a probability, as percentage points. */
export function percentPoints(change: number): string {
  return `${signed(change * 100)} pts`;
}

/** "91%": a probability. */
export function percent(chance: number): string {
  return `${Math.round(chance * 100)}%`;
}
