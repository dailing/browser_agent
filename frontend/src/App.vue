<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import mermaid from 'mermaid'
import { Toast } from 'bootstrap'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
const origFence = md.renderer.rules.fence
md.renderer.rules.fence = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const info = String(token.info || '')
    .trim()
    .split(/\s+/)[0]
  if (info === 'mermaid') {
    return `<div class="mermaid">${md.utils.escapeHtml(token.content)}</div>\n`
  }
  return origFence ? origFence(tokens, idx, options, env, self) : self.renderToken(tokens, idx, options)
}

const sessions = ref([])
const loadingSessions = ref(false)
const newSessionName = ref('')
const newMaxSteps = ref(40)
const creatingSession = ref(false)
const deletingSessionId = ref(null)

const sessionId = ref(null)
const messages = ref([])
const runStatus = ref('')
const draft = ref('')
const sending = ref(false)

const logEl = ref(null)
const analysisLogEl = ref(null)
const imgSrc = ref('')
const previewPlaceholder = ref(false)
const previewTabReady = ref(false)
const previewStatus = ref('connecting')
const viewportWidth = ref(0)
const viewportHeight = ref(0)
const remoteMouseEnabled = ref(false)
const viewportPresets = ref([])
const viewportPresetId = ref('')
const viewportApplyBusy = ref(false)
const VIEWPORT_LS_KEY = 'browser_agent_viewport_preset'
const SPLIT_PCT_LS_KEY = 'browser_agent_split_pct'

const mainView = ref('workspace')
const skillsList = ref([])
const loadingSkills = ref(false)
const skillPanelId = ref(null)
const skillDetail = ref(null)
const loadingSkillDetail = ref(false)
const composerSkillId = ref('')

const analysisResult = ref('')
const analysisBusy = ref(false)

const MIN_CHAT_W = 220
const MIN_PREVIEW_W = 200
const GUTTER_W = 4

function readInitialSplitPct() {
  const n = Number(typeof localStorage !== 'undefined' ? localStorage.getItem(SPLIT_PCT_LS_KEY) : NaN)
  if (Number.isFinite(n) && n >= 22 && n <= 78) return n
  return 52
}
const splitPct = ref(readInitialSplitPct())
const workspaceBodyEl = ref(null)

let toastSeq = 0
const toastItems = ref([])

function showAppToast(message, variant = 'warning') {
  const text = String(message || '').trim()
  if (!text) return
  const id = ++toastSeq
  toastItems.value = [...toastItems.value, { id, message: text, variant }]
  nextTick(() => {
    const el = document.getElementById(`app-toast-${id}`)
    if (!el) return
    const t = Toast.getOrCreateInstance(el, { autohide: true, delay: 6000 })
    const onHidden = () => {
      el.removeEventListener('hidden.bs.toast', onHidden)
      toastItems.value = toastItems.value.filter((x) => x.id !== id)
    }
    el.addEventListener('hidden.bs.toast', onHidden)
    t.show()
  })
}

const chatCollapsed = ref(false)
const previewCollapsed = ref(false)

function persistSplitPct() {
  try {
    localStorage.setItem(SPLIT_PCT_LS_KEY, String(Math.round(splitPct.value)))
  } catch {
    /* ignore */
  }
}

function clampSplitPctForWidth(pct, totalW) {
  const W = totalW || 1
  const lo = (MIN_CHAT_W / W) * 100
  const hi = ((W - MIN_PREVIEW_W - GUTTER_W) / W) * 100
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi < lo) return pct
  return Math.max(lo, Math.min(hi, pct))
}

function onSplitDragMouseDown(ev) {
  if (!bothPanelsOpen.value) return
  onSplitMouseDown(ev)
}

function onSplitMouseDown(ev) {
  ev.preventDefault()
  ev.stopPropagation()
  const container = workspaceBodyEl.value
  if (!container || chatCollapsed.value || previewCollapsed.value) return
  const rect = container.getBoundingClientRect()
  const total = rect.width || 1
  const startX = ev.clientX
  const startPct = splitPct.value

  function onMove(e) {
    const dx = e.clientX - startX
    const next = startPct + (dx / total) * 100
    splitPct.value = clampSplitPctForWidth(next, total)
  }
  function onUp() {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    const w = container.getBoundingClientRect().width
    splitPct.value = clampSplitPctForWidth(splitPct.value, w)
    persistSplitPct()
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

const bothPanelsOpen = computed(() => !chatCollapsed.value && !previewCollapsed.value)

const workspaceBodyGridStyle = computed(() => {
  const g = GUTTER_W
  if (chatCollapsed.value && previewCollapsed.value) {
    return {
      display: 'grid',
      gridTemplateColumns: `${g}px`,
      gridTemplateRows: 'minmax(0, 1fr)',
    }
  }
  if (chatCollapsed.value) {
    return {
      display: 'grid',
      gridTemplateColumns: `${g}px minmax(0, 1fr)`,
      gridTemplateRows: 'minmax(0, 1fr)',
    }
  }
  if (previewCollapsed.value) {
    return {
      display: 'grid',
      gridTemplateColumns: `minmax(0, 1fr) ${g}px`,
      gridTemplateRows: 'minmax(0, 1fr)',
    }
  }
  const p = splitPct.value
  return {
    display: 'grid',
    gridTemplateColumns: `minmax(0, ${p}%) ${g}px minmax(0, 1fr)`,
    gridTemplateRows: 'minmax(0, 1fr)',
  }
})

function finishPanelLayout() {
  nextTick(() => {
    requestAnimationFrame(() => {
      const root = workspaceBodyEl.value
      if (root && !chatCollapsed.value && !previewCollapsed.value) {
        let w = root.getBoundingClientRect().width
        if (w <= 0) {
          w = Math.max(360, window.innerWidth - 280)
        }
        splitPct.value = clampSplitPctForWidth(splitPct.value, w)
      }
      persistSplitPct()
    })
  })
}

function toggleChatPanel() {
  if (chatCollapsed.value) {
    chatCollapsed.value = false
  } else if (previewCollapsed.value) {
    previewCollapsed.value = false
    chatCollapsed.value = true
  } else {
    chatCollapsed.value = true
  }
  finishPanelLayout()
}

function togglePreviewPanel() {
  if (previewCollapsed.value) {
    previewCollapsed.value = false
  } else if (chatCollapsed.value) {
    chatCollapsed.value = false
    previewCollapsed.value = true
  } else {
    previewCollapsed.value = true
  }
  finishPanelLayout()
}

let previewWs = null
let previewReconnectTimer = null
let sessionWs = null
let previewMoveRaf = null
let previewMovePending = null

function connectPreview(id) {
  if (previewReconnectTimer) {
    clearTimeout(previewReconnectTimer)
    previewReconnectTimer = null
  }

  const sid = id || null
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const pathSuffix = `/ws/preview/${sid}`

  if (
    sid &&
    previewWs &&
    (previewWs.readyState === WebSocket.OPEN || previewWs.readyState === WebSocket.CONNECTING)
  ) {
    try {
      const p = new URL(previewWs.url).pathname
      if (p === pathSuffix || p.endsWith(pathSuffix)) return
    } catch {
      /* ignore */
    }
  }

  if (!sid) {
    if (previewWs) {
      previewWs.close()
      previewWs = null
    }
    previewStatus.value = 'no_session'
    imgSrc.value = ''
    previewPlaceholder.value = false
    previewTabReady.value = false
    viewportWidth.value = 0
    viewportHeight.value = 0
    return
  }

  if (previewWs) {
    previewWs.close()
    previewWs = null
  }

  imgSrc.value = ''
  previewPlaceholder.value = false
  previewTabReady.value = false
  const url = `${proto}//${location.host}${pathSuffix}`
  const ws = new WebSocket(url)
  previewWs = ws

  ws.onopen = () => {
    if (previewWs !== ws) return
    previewStatus.value = 'live'
  }

  ws.onmessage = (ev) => {
    if (previewWs !== ws) return
    try {
      const msg = JSON.parse(ev.data)
      if (msg.type !== 'preview') return
      if (msg.state === 'waiting') {
        imgSrc.value = ''
        previewPlaceholder.value = true
        previewTabReady.value = false
        viewportWidth.value = 0
        viewportHeight.value = 0
        return
      }
      if (msg.state === 'ping') {
        if (!imgSrc.value) {
          previewPlaceholder.value = true
          previewTabReady.value = false
        }
        return
      }
      if (msg.state === 'tab_opened') {
        previewPlaceholder.value = false
        previewTabReady.value = true
        return
      }
      if (msg.state === 'placeholder') {
        imgSrc.value = ''
        previewPlaceholder.value = true
        previewTabReady.value = false
        viewportWidth.value = 0
        viewportHeight.value = 0
        return
      }
      if (msg.state === 'live' && msg.mime === 'image/jpeg' && msg.data) {
        previewPlaceholder.value = false
        previewTabReady.value = false
        if (typeof msg.viewport_width === 'number' && typeof msg.viewport_height === 'number') {
          viewportWidth.value = msg.viewport_width
          viewportHeight.value = msg.viewport_height
        }
        imgSrc.value = `data:${msg.mime};base64,${msg.data}`
      }
    } catch {
      /* ignore */
    }
  }

  ws.onerror = () => {
    if (previewWs !== ws) return
    previewStatus.value = 'error'
  }

  ws.onclose = () => {
    if (previewWs !== ws) return
    if (!sessionId.value || sessionId.value !== sid) return
    previewStatus.value = 'reconnecting'
    previewReconnectTimer = setTimeout(() => {
      previewReconnectTimer = null
      if (sessionId.value === sid) connectPreview(sid)
    }, 1500)
  }
}

function disconnectSessionWs() {
  if (sessionWs) {
    sessionWs.close()
    sessionWs = null
  }
}

function connectSessionWs(id) {
  disconnectSessionWs()
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${proto}//${location.host}/ws/session/${id}`
  sessionWs = new WebSocket(url)
  sessionWs.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg.type === 'snapshot') {
        messages.value = [...(msg.messages || [])]
        runStatus.value = msg.status || ''
        if (msg.has_live_tab !== undefined && sessionId.value) {
          const sid = sessionId.value
          sessions.value = sessions.value.map((x) =>
            x.id === sid ? { ...x, has_live_tab: msg.has_live_tab } : x,
          )
        }
      } else if (msg.type === 'message') {
        messages.value = [...messages.value, msg.message]
      } else if (msg.type === 'status') {
        runStatus.value = msg.status || ''
        loadSessions()
      } else if (msg.type === 'live_tab' && msg.session_id) {
        sessions.value = sessions.value.map((x) =>
          x.id === msg.session_id ? { ...x, has_live_tab: !!msg.has_live_tab } : x,
        )
      }
    } catch {
      /* ignore */
    }
  }
  sessionWs.onerror = () => {}
}

async function loadSessions() {
  loadingSessions.value = true
  try {
    const r = await fetch('/api/sessions')
    if (r.ok) sessions.value = await r.json()
  } catch {
    sessions.value = []
  } finally {
    loadingSessions.value = false
  }
}

async function createSession() {
  if (creatingSession.value) return
  creatingSession.value = true
  try {
    const body = { max_steps: Number(newMaxSteps.value) || 40 }
    const n = newSessionName.value.trim()
    if (n) body.name = n
    const r = await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error((await r.text()) || r.statusText)
    const j = await r.json()
    sessionId.value = j.session_id
    messages.value = []
    runStatus.value = j.status || 'idle'
    connectSessionWs(j.session_id)
    await loadSessions()
  } catch (e) {
    showAppToast(e.message || String(e))
  } finally {
    creatingSession.value = false
  }
}

async function openSession(id) {
  if (sessionId.value === id) {
    chatCollapsed.value = false
    previewCollapsed.value = false
    finishPanelLayout()
    connectPreview(id)
    return
  }
  disconnectSessionWs()
  sessionId.value = id
  try {
    const r = await fetch(`/api/sessions/${id}`)
    if (!r.ok) throw new Error((await r.text()) || r.statusText)
    const j = await r.json()
    messages.value = [...(j.messages || [])]
    runStatus.value = j.status || ''
    if (j.has_live_tab !== undefined) {
      sessions.value = sessions.value.map((x) =>
        x.id === id ? { ...x, has_live_tab: j.has_live_tab } : x,
      )
    }
  } catch (e) {
    messages.value = []
    runStatus.value = ''
    showAppToast(e.message || String(e))
  }
  connectSessionWs(id)
}

async function deleteSession(id) {
  if (deletingSessionId.value) return
  deletingSessionId.value = id
  try {
    const r = await fetch(`/api/sessions/${id}`, { method: 'DELETE' })
    if (r.status === 409) {
      showAppToast('Wait for the agent to finish before deleting this session.')
      return
    }
    if (!r.ok) throw new Error((await r.text()) || r.statusText)
    if (sessionId.value === id) {
      disconnectSessionWs()
      sessionId.value = null
      messages.value = []
      runStatus.value = ''
    }
    await loadSessions()
  } catch (e) {
    showAppToast(e.message || String(e))
  } finally {
    deletingSessionId.value = null
  }
}

const agentBusy = computed(() => runStatus.value === 'running')

async function loadSkills() {
  loadingSkills.value = true
  try {
    const r = await fetch('/api/skills')
    if (!r.ok) throw new Error((await r.text()) || r.statusText)
    skillsList.value = await r.json()
  } catch (e) {
    skillsList.value = []
    showAppToast(e.message || String(e))
  } finally {
    loadingSkills.value = false
  }
}

async function openSkillDetail(id) {
  skillPanelId.value = id
  loadingSkillDetail.value = true
  skillDetail.value = null
  try {
    const r = await fetch(`/api/skills/${encodeURIComponent(id)}`)
    if (!r.ok) throw new Error((await r.text()) || r.statusText)
    skillDetail.value = await r.json()
  } catch (e) {
    showAppToast(e.message || String(e))
  } finally {
    loadingSkillDetail.value = false
  }
}

async function postUserMessage(text) {
  const t = String(text || '').trim()
  if (!t || !sessionId.value || sending.value || agentBusy.value) return false
  sending.value = true
  try {
    const r = await fetch(`/api/sessions/${sessionId.value}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: t }),
    })
    if (r.status === 409) {
      showAppToast('Agent is still working on the previous message.')
      return false
    }
    if (!r.ok) throw new Error((await r.text()) || r.statusText)
    const j = await r.json()
    runStatus.value = j.status || 'running'
    return true
  } catch (e) {
    showAppToast(e.message || String(e))
    return false
  } finally {
    sending.value = false
  }
}

async function sendMessage() {
  const text = draft.value.trim()
  if (!text) return
  if (await postUserMessage(text)) draft.value = ''
}

async function onComposerSkillSelect() {
  const id = composerSkillId.value
  if (!id) return
  try {
    const r = await fetch(`/api/skills/${encodeURIComponent(id)}`)
    if (!r.ok) throw new Error((await r.text()) || r.statusText)
    const j = await r.json()
    const body = j.body != null ? String(j.body) : ''
    if (body.trim()) await postUserMessage(body)
  } catch (e) {
    showAppToast(e.message || String(e))
  } finally {
    composerSkillId.value = ''
  }
}

async function runSessionAnalysis() {
  if (!sessionId.value || analysisBusy.value) return
  analysisBusy.value = true
  try {
    const r = await fetch(`/api/sessions/${sessionId.value}/session-analysis`, {
      method: 'POST',
    })
    if (!r.ok) {
      let detail = (await r.text()) || r.statusText
      try {
        const j = JSON.parse(detail)
        if (typeof j.detail === 'string') detail = j.detail
        else if (Array.isArray(j.detail)) detail = j.detail.map((x) => x.msg || x).join('; ')
      } catch {
        /* keep text */
      }
      throw new Error(detail)
    }
    const j = await r.json()
    analysisResult.value = String(j.markdown || '')
  } catch (e) {
    showAppToast(e.message || String(e))
  } finally {
    analysisBusy.value = false
  }
}

function onComposerKeydown(ev) {
  if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') {
    ev.preventDefault()
    sendMessage()
  }
}

function renderMd(text) {
  if (!text) return ''
  return md.render(text)
}

async function hydrateMermaid(container) {
  await nextTick()
  if (!container) return
  const nodes = [...container.querySelectorAll('.mermaid')].filter((el) => !el.querySelector('svg'))
  if (!nodes.length) return
  try {
    await mermaid.run({ nodes })
  } catch {
    /* invalid diagram source */
  }
}

function formatToolCalls(tc) {
  if (!tc || !tc.length) return ''
  return JSON.stringify(tc, null, 2)
}

async function scrollLog() {
  await nextTick()
  const el = logEl.value
  if (el) el.scrollTop = el.scrollHeight
}

async function scrollAnalysisOutput() {
  await nextTick()
  const el = analysisLogEl.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(messages, scrollLog, { deep: true })
watch(analysisResult, async () => {
  await scrollAnalysisOutput()
  if (mainView.value === 'session_analysis') await hydrateMermaid(analysisLogEl.value)
})

watch(mainView, async (v) => {
  if (v === 'skills') loadSkills()
  if (v === 'workspace' || v === 'session_analysis') finishPanelLayout()
  if (v === 'session_analysis') {
    await scrollAnalysisOutput()
    await hydrateMermaid(analysisLogEl.value)
  }
})

watch(
  sessionId,
  (id, prev) => {
    if (id !== prev) analysisResult.value = ''
    if (id) {
      chatCollapsed.value = false
      previewCollapsed.value = false
      finishPanelLayout()
    }
    connectPreview(id || null)
  },
  { flush: 'sync' },
)

function sendRemoteMouse(event, x, y, button = 0) {
  if (!previewWs || previewWs.readyState !== WebSocket.OPEN) return
  previewWs.send(JSON.stringify({ type: 'mouse', event, x, y, button }))
}

function remoteEventToViewport(ev) {
  const el = ev.currentTarget
  const rect = el.getBoundingClientRect()
  const w = viewportWidth.value
  const h = viewportHeight.value
  if (rect.width <= 0 || rect.height <= 0) return { x: 0, y: 0 }
  let x = ((ev.clientX - rect.left) / rect.width) * w
  let y = ((ev.clientY - rect.top) / rect.height) * h
  x = Math.max(0, Math.min(w, x))
  y = Math.max(0, Math.min(h, y))
  return { x, y }
}

function queueRemoteMouseMove(x, y) {
  if (!remoteMouseEnabled.value) return
  previewMovePending = { x, y }
  if (previewMoveRaf != null) return
  previewMoveRaf = requestAnimationFrame(() => {
    previewMoveRaf = null
    const p = previewMovePending
    previewMovePending = null
    if (p && remoteMouseEnabled.value) sendRemoteMouse('move', p.x, p.y, 0)
  })
}

function onRemotePointerDown(ev) {
  if (!remoteMouseEnabled.value || !viewportWidth.value || !imgSrc.value) return
  ev.currentTarget.setPointerCapture(ev.pointerId)
  const { x, y } = remoteEventToViewport(ev)
  sendRemoteMouse('down', x, y, ev.button)
}

function onRemotePointerUp(ev) {
  if (!remoteMouseEnabled.value || !viewportWidth.value) return
  try {
    ev.currentTarget.releasePointerCapture(ev.pointerId)
  } catch {
    /* already released */
  }
  const { x, y } = remoteEventToViewport(ev)
  sendRemoteMouse('up', x, y, ev.button)
}

function onRemotePointerMove(ev) {
  if (!remoteMouseEnabled.value || !viewportWidth.value) return
  const { x, y } = remoteEventToViewport(ev)
  queueRemoteMouseMove(x, y)
}

watch(remoteMouseEnabled, (on) => {
  if (!on && previewMoveRaf != null) {
    cancelAnimationFrame(previewMoveRaf)
    previewMoveRaf = null
    previewMovePending = null
  }
})

async function loadViewportOptions() {
  try {
    const r = await fetch('/api/browser/viewport')
    if (!r.ok) return
    const j = await r.json()
    const list = j.presets || []
    viewportPresets.value = list
    if (!list.length) return
    const saved = localStorage.getItem(VIEWPORT_LS_KEY)
    const savedOk = saved && list.some((p) => p.id === saved)
    let pick = savedOk ? saved : null
    if (!pick) {
      const c = j.current
      const match = list.find((p) => p.width === c.width && p.height === c.height)
      pick = match ? match.id : list[0].id
    }
    viewportPresetId.value = pick
    const chosen = list.find((p) => p.id === pick)
    const cur = j.current
    if (chosen && (chosen.width !== cur.width || chosen.height !== cur.height)) {
      await applyViewportPreset(false)
    }
  } catch {
    /* ignore */
  }
}

async function onViewportPresetChange() {
  await applyViewportPreset(true)
}

async function applyViewportPreset(saveLs) {
  const id = viewportPresetId.value
  if (!id || viewportApplyBusy.value) return
  viewportApplyBusy.value = true
  try {
    const r = await fetch('/api/browser/viewport', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset_id: id }),
    })
    if (!r.ok) throw new Error((await r.text()) || r.statusText)
    if (saveLs) localStorage.setItem(VIEWPORT_LS_KEY, id)
  } catch {
    /* keep selection; next preview frame may still show old size */
  } finally {
    viewportApplyBusy.value = false
  }
}

onMounted(() => {
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' })
  connectPreview()
  loadSessions()
  loadSkills()
  loadViewportOptions()
  finishPanelLayout()
})
onUnmounted(() => {
  if (previewMoveRaf != null) cancelAnimationFrame(previewMoveRaf)
  if (previewReconnectTimer) clearTimeout(previewReconnectTimer)
  if (previewWs) previewWs.close()
  disconnectSessionWs()
})
</script>

<template>
  <div class="vh-100 d-flex flex-column min-h-0 min-w-0 overflow-hidden p-2">
    <nav
      class="app-top-nav d-flex align-items-center gap-1 flex-shrink-0 border-bottom border-secondary-subtle pb-2 mb-1"
      aria-label="Main navigation"
    >
      <button
        type="button"
        class="btn btn-sm"
        :class="mainView === 'workspace' ? 'btn-secondary' : 'btn-outline-secondary'"
        title="Workspace"
        aria-label="Workspace"
        @click="mainView = 'workspace'"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path
            d="M8.354 1.146a.5.5 0 0 0-.708 0l-6 6A.5.5 0 0 0 1.5 7.5v7a.5.5 0 0 0 .5.5h4.5a.5.5 0 0 0 .5-.5v-4h2v4a.5.5 0 0 0 .5.5H14a.5.5 0 0 0 .5-.5v-7a.5.5 0 0 0-.146-.354l-6-6zM2.5 7.707V14H1V7.5l5-5 5 5V14H9.5V7.707l-3-3-3 3z"
          />
        </svg>
      </button>
      <button
        type="button"
        class="btn btn-sm"
        :class="mainView === 'session_analysis' ? 'btn-secondary' : 'btn-outline-secondary'"
        title="Session analysis"
        aria-label="Session analysis"
        @click="mainView = 'session_analysis'"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path
            fill-rule="evenodd"
            d="M6 3.5A1.5 1.5 0 0 1 7.5 2h1A1.5 1.5 0 0 1 10 3.5v1A1.5 1.5 0 0 1 8.5 6v1H14a.5.5 0 0 1 .5.5v1a.5.5 0 0 1-1 0V8h-5v.5a.5.5 0 0 1-1 0V8h-5v.5a.5.5 0 0 1-1 0v-1A.5.5 0 0 1 2 7h5.5V6A1.5 1.5 0 0 1 6 4.5zM6.5 4a.5.5 0 0 0-.5.5v1a.5.5 0 0 0 .5.5h1a.5.5 0 0 0 .5-.5v-1a.5.5 0 0 0-.5-.5z"
          />
          <path
            d="M11 11a1.5 1.5 0 0 1 1.5-1.5h1A1.5 1.5 0 0 1 15 11v1a1.5 1.5 0 0 1-1.5 1.5h-1A1.5 1.5 0 0 1 11 12z"
          />
        </svg>
      </button>
      <button
        type="button"
        class="btn btn-sm"
        :class="mainView === 'skills' ? 'btn-secondary' : 'btn-outline-secondary'"
        title="Skills"
        aria-label="Skills"
        @click="mainView = 'skills'"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
          <path
            d="M1 2.828c.885-.37 2.154-.769 3.082-1.281C4.915 1.509 5.292 1 6 1h4c.708 0 1.085.509 1.918 1.546.928.512 2.197.911 3.082 1.28l.179.184A1 1 0 0 1 14 4.5V6a1 1 0 0 1-.485.832l-.179.085c-.885.37-2.154.769-3.082 1.281C9.085 7.491 8.708 8 8 8H4c-.708 0-1.085-.509-1.918-1.546-.928-.512-2.197-.911-3.082-1.28l-.179-.184A1 1 0 0 1 2 6V4.5a1 1 0 0 1 .485-.832l.179-.085zM4 2h4c.707 0 1.087.491 1.918 1.546.374.382.868.75 1.4 1.122l.544.338V6H2v-.282l.544-.338c.532-.372 1.026-.74 1.4-1.122C5.913 2.491 6.293 2 7 2H4z"
          />
          <path
            d="M2 7v4.5A1.5 1.5 0 0 0 3.5 13h9a1.5 1.5 0 0 0 1.5-1.5V7H2zm11 4.5a.5.5 0 0 1-.5.5h-9a.5.5 0 0 1-.5-.5V8h10v3.5z"
          />
        </svg>
      </button>
    </nav>
    <div class="layout-fill d-flex flex-row flex-nowrap gap-2">
      <aside class="border-end pe-2 d-flex flex-column min-h-0 flex-shrink-0" style="width: 220px; min-width: 200px">
        <div class="small text-muted mb-2 fw-semibold">Sessions</div>
        <div class="mb-2">
          <input
            v-model="newSessionName"
            type="text"
            class="form-control form-control-sm mb-1"
            placeholder="Name (optional)"
            :disabled="creatingSession"
          />
          <div class="d-flex gap-1 align-items-center mb-1">
            <input
              v-model.number="newMaxSteps"
              type="number"
              min="1"
              max="200"
              class="form-control form-control-sm"
              style="width: 4.5rem"
              title="Max steps per reply"
              :disabled="creatingSession"
            />
            <button
              type="button"
              class="btn btn-primary btn-sm flex-grow-1"
              :disabled="creatingSession"
              @click="createSession"
            >
              {{ creatingSession ? '...' : 'New chat' }}
            </button>
          </div>
        </div>
        <div v-if="loadingSessions" class="small text-muted">Loading...</div>
        <div v-else class="list-group list-group-flush small flex-grow-1 overflow-auto min-h-0">
          <div
            v-for="s in sessions"
            :key="s.id"
            class="list-group-item session-row py-2 px-2"
            :class="{ active: sessionId === s.id }"
          >
            <div class="d-flex align-items-start gap-1">
              <button
                type="button"
                class="session-select text-start btn btn-link text-decoration-none text-body p-0 border-0 flex-grow-1 min-w-0"
                :class="{ 'text-white': sessionId === s.id }"
                @click="openSession(s.id)"
              >
                <div class="d-flex align-items-center gap-2">
                  <span
                    class="session-live-dot flex-shrink-0"
                    :class="{ on: s.has_live_tab }"
                    :title="s.has_live_tab ? 'Live browser tab' : 'No live tab (opens on first browser action)'"
                  />
                  <div class="text-truncate">{{ s.name || s.id.slice(0, 8) }}</div>
                </div>
                <div class="text-muted session-meta" :class="{ 'text-white-50': sessionId === s.id }">
                  {{ s.status }} · {{ s.message_count }} msg
                </div>
              </button>
              <button
                type="button"
                class="btn btn-sm session-delete p-0 flex-shrink-0 text-danger border-0 bg-transparent lh-1"
                title="Delete session"
                :disabled="deletingSessionId === s.id"
                @click.stop="deleteSession(s.id)"
              >
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                  <path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0V6z" />
                  <path
                    d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1v1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118zM2.5 3V2h11v1h-11z"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </aside>

      <div class="layout-fill d-flex flex-column overflow-hidden">
        <template v-if="mainView === 'workspace'">
          <div v-if="runStatus" class="d-flex justify-content-end mb-1 flex-shrink-0">
            <span class="badge text-bg-secondary text-capitalize">{{ runStatus }}</span>
          </div>

          <div
            ref="workspaceBodyEl"
            class="workspace-body-grid overflow-hidden"
            :style="workspaceBodyGridStyle"
          >
            <div v-if="!chatCollapsed" class="workspace-chat">
              <h1 class="h5 mb-2 flex-shrink-0">Chat</h1>
              <p v-if="sessionId" class="small text-muted mb-2 font-monospace text-truncate flex-shrink-0">session: {{ sessionId }}</p>
              <p v-else class="small text-muted flex-shrink-0">Create a chat or pick one from the list.</p>
              <div
                ref="logEl"
                class="chat-messages-scroll mb-2 border rounded-2 bg-body-secondary p-2"
              >
                <div v-if="!messages.length" class="text-secondary small">No messages yet. Type below and send.</div>
                <div
                  v-for="(m, i) in messages"
                  :key="`m-${i}-${m.role}-${m.content?.slice?.(0, 24)}`"
                  class="mb-3 pb-3 border-bottom border-secondary-subtle"
                >
                  <template v-if="m.role === 'user'">
                    <div class="small text-info fw-semibold mb-1">User</div>
                    <div class="session-md" v-html="renderMd(m.content)"></div>
                  </template>
                  <template v-else-if="m.role === 'assistant'">
                    <div class="small text-success fw-semibold mb-1">Assistant</div>
                    <div v-if="m.content" class="session-md" v-html="renderMd(m.content)"></div>
                    <pre v-if="m.tool_calls?.length" class="small bg-dark text-light p-2 rounded mt-2 mb-0 overflow-x-auto">{{ formatToolCalls(m.tool_calls) }}</pre>
                  </template>
                  <template v-else-if="m.role === 'tool'">
                    <div class="small text-warning fw-semibold mb-1">Tool result</div>
                    <pre class="small bg-body-tertiary p-2 rounded mb-0 text-break overflow-auto" style="white-space: pre-wrap">{{ m.content }}</pre>
                  </template>
                  <template v-else>
                    <div class="small text-muted mb-1">{{ m.role }}</div>
                    <pre class="small mb-0">{{ JSON.stringify(m, null, 2) }}</pre>
                  </template>
                </div>
              </div>
              <div class="border rounded p-2 bg-body-tertiary flex-shrink-0">
                <div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-1">
                  <label class="form-label small text-muted mb-0" for="composer-message">Message</label>
                  <div class="d-flex align-items-center gap-1">
                    <label class="form-label small text-muted mb-0 text-nowrap" for="composer-skill">Run skill</label>
                    <select
                      id="composer-skill"
                      v-model="composerSkillId"
                      class="form-select form-select-sm"
                      style="width: auto; min-width: 9rem; max-width: 14rem"
                      :disabled="!sessionId || sending || agentBusy"
                      @change="onComposerSkillSelect"
                    >
                      <option value="">None</option>
                      <option v-for="s in skillsList" :key="s.id" :value="s.id">{{ s.name }}</option>
                    </select>
                  </div>
                </div>
                <textarea
                  id="composer-message"
                  v-model="draft"
                  class="form-control form-control-sm"
                  rows="3"
                  placeholder="Message... (Ctrl+Enter or Cmd+Enter to send)"
                  :disabled="!sessionId || sending || agentBusy"
                  @keydown="onComposerKeydown"
                />
                <div class="d-flex justify-content-between align-items-center mt-2">
                  <span class="small text-muted">Agent run is serialized per session while status is running.</span>
                  <button type="button" class="btn btn-primary btn-sm" :disabled="!sessionId || !draft.trim() || sending || agentBusy" @click="sendMessage">
                    {{ sending ? 'Sending...' : agentBusy ? 'Agent busy...' : 'Send' }}
                  </button>
                </div>
              </div>
            </div>

            <div
              class="split-gutter-wrap flex-shrink-0"
              :title="bothPanelsOpen ? 'Drag to resize chat and preview' : ''"
            >
              <div
                class="split-gutter-drag"
                :class="{ 'split-gutter-drag-disabled': !bothPanelsOpen }"
                @mousedown="onSplitDragMouseDown"
              />
              <div class="split-gutter-fabs">
                <button
                  type="button"
                  class="gutter-fab"
                  :class="{ 'gutter-fab-off': chatCollapsed }"
                  :title="chatCollapsed ? 'Show chat' : 'Hide chat'"
                  aria-label="Toggle chat panel"
                  @click.stop="toggleChatPanel"
                >
                  <svg class="gutter-fab-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                    <path
                      d="M14 1a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H4.414A2 2 0 0 0 3 11.586l-2 2V2a1 1 0 0 1 1-1h12zM2 0a2 2 0 0 0-2 2v12.793a.5.5 0 0 0 .854.353l2.853-2.853A1 1 0 0 1 4.414 12H14a2 2 0 0 0 2-2V2a2 2 0 0 0-2-2H2z"
                    />
                  </svg>
                </button>
                <button
                  type="button"
                  class="gutter-fab"
                  :class="{ 'gutter-fab-off': previewCollapsed }"
                  :title="previewCollapsed ? 'Show preview' : 'Hide preview'"
                  aria-label="Toggle browser preview panel"
                  @click.stop="togglePreviewPanel"
                >
                  <svg class="gutter-fab-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                    <path d="M0 4s0-2 2-2h12s2 0 2 2v6s0 2-2 2H2s-2 0-2-2V4zm1.398-.855a.758.758 0 0 0-.254.302A1.46 1.46 0 0 0 1 4.01V10c0 .325.078.502.145.602.07.105.17.188.365.221.296.05.685-.06 1.09-.218C4.09 9.582 6.195 9 8 9s3.91.582 4.91.865c.405.157.794.267 1.09.22.195-.033.295-.116.365-.221.068-.1.145-.277.145-.602V4.009c0-.124-.019-.245-.055-.352a.76.76 0 0 0-.254-.302C13.925 2.887 11.085 2 8 2c-3.086 0-5.925.887-7.602 1.145z" />
                    <path d="M8 5.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5zM4.5 8a3.5 3.5 0 1 1 7 0 3.5 3.5 0 0 1-7 0z" />
                  </svg>
                </button>
              </div>
            </div>

            <div v-if="!previewCollapsed" class="workspace-preview">
              <header class="preview-toolbar">
                <h2 class="h5 mb-0">Browser preview</h2>
                <div class="preview-toolbar-end">
                  <select
                    v-if="viewportPresets.length"
                    v-model="viewportPresetId"
                    class="form-select form-select-sm"
                    style="width: auto; min-width: 11rem; max-width: 16rem"
                    title="Browser viewport size"
                    :disabled="viewportApplyBusy"
                    @change="onViewportPresetChange"
                  >
                    <option v-for="p in viewportPresets" :key="p.id" :value="p.id">{{ p.label }}</option>
                  </select>
                  <div v-if="imgSrc && viewportWidth" class="form-check form-switch m-0">
                    <input
                      id="remote-mouse"
                      v-model="remoteMouseEnabled"
                      class="form-check-input"
                      type="checkbox"
                      role="switch"
                      :disabled="previewStatus !== 'live'"
                    />
                    <label class="form-check-label small" for="remote-mouse">Remote mouse</label>
                  </div>
                  <span class="badge text-bg-secondary text-capitalize">{{ previewStatus }}</span>
                </div>
              </header>
              <div
                id="preview-scroll-area"
                tabindex="0"
                class="preview-viewport border rounded-2 bg-dark p-2 d-flex align-items-center justify-content-center w-100"
              >
                <div v-if="imgSrc" class="position-relative d-inline-block">
                  <img
                    :src="imgSrc"
                    alt="viewport"
                    class="img-fluid d-block"
                    style="max-width: 100%; height: auto; user-select: none; pointer-events: none"
                  />
                  <div
                    v-show="remoteMouseEnabled && viewportWidth"
                    class="position-absolute top-0 start-0 end-0 bottom-0 remote-mouse-overlay"
                    style="touch-action: none; cursor: crosshair"
                    @pointerdown.prevent="onRemotePointerDown"
                    @pointerup.prevent="onRemotePointerUp"
                    @pointermove.prevent="onRemotePointerMove"
                  />
                </div>
                <div v-else-if="previewPlaceholder" class="text-secondary py-5 px-3 text-center">
                  <p class="mb-2 fw-semibold">No live browser tab yet</p>
                  <p class="small mb-0 text-muted">
                    Preview stays connected to this session. A tab opens when the agent runs a browser action; then video
                    starts automatically.
                  </p>
                </div>
                <p v-else-if="previewTabReady" class="text-secondary mb-0 py-5 text-center">Tab opened — loading preview…</p>
                <p v-else-if="previewStatus === 'no_session'" class="text-secondary mb-0 py-5 text-center">Select a session for preview.</p>
                <p v-else class="text-secondary mb-0 py-5 text-center">Connecting…</p>
              </div>
              <p class="text-muted small mt-2 mb-0 flex-shrink-0 preview-footnote">
                <template v-if="imgSrc && remoteMouseEnabled">Mouse on the image is sent to this session's tab.</template>
                <template v-else-if="imgSrc">Read-only preview unless Remote mouse is on.</template>
                <template v-else-if="sessionId">Preview WebSocket is per session; frames stream once a tab exists.</template>
                <template v-else>Pick a session to attach preview.</template>
              </p>
            </div>
          </div>
        </template>

        <div
          v-else-if="mainView === 'session_analysis'"
          class="session-analysis-page overflow-hidden d-flex flex-column"
        >
          <div v-if="runStatus" class="d-flex justify-content-end mb-1 flex-shrink-0">
            <span class="badge text-bg-secondary text-capitalize">{{ runStatus }}</span>
          </div>
          <div class="session-analysis-body border rounded-2 bg-body-secondary overflow-hidden">
            <div class="session-analysis-body-head px-2 pt-2 pb-0 flex-shrink-0">
              <h2 class="h5 mb-2">Analysis</h2>
              <p v-if="sessionId" class="small text-muted mb-2 font-monospace text-truncate">session: {{ sessionId }}</p>
              <p v-else class="small text-muted mb-2">Create a chat or pick one from the list.</p>
            </div>
            <div
              ref="analysisLogEl"
              class="session-analysis-scroll px-2 pb-2 border-top border-secondary-subtle"
              tabindex="0"
            >
              <div v-if="analysisResult" class="session-md pt-2" v-html="renderMd(analysisResult)"></div>
              <p v-else-if="analysisBusy" class="small text-muted mb-0 pt-2">Analyzing…</p>
              <p v-else-if="sessionId" class="small text-muted mb-0 pt-2">
                Run analysis to show Markdown here. Diagrams: use a fenced mermaid code block.
              </p>
              <p v-else class="small text-muted mb-0 pt-2">Pick a session in the sidebar.</p>
            </div>
            <div class="session-analysis-footer border-top border-secondary-subtle p-2 bg-body-tertiary d-flex justify-content-end flex-shrink-0">
              <button
                type="button"
                class="btn btn-primary btn-sm"
                :disabled="!sessionId || analysisBusy"
                @click="runSessionAnalysis"
              >
                {{ analysisBusy ? 'Analyzing…' : 'Analyze session' }}
              </button>
            </div>
          </div>
        </div>

        <div
          v-else
          class="skills-panel d-flex flex-column overflow-hidden"
        >
          <h1 class="h5 mb-2 flex-shrink-0">Skills</h1>
          <div class="row skills-body-row g-2 g-md-3">
            <div class="col-12 col-md-4 min-h-0 d-flex flex-column">
              <div v-if="loadingSkills" class="small text-muted">Loading...</div>
              <div
                v-else
                class="list-group list-group-flush small overflow-auto flex-grow-1 min-h-0 border rounded"
              >
                <button
                  v-for="s in skillsList"
                  :key="s.id"
                  type="button"
                  class="list-group-item list-group-item-action text-start"
                  :class="{ active: skillPanelId === s.id }"
                  @click="openSkillDetail(s.id)"
                >
                  <div class="fw-semibold">{{ s.name }}</div>
                  <div v-if="s.description" class="text-muted small text-wrap">{{ s.description }}</div>
                </button>
                <div v-if="!skillsList.length" class="p-2 text-muted small">
                  No skills. Add folders under _skills with SKILL.md.
                </div>
              </div>
            </div>
            <div class="col-12 col-md-8 min-h-0 d-flex flex-column">
              <div v-if="loadingSkillDetail" class="small text-muted">Loading...</div>
              <div v-else-if="skillDetail" class="skill-detail-panel">
                <div class="fw-semibold mb-1 flex-shrink-0">{{ skillDetail.name }}</div>
                <div v-if="skillDetail.description" class="small text-muted mb-2 flex-shrink-0">
                  {{ skillDetail.description }}
                </div>
                <div class="skill-detail-md session-md border rounded-2 bg-body-secondary p-2" v-html="renderMd(skillDetail.body)" />
              </div>
              <p v-else class="text-muted small mb-0">Select a skill from the list.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
    <div class="toast-container position-fixed top-0 end-0 p-2 app-toast-stack">
      <div
        v-for="t in toastItems"
        :id="`app-toast-${t.id}`"
        :key="t.id"
        class="toast align-items-center border-0"
        :class="`text-bg-${t.variant || 'warning'}`"
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
      >
        <div class="d-flex">
          <div class="toast-body small">{{ t.message }}</div>
          <button
            type="button"
            class="btn-close btn-close-white me-2 m-auto"
            data-bs-dismiss="toast"
            aria-label="Close"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.layout-fill {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
}
.preview-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
  flex-shrink: 0;
}
.preview-toolbar-end {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  justify-content: flex-end;
}
.workspace-body-grid {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  align-content: stretch;
  box-sizing: border-box;
}
.workspace-body-grid > * {
  min-width: 0;
  min-height: 0;
}
.session-analysis-page {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
}
.skills-panel {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
}
.skills-body-row {
  flex: 1 1 0%;
  min-height: 0;
}
.session-analysis-body {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  align-content: stretch;
}
.skill-detail-panel {
  display: flex;
  flex-direction: column;
  flex: 1 1 0%;
  min-height: 0;
  overflow: hidden;
}
.skill-detail-md {
  flex: 1 1 0%;
  min-height: 0;
  overflow: auto;
}
.preview-viewport {
  flex: 1 1 0%;
  min-height: 0;
  overflow: auto;
}
.session-analysis-scroll {
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.workspace-chat,
.workspace-preview {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.chat-messages-scroll {
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  max-width: 100%;
  overflow-x: hidden;
  overflow-y: auto;
}
.session-md :deep(.mermaid) {
  margin: 0.75rem 0;
  overflow-x: auto;
  text-align: center;
}
.session-md :deep(img) {
  max-width: 100%;
  height: auto;
}
.session-md :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
}
.split-gutter-wrap {
  position: relative;
  width: 4px;
  min-width: 4px;
  flex-shrink: 0;
  align-self: stretch;
  z-index: 2;
}
.split-gutter-drag {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 20px;
  margin-left: -10px;
  cursor: col-resize;
  background: transparent;
  border: 0;
  padding: 0;
  border-radius: 0;
}
.split-gutter-drag::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 2px;
  transform: translateX(-50%);
  background: var(--bs-border-color);
  border-radius: 1px;
  pointer-events: none;
}
.split-gutter-drag:hover:not(.split-gutter-drag-disabled)::after {
  background: var(--bs-secondary-color);
  width: 3px;
}
.split-gutter-drag-disabled {
  cursor: default;
  pointer-events: none;
}
.split-gutter-drag-disabled::after {
  opacity: 0.35;
}
.split-gutter-fabs {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  z-index: 4;
  pointer-events: none;
}
.gutter-fab {
  pointer-events: auto;
  width: 20px;
  height: 20px;
  padding: 0;
  border-radius: 50%;
  border: 1px solid var(--bs-border-color);
  background: var(--bs-body-bg);
  color: var(--bs-secondary-color);
  box-shadow: 0 0 0 1px var(--bs-body-bg), 0 1px 3px rgba(0, 0, 0, 0.12);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.gutter-fab:hover {
  color: var(--bs-body-color);
  border-color: var(--bs-secondary-color);
  background: var(--bs-tertiary-bg);
}
.gutter-fab:focus-visible {
  outline: 2px solid var(--bs-primary);
  outline-offset: 2px;
}
.gutter-fab-off {
  opacity: 0.45;
}
.gutter-fab-icon {
  width: 10px;
  height: 10px;
  display: block;
}
.session-row.active .session-delete {
  color: #f8a4a9;
}
.session-row.active .session-delete:hover {
  color: #fff;
}
.session-meta {
  font-size: 0.65rem;
}
.session-select:focus-visible {
  outline: 2px solid var(--bs-primary);
  outline-offset: 1px;
}
.session-live-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--bs-secondary-bg);
  border: 1px solid var(--bs-border-color);
}
.session-live-dot.on {
  background: #198754;
  border-color: #146c43;
  box-shadow: 0 0 0 1px rgba(25, 135, 84, 0.28);
}
.session-md :deep(p:last-child) {
  margin-bottom: 0;
}
.session-md :deep(pre) {
  max-width: 100%;
  padding: 0.5rem;
  background: var(--bs-tertiary-bg);
  border-radius: 0.25rem;
  overflow-x: auto;
}
.session-md :deep(code) {
  padding: 0.1rem 0.25rem;
  background: var(--bs-tertiary-bg);
  border-radius: 0.2rem;
}
.app-toast-stack {
  z-index: 1080;
}
</style>
