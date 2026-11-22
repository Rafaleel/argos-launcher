// A RetroAchievements rich presence line is one string: "Playing as X | 🗺️ Area | ❤️ 80 | 🧟 Zombies Killed: 11".
// Split it into a headline and small facts. Scripts differ per game, so anything that does not look like
// that shape is shown as it is.
export type Chip = { icon: string | null; label: string | null; value: string };
export type Place = { headline: string | null; chips: Chip[] };

const ICON = /^(\p{Extended_Pictographic}️?)\s*/u; // a leading emoji, with its variation selector (🗺️ and ❤️ have one)
const NUMBER = /^\d[\d:.,%/ ]*$/; // "11", "11:31.16", "80%": a value, unlike "R.P.D. 1F: Main Hall", which is a place

function toChip(part: string): Chip {
  const m = ICON.exec(part);
  const text = m ? part.slice(m[0].length) : part;
  const i = text.lastIndexOf(": ");
  if (i > 0 && NUMBER.test(text.slice(i + 2))) return { icon: m ? m[1] : null, label: text.slice(0, i), value: text.slice(i + 2) };
  return { icon: m ? m[1] : null, label: null, value: text };
}

export function parsePresence(message: string): Place {
  const parts = message.split(" | ").map((p) => p.trim()).filter(Boolean);
  if (parts.length < 2) return { headline: message.trim() || null, chips: [] };
  const headline = ICON.test(parts[0]) ? null : parts[0];
  return { headline, chips: (headline === null ? parts : parts.slice(1)).map(toChip) };
}
