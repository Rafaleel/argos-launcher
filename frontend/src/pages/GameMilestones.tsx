import { Check } from "lucide-react";
import type { Milestones } from "../api";
import { localTime, Panel } from "../ui";

type Story = Extract<Milestones, { supported: true }>;

export function GameMilestones({ story }: { story: Story }) {
  const next = story.items.findIndex((m) => !m.reached);
  return (
    <Panel
      title={story.total ? `${story.reached} de ${story.total} marcos da história` : "Marcos da história"}
      sub={story.read_at ? `Última mudança em ${localTime(story.read_at)}` : "Lidos da memória do Dolphin enquanto você joga."}
    >
      {story.problem && <div className="note warn" role="alert">{story.problem}</div>}
      {story.total === 0 && !story.problem && <p className="muted">A lista é baixada na primeira vez que você joga pelo Argos, com o Dolphin logado no RetroAchievements.</p>}
      <ol className="timeline">
        {story.items.map((m, i) => (
          <li key={m.name} className={m.reached ? "done" : i === next ? "next" : undefined} aria-current={i === next ? "step" : undefined}>
            <span className="node" aria-hidden="true">{m.reached ? <Check size={14} /> : i + 1}</span>
            <span className="step-name">{m.name}</span>
            {i === next && <span className="step-tag">próximo</span>}
          </li>
        ))}
      </ol>
    </Panel>
  );
}
