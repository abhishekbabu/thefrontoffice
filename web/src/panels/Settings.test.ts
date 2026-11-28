import { HtmlLocator, HtmlPlay, HtmlScene } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect } from "effect";
import { http, HttpResponse } from "msw";
import type { CaptureStatus, Setting, SettingsGroup } from "@/lib/types";
import { SettingsEvents, SettingsPanel } from "@/panels/Settings";
import { SetBookmark } from "@/panels/settings-yahoo";
import { page } from "@/test/play";
import { server } from "@/test/server";

const group = (title: string, section: SettingsGroup["section"], platform = "", settings: Setting[] = []): SettingsGroup => ({
  title,
  note: "",
  section,
  platform,
  switch: "",
  modes: {},
  settings,
});

const YAHOO = group("NBA on Yahoo", "platforms", "yahoo");
const YAHOO_CARD = HtmlLocator.role("group", { name: "NBA on Yahoo" });

type Play = HtmlPlay.HtmlPlay<unknown, unknown, unknown, unknown>;

/** Every element of `locator` on the page, as text. */
const texts = (play: { root: { all: Play["root"]["all"] } }, locator: Locator.Locator) =>
  play.root.all(locator).map((node) => Locator.textOf(node));

/** Settings showing `groups`, with Yahoo's reading `status`. */
const settingsWith = (status: CaptureStatus, groups: SettingsGroup[] = [YAHOO]) =>
  Effect.gen(function* () {
    server.use(
      http.get("*/api/settings", () => HttpResponse.json(groups)),
      http.get("*/api/platforms/yahoo/capture", () => HttpResponse.json(status)),
    );

    const play = yield* HtmlPlay.make(SettingsPanel, {});

    return { play, card: texts(play, YAHOO_CARD).join("") };
  });

const NEVER_SYNCED: CaptureStatus = { active: true, synced_at: null, leagues: [], session: null };

describe("Yahoo status", () => {
  it.layer(page(), { buildPerTest: true })("in the Yahoo card", (it) => {
    it.effect("is not shown without a Yahoo group", () =>
      Effect.gen(function* () {
        const { play } = yield* settingsWith(NEVER_SYNCED, []);

        assert.notInclude(play.root.text(), "Sync Yahoo");
      }),
    );

    it.effect("says it has never run before the first sync", () =>
      Effect.gen(function* () {
        const { card } = yield* settingsWith(NEVER_SYNCED);

        assert.include(card, "Never synced");
      }),
    );

    it.effect("says when it last ran, and how many leagues it holds, in its status", () =>
      Effect.gen(function* () {
        const synced = new Date();

        synced.setHours(9, 5);

        const { card } = yield* settingsWith({
          active: true,
          synced_at: synced.toISOString(),
          leagues: ["Hoops", "Dunks"],
          session: null,
        });

        assert.match(card, /2 leagues · last synced 0?9:05/);

        assert.notInclude(card, "Hoops");
      }),
    );

    it.effect("says how to copy the session cookie, and where it goes, while read with one", () =>
      Effect.gen(function* () {
        const { card } = yield* settingsWith({
          active: false,
          synced_at: null,
          leagues: [],
          session: { fetched_at: null, expired: false },
        });

        assert.include(card, "pub-api-ro.fantasysports.yahoo.com");

        assert.include(card, "YAHOO_SESSION_COOKIE");
      }),
    );

    it.effect("read with the session, says when it last fetched", () =>
      Effect.gen(function* () {
        const fetched = new Date();

        fetched.setHours(9, 5);

        const { card } = yield* settingsWith({
          active: false,
          synced_at: null,
          leagues: [],
          session: { fetched_at: fetched.toISOString(), expired: false },
        });

        assert.match(card, /Last fetched 0?9:05/);
      }),
    );

    it.effect("read with the session, says it expired in words", () =>
      Effect.gen(function* () {
        const { card } = yield* settingsWith({
          active: false,
          synced_at: null,
          leagues: [],
          session: { fetched_at: null, expired: true },
        });

        assert.include(card, "Session expired");
      }),
    );
  });

  // The bookmark's `javascript:` link is set on the element by a mount, which
  // no test host runs: a scene says what the mount is given.
  it.effect("offers the bookmark, built to call back the app it is served from", () =>
    Effect.gen(function* () {
      const s = yield* HtmlScene.make(SettingsPanel, {});

      s.loaded("settings", [YAHOO]).loaded("capture", NEVER_SYNCED).expectMount(SetBookmark({ app: window.location.origin }));

      assert.isNotNull(s.query(HtmlLocator.role("link", { name: "Sync Yahoo" })));
    }).pipe(Effect.scoped),
  );
});

function setting(key: string, kind: Setting["kind"], value: string, choices: string[] = [], mode = ""): Setting {
  return {
    key,
    field: key.toLowerCase(),
    secret: false,
    present: true,
    kind,
    choices,
    value,
    shadowed: false,
    effective: value,
    mode,
    hint: "",
  };
}

const GROUPS: SettingsGroup[] = [
  group("NBA on Yahoo", "platforms", "yahoo", [
    setting("YAHOO_SOURCE", "choice", "oauth", ["oauth", "browser", "session"]),
    setting("LOG_LEVEL", "choice", "INFO", ["DEBUG", "INFO", "WARNING"]),
    setting("DEBUG_MODE", "boolean", "false"),
  ]),
];

/** Settings with the fixed-value fields, and every PUT the page sends recorded. */
const fixedValues = Effect.gen(function* () {
  const saved: Record<string, string>[] = [];
  const capture: CaptureStatus = { active: false, synced_at: null, leagues: [], session: null };

  server.use(
    http.get("*/api/settings", () => HttpResponse.json(GROUPS)),
    http.get("*/api/platforms/yahoo/capture", () => HttpResponse.json(capture)),
    http.put("*/api/settings", async ({ request }) => {
      // SAFETY: the settings page PUTs `{ values }`, which the assertions on `saved` read back.
      saved.push(((await request.json()) as { values: Record<string, string> }).values);

      return HttpResponse.json(GROUPS);
    }),
  );

  const play = yield* HtmlPlay.make(SettingsPanel, {});

  const chips = (key: string) => texts(play, Locator.inside(HtmlLocator.role("group", { name: key }), HtmlLocator.role("button")));

  const pressed = (key: string) =>
    texts(play, Locator.inside(HtmlLocator.role("group", { name: key }), Locator.attr("aria-pressed", "true")));

  const chip = (key: string, text: string) =>
    play.click(Locator.inside(HtmlLocator.role("group", { name: key }), HtmlLocator.role("button", { name: text })));

  return {
    play,
    saved,
    chips,
    pressed,
    chip,
    save: HtmlLocator.role("button", { name: /^Save/ }),
    discard: HtmlLocator.role("button", { name: /^Discard/ }),
    status: HtmlLocator.role("status"),
  };
});

describe("Fixed-value settings", () => {
  it.layer(page(), { buildPerTest: true })("chips", (it) => {
    it.effect("offers each choice as a chip, with the stored one pressed", () =>
      Effect.gen(function* () {
        const { chips, pressed } = yield* fixedValues;

        assert.deepStrictEqual(chips("LOG_LEVEL"), ["DEBUG", "INFO", "WARNING"]);

        assert.deepStrictEqual(pressed("LOG_LEVEL"), ["INFO"]);

        assert.deepStrictEqual(pressed("YAHOO_SOURCE"), ["oauth"]);

        assert.lengthOf(chips("DEBUG_MODE"), 2);
      }),
    );

    it.effect("saves the pressed choice, and a boolean as .env spells it", () =>
      Effect.gen(function* () {
        const { play, saved, pressed, chip, save } = yield* fixedValues;

        yield* chip("YAHOO_SOURCE", "browser");

        yield* chip("DEBUG_MODE", "On");

        assert.deepStrictEqual(pressed("YAHOO_SOURCE"), ["browser"]);

        yield* play.click(save);

        assert.deepStrictEqual(saved, [{ YAHOO_SOURCE: "browser", DEBUG_MODE: "true" }]);
      }),
    );

    it.effect("has nothing to save once a choice is pressed back to the stored one", () =>
      Effect.gen(function* () {
        const { play, chip, save } = yield* fixedValues;

        yield* chip("LOG_LEVEL", "DEBUG");

        yield* play.expect(save).toHaveAttribute("disabled", false);

        yield* chip("LOG_LEVEL", "INFO");

        yield* play.expect(save).toBeAbsent();
      }),
    );
  });
});

describe("Saving", () => {
  it.layer(page(), { buildPerTest: true })("the header", (it) => {
    it.effect("says how many changes wait, and that they were saved", () =>
      Effect.gen(function* () {
        const { play, chip, save, status } = yield* fixedValues;

        yield* chip("LOG_LEVEL", "DEBUG");

        yield* play.expect(status).toHaveText("1 unsaved");

        yield* play.click(save);

        yield* play.expect(status).toHaveText("Saved");
      }),
    );

    it.effect("discards every unsaved change at once", () =>
      Effect.gen(function* () {
        const { play, chip, discard, pressed, saved, status } = yield* fixedValues;

        yield* chip("LOG_LEVEL", "DEBUG");

        yield* chip("YAHOO_SOURCE", "session");

        yield* play.click(discard);

        assert.deepStrictEqual(pressed("LOG_LEVEL"), ["INFO"]);

        assert.deepStrictEqual(pressed("YAHOO_SOURCE"), ["oauth"]);

        yield* play.expect(status).toHaveText("");

        yield* play.expect(discard).toBeAbsent();

        assert.deepStrictEqual(saved, []);
      }),
    );

    it.effect("asks to go back from its back button", () =>
      Effect.gen(function* () {
        const { play } = yield* fixedValues;

        yield* play.click(HtmlLocator.role("button", { name: "Back" }));

        assert.deepStrictEqual(play.root.emitted, [SettingsEvents.RequestedBack()]);
      }),
    );
  });
});

describe("Layout", () => {
  it.layer(page(), { buildPerTest: true })("sections", (it) => {
    it.effect("runs from the accounts read to what is rarely touched", () =>
      Effect.gen(function* () {
        const { play } = yield* settingsWith({ active: false, synced_at: null, leagues: [], session: null }, [
          YAHOO,
          group("Model providers", "ai"),
          group("Tracing", "advanced"),
        ]);

        assert.deepStrictEqual(texts(play, HtmlLocator.role("heading", { level: 2 })), [
          "Platforms",
          "AI",
          "Appearance",
          "Advanced",
        ]);
      }),
    );
  });
});

describe("A group read more than one way", () => {
  const SWITCHED: SettingsGroup = {
    ...group("NBA on Yahoo", "platforms", "yahoo", [
      setting("YAHOO_SOURCE", "choice", "session", ["oauth", "browser", "session"]),
      setting("YAHOO_SESSION_COOKIE", "text", "", [], "session"),
      setting("YAHOO_CLIENT_ID", "text", "", [], "oauth"),
      { ...setting("YAHOO_MAX_WEEKLY_ADDS", "integer", "3"), hint: "fallback only" },
    ]),
    switch: "YAHOO_SOURCE",
    modes: { oauth: "needs a developer app", browser: "run the bookmark", session: "reads your cookie" },
  };

  const session: CaptureStatus = { active: false, synced_at: null, leagues: [], session: { fetched_at: null, expired: false } };

  const switched = Effect.gen(function* () {
    const { play } = yield* settingsWith(session, [SWITCHED]);

    const card = () => play.root.all(YAHOO_CARD)[0] ?? {};

    const other = () =>
      Locator.all(card(), Locator.tag("details")).find((details) => Locator.textOf(details).startsWith("Other methods"));

    const keys = (root: Locator.Node | undefined) =>
      root === undefined ? [] : Locator.all(root, Locator.tag("code")).map((code) => Locator.textOf(code));

    // Spelled out in the card, rather than folded under "Other methods".
    const shown = (key: string) =>
      keys(card()).filter((text) => text === key).length > keys(other()).filter((text) => text === key).length;

    return { play, card: () => Locator.textOf(card()), other: () => keys(other()), shown };
  });

  it.layer(page(), { buildPerTest: true })("the way chosen", (it) => {
    it.effect("spells out only the way chosen, and folds the others' fields away", () =>
      Effect.gen(function* () {
        const { card, other, shown } = yield* switched;

        assert.include(card(), "reads your cookie");

        assert.notInclude(card(), "needs a developer app");

        assert.isTrue(shown("YAHOO_SESSION_COOKIE"));

        assert.isFalse(shown("YAHOO_CLIENT_ID"));

        assert.include(other(), "YAHOO_CLIENT_ID");
      }),
    );

    it.effect("shows what a way needs as soon as it is pressed, before it is saved", () =>
      Effect.gen(function* () {
        const { play, card, other, shown } = yield* switched;

        yield* play.click(Locator.inside(HtmlLocator.role("group", { name: "YAHOO_SOURCE" }), HtmlLocator.role("button", { name: "oauth" })));

        assert.include(card(), "needs a developer app");

        assert.isTrue(shown("YAHOO_CLIENT_ID"));

        assert.include(other(), "YAHOO_SESSION_COOKIE");
      }),
    );

    it.effect("says what a setting does where it carries a hint", () =>
      Effect.gen(function* () {
        const { card } = yield* switched;

        assert.include(card(), "fallback only");
      }),
    );
  });
});
