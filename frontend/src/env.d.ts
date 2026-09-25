/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API 基址，默认 /api/v1；对接外部后端时可填完整地址 */
  readonly VITE_API_BASE_URL?: string
  /** 应用标题 */
  readonly VITE_APP_TITLE?: string
  /**
   * 默认访问 Token，由 .env.local 提供（该文件已被 git 忽略）。
   * 非空时优先生效，免手工输入；删除该变量即恢复手工输入模式。
   */
  readonly VITE_DEFAULT_TOKEN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}
