/**
 * The app's server, as a test answers for it: requests leave through the
 * real `fetch` and are answered by MSW handlers a test installs with `use`.
 *
 * A request no handler answers fails the test rather than reaching the
 * network or quietly returning nothing, and each test's handlers are dropped
 * after it, so one test's server never answers another's.
 */
import { afterAll, afterEach, beforeAll } from "vitest";
import { setupServer } from "msw/node";

export const server = setupServer();

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
