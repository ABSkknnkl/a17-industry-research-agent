/**
 * API请求封装
 * 负责人：前端B（交互工程师）
 *
 * 使用 Axios 封装统一的HTTP请求方法
 * 后续扩展：请求/响应拦截器、Token管理、错误处理
 */

import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器（预留）
api.interceptors.request.use(
  (config) => {
    // 后续添加 Token 等认证信息
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器（预留）
api.interceptors.response.use(
  (response) => {
    return response.data
  },
  (error) => {
    console.error('API请求错误:', error)
    return Promise.reject(error)
  }
)

export default api
