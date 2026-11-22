import { KeyboardEvent, ReactNode, useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
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

export type Choice = { value: string; label: string };

/** A dropdown in the site's own style (the native one cannot be styled). A listbox on a button: arrows move,
 *  Enter or Space picks, Escape and a click elsewhere close it. */
export function Select({ value, options, onChange, label }: { value: string; options: Choice[]; onChange: (v: string) => void; label?: string }) {
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const selected = Math.max(0, options.findIndex((o) => o.value === value));
  const [active, setActive] = useState(selected);
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);
  const show = () => { setActive(selected); setOpen(true); };
  const pick = (i: number) => { if (options[i]) onChange(options[i].value); setOpen(false); };
  const key = (e: KeyboardEvent) => {
    const move = (to: number) => { e.preventDefault(); if (open) setActive(Math.min(options.length - 1, Math.max(0, to))); else show(); };
    if (e.key === "ArrowDown") move(active + 1);
    else if (e.key === "ArrowUp") move(active - 1);
    else if (e.key === "Home" && open) move(0);
    else if (e.key === "End" && open) move(options.length - 1);
    else if ((e.key === "Enter" || e.key === " ") && open) { e.preventDefault(); pick(active); }
    else if (e.key === "Escape" && open) { e.preventDefault(); setOpen(false); }
    else if (e.key === "Tab") setOpen(false);
  };
  return (
    <div className="select" ref={root} onKeyDown={key}>
      <button type="button" className="select-btn" aria-label={label} aria-haspopup="listbox" aria-expanded={open}
        aria-controls={open ? id : undefined} aria-activedescendant={open ? `${id}-${active}` : undefined}
        onClick={() => (open ? setOpen(false) : show())}>
        <span>{options[selected]?.label ?? ""}</span>
        <ChevronDown aria-hidden="true" />
      </button>
      {open && (
        <ul className="select-list" role="listbox" id={id} aria-label={label}>
          {options.map((o, i) => (
            <li key={o.value} id={`${id}-${i}`} role="option" aria-selected={i === selected} className={i === active ? "active" : undefined}
              onPointerEnter={() => setActive(i)} onClick={() => pick(i)}>
              <span>{o.label}</span>{i === selected && <Check aria-hidden="true" />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Three states: unset ("Padrão"), on, off. */
export function Tri({ label, value, onChange, hint }: {
  label: string; value: boolean | undefined; onChange: (v: boolean | undefined) => void; hint?: ReactNode;
}) {
  return (
    <Field label={label} hint={hint}>
      <Select value={value === undefined ? "" : String(value)} onChange={(v) => onChange(v === "" ? undefined : v === "true")}
        options={[{ value: "", label: "Padrão" }, { value: "true", label: "Ligado" }, { value: "false", label: "Desligado" }]} label={label} />
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
