import { describe, expect, it } from "vitest";
import { DataTable } from "@/components/ui/data-table";
import { render } from "@/test/render";

describe("DataTable", () => {
  it("says what a column measures on a heading that does not sort, reachable by keyboard", async () => {
    const rows = [{ player_id: "1", columns: { Player: "Lopez", Rost: "44%" } }];
    const { container } = await render(<DataTable rows={rows} hints={{ Rost: "% rostered across Yahoo leagues" }} />);

    const focusable = [...container.querySelectorAll("th")].map((th) => th.querySelector("[tabindex='0']")?.textContent);
    expect(focusable).toEqual([undefined, "Rost"]);
  });
});
