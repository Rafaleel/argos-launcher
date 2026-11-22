import { useEffect, useState } from "react";
import { RefreshCw, ScanSearch } from "lucide-react";
import { AchievementSummary, api } from "../api";
import { Field, localTime, Notify, Panel } from "../ui";

export function GameAchievements({ gameId, notify, onChange }: {
  gameId: number; notify: Notify; onChange: (s: AchievementSummary | null) => void;
}) {
  const [ref, setRef] = useState("");
  const [linked, setLinked] = useState<number | null>(null);
  const [summary, setSummary] = useState<AchievementSummary | null>(null);
  const [busy, setBusy] = useState<"" | "detect" | "sync" | "link">("");

  const show = (s: AchievementSummary | null) => { setSummary(s); onChange(s); };
  useEffect(() => {
    api.gameRa(gameId).then((r) => { setLinked(r.ra_id); setRef(r.ra_id ? String(r.ra_id) : ""); setSummary(r.summary); })
      .catch((e) => notify(e.message, true));
  }, [gameId]);

  const run = (kind: "detect" | "sync" | "link", work: () => Promise<unknown>) => {
    setBusy(kind);
    work().catch((e) => notify(e.message, true)).finally(() => setBusy(""));
  };
  const detect = () => run("detect", async () => {
    const r = await api.detectGameRa(gameId);
    if (!r.found) { notify("O RetroAchievements não reconheceu este disco. Informe o ID à mão.", true); return; }
    setLinked(r.ra_id); setRef(String(r.ra_id));
    notify(`Encontrado: jogo ${r.ra_id} no RetroAchievements.`);
    show((await api.gameRa(gameId)).summary);
  });
  const link = () => run("link", async () => {
    const r = await api.saveGameRa(gameId, ref);
    setLinked(r.ra_id); setRef(r.ra_id ? String(r.ra_id) : "");
    notify(r.ra_id ? "Jogo vinculado." : "Vínculo removido.");
    show((await api.gameRa(gameId)).summary);
  });
  const sync = () => run("sync", async () => show(await api.syncGameRa(gameId)));

  return (
    <div className="stack">
      <Panel
        title={summary ? `${summary.earned} de ${summary.total} conquistas` : linked ? "Ainda não sincronizado" : "Sem vínculo com o RetroAchievements"}
        sub={summary ? <>Em "{summary.title}" · sincronizado em {localTime(summary.synced_at)}{summary.earned_hardcore ? ` · ${summary.earned_hardcore} no modo hardcore` : ""}</>
          : linked ? "Sincronize para ver quantas você já ganhou." : "Detecte o jogo pelo disco ou informe o ID do site."}
        action={
          <button className="btn" onClick={sync} disabled={busy !== "" || linked === null}>
            <RefreshCw /> {busy === "sync" ? "Sincronizando…" : "Sincronizar"}
          </button>
        }
      >
        <details open={linked === null || !linked}>
          <summary>Vínculo com o RetroAchievements</summary>
          <div className="link-box">
          <div className="row">
            <div className="grow">
              <Field label="Jogo no RetroAchievements (número ou endereço da página)">
                <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="1234 ou retroachievements.org/game/1234" />
              </Field>
            </div>
            <button className="btn" onClick={detect} disabled={busy !== ""}><ScanSearch /> {busy === "detect" ? "Detectando…" : "Detectar pelo disco"}</button>
            <button className="btn" onClick={link} disabled={busy !== ""}>Salvar</button>
          </div>
          {linked !== null && (
            <p className="muted" style={{ marginTop: 12, fontSize: 13 }}>
              Vinculado ao jogo <a href={`https://retroachievements.org/game/${linked}`} target="_blank" rel="noreferrer">{linked}</a>.
              Confira no site que é a versão certa.
            </p>
          )}
          </div>
        </details>
      </Panel>
      <p className="muted" style={{ fontSize: 13 }}>
        As conquistas são ganhas dentro do emulador, que precisa estar logado (veja Atividade → Conquistas), e são sincronizadas
        sozinhas quando você fecha o jogo.
      </p>
    </div>
  );
}
