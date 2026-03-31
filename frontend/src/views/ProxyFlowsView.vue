<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import CodeEditor from '../components/CodeEditor.vue'
import { useWorkspaceStore } from '../stores/workspace'
import type { ProxyFlowSummary } from '../types/api'

const workspace = useWorkspaceStore()
const selectedId = ref('')
const activeTab = ref<'request' | 'response'>('request')
const keyword = ref('')
const modeFilter = ref('')

const selectedFlow = computed(() => workspace.proxyFlowDetail)
const filteredFlows = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  return workspace.proxyFlows.filter((flow) => {
    const modeMatch = !modeFilter.value || flow.protocol_mode === modeFilter.value
    if (!modeMatch) return false
    if (!query) return true
    return [flow.method, flow.host, flow.path, flow.url, flow.reason ?? '', flow.error ?? '']
      .join(' ')
      .toLowerCase()
      .includes(query)
  })
})

function protocolText(flow: ProxyFlowSummary) {
  if (flow.is_websocket) return 'WebSocket'
  if (flow.is_sse) return 'SSE'
  if (flow.protocol_mode === 'https-mitm') return 'HTTPS MITM'
  if (flow.protocol_mode === 'tunnel') return '隧道透传'
  if (flow.protocol_mode === 'upgrade') return 'Upgrade'
  return 'HTTP'
}

function summarizeUrl(flow: ProxyFlowSummary) {
  const summary = `${flow.host}${flow.path}`
  return summary.length > 92 ? `${summary.slice(0, 92)}...` : summary
}

function formatDate(value: string) {
  return new Date(value).toLocaleString()
}

function formatBytes(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

async function loadFlows(resetSelection = false) {
  await workspace.loadProxyFlows(300)
  if (resetSelection || !workspace.proxyFlows.some((item) => item.id === selectedId.value)) {
    const first = workspace.proxyFlows[0]
    selectedId.value = first?.id ?? ''
  }
}

async function selectFlow(id: string) {
  selectedId.value = id
  activeTab.value = 'request'
  await workspace.loadProxyFlowDetail(id)
}

watch(
  () => selectedId.value,
  async (id) => {
    if (!id) {
      workspace.proxyFlowDetail = null
      return
    }
    await workspace.loadProxyFlowDetail(id)
  },
)

onMounted(async () => {
  await loadFlows(true)
  if (selectedId.value) {
    await workspace.loadProxyFlowDetail(selectedId.value)
  }
})
</script>

<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h2>代理记录</h2>
        <p>查看自动放行代理捕获到的 HTTP、HTTPS、Upgrade 和隧道流量。</p>
      </div>
      <div class="toolbar">
        <input v-model="keyword" class="input" placeholder="搜索 host / path / URL / 错误" />
        <select v-model="modeFilter" class="input">
          <option value="">全部模式</option>
          <option value="http">HTTP</option>
          <option value="https-mitm">HTTPS MITM</option>
          <option value="tunnel">隧道透传</option>
          <option value="upgrade">Upgrade</option>
          <option value="sse">SSE</option>
        </select>
        <button class="button secondary" @click="loadFlows(false)">刷新</button>
      </div>
    </div>

    <div class="panel-grid history-grid">
      <section class="panel list-panel">
        <div class="panel-title-row">
          <h3>流量列表</h3>
          <span class="muted">共 {{ filteredFlows.length }} 条</span>
        </div>
        <div v-if="!filteredFlows.length" class="empty-state compact-empty">
          <h4>当前没有代理流量</h4>
          <p>先启用本地代理，再让浏览器流量经过 `127.0.0.1:8899`。</p>
        </div>
        <button
          v-for="flow in filteredFlows"
          :key="flow.id"
          class="history-row"
          :class="{ active: flow.id === selectedId }"
          @click="selectFlow(flow.id)"
        >
          <div class="history-row-top">
            <div class="history-row-title">
              <strong>{{ flow.method }}</strong>
              <span class="source-badge">{{ protocolText(flow) }}</span>
            </div>
            <span class="history-row-status">{{ flow.status_code ?? '透传' }}</span>
          </div>
          <div class="history-url">{{ summarizeUrl(flow) }}</div>
          <div class="history-row-meta">
            <span>{{ formatBytes(flow.response_body_size) }}</span>
            <span>{{ formatDate(flow.created_at) }}</span>
          </div>
        </button>
      </section>

      <section class="panel detail-panel">
        <template v-if="selectedFlow">
          <div class="panel-title-row">
            <div class="request-summary">
              <div class="request-chip-row">
                <span class="method-chip">{{ selectedFlow.method }}</span>
                <span class="request-title-url">{{ selectedFlow.url }}</span>
              </div>
              <p class="muted request-status">
                {{ protocolText(selectedFlow) }}
                · {{ selectedFlow.status_code ?? '透传中' }}
                {{ selectedFlow.reason ?? selectedFlow.error ?? '' }}
              </p>
            </div>
          </div>

          <div class="detail-summary-card">
            <div class="detail-summary-grid">
              <div>
                <span class="summary-label">主机</span>
                <strong>{{ selectedFlow.host }}</strong>
              </div>
              <div>
                <span class="summary-label">客户端协议</span>
                <strong>{{ selectedFlow.client_http_version }}</strong>
              </div>
              <div>
                <span class="summary-label">上游协议</span>
                <strong>{{ selectedFlow.upstream_http_version ?? '透传' }}</strong>
              </div>
              <div>
                <span class="summary-label">时间</span>
                <strong>{{ formatDate(selectedFlow.created_at) }}</strong>
              </div>
            </div>
          </div>

          <div class="proxy-badge-row">
            <span class="source-badge" v-if="selectedFlow.is_tls_mitm">已解密</span>
            <span class="source-badge" v-if="selectedFlow.is_passthrough">透传</span>
            <span class="source-badge" v-if="selectedFlow.is_websocket">WebSocket</span>
            <span class="source-badge" v-if="selectedFlow.is_sse">SSE</span>
            <span class="source-badge">请求 {{ formatBytes(selectedFlow.request_body_size) }}</span>
            <span class="source-badge">响应 {{ formatBytes(selectedFlow.response_body_size) }}</span>
          </div>

          <div class="detail-tabs">
            <button
              class="tab-button"
              :class="{ active: activeTab === 'request' }"
              @click="activeTab = 'request'"
            >
              原始请求
            </button>
            <button
              class="tab-button"
              :class="{ active: activeTab === 'response' }"
              @click="activeTab = 'response'"
            >
              原始响应
            </button>
          </div>

          <div v-if="activeTab === 'request'">
            <CodeEditor :model-value="selectedFlow.raw_request" read-only mode="http" />
          </div>
          <div v-else>
            <CodeEditor :model-value="selectedFlow.raw_response || '<no response body captured>'" read-only mode="http" />
          </div>
        </template>
        <div v-else class="empty-state">
          <h3>请选择一条代理记录</h3>
          <p>这里会显示原始请求、原始响应和协议模式信息。</p>
        </div>
      </section>
    </div>
  </section>
</template>
