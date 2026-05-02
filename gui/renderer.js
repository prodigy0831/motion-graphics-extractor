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
const trajCanvas        = document.getElementById('trajCanvas')
const scaleCanvas       = document.getElementById('scaleCanvas')
const scaleEmpty        = document.getElementById('scaleEmpty')
const rotCanvas         = document.getElementById('rotCanvas')
const rotEmpty          = document.getElementById('rotEmpty')

let fps              = 30
let clickMode        = false
let currentVideoPath = null
let lastOutputPath   = null

// 클릭 데이터: frame, time, x, y (영상 원본 좌표), x_norm, y_norm
let clickData = null

// 마스크 프리뷰 상태
let maskImage     = null  // 로드된 Image 객체
let maskRequestId = 0     // 최신 요청 추적 (이전 요청 응답 무시용)

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

  if (clickData) redrawCanvas()
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
  clickData  = null
  maskImage  = null
  ++maskRequestId   // 진행 중인 프리뷰 요청 무효화
  clickCanvas.getContext('2d').clearRect(0, 0, clickCanvas.width, clickCanvas.height)
  clickCoord.textContent = '—'
  extractBtn.disabled = true
}

clearBtn.addEventListener('click', () => {
  clearClick()
  hideHint()
})

// ── 캔버스 전체 재렌더 (마스크 + 마커) ────────────────────────
function redrawCanvas() {
  const ctx = clickCanvas.getContext('2d')
  ctx.clearRect(0, 0, clickCanvas.width, clickCanvas.height)

  if (maskImage) {
    ctx.drawImage(maskImage, 0, 0, clickCanvas.width, clickCanvas.height)
  }

  if (clickData) {
    const cx = (clickData.x / video.videoWidth)  * clickCanvas.width
    const cy = (clickData.y / video.videoHeight) * clickCanvas.height
    _drawMarkerShape(ctx, cx, cy)
  }
}

// ── 마커 도형 그리기 (clear 없이 현재 ctx 위에 그림) ──────────
function _drawMarkerShape(ctx, cx, cy) {
  const SIZE  = 14
  const COLOR = '#ffeb3b'

  ctx.save()
  ctx.strokeStyle = COLOR
  ctx.lineWidth   = 2
  ctx.shadowColor = 'rgba(0, 0, 0, 0.9)'
  ctx.shadowBlur  = 6

  ctx.beginPath(); ctx.moveTo(cx - SIZE, cy); ctx.lineTo(cx + SIZE, cy); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(cx, cy - SIZE); ctx.lineTo(cx, cy + SIZE); ctx.stroke()
  ctx.beginPath(); ctx.arc(cx, cy, 7, 0, Math.PI * 2); ctx.stroke()
  ctx.restore()
}

// ── 마스크 프리뷰 요청 ─────────────────────────────────────────
// data: URL → blob URL 변환 (CSP data: 차단 우회)
function dataUrlToBlob(dataUrl) {
  const [header, b64] = dataUrl.split(',')
  const mime  = header.match(/:(.*?);/)[1]
  const bytes = atob(b64)
  const arr   = new Uint8Array(bytes.length)
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i)
  return new Blob([arr], { type: mime })
}

async function requestMaskPreview() {
  if (!clickData || !currentVideoPath) return
  const myId = ++maskRequestId

  showHint('객체 인식 중...')
  try {
    const { dataUrl } = await window.electronAPI.previewMask({
      videoPath: currentVideoPath,
      time: clickData.time,
      x:    clickData.x,
      y:    clickData.y,
    })
    if (myId !== maskRequestId) return

    // blob URL로 변환해서 로드 (CSP data: 차단 우회)
    const blobUrl = URL.createObjectURL(dataUrlToBlob(dataUrl))
    const img     = new Image()
    img.onload = () => {
      URL.revokeObjectURL(blobUrl)
      if (myId !== maskRequestId) return
      maskImage = img
      redrawCanvas()
      showHint('추출 시작 버튼을 눌러 SAM 2 추적을 시작하세요')
    }
    img.onerror = (e) => {
      URL.revokeObjectURL(blobUrl)
      console.error('마스크 이미지 로드 실패:', e)
      showHint('추출 시작 버튼을 눌러 SAM 2 추적을 시작하세요')
    }
    img.src = blobUrl
  } catch (err) {
    if (myId !== maskRequestId) return
    console.error('마스크 프리뷰 실패:', err)
    showHint('추출 시작 버튼을 눌러 SAM 2 추적을 시작하세요')
  }
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

  clickData  = { frame, time, x, y, x_norm, y_norm }
  maskImage  = null   // 이전 마스크 제거

  redrawCanvas()   // 마커 즉시 표시
  clickCoord.textContent = `클릭: (${x}, ${y})  [${x_norm}, ${y_norm}]  프레임 ${frame}`

  extractBtn.disabled = false
  setClickMode(false)

  requestMaskPreview()   // 비동기로 마스크 요청
})

// ═══════════════════════════════════════════════════════════════
// 시각화: 궤적 / 스케일 / 회전
// ═══════════════════════════════════════════════════════════════

// ── 궤적 캔버스 ────────────────────────────────────────────────
function drawTrajectory(canvas, frames, vidW, vidH) {
  const W   = canvas.width
  const H   = canvas.height
  const ctx = canvas.getContext('2d')

  ctx.fillStyle = '#0d0d0d'
  ctx.fillRect(0, 0, W, H)

  // 격자
  ctx.strokeStyle = '#1e1e1e'
  ctx.lineWidth = 0.5
  for (let i = 1; i < 4; i++) {
    ctx.beginPath(); ctx.moveTo(W * i / 4, 0);   ctx.lineTo(W * i / 4, H);   ctx.stroke()
    ctx.beginPath(); ctx.moveTo(0, H * i / 4);   ctx.lineTo(W, H * i / 4);   ctx.stroke()
  }

  const valid = frames.filter(f => f.x !== null && f.x !== undefined)
  if (valid.length < 2) {
    ctx.fillStyle = '#444'
    ctx.font = '11px -apple-system, sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('추적 데이터 없음', W / 2, H / 2)
    return
  }

  const sx = W / vidW
  const sy = H / vidH
  const n  = valid.length

  // 시간 그라데이션 경로 (초록 → 빨강)
  for (let i = 1; i < n; i++) {
    const t = i / (n - 1)
    const r = Math.round(34  + (239 - 34)  * t)
    const g = Math.round(197 + (68  - 197) * t)
    const b = Math.round(94  + (68  - 94)  * t)
    ctx.strokeStyle = `rgb(${r},${g},${b})`
    ctx.lineWidth   = 1.5
    ctx.lineJoin    = 'round'
    ctx.beginPath()
    ctx.moveTo(valid[i - 1].x * sx, valid[i - 1].y * sy)
    ctx.lineTo(valid[i].x * sx,     valid[i].y * sy)
    ctx.stroke()
  }

  // 시작 마커 (초록 ●)
  ctx.fillStyle = '#22c55e'
  ctx.beginPath()
  ctx.arc(valid[0].x * sx, valid[0].y * sy, 4, 0, Math.PI * 2)
  ctx.fill()

  // 끝 마커 (빨강 ●)
  ctx.fillStyle = '#ef4444'
  ctx.beginPath()
  ctx.arc(valid[n - 1].x * sx, valid[n - 1].y * sy, 4, 0, Math.PI * 2)
  ctx.fill()
}

// ── 라인 차트 (스케일 / 회전) ──────────────────────────────────
// 반환값: true = 그래프 그림, false = 변화 없음 (empty 메시지 표시 필요)
function drawLineChart(canvas, frames, key, unit, minChange) {
  const W   = canvas.width
  const H   = canvas.height
  const ctx = canvas.getContext('2d')
  const PAD = { top: 14, right: 8, bottom: 20, left: 38 }

  ctx.fillStyle = '#0d0d0d'
  ctx.fillRect(0, 0, W, H)

  const points = frames
    .map((f, i) => ({ i, v: f[key] }))
    .filter(p => p.v !== null && p.v !== undefined)

  if (points.length < 2) return false

  const vals  = points.map(p => p.v)
  const range = Math.max(...vals) - Math.min(...vals)
  if (range < minChange) return false

  const cW   = W - PAD.left - PAD.right
  const cH   = H - PAD.top  - PAD.bottom
  const yPad = Math.max(range * 0.12, 0.5)
  const yMin = Math.min(...vals) - yPad
  const yMax = Math.max(...vals) + yPad
  const yRng = yMax - yMin
  const total = frames.length - 1

  const toX = (fi) => PAD.left + (fi / total) * cW
  const toY = (v)  => PAD.top  + (1 - (v - yMin) / yRng) * cH

  // 격자 + Y 레이블
  ctx.strokeStyle = '#2a2a2a'
  ctx.lineWidth   = 0.5
  ctx.font        = '9px -apple-system, sans-serif'
  ctx.textAlign   = 'right'
  for (let i = 0; i <= 3; i++) {
    const gy  = PAD.top + (i / 3) * cH
    const val = yMax - (i / 3) * yRng
    ctx.beginPath(); ctx.moveTo(PAD.left, gy); ctx.lineTo(PAD.left + cW, gy); ctx.stroke()
    ctx.fillStyle = '#555'
    ctx.fillText(val.toFixed(1) + unit, PAD.left - 3, gy + 3)
  }

  // 라인
  ctx.strokeStyle = '#4a9eff'
  ctx.lineWidth   = 1.5
  ctx.lineJoin    = 'round'
  ctx.beginPath()
  points.forEach((p, idx) => {
    if (idx === 0) ctx.moveTo(toX(p.i), toY(p.v))
    else           ctx.lineTo(toX(p.i), toY(p.v))
  })
  ctx.stroke()

  return true
}

// ── 시각화 렌더링 ──────────────────────────────────────────────
function renderVisualizations(data) {
  const { frames, width: vidW, height: vidH } = data

  // 캔버스 크기: 컨테이너 너비에 맞춤
  const cw = trajCanvas.clientWidth || 220

  // 궤적: 영상 비율 유지
  trajCanvas.width  = cw
  trajCanvas.height = Math.round(cw * vidH / vidW)
  drawTrajectory(trajCanvas, frames, vidW, vidH)

  // 스케일 차트
  scaleCanvas.width  = cw
  scaleCanvas.height = 90
  const hasScale = drawLineChart(scaleCanvas, frames, 'scale', '%', 5)
  scaleCanvas.hidden = !hasScale
  scaleEmpty.hidden  = hasScale

  // 회전 차트
  rotCanvas.width  = cw
  rotCanvas.height = 90
  const hasRot = drawLineChart(rotCanvas, frames, 'rotation', '°', 1)
  rotCanvas.hidden = !hasRot
  rotEmpty.hidden  = hasRot
}

// ── 통계 업데이트 (JSON 데이터 기반) ──────────────────────────
function updateStatsFromData(data) {
  const { width, height, fps: dataFps, total_frames, frames } = data
  statFrames.textContent = `${total_frames}f`
  statRes.textContent    = `${width}×${height}`
  statFps.textContent    = `${dataFps}`

  const scaleVals = frames.map(f => f.scale).filter(v => v !== null && v !== undefined)
  if (scaleVals.length > 0) {
    const sMin = Math.min(...scaleVals)
    const sMax = Math.max(...scaleVals)
    statScale.textContent = `${sMin.toFixed(0)}% ~ ${sMax.toFixed(0)}%`
  }

  const rotVals = frames.map(f => f.rotation).filter(v => v !== null && v !== undefined)
  if (rotVals.length > 0) {
    const rMin = Math.min(...rotVals)
    const rMax = Math.max(...rotVals)
    statRot.textContent = `${rMin.toFixed(1)}° ~ ${rMax.toFixed(1)}°`
  }
}

// ── 결과 패널 표시 ─────────────────────────────────────────────
// outputPath: Python이 DONE: 으로 내보내는 _coords.json 절대경로
async function showResultPanel(outputPath) {
  lastOutputPath = outputPath

  // _coords.json → _debug.mp4 / .jsx 파생
  const debugPath = outputPath.replace('_coords.json', '_debug.mp4')
  const jsxPath   = outputPath.replace('_coords.json', '.jsx')

  // 한글 경로 포함 file:// URL 안전 인코딩
  debugVideo.src = encodeURI('file://' + debugPath)

  // JSX 다운로드 버튼에 경로 연결
  downloadJsxBtn._jsxPath = jsxPath

  // 패널 먼저 표시 (clientWidth 측정을 위해 DOM 렌더 필요)
  videoWrapper.hidden = true
  resultPanel.hidden  = false
  clickRow.hidden     = false
  extractRow.hidden   = true

  // JSON 로드 → 통계 + 시각화
  try {
    const data = await window.electronAPI.loadCoordsJson(outputPath)
    updateStatsFromData(data)
    renderVisualizations(data)
  } catch (err) {
    console.error('좌표 데이터 로드 실패:', err)
    // JSON 로드 실패 시 video 메타 기반으로 기본 통계만 표시
    const totalFrames = Math.round(video.duration * fps)
    statFrames.textContent = `${totalFrames}f`
    statRes.textContent    = `${video.videoWidth}×${video.videoHeight}`
    statFps.textContent    = `${fps}`
  }
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

  // 캔버스 초기화
  ;[trajCanvas, scaleCanvas, rotCanvas].forEach(c => {
    c.getContext('2d').clearRect(0, 0, c.width, c.height)
    c.hidden = false
  })
  scaleEmpty.hidden = true
  rotEmpty.hidden   = true
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
      time: clickData.time,
      x:    clickData.x,
      y:    clickData.y,
    })
  } catch (err) {
    setExtracting(false)
    extractStatus.textContent = `오류: ${err.message.slice(0, 60)}`
    extractStatus.className   = 'extract-status error'
  }
})
