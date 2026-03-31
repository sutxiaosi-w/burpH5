import { defineStore } from 'pinia'

import {
  clearHistory as clearHistoryRequest,
  createCollection,
  deleteHistoryItem as deleteHistoryItemRequest,
  deleteProxyCertificates as deleteProxyCertificatesRequest,
  fetchCollections,
  fetchHistory,
  fetchProxyFlowDetail,
  fetchProxyFlows,
  fetchProxyStatus,
  clearProxyLeafCertificates as clearProxyLeafCertificatesRequest,
  ensureProxyCertificate as ensureProxyCertificateRequest,
  installProxyCertificate as installProxyCertificateRequest,
  getProxyCertificateDownloadUrl,
  parseRawRequest,
  resetProxyCertificate as resetProxyCertificateRequest,
  runSavedCollection,
  sendReplay,
  updateCollection,
  updateProxyStatus,
} from '../api/client'
import type {
  BatchRun,
  CollectionEntry,
  CollectionItem,
  HistoryItem,
  ProxyFlowDetail,
  ProxyFlowSummary,
  ProxySettings,
  ProxyStatus,
  ReplayExecuteResponse,
  ReplayRequest,
} from '../types/api'

const starterRequest = `GET http://httpbin.org/get HTTP/1.1
User-Agent: burph5
Accept: */*
`

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    loading: false,
    history: [] as HistoryItem[],
    proxyFlows: [] as ProxyFlowSummary[],
    proxyFlowDetail: null as ProxyFlowDetail | null,
    collections: [] as CollectionItem[],
    proxyStatus: {
      enabled: false,
      host: '127.0.0.1',
      port: 8899,
      capture_https: false,
      bypass_hosts: [],
      running: false,
      ca_ready: false,
      ca_installed: null,
      ca_subject: null,
      ca_thumbprint: null,
      ca_cert_path: null,
      leaf_cert_count: 0,
      last_error: null,
    } as ProxyStatus,
    repeaterRawRequest: starterRequest,
    repeaterParsedRequest: null as ReplayRequest | null,
    lastReplay: null as ReplayExecuteResponse | null,
    lastBatchRun: null as BatchRun | null,
    error: '',
  }),
  actions: {
    clearError() {
      this.error = ''
    },
    setRepeaterRawRequest(value: string) {
      this.repeaterRawRequest = value
    },
    loadIntoRepeater(historyItem: HistoryItem) {
      this.repeaterRawRequest = historyItem.result.raw_request || historyItem.request.url
      this.lastReplay = {
        request: historyItem.request,
        result: historyItem.result,
        history_id: historyItem.id,
      }
    },
    async loadHistory(source?: string) {
      this.history = await fetchHistory(source)
    },
    async loadProxyFlows(limit = 200) {
      this.proxyFlows = await fetchProxyFlows(limit)
      return this.proxyFlows
    },
    async loadProxyFlowDetail(id: string) {
      this.proxyFlowDetail = await fetchProxyFlowDetail(id)
      return this.proxyFlowDetail
    },
    async deleteHistoryItem(id: string) {
      await deleteHistoryItemRequest(id)
    },
    async clearHistory(source?: string) {
      return clearHistoryRequest(source)
    },
    async loadCollections() {
      this.collections = await fetchCollections()
    },
    async loadProxyStatus() {
      this.proxyStatus = await fetchProxyStatus()
    },
    async parseRepeaterRequest() {
      this.repeaterParsedRequest = await parseRawRequest(this.repeaterRawRequest)
      return this.repeaterParsedRequest
    },
    async executeRepeater() {
      this.loading = true
      this.error = ''
      try {
        this.lastReplay = await sendReplay(this.repeaterRawRequest)
        await this.loadHistory()
        return this.lastReplay
      } catch (error) {
        this.error = error instanceof Error ? error.message : '请求重放失败。'
        throw error
      } finally {
        this.loading = false
      }
    },
    async appendRequestToCollection(options: {
      collectionId?: string
      newCollectionName?: string
      entryName: string
    }) {
      const request = await this.parseRepeaterRequest()
      const entry: CollectionEntry = {
        id: crypto.randomUUID(),
        name: options.entryName,
        request,
      }

      if (options.collectionId) {
        const existing = this.collections.find((item) => item.id === options.collectionId)
        if (!existing) {
          throw new Error('未找到所选集合。')
        }
        await updateCollection(existing.id, {
          name: existing.name,
          description: existing.description,
          variables: existing.variables,
          entries: [...existing.entries, entry],
        })
      } else if (options.newCollectionName) {
        await createCollection({
          name: options.newCollectionName,
          description: '',
          variables: {},
          entries: [entry],
        })
      } else {
        throw new Error('请选择一个已有集合，或填写新的集合名称。')
      }

      await this.loadCollections()
    },
    async executeCollection(id: string, concurrency = 1) {
      this.lastBatchRun = await runSavedCollection(id, concurrency)
      await this.loadHistory()
      return this.lastBatchRun
    },
    async saveProxyStatus() {
      const payload: ProxySettings = {
        enabled: this.proxyStatus.enabled,
        host: this.proxyStatus.host,
        port: this.proxyStatus.port,
        capture_https: this.proxyStatus.capture_https,
        bypass_hosts: [...this.proxyStatus.bypass_hosts],
      }
      this.proxyStatus = await updateProxyStatus(payload)
      return this.proxyStatus
    },
    async ensureProxyCertificate() {
      this.proxyStatus = await ensureProxyCertificateRequest()
      return this.proxyStatus
    },
    async installProxyCertificate() {
      this.proxyStatus = await installProxyCertificateRequest()
      return this.proxyStatus
    },
    async clearProxyLeafCertificates() {
      this.proxyStatus = await clearProxyLeafCertificatesRequest()
      return this.proxyStatus
    },
    async deleteProxyCertificates() {
      this.proxyStatus = await deleteProxyCertificatesRequest()
      return this.proxyStatus
    },
    async resetProxyCertificate() {
      this.proxyStatus = await resetProxyCertificateRequest()
      return this.proxyStatus
    },
    getProxyCertificateDownloadUrl() {
      return getProxyCertificateDownloadUrl()
    },
  },
})
