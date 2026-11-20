import { useEffect, useState } from "react";
import { api, DolphinInfo, PackJob, Profile, VideoSettings, formatBytes } from "./api";

type Notify = (text: string, error?: boolean) => void;

const toTri = (v: boolean | undefined) => (v === undefined ? "" : String(v));
const fromTri = (s: string) => (s === "" ? undefined : s === "true");
const toNum = (v: number | undefined) => (v === undefined ? "" : String(v));
const fromNum = (s: string) => (s === "" ? undefined : Number(s));

function Tri({ label, value, onChange, on = "Ligado", off = "Desligado" }: {
  label: string; value: boolean | undefined; onChange: (v: boolean | undefined) => void; on?: string; off?: string;
}) {
  return (
    <div>
      <label>{label}</label>
      <select aria-label={label} value={toTri(value)} onChange={(e) => onChange(fromTri(e.target.value))}>
        <option value="">Padrão</option>
        <option value="true">{on}</option>
        <option value="false">{off}</option>
      </select>
    </div>
  );
}

export function VideoForm({ value, onChange, isDefault = false }: { value: VideoSettings; onChange: (v: VideoSettings) => void; isDefault?: boolean }) {
  const set = (patch: Partial<VideoSettings>) => onChange({ ...value, ...patch });
  // Measured on Dolphin 2609b: with OpenGL the game window loses its focus and key events
  // (Dolphin issue 13354). In the defaults form "Padrão" also means OpenGL; in a game it means "inherit".
  const openGl = value.backend === "OGL" || (isDefault && !value.backend);
  return (
    <>
    <div className="grid-form">
      <div>
        <label>Backend de vídeo</label>
        <select aria-label="Backend de vídeo" value={value.backend ?? ""}
          onChange={(e) => set({ backend: (e.target.value || undefined) as VideoSettings["backend"] })}>
          <option value="">Padrão do Dolphin</option>
          <option value="Vulkan">Vulkan</option>
          <option value="OGL">OpenGL</option>
        </select>
      </div>
      <div>
        <label>Placa de vídeo</label>
        <select aria-label="Placa de vídeo" value={value.gpu ?? ""}
          onChange={(e) => set({ gpu: (e.target.value || undefined) as VideoSettings["gpu"] })}>
          <option value="">Padrão do sistema</option>
          <option value="nvidia">NVIDIA (placa dedicada)</option>
        </select>
      </div>
      <div>
        <label>Resolução interna</label>
        <select aria-label="Resolução interna" value={toNum(value.internal_resolution)}
          onChange={(e) => set({ internal_resolution: fromNum(e.target.value) })}>
          <option value="">Padrão</option>
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <option key={n} value={n}>{n}x{n === 1 ? " (nativa)" : n === 3 ? " (~1080p)" : n === 6 ? " (~4K)" : ""}</option>
          ))}
        </select>
      </div>
      <div>
        <label>Filtragem anisotrópica</label>
        <select aria-label="Filtragem anisotrópica" value={toNum(value.anisotropy)}
          onChange={(e) => set({ anisotropy: fromNum(e.target.value) })}>
          <option value="">Padrão</option>
          {[0, 1, 2, 3, 4].map((n) => <option key={n} value={n}>{2 ** n}x</option>)}
        </select>
      </div>
      <Tri label="VSync" value={value.vsync} onChange={(vsync) => set({ vsync })} />
      <Tri label="Texturas HD (personalizadas)" value={value.hires_textures} onChange={(hires_textures) => set({ hires_textures })} />
      <Tri label="Pré-carregar texturas" value={value.prefetch_textures} onChange={(prefetch_textures) => set({ prefetch_textures })} />
    </div>
    <h4>Janela e entrada</h4>
    <p className="muted">
      Se o teclado parar de responder depois de você clicar fora do jogo e voltar (bug conhecido do Dolphin no Linux), teste
      estas opções, uma de cada vez. Valem para os jogos abertos pelo Argos e não mudam os arquivos do Dolphin.
    </p>
    <div className="grid-form">
      <Tri label="Renderizar na janela principal" value={value.render_to_main} onChange={(render_to_main) => set({ render_to_main })} />
      <Tri label="Entrada em segundo plano" value={value.background_input} onChange={(background_input) => set({ background_input })} />
      <Tri label="Manter janela no topo" value={value.keep_on_top} onChange={(keep_on_top) => set({ keep_on_top })} />
    </div>
    <p className="muted">
      Renderizar na janela principal: contorno que apareceu em relatos do mesmo bug; a janela do jogo é a principal do Dolphin e
      começa pequena. Não funciona com o argumento -b (o Argos recusa abrir assim). Entrada em segundo plano: o Dolphin deixa de exigir foco, mas o jogo pode reagir a teclas de outros
      programas. Manter no topo: citado como contorno, sem garantia.
    </p>
    {openGl && (
      <p className="muted">
        Atenção: no Dolphin 2609b o OpenGL tem um bug conhecido (issue 13354): depois que a janela do jogo perde o foco
        uma vez, o teclado pode parar de responder. Trocar para Vulkan não basta: o mesmo sintoma já apareceu com Vulkan.
      </p>
    )}
    </>
  );
}

const PRESET_LABELS: Record<string, string> = {
  keyboard_default: "Teclado e mouse (padrão do Dolphin)",
  keyboard_wasd: "Teclado e mouse (WASD)",
  xbox: "Controle de Xbox",
};

export function DolphinPanel({ info, notify, refreshInfo }: { info: DolphinInfo; notify: Notify; refreshInfo: () => void }) {
  const [defaults, setDefaults] = useState<VideoSettings>({});
  const [preset, setPreset] = useState("keyboard_default");
  const [device, setDevice] = useState("");

  useEffect(() => {
    api.dolphinDefaults().then(setDefaults).catch((e) => notify(String(e.message ?? e), true));
  }, []);
  useEffect(() => {
    if (!device && info.controllers[0]) setDevice(info.controllers[0].device);
  }, [info.controllers]);

  const wantsNvidia = info.gpus.some((g) => /nvidia/i.test(g));
  const save = () =>
    api.saveDolphinDefaults(defaults).then((v) => { setDefaults(v); notify("Padrões do Dolphin salvos."); }).catch((e) => notify(e.message, true));
  const apply = () =>
    api.saveControls(preset, preset === "xbox" ? device.trim() : null)
      .then((r) => { notify(`Controles aplicados (${r.device}).`); refreshInfo(); })
      .catch((e) => notify(e.message, true));

  return (
    <section>
      <h2>Dolphin</h2>
      <p className="muted">
        Placas de vídeo: {info.gpus.length ? info.gpus.join(" · ") : "não consegui listar"}.
        {wantsNvidia && info.flatpak && info.nvidia_ready === false &&
          " A extensão NVIDIA do Flatpak não está instalada: a opção de placa NVIDIA pode não funcionar."}
      </p>
      {info.running && <div className="msg err">O Dolphin está aberto. Feche-o para mudar controles e texturas.</div>}

      <div className="card">
        <h3>Vídeo: padrão para todos os jogos</h3>
        <p className="muted">"Padrão" deixa o valor como o Dolphin já tem. Cada jogo pode mudar isso em "Ajustes".</p>
        <VideoForm value={defaults} onChange={setDefaults} isDefault />
        <p><button onClick={save}>Salvar padrões</button></p>
      </div>

      <div className="card">
        <h3>Controles (jogador 1)</h3>
        <div className="row">
          <div className="grow">
            <label>Tipo</label>
            <select aria-label="Tipo de controle" value={preset} onChange={(e) => setPreset(e.target.value)}>
              {info.presets.map((p) => <option key={p} value={p}>{PRESET_LABELS[p] ?? p}</option>)}
            </select>
          </div>
          {preset === "xbox" && (
            <div className="grow">
              <label>Dispositivo do controle</label>
              <input aria-label="Dispositivo do controle" list="controllers" value={device} onChange={(e) => setDevice(e.target.value)} placeholder="SDL/0/Xbox Wireless Controller" />
              <datalist id="controllers">{info.controllers.map((c) => <option key={c.device} value={c.device} />)}</datalist>
            </div>
          )}
          <div><button onClick={apply} disabled={info.running}>Aplicar</button></div>
        </div>
        <p className="muted">Dispositivo atual: {info.pad_device ?? "nenhum"}.</p>
        {preset === "xbox" && (
          <p className="muted">
            {info.controllers.length === 0
              ? "Nenhum controle detectado agora: conecte-o e recarregue a página. "
              : "O nome sugerido vem do sistema e pode diferir do que o Dolphin usa. "}
            Se o controle não responder no jogo, copie o nome exato que aparece em Controles do Dolphin.
          </p>
        )}
        <p className="muted">O arquivo anterior fica guardado como GCPadNew.ini.argos-bak (a primeira cópia nunca é sobrescrita). Não há mapeamento de mouse: o Dolphin não expõe esses nomes de forma que eu pudesse verificar.</p>
      </div>
    </section>
  );
}

export function GameSettings({ gameId, info, notify }: { gameId: number; info: DolphinInfo; notify: Notify }) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [mine, setMine] = useState<VideoSettings>({});
  const [archive, setArchive] = useState("");
  const [job, setJob] = useState<PackJob | null>(null);
  const [confirming, setConfirming] = useState(false);
  const load = () =>
    api.profile(gameId).then((p) => {
      setProfile(p);
      setMine(p.settings);
      // reopening the panel while an install runs must pick the progress up again
      api.packJob().then((j) => { if (j.state === "running" && j.game_id === p.game_code) setJob(j); }).catch(() => undefined);
    }).catch((e) => notify(e.message, true));

  useEffect(() => { load(); }, [gameId]);

  useEffect(() => {
    if (job?.state !== "running") return;
    const id = setInterval(() => {
      api.packJob().then((j) => {
        setJob(j);
        if (j.state !== "running") { load(); notify(j.message, j.state === "error"); }
      }).catch(() => undefined);
    }, 2000);
    return () => clearInterval(id);
  }, [job?.state]);

  if (!profile) return <p className="muted">Carregando…</p>;
  const t = profile.textures;
  const install = () =>
    api.installTextures(gameId, archive.trim())
      .then(() => setJob({ state: "running", message: "Extraindo o pacote…", game_id: profile.game_code }))
      .catch((e) => notify(e.message, true));
  const remove = () => {
    setConfirming(false);
    api.removeTextures(gameId).then(() => { notify("Pacote removido."); load(); }).catch((e) => notify(e.message, true));
  };

  return (
    <div className="card">
      <h3>Vídeo deste jogo</h3>
      <p className="muted">"Padrão" usa o valor da seção Dolphin. ID do jogo: {profile.game_code ?? "não consegui ler"}.</p>
      {profile.game_code === null && (
        <div className="msg err">
          Não consegui ler o ID deste jogo (formatos como RVZ, WBFS e CISO não trazem o ID no começo do arquivo).
          Backend e placa de vídeo funcionam, mas resolução, anisotropia, VSync e texturas não serão aplicados.
        </div>
      )}
      <VideoForm value={mine} onChange={setMine} />
      <p>
        <button onClick={() => api.saveProfile(gameId, mine).then((v) => { setMine(v); notify("Ajustes do jogo salvos."); load(); }).catch((e) => notify(e.message, true))}>
          Salvar ajustes do jogo
        </button>
      </p>

      <h3>Pacote de texturas HD</h3>
      {t === null ? <p className="muted">Sem ID de jogo, não dá para gerenciar texturas.</p> : (
        <>
          <p>{t.installed ? `Instalado em ${t.folder}/: ${t.files} arquivos, ${formatBytes(t.bytes)}.` : "Nenhum pacote instalado."}</p>
          <div className="row">
            <div className="grow">
              <label>Arquivo do pacote (.zip, .7z, .rar; caminho absoluto)</label>
              <input aria-label="Arquivo do pacote de texturas" value={archive} onChange={(e) => setArchive(e.target.value)} placeholder="/caminho/do/pacote.zip" />
            </div>
            <button onClick={install} disabled={!archive.trim() || info.running || job?.state === "running" || !info.seven_zip}>
              {t.installed ? "Reinstalar" : "Instalar"}
            </button>
            {t.installed && !confirming && (
              <button onClick={() => setConfirming(true)} disabled={info.running || job?.state === "running"}>Remover</button>
            )}
            {t.installed && confirming && (
              <>
                <button onClick={remove}>Confirmar remoção</button>
                <button onClick={() => setConfirming(false)}>Cancelar</button>
              </>
            )}
          </div>
          {!info.seven_zip && <p className="muted">Instale o p7zip (comando 7z) para extrair pacotes.</p>}
          {job?.state === "running" && <p>{job.message} Pode levar alguns minutos para pacotes grandes.</p>}
          <p className="muted">O pacote precisa ter a pasta com o ID do jogo ({profile.game_code?.slice(0, 3)}/ ou {profile.game_code}/). Pacotes de outro jogo são recusados.</p>
        </>
      )}
    </div>
  );
}
