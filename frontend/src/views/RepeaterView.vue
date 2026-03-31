<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import CodeEditor from '../components/CodeEditor.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const entryName = ref('重放请求')
const selectedCollectionId = ref('')
const newCollectionName = ref('')
const parseMessage = ref('把原始 HTTP 报文拆成结构化字段，便于快速检查方法、地址、请求头和请求体。')
let parseTimer: ReturnType<typeof setTimeout> | null = null

const parsedPreview = computed(() =>
  workspace.repeaterParsedRequest
    ? JSON.stringify(workspace.repeaterParsedRequest, null, 2)
    : '这里会显示解析后的请求结构。\n\n建议直接粘贴完整原始 HTTP 报文。',
)

async function parseRequest(silent = false) {
  try {
    await workspace.parseRepeaterRequest()
    parseMessage.value = '解析结果仅用于核对结构，不会替代你提交的原始报文。'
  } catch (error) {
    workspace.repeaterParsedRequest = null
    if (!silent) {
      parseMessage.value = error instanceof Error ? error.message : '请求解析失败。'
    }
  }
}

async function executeRequest() {
  await workspace.executeRepeater()
}

async function saveToCollection() {
  await workspace.appendRequestToCollection({
    collectionId: selectedCollectionId.value || undefined,
    newCollectionName: newCollectionName.value || undefined,
    entryName: entryName.value,
  })
  newCollectionName.value = ''
}

onMounted(async () => {
  await workspace.loadCollections()
  await parseRequest(true)
})

onBeforeUnmount(() => {
  if (parseTimer) {
    clearTimeout(parseTimer)
  }
})

watch(
  () => workspace.repeaterRawRequest,
  () => {
    if (parseTimer) {
      clearTimeout(parseTimer)
    }
    parseTimer = setTimeout(() => {
      void parseRequest(true)
    }, 250)
  },
)
</script>

<template>
  <section class="page">
    <div class="page-header">
      <div>
        <span class="page-kicker">REPLAY</span>
        <h2>请求重放</h2>
        <p>直接编辑原始报文，核对解析结构，然后发起一次真实请求。</p>
      </div>
      <div class="toolbar">
        <button class="button secondary" @click="parseRequest()">重新解析</button>
        <button class="button" :disabled="workspace.loading" @click="executeRequest">
          {{ workspace.loading ? '发送中...' : '发送请求' }}
        </button>
      </div>
    </div>

    <div class="panel-grid repeater-grid">
      <section class="panel">
        <div class="panel-title-row">
          <h3>原始报文</h3>
          <span class="muted">完整 HTTP 请求原文</span>
        </div>
        <CodeEditor v-model="workspace.repeaterRawRequest" mode="http" />
      </section>

      <section class="panel">
        <div class="panel-title-row">
          <h3>解析预览</h3>
          <span class="muted">字段级核对视图</span>
        </div>
        <p class="muted panel-helper">{{ parseMessage }}</p>
        <CodeEditor :model-value="parsedPreview" mode="json" read-only />
      </section>
    </div>

    <div class="panel-grid single-grid">
      <section class="panel">
        <div class="panel-title-row">
          <h3>保存到集合</h3>
          <span class="muted">加入现有集合，或顺手新建一个</span>
        </div>
        <div class="form-grid">
          <label>
            <span>条目名称</span>
            <input v-model="entryName" class="input" />
          </label>
          <label>
            <span>已有集合</span>
            <select v-model="selectedCollectionId" class="input">
              <option value="">不选则新建</option>
              <option v-for="item in workspace.collections" :key="item.id" :value="item.id">
                {{ item.name }}
              </option>
            </select>
          </label>
          <label>
            <span>新集合名称</span>
            <input v-model="newCollectionName" class="input" placeholder="未选择已有集合时使用" />
          </label>
        </div>
        <button class="button secondary" @click="saveToCollection">保存请求</button>
      </section>
    </div>

    <section class="panel" v-if="workspace.lastReplay">
      <div class="panel-title-row">
        <div>
          <h3>重放结果</h3>
          <p class="muted">
            {{ workspace.lastReplay.result.status_code ?? '错误' }}
            {{ workspace.lastReplay.result.reason ?? workspace.lastReplay.result.error ?? '' }}
          </p>
        </div>
        <span class="muted">{{ workspace.lastReplay.result.elapsed_ms ?? 0 }} ms</span>
      </div>
      <CodeEditor :model-value="workspace.lastReplay.result.raw_response" read-only mode="http" />
    </section>

    <p v-if="workspace.error" class="error-banner">{{ workspace.error }}</p>
  </section>
</template>
