import { inDesktop } from "./api";

/** Native folder/file chooser in the desktop app; null in the browser (the UI then shows a text field). */
export async function pickFolder(title: string): Promise<string | null> {
  if (!inDesktop) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const r = await open({ directory: true, multiple: false, title });
  return typeof r === "string" ? r : null;
}

export async function pickArchive(title: string): Promise<string | null> {
  if (!inDesktop) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const r = await open({ multiple: false, title, filters: [{ name: "Pacotes", extensions: ["zip", "7z", "rar"] }] });
  return typeof r === "string" ? r : null;
}
