import { ReactNode, useState } from "react";
import { coverUrl, Game } from "./api";

export type Notify = (text: string, error?: boolean) => void;

const SHORT: Record<string, string> = {
  "Nintendo - GameCube": "GameCube",
  "Nintendo - Wii": "Wii",
  "Nintendo - Nintendo Entertainment System": "NES",
  "Nintendo - Super Nintendo Entertainment System": "SNES",
  "Nintendo - Game Boy": "Game Boy",
  "Nintendo - Game Boy Color": "Game Boy Color",
  "Nintendo - Game Boy Advance": "Game Boy Advance",
  "Sony - PlayStation": "PlayStation",
  "Sony - PlayStation 2": "PlayStation 2",
};

/** "Nintendo - GameCube" -> "GameCube": the DAT name is precise but long. */
export const platformName = (p: string | null) => (p === null ? "Não identificado" : SHORT[p] ?? p.split(" - ").pop() ?? p);

/** "Resident Evil 2 (USA)" -> title and the tags the DAT appends. */
export function splitTitle(title: string): { name: string; tags: string } {
  const m = title.match(/^(.*?)\s*((?:\([^)]*\)\s*)+)$/);
  if (!m) return { name: title, tags: "" };
  const disc = m[2].match(/\(Disc (\d+)\)/i); // the disc tells two entries apart: keep it in the name
  return { name: disc ? `${m[1]} · Disco ${disc[1]}` : m[1], tags: m[2].replace(/\(Disc \d+\)/i, "").trim() };
}

export function Cover({ game }: { game: Pick<Game, "id" | "identified" | "title" | "platform"> }) {
  const [failed, setFailed] = useState(false);
  const { name } = splitTitle(game.title);
  if (failed || !game.identified) {
    return (
      <span className="plate" aria-hidden="true">
        <b>{name}</b>
        <i>{platformName(game.platform)}</i>
      </span>
    );
  }
  return <img src={coverUrl(game.id)} alt="" loading="lazy" onError={() => setFailed(true)} />;
}

/** The Argos eye: a share of something as an iris ring around the number. */
export function Eye({ value, total, label, gold = false }: { value: number; total: number; label: string; gold?: boolean }) {
  const r = 58;
  const c = 2 * Math.PI * r;
  const share = total > 0 ? Math.min(1, value / total) : 0;
  return (
    <div className="eye" role="img" aria-label={`${label}: ${value} de ${total}`}>
      <svg viewBox="0 0 132 132" width="132" height="132">
        <circle className="ring-bg" cx="66" cy="66" r={r} fill="none" strokeWidth="6" />
        <circle className={`ring ${gold ? "gold" : ""}`} cx="66" cy="66" r={r} fill="none" strokeWidth="6" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - share)} />
      </svg>
      <div className="pupil">
        <b>{total > 0 ? `${Math.round(share * 100)}%` : "—"}</b>
        <span>{label}</span>
      </div>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}

/** Three states: unset ("Padrão"), on, off. */
export function Tri({ label, value, onChange, hint }: {
  label: string; value: boolean | undefined; onChange: (v: boolean | undefined) => void; hint?: ReactNode;
}) {
  return (
    <Field label={label} hint={hint}>
      <select value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value === "true")}>
        <option value="">Padrão</option>
        <option value="true">Ligado</option>
        <option value="false">Desligado</option>
      </select>
    </Field>
  );
}

export function Panel({ title, sub, action, children }: { title: string; sub?: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel">
      <header>
        <div>
          <h3>{title}</h3>
          {sub && <p>{sub}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

export const localTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString("pt-BR") : "nunca");
export const localDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("pt-BR", { day: "numeric", month: "short" }) : "nunca");
