import { describe, expect, it } from "vitest";
import { failure, isExpired, leagueApi } from "@/lib/api";

describe("reading a failed response", () => {
  it("carries the server's sentence, code and remedy as they are", () => {
    const remedy = { action: "retry", label: "Try again", url: "", platform: "", command: "" } as const;
    const error = failure({ detail: "Sleeper is not responding.", code: "platform_unavailable", remedy }, "503");

    expect([error.message, error.code, error.remedy]).toEqual(["Sleeper is not responding.", "platform_unavailable", remedy]);
  });

  it("names the condition a page acts on, such as a conversation the server no longer holds", () => {
    expect(failure({ detail: "Expired.", code: "chat_expired", remedy: null }, "404 Not Found").code).toBe("chat_expired");
  });

  it("says the server did not answer where nothing it sent came back", () => {
    const error = failure(null, "502 Bad Gateway");

    expect(error.code).toBe("error");
    expect(error.message).toContain("502 Bad Gateway");
  });
});

/** The paths `ask` requested, each answered with an empty list. */
async function pathsAsked(ask: () => Promise<unknown>): Promise<string[]> {
  const asked: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (path: string) => {
    asked.push(path);
    return new Response("[]");
  }) as typeof fetch;
  try {
    await ask();
  } finally {
    globalThis.fetch = original;
  }
  return asked;
}

describe("addressing a league", () => {
  it("encodes every segment, so an id with a slash in it stays one segment", async () => {
    expect(await pathsAsked(() => leagueApi("nfl-sleeper", "a/b").teamRoster("t 1"))).toEqual([
      "/api/nfl-sleeper/leagues/a%2Fb/teams/t%201/roster",
    ]);
  });

  it("asks a roster in the order clicked, leaving out what the server defaults", async () => {
    const league = leagueApi("nfl-sleeper", "1");
    const asked = await pathsAsked(async () => {
      await league.roster({ sort: "Proj", descending: false });
      await league.roster({ sort: "", descending: true });
    });
    expect(asked).toEqual([
      "/api/nfl-sleeper/leagues/1/roster?sort=Proj&descending=false",
      "/api/nfl-sleeper/leagues/1/roster?descending=true",
    ]);
  });
});

describe("a conversation the server no longer holds", () => {
  it("is told apart by its code, so the page opens a fresh one instead of asking the old id forever", () => {
    expect(isExpired(failure({ detail: "Expired.", code: "chat_expired", remedy: null }, "404"))).toBe(true);
    expect(isExpired(failure({ detail: "No such league.", code: "not_found", remedy: null }, "404"))).toBe(false);
    expect(isExpired(new Error("chat_expired"))).toBe(false);
  });
});
