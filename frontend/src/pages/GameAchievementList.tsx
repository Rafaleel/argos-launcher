import { useEffect, useMemo, useState } from "react";
import { Check, Circle, Search, ShieldCheck } from "lucide-react";
import { api, RaAchievement } from "../api";
import { Notify, Select } from "../ui";

type Filter = "all" | "earned" | "locked";

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
  const earnedCount = rows.filter((r) => r.a.earned).length;
  const lockedCount = rows.length - earnedCount;
  const needle = plain(query.trim());
  const shown = rows.filter((r) =>
    (filter === "all" || (filter === "earned") === r.a.earned) && (!tag || r.tag === tag) && (!needle || r.haystack.includes(needle)));

  if (items === null) return null;
  if (items.length === 0) {
    return (
      <section className="panel" aria-label="Todas as conquistas">
        <p className="muted">A lista completa de conquistas aparece aqui depois da primeira sincronização.</p>
      </section>
    );
  }

  const filters: [Filter, string, number][] = [
    ["all", "Todas", items.length],
    ["earned", "Ganhas", earnedCount],
    ["locked", "Pendentes", lockedCount],
  ];

  return (
    <section className="panel gm-ach-list-panel" aria-label="Todas as conquistas">
      <header>
        <div>
          <h3>Lista de conquistas</h3>
          <p>Busque por nome, requisito ou filtre por cenário.</p>
        </div>
        <span className="ofc-pill muted num" aria-live="polite">
          {shown.length === items.length ? `${items.length} conquistas` : `${shown.length} de ${items.length}`}
        </span>
      </header>

      <div className="gm-ach-tools">
        <label className="act-search">
          <Search size={16} aria-hidden="true" />
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar por nome ou pelo que fazer" aria-label="Buscar conquistas" />
        </label>
        <div className="seg" role="group" aria-label="Filtrar">
          {filters.map(([k, label, count]) => (
            <button type="button" key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>
              {label} <span className="gm-seg-count num">{count}</span>
            </button>
          ))}
        </div>
        {tags.length > 1 && (
          <div className="gm-ach-select">
            <Select value={tag} onChange={setTag} label="Cenário ou modo"
              options={[{ value: "", label: "Todos os cenários" }, ...tags.map((t) => ({ value: t, label: t }))]} />
          </div>
        )}
      </div>

      {shown.length === 0 ? (
        <p className="muted gm-empty-filter">Nenhuma conquista corresponde a esse filtro.</p>
      ) : (
        <ul className="gm-ach-list">
          {shown.map(({ a, tag: t, text }) => (
            <li key={a.id} className={`gm-ach-row ${a.earned ? "earned" : ""}`}>
              <span className="gm-ach-state" role="img" aria-label={a.earned ? "ganha" : "pendente"}>
                {a.earned ? <Check size={14} aria-hidden="true" /> : <Circle size={14} aria-hidden="true" />}
              </span>
              <div className="gm-ach-copy">
                <div className="gm-ach-title-line">
                  <b>{a.title}</b>
                  {a.type === "progression" && <span className="gm-type-tag">História</span>}
                  {a.earned && a.hardcore && (
                    <span className="gm-hc-tag"><ShieldCheck size={11} aria-hidden="true" /> Hardcore</span>
                  )}
                </div>
                <p>{t && <span className="tag">{t}</span>}{text}</p>
              </div>
              <div className="gm-ach-meta num">
                <span className="gm-ach-pts">{a.points} pts</span>
                {a.earned && a.at && (
                  <time dateTime={a.at.replace(" ", "T") + "Z"}>
                    {new Date(a.at.replace(" ", "T") + "Z").toLocaleDateString("pt-BR")}
                  </time>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
