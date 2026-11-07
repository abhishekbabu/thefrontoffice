import { describe, expect, it } from "vitest";
import { failureMessage, leagueApi } from "@/lib/api";

describe("reading a failed response", () => {
  it("shows the server's own sentence as it is", () => {
    expect(failureMessage("Unknown competition 'x'.", "404 Not Found")).toBe("Unknown competition 'x'.");
  });

  it("reads a refused request's field list as words, not as an object", () => {
    const detail = [
      { loc: ["query", "limit"], msg: "Input should be less than or equal to 200", type: "less_than_equal" },
      { loc: ["query", "offset"], msg: "Input should be greater than or equal to 0", type: "greater_than_equal" },
    ];
    expect(failureMessage(detail, "422 Unprocessable Entity")).toBe(
      "Input should be less than or equal to 200; Input should be greater than or equal to 0",
    );
  });

  it("falls back to the status line where the body says nothing", () => {
    expect(failureMessage(undefined, "500 Internal Server Error")).toBe("500 Internal Server Error");
  });
});

describe("addressing a league", () => {
  it("encodes every segment, so an id with a slash in it stays one segment", async () => {
    const asked: string[] = [];
    const original = globalThis.fetch;
    globalThis.fetch = (async (path: string) => {
      asked.push(path);
      return new Response("[]");
    }) as typeof fetch;
    try {
      await leagueApi("nfl-sleeper", "a/b").teamRoster("t 1");
    } finally {
      globalThis.fetch = original;
    }
    expect(asked).toEqual(["/api/nfl-sleeper/leagues/a%2Fb/teams/t%201/roster"]);
  });
});
