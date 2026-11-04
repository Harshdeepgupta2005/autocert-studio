/* AutoCert Studio — Electron main process.
   Spawns the bundled Python engine (sidecar), waits for ENGINE-READY,
   then shows the app window. Also provides native folder picking. */
const { app, BrowserWindow, Menu, ipcMain, dialog, nativeImage, shell } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const net = require("net");

const isDev = !app.isPackaged;
let engineProc = null;
let win = null;
let enginePort = null;

/* ───────────────────────── data dir (mirrors app_config.py) ───────────── */
function dataDir() {
  const home = app.getPath("home");
  if (process.platform === "darwin") {
    return path.join(home, "Library", "Application Support", "AutoCertStudio");
  }
  if (process.platform === "win32") {
    return path.join(app.getPath("appData"), "AutoCertStudio");
  }
  return path.join(home, ".config", "AutoCertStudio");
}

/* ───────────────────────── free port ──────────────────────────────────── */
function findFreePort(start) {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.on("error", () => resolve(findFreePort(start + 1)));
    srv.listen(start, "127.0.0.1", () => {
      const p = srv.address().port;
      srv.close(() => resolve(p));
    });
  });
}

/* ───────────────────────── engine spawn ───────────────────────────────── */
function engineSpec() {
  if (isDev) {
    const py = process.platform === "win32"
      ? path.join(__dirname, "..", "venv", "Scripts", "python.exe")
      : path.join(__dirname, "..", "venv", "bin", "python");
    return {
      cmd: py,
      args: ["app.py", "--electron", "--port", String(enginePort)],
      cwd: path.join(__dirname, ".."),
    };
  }
  const exe = process.platform === "win32" ? "engine.exe" : "engine";
  const enginePath = path.join(process.resourcesPath, "engine", exe);
  return { cmd: enginePath, args: ["--electron", "--port", String(enginePort)], cwd: path.dirname(enginePath) };
}

function startEngine() {
  const spec = engineSpec();
  console.log("[electron] starting engine:", spec.cmd, spec.args.join(" "));
  engineProc = spawn(spec.cmd, spec.args, { cwd: spec.cwd, env: { ...process.env, AUTOCERT_ELECTRON: "1" } });
  engineProc.stdout.on("data", (d) => {
    for (const line of String(d).split("\n")) {
      const m = line.match(/ENGINE-READY\s+port=(\d+)/);
      if (m) {
        enginePort = parseInt(m[1], 10);
        createWindow();
      } else if (line.trim()) {
        console.log("[engine]", line.trim());
      }
    }
  });
  engineProc.stderr.on("data", (d) => console.log("[engine:err]", String(d).trim()));
  engineProc.on("exit", (code) => {
    console.log("[electron] engine exited", code);
    if (!app.isQuitting && code && code !== 0 && win) {
      dialog.showErrorBox("AutoCert Studio", "The rendering engine stopped unexpectedly. Please reopen the app.");
    }
  });
}

/* ───────────────────────── window ─────────────────────────────────────── */
function createWindow() {
  if (win) { win.loadURL(`http://127.0.0.1:${enginePort}`); return; }
  win = new BrowserWindow({
    width: 1460, height: 920, minWidth: 1120, minHeight: 660,
    title: "AutoCert Studio", backgroundColor: "#f3f4fb", show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });
  win.loadURL(`http://127.0.0.1:${enginePort}`);
  win.once("ready-to-show", () => win.show());

  /* debug hook: AUTOCERT_CAPTURE=/path.png screenshots the app then quits.
     Combine with AUTOCERT_DEMO=1 to load the built-in demo first,
     AUTOCERT_SELECT=1 to select a field (shows the property panel),
     AUTOCERT_PROPS=1 to scroll the property panel into view, and
     AUTOCERT_ERR=1 to open the generation-warnings dialog. */
  if (process.env.AUTOCERT_CAPTURE) {
    const out = process.env.AUTOCERT_CAPTURE;
    win.webContents.once("did-finish-load", () => {
      setTimeout(async () => {
        if (process.env.AUTOCERT_DEMO) {
          try {
            await win.webContents.executeJavaScript(
              "document.getElementById('btnWelcomeDemo')?.click(); true");
            await new Promise((r) => setTimeout(r, 3500));
          } catch (_) { /* best effort */ }
        }
        if (process.env.AUTOCERT_SELECT) {
          try {
            await win.webContents.executeJavaScript(
              "(S.config && S.config.fields && typeof select==='function') ? " +
              "(select(S.config.fields.find(f => f.type === 'text') || S.config.fields[0]), true) : true");
            await new Promise((r) => setTimeout(r, 1800));
            if (process.env.AUTOCERT_PROPS) {
              await win.webContents.executeJavaScript(
                "document.getElementById('propsCard')?.scrollIntoView({block:'start'}); true");
              await new Promise((r) => setTimeout(r, 900));
            }
          } catch (_) { /* best effort */ }
        }
        if (process.env.AUTOCERT_ERR) {
          try {
            await win.webContents.executeJavaScript(
              "(typeof showWarnings === 'function' ? showWarnings([" +
              "{row: 2, message: 'photo not found in Excel column'}," +
              "{row: 4, message: 'background removal failed for: photo_03.jpg'}]) : null); true");
            await new Promise((r) => setTimeout(r, 700));
          } catch (_) { /* best effort */ }
        }
        try {
          const img = await win.webContents.capturePage();
          fs.writeFileSync(out, img.toPNG());
          console.log("[electron] captured", out);
        } catch (e) { console.log("[electron] capture failed", e); }
        app.exit(0);
      }, 3000);
    });
  }

  win.on("closed", () => { win = null; });
}

function buildMenu() {
  const data = dataDir();
  const tpl = [];
  if (process.platform === "darwin") {
    tpl.push({
      label: app.getName(),
      submenu: [
        { role: "about" },
        { type: "separator" },
        { label: "Open My Files Folder", click: () => shell.openPath(data) },
        { type: "separator" },
        { role: "hide" }, { role: "hideOthers" }, { role: "unhide" },
        { type: "separator" }, { role: "quit" },
      ],
    });
  }
  if (process.platform !== "darwin") {
    tpl.push({
      label: "File",
      submenu: [
        { label: "Open My Files Folder", click: () => shell.openPath(data) },
        { type: "separator" },
        { role: "quit" },
      ],
    });
  }
  tpl.push({
    label: "Edit",
    submenu: [
      { role: "undo" }, { role: "redo" }, { type: "separator" },
      { role: "cut" }, { role: "copy" }, { role: "paste" }, { role: "selectAll" },
    ],
  });
  tpl.push({
    label: "View",
    submenu: [
      { role: "reload" }, { role: "forceReload" },
      { role: "toggleDevTools" }, { type: "separator" },
      { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" },
      { type: "separator" }, { role: "togglefullscreen" },
    ],
  });
  tpl.push({ label: "Window", submenu: [{ role: "minimize" }, { role: "zoom" }] });
  Menu.setApplicationMenu(Menu.buildFromTemplate(tpl));
}

/* ───────────────────────── IPC: native folder pick ────────────────────── */
ipcMain.handle("dialog:pickPhotos", async () => {
  const r = await dialog.showOpenDialog(win, {
    title: "Choose your photos folder",
    properties: ["openDirectory", "dontAddToRecent"],
  });
  return r.canceled ? null : r.filePaths[0];
});

/* ───────────────────────── lifecycle ──────────────────────────────────── */
if (!app.requestSingleInstanceLock()) app.quit();

app.on("second-instance", () => {
  if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
});

app.whenReady().then(async () => {
  buildMenu();
  enginePort = await findFreePort(7481);
  startEngine();
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => {
  app.isQuitting = true;
  if (engineProc) {
    try { engineProc.stdout.destroy(); engineProc.stdin.end(); } catch (_) {}
    try { engineProc.kill(); } catch (_) {}
  }
});
