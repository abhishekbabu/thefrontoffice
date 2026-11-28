/**
 * A Schema for something the server sent, typed by the generated `schema.ts`.
 *
 * Effect UI keeps its props, Models, messages and query results as Schemas so
 * it can log, compare and save them. The server's response models are already
 * typed, field for field, by the OpenAPI types `just api-types` generates, and
 * `openapi-fetch` hands them over unchecked: writing every model a second time
 * as a Schema would be a copy that drifts from the server's. This declares
 * one that passes the value through, which JSON already carries, so a model
 * gains a field with the next `just api-types` and nothing here.
 */
import { Schema } from "effect";

/** The server's own `T`, passed through as it arrived. */
export function wire<T>(): Schema.declare<T> {
  return Schema.declare((value: unknown): value is T => value !== undefined);
}
