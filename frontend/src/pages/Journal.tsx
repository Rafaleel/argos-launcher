import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen } from "lucide-react";
import { api, formatDuration, Game, JournalPage } from "../api";
import { collectEditions, editionTitle } from "../collection";
import { Cover, platformName, splitTitle } from "../ui";

const dateFormat = new Intl.DateTimeFormat("pt-BR", { day: "numeric", month: "long", year: "numeric" });

export function Journal({ games }: { games: Game[] }) {
  const [cursors, setCursors] = useState<string[]>([]);
  const before = cursors.at(-1) ?? null;
  const [page, setPage] = useState<JournalPage | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let current = true;
    api.journal(before).then(result => {
      if (current) { setPage(result); setError(""); }
    }).catch(e => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [before, games, retry]);
  function turn(next: string[]) {
    setPage(null);
    setError("");
    setCursors(next);
  }
  const available = new Map(games.map(g => [g.id, g]));
  return (
    <section className="journal" aria-label="Diário de jogo">
      <header><BookOpen /><h2>Diário de jogo</h2></header>
      {error && <div role="alert" className="note warn">{error} <button className="btn" onClick={() => setRetry(value => value + 1)}>Tentar novamente</button></div>}
      {!page && !error && <p className="muted" role="status">Lendo sessões…</p>}
      {page && !page.days.length && <p className="muted">As sessões aparecem aqui quando você abre um jogo pelo Argos.</p>}
      {page?.days.map(({ day, games: rows }) => (
        <div className="journal-day" key={day}>
          <time dateTime={day}>{dateFormat.format(new Date(day + "T12:00:00"))}</time>
          <ul>{collectEditions(rows.map(r => ({ ...r, id: r.game_id, identified: r.platform !== null }))).map(group => {
            const first = group[0];
            const present = group.find(r => available.has(r.id));
            const art = available.get(present?.id ?? first.id) ?? first;
            const name = splitTitle(editionTitle(first.title)).name;
            const sessions = group.reduce((sum,r) => sum + r.sessions, 0);
            const seconds = group.reduce((sum,r) => sum + r.seconds, 0);
            return (
              <li key={first.id}>
                <span className="journal-cover"><Cover game={art} /></span>
                <div>{present ? <a href={`#/game/${present.id}`}>{name}</a> : <strong>{name}</strong>}
                  <small>{platformName(first.platform)}</small></div>
                <span className="journal-count">{sessions} {sessions === 1 ? "sessão" : "sessões"}</span>
                <strong className="num">{formatDuration(seconds)}</strong>
              </li>
            );
          })}</ul>
        </div>
      ))}
      {(before || page?.next_before) && <div className="journal-pager">
        {before && <button className="text-link" onClick={() => turn(cursors.slice(0, -1))}><ArrowLeft />Mais recentes</button>}
        {page?.next_before && <button className="text-link" onClick={() => turn([...cursors, page.next_before!])}>Dias anteriores <ArrowRight /></button>}
      </div>}
    </section>
  );
}
