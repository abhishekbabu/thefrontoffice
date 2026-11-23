import { act } from "react";
import { describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import type { League } from "@/lib/types";
import { keys } from "@/lib/queries";
import { LeagueHeader } from "@/components/league/page-header";
import { offlineClient, render, settle } from "@/test/render";
import { server } from "@/test/server";
import { competitionOf } from "@/test/leagues";

const competition = competitionOf({ key: "nba-yahoo", refreshes: true });
const league: League = { league_id: "478.l.1", name: "GM 3", detail: "", url: "" };

const refreshButton = (container: HTMLElement) =>
  container.querySelector<HTMLButtonElement>('button[aria-label^="Refresh"]');

describe("LeagueHeader", () => {
  it("refreshes the league on the server, then marks every answer about it stale and no other league's", async () => {
    const asked: string[] = [];

    server.use(
      http.post("*/refresh", ({ request }) => {
        asked.push(new URL(request.url).pathname);

        return HttpResponse.json({ dropped: 4 });
      }),
    );

    const client = offlineClient();

    client.setQueryData(keys.week(competition.key, league.league_id), {});

    client.setQueryData(keys.leagues(competition.key), [league]);

    client.setQueryData(keys.week(competition.key, "478.l.2"), {});

    const { container } = await render(<LeagueHeader competition={competition} league={league} />, client);

    await act(async () => refreshButton(container)!.click());

    await settle();

    expect(asked).toEqual(["/api/competitions/nba-yahoo/leagues/478.l.1/refresh"]);

    const stale = (key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated;

    expect([
      stale(keys.week(competition.key, league.league_id)),
      stale(keys.leagues(competition.key)),
      stale(keys.week(competition.key, "478.l.2")),
    ]).toEqual([true, true, false]);
  });

  it("says why a refresh failed in its own name", async () => {
    server.use(
      http.post("*/refresh", () =>
        HttpResponse.json({ detail: "Could not drop cached reads.", code: "error", remedy: null }, { status: 500 }),
      ),
    );

    const { container } = await render(<LeagueHeader competition={competition} league={league} />);

    await act(async () => refreshButton(container)!.click());

    await settle();

    expect(refreshButton(container)!.getAttribute("aria-label")).toContain("Could not drop cached reads.");
  });

  it("offers no refresh where the competition cannot", async () => {
    const { container } = await render(
      <LeagueHeader competition={{ ...competition, refreshes: false }} league={league} />,
    );

    expect(refreshButton(container)).toBeNull();
  });
});
