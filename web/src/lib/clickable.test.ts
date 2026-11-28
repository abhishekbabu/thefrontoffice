import { UiSchema } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { HtmlLocator, HtmlScene } from "@effect/ui/html/testing";
import { Locator } from "@effect/ui/testing";
import { assert, describe, it } from "@effect/vitest";
import { Effect, Schema } from "effect";
import { Clickable } from "@/lib/clickable";

const RowEvents = UiSchema.TaggedEnum({ Opened: {} });

const RowMessage = UiSchema.TaggedEnum({ Pressed: {} });

/** A row as a list draws one: something to open or nothing, and a field inside it or not. */
const Row = Html.component({
  name: "Row",
  props: Schema.Struct({ opens: Schema.Boolean, inside: Schema.Boolean }),
  model: Schema.Null,
  message: RowMessage,
  events: RowEvents,
}).make({
  init: () => null,
  update: { Pressed: ($) => $.emit(RowEvents.Opened()) },
  view: (h) =>
    Clickable(h, "div", h.props.opens ? RowMessage.Pressed() : undefined)
      .attr("data-testid", "row")
      .children(h.props.inside && h.input.attr("aria-label", "inside")),
});

/** A table row that opens, inside the table that keeps it one. */
const TableRow = Html.component({ name: "TableRow", model: Schema.Null, message: RowMessage }).make({
  init: () => null,
  update: { Pressed: ($) => $.model },
  view: (h) => h.table.children(h.tbody.children(Clickable(h, "tr", RowMessage.Pressed(), { role: null }))),
});

const row = Locator.testId("row");

describe("a clickable row", () => {
  it.effect("opens on Enter and on Space, as a button does", () =>
    Effect.gen(function* () {
      const s = yield* HtmlScene.make(Row, { opens: true, inside: false });

      s.keydown(row, "Enter").emitted(RowEvents.Opened());

      s.keydown(row, " ");

      // Space would otherwise also scroll the page.
      assert.isTrue(s.defaultPrevented);

      s.emitted(RowEvents.Opened());
    }),
  );

  it.effect("is announced and reachable as a button", () =>
    Effect.gen(function* () {
      const s = yield* HtmlScene.make(Row, { opens: true, inside: false });

      const { attrs } = s.get(row);

      assert.deepStrictEqual([attrs?.role, attrs?.tabindex], ["button", "0"]);
    }),
  );

  it.effect("leaves the keys of a control inside it to that control", () =>
    Effect.gen(function* () {
      const s = yield* HtmlScene.make(Row, { opens: true, inside: true });

      // Ignored: the row heard the key and sent nothing, so nothing opened.
      s.keydown(HtmlLocator.label("inside"), " ").expectIgnored();

      assert.deepStrictEqual(s.current.emitted, []);
    }),
  );

  it.effect("is not a button at all where there is nothing to open", () =>
    Effect.gen(function* () {
      const s = yield* HtmlScene.make(Row, { opens: false, inside: false });

      const { attrs } = s.get(row);

      assert.deepStrictEqual([attrs?.role, attrs?.tabindex], [undefined, undefined]);
    }),
  );

  it.effect("keeps a table row a row", () =>
    Effect.gen(function* () {
      const s = yield* HtmlScene.make(TableRow, {});

      const { attrs } = s.get(Locator.tag("tr"));

      assert.deepStrictEqual([attrs?.role, attrs?.tabindex], [undefined, "0"]);
    }),
  );
});
