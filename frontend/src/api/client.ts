import axios from 'axios'

import type {
  BatchRun,
  CollectionItem,
  CollectionWrite,
  HistoryClearResponse,
  HistoryDeleteResponse,
  HistoryItem,
  ProxyFlowDetail,
  ProxyFlowSummary,
  ProxySettings,
  ProxyStatus,
  ReplayExecuteResponse,
  ReplayRequest,
} from '../types/api'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 20000,
})

export async function fetchHistory(source?: string): Promise<HistoryItem[]> {
  const response = await client.get<HistoryItem[]>('/api/history', {
    params: source ? { source } : undefined,
  })
  return response.data
}

export async function deleteHistoryItem(id: string): Promise<HistoryDeleteResponse> {
  const response = await client.delete<HistoryDeleteResponse>(`/api/history/${id}`)
  return response.data
}

export async function clearHistory(source?: string): Promise<HistoryClearResponse> {
  const response = await client.delete<HistoryClearResponse>('/api/history', {
    params: source ? { source } : undefined,
  })
  return response.data
}

export async function parseRawRequest(rawRequest: string, defaultScheme = 'http'): Promise<ReplayRequest> {
  const response = await client.post<ReplayRequest>('/api/replay/parse-raw', {
    raw_request: rawRequest,
    default_scheme: defaultScheme,
  })
  return response.data
}

export async function sendReplay(rawRequest: string): Promise<ReplayExecuteResponse> {
  const response = await client.post<ReplayExecuteResponse>('/api/replay', {
    raw_request: rawRequest,
    source: 'ui',
    persist: true,
    default_scheme: 'http',
  })
  return response.data
}

export async function fetchCollections(): Promise<CollectionItem[]> {
  const response = await client.get<CollectionItem[]>('/api/collections')
  return response.data
}

export async function createCollection(payload: CollectionWrite): Promise<CollectionItem> {
  const response = await client.post<CollectionItem>('/api/collections', payload)
  return response.data
}

export async function updateCollection(id: string, payload: CollectionWrite): Promise<CollectionItem> {
  const response = await client.put<CollectionItem>(`/api/collections/${id}`, payload)
  return response.data
}

export async function runSavedCollection(id: string, concurrency = 1): Promise<BatchRun> {
  const response = await client.post<BatchRun>(`/api/collections/${id}/run`, {
    concurrency,
    source: 'ui',
    persist: true,
  })
  return response.data
}

export async function fetchProxyStatus(): Promise<ProxyStatus> {
  const response = await client.get<ProxyStatus>('/api/proxy')
  return response.data
}

export async function fetchProxyFlows(limit = 200): Promise<ProxyFlowSummary[]> {
  const response = await client.get<ProxyFlowSummary[]>('/api/proxy/flows', {
    params: { limit },
  })
  return response.data
}

export async function fetchProxyFlowDetail(id: string): Promise<ProxyFlowDetail> {
  const response = await client.get<ProxyFlowDetail>(`/api/proxy/flows/${id}`)
  return response.data
}

export async function updateProxyStatus(payload: ProxySettings): Promise<ProxyStatus> {
  const response = await client.put<ProxyStatus>('/api/proxy', payload)
  return response.data
}

export async function ensureProxyCertificate(): Promise<ProxyStatus> {
  const response = await client.post<ProxyStatus>('/api/proxy/certificate/ensure')
  return response.data
}

export async function installProxyCertificate(): Promise<ProxyStatus> {
  const response = await client.post<ProxyStatus>('/api/proxy/certificate/install')
  return response.data
}

export async function clearProxyLeafCertificates(): Promise<ProxyStatus> {
  const response = await client.post<ProxyStatus>('/api/proxy/certificate/clear-leaf')
  return response.data
}

export async function deleteProxyCertificates(): Promise<ProxyStatus> {
  const response = await client.post<ProxyStatus>('/api/proxy/certificate/delete')
  return response.data
}

export async function resetProxyCertificate(): Promise<ProxyStatus> {
  const response = await client.post<ProxyStatus>('/api/proxy/certificate/reset')
  return response.data
}

export function getProxyCertificateDownloadUrl(): string {
  return `${API_BASE_URL}/api/proxy/certificate/download`
}
