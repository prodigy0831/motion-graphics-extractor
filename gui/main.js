const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron')
const { spawn } = require('child_process')
const { copyFileSync, readFileSync } = require('fs')
const path = require('path')

const ROOT_DIR          = path.join(__dirname, '..')
const VENV_SAM2         = path.join(ROOT_DIR, 'venv_sam2', 'bin', 'python')
const SAM2_SCRIPT       = path.join(ROOT_DIR, 'src', 'extract_with_sam2.py')
const TEXT_SCRIPT       = path.join(ROOT_DIR, 'src', 'extract_text.py')
const PREVIEW_SCRIPT    = path.join(ROOT_DIR, 'src', 'preview_mask.py')
const AI_TEXT_SCRIPT    = path.join(ROOT_DIR, 'src', 'generate_text_image.py')
const FINAL_JSX_SCRIPT  = path.join(ROOT_DIR, 'src', 'build_final_jsx.py')
const OUTPUT_DIR        = path.join(ROOT_DIR, 'output')

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

// ── 텍스트 추출 실행 ──────────────────────────────────────────
ipcMain.handle('extract:text', async (event, { videoPath, time, x1, y1, x2, y2 }) => {
  return new Promise((resolve, reject) => {
    const child = spawn(VENV_SAM2, [
      TEXT_SCRIPT,
      videoPath,
      '--click-time', String(time),
      '--bbox',       `${x1},${y1},${x2},${y2}`,
    ])

    let buffer     = ''
    let stderrText = ''

    child.stdout.on('data', (data) => {
      buffer += data.toString()
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        const l = line.trim()
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

    child.stderr.on('data', (data) => { stderrText += data.toString() })

    child.on('close', (code) => {
      if (code === 0) resolve({ success: true })
      else reject(new Error(`텍스트 추출 실패 (코드: ${code})\nSTDERR:\n${stderrText}`))
    })

    child.on('error', (err) => reject(new Error(err.message)))
  })
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

// ── AI 텍스트 이미지 생성 ─────────────────────────────────────
ipcMain.handle('generate-ai-text', async (event, { referenceImagePath, newText, apiKey, outputPath }) => {
  return new Promise((resolve, reject) => {
    const child = spawn(VENV_SAM2, [
      AI_TEXT_SCRIPT,
      '--reference-image', referenceImagePath,
      '--new-text',        newText,
      '--api-key',         apiKey,
      '--output',          outputPath,
    ])

    let buffer    = ''
    let stderrText = ''
    let aiImagePath = null

    child.stdout.on('data', (data) => {
      buffer += data.toString()
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        const l = line.trim()
        if (l.startsWith('AI_IMAGE_READY:'))
          aiImagePath = l.replace('AI_IMAGE_READY:', '').trim()
      }
    })

    child.stderr.on('data', (data) => { stderrText += data.toString() })

    child.on('close', (code) => {
      if (code === 0 && aiImagePath) {
        try {
          const dataUrl = 'data:image/png;base64,' + readFileSync(aiImagePath).toString('base64')
          resolve({ dataUrl, outputPath: aiImagePath })
        } catch (err) {
          reject(new Error('PNG 읽기 실패: ' + err.message))
        }
      } else {
        reject(new Error(`AI 이미지 생성 실패 (코드: ${code})\nSTDERR:\n${stderrText}`))
      }
    })

    child.on('error', (err) => reject(new Error(err.message)))
  })
})

// ── 로컬 이미지 파일 → data URL ───────────────────────────────
ipcMain.handle('read-image-as-data-url', async (event, { filePath }) => {
  const ext  = path.extname(filePath).slice(1).toLowerCase()
  const mime = ext === 'png' ? 'image/png' : ext === 'jpg' || ext === 'jpeg' ? 'image/jpeg' : 'image/png'
  return 'data:' + mime + ';base64,' + readFileSync(filePath).toString('base64')
})

// ── AI 통합 .jsx 생성 ────────────────────────────────────
ipcMain.handle('build-final-jsx', async (event, { jsonPath, aiPngPath, outputJsxPath }) => {
  return new Promise((resolve, reject) => {
    const child = spawn(VENV_SAM2, [
      FINAL_JSX_SCRIPT,
      '--json-path',   jsonPath,
      '--ai-png-path', aiPngPath,
      '--output-jsx',  outputJsxPath,
    ])

    let buffer    = ''
    let stderrText = ''
    let jsxPath   = null

    child.stdout.on('data', (data) => {
      buffer += data.toString()
      const lines = buffer.split('\n')
      buffer = lines.pop()
      for (const line of lines) {
        const l = line.trim()
        if (l.startsWith('JSX_READY:'))
          jsxPath = l.replace('JSX_READY:', '').trim()
      }
    })

    child.stderr.on('data', (data) => { stderrText += data.toString() })

    child.on('close', (code) => {
      if (code === 0 && jsxPath) resolve({ jsxPath })
      else reject(new Error(`.jsx 생성 실패 (코드: ${code})\nSTDERR:\n${stderrText}`))
    })

    child.on('error', (err) => reject(new Error(err.message)))
  })
})

// ── 범용 파일 다른 이름으로 저장 ─────────────────────────────
ipcMain.handle('save-file-as', async (event, { sourcePath, title, filterName, ext }) => {
  const { canceled, filePath } = await dialog.showSaveDialog({
    title:       title      || '파일 저장',
    defaultPath: path.basename(sourcePath),
    filters:     [{ name: filterName || '파일', extensions: [ext || 'png'] }],
  })
  if (canceled || !filePath) return null
  copyFileSync(sourcePath, filePath)
  return filePath
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
