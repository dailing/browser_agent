<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

const goal = ref('')
const maxSteps = ref(40)
const busy = ref(false)
const sessionId = ref(null)
const messages = ref([])
const runStatus = ref('')
const logEl = ref(null)

const imgSrc = ref('')
const previewStatus = ref('connecting')
let previewWs = null
let previewReconnectTimer = null
let sessionWs = null

function connectPreview() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${proto}//${location.host}/ws/preview`
  previewWs = new WebSocket(url)
  previewWs.onopen = () => {
    previewStatus.value = 'live'
  }
  previewWs.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg.type === 'preview' && msg.mime === 'image/jpeg' && msg.data) {
        imgSrc.value = `data:${msg.mime};base64,${msg.data}`
      }
    } catch {
      /* ignore */
    }
  }
  previewWs.onerror = () => {
    previewStatus.value = 'error'
  }
  previewWs.onclose = () => {
    previewStatus.value = 'reconnecting'
    previewReconnectTimer = setTimeout(connectPreview, 1500)
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
      } else if (msg.type === 'message') {
        messages.value = [...messages.value, msg.message]
      } else if (msg.type === 'status') {
        runStatus.value = msg.status || ''
      }
    } catch {
      /* ignore */
    }
  }
  sessionWs.onerror = () => {}
}

async function startRun() {
  const g = goal.value.trim()
  if (!g || busy.value) return
  busy.value = true
  disconnectSessionWs()
  try {
    const r = await fetch('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal: g, max_steps: Number(maxSteps.value) || 40 }),
    })
    if (!r.ok) {
      const t = await r.text()
      throw new Error(t || r.statusText)
    }
    const j = await r.json()
    sessionId.value = j.session_id
    messages.value = []
    runStatus.value = j.status || 'running'
    connectSessionWs(j.session_id)
  } catch (e) {
    runStatus.value = 'error'
    messages.value = [{ role: 'assistant', content: `_Request failed: ${e.message}_` }]
  } finally {
    busy.value = false
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

onMounted(() => {
  connectPreview()
})
onUnmounted(() => {
  if (previewReconnectTimer) clearTimeout(previewReconnectTimer)
  if (previewWs) previewWs.close()
  disconnectSessionWs()
})
</script>

<template>
  <div class="container-fluid py-3">
    <div class="row g-3">
      <div class="col-lg-5 d-flex flex-column" style="min-height: 70vh">
        <div class="d-flex align-items-center justify-content-between mb-2 flex-wrap gap-2">
          <h1 class="h5 mb-0">Session</h1>
          <span v-if="runStatus" class="badge text-bg-secondary text-capitalize">{{ runStatus }}</span>
        </div>
        <div class="mb-2">
          <label class="form-label small text-muted mb-1">Goal</label>
          <textarea v-model="goal" class="form-control form-control-sm" rows="2" placeholder="Describe the browser task..." :disabled="busy"></textarea>
        </div>
        <div class="d-flex align-items-end gap-2 mb-2">
          <div>
            <label class="form-label small text-muted mb-1">Max steps</label>
            <input v-model.number="maxSteps" type="number" min="1" max="200" class="form-control form-control-sm" style="width: 5rem" :disabled="busy" />
          </div>
          <button type="button" class="btn btn-primary btn-sm mt-4" :disabled="busy || !goal.trim()" @click="startRun">
            Run agent
          </button>
        </div>
        <p v-if="sessionId" class="small text-muted mb-2 font-monospace">session: {{ sessionId }}</p>
        <div ref="logEl" class="border rounded flex-grow-1 overflow-auto bg-body-secondary p-2" style="max-height: 68vh">
          <div v-if="!messages.length" class="text-secondary small">No messages yet. Enter a goal and run.</div>
          <div v-for="(m, i) in messages" :key="i" class="mb-3 pb-3 border-bottom border-secondary-subtle">
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
      </div>
      <div class="col-lg-7">
        <div class="d-flex align-items-center justify-content-between mb-2">
          <h2 class="h5 mb-0">Browser preview</h2>
          <span class="badge text-bg-secondary text-capitalize">{{ previewStatus }}</span>
        </div>
        <div class="border rounded overflow-hidden bg-dark p-2 text-center" style="min-height: 240px">
          <img v-if="imgSrc" :src="imgSrc" alt="viewport" class="img-fluid" style="zoom: 0.85; max-width: 100%" />
          <p v-else class="text-secondary mb-0 py-5">Waiting for frames...</p>
        </div>
        <p class="text-muted small mt-2 mb-0">Read-only preview. Agent controls the browser via the backend only.</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
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
</style>
