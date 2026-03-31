<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import CodeEditor from '../components/CodeEditor.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const selectedCollectionId = ref('')
const concurrency = ref(1)

const selectedCollection = computed(() =>
  workspace.collections.find((item) => item.id === selectedCollectionId.value) ?? workspace.collections[0] ?? null,
)

watch(
  () => workspace.collections,
  (items) => {
    if (!items.length) {
      selectedCollectionId.value = ''
      return
    }
    if (!items.some((item) => item.id === selectedCollectionId.value)) {
      selectedCollectionId.value = items[0].id
    }
  },
  { immediate: true },
)

async function runSelectedCollection() {
  if (!selectedCollection.value) return
  await workspace.executeCollection(selectedCollection.value.id, concurrency.value)
}

onMounted(async () => {
  await workspace.loadCollections()
})
</script>

<template>
  <section class="page">
    <div class="page-header">
      <div>
        <span class="page-kicker">BATCH</span>
        <h2>请求集合</h2>
        <p>把高频请求整理成集合，按顺序或有限并发批量执行。</p>
      </div>
      <div class="toolbar">
        <label class="inline-field">
          <span>并发数</span>
          <input v-model.number="concurrency" type="number" min="1" max="5" class="input compact" />
        </label>
        <button class="button" :disabled="!selectedCollection" @click="runSelectedCollection">运行集合</button>
      </div>
    </div>

    <div class="panel-grid history-grid">
      <section class="panel list-panel">
        <div class="panel-title-row">
          <h3>已保存集合</h3>
          <span class="muted">共 {{ workspace.collections.length }} 个</span>
        </div>
        <button
          v-for="collection in workspace.collections"
          :key="collection.id"
          class="history-row"
          :class="{ active: collection.id === selectedCollection?.id }"
          @click="selectedCollectionId = collection.id"
        >
          <div class="history-row-top">
            <strong>{{ collection.name }}</strong>
            <span class="source-badge">{{ collection.entries.length }} 条请求</span>
          </div>
          <div class="history-url">{{ collection.description || '暂无说明' }}</div>
          <div class="history-row-meta">
            <span>{{ new Date(collection.updated_at).toLocaleString() }}</span>
          </div>
        </button>
      </section>

      <section class="panel detail-panel" v-if="selectedCollection">
        <div class="panel-title-row">
          <div>
            <h3>{{ selectedCollection.name }}</h3>
            <p class="muted">{{ selectedCollection.description || '可重复执行的请求集合' }}</p>
          </div>
        </div>

        <div class="stack">
          <div v-for="entry in selectedCollection.entries" :key="entry.id" class="subpanel">
            <div class="panel-title-row">
              <h4>{{ entry.name }}</h4>
              <span class="muted">{{ entry.request.method }} {{ entry.request.url }}</span>
            </div>
            <CodeEditor :model-value="entry.request.body_text || entry.request.url" read-only />
          </div>
        </div>
      </section>
      <div v-else class="panel empty-state compact-empty">
        <h4>还没有可运行的集合</h4>
        <p>去“请求重放”页保存一条请求，这里就会出现第一组可复用的脚本化流量。</p>
      </div>
    </div>

    <section class="panel" v-if="workspace.lastBatchRun">
      <div class="panel-title-row">
        <div>
          <h3>最近一次批量执行</h3>
          <p class="muted">共 {{ workspace.lastBatchRun.results.length }} 个结果</p>
        </div>
      </div>
      <div class="stack">
        <div v-for="result in workspace.lastBatchRun.results" :key="result.entry_id" class="subpanel">
          <div class="panel-title-row">
            <h4>{{ result.entry_name }}</h4>
            <span class="muted">
              {{ result.result.status_code ?? '错误' }}
              {{ result.result.elapsed_ms ?? 0 }} ms
            </span>
          </div>
          <CodeEditor :model-value="result.result.raw_response" read-only mode="http" />
        </div>
      </div>
    </section>
  </section>
</template>
