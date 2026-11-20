import type { Game } from "./api";
import { Cover } from "./ui";

type Medium = "disc" | "cartridge" | "handheld" | "sleeve";
const formats: Record<string, Medium> = {
  "Nintendo - GameCube": "disc",
  "Nintendo - Wii": "disc",
  "Nintendo - Wii U": "disc",
  "Sony - PlayStation": "disc",
  "Sony - PlayStation 2": "disc",
  "Sony - PlayStation 3": "disc",
  "Sega - Dreamcast": "disc",
  "Sega - Saturn": "disc",
  "Sega - Mega-CD - Sega CD": "disc",
  "Nintendo - Nintendo Entertainment System": "cartridge",
  "Nintendo - Super Nintendo Entertainment System": "cartridge",
  "Nintendo - Nintendo 64": "cartridge",
  "Sega - Mega Drive - Genesis": "cartridge",
  "Nintendo - Game Boy": "handheld",
  "Nintendo - Game Boy Color": "handheld",
  "Nintendo - Game Boy Advance": "handheld",
};

export function GameMedia({ game }: { game: Game }) {
  const medium = formats[game.platform ?? ""] ?? "sleeve";
  return (
    <div className={`print-stage media-${medium}`} aria-hidden="true">
      <div className="media-object" key={game.id}>
        {medium === "disc" && <div className="print-orbit" />}
        <div className="print-case"><div className="media-label"><Cover game={game} /></div></div>
      </div>
    </div>
  );
}
