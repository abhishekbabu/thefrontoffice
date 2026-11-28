/**
 * Every icon the app draws, by its Lucide name (`undo-2` is Lucide's `Undo2`): what a control's props say it shows.
 *
 * A name rather than the drawing itself, so the props of a control stay
 * plain data a Schema can carry — and the set the app uses is one list.
 */
import { Schema } from "effect";
import {
  AlarmClock,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Eye,
  EyeOff,
  GitCompareArrows,
  Lock,
  LockOpen,
  Maximize2,
  Menu,
  MessageCircleQuestion,
  Minus,
  Moon,
  Plus,
  RotateCcw,
  RotateCw,
  Save,
  Search,
  SendHorizontal,
  Settings,
  Sparkles,
  Star,
  Sun,
  Trophy,
  Undo2,
  X,
} from "lucide";

export const ICONS = {
  "alarm-clock": AlarmClock,
  "arrow-down": ArrowDown,
  "arrow-left": ArrowLeft,
  "arrow-up": ArrowUp,
  "check": Check,
  "chevron-left": ChevronLeft,
  "chevron-right": ChevronRight,
  "external-link": ExternalLink,
  "eye": Eye,
  "eye-off": EyeOff,
  "git-compare-arrows": GitCompareArrows,
  "lock": Lock,
  "lock-open": LockOpen,
  "maximize-2": Maximize2,
  "menu": Menu,
  "message-circle-question": MessageCircleQuestion,
  "minus": Minus,
  "moon": Moon,
  "plus": Plus,
  "rotate-ccw": RotateCcw,
  "rotate-cw": RotateCw,
  "save": Save,
  "search": Search,
  "send-horizontal": SendHorizontal,
  "settings": Settings,
  "sparkles": Sparkles,
  "star": Star,
  "sun": Sun,
  "trophy": Trophy,
  "undo-2": Undo2,
  "x": X,
} as const;

/** The name of an icon the app draws. */
export const IconName = Schema.Literals(
  // SAFETY: `Object.keys` of a literal object lists exactly its keys.
  Object.keys(ICONS) as [keyof typeof ICONS, ...(keyof typeof ICONS)[]],
);

export type IconName = typeof IconName.Type;
