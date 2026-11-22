import { Check, Circle } from "lucide-react";
import type { Milestones } from "../api";
import { localTime, Panel } from "../ui";

type Story = Extract<Milestones, { supported: true }>;

export function GameMilestones({ story }: { story: Story }) {
  return (
    <Panel
      title={story.total ? `${story.reached} de ${story.total} marcos da história` : "Marcos da história"}
      sub={story.read_at ? `Última mudança em ${localTime(story.read_at)}` : "Lidos da memória do Dolphin enquanto você joga."}
    >
      {story.problem && <div className="note warn" role="alert">{story.problem}</div>}
      {story.total === 0 && !story.problem && <p className="muted">A lista é baixada na primeira vez que você joga pelo Argos, com o Dolphin logado no RetroAchievements.</p>}
      <ul className="list-plain">
        {story.items.map((m) => (
          <li key={m.name} className="row">
            {m.reached ? <Check size={16} aria-label="alcançado" /> : <Circle size={16} aria-label="ainda não" />} <span>{m.name}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
