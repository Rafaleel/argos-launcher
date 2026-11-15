import { useCallback, useEffect, useState } from "react";
import { api, Emulator, Game, ScanResult } from "./api";

const lines = (s: string) => s.split("\n");

export default function App() {
  const [games, setGames] = useState<Game[]>([]);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [emulators, setEmulators] = useState<Emulator[]>([]);
  const [romDirs, setRomDirs] = useState("");
  const [datDirs, setDatDirs] = useState("");
  const [msg, setMsg] = useState<{ text: string; error: boolean } | null>(null);
  const [scanning, setScanning] = useState(false);
  const [loaded, setLoaded] = useState(false); // never save a textarea that did not load

  const show = (text: string, error = false) => setMsg({ text, error });
  const fail = (e: unknown) => show(e instanceof Error ? e.message : String(e), true);

  const refresh = useCallback(async () => {
    const [g, p, e] = await Promise.all([api.games(), api.platforms(), api.emulators()]);
    setGames(g);
    setPlatforms(p);
    setEmulators(e);
  }, []);

  useEffect(() => {
    api.settings().then((s) => {
      setRomDirs(s.rom_dirs.join("\n"));
      setDatDirs(s.dat_dirs.join("\n"));
      setLoaded(true);
    }).catch(fail);
    refresh().catch(fail);
  }, [refresh]);

  const scan = async () => {
    setScanning(true);
    try {
      await api.saveSettings({ rom_dirs: lines(romDirs), dat_dirs: lines(datDirs) });
      const r: ScanResult = await api.scan();
      await refresh();
      const note = r.errors.length ? ` Avisos: ${r.errors.join("; ")}` : "";
      show(`${r.games} jogos (${r.files_hashed} arquivos lidos, ${r.files_cached} em cache, ${r.files_removed} removidos).${note}`, r.errors.length > 0);
    } catch (e) {
      fail(e);
    } finally {
      setScanning(false);
    }
  };

  const play = (g: Game) =>
    api.play(g.id).then(() => show(`Abrindo ${g.title}…`)).catch(fail);

  return (
    <main>
      <h1>Argos Launcher</h1>
      {msg && <div className={`msg ${msg.error ? "err" : ""}`}>{msg.text}</div>}

      <section>
        <h2>Biblioteca</h2>
        <label>Pastas de ROMs (uma por linha)</label>
        <textarea rows={3} value={romDirs} onChange={(e) => setRomDirs(e.target.value)} />
        <label>Pastas de DATs No-Intro/Redump (uma por linha)</label>
        <textarea rows={2} value={datDirs} onChange={(e) => setDatDirs(e.target.value)} />
        <p><button onClick={scan} disabled={scanning || !loaded}>{scanning ? "Escaneando…" : "Salvar e escanear"}</button></p>
        <p className="muted">Só imagens cruas (bin/cue, iso, ROMs soltas) são identificadas. Arquivos zip, CHD e RVZ aparecem como não identificados.</p>
      </section>

      <section>
        <h2>Jogos</h2>
        {games.length === 0 ? <p className="muted">Nenhum jogo ainda. Escaneie uma pasta.</p> : (
          <table>
            <thead><tr><th>Título</th><th>Plataforma</th><th /></tr></thead>
            <tbody>
              {games.map((g) => (
                <tr key={g.id}>
                  <td>{g.title}</td>
                  <td>{g.platform ?? <span className="muted">não identificado</span>}</td>
                  <td>
                    <button disabled={!g.identified || !g.has_emulator} onClick={() => play(g)}
                      title={!g.identified ? "Jogo não identificado" : !g.has_emulator ? "Configure um emulador" : ""}>
                      Jogar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Emuladores</h2>
        {platforms.length === 0 && <p className="muted">As plataformas aparecem depois do primeiro scan com DATs.</p>}
        {platforms.map((p) => (
          <EmulatorRow key={p} platform={p} current={emulators.find((e) => e.platform === p)}
            onSave={(e) => api.saveEmulator(e).then(refresh).then(() => show(`Emulador de ${p} salvo.`)).catch(fail)} />
        ))}
      </section>
    </main>
  );
}

function EmulatorRow({ platform, current, onSave }: { platform: string; current?: Emulator; onSave: (e: Emulator) => void }) {
  const [exe, setExe] = useState(current?.executable ?? "");
  const [args, setArgs] = useState((current?.args ?? ["{rom}"]).join("\n"));
  return (
    <div>
      <h3>{platform}</h3>
      <label>Caminho do executável (absoluto)</label>
      <input value={exe} onChange={(e) => setExe(e.target.value)} placeholder="/usr/bin/retroarch" />
      <label>Argumentos (um por linha; {"{rom}"} vira o caminho do jogo)</label>
      <textarea rows={3} value={args} onChange={(e) => setArgs(e.target.value)} />
      <p><button onClick={() => onSave({ platform, executable: exe.trim(), args: lines(args).filter(Boolean) })}>Salvar</button></p>
    </div>
  );
}
