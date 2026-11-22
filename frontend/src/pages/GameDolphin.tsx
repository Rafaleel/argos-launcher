import { useEffect, useState } from "react";
import { FolderOpen, Trash2 } from "lucide-react";
import { api, DolphinInfo, formatBytes, inDesktop, PackJob, Profile, VideoSettings } from "../api";
import { pickArchive } from "../pickers";
import { Field, Notify, Panel, Select, Tri } from "../ui";

const num = (v: number | undefined) => (v === undefined ? "" : String(v));
const fromNum = (s: string) => (s === "" ? undefined : Number(s));

/** Video and window options. "Padrão" inherits: from Dolphin for the defaults, from the defaults for a game. */
export function VideoForm({ value, onChange, inherit, grouped = false }: {
  value: VideoSettings; onChange: (v: VideoSettings) => void; inherit: string; grouped?: boolean;
}) {
  const set = (patch: Partial<VideoSettings>) => onChange({ ...value, ...patch });
  const renderFields = (
    <>
      <Field label="Backend de vídeo">
        <Select value={value.backend ?? ""} label="Backend de vídeo" onChange={(v) => set({ backend: (v || undefined) as VideoSettings["backend"] })}
          options={[{ value: "", label: inherit }, { value: "Vulkan", label: "Vulkan" }, { value: "OGL", label: "OpenGL" }]} />
      </Field>
      <Field label="Placa de vídeo">
        <Select value={value.gpu ?? ""} label="Placa de vídeo" onChange={(v) => set({ gpu: (v || undefined) as VideoSettings["gpu"] })}
          options={[{ value: "", label: inherit }, { value: "nvidia", label: "NVIDIA (dedicada)" }]} />
      </Field>
    </>
  );
  const qualityFields = (
    <>
      <Field label="Resolução interna">
        <Select value={num(value.internal_resolution)} label="Resolução interna" onChange={(v) => set({ internal_resolution: fromNum(v) })}
          options={[{ value: "", label: inherit }, ...[1, 2, 3, 4, 5, 6].map((n) => ({ value: String(n), label: `${n}x${n === 1 ? " · nativa" : n === 3 ? " · ~1080p" : n === 6 ? " · ~4K" : ""}` }))]} />
      </Field>
      <Field label="Filtragem anisotrópica">
        <Select value={num(value.anisotropy)} label="Filtragem anisotrópica" onChange={(v) => set({ anisotropy: fromNum(v) })}
          options={[{ value: "", label: inherit }, ...[0, 1, 2, 3, 4].map((n) => ({ value: String(n), label: `${2 ** n}x` }))]} />
      </Field>
      <Tri label="VSync" value={value.vsync} onChange={(vsync) => set({ vsync })} />
      <Tri label="Texturas HD" value={value.hires_textures} onChange={(hires_textures) => set({ hires_textures })} />
      <Tri label="Pré-carregar texturas" value={value.prefetch_textures} onChange={(prefetch_textures) => set({ prefetch_textures })} />
    </>
  );

  return (
    <div className="stack">
      {grouped ? (
        <div className="ofc-video-groups">
          <div className="ofc-field-group">
            <span className="eyebrow">Renderização</span>
            <div className="form-grid">{renderFields}</div>
          </div>
          <div className="ofc-field-group">
            <span className="eyebrow">Imagem e texturas</span>
            <div className="form-grid">{qualityFields}</div>
          </div>
        </div>
      ) : (
        <div className="form-grid">
          {renderFields}
          {qualityFields}
        </div>
      )}
      <details className={grouped ? "ofc-disclosure" : undefined}>
        <summary>Janela e teclado</summary>
        <div className="stack" style={{ marginTop: 14 }}>
          <p className="muted" style={{ fontSize: 13 }}>
            Se o teclado parar depois de clicar fora do jogo e voltar (defeito conhecido do Dolphin no Linux), teste uma opção por vez.
          </p>
          <div className="form-grid">
            <Tri label="Entrada em segundo plano" value={value.background_input} onChange={(background_input) => set({ background_input })}
              hint="O jogo também ouve teclas de outros programas." />
            <Tri label="Manter janela no topo" value={value.keep_on_top} onChange={(keep_on_top) => set({ keep_on_top })} />
            <Tri label="Renderizar na janela principal" value={value.render_to_main} onChange={(render_to_main) => set({ render_to_main })}
              hint="Não funciona com o modo -b, que o Argos usa por padrão." />
          </div>
        </div>
      </details>
    </div>
  );
}

export function GameVideo({ gameId, notify }: { gameId: number; notify: Notify }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [mine, setMine] = useState<VideoSettings>({});
  useEffect(() => {
    api.profile(gameId).then((p) => { setProfile(p); setMine(p.settings); }).catch((e) => notify(e.message, true));
  }, [gameId]);
  if (!profile) return <p className="muted">Carregando…</p>;
  const save = () => api.saveProfile(gameId, mine).then((v) => { setMine(v); notify("Ajustes do jogo salvos. Valem na próxima vez que ele abrir."); })
    .catch((e) => notify(e.message, true));
  return (
    <Panel title="Vídeo deste jogo" sub={<>"Padrão" usa o que está em Oficina → Emuladores → Dolphin. ID do disco: {profile.game_code ?? "não lido"}.</>}
      action={<button className="btn primary" onClick={save}>Salvar</button>}>
      {profile.game_code === null && (
        <p className="note warn" style={{ marginBottom: 16 }}>
          Não consegui ler o ID do disco: backend e placa funcionam, mas resolução, anisotropia, VSync e texturas não serão aplicados.
        </p>
      )}
      <VideoForm value={mine} onChange={setMine} inherit="Padrão" />
    </Panel>
  );
}

export function GameTextures({ gameId, info, notify }: { gameId: number; info: DolphinInfo; notify: Notify }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [archive, setArchive] = useState("");
  const [job, setJob] = useState<PackJob | null>(null);
  const [confirming, setConfirming] = useState(false);
  const load = () => api.profile(gameId).then((p) => {
    setProfile(p);
    api.packJob().then((j) => { if (j.state === "running" && j.game_id === p.game_code) setJob(j); }).catch(() => undefined);
  }).catch((e) => notify(e.message, true));
  useEffect(() => { load(); }, [gameId]);
  useEffect(() => {
    if (job?.state !== "running") return;
    const id = setInterval(() => api.packJob().then((j) => {
      setJob(j);
      if (j.state !== "running") { load(); notify(j.message, j.state === "error"); }
    }).catch(() => undefined), 2000);
    return () => clearInterval(id);
  }, [job?.state]);

  if (!profile) return <p className="muted">Carregando…</p>;
  const t = profile.textures;
  if (t === null) return <p className="note warn">Sem o ID do disco não dá para gerenciar texturas.</p>;
  const running = job?.state === "running";
  const install = (path: string) => api.installTextures(gameId, path.trim())
    .then(() => setJob({ state: "running", message: "Extraindo o pacote…", game_id: profile.game_code }))
    .catch((e) => notify(e.message, true));
  const choose = async () => { const p = await pickArchive("Escolha o pacote de texturas"); if (p) { setArchive(p); install(p); } };
  const remove = () => { setConfirming(false); api.removeTextures(gameId).then(() => { notify("Pacote removido."); load(); }).catch((e) => notify(e.message, true)); };

  return (
    <Panel title={t.installed ? "Pacote instalado" : "Nenhum pacote instalado"}
      sub={t.installed ? <span className="num">Pasta {t.folder}/ · {t.files} arquivos · {formatBytes(t.bytes)}</span>
        : <>O pacote precisa ter a pasta {profile.game_code?.slice(0, 3)}/ ou {profile.game_code}/. Pacotes de outro jogo são recusados.</>}
      action={t.installed && (!confirming
        ? <button className="btn danger" onClick={() => setConfirming(true)} disabled={info.running || running}><Trash2 /> Remover</button>
        : <div className="row"><button className="btn danger" onClick={remove}>Confirmar remoção</button><button className="btn ghost" onClick={() => setConfirming(false)}>Cancelar</button></div>)}>
      {info.running && <p className="note warn" style={{ marginBottom: 12 }}>Feche o Dolphin para instalar ou remover pacotes.</p>}
      {!info.seven_zip && <p className="note warn" style={{ marginBottom: 12 }}>Instale o p7zip (comando 7z) para extrair pacotes.</p>}
      {running ? <p className="note ok">{job?.message} Pacotes grandes levam alguns minutos.</p> : inDesktop ? (
        <button className="btn primary" onClick={choose} disabled={info.running || !info.seven_zip}>
          <FolderOpen /> {t.installed ? "Trocar pacote…" : "Escolher pacote (.zip, .7z, .rar)…"}
        </button>
      ) : (
        <div className="row">
          <div className="grow">
            <Field label="Caminho do pacote"><input value={archive} onChange={(e) => setArchive(e.target.value)} placeholder="/caminho/do/pacote.zip" /></Field>
          </div>
          <button className="btn primary" onClick={() => install(archive)} disabled={!archive.trim() || info.running || !info.seven_zip}>Instalar</button>
        </div>
      )}
    </Panel>
  );
}
