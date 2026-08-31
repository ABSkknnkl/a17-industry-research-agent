import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

/**
 * 后端地址：默认本机 8000 端口。
 * 对接外部后端时，在 .env.local 中设置 VITE_PROXY_TARGET=http://host:port 即可，
 * 开发服务器会把 /api 请求代理过去，无需改动业务代码。
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const proxyTarget = env.VITE_PROXY_TARGET?.trim() || 'http://localhost:8000'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  }
})
