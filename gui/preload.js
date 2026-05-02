const { contextBridge, ipcRenderer, webUtils } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  // 파일 선택 다이얼로그
  selectVideoFile: () => ipcRenderer.invoke('dialog:openFile'),

  // 드롭된 File 객체의 절대 경로 반환 (Electron 32+)
  getFilePath: (file) => webUtils.getPathForFile(file),

  // SAM 2 추출 실행
  extractWithSam2: (params) => ipcRenderer.invoke('extract:sam2', params),

  // 추출 진행 이벤트 리스너 등록
  onProgress: (cb) => ipcRenderer.on('extract:progress', (_, d) => cb(d)),
  onComplete: (cb) => ipcRenderer.on('extract:complete', (_, d) => cb(d)),
  onError:    (cb) => ipcRenderer.on('extract:error',    (_, d) => cb(d)),

  // 리스너 정리 (재실행 전 호출)
  removeExtractListeners: () => {
    ipcRenderer.removeAllListeners('extract:progress')
    ipcRenderer.removeAllListeners('extract:complete')
    ipcRenderer.removeAllListeners('extract:error')
  },

  // .jsx 다른 이름으로 저장
  saveJsxAs: (sourcePath) => ipcRenderer.invoke('save-jsx-as', { sourcePath }),

  // output 폴더 Finder에서 열기
  openOutputFolder: () => ipcRenderer.invoke('open-output-folder'),

  // 좌표 JSON 로드
  loadCoordsJson: (filePath) => ipcRenderer.invoke('load-coords-json', { filePath }),

  // 마스크 프리뷰 (단일 프레임 image predictor)
  previewMask: (params) => ipcRenderer.invoke('preview-mask', params),
})
