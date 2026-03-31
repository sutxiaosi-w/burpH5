export type HistorySource = 'ui' | 'api' | 'cli' | 'mcp' | 'proxy'

export interface Header {
  name: string
  value: string
}

export interface ReplayRequest {
  method: string
  url: string
  headers: Header[]
  body_text?: string | null
  body_base64?: string | null
  timeout_ms: number
  follow_redirects: boolean
  tags: string[]
  variables: Record<string, string>
}

export interface ReplayResult {
  status_code?: number | null
  reason?: string | null
  headers: Header[]
  body_text?: string | null
  body_base64?: string | null
  elapsed_ms?: number | null
  raw_request: string
  raw_response: string
  error?: string | null
}

export interface ReplayExecuteResponse {
  request: ReplayRequest
  result: ReplayResult
  history_id?: string | null
}

export interface HistoryItem {
  id: string
  source: HistorySource
  request: ReplayRequest
  result: ReplayResult
  created_at: string
  tags: string[]
}

export interface HistoryDeleteResponse {
  deleted: boolean
  id: string
}

export interface HistoryClearResponse {
  deleted_count: number
  source?: string | null
}

export interface CollectionEntry {
  id: string
  name: string
  request: ReplayRequest
}

export interface CollectionItem {
  id: string
  name: string
  description: string
  variables: Record<string, string>
  entries: CollectionEntry[]
  created_at: string
  updated_at: string
}

export interface CollectionWrite {
  name: string
  description: string
  variables: Record<string, string>
  entries: CollectionEntry[]
}

export interface BatchRunEntryResult {
  entry_id: string
  entry_name: string
  request: ReplayRequest
  result: ReplayResult
  history_id?: string | null
}

export interface BatchRun {
  id: string
  collection_id: string
  concurrency: number
  variables: Record<string, string>
  results: BatchRunEntryResult[]
  created_at: string
}

export interface ProxyStatus {
  enabled: boolean
  host: string
  port: number
  capture_https: boolean
  running: boolean
}
