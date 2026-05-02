const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  selectVideoFile: () => ipcRenderer.invoke('dialog:openFile'),
})
