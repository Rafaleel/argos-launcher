import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, Search } from "lucide-react";
import { api, formatDuration, Game, JournalPage } from "../api";
import { collectEditions, editionTitle } from "../collection";
import { Cover, platformName, Select, splitTitle } from "../ui";

const dateFormat = new Intl.DateTimeFormat("pt-BR", { day: "numeric", month: "long", year: "numeric" });

export function Journal({ games }: { games: Game[] }) {
  const [cursors, setCursors] = useState<string[]>([]);
  const before = cursors.at(-1) ?? null;
  const [page, setPage] = useState<JournalPage | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState("");

  useEffect(() => {
    let current = true;
    api.journal(before).then((result) => {
      if (current) { setPage(result); setError(""); }
    }).catch((e) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [before, games, retry]);

  function turn(next: string[]) {
    setPage(null);
    setError("");
    setCursors(next);
  }

  const available = useMemo(() => new Map(games.map((g) => [g.id, g])), [games]);
  const platforms = useMemo(() => {
    const set = new Set<string>();
    for (const g of games) if (g.platform) set.add(g.platform);
    if (page) for (const d of page.days) for (const r of d.games) if (r.platform) set.add(r.platform);
    return [...set].sort((a, b) => platformName(a).localeCompare(platformName(b), "pt-BR"));
  }, [games, page]);

  const needle = query.trim().toLocaleLowerCase();
  const filteredDays = useMemo(() => {
    if (!page) return [];
    return page.days.map(({ day, games: rows }) => {
      const grouped = collectEditions(rows.map((r) => ({ ...r, id: r.game_id, identified: r.platform !== null })))
        .filter((group) => {
          const first = group[0];
          if (platform && first.platform !== platform) return false;
          if (!needle) return true;
          const name = splitTitle(editionTitle(first.title)).name;
          return (name + " " + platformName(first.platform)).toLocaleLowerCase().includes(needle);
        });
      const dayTotal = grouped.reduce((sum, g) => sum + g.reduce((s, r) => s + r.seconds, 0), 0);
      return { day, grouped, dayTotal };
    }).filter((d) => d.grouped.length > 0);
  }, [page, platform, needle]);

  const hasFilters = !!needle || !!platform;

  return (
    <section className="panel act-journal" aria-label="Diário de jogo">
      <header>
        <div>
          <h3 className="act-journal-title"><BookOpen size={19} aria-hidden="true" /> Diário de jogo</h3>
          <p>Sessões agrupadas por dia local e por edição.</p>
        </div>
      </header>

      {(page?.days.length || hasFilters || before) && (
        <div className="act-journal-tools">
          <label className="act-search">
            <Search size={15} aria-hidden="true" />
            <input data-search-input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filtrar jogo no diário" aria-label="Filtrar jogo no diário" />
          </label>
          {platforms.length > 1 && (
            <div className="act-journal-plat">
              <Select
                value={platform}
                onChange={setPlatform}
                label="Filtrar por plataforma"
                options={[
                  { value: "", label: "Todas as plataformas" },
                  ...platforms.map((p) => ({ value: p, label: platformName(p) })),
                ]}
              />
            </div>
          )}
        </div>
      )}

      {error && (
        <div role="alert" className="note warn">
          {error} <button type="button" className="btn" onClick={() => setRetry((value) => value + 1)}>Tentar novamente</button>
        </div>
      )}
      {!page && !error && (
        <div className="skel-panel" role="status" aria-label="Lendo sessões">
          <span className="skel-block" /><span className="skel-block" />
        </div>
      )}
      {page && !page.days.length && <p className="muted">As sessões aparecem aqui quando você abre um jogo pelo Argos.</p>}
      {page && page.days.length > 0 && filteredDays.length === 0 && hasFilters && (
        <p className="muted">Nenhuma sessão nesta página corresponde a esse filtro.</p>
      )}

      {filteredDays.length > 0 && (
        <div className="act-days">
          {filteredDays.map(({ day, grouped, dayTotal }) => (
            <div className="act-day" key={day}>
              <div className="act-day-head">
                <time dateTime={day}>{dateFormat.format(new Date(day + "T12:00:00"))}</time>
                <span className="act-day-total num">{formatDuration(dayTotal)}</span>
              </div>
              <ul className="act-session-list">
                {grouped.map((group) => {
                  const first = group[0];
                  const present = group.find((r) => available.has(r.id));
                  const art = available.get(present?.id ?? first.id) ?? first;
                  const name = splitTitle(editionTitle(first.title)).name;
                  const sessions = group.reduce((sum, r) => sum + r.sessions, 0);
                  const seconds = group.reduce((sum, r) => sum + r.seconds, 0);
                  return (
                    <li className="act-session-row" key={first.id}>
                      <span className="act-session-cover"><Cover game={art} /></span>
                      <div className="act-session-info">
                        {present ? <a href={`#/game/${present.id}`}>{name}</a> : <strong>{name}</strong>}
                        <small>{platformName(first.platform)}</small>
                      </div>
                      <span className="act-session-count num">{sessions} {sessions === 1 ? "sessão" : "sessões"}</span>
                      <strong className="act-session-dur num">{formatDuration(seconds)}</strong>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}

      {(before || page?.next_before) && (
        <div className="act-journal-pager">
          {before ? (
            <button type="button" className="btn ghost" onClick={() => turn(cursors.slice(0, -1))}><ArrowLeft size={15} /> Mais recentes</button>
          ) : <span />}
          {page?.next_before && (
            <button type="button" className="btn ghost" onClick={() => turn([...cursors, page.next_before!])}>Dias anteriores <ArrowRight size={15} /></button>
          )}
        </div>
      )}
    </section>
  );
}
