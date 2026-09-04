import axios, { AxiosError } from 'axios'
import { useAuthStore } from '../stores/auth'

export const AUTH_REQUIRED_EVENT = 'trc:auth-required'

/** 后端错误归一化：detail 可能是 string 或 {code, message} 对象 */
export class ApiError extends Error {
  readonly status?: number
  readonly code?: string

  constructor(message: string, status?: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

function extractDetail(data: unknown): { message: string; code?: string } {
  if (typeof data === 'string') return { message: data }
  if (data && typeof data === 'object' && 'detail' in data) {
    const detail = (data as { detail: unknown }).detail
    if (typeof detail === 'string') return { message: detail }
    if (detail && typeof detail === 'object') {
      const obj = detail as Record<string, unknown>
      const code = typeof obj.code === 'string' ? obj.code : undefined
      const message =
        typeof obj.message === 'string'
          ? obj.message
          : typeof obj.msg === 'string'
            ? obj.msg
            : JSON.stringify(detail)
      return { message, code }
    }
  }
  return { message: JSON.stringify(data) }
}

/**
 * API 基址：默认走 Vite 代理转发到后端的同源前缀 /api/v1。
 * 对接外部后端时，在 .env.local 里设置 VITE_API_BASE_URL 为完整地址即可，例如：
 *   VITE_API_BASE_URL=http://10.0.0.7:8000/api/v1
 * 该后端需开启 CORS 并放行 Authorization 头。
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL?.trim() || '/api/v1'

export const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60_000,
})

http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.isAuthenticated) {
    config.headers.set('Authorization', auth.authHeader)
  }
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status
    if (status === 401) {
      const auth = useAuthStore()
      auth.clearToken()
      window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT))
      return Promise.reject(new ApiError('认证失败，请输入有效 Token', 401, 'AUTH_FAILED'))
    }
    const { message, code } = extractDetail(error.response?.data)
    const fallback = error.code === 'ECONNABORTED' ? '请求超时，请稍后重试' : error.message
    return Promise.reject(new ApiError(message || fallback, status, code))
  }
)
