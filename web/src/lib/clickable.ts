import type * as React from "react";

/**
 * What makes something other than a button open on a click and on the keys a
 * button answers to: Enter and Space, from the element itself.
 *
 * Rows open a player or a team, and each one wired its own key handler — four
 * copies, all answering Enter alone, so Space did nothing on a row announced
 * as a button. A key pressed inside the row (a control it holds) is that
 * control's, not the row's. Nothing at all where there is nothing to open, so
 * the row is not announced as something it is not.
 *
 * `role` is null on a table row, which has to stay a row to keep the table a
 * table; it is still focusable and opens the same way.
 */
export function clickable(
  open: (() => void) | undefined,
  { role = "button" }: { role?: "button" | null } = {},
) {
  if (!open) return {};
  return {
    onClick: () => open(),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.target !== e.currentTarget || (e.key !== "Enter" && e.key !== " ")) return;
      // Space would otherwise scroll the page as well.
      e.preventDefault();
      open();
    },
    tabIndex: 0,
    ...(role ? { role } : {}),
  };
}
