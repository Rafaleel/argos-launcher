import { useEffect, useState } from "react";
import { Gamepad2, Keyboard } from "lucide-react";
import type { Ctx } from "../App";
import { api, DolphinInfo, Emulator, EmulatorOption, VideoSettings } from "../api";
import { Field, Notify, Panel, platformName } from "../ui";
import { VideoForm } from "./GameDolphin";

const same = (e: Emulator | undefined, o: EmulatorOption) =>
  !!e && e.executable === o.executable && JSON.stringify(e.args) === JSON.stringify(o.args);

function PlatformRow({ platform, current, options, onSaved, notify }: {
  platform: string; current?: Emulator; options: EmulatorOption[]; onSaved: () => void; notify: Notify;
}) {
  const [exe, setExe] = useState(current?.executable ?? "");
  const [args, setArgs] = useState((current?.args ?? ["{rom}"]).join("\n"));
  useEffect(() => { setExe(current?.executable ?? ""); setArgs((current?.args ?? ["{rom}"]).join("\n")); }, [current]);
  const chosen = options.findIndex((o) => same(current, o));
  const save = (e: Emulator) => api.saveEmulator(e).then(() => { notify(`Emulador de ${platformName(platform)} salvo.`); onSaved(); })
    .catch((err) => notify(err.message, true));

  return (
    <div className="emu">
      <div>
        <h3>{platformName(platform)}</h3>
        <div className="muted" style={{ fontSize: 12 }}>
          <span className={`status-dot ${current ? "on" : "off"}`} />{current ? "Pronto para jogar" : "Sem emulador"}
        </div>
      </div>
      <div>
        {options.length > 0 ? (
          <select aria-label={`Emulador de ${platformName(platform)}`} value={chosen >= 0 ? chosen : "custom"}
            onChange={(e) => { const o = options[Number(e.target.value)]; if (o) save({ platform, executable: o.executable, args: o.args }); }}>
            {chosen < 0 && <option value="custom">{current ? "Personalizado" : "Escolha um emulador"}</option>}
            {options.map((o, i) => <option key={o.name} value={i}>{o.name}</option>)}
          </select>
        ) : (
          <p className="muted" style={{ fontSize: 13 }}>Nenhum emulador instalado para esta plataforma foi encontrado.</p>
        )}
        <details style={{ marginTop: 10 }}>
          <summary>Avançado</summary>
          <div className="stack" style={{ marginTop: 12 }}>
            <Field label="Executável (caminho absoluto)"><input value={exe} onChange={(e) => setExe(e.target.value)} placeholder="/usr/bin/flatpak" /></Field>
            <Field label="Argumentos, um por linha" hint="{rom} vira o caminho do jogo.">
              <textarea rows={4} value={args} onChange={(e) => setArgs(e.target.value)} />
            </Field>
            <div><button className="btn" onClick={() => save({ platform, executable: exe.trim(), args: args.split("\n").map((a) => a.trim()).filter(Boolean) })}>Salvar manualmente</button></div>
          </div>
        </details>
      </div>
      <div />
    </div>
  );
}

const PRESETS: Record<string, { label: string; icon: typeof Keyboard }> = {
  keyboard_default: { label: "Teclado · layout do Dolphin", icon: Keyboard },
  keyboard_wasd: { label: "Teclado · WASD", icon: Keyboard },
  xbox: { label: "Controle (Xbox, PlayStation e outros)", icon: Gamepad2 },
};

function DolphinSection({ info, notify, refresh }: { info: DolphinInfo; notify: Notify; refresh: () => void }) {
  const [defaults, setDefaults] = useState<VideoSettings>({});
  const [preset, setPreset] = useState(info.pad_device?.startsWith("SDL/") || info.controllers.length ? "xbox" : "keyboard_default");
  const [device, setDevice] = useState(info.pad_device?.startsWith("SDL/") ? info.pad_device : info.controllers[0]?.device ?? "");
  const [touched, setTouched] = useState(false); // once the user picks, detection stops choosing for them
  useEffect(() => { api.dolphinDefaults().then(setDefaults).catch((e) => notify(e.message, true)); }, []);
  // look for pads every few seconds, so turning one on is enough (no reload)
  useEffect(() => { const id = setInterval(refresh, 3000); return () => clearInterval(id); }, [refresh]);
  const found = info.controllers.map((c) => c.device).join("|");
  useEffect(() => {
    if (touched || !info.controllers.length) return;
    setPreset("xbox");
    if (!info.controllers.some((c) => c.device === device)) setDevice(info.controllers[0].device);
  }, [found]);

  const save = () => api.saveDolphinDefaults(defaults).then((v) => { setDefaults(v); notify("Padrões do Dolphin salvos."); })
    .catch((e) => notify(e.message, true));
  const apply = () => api.saveControls(preset, preset === "xbox" ? device.trim() : null)
    .then((r) => { notify(`Controles aplicados (${r.device}).`); refresh(); }).catch((e) => notify(e.message, true));
  const hasNvidia = info.gpus.some((g) => /nvidia/i.test(g));

  return (
    <div className="stack section-gap">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div><h2>Dolphin</h2><p>{info.gpus.length ? info.gpus.join(" · ") : "Placas de vídeo não listadas"}</p></div>
      </div>
      {info.running && <p className="note warn">O Dolphin está aberto. Feche-o para mudar controles e texturas.</p>}
      {hasNvidia && info.flatpak && info.nvidia_ready === false && (
        <p className="note warn">A extensão NVIDIA do Flatpak não está instalada: a opção de placa NVIDIA pode não funcionar.</p>
      )}
      <Panel title="Vídeo de todos os jogos" sub='Cada jogo pode mudar isso na própria página. "Padrão do Dolphin" deixa como o Dolphin já está.'
        action={<button className="btn primary" onClick={save}>Salvar</button>}>
        <VideoForm value={defaults} onChange={setDefaults} inherit="Padrão do Dolphin" />
      </Panel>
      <Panel title="Controles do jogador 1" sub={<>Em uso agora: {info.pad_device ?? "nenhum"}</>}
        action={<button className="btn primary" onClick={apply} disabled={info.running}>Aplicar</button>}>
        <div className="seg" role="group" aria-label="Tipo de controle" style={{ flexWrap: "wrap" }}>
          {info.presets.map((p) => {
            const meta = PRESETS[p] ?? { label: p, icon: Gamepad2 };
            const Icon = meta.icon;
            return <button key={p} aria-pressed={preset === p} onClick={() => { setTouched(true); setPreset(p); }}><Icon /> {meta.label}</button>;
          })}
        </div>
        {preset === "xbox" && (
          <div style={{ marginTop: 16, maxWidth: 480 }}>
            {info.controllers.length > 0 ? (
              <Field label="Controle detectado" hint={info.controllers.some((c) => c.source === "kernel")
                ? "Sem a biblioteca SDL3 o nome é um palpite; se não responder no jogo, use o nome que o Dolphin mostra." : undefined}>
                <select value={device} onChange={(e) => { setTouched(true); setDevice(e.target.value); }}>
                  {!info.controllers.some((c) => c.device === device) && device && <option value={device}>{device}</option>}
                  {info.controllers.map((c) => <option key={c.device} value={c.device}>{c.name}{c.device.startsWith("SDL/0/") ? "" : ` (${c.device.split("/")[1]})`}</option>)}
                </select>
              </Field>
            ) : (
              <Field label="Controle" hint="Nenhum controle conectado. Ligue ou conecte o controle: ele aparece aqui sozinho.">
                <input value={device} onChange={(e) => { setTouched(true); setDevice(e.target.value); }} placeholder="SDL/0/Xbox Series X Controller" />
              </Field>
            )}
          </div>
        )}
        <p className="muted" style={{ fontSize: 12, marginTop: 14 }}>O arquivo anterior fica salvo como GCPadNew.ini.argos-bak.</p>
      </Panel>
    </div>
  );
}

export function Emulators({ games, info, notify, refresh }: Ctx) {
  const [emulators, setEmulators] = useState<Emulator[]>([]);
  const [options, setOptions] = useState<Record<string, EmulatorOption[]>>({});
  const load = () => {
    api.emulators().then(setEmulators).catch((e) => notify(e.message, true));
    api.detectedEmulators().then(setOptions).catch(() => undefined);
  };
  useEffect(load, [games.length]);
  const platforms = [...new Set(games.map((g) => g.platform).filter((p): p is string => p !== null))].sort();

  return (
    <>
      <Panel title="Plataformas da biblioteca">
        {platforms.length === 0 ? <p className="muted">As plataformas aparecem depois que a biblioteca tiver jogos identificados.</p> : (
          platforms.map((p) => (
            <PlatformRow key={p} platform={p} current={emulators.find((e) => e.platform === p)} options={options[p] ?? []}
              notify={notify} onSaved={() => { load(); refresh().catch(() => undefined); }} />
          ))
        )}
      </Panel>
      {info?.detected && <DolphinSection info={info} notify={notify} refresh={() => refresh().catch(() => undefined)} />}
    </>
  );
}
