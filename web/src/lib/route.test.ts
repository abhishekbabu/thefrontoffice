import { describe, expect, it } from "vitest";
import { href, parse } from "./route";
import { DEFAULT_VIEW, VIEWS } from "./views";

describe("parse", () => {
  it("reads the landing page", () => {
    expect(parse("/")).toEqual({ page: "landing" });
  });

  it("reads settings rather than a competition of that name", () => {
    expect(parse("/settings")).toEqual({ page: "settings" });
  });

  it("reads a competition with no league yet", () => {
    expect(parse("/nfl-sleeper")).toEqual({
      page: "competition",
      competition: "nfl-sleeper",
      leagueId: null,
      view: DEFAULT_VIEW,
    });
  });

  it("defaults the view when the address leaves it off", () => {
    expect(parse("/nfl-sleeper/123")).toMatchObject({ leagueId: "123", view: DEFAULT_VIEW });
  });

  it("falls back rather than trusting a view nobody wrote", () => {
    expect(parse("/nfl-sleeper/123/nonsense")).toMatchObject({ view: DEFAULT_VIEW });
  });

  it("treats a path too deep to be a page as the landing page", () => {
    expect(parse("/a/b/c/d")).toEqual({ page: "landing" });
  });
});

describe("href", () => {
  it("leaves the default view off, so both spellings are one page", () => {
    expect(href("nfl-sleeper", "123")).toBe("/nfl-sleeper/123");
    expect(href("nfl-sleeper", "123", DEFAULT_VIEW)).toBe("/nfl-sleeper/123");
  });

  // The point of keeping these two in one module: a link that parses back to
  // something else is the failure this pairing exists to make impossible.
  it("round-trips through parse for every view", () => {
    for (const view of VIEWS) {
      expect(parse(href("nfl-sleeper", "123", view))).toEqual({
        page: "competition",
        competition: "nfl-sleeper",
        leagueId: "123",
        view,
      });
    }
  });
});
