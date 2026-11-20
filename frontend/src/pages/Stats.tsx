import { useEffect, useState } from "react";
import { api, By, formatDuration, Game, GameTime, Period, PlatformTime } from "../api";
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

  const total = top.reduce((a, g) => a + g.seconds, 0);
  const sessions = top.reduce((a, g) => a + g.sessions, 0);
  const maxPeriod = Math.max(1, ...periods.map((p) => p.seconds));

  return (
    <>
      <div className="page-head"><div><h1>Estatísticas</h1><p>Quanto você jogou, onde e quando.</p></div></div>
      {top.length === 0 ? (
        <div className="empty"><h2>Nada registrado ainda</h2><p>Abra um jogo pelo Argos e o tempo começa a contar sozinho.</p></div>
      ) : (
        <>
          <div className="kpis">
            <div className="kpi"><span className="eyebrow">Tempo total</span><b>{formatDuration(total)}</b></div>
            <div className="kpi"><span className="eyebrow">Jogos jogados</span><b>{top.length}</b></div>
            <div className="kpi"><span className="eyebrow">Sessões</span><b>{sessions}</b></div>
            <div className="kpi"><span className="eyebrow">Mais jogado</span><b style={{ fontSize: 18, lineHeight: 1.3 }}>{splitTitle(top[0].title).name}</b></div>
          </div>
          <div className="stack">
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
                    <div style={{ height: `${(p.seconds / maxPeriod) * 100}%` }} />
                    <span>{periodLabel(p.period, by)}</span>
                  </div>
                ))}
              </div>
            </Panel>
            <Panel title="Por jogo">
              <Bars rows={top.slice(0, 10).map((g) => ({ id: String(g.game_id), label: splitTitle(g.title).name, seconds: g.seconds, href: `#/game/${g.game_id}` }))} />
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
