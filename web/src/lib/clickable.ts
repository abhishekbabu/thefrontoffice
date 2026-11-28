import type { Html } from "@effect/ui/html";

/**
 * What makes something other than a button open on a click and on the keys a
 * button answers to: Enter and Space, from the element itself.
 *
 * Rows open a player or a team, and each one wired its own key handler — four
 * copies, all answering Enter alone, so Space did nothing on a row announced
 * as a button. A key pressed inside the row is the control's it was pressed
 * in: a field types it, and a button (`components/ui/controls/button.ts`)
 * holds its own keys. Nothing at all where there is nothing to open, so the
 * row is not announced as something it is not.
 *
 * `role` is null on a table row, which has to stay a row to keep the table a
 * table; it is still focusable and opens the same way.
 */
export function Clickable<M, K extends "div" | "tr" | "li">(
  h: Html.H<M>,
  tag: K,
  open: M | undefined,
  { role = "button" }: { role?: "button" | null } = {},
) {
  const element = h[tag].attrs({});

  if (open === undefined) return element;

  return element
    .attrs({ tabindex: "0", role: role ?? undefined })
    .on("click", open)
    .on(
      "keydown",
      ({ key, editable }) => (!editable && (key === "Enter" || key === " ") ? open : undefined),
      // Space would otherwise scroll the page as well.
      { preventDefault: true },
    );
}
