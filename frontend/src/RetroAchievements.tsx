import { useEffect, useState } from "react";
import { AchievementSummary, api, RaSyncResult } from "./api";

type Notify = (text: string, error?: boolean) => void;

const localTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString("pt-BR") : "nunca");

export const achievementText = (a: AchievementSummary | null) =>
  a === null ? "—" : a.total === 0 ? "sem conquistas" : `${a.earned} de ${a.total} (${a.percent ?? 0}%)`;

export function RaPanel({ notify, onSynced }: { notify: Notify; onSynced: () => void }) {
  const [user, setUser] = useState("");
  const [key, setKey] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [results, setResults] = useState<RaSyncResult[] | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.raSettings().then((s) => { setUser(s.user); setHasKey(s.has_key); }).catch((e) => notify(e.message, true));
  }, []);

  const save = () =>
    api.saveRaSettings(user.trim(), key.trim() === "" ? null : key.trim())
      .then((s) => { setHasKey(s.has_key); setKey(""); notify("Credenciais do RetroAchievements salvas."); })
      .catch((e) => notify(e.message, true));
  const removeKey = () =>
    api.saveRaSettings(user.trim(), "")
      .then((s) => { setHasKey(s.has_key); setKey(""); notify("Chave removida."); })
      .catch((e) => notify(e.message, true));
  const syncAll = () => {
    setBusy(true);
    api.syncAllRa().then((r) => { setResults(r); onSynced(); }).catch((e) => notify(e.message, true)).finally(() => setBusy(false));
  };

  return (
    <section>
      <h2>RetroAchievements</h2>
      <p className="muted">
        As conquistas viram o primeiro sinal de progresso. A chave de API fica em retroachievements.org, em Configurações, e é
        guardada só no seu banco local (nunca é mostrada de novo nem vai para o repositório).
      </p>
      <div className="card">
        <div className="row">
          <div className="grow">
            <label>Usuário</label>
            <input aria-label="Usuário do RetroAchievements" value={user} onChange={(e) => setUser(e.target.value)} autoComplete="off" />
          </div>
          <div className="grow">
            <label>Chave de API {hasKey && "(já salva; deixe em branco para manter)"}</label>
            <input aria-label="Chave de API do RetroAchievements" type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" placeholder={hasKey ? "••••••••" : ""} />
          </div>
          <div><button onClick={save} disabled={!user.trim()}>Salvar</button></div>
          {hasKey && <div><button onClick={removeKey}>Remover chave</button></div>}
        </div>
        <p>
          <button onClick={syncAll} disabled={busy || !hasKey}>{busy ? "Sincronizando…" : "Sincronizar todos os jogos vinculados"}</button>
        </p>
        {results && (
          results.length === 0
            ? <p className="muted">Nenhum jogo vinculado ainda. Abra "Ajustes" em um jogo e informe o ID dele no RetroAchievements.</p>
            : <ul>{results.map((r) => <li key={r.game_id}>{r.ok ? "✓" : "✗"} {r.title}: {r.message}</li>)}</ul>
        )}
      </div>
    </section>
  );
}

export function GameAchievements({ gameId, notify, onSynced }: { gameId: number; notify: Notify; onSynced: () => void }) {
  const [ref, setRef] = useState("");
  const [linked, setLinked] = useState<number | null>(null);
  const [summary, setSummary] = useState<AchievementSummary | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.gameRa(gameId).then((r) => { setLinked(r.ra_id); setRef(r.ra_id ? String(r.ra_id) : ""); setSummary(r.summary); }).catch((e) => notify(e.message, true));
  }, [gameId]);

  const link = () =>
    api.saveGameRa(gameId, ref).then((r) => {
      setLinked(r.ra_id);
      setRef(r.ra_id ? String(r.ra_id) : "");
      notify(r.ra_id ? "Jogo vinculado." : "Vínculo removido.");
      // a new or removed link must not keep showing the old game's result
      return api.gameRa(gameId).then((g) => { setSummary(g.summary); onSynced(); });
    }).catch((e) => notify(e.message, true));
  const sync = () => {
    setBusy(true);
    api.syncGameRa(gameId).then((s) => { setSummary(s); notify(`Conquistas: ${achievementText(s)}.`); onSynced(); })
      .catch((e) => notify(e.message, true)).finally(() => setBusy(false));
  };

  return (
    <div className="card">
      <h3>Conquistas (RetroAchievements)</h3>
      <div className="row">
        <div className="grow">
          <label>ID do jogo no RetroAchievements ou endereço da página dele</label>
          <input aria-label="ID do jogo no RetroAchievements" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="1234 ou retroachievements.org/game/1234" />
        </div>
        <button onClick={link}>Salvar vínculo</button>
        <button onClick={sync} disabled={busy || linked === null}>{busy ? "Sincronizando…" : "Sincronizar"}</button>
      </div>
      <p>
        {summary ? <>Conquistas: <strong>{achievementText(summary)}</strong>{summary.title && <> em "{summary.title}"</>}. Última sincronização: {localTime(summary.synced_at)}.</> : "Ainda não sincronizado."}
      </p>
      <p className="muted">
        Isso mede conquistas ganhas, não o quanto da história você já jogou: esse é o trabalho da fusão de sinais, mais adiante.
        O ID aparece no endereço da página do jogo no site. Confira que a página é a da versão certa (por exemplo, GameCube).
      </p>
    </div>
  );
}
