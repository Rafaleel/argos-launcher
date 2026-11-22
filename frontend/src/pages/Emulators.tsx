import { useEffect, useState } from "react";
import { Check, Cpu, Gamepad2, Keyboard, Monitor, RotateCcw, SlidersHorizontal } from "lucide-react";
import type { Ctx } from "../App";
import { api, DolphinInfo, Emulator, EmulatorOption, VideoSettings } from "../api";
import { Field, Notify, Panel, platformName, Select } from "../ui";
import { hasVideoOverrides, VideoForm } from "./GameDolphin";

const same = (e: Emulator | undefined, o: EmulatorOption) =>
  !!e && e.executable === o.executable && JSON.stringify(e.args) === JSON.stringify(o.args);

const VIDEO_KEYS: (keyof VideoSettings)[] = [
  "backend", "gpu", "internal_resolution", "anisotropy",
  "vsync", "hires_textures", "prefetch_textures",
  "render_to_main", "background_input", "keep_on_top",
];

function sameVideo(a: VideoSettings, b: VideoSettings): boolean {
  return VIDEO_KEYS.every((k) => (a[k] ?? undefined) === (b[k] ?? undefined));
}

function PlatformRow({ platform, current, options, onSaved, notify }: {
  platform: string; current?: Emulator; options: EmulatorOption[]; onSaved: () => void; notify: Notify;
}) {
  const [exe, setExe] = useState(current?.executable ?? "");
  const [args, setArgs] = useState((current?.args ?? ["{rom}"]).join("\n"));
  const [openAdv, setOpenAdv] = useState(false);

  useEffect(() => {
    setExe(current?.executable ?? "");
    setArgs((current?.args ?? ["{rom}"]).join("\n"));
  }, [current]);

  useEffect(() => {
    if (!openAdv) return;
    const onKey = (e: KeyboardEvent) => { if (!e.defaultPrevented && e.key === "Escape") setOpenAdv(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openAdv]);

  const chosen = options.findIndex((o) => same(current, o));
  const activeName = chosen >= 0 ? options[chosen].name : current ? current.executable : null;

  const save = (e: Emulator, closeAfter = false) => api.saveEmulator(e)
    .then(() => {
      notify(`Emulador de ${platformName(platform)} salvo.`);
      if (closeAfter) setOpenAdv(false);
      onSaved();
    })
    .catch((err) => notify(err.message, true));

  return (
    <div className="ofc-plat-item">
      <div className="ofc-plat-row">
        <div className="ofc-plat-meta">
          <div className="ofc-plat-title">
            <h4>{platformName(platform)}</h4>
            <span className={`ofc-pill ${current ? "ok" : "warn"}`}>
              <span className={`status-dot ${current ? "on" : "off"}`} />
              {current ? "Pronto" : "Sem emulador"}
            </span>
          </div>
          {activeName && <code className="ofc-plat-cmd" title={activeName}>{activeName}</code>}
        </div>

        <div className="ofc-plat-controls">
          {options.length > 0 ? (
            <Select
              label={`Emulador de ${platformName(platform)}`}
              value={chosen >= 0 ? String(chosen) : "custom"}
              onChange={(v) => { const o = options[Number(v)]; if (o) save({ platform, executable: o.executable, args: o.args }); }}
              options={[
                ...(chosen < 0 ? [{ value: "custom", label: current ? "Personalizado" : "Escolha um emulador" }] : []),
                ...options.map((o, i) => ({ value: String(i), label: o.name })),
              ]}
            />
          ) : (
            <span className="muted ofc-plat-none">Nenhum emulador instalado foi detectado.</span>
          )}
          <button
            type="button"
            className="btn ghost ofc-adv-btn"
            aria-expanded={openAdv}
            onClick={() => setOpenAdv((v) => !v)}
          >
            <SlidersHorizontal size={15} /> Avançado
          </button>
        </div>
      </div>

      {openAdv && (
        <div className="ofc-plat-adv">
          <div className="ofc-plat-adv-grid">
            <Field label="Executável (caminho absoluto)">
              <input value={exe} onChange={(e) => setExe(e.target.value)} placeholder="/usr/bin/flatpak" />
            </Field>
            <Field label="Argumentos (um por linha)" hint="{rom} vira o caminho do jogo.">
              <textarea rows={3} value={args} onChange={(e) => setArgs(e.target.value)} />
            </Field>
          </div>
          <div className="row ofc-actions">
            <button
              className="btn primary"
              onClick={() => save({ platform, executable: exe.trim(), args: args.split("\n").map((a) => a.trim()).filter(Boolean) }, true)}
              disabled={!exe.trim()}
            >
              Salvar manualmente
            </button>
            <button className="btn ghost" onClick={() => setOpenAdv(false)}>Fechar</button>
          </div>
        </div>
      )}
    </div>
  );
}

const PRESETS: Record<string, { label: string; hint: string; icon: typeof Keyboard }> = {
  keyboard_default: { label: "Teclado · Dolphin", hint: "Mapeamento clássico padrão do Dolphin.", icon: Keyboard },
  keyboard_wasd: { label: "Teclado · WASD", hint: "Movimento em WASD para jogar sem controle.", icon: Keyboard },
  xbox: { label: "Controle", hint: "Xbox, PlayStation e outros gamepads SDL.", icon: Gamepad2 },
};

function DolphinWorkbench({ info, notify, refresh }: { info: DolphinInfo; notify: Notify; refresh: () => Promise<void> }) {
  const [tab, setTab] = useState<"video" | "controls">("video");
  const [defaults, setDefaults] = useState<VideoSettings>({});
  const [savedDefaults, setSavedDefaults] = useState<VideoSettings | null>(null);
  const [preset, setPreset] = useState(info.pad_device?.startsWith("SDL/") || info.controllers.length ? "xbox" : "keyboard_default");
  const [device, setDevice] = useState(info.pad_device?.startsWith("SDL/") ? info.pad_device : info.controllers[0]?.device ?? "");
  const [touched, setTouched] = useState(false); // once the user picks, detection stops choosing for them

  useEffect(() => {
    api.dolphinDefaults()
      .then((v) => { setDefaults(v); setSavedDefaults(v); })
      .catch((e) => notify(e.message, true));
  }, [notify]);

  // look for pads every few seconds, so turning one on is enough (no reload)
  useEffect(() => {
    const id = setInterval(() => { refresh().catch(() => undefined); }, 3000);
    return () => clearInterval(id);
  }, [refresh]);

  const found = info.controllers.map((c) => c.device).join("|");
  useEffect(() => {
    if (touched || !info.controllers.length) return;
    setPreset("xbox");
    if (!info.controllers.some((c) => c.device === device)) setDevice(info.controllers[0].device);
  }, [found]);

  const defaultsLoaded = savedDefaults !== null;
  const dirty = defaultsLoaded && !sameVideo(defaults, savedDefaults);
  const save = () => api.saveDolphinDefaults(defaults)
    .then((v) => { setDefaults(v); setSavedDefaults(v); notify("Padrões do Dolphin salvos."); })
    .catch((e) => notify(e.message, true));

  const effectiveDevice = device.trim() || info.controllers[0]?.device || "";
  const apply = () => api.saveControls(preset, preset === "xbox" ? effectiveDevice : null)
    .then((r) => { notify(`Controles aplicados (${r.device}).`); refresh().catch(() => undefined); })
    .catch((e) => notify(e.message, true));

  const hasNvidia = info.gpus.some((g) => /nvidia/i.test(g));

  return (
    <section className="panel ofc-dolphin-bench" aria-label="Ajustes globais do Dolphin">
      <div className="ofc-bench-head">
        <div>
          <div className="kicker"><span className="signal" />Ajuste global do emulador</div>
          <h2>Dolphin</h2>
          <div className="ofc-hw-tags">
            {info.flatpak !== null && <span className="ofc-pill muted">{info.flatpak ? "Flatpak" : "Nativo"}</span>}
            {info.gpus.length > 0
              ? info.gpus.map((g) => <span className="ofc-pill muted" key={g}><Cpu size={13} aria-hidden="true" /> {g}</span>)
              : <span className="ofc-pill muted">Placas de vídeo não listadas</span>}
          </div>
        </div>
        <div className="seg ofc-bench-tabs" role="group" aria-label="Seções do Dolphin">
          <button type="button" aria-pressed={tab === "video"} onClick={() => setTab("video")}>
            <Monitor size={15} /> Vídeo padrão
          </button>
          <button type="button" aria-pressed={tab === "controls"} onClick={() => setTab("controls")}>
            <Gamepad2 size={15} /> Controles (J1)
          </button>
        </div>
      </div>

      {info.running && <p className="note warn ofc-bench-note">O Dolphin está aberto. Feche-o para mudar controles e texturas.</p>}
      {hasNvidia && info.flatpak && info.nvidia_ready === false && (
        <p className="note warn ofc-bench-note">A extensão NVIDIA do Flatpak não está instalada: a opção de placa NVIDIA pode não funcionar.</p>
      )}

      {tab === "video" ? (
        <div className="ofc-bench-body">
          <div className="ofc-sub-bar">
            <p className="muted">
              Vale para todos os jogos sem ajuste próprio. <strong>Padrão do Dolphin</strong> mantém o que o emulador já usa.
            </p>
            <div className="ofc-sub-actions">
              {dirty && <span className="ofc-pill warn">Alterações não salvas</span>}
              {defaultsLoaded && hasVideoOverrides(defaults) && (
                <button type="button" className="btn ghost" onClick={() => setDefaults({})}>
                  <RotateCcw size={14} /> Restaurar padrões
                </button>
              )}
              <button type="button" className={dirty ? "btn primary" : "btn"} onClick={save} disabled={!defaultsLoaded}>
                {!defaultsLoaded ? "Carregando…" : dirty ? "Salvar padrões" : <><Check size={15} /> Salvo</>}
              </button>
            </div>
          </div>
          <VideoForm value={defaults} onChange={setDefaults} inherit="Padrão do Dolphin" grouped />
        </div>
      ) : (
        <div className="ofc-bench-body">
          <div className="ofc-sub-bar">
            <p className="muted">
              Em uso no jogador 1: <code className="mono">{info.pad_device ?? "nenhum"}</code>
            </p>
            <button type="button" className="btn primary" onClick={apply} disabled={info.running}>Aplicar controles</button>
          </div>

          <div className="ofc-preset-grid" role="group" aria-label="Tipo de controle">
            {info.presets.map((p) => {
              const meta = PRESETS[p] ?? { label: p, hint: "Perfil de controle do Dolphin.", icon: Gamepad2 };
              const Icon = meta.icon;
              return (
                <button
                  type="button"
                  key={p}
                  className="ofc-preset-card"
                  aria-pressed={preset === p}
                  onClick={() => { setTouched(true); setPreset(p); }}
                >
                  <span className="ofc-preset-icon"><Icon size={18} aria-hidden="true" /></span>
                  <span>
                    <strong>{meta.label}</strong>
                    <small>{meta.hint}</small>
                  </span>
                </button>
              );
            })}
          </div>

          {preset === "xbox" && (
            <div className="ofc-pad-picker">
              {info.controllers.length > 0 ? (
                <Field
                  label="Controle detectado"
                  hint={info.controllers.some((c) => c.source === "kernel")
                    ? "Sem a biblioteca SDL3 o nome é um palpite; se não responder no jogo, use o nome que o Dolphin mostra."
                    : "Detectado automaticamente via SDL."}
                >
                  <Select
                    label="Controle detectado"
                    value={effectiveDevice}
                    onChange={(v) => { setTouched(true); setDevice(v); }}
                    options={[
                      ...(!info.controllers.some((c) => c.device === effectiveDevice) && effectiveDevice ? [{ value: effectiveDevice, label: effectiveDevice }] : []),
                      ...info.controllers.map((c) => ({ value: c.device, label: `${c.name}${c.device.startsWith("SDL/0/") ? "" : ` (${c.device.split("/")[1]})`}` })),
                    ]}
                  />
                </Field>
              ) : (
                <Field label="Controle" hint="Nenhum controle conectado. Ligue ou conecte o controle: ele aparece aqui sozinho.">
                  <input value={device} onChange={(e) => { setTouched(true); setDevice(e.target.value); }} placeholder="SDL/0/Xbox Series X Controller" />
                </Field>
              )}
            </div>
          )}

          <p className="muted ofc-bench-foot">
            O arquivo anterior fica salvo como <code className="mono">GCPadNew.ini.argos-bak</code>. Para login de conquistas no Dolphin, acesse <a href="#/accounts">Oficina → RetroAchievements</a>.
          </p>
        </div>
      )}
    </section>
  );
}

export function Emulators({ games, info, notify, refresh, refreshDolphin }: Ctx) {
  const [emulators, setEmulators] = useState<Emulator[]>([]);
  const [options, setOptions] = useState<Record<string, EmulatorOption[]>>({});

  const load = () => {
    api.emulators().then(setEmulators).catch((e) => notify(e.message, true));
    api.detectedEmulators().then(setOptions).catch(() => undefined);
  };
  useEffect(load, [games.length]);

  const platforms = [...new Set(games.map((g) => g.platform).filter((p): p is string => p !== null))]
    .sort((a, b) => platformName(a).localeCompare(platformName(b), "pt-BR"));
  const configured = platforms.filter((p) => emulators.some((e) => e.platform === p)).length;

  return (
    <div className="ofc-stack">
      <Panel
        title="Plataformas do acervo"
        sub="Escolha qual emulador abre cada console. Use Avançado apenas para executáveis ou argumentos personalizados."
        action={platforms.length > 0 && (
          <span className={`ofc-pill ${configured === platforms.length ? "ok" : "warn"} num`}>
            {configured}/{platforms.length} configuradas
          </span>
        )}
      >
        {platforms.length === 0 ? (
          <p className="muted">
            As plataformas aparecem aqui depois que o acervo tiver jogos identificados. Adicione suas pastas em <a href="#/settings">Pastas e DATs</a>.
          </p>
        ) : (
          <div className="ofc-plat-list">
            {platforms.map((p) => (
              <PlatformRow
                key={p}
                platform={p}
                current={emulators.find((e) => e.platform === p)}
                options={options[p] ?? []}
                notify={notify}
                onSaved={() => { load(); refresh().catch(() => undefined); }}
              />
            ))}
          </div>
        )}
      </Panel>

      {info?.detected && <DolphinWorkbench info={info} notify={notify} refresh={refreshDolphin} />}
    </div>
  );
}
