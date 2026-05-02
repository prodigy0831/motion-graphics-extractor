// 렌더러 프로세스: 비디오 플레이어 로직

const dropZone      = document.getElementById('dropZone')
const videoWrapper  = document.getElementById('videoWrapper')
const video         = document.getElementById('video')
const playBtn       = document.getElementById('playBtn')
const seekbar       = document.getElementById('seekbar')
const timeDisplay   = document.getElementById('timeDisplay')
const durationDisplay = document.getElementById('durationDisplay')
const metaInfo      = document.getElementById('metaInfo')
const frameBack     = document.getElementById('frameBack')
const frameForward  = document.getElementById('frameForward')

let fps = 30  // 기본값 — 실제 fps는 백엔드 연동 후 갱신 예정

// ── 시간 포맷 ──────────────────────────────────────────────────
function formatTime(sec) {
  if (!isFinite(sec)) return '00:00:00'
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = Math.floor(sec % 60)
  return [h, m, s].map(v => String(v).padStart(2, '0')).join(':')
}

// ── 영상 로드 ──────────────────────────────────────────────────
function loadVideo(src) {
  video.src = src
  dropZone.hidden = true
  videoWrapper.hidden = false
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

  loadVideo(URL.createObjectURL(file))
})

// ── 클릭으로 파일 선택 ─────────────────────────────────────────
dropZone.addEventListener('click', async () => {
  const filePath = await window.electronAPI.selectVideoFile()
  if (!filePath) return
  // 로컬 파일은 file:// 프로토콜로 직접 로드
  loadVideo(`file://${filePath}`)
})

// ── 메타데이터 로드 ────────────────────────────────────────────
video.addEventListener('loadedmetadata', () => {
  const { videoWidth, videoHeight, duration } = video
  const totalFrames = Math.round(duration * fps)

  durationDisplay.textContent = formatTime(duration)
  seekbar.max = Math.round(duration * 1000)  // 밀리초 단위로 정밀도 확보

  metaInfo.textContent =
    `${videoWidth}×${videoHeight}  ·  ${fps}fps  ·  ${totalFrames}f`
})

// ── 재생 상태 업데이트 ─────────────────────────────────────────
video.addEventListener('timeupdate', () => {
  timeDisplay.textContent = formatTime(video.currentTime)
  if (!seekbar._dragging) {
    seekbar.value = Math.round(video.currentTime * 1000)
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

// ── 진행 바 시크 ───────────────────────────────────────────────
seekbar.addEventListener('mousedown', () => { seekbar._dragging = true })

seekbar.addEventListener('input', () => {
  video.currentTime = seekbar.value / 1000
  timeDisplay.textContent = formatTime(video.currentTime)
  updateSeekbarFill()
})

function updateSeekbarFill() {
  const pct = (seekbar.value / seekbar.max) * 100
  seekbar.style.setProperty('--progress', `${pct}%`)
}

video.addEventListener('timeupdate', updateSeekbarFill)

seekbar.addEventListener('mouseup', () => { seekbar._dragging = false })

// ── 프레임 단위 이동 ───────────────────────────────────────────
function stepFrame(delta) {
  if (!video.src) return
  video.pause()
  video.currentTime = Math.max(
    0,
    Math.min(video.duration, video.currentTime + delta / fps)
  )
}

frameBack.addEventListener('click',    () => stepFrame(-1))
frameForward.addEventListener('click', () => stepFrame(+1))

// ── 키보드 단축키 ──────────────────────────────────────────────
document.addEventListener('keydown', e => {
  // 입력 필드에서는 단축키 무시
  if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return
  if (!video.src) return

  switch (e.code) {
    case 'Space':
      e.preventDefault()
      togglePlay()
      break
    case 'ArrowLeft':
      e.preventDefault()
      stepFrame(-1)
      break
    case 'ArrowRight':
      e.preventDefault()
      stepFrame(+1)
      break
  }
})
