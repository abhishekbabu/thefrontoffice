import { Layer } from "effect";
import { GetCaptureStatus, GetCapabilities, GetLoginState, GetSettings, ListCompetitions, ListLeagues } from "@/lib/queries/app";
import { GetTurns, OpenChat } from "@/lib/queries/chat";
import { GetFreeAgentCalls, GetFreeAgents } from "@/lib/queries/free-agents";
import { GetComparison, GetPlayer, GetPlayerTab, GetTrades, SearchPlayers } from "@/lib/queries/players";
import { GetOutlook, GetRoster, GetSeason, GetTeamRoster, GetUntouchables, ListTeams } from "@/lib/queries/teams";
import { GetDayOf, GetGamesOf, GetJudgment, GetWeek, GetWeekOf } from "@/lib/queries/week";

/** Every query's fetch, provided once by the app's root and by a test of any part of it. */
export const QueriesLayer = Layer.mergeAll(
  GetCapabilities.layer,
  ListCompetitions.layer,
  ListLeagues.layer,
  GetSettings.layer,
  GetLoginState.layer,
  GetCaptureStatus.layer,
  GetTurns.layer,
  OpenChat.layer,
  GetWeek.layer,
  GetWeekOf.layer,
  GetDayOf.layer,
  GetGamesOf.layer,
  GetJudgment.layer,
  GetRoster.layer,
  GetUntouchables.layer,
  GetSeason.layer,
  ListTeams.layer,
  GetTeamRoster.layer,
  GetOutlook.layer,
  GetTrades.layer,
  GetComparison.layer,
  SearchPlayers.layer,
  GetPlayer.layer,
  GetPlayerTab.layer,
  GetFreeAgents.layer,
  GetFreeAgentCalls.layer,
);
