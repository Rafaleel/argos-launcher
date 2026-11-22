import { AchievementSummary, formatDuration, Game, GameTime, Milestones } from "../api";
import { parsePresence } from "../presence";
import { localDate, localTime } from "../ui";

type Story = Extract<Milestones, { supported: true }>;
export type Place = { message: string; at: string | null };

function Meter({ value, total, gold }: { value: number; total: number; gold?: boolean }) {
  return (
    <div className="meter" role="img" aria-label={`${value} de ${total}`}>
      <i className={gold ? "gold" : undefined} style={{ width: `${total ? Math.min(100, (value / total) * 100) : 0}%` }} />
    </div>
  );
}

export function GameSummary({ game, place, summary, story, time, history, openTab }: {
  game: Game; place: Place | null; summary: AchievementSummary | null; story: Milestones | null;
  time: GameTime | undefined; history: boolean; openTab: (tab: "achievements" | "story") => void;
}) {
  const parsed = place ? parsePresence(place.message) : null;
  const next = story?.supported ? story.items.find((m) => !m.reached) : undefined;
  return (
    <div className="stack">
      <section className="panel place" aria-label="Onde você parou">
        <span className="eyebrow">Onde você parou</span>
        {parsed && place ? (
          <>
            {parsed.headline && <p className="place-head">{parsed.headline}</p>}
            {parsed.chips.length > 0 && (
              <ul className="chips">
                {parsed.chips.map((c, i) => (
                  <li key={i} className="chip">
                    {c.icon && <span aria-hidden="true">{c.icon}</span>}
                    <span>{c.label && <small>{c.label}</small>}<b>{c.value}</b></span>
                  </li>
                ))}
              </ul>
            )}
            {place.at && <small className="muted">Informado pelo RetroAchievements em {localTime(place.at)}</small>}
          </>
        ) : (
          <p className="muted">Ainda sem registro. Jogue pelo Argos, com o jogo vinculado ao RetroAchievements e o Dolphin logado, e o último lugar aparece aqui.</p>
        )}
      </section>
      <div className="stat-grid">
        <section className="panel stat">
          <span className="eyebrow">Conquistas</span>
          {summary ? (
            <>
              <b className="stat-num">{summary.earned} <small>de {summary.total}</small></b>
              <Meter value={summary.earned} total={summary.total} gold />
              <p className="muted">{summary.points_earned} de {summary.points_total} pontos · sincronizado em {localTime(summary.synced_at)}</p>
            </>
          ) : <p className="muted">{game.ra_id ? "Ainda não sincronizado." : "Sem vínculo com o RetroAchievements."}</p>}
          <button className="btn ghost" onClick={() => openTab("achievements")}>Ver conquistas</button>
        </section>
        {story?.supported && (
          <section className="panel stat">
            <span className="eyebrow">História</span>
            {story.total > 0 ? (
              <>
                <b className="stat-num">{story.reached} <small>de {story.total}</small></b>
                <Meter value={story.reached} total={story.total} />
                <p className="muted">{next ? <>Próximo: {next.name}</> : "Todos os marcos alcançados."}</p>
              </>
            ) : <p className="muted">A lista é baixada na primeira vez que você joga pelo Argos.</p>}
            <button className="btn ghost" onClick={() => openTab("story")}>Ver marcos</button>
          </section>
        )}
        <section className="panel stat">
          <span className="eyebrow">Tempo jogado</span>
          <b className="stat-num">{formatDuration(game.seconds_played)}</b>
          <p className="muted">{history ? `${time?.sessions ?? 0} sessões · última vez ${localDate(time?.last_played ?? null)}` : "—"}</p>
        </section>
      </div>
    </div>
  );
}
