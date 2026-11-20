import type { Game } from "./api";

// Keep the platform, region and revision in the key. Only the DAT's disc number is shared.
const discTag = /\s*\(Disc (\d+)\)(?=(?:\s*\([^)]*\))*\s*$)/i;

export function discNumber(title: string) {
  return Number(title.match(discTag)?.[1] ?? 0);
}

export function editionTitle(title: string) {
  return title.replace(discTag, "").trim();
}

type EditionRecord = Pick<Game, "id" | "title" | "platform" | "identified">;

export function collectEditions<T extends EditionRecord>(games: T[]): T[][] {
  const groups = new Map<string, T[]>();
  for (const game of games) {
    const key = game.identified && discNumber(game.title)
      ? JSON.stringify([game.platform, editionTitle(game.title)])
      : String(game.id);
    const group = groups.get(key);
    if (group) group.push(game);
    else groups.set(key, [game]);
  }
  return [...groups.values()].map(group => group.sort((a, b) => discNumber(a.title) - discNumber(b.title)));
}
