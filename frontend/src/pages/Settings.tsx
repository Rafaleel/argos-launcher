import { useEffect, useState } from "react";
import { AlertCircle, Folder, FolderPlus, HardDrive, Info, RefreshCw, X } from "lucide-react";
import type { Ctx } from "../App";
import { api, inDesktop, Settings as SettingsT } from "../api";
import { collectEditions } from "../collection";
import { pickFolder } from "../pickers";
import { Panel } from "../ui";

function FolderList({ label, folders, onChange, title, busy }: {
  label: string; folders: string[]; onChange: (f: string[]) => void; title: string; busy: boolean;
}) {
  const [typed, setTyped] = useState("");
  const add = (path: string) => {
    const p = path.trim();
    if (p && !folders.includes(p)) onChange([...folders, p]);
    setTyped("");
  };

  return (
    <div className="ofc-folder-wrap">
      {folders.length === 0 ? (
        <p className="muted ofc-folder-empty">Nenhuma pasta configurada ainda.</p>
      ) : (
        <ul className="ofc-folder-list">
          {folders.map((f) => (
            <li className="ofc-folder-row" key={f}>
              <Folder size={16} aria-hidden="true" />
              <code title={f}>{f}</code>
              <button className="btn ghost icon" disabled={busy} aria-label={`Remover ${f}`} onClick={() => onChange(folders.filter((x) => x !== f))}>
                <X />
              </button>
            </li>
          ))}
        </ul>
      )}
      {inDesktop ? (
        <div>
          <button className="btn" disabled={busy} onClick={async () => { const p = await pickFolder(title); if (p) add(p); }}>
            <FolderPlus /> {label}
          </button>
        </div>
      ) : (
        <div className="row">
          <div className="grow">
            <input
              aria-label={label}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder="/caminho/absoluto"
              onKeyDown={(e) => { if (e.key === "Enter" && !busy) add(typed); }}
            />
          </div>
          <button className="btn" onClick={() => add(typed)} disabled={busy || !typed.trim()}>
            <FolderPlus /> Adicionar
          </button>
        </div>
      )}
    </div>
  );
}

export function Settings({ games, notify, refresh }: Ctx) {
  const [s, setS] = useState<SettingsT | null>(null);
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    api.settings().then(setS).catch((e) => notify(e.message, true));
  }, [notify]);

  if (!s) return <p className="muted" role="status">Carregando pastas…</p>;

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

  const editions = collectEditions(games);
  const identifiedCount = editions.filter(([g]) => g.identified).length;
  const unknownCount = games.filter((g) => !g.identified).length;
  const platformCount = new Set(games.map((g) => g.platform).filter((p): p is string => p !== null)).size;

  return (
    <div className="ofc-stack">
      <section className="panel ofc-scan-hero" aria-label="Resumo do acervo e escaneamento">
        <div className="ofc-scan-copy">
          <div className="kicker"><span className="signal" />Fontes do acervo</div>
          <h2>
            {s.rom_dirs.length === 0
              ? "Configure suas pastas para montar o acervo"
              : <span className="num">{identifiedCount} {identifiedCount === 1 ? "título identificado" : "títulos identificados"}</span>}
          </h2>
          <div className="ofc-scan-meta">
            <span className="ofc-pill muted num"><HardDrive size={13} aria-hidden="true" /> {platformCount} {platformCount === 1 ? "plataforma" : "plataformas"}</span>
            <span className="ofc-pill muted num">{s.rom_dirs.length} {s.rom_dirs.length === 1 ? "pasta de jogos" : "pastas de jogos"}</span>
            <span className="ofc-pill muted num">{s.dat_dirs.length} {s.dat_dirs.length === 1 ? "pasta de DATs" : "pastas de DATs"}</span>
            {unknownCount > 0 && (
              <span className="ofc-pill warn num">
                <AlertCircle size={13} aria-hidden="true" /> {unknownCount} {unknownCount === 1 ? "arquivo não identificado" : "arquivos não identificados"}
              </span>
            )}
          </div>
        </div>
        <div className="ofc-scan-cta">
          <button className="btn primary big" onClick={() => scan(s)} disabled={scanning || s.rom_dirs.length === 0}>
            <RefreshCw className={scanning ? "spin" : undefined} /> {scanning ? "Escaneando…" : "Escanear biblioteca"}
          </button>
        </div>
      </section>

      <div className="ofc-sources-grid">
        <Panel
          title="Pastas de jogos"
          sub="Imagens de disco (ISO, GCM, bin/cue) e ROMs. Subpastas também são lidas automaticamente."
          action={<span className="ofc-pill muted num">{s.rom_dirs.length}</span>}
        >
          <FolderList
            busy={scanning}
            label="Adicionar pasta de jogos"
            title="Escolha uma pasta de jogos"
            folders={s.rom_dirs}
            onChange={(rom_dirs) => scan({ ...s, rom_dirs })}
          />
        </Panel>

        <Panel
          title="Pastas de DATs"
          sub="Arquivos .dat do No-Intro e do Redump. É com eles que o Argos identifica cada título e sua plataforma."
          action={<span className="ofc-pill muted num">{s.dat_dirs.length}</span>}
        >
          <FolderList
            busy={scanning}
            label="Adicionar pasta de DATs"
            title="Escolha a pasta com os DATs"
            folders={s.dat_dirs}
            onChange={(dat_dirs) => scan({ ...s, dat_dirs })}
          />
        </Panel>
      </div>

      <div className="note ofc-footnote">
        <Info size={16} aria-hidden="true" />
        <p>
          Arquivos compactados (zip, 7z, rar), como pacotes de textura, são ignorados no scan. Imagens CHD e RVZ entram na biblioteca, mas ainda aparecem como não identificadas.
        </p>
      </div>
    </div>
  );
}
