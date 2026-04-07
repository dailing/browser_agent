<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

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
const sendError = ref('')

const logEl = ref(null)
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

const MIN_CHAT_W = 220
const MIN_PREVIEW_W = 200
const SPLIT_COLLAPSE_PX = 96
const GUTTER_W = 8

function readInitialSplitPct() {
  const n = Number(typeof localStorage !== 'undefined' ? localStorage.getItem(SPLIT_PCT_LS_KEY) : NaN)
  if (Number.isFinite(n) && n >= 22 && n <= 78) return n
  return 52
}
const splitPct = ref(readInitialSplitPct())
const workspaceBodyEl = ref(null)
const chatPanelEl = ref(null)
const previewPanelEl = ref(null)

const chatCollapsed = ref(false)
const previewCollapsed = ref(false)

let workspaceResizeObserver = null

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

function onSplitMouseDown(ev) {
  ev.preventDefault()
  const container = workspaceBodyEl.value
  if (!container || chatCollapsed.value || previewCollapsed.value) return
  const rect = container.getBoundingClientRect()
  const total = rect.width || 1
  const startX = ev.clientX
  const startPct = splitPct.value

  function onMove(e) {
    const dx = e.clientX - startX
    const next = startPct + (dx / total) * 100
    splitPct.value = Math.max(0.5, Math.min(99.5, next))
  }
  function onUp() {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    const w = container.getBoundingClientRect().width
    const cw = chatPanelEl.value?.getBoundingClientRect().width ?? 0
    const pw = previewPanelEl.value?.getBoundingClientRect().width ?? 0
    if (cw < SPLIT_COLLAPSE_PX) {
      chatCollapsed.value = true
    } else if (pw < SPLIT_COLLAPSE_PX) {
      previewCollapsed.value = true
    } else {
      splitPct.value = clampSplitPctForWidth(splitPct.value, w)
    }
    persistSplitPct()
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

const bothPanelsOpen = computed(() => !chatCollapsed.value && !previewCollapsed.value)

const chatPanelStyle = computed(() => {
  if (bothPanelsOpen.value) {
    return { flex: `0 0 ${splitPct.value}%`, minWidth: 0 }
  }
  if (!chatCollapsed.value) return { flex: '1 1 0%', minWidth: `${MIN_CHAT_W}px` }
  return {}
})

const previewPanelStyle = computed(() => {
  if (bothPanelsOpen.value) {
    return { flex: '1 1 0%', minWidth: 0 }
  }
  if (!previewCollapsed.value) return { flex: '1 1 0%', minWidth: `${MIN_PREVIEW_W}px` }
  return {}
})

function expandPreview() {
  const el = workspaceBodyEl.value
  const W = el?.getBoundingClientRect().width ?? 0
  const needBoth = MIN_CHAT_W + MIN_PREVIEW_W + GUTTER_W
  if (W > 0 && W < needBoth) {
    chatCollapsed.value = true
  } else if (W >= needBoth) {
    chatCollapsed.value = false
  }
  previewCollapsed.value = false
  nextTick(() => {
    const root = workspaceBodyEl.value
    if (!root) return
    const w = root.getBoundingClientRect().width
    if (w <= 0) return
    splitPct.value = clampSplitPctForWidth(splitPct.value, w)
    syncPanelsToWorkspaceSize()
  })
}

function expandChat() {
  const el = workspaceBodyEl.value
  const W = el?.getBoundingClientRect().width ?? 0
  const needBoth = MIN_CHAT_W + MIN_PREVIEW_W + GUTTER_W
  if (W > 0 && W < needBoth) {
    previewCollapsed.value = true
  } else if (W >= needBoth) {
    previewCollapsed.value = false
  }
  chatCollapsed.value = false
  nextTick(() => {
    const root = workspaceBodyEl.value
    if (!root) return
    const w = root.getBoundingClientRect().width
    if (w <= 0) return
    splitPct.value = clampSplitPctForWidth(splitPct.value, w)
    syncPanelsToWorkspaceSize()
  })
}

function syncPanelsToWorkspaceSize() {
  const el = workspaceBodyEl.value
  if (!el) return
  const W = el.getBoundingClientRect().width
  if (W <= 0) return

  const needBoth = MIN_CHAT_W + MIN_PREVIEW_W + GUTTER_W
  const peek = 14

  if (chatCollapsed.value && previewCollapsed.value) {
    if (W >= needBoth) {
      chatCollapsed.value = false
      previewCollapsed.value = false
      splitPct.value = clampSplitPctForWidth(splitPct.value, W)
    } else if (W >= MIN_CHAT_W + peek) {
      chatCollapsed.value = false
    } else if (W >= MIN_PREVIEW_W + peek) {
      previewCollapsed.value = false
    }
    return
  }

  if (!chatCollapsed.value && previewCollapsed.value && W >= needBoth) {
    previewCollapsed.value = false
    splitPct.value = clampSplitPctForWidth(splitPct.value, W)
    return
  }
  if (chatCollapsed.value && !previewCollapsed.value && W >= needBoth) {
    chatCollapsed.value = false
    splitPct.value = clampSplitPctForWidth(splitPct.value, W)
    return
  }

  if (!chatCollapsed.value && !previewCollapsed.value) {
    const cw = chatPanelEl.value?.getBoundingClientRect().width ?? 0
    const pw = previewPanelEl.value?.getBoundingClientRect().width ?? 0
    if (W < needBoth) {
      previewCollapsed.value = true
      return
    }
    if (pw < MIN_PREVIEW_W - 0.5) {
      previewCollapsed.value = true
      return
    }
    if (cw < MIN_CHAT_W - 0.5) {
      chatCollapsed.value = true
      return
    }
    splitPct.value = clampSplitPctForWidth(splitPct.value, W)
    return
  }

  if (!chatCollapsed.value && previewCollapsed.value && W < MIN_CHAT_W + peek) {
    chatCollapsed.value = true
    return
  }
  if (!previewCollapsed.value && chatCollapsed.value && W < MIN_PREVIEW_W + peek) {
    previewCollapsed.value = true
  }
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
  sendError.value = ''
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
    sendError.value = e.message || String(e)
  } finally {
    creatingSession.value = false
  }
}

async function openSession(id) {
  if (sessionId.value === id) return
  sendError.value = ''
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
    sendError.value = e.message || String(e)
  }
  connectSessionWs(id)
}

async function deleteSession(id) {
  if (deletingSessionId.value) return
  deletingSessionId.value = id
  sendError.value = ''
  try {
    const r = await fetch(`/api/sessions/${id}`, { method: 'DELETE' })
    if (r.status === 409) {
      sendError.value = 'Wait for the agent to finish before deleting this session.'
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
    sendError.value = e.message || String(e)
  } finally {
    deletingSessionId.value = null
  }
}

const agentBusy = computed(() => runStatus.value === 'running')

async function sendMessage() {
  const text = draft.value.trim()
  if (!text || !sessionId.value || sending.value || agentBusy.value) return
  sending.value = true
  sendError.value = ''
  try {
    const r = await fetch(`/api/sessions/${sessionId.value}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    if (r.status === 409) {
      sendError.value = 'Agent is still working on the previous message.'
      return
    }
    if (!r.ok) throw new Error((await r.text()) || r.statusText)
    const j = await r.json()
    runStatus.value = j.status || 'running'
    draft.value = ''
  } catch (e) {
    sendError.value = e.message || String(e)
  } finally {
    sending.value = false
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

function formatToolCalls(tc) {
  if (!tc || !tc.length) return ''
  return JSON.stringify(tc, null, 2)
}

async function scrollLog() {
  await nextTick()
  const el = logEl.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(messages, scrollLog, { deep: true })

watch(
  sessionId,
  (id) => {
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
  connectPreview()
  loadSessions()
  loadViewportOptions()
  nextTick(() => {
    const root = workspaceBodyEl.value
    if (!root) {
      syncPanelsToWorkspaceSize()
      return
    }
    if (typeof ResizeObserver !== 'undefined') {
      workspaceResizeObserver = new ResizeObserver(() => {
        syncPanelsToWorkspaceSize()
      })
      workspaceResizeObserver.observe(root)
    }
    syncPanelsToWorkspaceSize()
  })
})
onUnmounted(() => {
  if (workspaceResizeObserver) {
    workspaceResizeObserver.disconnect()
    workspaceResizeObserver = null
  }
  if (previewMoveRaf != null) cancelAnimationFrame(previewMoveRaf)
  if (previewReconnectTimer) clearTimeout(previewReconnectTimer)
  if (previewWs) previewWs.close()
  disconnectSessionWs()
})
</script>

<template>
  <div class="app-shell">
    <div class="row g-2 flex-nowrap main-row">
      <div class="col-auto border-end pe-2 sidebar-col d-flex flex-column" style="width: 220px; min-width: 200px">
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
        <div v-else class="list-group list-group-flush small session-list">
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
      </div>

      <div class="col d-flex flex-column workspace-root" style="min-width: 0">
        <div class="d-flex align-items-center justify-content-end mb-1 flex-wrap gap-2 flex-shrink-0">
          <span v-if="runStatus" class="badge text-bg-secondary text-capitalize">{{ runStatus }}</span>
        </div>

        <div
          ref="workspaceBodyEl"
          class="workspace-body d-flex flex-row flex-grow-1 align-items-stretch"
          :class="{ 'is-split': bothPanelsOpen }"
        >
          <div
            v-show="!chatCollapsed"
            ref="chatPanelEl"
            class="d-flex flex-column panel-chat min-h-0"
            :style="chatPanelStyle"
          >
            <div class="d-flex align-items-center justify-content-between mb-2 flex-wrap gap-2 flex-shrink-0">
              <h1 class="h5 mb-0">Chat</h1>
            </div>
            <p v-if="sessionId" class="small text-muted mb-2 font-monospace text-truncate flex-shrink-0">session: {{ sessionId }}</p>
            <p v-else class="small text-muted flex-shrink-0">Create a chat or pick one from the list.</p>
            <div v-if="sendError" class="alert alert-warning py-1 px-2 small mb-2 flex-shrink-0">{{ sendError }}</div>
            <div
              ref="logEl"
              class="border rounded flex-grow-1 overflow-auto bg-body-secondary p-2 mb-2 chat-log min-h-0"
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
                  <pre class="small bg-body-tertiary p-2 rounded mb-0 text-break" style="white-space: pre-wrap; max-height: 240px; overflow: auto">{{ m.content }}</pre>
                </template>
                <template v-else>
                  <div class="small text-muted mb-1">{{ m.role }}</div>
                  <pre class="small mb-0">{{ JSON.stringify(m, null, 2) }}</pre>
                </template>
              </div>
            </div>
            <div class="border rounded p-2 bg-body-tertiary flex-shrink-0">
              <label class="form-label small text-muted mb-1">Message</label>
              <textarea
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
            v-show="bothPanelsOpen"
            class="split-gutter flex-shrink-0"
            title="Drag to resize chat and preview"
            @mousedown.prevent="onSplitMouseDown"
          />

          <button
            v-if="previewCollapsed && !chatCollapsed"
            type="button"
            class="peek-btn peek-edge-right flex-shrink-0"
            title="Show browser preview"
            @click="expandPreview"
          >
            Preview
          </button>

          <button
            v-if="chatCollapsed && !previewCollapsed"
            type="button"
            class="peek-btn peek-edge-left flex-shrink-0"
            title="Show chat"
            @click="expandChat"
          >
            Chat
          </button>

          <div v-if="chatCollapsed && previewCollapsed" class="d-flex flex-row flex-shrink-0 align-items-stretch">
            <button
              type="button"
              class="peek-btn peek-edge-right flex-shrink-0"
              title="Show chat"
              @click="expandChat"
            >
              Chat
            </button>
            <button
              type="button"
              class="peek-btn peek-edge-left flex-shrink-0 border-start-0"
              title="Show browser preview"
              @click="expandPreview"
            >
              Preview
            </button>
          </div>

          <div
            v-show="!previewCollapsed"
            ref="previewPanelEl"
            class="d-flex flex-column panel-preview preview-col min-h-0"
            :style="previewPanelStyle"
          >
            <div class="d-flex align-items-center justify-content-between mb-2 flex-wrap gap-2 flex-shrink-0">
              <h2 class="h5 mb-0">Browser preview</h2>
              <div class="d-flex align-items-center gap-2 flex-wrap justify-content-end">
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
            </div>
            <div
              class="border rounded overflow-auto bg-dark p-2 text-center flex-grow-1 d-flex align-items-start justify-content-center preview-viewport-box min-h-0"
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
              <div v-else-if="previewPlaceholder" class="text-secondary py-5 px-3">
                <p class="mb-2 fw-semibold">No live browser tab yet</p>
                <p class="small mb-0 text-muted">
                  Preview stays connected to this session. A tab opens when the agent runs a browser action; then video
                  starts automatically.
                </p>
              </div>
              <p v-else-if="previewTabReady" class="text-secondary mb-0 py-5">Tab opened — loading preview…</p>
              <p v-else-if="previewStatus === 'no_session'" class="text-secondary mb-0 py-5">Select a session for preview.</p>
              <p v-else class="text-secondary mb-0 py-5">Connecting…</p>
            </div>
            <p class="text-muted small mt-2 mb-0 flex-shrink-0 preview-footnote">
              <template v-if="imgSrc && remoteMouseEnabled">Mouse on the image is sent to this session's tab.</template>
              <template v-else-if="imgSrc">Read-only preview unless Remote mouse is on.</template>
              <template v-else-if="sessionId">Preview WebSocket is per session; frames stream once a tab exists.</template>
              <template v-else>Pick a session to attach preview.</template>
            </p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  box-sizing: border-box;
  flex: 1 1 auto;
  min-height: 0;
  padding: 0.75rem;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.main-row {
  flex: 1 1 auto;
  min-height: 0;
  align-items: stretch;
  overflow: hidden;
}
.sidebar-col {
  min-height: 0;
}
.workspace-root {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.workspace-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.workspace-body.is-split .panel-chat,
.workspace-body.is-split .panel-preview {
  min-height: 0;
}
.workspace-body.is-split .preview-viewport-box {
  min-height: 0;
}
.panel-chat,
.panel-preview {
  min-width: 0;
  overflow: hidden;
}
.min-h-0 {
  min-height: 0;
}
.split-gutter {
  width: 6px;
  margin: 0 1px;
  cursor: col-resize;
  background: var(--bs-border-color);
  border-radius: 2px;
  align-self: stretch;
  flex-shrink: 0;
}
.split-gutter:hover {
  background: var(--bs-secondary-color);
}
.peek-btn {
  width: 14px;
  min-width: 14px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: var(--bs-secondary-bg);
  color: var(--bs-secondary-color);
  font-size: 0.62rem;
  line-height: 1.2;
  writing-mode: vertical-rl;
  text-orientation: mixed;
  letter-spacing: 0.04em;
  cursor: pointer;
  align-self: stretch;
}
.peek-btn:hover {
  background: var(--bs-tertiary-bg);
  color: var(--bs-body-color);
}
.peek-edge-right {
  border-left: 1px solid var(--bs-border-color);
}
.peek-edge-left {
  border-right: 1px solid var(--bs-border-color);
}
.chat-log {
  max-height: none;
}
.session-list {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
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
.preview-viewport-box {
  max-height: none;
}
.preview-col {
  max-height: none;
}
.preview-footnote {
  max-height: 4.5rem;
  overflow-y: auto;
}
</style>
