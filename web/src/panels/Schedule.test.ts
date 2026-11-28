import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import type { ScheduleRow } from "@/lib/types";
import { Season } from "@/panels/Schedule";
import { page, showing } from "@/test/play";

const row = (label: string, extra: Partial<ScheduleRow> = {}): ScheduleRow => ({
  label,
  date: "",
  opponent: "rival",
  detail: "",
  result: "",
  outcome: null,
  is_current: false,
  marks: [],
  playoffs: false,
  ...extra,
});

const season = (rows: ScheduleRow[]) => HtmlPlay.make(showing((h) => Season(h, { rows })), {});

describe("Season", () => {
  it.layer(page(), { buildPerTest: true })("a row", (it) => {
    it.effect("names what else falls in a week beside it, in words", () =>
      Effect.gen(function* () {
        const play = yield* season([
          row("Week 10", { is_current: true, result: "119.24-103.90" }),
          row("Week 11", { marks: ["Trade deadline"] }),
        ]);

        assert.match(play.root.text(), /Week 10.*live 119\.24-103\.90.*Week 11.*Trade deadline/);
      }),
    );

    it.effect("puts the opponent's record now beside their name for a week still to be decided", () =>
      Effect.gen(function* () {
        const play = yield* season([row("Week 12", { opponent: "Rival", detail: "4-6" })]);

        assert.include(play.root.text(), "Rival4-6");

        yield* play.expect(HtmlLocator.role("button", { name: "Record now 4-6" })).toExist();
      }),
    );

    it.effect("shows no record for a week already decided, which would read as theirs at the time", () =>
      Effect.gen(function* () {
        const played = row("Week 3", { opponent: "Rival", detail: "5-5", result: "140.19-132.14", outcome: "won" });

        const play = yield* season([played]);

        assert.notInclude(play.root.text(), "5-5");

        assert.include(play.root.text(), "RivalW 140.19-132.14");
      }),
    );

    it.effect("keeps a playoff round beside the opponent once the week is decided", () =>
      Effect.gen(function* () {
        const final = row("Week 17", { opponent: "Rival", detail: "Final", playoffs: true, result: "1-2", outcome: "lost" });

        const play = yield* season([final]);

        assert.include(play.root.text(), "RivalFinalL 1-2");
      }),
    );
  });
});
