/**
 * 前端主应用入口
 * 负责人：前端A（UI工程师）+ 前端B（交互工程师）
 *
 * 本轮仅负责：挂载应用、注册 Element Plus、接入 Router
 * 后续接入：Pinia状态管理、ECharts图表组件
 */

import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'

const app = createApp(App)

app.use(createPinia())

// 注册 Element Plus
app.use(ElementPlus)

// 注册 Router
app.use(router)

// 挂载应用
app.mount('#app')
