<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import CodeEditor from '../components/CodeEditor.vue'
import { useWorkspaceStore } from '../stores/workspace'

const router = useRouter()
const workspace = useWorkspaceStore()
const sourceFilter = ref('')
const selectedId = ref('')
const activeTab = ref<'request' | 'response'>('request')

const sourceTextMap: Record<string, string> = {
  ui: '页面',
  api: '接口',
  cli: '命令行',
  mcp: 'MCP',
  proxy: '代理',
}

const selectedItem = computed(() => workspace.history.find((item) => item.id === selectedId.value) ?? null)

async function loadHistory(resetSelection = false) {
  await workspace.loadHistory(sourceFilter.value || undefined)
  if (resetSelection || !workspace.history.some((item) => item.id === selectedId.value)) {
    selectedId.value = ''
    activeTab.value = 'request'
  }
}

function selectHistoryItem(id: string) {
  selectedId.value = id
  activeTab.value = 'request'
}

function formatSource(source: string) {
  return sourceTextMap[source] ?? source
}

function formatDate(value: string) {
  return new Date(value).toLocaleString()
}

function summarizeUrl(rawUrl: string) {
  try {
    const url = new URL(rawUrl)
    const summary = `${url.host}${url.pathname}${url.search}`
    return summary.length > 96 ? `${summary.slice(0, 96)}...` : summary
  } catch {
    return rawUrl.length > 96 ? `${rawUrl.slice(0, 96)}...` : rawUrl
  }
}

async function applyFilter() {
  await loadHistory(true)
}

async function sendToRepeater() {
  if (!selectedItem.value) return
  workspace.loadIntoRepeater(selectedItem.value)
  await router.push('/repeater')
}

async function removeCurrentItem() {
  if (!selectedItem.value) return
  const currentId = selectedItem.value.id
  const currentIndex = workspace.history.findIndex((item) => item.id === currentId)
  const nextId =
    workspace.history[currentIndex + 1]?.id ?? workspace.history[currentIndex - 1]?.id ?? ''

  const confirmed = window.confirm('确定删除这条历史记录吗？')
  if (!confirmed) return

  await workspace.deleteHistoryItem(currentId)
  await loadHistory(false)
  selectedId.value = workspace.history.some((item) => item.id === nextId) ? nextId : ''
  activeTab.value = 'request'
}

async function clearCurrentHistory() {
  if (!workspace.history.length) return
  const label = sourceFilter.value ? `当前筛选来源“${formatSource(sourceFilter.value)}”` : '全部历史记录'
  const confirmed = window.confirm(`确定清空${label}吗？`)
  if (!confirmed) return

  await workspace.clearHistory(sourceFilter.value || undefined)
  await loadHistory(true)
}

watch(sourceFilter, () => {
  void applyFilter()
})

onMounted(() => {
  void loadHistory(true)
})
</script>

<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h2>历史记录</h2>
        <p>查看代理抓包、接口调用、命令行执行和页面重放留下的请求记录。</p>
      </div>
      <div class="toolbar">
        <select v-model="sourceFilter" class="input">
          <option value="">全部来源</option>
          <option value="ui">页面</option>
          <option value="api">接口</option>
          <option value="cli">命令行</option>
          <option value="mcp">MCP</option>
          <option value="proxy">代理</option>
        </select>
        <button class="button secondary" @click="loadHistory(false)">刷新</button>
        <button class="button danger-secondary" :disabled="!workspace.history.length" @click="clearCurrentHistory">
          清空当前列表
        </button>
      </div>
    </div>

    <div class="panel-grid history-grid">
      <section class="panel list-panel">
        <div class="panel-title-row">
          <h3>请求列表</h3>
          <span class="muted">共 {{ workspace.history.length }} 条</span>
        </div>
        <div v-if="!workspace.history.length" class="empty-state compact-empty">
          <h4>当前没有历史记录</h4>
          <p>你可以先去重放台发送请求，或者开启本地代理进行抓包。</p>
        </div>
        <button
          v-for="item in workspace.history"
          :key="item.id"
          class="history-row"
          :class="{ active: item.id === selectedItem?.id }"
          @click="selectHistoryItem(item.id)"
        >
          <div class="history-row-top">
            <div class="history-row-title">
              <strong>{{ item.request.method }}</strong>
              <span class="source-badge">{{ formatSource(item.source) }}</span>
            </div>
            <span class="history-row-status">{{ item.result.status_code ?? '失败' }}</span>
          </div>
          <div class="history-url">{{ summarizeUrl(item.request.url) }}</div>
          <div class="history-row-meta">
            <span>{{ item.result.elapsed_ms ?? 0 }} ms</span>
            <span>{{ formatDate(item.created_at) }}</span>
          </div>
        </button>
      </section>

      <section class="panel detail-panel">
        <template v-if="selectedItem">
          <div class="panel-title-row">
            <div class="request-summary">
              <div class="request-chip-row">
                <span class="method-chip">{{ selectedItem.request.method }}</span>
                <span class="request-title-url">{{ selectedItem.request.url }}</span>
              </div>
              <p class="muted request-status">
                {{ selectedItem.result.status_code ?? '失败' }}
                {{ selectedItem.result.reason ?? selectedItem.result.error ?? '' }}
              </p>
            </div>
            <div class="toolbar detail-actions">
              <button class="button secondary" @click="sendToRepeater">发送到重放台</button>
              <button class="button danger-secondary" @click="removeCurrentItem">删除当前记录</button>
            </div>
          </div>

          <div class="detail-summary-card">
            <div class="detail-summary-grid">
              <div>
                <span class="summary-label">来源</span>
                <strong>{{ formatSource(selectedItem.source) }}</strong>
              </div>
              <div>
                <span class="summary-label">状态</span>
                <strong>{{ selectedItem.result.status_code ?? '失败' }}</strong>
              </div>
              <div>
                <span class="summary-label">耗时</span>
                <strong>{{ selectedItem.result.elapsed_ms ?? 0 }} ms</strong>
              </div>
              <div>
                <span class="summary-label">时间</span>
                <strong>{{ formatDate(selectedItem.created_at) }}</strong>
              </div>
            </div>
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
            <CodeEditor :model-value="selectedItem.result.raw_request" read-only mode="http" />
          </div>
          <div v-else>
            <CodeEditor :model-value="selectedItem.result.raw_response" read-only mode="http" />
          </div>
        </template>
        <div v-else class="empty-state">
          <h3>请选择一条记录查看详情</h3>
          <p>左侧列表只展示摘要信息，点击后会在这里显示原始请求、原始响应和快捷操作。</p>
        </div>
      </section>
    </div>
  </section>
</template>
