import { useEffect, useState } from "react";
import { api, By, formatDuration, Game, GameTime, Period, PlatformTime } from "../api";
import { collectEditions, editionTitle } from "../collection";
import { Journal } from "./Journal";
import { Panel, platformName, splitTitle } from "../ui";

function Bars({ rows }: { rows: { id: string; label: string; seconds: number; href?: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.seconds));
  return (
    <div className="bars">
      {rows.map((r) => (
        <div className="bar-row" key={r.id}>
          <span title={r.label}>{r.href ? <a href={r.href} style={{ color: "inherit" }}>{r.label}</a> : r.label}</span>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${(r.seconds / max) * 100}%` }} /></div>
          <span>{formatDuration(r.seconds)}</span>
        </div>
      ))}
    </div>
  );
}

const periodLabel = (p: string, by: By) => {
  if (by === "month") return new Date(`${p}-01T12:00:00`).toLocaleDateString("pt-BR", { month: "short" });
  const d = new Date(`${p}T12:00:00`);
  return by === "week" ? d.toLocaleDateString("pt-BR", { day: "numeric", month: "numeric" }) : d.toLocaleDateString("pt-BR", { day: "numeric" });
};

export function Stats({ games }: { games: Game[] }) {
  const [platforms, setPlatforms] = useState<PlatformTime[]>([]);
  const [top, setTop] = useState<GameTime[]>([]);
  const [periods, setPeriods] = useState<Period[]>([]);
  const [by, setBy] = useState<By>("day");

  useEffect(() => { api.statsPlatforms().then(setPlatforms).catch(() => undefined); api.statsGames().then(setTop).catch(() => undefined); }, [games]);
  useEffect(() => { api.statsPeriods(by).then(setPeriods).catch(() => undefined); }, [by, games]);

  const availableIds = new Set(games.map(g => g.id));
  const titles = collectEditions(top.map(row => ({
    ...row, id: row.game_id, identified: row.platform !== null,
  }))).map(group => {
    const first = group[0];
    const available = group.find(row => availableIds.has(row.id));
    return {
      id: first.id,
      name: splitTitle(editionTitle(first.title)).name,
      seconds: group.reduce((sum, row) => sum + row.seconds, 0),
      href: available ? `#/game/${available.id}` : undefined,
    };
  }).sort((a, b) => b.seconds - a.seconds);
  const total = top.reduce((a, g) => a + g.seconds, 0);
  const sessions = top.reduce((a, g) => a + g.sessions, 0);
  const maxPeriod = Math.max(1, ...periods.map((p) => p.seconds));

  return (
    <>
      <Journal games={games} />
      {top.length > 0 && (
        <>
          <div className="kpis">
            <div className="kpi"><span className="eyebrow">Tempo total</span><b>{formatDuration(total)}</b></div>
            <div className="kpi"><span className="eyebrow">Jogos jogados</span><b>{titles.length}</b></div>
            <div className="kpi"><span className="eyebrow">Sessões</span><b>{sessions}</b></div>
            <div className="kpi"><span className="eyebrow">Mais jogado</span><b style={{ fontSize: 18, lineHeight: 1.3 }}>{titles[0].name}</b></div>
          </div>
          <div className="stats-layout">
            <Panel title="Ao longo do tempo" action={
              <div className="seg" role="group" aria-label="Agrupar por">
                {(["day", "week", "month"] as By[]).map((b) => (
                  <button key={b} aria-pressed={by === b} onClick={() => setBy(b)}>{{ day: "Dias", week: "Semanas", month: "Meses" }[b]}</button>
                ))}
              </div>
            }>
              <div className="columns">
                {periods.map((p) => (
                  <div className="col" key={p.period} title={`${p.period}: ${formatDuration(p.seconds)}`}>
                    <div hidden={p.seconds === 0} style={{ height: `${(p.seconds / maxPeriod) * 100}%` }} />
                    <span>{periodLabel(p.period, by)}</span>
                  </div>
                ))}
              </div>
            </Panel>
            <Panel title="Por jogo">
              <Bars rows={titles.slice(0, 10).map(g => ({ id: String(g.id), label: g.name, seconds: g.seconds, href: g.href }))} />
            </Panel>
            <Panel title="Por plataforma">
              <Bars rows={platforms.map((p) => ({ id: p.platform ?? "-", label: platformName(p.platform), seconds: p.seconds }))} />
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
