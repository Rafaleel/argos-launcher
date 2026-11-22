// A RetroAchievements rich presence line is one string: "Playing as X | 🗺️ Area | ❤️ 80 | 🧟 Zombies Killed: 11".
// Split it into a headline and small facts. Scripts differ per game, so anything that does not look like
// that shape is shown as it is.
export type Chip = { icon: string | null; label: string | null; value: string };
export type Place = { headline: string | null; chips: Chip[] };

const ICON = /^(\p{Extended_Pictographic}️?)\s*/u; // a leading emoji, with its variation selector (🗺️ and ❤️ have one)
const NUMBER = /^\d[\d:.,%/ ]*$/; // "11", "11:31.16", "80%": a value, unlike "R.P.D. 1F: Main Hall", which is a place

// No emoji is ever shown: the leading one only picks an SVG icon, and any other one in the text is dropped.
const EMOJI = /[\p{Extended_Pictographic}\u{1F3FB}-\u{1F3FF}\uFE0F\u200D\u20E3]/gu;
const clean = (s: string) => s.replace(EMOJI, "").replace(/\s{2,}/g, " ").trim();

function toChip(part: string): Chip {
  const m = ICON.exec(part);
  const text = clean(m ? part.slice(m[0].length) : part);
  const i = text.lastIndexOf(": ");
  if (i > 0 && NUMBER.test(text.slice(i + 2))) return { icon: m ? m[1] : null, label: text.slice(0, i), value: text.slice(i + 2) };
  return { icon: m ? m[1] : null, label: null, value: text };
}

export function parsePresence(message: string): Place {
  const parts = message.split(" | ").map((p) => p.trim()).filter(Boolean);
  if (parts.length < 2) return { headline: clean(message) || null, chips: [] };
  const headline = ICON.test(parts[0]) ? null : clean(parts[0]) || null;
  return { headline, chips: (headline === null ? parts : parts.slice(1)).map(toChip).filter((c) => c.value) };
}
