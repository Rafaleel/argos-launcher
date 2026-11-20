import { useEffect, useState } from "react";
import { Folder, FolderPlus, RefreshCw, X } from "lucide-react";
import type { Ctx } from "../App";
import { api, inDesktop, Settings as SettingsT } from "../api";
import { pickFolder } from "../pickers";
import { Panel } from "../ui";

function FolderList({ label, folders, onChange, title, busy }: {
  label: string; folders: string[]; onChange: (f: string[]) => void; title: string; busy: boolean;
}) {
  const [typed, setTyped] = useState("");
  const add = (path: string) => { const p = path.trim(); if (p && !folders.includes(p)) onChange([...folders, p]); setTyped(""); };
  return (
    <div className="stack" style={{ gap: 8 }}>
      {folders.length === 0 && <p className="muted">Nenhuma pasta ainda.</p>}
      {folders.map((f) => (
        <div className="folder" key={f}>
          <Folder /><code title={f}>{f}</code>
          <button className="btn ghost icon" disabled={busy} aria-label={`Remover ${f}`} onClick={() => onChange(folders.filter((x) => x !== f))}><X /></button>
        </div>
      ))}
      {inDesktop ? (
        <div><button className="btn" disabled={busy} onClick={async () => { const p = await pickFolder(title); if (p) add(p); }}><FolderPlus /> {label}</button></div>
      ) : (
        <div className="row">
          <div className="grow"><input aria-label={label} value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="/caminho/absoluto"
            onKeyDown={(e) => { if (e.key === "Enter") add(typed); }} /></div>
          <button className="btn" onClick={() => add(typed)} disabled={busy || !typed.trim()}><FolderPlus /> Adicionar</button>
        </div>
      )}
    </div>
  );
}

export function Settings({ notify, refresh }: Ctx) {
  const [s, setS] = useState<SettingsT | null>(null);
  const [scanning, setScanning] = useState(false);
  useEffect(() => { api.settings().then(setS).catch((e) => notify(e.message, true)); }, []);
  if (!s) return null;

  const scan = async (next: SettingsT) => {
    setScanning(true);
    try {
      setS(await api.saveSettings(next)); // only what the backend accepted stays on screen
      if (next.rom_dirs.length === 0) {
        notify("Sem pastas de jogos, nada foi escaneado: os jogos que já estão na biblioteca continuam lá. Adicione uma pasta para atualizar.");
        return;
      }
      const r = await api.scan();
      await refresh();
      const emus = r.emulators_configured.length ? ` Emulador configurado: ${r.emulators_configured.map((e) => e.name).join(", ")}.` : "";
      const warn = r.errors.length ? ` Avisos: ${r.errors.join("; ")}` : "";
      notify(`${r.games} jogos na biblioteca.${emus}${warn}`, r.errors.length > 0);
    } catch (e) {
      notify(e instanceof Error ? e.message : String(e), true);
    } finally {
      setScanning(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div><h1>Configurações</h1><p>Onde o Argos procura seus jogos.</p></div>
        <button className="btn" onClick={() => scan(s)} disabled={scanning || s.rom_dirs.length === 0}>
          <RefreshCw /> {scanning ? "Escaneando…" : "Escanear de novo"}
        </button>
      </div>
      <div className="stack">
        <Panel title="Pastas de jogos" sub="Imagens de disco (ISO, GCM, bin/cue) e ROMs. Subpastas também são lidas.">
          <FolderList busy={scanning} label="Adicionar pasta de jogos" title="Escolha uma pasta de jogos" folders={s.rom_dirs}
            onChange={(rom_dirs) => scan({ ...s, rom_dirs })} />
        </Panel>
        <Panel title="Pastas de DATs" sub="Arquivos .dat do No-Intro e do Redump. É com eles que o Argos reconhece cada jogo e sua plataforma.">
          <FolderList busy={scanning} label="Adicionar pasta de DATs" title="Escolha a pasta com os DATs" folders={s.dat_dirs}
            onChange={(dat_dirs) => scan({ ...s, dat_dirs })} />
        </Panel>
        <p className="muted" style={{ fontSize: 13 }}>Arquivos compactados (zip, 7z), CHD e RVZ entram na biblioteca, mas ainda não são identificados.</p>
      </div>
    </>
  );
}
