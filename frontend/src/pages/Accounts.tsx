import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, KeyRound, LogOut, ShieldAlert, ShieldCheck, Trophy } from "lucide-react";
import type { Ctx } from "../App";
import { api, DolphinRa } from "../api";
import { Field, Panel } from "../ui";

export function Accounts({ info, notify }: Ctx) {
  const [user, setUser] = useState("");
  const [savedUser, setSavedUser] = useState("");
  const [key, setKey] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [dolphin, setDolphin] = useState<DolphinRa | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "login">("");

  useEffect(() => {
    api.raSettings().then((s) => { setUser(s.user); setSavedUser(s.user); setHasKey(s.has_key); }).catch((e) => notify(e.message, true));
    if (info?.detected) api.dolphinRa().then(setDolphin).catch(() => undefined);
  }, [info?.detected, notify]);

  const saveAccount = () => {
    setBusy("save");
    api.saveRaSettings(user.trim(), key.trim() === "" ? null : key.trim())
      .then((s) => { setSavedUser(s.user); setHasKey(s.has_key); setKey(""); notify("Conta do RetroAchievements salva."); })
      .catch((e) => notify(e.message, true))
      .finally(() => setBusy(""));
  };

  const removeKey = () => api.saveRaSettings(user.trim(), "")
    .then((s) => { setSavedUser(s.user); setHasKey(s.has_key); notify("Chave removida."); })
    .catch((e) => notify(e.message, true));

  const login = () => {
    setBusy("login");
    api.dolphinRaLogin(user.trim(), password)
      .then((s) => { setDolphin(s); notify(`Dolphin conectado ao RetroAchievements como ${s.user}.`); })
      .catch((e) => notify(e.message, true))
      .finally(() => { setPassword(""); setBusy(""); }); // the password never stays in the page
  };

  const logout = () => api.dolphinRaLogout()
    .then((s) => { setDolphin(s); notify("Dolphin desconectado do RetroAchievements."); })
    .catch((e) => notify(e.message, true));

  const accountReady = !!savedUser && hasKey;

  return (
    <div className="ofc-stack">
      <section className="panel ofc-ra-hero" aria-label="Status do RetroAchievements">
        <div className="ofc-ra-hero-copy">
          <div className="kicker"><span className="signal" />Integração opcional</div>
          <h2>RetroAchievements</h2>
          <p className="muted">
            Conecte sua conta para sincronizar conquistas no Argos e autorizar o Dolphin a registrá-las enquanto você joga.
            As credenciais ficam apenas no seu computador.
          </p>
        </div>
        <div className="ofc-ra-badges">
          <div className={`ofc-badge ${accountReady ? "ok" : "warn"}`}>
            {accountReady ? <CheckCircle2 size={15} aria-hidden="true" /> : <KeyRound size={15} aria-hidden="true" />}
            <div>
              <span>Chave da API</span>
              <strong>{accountReady ? `@${savedUser}` : "Não configurada"}</strong>
            </div>
          </div>
          {info?.detected && (
            <div className={`ofc-badge ${dolphin?.logged_in ? "ok" : "warn"}`}>
              {dolphin?.logged_in ? <ShieldCheck size={15} aria-hidden="true" /> : <ShieldAlert size={15} aria-hidden="true" />}
              <div>
                <span>Dolphin</span>
                <strong>{dolphin?.logged_in ? dolphin.user : "Desconectado"}</strong>
              </div>
            </div>
          )}
        </div>
      </section>

      <div className="ofc-ra-grid">
        <Panel
          title="Conta da API Web"
          sub="Usuário do site e chave de API (em retroachievements.org → Configurações). Usada pelo Argos para buscar conquistas e progresso."
          action={<span className={`ofc-pill ${accountReady ? "ok" : "muted"}`}>{accountReady ? "Configurada" : "Pendente"}</span>}
        >
          <div className="ofc-form-stack">
            <Field label="Usuário">
              <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" placeholder="seu_usuario" />
            </Field>
            <Field label="Chave de API" hint={hasKey ? "Já salva localmente. Deixe em branco para manter." : "Nunca é exibida de volta depois de salva."}>
              <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" placeholder={hasKey ? "••••••••••••" : "Cole sua chave de API"} />
            </Field>
            <div className="row ofc-actions">
              <button type="button" className="btn primary" onClick={saveAccount} disabled={!user.trim() || busy !== ""}>
                {busy === "save" ? "Salvando…" : "Salvar conta"}
              </button>
              {hasKey && <button type="button" className="btn ghost" onClick={removeKey} disabled={!user.trim() || busy !== ""}>Remover chave</button>}
            </div>
          </div>
        </Panel>

        <Panel
          title="Login no Dolphin"
          sub="Quem ganha as conquistas durante o jogo é o Dolphin. A chave de API não serve para isso: o login usa sua senha uma vez e grava apenas um token no emulador."
          action={info?.detected && dolphin?.logged_in
            ? <button className="btn ghost" onClick={logout} disabled={info.running}><LogOut /> Sair</button>
            : info?.detected
              ? <span className="ofc-pill warn">Desconectado</span>
              : undefined}
        >
          {!info?.detected ? (
            <div className="note">
              Nenhum Dolphin detectado nesta máquina. Configure um emulador em <a href="#/emulators">Oficina → Emuladores</a> para habilitar o login direto.
            </div>
          ) : dolphin?.logged_in ? (
            <div className="ofc-connected-box">
              <p className="note ok">
                Conectado como <b>{dolphin.user}</b>{dolphin.hardcore ? " · modo hardcore ligado" : ""}.
              </p>
              {info.running && <p className="note warn">Feche o Dolphin antes de desconectar: ele regrava a configuração ao sair.</p>}
            </div>
          ) : (
            <div className="ofc-form-stack">
              <Field
                label={`Senha do RetroAchievements${user.trim() ? ` de ${user.trim()}` : ""}`}
                hint={user.trim() ? "A senha é usada só para este login e não é salva em lugar nenhum." : "Informe seu usuário no cartão ao lado antes de conectar."}
              >
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder="Digite sua senha"
                  onKeyDown={(e) => { if (e.key === "Enter" && user.trim() && password && busy === "" && !info.running) login(); }}
                />
              </Field>
              <div className="row ofc-actions">
                <button className="btn primary" onClick={login} disabled={!user.trim() || !password || busy !== "" || info.running}>
                  {busy === "login" ? "Entrando…" : "Conectar o Dolphin"}
                </button>
              </div>
              {info.running && <p className="note warn">Feche o Dolphin antes: ele regrava a configuração ao sair.</p>}
            </div>
          )}
        </Panel>
      </div>

      <div className="ofc-bridge">
        <div>
          <span className="eyebrow"><Trophy size={13} aria-hidden="true" /> Próximo passo</span>
          <p>Depois de salvar sua conta, acompanhe o progresso e sincronize seus jogos na aba de Conquistas.</p>
        </div>
        <a className="btn" href="#/achievements">Ir para Atividade → Conquistas <ArrowRight size={15} /></a>
      </div>
    </div>
  );
}
