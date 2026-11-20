import { useEffect, useState } from "react";
import { LogOut, RefreshCw, ScanSearch } from "lucide-react";
import type { Ctx } from "../App";
import { api, DolphinRa, RaSyncResult } from "../api";
import { Field, Panel, splitTitle } from "../ui";

export function Achievements({ games, info, notify, refresh }: Ctx) {
  const [user, setUser] = useState("");
  const [key, setKey] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [dolphin, setDolphin] = useState<DolphinRa | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"" | "login" | "detect" | "sync">("");
  const [results, setResults] = useState<{ kind: "detect" | "sync"; rows: RaSyncResult[] } | null>(null);

  useEffect(() => {
    api.raSettings().then((s) => { setUser(s.user); setHasKey(s.has_key); }).catch((e) => notify(e.message, true));
    if (info?.detected) api.dolphinRa().then(setDolphin).catch(() => undefined);
  }, [info?.detected]);

  const saveAccount = () => api.saveRaSettings(user.trim(), key.trim() === "" ? null : key.trim())
    .then((s) => { setHasKey(s.has_key); setKey(""); notify("Conta do RetroAchievements salva."); })
    .catch((e) => notify(e.message, true));
  const removeKey = () => api.saveRaSettings(user.trim(), "").then((s) => { setHasKey(s.has_key); notify("Chave removida."); })
    .catch((e) => notify(e.message, true));
  const login = () => {
    setBusy("login");
    api.dolphinRaLogin(user.trim(), password)
      .then((s) => { setDolphin(s); notify(`Dolphin conectado ao RetroAchievements como ${s.user}.`); })
      .catch((e) => notify(e.message, true))
      .finally(() => { setPassword(""); setBusy(""); }); // the password never stays in the page
  };
  const logout = () => api.dolphinRaLogout().then((s) => { setDolphin(s); notify("Dolphin desconectado do RetroAchievements."); })
    .catch((e) => notify(e.message, true));
  const batch = (kind: "detect" | "sync") => {
    setBusy(kind);
    (kind === "detect" ? api.detectAllRa() : api.syncAllRa())
      .then((rows) => { setResults({ kind, rows }); refresh().catch(() => undefined); })
      .catch((e) => notify(e.message, true)).finally(() => setBusy(""));
  };

  const linked = games.filter((g) => g.ra_id !== null).length;
  const earned = games.reduce((a, g) => a + (g.achievements?.earned ?? 0), 0);

  return (
    <>
      <div className="kpis">
        <div className="kpi"><span className="eyebrow">Jogos vinculados</span><b>{linked}</b></div>
        <div className="kpi"><span className="eyebrow">Conquistas ganhas</span><b>{earned}</b></div>
        <div className="kpi"><span className="eyebrow">Dolphin</span>
          <b style={{ fontSize: 18 }}><span className={`status-dot ${dolphin?.logged_in ? "on" : "off"}`} />{dolphin?.logged_in ? `Logado como ${dolphin.user}` : "Não logado"}</b>
        </div>
      </div>

      <div className="account-layout">
        <Panel title="Sua conta" sub="Usuário do site e a chave de API (em retroachievements.org → Configurações). A chave fica só no seu computador.">
          <div className="form-grid">
            <Field label="Usuário"><input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" /></Field>
            <Field label="Chave de API" hint={hasKey ? "Já salva. Deixe em branco para manter." : undefined}>
              <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" placeholder={hasKey ? "••••••••" : ""} />
            </Field>
          </div>
          <div className="row" style={{ marginTop: 16 }}>
            <button className="btn primary" onClick={saveAccount} disabled={!user.trim()}>Salvar conta</button>
            {hasKey && <button className="btn ghost" onClick={removeKey}>Remover chave</button>}
          </div>
        </Panel>

        {info?.detected && (
          <Panel title="Login no Dolphin" sub="É o Dolphin quem ganha as conquistas enquanto você joga. A chave de API não serve para isso: o login usa sua senha uma vez, e o Dolphin guarda só um token."
            action={dolphin?.logged_in && <button className="btn ghost" onClick={logout} disabled={info.running}><LogOut /> Sair</button>}>
            {dolphin?.logged_in ? (
              <p className="note ok">Conectado como <b>{dolphin.user}</b>{dolphin.hardcore ? " · modo hardcore ligado" : ""}.</p>
            ) : (
              <div className="row">
                <div className="grow">
                  <Field label={`Senha do RetroAchievements${user ? ` de ${user}` : ""}`}>
                    <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
                      onKeyDown={(e) => { if (e.key === "Enter" && user.trim() && password) login(); }} />
                  </Field>
                </div>
                <button className="btn primary" onClick={login} disabled={!user.trim() || !password || busy !== "" || info.running}>
                  {busy === "login" ? "Entrando…" : "Conectar o Dolphin"}
                </button>
                <p className="row-hint" style={{ flexBasis: "100%" }}>A senha é usada só para este login e não é salva em lugar nenhum.</p>
              </div>
            )}
            {info.running && <p className="note warn" style={{ marginTop: 12 }}>Feche o Dolphin antes: ele regrava a configuração ao sair.</p>}
          </Panel>
        )}

        <Panel title="Biblioteca" sub="Detectar acha o jogo de cada disco no RetroAchievements (só o hash do disco é enviado). Sincronizar busca o que você já ganhou.">
          <div className="row">
            <button className="btn" onClick={() => batch("detect")} disabled={busy !== ""}><ScanSearch /> {busy === "detect" ? "Detectando…" : "Detectar todos os jogos"}</button>
            <button className="btn" onClick={() => batch("sync")} disabled={busy !== "" || !hasKey}><RefreshCw /> {busy === "sync" ? "Sincronizando…" : "Sincronizar todos"}</button>
          </div>
          {results && (
            <ul className="list-plain" style={{ marginTop: 16 }}>
              {results.rows.length === 0 && (
                <li className="muted">{results.kind === "detect" ? "Nenhum jogo sem vínculo para detectar." : "Nenhum jogo vinculado ainda."}</li>
              )}
              {results.rows.map((r) => (
                <li key={r.game_id}>
                  <span className={`status-dot ${r.ok ? "on" : "off"}`} />
                  <a href={`#/game/${r.game_id}`} style={{ color: "inherit" }}>{splitTitle(r.title).name}</a>
                  <span className="muted"> · {r.message}</span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </>
  );
}
