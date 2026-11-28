/**
 * Putting a part of the app on a page, as the shell would host it.
 *
 * Every Play runs on Effect UI's `TestHost` — an in-memory page — with the
 * Router at an address and every query fetching through the real `fetch`,
 * which MSW answers (`test/server.ts`): a request no handler answers fails
 * the test. Each test builds its own, so no cache or address leaks into the
 * next.
 */
import { Router, type View } from "@effect/ui";
import { Html } from "@effect/ui/html";
import { TestHost } from "@effect/ui/testing";
import { Layer, Schema } from "effect";
import { QueriesLayer } from "@/lib/queries/layer";
import { AppRoute } from "@/lib/route";
import "@/test/server";

/**
 * The browser's element operations — focus, scroll, measure — doing nothing:
 * `TestHost` has no layout, and a Command that reaches for one without a
 * host dies. `scrollIntoView` is passed for a test that records the scrolls.
 */
export function elementHost(scrollIntoView: (element: Element) => void = () => {}) {
  return Layer.succeed(Html.Host, {
    focus: () => {},
    blur: () => {},
    scrollIntoView,
    measure: () => ({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
    }),
    select: () => {},
    requestSubmit: () => false,
    showPicker: () => false,
  });
}

/** The host, the Router opened `at` an address, and the app's queries. `host` replaces the element operations. */
export function page(at = "/", host = elementHost()) {
  return Layer.mergeAll(QueriesLayer, Router.memory({ routes: AppRoute, url: at }), host).pipe(
    Layer.provideMerge(TestHost.layer()),
  );
}

/**
 * A page holding nothing but what `view` draws: for a view function, which
 * is no component of its own, put on a page as a panel would put it.
 */
export function showing<R>(view: (h: Html.H<never>) => View.Content<never, R>) {
  return Html.component({
    name: "Showing",
    model: Schema.Null,
    message: Schema.Never,
  }).make({
    init: () => null,
    update: ($) => $.model,
    view: (h) => view(h),
  });
}
