import { useEffect, useState } from "react";
import { ExternalLink, Info, Link2, RefreshCw, ScanSearch, ShieldCheck, Trophy } from "lucide-react";
import { AchievementSummary, api } from "../api";
import { Field, localTime, Notify } from "../ui";

export function GameAchievements({ gameId, notify, onChange }: {
  gameId: number; notify: Notify; onChange: (s: AchievementSummary | null) => void;
}) {
  const [ref, setRef] = useState("");
  const [linked, setLinked] = useState<number | null>(null);
  const [summary, setSummary] = useState<AchievementSummary | null>(null);
  const [busy, setBusy] = useState<"" | "detect" | "sync" | "link">("");
  const [openLink, setOpenLink] = useState(false);

  const show = (s: AchievementSummary | null) => { setSummary(s); onChange(s); };
  useEffect(() => {
    api.gameRa(gameId).then((r) => {
      setLinked(r.ra_id);
      setRef(r.ra_id ? String(r.ra_id) : "");
      setSummary(r.summary);
      setOpenLink(r.ra_id === null);
    }).catch((e) => notify(e.message, true));
  }, [gameId]);

  const run = (kind: "detect" | "sync" | "link", work: () => Promise<unknown>) => {
    setBusy(kind);
    work().catch((e) => notify(e.message, true)).finally(() => setBusy(""));
  };
  const detect = () => run("detect", async () => {
    const r = await api.detectGameRa(gameId);
    if (!r.found) { notify("O RetroAchievements não reconheceu este disco. Informe o ID à mão.", true); return; }
    setLinked(r.ra_id); setRef(String(r.ra_id)); setOpenLink(false);
    notify(`Encontrado: jogo ${r.ra_id} no RetroAchievements.`);
    show((await api.gameRa(gameId)).summary);
  });
  const link = () => run("link", async () => {
    const r = await api.saveGameRa(gameId, ref);
    setLinked(r.ra_id); setRef(r.ra_id ? String(r.ra_id) : "");
    if (r.ra_id !== null) setOpenLink(false);
    notify(r.ra_id ? "Jogo vinculado." : "Vínculo removido.");
    show((await api.gameRa(gameId)).summary);
  });
  const sync = () => run("sync", async () => show(await api.syncGameRa(gameId)));

  const pct = summary && summary.total > 0 ? Math.round((summary.earned / summary.total) * 100) : 0;

  return (
    <div className="gm-stack">
      <section className="panel gm-ach-hero" aria-label="Resumo do RetroAchievements">
        <div className="gm-ach-hero-top">
          <div className="gm-ach-hero-copy">
            <div className="kicker"><span className="signal" />RetroAchievements</div>
            <h3>
              {summary
                ? <span className="num">{summary.earned} de {summary.total} conquistas</span>
                : linked
                  ? "Vinculado, pronto para sincronizar"
                  : "Sem vínculo com o RetroAchievements"}
            </h3>
            <p className="muted">
              {summary
                ? <>Conjunto "{summary.title}" · sincronizado em {localTime(summary.synced_at)}.</>
                : linked
                  ? "Sincronize para baixar a lista de conquistas e o que você já ganhou."
                  : "Detecte automaticamente pelo hash do disco ou informe o ID do jogo no site."}
            </p>
          </div>

          <div className="gm-ach-hero-actions">
            <button type="button" className="btn primary" onClick={sync} disabled={busy !== "" || linked === null}>
              <RefreshCw className={busy === "sync" ? "spin" : undefined} /> {busy === "sync" ? "Sincronizando…" : "Sincronizar"}
            </button>
            <button type="button" className="btn ghost ofc-adv-btn" aria-expanded={openLink} onClick={() => setOpenLink((v) => !v)}>
              <Link2 size={15} /> {linked !== null ? `Vínculo #${linked}` : "Vincular"}
            </button>
          </div>
        </div>

        {summary && (
          <div className="gm-ach-progress">
            <div className="gm-ach-pills">
              <span className="ofc-pill ok num"><Trophy size={13} aria-hidden="true" /> {pct}% completo</span>
              <span className="ofc-pill muted num">{summary.points_earned} / {summary.points_total} pontos</span>
              {summary.earned_hardcore > 0 && (
                <span className="ofc-pill ok num"><ShieldCheck size={13} aria-hidden="true" /> {summary.earned_hardcore} hardcore</span>
              )}
            </div>
            <div className="meter gm-meter" aria-hidden="true"><i className="gold" style={{ width: `${pct}%` }} /></div>
          </div>
        )}

        {openLink && (
          <div className="gm-link-drawer">
            <div className="row">
              <div className="grow">
                <Field label="Jogo no RetroAchievements (número ou endereço da página)">
                  <input
                    value={ref}
                    onChange={(e) => setRef(e.target.value)}
                    placeholder="1234 ou retroachievements.org/game/1234"
                    onKeyDown={(e) => { if (e.key === "Enter" && busy === "") link(); }}
                  />
                </Field>
              </div>
              <button type="button" className="btn" onClick={detect} disabled={busy !== ""}>
                <ScanSearch /> {busy === "detect" ? "Detectando…" : "Detectar pelo disco"}
              </button>
              <button type="button" className="btn primary" onClick={link} disabled={busy !== ""}>Salvar vínculo</button>
            </div>
            {linked !== null && (
              <p className="muted gm-link-meta">
                Vinculado ao jogo{" "}
                <a href={`https://retroachievements.org/game/${linked}`} target="_blank" rel="noreferrer">
                  #{linked} <ExternalLink size={12} aria-hidden="true" />
                </a>
                . Confira no site se corresponde à mesma região/versão do seu disco.
              </p>
            )}
          </div>
        )}
      </section>

      <div className="note ofc-footnote">
        <Info size={16} aria-hidden="true" />
        <p>
          As conquistas são registradas pelo emulador logado (veja <a href="#/accounts">Oficina → RetroAchievements</a>) e sincronizadas automaticamente quando você fecha o jogo.
        </p>
      </div>
    </div>
  );
}
