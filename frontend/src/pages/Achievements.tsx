import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, CheckCircle2, KeyRound, RefreshCw, ScanSearch, Search, ShieldAlert, ShieldCheck, Trophy, X } from "lucide-react";
import type { Ctx } from "../App";
import { AchievementSummary, api, DolphinRa, Game, RaSyncResult } from "../api";
import { collectEditions, editionTitle } from "../collection";
import { Cover, Eye, localDate, platformName, splitTitle } from "../ui";

type Filter = "all" | "synced" | "linked" | "unlinked";

type EditionRow = {
  id: number;
  game: Game;
  name: string;
  platform: string | null;
  linked: boolean;
  summary: AchievementSummary | null;
  percent: number;
};

export function Achievements({ games, info, notify, refresh }: Ctx) {
  const [user, setUser] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [dolphin, setDolphin] = useState<DolphinRa | null>(null);
  const [busy, setBusy] = useState<"" | "detect" | "sync">("");
  const [results, setResults] = useState<{ kind: "detect" | "sync"; rows: RaSyncResult[] } | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    api.raSettings().then((s) => { setUser(s.user); setHasKey(s.has_key); }).catch((e) => notify(e.message, true));
    if (info?.detected) api.dolphinRa().then(setDolphin).catch(() => undefined);
  }, [info?.detected, notify]);

  const batch = (kind: "detect" | "sync") => {
    setBusy(kind);
    (kind === "detect" ? api.detectAllRa() : api.syncAllRa())
      .then((rows) => { setResults({ kind, rows }); refresh().catch(() => undefined); })
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(""));
  };

  const rows = useMemo<EditionRow[]>(() => {
    return collectEditions(games)
      .filter(([g]) => g.identified)
      .map((discs) => {
        const game = discs.find((d) => d.playing) ?? discs[0];
        const linked = discs.some((d) => d.ra_id !== null);
        const summary = discs.map((d) => d.achievements).filter((a) => a !== null)
          .sort((a, b) => (b!.synced_at ?? "").localeCompare(a!.synced_at ?? ""))[0] ?? null;
        const percent = summary && summary.total > 0 ? Math.round((summary.earned / summary.total) * 100) : 0;
        return {
          id: game.id,
          game,
          name: splitTitle(discs.length > 1 ? editionTitle(game.title) : game.title).name,
          platform: game.platform,
          linked,
          summary,
          percent,
        };
      })
      .sort((a, b) => {
        const rank = (r: EditionRow) => (r.summary ? 2 : r.linked ? 1 : 0);
        if (rank(b) !== rank(a)) return rank(b) - rank(a);
        if (b.percent !== a.percent) return b.percent - a.percent;
        return a.name.localeCompare(b.name, "pt-BR");
      });
  }, [games]);

  const totalEarned = rows.reduce((s, r) => s + (r.summary?.earned ?? 0), 0);
  const totalPossible = rows.reduce((s, r) => s + (r.summary?.total ?? 0), 0);
  const totalPoints = rows.reduce((s, r) => s + (r.summary?.points_earned ?? 0), 0);
  const totalPointsMax = rows.reduce((s, r) => s + (r.summary?.points_total ?? 0), 0);
  const totalHardcore = rows.reduce((s, r) => s + (r.summary?.earned_hardcore ?? 0), 0);
  const linkedCount = rows.filter((r) => r.linked).length;
  const syncedCount = rows.filter((r) => r.summary !== null).length;

  const needle = query.trim().toLocaleLowerCase();
  const visible = rows.filter((r) => {
    if (filter === "synced" && !r.summary) return false;
    if (filter === "linked" && !r.linked) return false;
    if (filter === "unlinked" && r.linked) return false;
    if (needle && !(r.name + " " + platformName(r.platform)).toLocaleLowerCase().includes(needle)) return false;
    return true;
  });

  const accountReady = !!user.trim() && hasKey;

  return (
    <div className="act-stack">
      <section className="panel act-ach-hero" aria-label="Resumo de conquistas">
        <Eye value={totalEarned} total={totalPossible} label="conquistas" gold />

        <div className="act-ach-summary">
          <div className="kicker"><span className="signal" />RetroAchievements</div>
          <h2>
            {totalPossible > 0
              ? <span className="num">{totalEarned} de {totalPossible} conquistas</span>
              : linkedCount > 0
                ? "Jogos vinculados prontos para sincronizar"
                : "Nenhuma conquista sincronizada ainda"}
          </h2>
          <div className="facts act-ach-facts">
            <div className="fact">
              <span className="eyebrow">Jogos vinculados</span>
              <b className="num">{linkedCount} <small>de {rows.length}</small></b>
            </div>
            <div className="fact">
              <span className="eyebrow">Pontos</span>
              <b className="num">{totalPoints}{totalPointsMax > 0 ? <small> / {totalPointsMax}</small> : null}</b>
            </div>
            <div className="fact">
              <span className="eyebrow">Hardcore</span>
              <b className="num">{totalHardcore}</b>
            </div>
          </div>
        </div>

        <div className="act-ach-controls">
          <div className="act-status-row">
            <a className={`act-status-chip ${accountReady ? "ok" : "warn"}`} href="#/accounts">
              {accountReady ? <CheckCircle2 size={14} aria-hidden="true" /> : <KeyRound size={14} aria-hidden="true" />}
              {accountReady ? `Conta @${user}` : "Conta não configurada"}
            </a>
            {info?.detected && (
              <a className={`act-status-chip ${dolphin?.logged_in ? "ok" : "warn"}`} href="#/accounts">
                {dolphin?.logged_in ? <ShieldCheck size={14} aria-hidden="true" /> : <ShieldAlert size={14} aria-hidden="true" />}
                {dolphin?.logged_in ? `Dolphin: ${dolphin.user}` : "Dolphin desconectado"}
              </a>
            )}
          </div>

          <div className="act-ach-actions">
            {accountReady ? (
              <>
                <button className="btn primary" onClick={() => batch("sync")} disabled={busy !== ""}>
                  <RefreshCw className={busy === "sync" ? "spin" : undefined} /> {busy === "sync" ? "Sincronizando…" : "Sincronizar todos"}
                </button>
                <button className="btn" onClick={() => batch("detect")} disabled={busy !== ""}>
                  <ScanSearch /> {busy === "detect" ? "Detectando…" : "Detectar jogos"}
                </button>
                <a className="text-link" href="#/accounts">Gerenciar conta <ArrowUpRight size={15} /></a>
              </>
            ) : (
              <>
                <a className="btn primary" href="#/accounts"><KeyRound size={15} /> Configurar na Oficina</a>
                <button className="btn" onClick={() => batch("detect")} disabled={busy !== ""}>
                  <ScanSearch /> {busy === "detect" ? "Detectando…" : "Detectar jogos"}
                </button>
              </>
            )}
          </div>
        </div>
      </section>

      {results && (
        <section className="panel act-batch-results" aria-label="Resultado da operação">
          <header>
            <div>
              <h3>{results.kind === "detect" ? "Detecção concluída" : "Sincronização concluída"}</h3>
              <p>{results.rows.length === 0
                ? (results.kind === "detect" ? "Nenhum jogo sem vínculo para detectar." : "Nenhum jogo vinculado ainda.")
                : `${results.rows.filter((r) => r.ok).length} de ${results.rows.length} jogos atualizados.`}
              </p>
            </div>
            <button className="btn ghost icon" aria-label="Fechar resultado" onClick={() => setResults(null)}><X /></button>
          </header>
          {results.rows.length > 0 && (
            <ul className="list-plain act-batch-list">
              {results.rows.map((r) => (
                <li key={r.game_id}>
                  <span className={`status-dot ${r.ok ? "on" : "off"}`} />
                  <a href={`#/game/${r.game_id}`}>{splitTitle(r.title).name}</a>
                  <span className="muted"> · {r.message}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="panel act-ach-ledger" aria-label="Progresso por jogo">
        <header>
          <div>
            <h3>Progresso por jogo</h3>
            <p>Clique em um título para ver a lista completa de conquistas ou ajustar o vínculo.</p>
          </div>
          <span className="eyebrow num">{syncedCount} sincronizados · {linkedCount} vinculados</span>
        </header>

        <div className="act-ledger-tools">
          <label className="act-search">
            <Search size={16} aria-hidden="true" />
            <input data-search-input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar jogo ou plataforma" aria-label="Buscar jogo ou plataforma" />
          </label>
          <div className="seg" role="group" aria-label="Filtrar jogos">
            {([
              ["all", "Todos"],
              ["synced", "Sincronizados"],
              ["linked", "Vinculados"],
              ["unlinked", "Sem vínculo"],
            ] as [Filter, string][]).map(([key, label]) => (
              <button key={key} aria-pressed={filter === key} onClick={() => setFilter(key)}>{label}</button>
            ))}
          </div>
        </div>

        {visible.length === 0 ? (
          <p className="muted act-ledger-empty">
            {rows.length === 0
              ? "Adicione e escaneie jogos na Oficina para acompanhar suas conquistas."
              : "Nenhum jogo corresponde a esse filtro."}
          </p>
        ) : (
          <ul className="act-ledger-list">
            {visible.map((r) => (
              <li key={r.id}>
                <a className="act-ledger-row" href={`#/game/${r.id}`}>
                  <span className="act-session-cover"><Cover game={r.game} /></span>
                  <div className="act-ledger-info">
                    <strong>{r.name}</strong>
                    <small>
                      {platformName(r.platform)}
                      {r.summary?.synced_at ? ` · sincronizado em ${localDate(r.summary.synced_at)}` : r.linked ? " · vinculado, ainda não sincronizado" : " · sem vínculo"}
                    </small>
                  </div>
                  <div className="act-ledger-progress">
                    {r.summary ? (
                      <>
                        <div className="act-ledger-nums num">
                          <b><Trophy size={13} aria-hidden="true" /> {r.summary.earned}/{r.summary.total}</b>
                          <span>{r.percent}% · {r.summary.points_earned} pts</span>
                        </div>
                        <div className="meter" aria-hidden="true"><i className="gold" style={{ width: `${r.percent}%` }} /></div>
                      </>
                    ) : (
                      <span className={`ofc-pill ${r.linked ? "warn" : "muted"}`}>
                        {r.linked ? "Pronto para sincronizar" : "Sem vínculo"}
                      </span>
                    )}
                  </div>
                  <ArrowUpRight className="act-ledger-arrow" size={16} aria-hidden="true" />
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
