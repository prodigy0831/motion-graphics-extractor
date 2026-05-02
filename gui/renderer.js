// 렌더러 프로세스: 비디오 플레이어 + 객체 클릭 인터페이스 + 결과 패널

const dropZone          = document.getElementById('dropZone')
const videoWrapper      = document.getElementById('videoWrapper')
const video             = document.getElementById('video')
const clickCanvas       = document.getElementById('clickCanvas')
const hintOverlay       = document.getElementById('hintOverlay')
const hintText          = document.getElementById('hintText')
const resultPanel       = document.getElementById('resultPanel')
const debugVideo        = document.getElementById('debugVideo')
const statFrames        = document.getElementById('statFrames')
const statRes           = document.getElementById('statRes')
const statFps           = document.getElementById('statFps')
const statScale         = document.getElementById('statScale')
const statRot           = document.getElementById('statRot')
const downloadJsxBtn    = document.getElementById('downloadJsxBtn')
const openFolderBtn     = document.getElementById('openFolderBtn')
const newVideoBtn       = document.getElementById('newVideoBtn')
const playBtn           = document.getElementById('playBtn')
const seekbar           = document.getElementById('seekbar')
const timeDisplay       = document.getElementById('timeDisplay')
const durationDisplay   = document.getElementById('durationDisplay')
const metaInfo          = document.getElementById('metaInfo')
const frameBack         = document.getElementById('frameBack')
const frameForward      = document.getElementById('frameForward')
const selectBtn         = document.getElementById('selectBtn')
const clearBtn          = document.getElementById('clearBtn')
const clickCoord        = document.getElementById('clickCoord')
const extractBtn        = document.getElementById('extractBtn')
const extractStatus     = document.getElementById('extractStatus')
const extractRow        = document.getElementById('extractRow')
const clickRow          = document.getElementById('clickRow')
const progressFill      = document.getElementById('progressFill')
const extractStatusRunning = document.getElementById('extractStatusRunning')

let fps              = 30
let clickMode        = false
let currentVideoPath = null
let lastOutputPath   = null   // 추출 완료 후 output 경로

// 클릭 데이터: frame, time, x, y (영상 원본 좌표), x_norm, y_norm
let clickData = null

// ── 시간 포맷 ──────────────────────────────────────────────────
function formatTime(sec) {
  if (!isFinite(sec)) return '00:00:00'
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  return [h, m, s].map(v => String(v).padStart(2, '0')).join(':')
}

// ── 힌트 표시 ──────────────────────────────────────────────────
function showHint(msg) {
  hintText.textContent = msg
  hintOverlay.hidden = false
}

function hideHint() {
  hintOverlay.hidden = true
}

// ── 상태: 추출 중 UI 잠금 ──────────────────────────────────────
function setExtracting(active) {
  extractBtn.disabled  = active
  selectBtn.disabled   = active
  clearBtn.disabled    = active
  frameBack.disabled   = active
  frameForward.disabled = active
  playBtn.disabled     = active
  seekbar.disabled     = active

  extractRow.hidden = !active
  clickRow.hidden   = active

  if (!active) {
    progressFill.style.width = '0%'
    extractStatusRunning.textContent = ''
  }
}

// ── 영상 로드 ──────────────────────────────────────────────────
function loadVideo(src) {
  video.src = src
  dropZone.hidden = true
  resultPanel.hidden = true
  videoWrapper.hidden = false
  clearClick()
  hideHint()
  lastOutputPath = null
  extractStatus.textContent = ''
  extractStatus.className = 'extract-status'
  setExtracting(false)
  // 재생 컨트롤 버튼 재활성화
  frameBack.disabled = false
  frameForward.disabled = false
  playBtn.disabled = false
  seekbar.disabled = false
}

// ── 파일 검증 ──────────────────────────────────────────────────
const VALID_EXT = ['mp4', 'mov', 'webm', 'avi']

function isValidVideo(filename) {
  const ext = filename.split('.').pop().toLowerCase()
  return VALID_EXT.includes(ext)
}

// ── 드래그 앤 드롭 ─────────────────────────────────────────────
document.addEventListener('dragover', e => {
  e.preventDefault()
  dropZone.classList.add('drag-over')
})

document.addEventListener('dragleave', e => {
  if (!e.relatedTarget) dropZone.classList.remove('drag-over')
})

document.addEventListener('drop', e => {
  e.preventDefault()
  dropZone.classList.remove('drag-over')
  const file = e.dataTransfer.files[0]
  if (!file) return
  if (!isValidVideo(file.name)) {
    alert(`지원하지 않는 형식입니다: ${file.name}\n지원 형식: MP4, MOV, WebM`)
    return
  }
  // Electron 32+: file.path 대신 webUtils.getPathForFile 사용
  currentVideoPath = window.electronAPI.getFilePath(file)
  loadVideo(URL.createObjectURL(file))
})

// ── 클릭으로 파일 선택 ─────────────────────────────────────────
dropZone.addEventListener('click', async () => {
  try {
    const filePath = await window.electronAPI.selectVideoFile()
    if (!filePath) return
    currentVideoPath = filePath
    loadVideo(`file://${filePath}`)
  } catch (err) {
    console.error('파일 선택 오류:', err)
    alert(`파일 선택 중 오류가 발생했습니다: ${err.message}`)
  }
})

// ── 메타데이터 로드 ────────────────────────────────────────────
video.addEventListener('loadedmetadata', () => {
  const { videoWidth, videoHeight, duration } = video
  const totalFrames = Math.round(duration * fps)

  durationDisplay.textContent = formatTime(duration)
  seekbar.max = Math.round(duration * 1000)
  metaInfo.textContent = `${videoWidth}×${videoHeight}  ·  ${fps}fps  ·  ${totalFrames}f`

  syncCanvas()

  // 영상 로드 직후 힌트: 객체 선택 유도
  showHint('객체 선택 버튼을 누른 뒤 추적할 객체를 클릭하세요')
})

// ── 재생 상태 업데이트 ─────────────────────────────────────────
video.addEventListener('timeupdate', () => {
  timeDisplay.textContent = formatTime(video.currentTime)
  if (!seekbar._dragging) {
    seekbar.value = Math.round(video.currentTime * 1000)
    updateSeekbarFill()
  }
})

video.addEventListener('play',  () => { playBtn.textContent = '⏸' })
video.addEventListener('pause', () => { playBtn.textContent = '▶' })
video.addEventListener('ended', () => { playBtn.textContent = '▶' })

// ── 재생/정지 ──────────────────────────────────────────────────
function togglePlay() {
  if (video.paused) video.play()
  else              video.pause()
}

playBtn.addEventListener('click', togglePlay)

// ── 진행 바 ────────────────────────────────────────────────────
seekbar.addEventListener('mousedown', () => { seekbar._dragging = true })

seekbar.addEventListener('input', () => {
  video.currentTime = seekbar.value / 1000
  timeDisplay.textContent = formatTime(video.currentTime)
  updateSeekbarFill()
})

seekbar.addEventListener('mouseup', () => { seekbar._dragging = false })

function updateSeekbarFill() {
  const pct = (seekbar.value / seekbar.max) * 100
  seekbar.style.setProperty('--progress', `${pct}%`)
}

video.addEventListener('timeupdate', updateSeekbarFill)

// ── 프레임 이동 ────────────────────────────────────────────────
function stepFrame(delta) {
  if (!video.src) return
  video.pause()
  video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + delta / fps))
}

frameBack.addEventListener('click',    () => stepFrame(-1))
frameForward.addEventListener('click', () => stepFrame(+1))

// ── 키보드 단축키 ──────────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return
  if (!video.src) return
  switch (e.code) {
    case 'Space':       e.preventDefault(); togglePlay();   break
    case 'ArrowLeft':   e.preventDefault(); stepFrame(-1);  break
    case 'ArrowRight':  e.preventDefault(); stepFrame(+1);  break
  }
})

// ═══════════════════════════════════════════════════════════════
// 캔버스 오버레이 & 객체 클릭
// ═══════════════════════════════════════════════════════════════

// ── 캔버스를 영상 렌더링 영역에 정확히 동기화 ──────────────────
function syncCanvas() {
  if (!video.videoWidth) return

  const wRect = videoWrapper.getBoundingClientRect()
  const vRect = video.getBoundingClientRect()

  const left   = vRect.left - wRect.left
  const top    = vRect.top  - wRect.top
  const width  = vRect.width
  const height = vRect.height

  clickCanvas.style.left   = `${left}px`
  clickCanvas.style.top    = `${top}px`
  clickCanvas.style.width  = `${width}px`
  clickCanvas.style.height = `${height}px`
  clickCanvas.width        = width
  clickCanvas.height       = height

  if (clickData) redrawMarker()
}

window.addEventListener('resize', syncCanvas)

// ── 클릭 모드 토글 ─────────────────────────────────────────────
function setClickMode(active) {
  clickMode = active
  selectBtn.classList.toggle('active', active)
  clickCanvas.style.pointerEvents = active ? 'all' : 'none'
  clickCanvas.style.cursor = active ? 'crosshair' : 'default'

  if (active) {
    video.pause()
    showHint('추적할 객체를 클릭하세요')
  } else {
    hideHint()
  }
}

selectBtn.addEventListener('click', () => {
  if (!video.src) return
  setClickMode(!clickMode)
})

// ── 마커 초기화 ────────────────────────────────────────────────
function clearClick() {
  clickData = null
  const ctx = clickCanvas.getContext('2d')
  ctx.clearRect(0, 0, clickCanvas.width, clickCanvas.height)
  clickCoord.textContent = '—'
  extractBtn.disabled = true
}

clearBtn.addEventListener('click', () => {
  clearClick()
  hideHint()
})

// ── 마커 그리기 ────────────────────────────────────────────────
function drawMarker(cx, cy) {
  const ctx   = clickCanvas.getContext('2d')
  const SIZE  = 14
  const COLOR = '#ffeb3b'

  ctx.clearRect(0, 0, clickCanvas.width, clickCanvas.height)

  ctx.save()
  ctx.strokeStyle = COLOR
  ctx.lineWidth = 2
  ctx.shadowColor = 'rgba(0, 0, 0, 0.9)'
  ctx.shadowBlur  = 6

  ctx.beginPath()
  ctx.moveTo(cx - SIZE, cy)
  ctx.lineTo(cx + SIZE, cy)
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(cx, cy - SIZE)
  ctx.lineTo(cx, cy + SIZE)
  ctx.stroke()

  ctx.beginPath()
  ctx.arc(cx, cy, 7, 0, Math.PI * 2)
  ctx.stroke()
  ctx.restore()
}

function redrawMarker() {
  if (!clickData) return
  const cx = (clickData.x / video.videoWidth)  * clickCanvas.width
  const cy = (clickData.y / video.videoHeight) * clickCanvas.height
  drawMarker(cx, cy)
}

// ── 캔버스 클릭 이벤트 ─────────────────────────────────────────
clickCanvas.addEventListener('click', e => {
  if (!clickMode) return

  const rect = clickCanvas.getBoundingClientRect()
  const cx   = e.clientX - rect.left
  const cy   = e.clientY - rect.top

  const x = Math.round((cx / clickCanvas.width)  * video.videoWidth)
  const y = Math.round((cy / clickCanvas.height) * video.videoHeight)

  const frame  = Math.round(video.currentTime * fps)
  const time   = Math.round(video.currentTime * 1000) / 1000
  const x_norm = Math.round((x / video.videoWidth)  * 10000) / 10000
  const y_norm = Math.round((y / video.videoHeight) * 10000) / 10000

  clickData = { frame, time, x, y, x_norm, y_norm }

  drawMarker(cx, cy)
  clickCoord.textContent = `클릭: (${x}, ${y})  [${x_norm}, ${y_norm}]  프레임 ${frame}`

  extractBtn.disabled = false
  setClickMode(false)

  showHint('추출 시작 버튼을 눌러 SAM 2 추적을 시작하세요')
})

// ── 결과 패널 표시 ─────────────────────────────────────────────
// outputPath: Python이 DONE: 으로 내보내는 _coords.json 절대경로
function showResultPanel(outputPath) {
  lastOutputPath = outputPath

  // _coords.json → _debug.mp4 / .jsx 파생
  const debugPath = outputPath.replace('_coords.json', '_debug.mp4')
  const jsxPath   = outputPath.replace('_coords.json', '.jsx')

  // 한글 경로 포함 file:// URL 안전 인코딩
  debugVideo.src = encodeURI('file://' + debugPath)

  // 통계: video 메타에서 취득
  const totalFrames = Math.round(video.duration * fps)
  statFrames.textContent = `${totalFrames}f`
  statRes.textContent    = `${video.videoWidth}×${video.videoHeight}`
  statFps.textContent    = `${fps}`
  statScale.textContent  = '—'
  statRot.textContent    = '—'

  // JSX 다운로드 버튼에 경로 연결
  downloadJsxBtn._jsxPath = jsxPath

  videoWrapper.hidden = true
  resultPanel.hidden  = false
  clickRow.hidden     = false
  extractRow.hidden   = true
}

// ── 결과 버튼 핸들러 ───────────────────────────────────────────
downloadJsxBtn.addEventListener('click', async () => {
  const src = downloadJsxBtn._jsxPath
  if (!src) return
  const saved = await window.electronAPI.saveJsxAs(src)
  if (saved) {
    downloadJsxBtn.textContent = '저장 완료 ✓'
    setTimeout(() => { downloadJsxBtn.textContent = 'AE 스크립트 저장' }, 2000)
  }
})

openFolderBtn.addEventListener('click', () => {
  window.electronAPI.openOutputFolder()
})

newVideoBtn.addEventListener('click', () => {
  // 결과 패널 숨기고 드롭존으로 돌아가기
  resultPanel.hidden = true
  debugVideo.src = ''
  dropZone.hidden = false
  currentVideoPath = null
  lastOutputPath   = null
  clickData        = null
  clickCoord.textContent = '—'
  extractBtn.disabled = true
  extractStatus.textContent = ''
  extractStatus.className = 'extract-status'
  video.src = ''
  timeDisplay.textContent = '00:00:00'
  durationDisplay.textContent = '00:00:00'
  metaInfo.textContent = '—'
  seekbar.value = 0
  updateSeekbarFill()
  setExtracting(false)
  hideHint()
})

// ── 추출 시작 ──────────────────────────────────────────────────
extractBtn.addEventListener('click', async () => {
  if (!clickData || !currentVideoPath) return

  setExtracting(true)
  extractStatusRunning.textContent = '준비 중...'
  hideHint()

  window.electronAPI.removeExtractListeners()

  window.electronAPI.onProgress(({ current, total }) => {
    const pct = Math.round((current / total) * 100)
    progressFill.style.width = `${pct}%`
    extractStatusRunning.textContent = `처리 중: ${current} / ${total}  (${pct}%)`
  })

  window.electronAPI.onComplete(({ outputPath }) => {
    setExtracting(false)
    const filename = outputPath.split('/').pop()
    extractStatus.textContent = `완료: ${filename}`
    extractStatus.className   = 'extract-status done'
    showResultPanel(outputPath)
  })

  window.electronAPI.onError(({ message }) => {
    setExtracting(false)
    extractStatus.textContent = `오류: ${message.slice(0, 60)}`
    extractStatus.className   = 'extract-status error'
  })

  try {
    await window.electronAPI.extractWithSam2({
      videoPath: currentVideoPath,
      frame: clickData.frame,
      x:     clickData.x,
      y:     clickData.y,
    })
  } catch (err) {
    setExtracting(false)
    extractStatus.textContent = `오류: ${err.message.slice(0, 60)}`
    extractStatus.className   = 'extract-status error'
  }
})
