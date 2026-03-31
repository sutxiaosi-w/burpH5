<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref, watch } from 'vue'

import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const bypassHostsText = ref('')
const actionLoading = ref('')
const actionError = ref('')

const certificateDownloadUrl = computed(() => workspace.getProxyCertificateDownloadUrl())
const httpsReady = computed(() => workspace.proxyStatus.capture_https && workspace.proxyStatus.ca_ready)
const visibleErrorText = computed(() => sanitizeError(actionError.value || workspace.proxyStatus.last_error || ''))
const certificatePathText = computed(() => {
  const path = workspace.proxyStatus.ca_cert_path
  if (!path) return '尚未生成或已删除本地根证书。'
  const normalized = path.replaceAll('\\', '/')
  const marker = '/backend/data/certs/'
  const markerIndex = normalized.toLowerCase().indexOf(marker)
  if (markerIndex >= 0) {
    return normalized.slice(markerIndex + 1)
  }
  const fileName = normalized.split('/').pop() || 'burph5-root-ca.cer'
  return `backend/data/certs/${fileName}`
})

watch(
  () => workspace.proxyStatus.bypass_hosts,
  (hosts) => {
    bypassHostsText.value = (hosts ?? []).join('\n')
  },
  { immediate: true },
)

function parseBypassHosts() {
  return Array.from(new Set(bypassHostsText.value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)))
}

async function runAction(name: string, action: () => Promise<void>) {
  actionLoading.value = name
  actionError.value = ''
  try {
    await action()
  } catch (error) {
    actionError.value = formatActionError(error)
  } finally {
    actionLoading.value = ''
  }
}

function formatActionError(error: unknown) {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status
    if (status === 405) return '当前后端还没更新到这个功能，请重启 burph5 后再试。'
    if (status === 404) return '当前接口不存在，可能是后端版本还没同步。'
    if (status === 500) return '后端处理失败，请查看控制台或日志。'
    if (error.message) return `请求失败：${error.message}`
  }
  return error instanceof Error ? error.message : '操作失败，请稍后重试。'
}

async function saveProxy() {
  workspace.proxyStatus.bypass_hosts = parseBypassHosts()
  await runAction('save', async () => {
    await workspace.saveProxyStatus()
  })
}

async function ensureCertificate() {
  await runAction('ensure', async () => {
    await workspace.ensureProxyCertificate()
  })
}

async function installCertificate() {
  await runAction('install', async () => {
    await workspace.installProxyCertificate()
  })
}

async function clearLeafCertificates() {
  const confirmed = window.confirm('这只会清空已签发叶子证书缓存，不会删除根证书，也不会卸载 Windows 信任。是否继续？')
  if (!confirmed) return

  await runAction('clear-leaf', async () => {
    await workspace.clearProxyLeafCertificates()
  })
}

async function resetCertificate() {
  const confirmed = window.confirm('重置会删除当前 burph5 根证书和已签发站点证书，是否继续？')
  if (!confirmed) return

  await runAction('reset', async () => {
    await workspace.resetProxyCertificate()
  })
}

function downloadCertificate() {
  window.open(certificateDownloadUrl.value, '_blank', 'noopener,noreferrer')
}

function certificateInstallText() {
  if (workspace.proxyStatus.ca_installed === true) return '已安装'
  if (workspace.proxyStatus.ca_ready) return '未安装'
  return '未安装'
}

function sanitizeError(message: string) {
  if (!message) return ''
  const sanitized = message.replace(/[A-Z]:\\\\[^\\s'"]+/gi, '[本地文件路径]')
  if (sanitized.includes('Import-Certificate') && sanitized.includes('操作已被用户取消')) {
    return '证书导入已取消。若暂时不用 HTTPS 抓取，可以删除本地证书文件。'
  }
  if (sanitized.includes('Import-Certificate')) {
    return 'Windows 证书导入失败，请检查系统证书弹窗或权限。'
  }
  return sanitized
}

async function deleteCertificates() {
  const confirmed = window.confirm(
    '这会删除本地证书文件目录、移除当前用户里的 burph5 根证书信任，并自动关闭 HTTPS 抓取。是否继续？',
  )
  if (!confirmed) return

  await runAction('delete', async () => {
    await workspace.deleteProxyCertificates()
  })
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
        <p>在这里管理本地代理、HTTPS 证书、接口地址和 MCP 的调用说明。</p>
      </div>
    </div>

    <div v-if="visibleErrorText" class="error-banner">
      {{ visibleErrorText }}
    </div>

    <div class="panel-grid save-grid">
      <section class="panel settings-panel">
        <div class="panel-title-row">
          <div>
            <h3>HTTP / HTTPS 代理</h3>
            <p class="muted">支持明文 HTTP 抓取，以及基于本地根证书的 HTTPS MITM 解密。</p>
          </div>
          <span class="status-pill" :class="workspace.proxyStatus.running ? 'ok' : 'idle'">
            {{ workspace.proxyStatus.running ? '运行中' : '未启动' }}
          </span>
        </div>

        <div class="form-grid settings-form-grid">
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
          <label class="toggle-field">
            <span>HTTPS 抓取</span>
            <input v-model="workspace.proxyStatus.capture_https" type="checkbox" />
          </label>
        </div>

        <label class="textarea-field">
          <span>HTTPS 例外主机</span>
          <textarea
            v-model="bypassHostsText"
            class="input textarea"
            placeholder="一行一个主机或域后缀，例如&#10;localhost&#10;internal.example.com"
          />
          <small class="muted">
            命中例外主机时将继续透传 CONNECT，不做中间人解密。默认 `localhost / 127.0.0.1 / ::1`
            也不会被解密。
          </small>
        </label>

        <div class="status-grid">
          <div class="status-card">
            <span class="summary-label">HTTPS 代理状态</span>
            <strong class="status-value">{{ httpsReady ? '可解密' : '未就绪' }}</strong>
          </div>
          <div class="status-card">
            <span class="summary-label">Windows 证书状态</span>
            <strong class="status-value">{{ certificateInstallText() }}</strong>
          </div>
        </div>

        <div class="button-row settings-button-row">
          <button class="button settings-primary-button" :disabled="actionLoading !== ''" @click="saveProxy">
            {{ actionLoading === 'save' ? '保存中...' : '应用代理设置' }}
          </button>
        </div>

        <p class="muted settings-footnote">
          开启 HTTPS 抓取但未安装根证书时，浏览器会提示证书不受信任。安装或重置证书后，建议重启浏览器。
        </p>
      </section>

      <section class="panel settings-panel">
        <div class="panel-title-row">
          <div>
            <h3>CA 证书管理</h3>
            <p class="muted">burph5 会生成本地根证书并按目标主机动态签发叶子证书。</p>
          </div>
          <span class="status-pill" :class="workspace.proxyStatus.ca_ready ? 'ok' : 'warn'">
            {{ workspace.proxyStatus.ca_ready ? '已生成' : '未生成' }}
          </span>
        </div>

        <div class="status-grid">
          <div class="status-card">
            <span class="summary-label">CA 状态</span>
            <strong class="status-value">{{ workspace.proxyStatus.ca_ready ? '已生成' : '未生成' }}</strong>
          </div>
          <div class="status-card">
            <span class="summary-label">已签发叶子证书</span>
            <strong class="status-value">{{ workspace.proxyStatus.leaf_cert_count }}</strong>
          </div>
          <div class="status-card">
            <span class="summary-label">证书指纹</span>
            <code>{{ workspace.proxyStatus.ca_thumbprint ?? '暂无' }}</code>
          </div>
          <div class="status-card">
            <span class="summary-label">证书主题</span>
            <code>{{ workspace.proxyStatus.ca_subject ?? '暂无' }}</code>
          </div>
        </div>

        <div class="stack settings-stack">
          <div class="subpanel">
            <h4>证书文件</h4>
            <p class="muted mono-block">{{ certificatePathText }}</p>
          </div>
          <div class="subpanel">
            <h4>自动安装说明</h4>
            <p class="muted">
              “安装到 Windows” 会写入 `Cert:\CurrentUser\Root`，默认不需要管理员权限，只影响当前用户。
            </p>
          </div>
        </div>

        <div class="button-row wrap settings-button-row">
          <button class="button" :disabled="actionLoading !== ''" @click="ensureCertificate">
            {{ actionLoading === 'ensure' ? '生成中...' : '生成证书' }}
          </button>
          <button class="button secondary" :disabled="actionLoading !== ''" @click="installCertificate">
            {{ actionLoading === 'install' ? '安装到 Windows' : '安装到 Windows' }}
          </button>
          <button class="button secondary" :disabled="actionLoading !== ''" @click="clearLeafCertificates">
            {{ actionLoading === 'clear-leaf' ? '清空中...' : '清空叶子缓存' }}
          </button>
          <button class="button secondary" :disabled="!workspace.proxyStatus.ca_ready" @click="downloadCertificate">
            下载证书
          </button>
          <button class="button danger-secondary" :disabled="actionLoading !== ''" @click="deleteCertificates">
            {{ actionLoading === 'delete' ? '删除中...' : '删除证书文件' }}
          </button>
          <button class="button danger-secondary" :disabled="actionLoading !== ''" @click="resetCertificate">
            {{ actionLoading === 'reset' ? '重置中...' : '重置证书' }}
          </button>
        </div>
      </section>
    </div>

    <section class="panel settings-panel">
      <div class="panel-title-row">
        <h3>调用方式</h3>
      </div>
      <div class="stack settings-stack">
        <div class="subpanel">
          <h4>REST 接口</h4>
          <p class="muted">默认地址：<code>http://127.0.0.1:8765</code></p>
          <p class="muted">
            常用接口：<code>POST /api/replay</code>、<code>GET /api/history</code>、
            <code>POST /api/collections/{id}/run</code>
          </p>
        </div>
        <div class="subpanel">
          <h4>CLI</h4>
          <p class="muted"><code>python -m burph5.cli proxy start --capture-https</code></p>
          <p class="muted"><code>python -m burph5.cli proxy ca install</code></p>
        </div>
        <div class="subpanel">
          <h4>MCP</h4>
          <p class="muted"><code>python -m burph5.mcp_server</code></p>
          <p class="muted">
            工具：replay_request、parse_raw_request、list_history、get_history_item、save_collection、run_collection
          </p>
        </div>
      </div>
    </section>
  </section>
</template>
