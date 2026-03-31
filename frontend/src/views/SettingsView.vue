<script setup lang="ts">
import { onMounted } from 'vue'

import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()

async function saveProxy() {
  await workspace.saveProxyStatus()
}

onMounted(async () => {
  await workspace.loadProxyStatus()
})
</script>

<template>
  <section class="page">
    <div class="page-header">
      <div>
        <h2>系统设置</h2>
        <p>在这里管理本地代理、接口地址和 MCP 的调用说明。</p>
      </div>
    </div>

    <div class="panel-grid save-grid">
      <section class="panel">
        <div class="panel-title-row">
          <h3>HTTP 代理</h3>
          <span class="muted">{{ workspace.proxyStatus.running ? '运行中' : '未启动' }}</span>
        </div>
        <div class="form-grid">
          <label class="toggle-field">
            <span>启用代理</span>
            <input v-model="workspace.proxyStatus.enabled" type="checkbox" />
          </label>
          <label>
            <span>监听地址</span>
            <input v-model="workspace.proxyStatus.host" class="input" />
          </label>
          <label>
            <span>监听端口</span>
            <input v-model.number="workspace.proxyStatus.port" type="number" class="input" />
          </label>
          <label>
            <span>HTTPS 抓取</span>
            <input :checked="false" type="checkbox" disabled />
            <small class="muted">当前版本仅透传 CONNECT，不做证书中间人解密。</small>
          </label>
        </div>
        <button class="button" @click="saveProxy">应用代理设置</button>
      </section>

      <section class="panel">
        <div class="panel-title-row">
          <h3>调用方式</h3>
        </div>
        <div class="stack">
          <div class="subpanel">
            <h4>REST 接口</h4>
            <p class="muted">默认地址：<code>http://127.0.0.1:8765</code></p>
            <p class="muted">
              常用接口：<code>POST /api/replay</code>、
              <code>GET /api/history</code>、
              <code>POST /api/collections/{id}/run</code>
            </p>
          </div>
          <div class="subpanel">
            <h4>CLI</h4>
            <p class="muted"><code>python -m burph5.cli replay --raw-file req.txt</code></p>
            <p class="muted"><code>python -m burph5.cli proxy start</code></p>
          </div>
          <div class="subpanel">
            <h4>MCP</h4>
            <p class="muted"><code>python -m burph5.mcp_server</code></p>
            <p class="muted">工具：replay_request、parse_raw_request、list_history、get_history_item、save_collection、run_collection</p>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>
