const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron')
const { spawn } = require('child_process')
const { copyFileSync, readFileSync } = require('fs')
const path = require('path')

const ROOT_DIR       = path.join(__dirname, '..')
const VENV_SAM2      = path.join(ROOT_DIR, 'venv_sam2', 'bin', 'python')
const SAM2_SCRIPT    = path.join(ROOT_DIR, 'src', 'extract_with_sam2.py')
const PREVIEW_SCRIPT = path.join(ROOT_DIR, 'src', 'preview_mask.py')
const OUTPUT_DIR     = path.join(ROOT_DIR, 'output')

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    title: '모션그래픽 추출기',
    backgroundColor: '#1a1a1a',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  })
  win.loadFile('index.html')
}

// ── 파일 선택 다이얼로그 ───────────────────────────────────────
ipcMain.handle('dialog:openFile', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog({
    properties: ['openFile'],
    filters: [{ name: '영상 파일', extensions: ['mp4', 'mov', 'webm', 'avi'] }],
  })
  return canceled ? null : filePaths[0]
})

// ── SAM 2 추출 실행 ────────────────────────────────────────────
ipcMain.handle('extract:sam2', async (event, { videoPath, time, x, y }) => {
  return new Promise((resolve, reject) => {
    const child = spawn(VENV_SAM2, [
      SAM2_SCRIPT,
      '--video',       videoPath,
      '--click-time',  String(time),
      '--click-x',     String(x),
      '--click-y',     String(y),
    ])

    let buffer = ''

    child.stdout.on('data', (data) => {
      buffer += data.toString()
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        const l = line.trim()
        if (!l) continue
        if (l.startsWith('PROGRESS:')) {
          const parts = l.replace('PROGRESS:', '').trim().split('/')
          const current = parseInt(parts[0])
          const total   = parseInt(parts[1])
          if (!isNaN(current) && !isNaN(total))
            event.sender.send('extract:progress', { current, total })
        } else if (l.startsWith('DONE:')) {
          event.sender.send('extract:complete', { outputPath: l.replace('DONE:', '').trim() })
        } else if (l.startsWith('ERROR:')) {
          event.sender.send('extract:error', { message: l.replace('ERROR:', '').trim() })
        }
      }
    })

    child.stderr.on('data', (data) => {
      const msg = data.toString()
      if (msg.includes('Traceback') || (msg.includes('Error') && !msg.includes('UserWarning'))) {
        event.sender.send('extract:error', { message: msg })
      }
    })

    child.on('close', (code) => {
      if (code === 0) resolve({ success: true })
      else reject(new Error(`프로세스 종료 코드: ${code}`))
    })

    child.on('error', (err) => reject(new Error(err.message)))
  })
})

// ── .jsx 다른 이름으로 저장 ────────────────────────────────────
ipcMain.handle('save-jsx-as', async (event, { sourcePath }) => {
  const defaultName = path.basename(sourcePath)
  const { canceled, filePath } = await dialog.showSaveDialog({
    title: 'AE 스크립트 저장',
    defaultPath: defaultName,
    filters: [{ name: 'After Effects Script', extensions: ['jsx'] }],
  })
  if (canceled || !filePath) return null
  copyFileSync(sourcePath, filePath)
  return filePath
})

// ── output 폴더 열기 ──────────────────────────────────────────
ipcMain.handle('open-output-folder', async () => {
  await shell.openPath(OUTPUT_DIR)
})

// ── 좌표 JSON 로드 ────────────────────────────────────────────
ipcMain.handle('load-coords-json', async (event, { filePath }) => {
  return JSON.parse(readFileSync(filePath, 'utf8'))
})

// ── 마스크 프리뷰 (단일 프레임, image predictor) ──────────────
ipcMain.handle('preview-mask', async (event, { videoPath, time, x, y }) => {
  return new Promise((resolve, reject) => {
    const child = spawn(VENV_SAM2, [
      PREVIEW_SCRIPT,
      '--video',      videoPath,
      '--click-time', String(time),
      '--click-x',    String(x),
      '--click-y',    String(y),
    ])

    let buffer     = ''
    let stderrText = ''
    let maskPath   = null

    child.stdout.on('data', (data) => {
      buffer += data.toString()
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        const l = line.trim()
        if (l.startsWith('MASK_READY:'))
          maskPath = l.replace('MASK_READY:', '').trim()
      }
    })

    child.stderr.on('data', (data) => { stderrText += data.toString() })

    child.on('close', (code) => {
      if (code === 0 && maskPath) {
        try {
          const dataUrl = 'data:image/png;base64,' + readFileSync(maskPath).toString('base64')
          resolve({ dataUrl })
        } catch (err) {
          reject(new Error('PNG 읽기 실패: ' + err.message))
        }
      } else {
        reject(new Error(`마스크 프리뷰 실패 (코드: ${code})\nSTDERR:\n${stderrText}`))
      }
    })

    child.on('error', (err) => reject(new Error(err.message)))
  })
})

// ── 앱 생명주기 ───────────────────────────────────────────────
app.whenReady().then(() => {
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
