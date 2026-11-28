/**
 * The front end's own lint rules: what neither `tsc`, Oxlint's built-in rules
 * nor the production build can see, each here because something went wrong.
 *
 * Loaded by Oxlint from `.oxlintrc.json`, as TypeScript that Node runs with
 * its types stripped, so only erasable syntax belongs here.
 */
import type { RuleTester } from "oxlint/plugins-dev";

/** A rule as Oxlint takes one; the package names the type only through its tester. */
export type Rule = Parameters<RuleTester["run"]>[1];

/** Tailwind's own palette, which a theme cannot follow. */
const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|" +
  "teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";

const RAW_COLOR = new RegExp(`\\b(text|bg|border|ring|fill|stroke|from|via|to)-(${PALETTE})-[0-9]{2,3}\\b`);

/**
 * Color comes only from semantic tokens. A raw palette utility (`text-red-500`)
 * cannot follow a palette change, and bypasses the light-dark pair every
 * token is.
 */
export const semanticColor: Rule = {
  meta: { type: "problem", docs: { description: "Color comes from semantic tokens, never Tailwind's palette." } },
  create(context) {
    const check = (node: NonNullable<Parameters<typeof context.report>[0]["node"]>, text: string) => {
      const found = RAW_COLOR.exec(text);

      if (found)
        context.report({
          node,
          message: `\`${found[0]}\`: color comes from semantic tokens (bg-card, text-muted-foreground), which follow a palette change.`,
        });
    };

    return {
      Literal: (node) => check(node, String(node.value)),
      TemplateElement: (node) => check(node, node.value.raw),
    };
  },
};

/**
 * Tooltips go through `IconButton`, `Hint`, `ExternalLink` or `Tip`
 * (components/ui/overlays/tooltip.ts). A native one cannot be styled, waits a
 * second before appearing, and never shows on keyboard focus, so a control
 * whose only label is a `title` has no label at all for anyone not using a
 * mouse.
 *
 * An element's attributes are set on its builder: `.attr("title", …)` and
 * `.attrs({ title: … })`, so those are what this catches. A `title` anywhere
 * else is no attribute — `Empty(h, { title })` is a heading, and a
 * component's `title` prop is its own — and is left alone.
 *
 * That an `IconButton` carries its `label` needs no rule: the label is a
 * required field of its props Schema, so leaving it out fails the type check.
 */
export const noNativeTitle: Rule = {
  meta: { type: "problem", docs: { description: "Use a tooltip component, not a native title attribute." } },
  create(context) {
    const message = "Use IconButton, Hint or Tip: a native title is invisible to keyboard focus and cannot be styled.";

    return {
      CallExpression(call) {
        const { callee } = call;

        if (callee.type !== "MemberExpression" || callee.computed || callee.property.type !== "Identifier") return;

        const [first] = call.arguments;

        if (first === undefined) return;

        if (callee.property.name === "attr" && first.type === "Literal" && first.value === "title")
          context.report({ node: first, message });

        if (callee.property.name === "attrs" && first.type === "ObjectExpression")
          for (const property of first.properties) {
            if (property.type !== "Property") continue;

            // `{ title }`, `{ "title": … }`; a computed key is not known to be one.
            const { key } = property;
            const named = key.type === "Identifier" ? !property.computed && key.name === "title" : false;

            if (named || (key.type === "Literal" && key.value === "title")) context.report({ node: property, message });
          }
      },
    };
  },
};

export default {
  meta: { name: "front-office" },
  rules: { "semantic-color": semanticColor, "no-native-title": noNativeTitle },
};
