import { useEffect, useMemo, useState } from "react";
import { Check, Circle, Search } from "lucide-react";
import { api, RaAchievement } from "../api";
import { Notify, Select } from "../ui";

type Filter = "all" | "earned" | "locked";
const FILTERS: [Filter, string][] = [["all", "Todas"], ["earned", "Ganhas"], ["locked", "Pendentes"]];

// "[Leon A] Defeat G-Type 2" -> tag "Leon A", text "Defeat G-Type 2". Sets use the tag to say which scenario or mode it is for.
const TAG = /^\[([^\]]{1,40})\]\s*/;
const split = (description: string) => {
  const m = TAG.exec(description);
  return m ? { tag: m[1], text: description.slice(m[0].length) } : { tag: null, text: description };
};
const plain = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();

export function GameAchievementList({ gameId, version, notify }: { gameId: number; version: string | null; notify: Notify }) {
  const [items, setItems] = useState<RaAchievement[] | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [tag, setTag] = useState("");

  // `version` changes with every sync, which is when the list may have changed
  useEffect(() => {
    let active = true;
    api.achievements(gameId).then((r) => { if (active) setItems(r.items); }).catch((e) => notify(e.message, true));
    return () => { active = false; };
  }, [gameId, version]);

  const rows = useMemo(() => (items ?? []).map((a) => ({ a, ...split(a.description), haystack: plain(`${a.title} ${a.description}`) })), [items]);
  const tags = useMemo(() => [...new Set(rows.map((r) => r.tag).filter((t): t is string => t !== null))], [rows]);
  const needle = plain(query.trim());
  const shown = rows.filter((r) =>
    (filter === "all" || (filter === "earned") === r.a.earned) && (!tag || r.tag === tag) && (!needle || r.haystack.includes(needle)));

  if (items === null) return null;
  if (items.length === 0) {
    return <p className="muted">A lista completa aparece depois da primeira sincronização.</p>;
  }
  return (
    <section className="panel" aria-label="Todas as conquistas">
      <div className="ach-tools">
        <label className="ach-search">
          <Search size={16} aria-hidden="true" />
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar por nome ou pelo que fazer" aria-label="Buscar conquistas" />
        </label>
        <div className="seg" role="group" aria-label="Filtrar">
          {FILTERS.map(([k, label]) => (
            <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{label}</button>
          ))}
        </div>
        {tags.length > 1 && (
          <Select value={tag} onChange={setTag} label="Cenário ou modo"
            options={[{ value: "", label: "Todos os cenários" }, ...tags.map((t) => ({ value: t, label: t }))]} />
        )}
      </div>
      <p className="muted ach-count" aria-live="polite">{shown.length === items.length ? `${items.length} conquistas` : `${shown.length} de ${items.length} conquistas`}</p>
      {shown.length === 0 ? <p className="muted">Nenhuma conquista com esse filtro.</p> : (
        <ul className="ach-list">
          {shown.map(({ a, tag: t, text }) => (
            <li key={a.id} className={a.earned ? "ach earned" : "ach"}>
              {a.earned ? <Check size={18} aria-label="ganha" /> : <Circle size={18} aria-label="pendente" />}
              <div>
                <b>{a.title}</b>
                <p>{t && <span className="tag">{t}</span>}{text}</p>
              </div>
              <div className="ach-meta">
                <span className="pts">{a.points} pts</span>
                {a.earned && a.at && <time dateTime={a.at.replace(" ", "T") + "Z"}>{new Date(a.at.replace(" ", "T") + "Z").toLocaleDateString("pt-BR")}</time>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
