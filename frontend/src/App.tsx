import { Fragment, useCallback, useEffect, useState } from "react";
import { api, By, DolphinInfo, Emulator, Game, GameTime, Period, PlatformTime, ScanResult, formatDuration } from "./api";
import { DolphinPanel, GameSettings } from "./Dolphin";

const lines = (s: string) => s.split("\n");

export default function App() {
  const [games, setGames] = useState<Game[]>([]);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [emulators, setEmulators] = useState<Emulator[]>([]);
  const [romDirs, setRomDirs] = useState("");
  const [datDirs, setDatDirs] = useState("");
  const [msg, setMsg] = useState<{ text: string; error: boolean } | null>(null);
  const [scanning, setScanning] = useState(false);
  const [platformTime, setPlatformTime] = useState<PlatformTime[]>([]);
  const [gameTime, setGameTime] = useState<GameTime[]>([]);
  const [periods, setPeriods] = useState<Period[]>([]);
  const [by, setBy] = useState<By>("day");
  const [info, setInfo] = useState<DolphinInfo | null>(null);
  const [openGame, setOpenGame] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false); // never save a textarea that did not load

  const show = (text: string, error = false) => setMsg({ text, error });
  const fail = (e: unknown) => show(e instanceof Error ? e.message : String(e), true);

  const refresh = useCallback(async () => {
    const [g, p, e, pt, gt, per, di] = await Promise.all([
      api.games(), api.platforms(), api.emulators(), api.statsPlatforms(), api.statsGames(), api.statsPeriods(by),
      api.dolphinInfo(),
    ]);
    setInfo(di);
    setGames(g);
    setPlatforms(p);
    setEmulators(e);
    setPlatformTime(pt);
    setGameTime(gt);
    setPeriods(per);
  }, [by]);

  useEffect(() => {
    api.settings().then((s) => {
      setRomDirs(s.rom_dirs.join("\n"));
      setDatDirs(s.dat_dirs.join("\n"));
      setLoaded(true);
    }).catch(fail);
  }, []);

  useEffect(() => {
    refresh().catch(fail);
  }, [refresh]);

  // While a game is open, poll so "jogando agora" and the time clear by themselves.
  const anyPlaying = games.some((g) => g.playing);
  useEffect(() => {
    if (!anyPlaying) return;
    let busy = false;
    const id = setInterval(() => {
      if (busy) return; // a slow answer must not pile up requests
      busy = true;
      refresh().catch(fail).finally(() => { busy = false; });
    }, 5000);
    return () => clearInterval(id);
  }, [anyPlaying, refresh]);

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
    api.play(g.id).then(() => { show(`Abrindo ${g.title}…`); return refresh(); }).catch(fail);

  return (
    <main>
      <h1>Argos Launcher</h1>
      {msg && <div className={`msg ${msg.error ? "err" : ""}`}>{msg.text}</div>}

      <section>
        <h2>Biblioteca</h2>
        <label>Pastas de ROMs (uma por linha)</label>
        <textarea aria-label="Pastas de ROMs" rows={3} value={romDirs} onChange={(e) => setRomDirs(e.target.value)} />
        <label>Pastas de DATs No-Intro/Redump (uma por linha)</label>
        <textarea aria-label="Pastas de DATs" rows={2} value={datDirs} onChange={(e) => setDatDirs(e.target.value)} />
        <p><button onClick={scan} disabled={scanning || !loaded}>{scanning ? "Escaneando…" : "Salvar e escanear"}</button></p>
        <p className="muted">Só imagens cruas (bin/cue, iso, ROMs soltas) são identificadas. Arquivos zip, CHD e RVZ aparecem como não identificados.</p>
      </section>

      <section>
        <h2>Jogos</h2>
        {games.length === 0 ? <p className="muted">Nenhum jogo ainda. Escaneie uma pasta.</p> : (
          <table>
            <thead><tr><th>Título</th><th>Plataforma</th><th>Tempo jogado</th><th /></tr></thead>
            <tbody>
              {games.map((g) => (
                <Fragment key={g.id}>
                  <tr>
                    <td>{g.title}{g.playing && <span className="badge">jogando agora</span>}</td>
                    <td>{g.platform ?? <span className="muted">não identificado</span>}</td>
                    <td>{formatDuration(g.seconds_played)}</td>
                    <td>
                      {g.dolphin && (
                        <button aria-expanded={openGame === g.id} onClick={() => setOpenGame(openGame === g.id ? null : g.id)}>
                          Ajustes
                        </button>
                      )}{" "}
                      <button disabled={!g.identified || !g.has_emulator || g.playing} onClick={() => play(g)}
                        title={!g.identified ? "Jogo não identificado" : !g.has_emulator ? "Configure um emulador" : g.playing ? "Já está aberto" : ""}>
                        Jogar
                      </button>
                    </td>
                  </tr>
                  {openGame === g.id && info && (
                    <tr><td colSpan={4}><GameSettings gameId={g.id} info={info} notify={show} /></td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Estatísticas</h2>
        {gameTime.length === 0 ? <p className="muted">Ainda não há tempo registrado. Abra um jogo para começar.</p> : (
          <>
            <h3>Por plataforma</h3>
            <Bars rows={platformTime.map((p) => ({ id: p.platform ?? "-", label: p.platform ?? "Não identificado", seconds: p.seconds }))} />
            <h3>Por jogo</h3>
            <Bars rows={gameTime.slice(0, 10).map((g) => ({ id: String(g.game_id), label: g.title, seconds: g.seconds }))} />
            <h3>Por período
              <select aria-label="Agrupar por" value={by} onChange={(e) => setBy(e.target.value as By)} style={{ width: "auto", marginLeft: 8 }}>
                <option value="day">Dia</option><option value="week">Semana</option><option value="month">Mês</option>
              </select>
            </h3>
            <Bars rows={periods.map((p) => ({ id: p.period, label: p.period, seconds: p.seconds }))} />
          </>
        )}
      </section>

      {info?.detected && <DolphinPanel info={info} notify={show} refreshInfo={() => refresh().catch(fail)} />}

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
      <input aria-label={`Executável do emulador de ${platform}`} value={exe} onChange={(e) => setExe(e.target.value)} placeholder="/usr/bin/retroarch" />
      <label>Argumentos (um por linha; {"{rom}"} vira o caminho do jogo)</label>
      <textarea aria-label={`Argumentos do emulador de ${platform}`} rows={3} value={args} onChange={(e) => setArgs(e.target.value)} />
      <p><button onClick={() => onSave({ platform, executable: exe.trim(), args: lines(args).filter(Boolean) })}>Salvar</button></p>
    </div>
  );
}

function Bars({ rows }: { rows: { id: string; label: string; seconds: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.seconds));
  return (
    <div>
      {rows.map((r) => (
        <div className="bar-row" key={r.id}>
          <span title={r.label} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.label}</span>
          <div className="bar" style={{ width: `${(r.seconds / max) * 100}%` }} />
          <span>{formatDuration(r.seconds)}</span>
        </div>
      ))}
    </div>
  );
}
