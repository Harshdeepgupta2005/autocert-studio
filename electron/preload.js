/* AutoCert Studio — preload: safe bridge between renderer and Electron APIs */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("autoCert", {
  isElectron: true,
  pickPhotosFolder: () => ipcRenderer.invoke("dialog:pickPhotos"),
});
