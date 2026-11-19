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
    const check = (node: NonNullable<Parameters<typeof context.report>[0]["node"]>, text: unknown) => {
      const found = typeof text === "string" ? RAW_COLOR.exec(text) : null;
      if (found)
        context.report({
          node,
          message: `\`${found[0]}\`: color comes from semantic tokens (bg-card, text-muted-foreground), which follow a palette change.`,
        });
    };
    return {
      Literal: (node) => check(node, node.value),
      TemplateElement: (node) => check(node, node.value.raw),
    };
  },
};

/**
 * Tooltips go through components/ui/tooltip.tsx. A native one cannot be
 * styled, waits a second before appearing, and never shows on keyboard focus,
 * so a control whose only label is a `title` has no label at all for anyone
 * not using a mouse. Host elements only: `title` is a legitimate prop on our
 * own components, and <Empty title="..."> is not a tooltip.
 */
export const noNativeTitle: Rule = {
  meta: { type: "problem", docs: { description: "Use <Tooltip>, not a native title attribute." } },
  create(context) {
    return {
      JSXOpeningElement(element) {
        if (element.name.type !== "JSXIdentifier" || !/^[a-z]/.test(element.name.name)) return;
        for (const attribute of element.attributes) {
          if (attribute.type === "JSXAttribute" && attribute.name.type === "JSXIdentifier" && attribute.name.name === "title")
            context.report({
              node: attribute,
              message: "Use <Tooltip>: a native title is invisible to keyboard focus and cannot be styled.",
            });
        }
      },
    };
  },
};

export default {
  meta: { name: "front-office" },
  rules: { "semantic-color": semanticColor, "no-native-title": noNativeTitle },
};
