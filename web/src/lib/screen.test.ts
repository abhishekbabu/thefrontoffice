import { describe, expect, it } from "vitest";
import { onScreen, type Shown } from "./screen";

const GIBBS: Shown = { subject: { kind: "player", key: "9509" }, label: "Jahmyr Gibbs" };

describe("onScreen", () => {
  it("puts the page in view first", () => {
    const shown = onScreen({ page: "competition", competition: "nfl-sleeper", leagueId: "1", view: "team" }, [GIBBS]);

    expect(shown.map((s) => s.subject)).toEqual([
      { kind: "page", key: "team" },
      { kind: "player", key: "9509" },
    ]);
  });

  it("puts nothing of a league on screen from settings", () => {
    expect(onScreen({ page: "settings" }, [])).toEqual([]);
  });

  it("names the same thing opened twice once", () => {
    expect(onScreen({ page: "landing" }, [GIBBS, GIBBS])).toHaveLength(1);
  });
});
