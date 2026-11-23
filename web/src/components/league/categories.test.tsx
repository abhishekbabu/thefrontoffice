import { describe, expect, it } from "vitest";
import { render } from "@/test/render";
import { Categories } from "@/components/league/categories";

describe("Categories", () => {
  it("says who leads each category in words, and a dash where nobody does yet", async () => {
    const { container } = await render(
      <Categories
        lines={[
          { name: "PTS", mine: "520", theirs: "498", lead: "mine", win: null },
          { name: "BLK", mine: "12", theirs: "17", lead: "theirs", win: null },
          { name: "TO", mine: "-", theirs: "-", lead: null, win: null },
        ]}
      />,
    );

    const rows = [...container.querySelectorAll("[class*=border-b]")].map((r) => r.textContent ?? "");

    expect(rows.find((r) => r.startsWith("PTS"))).toMatch(/You$/);
    expect(rows.find((r) => r.startsWith("BLK"))).toMatch(/Them$/);
    expect(rows.find((r) => r.startsWith("TO"))).toMatch(/—$/);
    expect(container.textContent).not.toContain("Win");
    // The heading says "Them" rather than a name the column truncates.
    expect(container.querySelector("thead")?.textContent).toBe("CatYouThemLeads");
  });

  it("gives each category's chance of winning where the week is forecast", async () => {
    const { container } = await render(
      <Categories
        lines={[
          { name: "PTS", mine: "520", theirs: "498", lead: "mine", win: 0.734 },
          { name: "DD", mine: "1", theirs: "0", lead: "mine", win: null },
        ]}
      />,
    );

    const rows = [...container.querySelectorAll("[class*=border-b]")].map((r) => r.textContent ?? "");

    expect(rows.find((r) => r.startsWith("PTS"))).toMatch(/You73%$/);
    expect(rows.find((r) => r.startsWith("DD"))).toMatch(/You—$/);
  });
});
