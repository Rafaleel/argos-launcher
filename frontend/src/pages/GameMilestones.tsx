import { AlertTriangle, Check, CheckCircle2, Clock3, Compass, Flag } from "lucide-react";
import type { Milestones } from "../api";
import { localTime } from "../ui";

type Story = Extract<Milestones, { supported: true }>;

export function GameMilestones({ story }: { story: Story }) {
  const nextIdx = story.items.findIndex((m) => !m.reached);
  const nextStep = nextIdx >= 0 ? story.items[nextIdx] : null;
  const pct = story.total > 0 ? Math.round((story.reached / story.total) * 100) : 0;
  const complete = story.total > 0 && story.reached === story.total;

  return (
    <div className="gm-stack">
      <section className="panel gm-story-hero" aria-label="Resumo dos marcos da história">
        <div className="gm-story-top">
          <div>
            <div className="kicker"><span className="signal" />Progresso da história</div>
            <h3>
              {story.total > 0
                ? <span className="num">{story.reached} de {story.total} marcos alcançados</span>
                : "Marcos da história"}
            </h3>
            <p className="muted">
              {story.read_at
                ? <>Última atualização em {localTime(story.read_at)}.</>
                : "Lidos diretamente da memória do Dolphin durante as sessões."}
            </p>
          </div>
          {story.total > 0 && (
            <div className="gm-story-pct-box">
              <strong className="num">{pct}%</strong>
              <span className="eyebrow">{complete ? "Concluído" : "Avanço"}</span>
            </div>
          )}
        </div>

        {story.total > 0 && (
          <div className="meter gm-meter" aria-hidden="true">
            <i className={complete ? "gold" : undefined} style={{ width: `${pct}%` }} />
          </div>
        )}

        {nextStep && (
          <div className="gm-story-callout">
            <span className="gm-callout-icon" aria-hidden="true"><Compass size={17} /></span>
            <div>
              <span className="eyebrow">Próximo marco · #{String(nextIdx + 1).padStart(2, "0")}</span>
              <strong>{nextStep.name}</strong>
            </div>
          </div>
        )}

        {complete && (
          <div className="gm-story-callout done">
            <span className="gm-callout-icon" aria-hidden="true"><CheckCircle2 size={17} /></span>
            <div>
              <span className="eyebrow">Rota finalizada</span>
              <strong>Todos os marcos desta história foram alcançados.</strong>
            </div>
          </div>
        )}

        {story.problem && (
          <div className="note warn gm-story-alert" role="alert">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>{story.problem}</span>
          </div>
        )}
      </section>

      {!(story.total === 0 && story.problem) && (
        <section className="panel gm-timeline-panel" aria-label="Linha do tempo dos marcos">
          <header>
            <div>
              <h3>Linha do tempo</h3>
              <p>Ordem esperada dos eventos principais acompanhados na memória.</p>
            </div>
            {story.read_at && (
              <span className="ofc-pill muted num"><Clock3 size={13} aria-hidden="true" /> {localTime(story.read_at)}</span>
            )}
          </header>

          {story.total === 0 ? (
            <p className="muted">
              A lista de marcos é baixada na primeira vez que você joga pelo Argos com o Dolphin logado no RetroAchievements.
            </p>
          ) : (
            <ol className="gm-timeline">
              {story.items.map((m, i) => {
                const isDone = m.reached;
                const isNext = i === nextIdx;
                const state = isDone ? "done" : isNext ? "next" : "upcoming";
                return (
                  <li key={m.name} className={`gm-step ${state}`} aria-current={isNext ? "step" : undefined}>
                    <span className="gm-step-node num" aria-hidden="true">
                      {isDone ? <Check size={14} /> : String(i + 1).padStart(2, "0")}
                    </span>
                    <div className="gm-step-card">
                      <div className="gm-step-copy">
                        <span className="eyebrow num">Marco {String(i + 1).padStart(2, "0")}</span>
                        <strong className="gm-step-name">{m.name}</strong>
                      </div>
                      <span className={`ofc-pill ${isDone ? "ok" : isNext ? "warn" : "muted"}`}>
                        {isDone ? <><Check size={12} aria-hidden="true" /> Alcançado</>
                          : isNext ? <><Flag size={12} aria-hidden="true" /> Próximo</>
                            : "Pendente"}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
      )}
    </div>
  );
}
