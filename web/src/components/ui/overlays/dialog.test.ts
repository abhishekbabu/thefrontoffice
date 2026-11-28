import { UiSchema } from "@effect/ui";
import { BrowserHost, Html } from "@effect/ui/html";
import { HtmlLocator, HtmlPlay } from "@effect/ui/html/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect, Schema } from "effect";
import { vi } from "vitest";
import { SlideOver, SlideOverHeader } from "@/components/ui/overlays/dialog";
import { page } from "@/test/play";

const PageMessage = UiSchema.TaggedEnum({ ClickedOpen: {}, RequestedClose: {} });

/** `Closed`: the panel asked to close, once per ask. */
const PageEvents = UiSchema.TaggedEnum({ Closed: {} });

/** A page with one button that opens the panel, as a row opens a player. */
const Page = Html.component({
  name: "Page",
  model: Schema.Struct({ open: Schema.Boolean }),
  message: PageMessage,
  events: PageEvents,
}).make({
  init: () => ({ open: false }),
  update: {
    ClickedOpen: ($) => $.evolve({ open: true }),
    RequestedClose: ($) => $.evolve({ open: false }).emit(PageEvents.Closed()),
  },
  view: (h, model) =>
    h.div.attr("data-page", "reading").children(
      h.button.attr("type", "button").on("click", PageMessage.ClickedOpen()).children("Open"),
      SlideOver(h, {
        key: "panel",
        open: model.open,
        label: "Josh Allen",
        onClose: PageMessage.RequestedClose(),
        children: [
          SlideOverHeader(h, { title: ["Josh Allen"], onClose: PageMessage.RequestedClose() }),
          h.button.attr("type", "button").children("First"),
          h.button.attr("type", "button").children("Last"),
        ],
      }),
    ),
});

const dialog = HtmlLocator.role("dialog", { name: "Josh Allen" });

describe("a slide-over", () => {
  it.layer(page(), { buildPerTest: true })("on the page", (it) => {
    const opened = Effect.gen(function* () {
      const play = yield* HtmlPlay.make(Page, {});

      yield* play.click(HtmlLocator.role("button", { name: "Open" }));

      return play;
    });

    it.effect("is announced as a dialog, named for what it is about", () =>
      Effect.gen(function* () {
        const play = yield* opened;

        // A `<dialog>` in the top layer is modal to a screen reader; the kit
        // writes `aria-modal` only to say one is not.
        const { tag, attrs } = play.root.get(dialog);

        assert.deepStrictEqual([tag, attrs?.["aria-modal"]], ["dialog", undefined]);
      }),
    );

    it.effect("sits in the browser's top layer, so no page width cap or transform can reach it", () =>
      Effect.gen(function* () {
        const play = yield* opened;

        assert.strictEqual(HtmlLocator.popoverState(play.root.get(dialog)), "open");
      }),
    );

    it.effect("closes from its header's close button", () =>
      Effect.gen(function* () {
        const play = yield* opened;

        yield* play.click(HtmlLocator.role("button", { name: "Close" }));

        assert.deepStrictEqual(play.root.emitted, [PageEvents.Closed()]);

        yield* play.expect(dialog).toBeAbsent();
      }),
    );
  });

  /**
   * Focus and Escape are the kit's DOM listeners, which only a real document
   * runs: these mount on happy-dom through `BrowserHost`. happy-dom has no
   * Popover API, so the top layer's two calls are given as doing nothing —
   * what they decide (stacking above the page) is no fact a test here reads.
   */
  describe("in a document", () => {
    if (!("showPopover" in HTMLElement.prototype)) {
      Object.defineProperties(HTMLElement.prototype, {
        showPopover: { value: () => {}, configurable: true },
        hidePopover: { value: () => {}, configurable: true },
      });
    }

    const opened = Effect.gen(function* () {
      const container = document.createElement("div");

      document.body.append(container);

      yield* Effect.addFinalizer(() => Effect.sync(() => container.remove()));

      const closes: Array<typeof PageEvents.Type> = [];

      yield* BrowserHost.mountEffect(Page, {}, container, { onEmit: (event) => closes.push(event) });

      const opener = yield* Effect.promise(() => vi.waitFor(() => container.querySelector("button")!));

      opener.focus();

      opener.click();

      const panel = yield* Effect.promise(() =>
        vi.waitFor(() => {
          const found = document.querySelector<HTMLElement>("[data-drawer]");

          assert.isTrue(found?.contains(document.activeElement));

          return found;
        }),
      );

      return { opener, panel, closes };
    });

    const press = (target: Element, key: string, shiftKey = false) =>
      target.dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true }));

    it.effect("takes focus when it opens", () =>
      Effect.gen(function* () {
        const { panel } = yield* opened;

        assert.isTrue(panel.contains(document.activeElement));
      }),
    );

    it.effect("closes on Escape and hands focus back to what opened it", () =>
      Effect.gen(function* () {
        const { opener, panel, closes } = yield* opened;

        press(panel, "Escape");

        yield* Effect.promise(() => vi.waitFor(() => assert.isNull(document.querySelector("dialog"))));

        assert.deepStrictEqual(closes, [PageEvents.Closed()]);

        assert.strictEqual(document.activeElement, opener);
      }),
    );

    it.effect("keeps focus inside while it is open", () =>
      Effect.gen(function* () {
        const { panel } = yield* opened;

        const buttons = [...panel.querySelectorAll<HTMLElement>("button")];
        const first = buttons.at(0)!;
        const last = buttons.at(-1)!;

        last.focus();

        press(last, "Tab");

        yield* Effect.promise(() => vi.waitFor(() => assert.strictEqual(document.activeElement, first)));

        press(first, "Tab", true);

        yield* Effect.promise(() => vi.waitFor(() => assert.strictEqual(document.activeElement, last)));
      }),
    );
  });
});
