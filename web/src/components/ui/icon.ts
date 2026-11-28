/**
 * An icon from Lucide, drawn as the SVG Lucide itself would draw it.
 *
 * Lucide's framework-free package hands each icon over as data — a list of
 * shapes and their attributes — so it is drawn here with the view's own SVG
 * builders, at the size and stroke every icon in the app shares. Decorative
 * by default: the control around an icon carries its name.
 */
import type { Html } from "@effect/ui/html";
import type { IconNode } from "lucide";
import { cn } from "@/lib/utils";
import { ICONS, type IconName } from "@/components/ui/icons";

type Stroke = IconNode[number];

/** One of an icon's shapes, with the attributes its tag takes. */
function stroke<M>(h: Html.H<M>, [tag, attrs]: Stroke, index: number) {
  const at = (name: string) => (attrs[name] === undefined ? undefined : String(attrs[name]));

  switch (tag) {
    case "path":
      return h.path.key(String(index)).attrs({ d: at("d") });
    case "circle":
      return h.circle.key(String(index)).attrs({ cx: at("cx"), cy: at("cy"), r: at("r") });
    case "ellipse":
      return h.ellipse.key(String(index)).attrs({ cx: at("cx"), cy: at("cy"), rx: at("rx"), ry: at("ry") });
    case "rect":
      return h.rect.key(String(index)).attrs({
        x: at("x"),
        y: at("y"),
        width: at("width"),
        height: at("height"),
        rx: at("rx"),
        ry: at("ry"),
      });
    case "line":
      return h.line.key(String(index)).attrs({ x1: at("x1"), y1: at("y1"), x2: at("x2"), y2: at("y2") });
    case "polyline":
      return h.polyline.key(String(index)).attrs({ points: at("points") });
    case "polygon":
      return h.polygon.key(String(index)).attrs({ points: at("points") });
    default:
      return null;
  }
}

/** The icon `name`, as an inline SVG: 24 units square, stroked in the text's color. */
export function Icon<M>(
  h: Html.H<M>,
  name: IconName,
  options: { class?: string | undefined; strokeWidth?: number | undefined } = {},
) {
  const node: IconNode = ICONS[name];

  return h.svg
    .attrs({
      xmlns: "http://www.w3.org/2000/svg",
      width: "24",
      height: "24",
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": String(options.strokeWidth ?? 2),
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true",
    })
    .attr("class", cn("lucide", options.class))
    .children(node.map((part, index) => stroke(h, part, index)));
}
