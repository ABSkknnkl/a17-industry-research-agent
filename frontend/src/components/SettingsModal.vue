<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getSettingsConfig,
  updateSettingsConfig,
  resetSettingsConfig,
  testLlmConnectivity,
  testIwencaiConnectivity,
} from '../api/client'
import type { SystemSettingsConfig, TestConnectivityResult } from '../api/types'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
}>()

const loading = ref(false)
const saving = ref(false)
const testingLlm = ref(false)
const testingIwencai = ref(false)

const llmTestResult = ref<TestConnectivityResult | null>(null)
const iwencaiTestResult = ref<TestConnectivityResult | null>(null)

const activeTab = ref('llm')

const form = reactive<SystemSettingsConfig>({
  llm_api_key: '',
  llm_base_url: '',
  llm_model: '',
  iwencai_api_key: '',
  has_custom_settings: false,
})

interface ProviderPreset {
  name: string
  label: string
  baseUrl: string
  defaultModel: string
  desc: string
}

const PRESETS: ProviderPreset[] = [
  {
    name: 'volcengine',
    label: '火山方舟 (默认)',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/plan/v3',
    defaultModel: 'deepseek-v4-flash',
    desc: '字节跳动火山引擎企业级高可用接入点，极速低延迟',
  },
  {
    name: 'deepseek',
    label: 'DeepSeek 官方',
    baseUrl: 'https://api.deepseek.com',
    defaultModel: 'deepseek-chat',
    desc: 'DeepSeek 原厂 API，支持 deepseek-chat 及 deepseek-reasoner',
  },
  {
    name: 'siliconflow',
    label: '硅基流动',
    baseUrl: 'https://api.siliconflow.cn/v1',
    defaultModel: 'deepseek-ai/DeepSeek-V3',
    desc: '国内主流算力平台，支持高并发全系列 DeepSeek 模型',
  },
  {
    name: 'ollama',
    label: '本地 Ollama',
    baseUrl: 'http://127.0.0.1:11434/v1',
    defaultModel: 'deepseek-r1:latest',
    desc: '局域网或单机私有化离线部署，免公网 Token',
  },
]

function applyPreset(preset: ProviderPreset): void {
  form.llm_base_url = preset.baseUrl
  form.llm_model = preset.defaultModel
  llmTestResult.value = null
  ElMessage.info(`已填入【${preset.label}】接口地址与模型名称`)
}

async function loadConfig(): Promise<void> {
  loading.value = true
  llmTestResult.value = null
  iwencaiTestResult.value = null
  try {
    const data = await getSettingsConfig()
    form.llm_api_key = data.llm_api_key
    form.llm_base_url = data.llm_base_url
    form.llm_model = data.llm_model
    form.iwencai_api_key = data.iwencai_api_key
    form.has_custom_settings = data.has_custom_settings
  } catch (e: any) {
    ElMessage.error(`加载配置失败: ${e.message || '网络异常'}`)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (visible) => {
    if (visible) {
      loadConfig()
    }
  }
)

async function onTestLlm(): Promise<void> {
  testingLlm.value = true
  llmTestResult.value = null
  try {
    const res = await testLlmConnectivity({
      llm_api_key: form.llm_api_key,
      llm_base_url: form.llm_base_url,
      llm_model: form.llm_model,
    })
    llmTestResult.value = res
  } catch (e: any) {
    llmTestResult.value = {
      success: false,
      message: `连通性测试请求异常: ${e.message || '未知错误'}`,
    }
  } finally {
    testingLlm.value = false
  }
}

async function onTestIwencai(): Promise<void> {
  testingIwencai.value = true
  iwencaiTestResult.value = null
  try {
    const res = await testIwencaiConnectivity({
      iwencai_api_key: form.iwencai_api_key,
    })
    iwencaiTestResult.value = res
  } catch (e: any) {
    iwencaiTestResult.value = {
      success: false,
      message: `问财测试请求异常: ${e.message || '未知错误'}`,
    }
  } finally {
    testingIwencai.value = false
  }
}

async function onSave(): Promise<void> {
  if (!form.llm_base_url.trim()) {
    ElMessage.warning('大模型 Base URL 不能为空')
    return
  }
  if (!form.llm_model.trim()) {
    ElMessage.warning('模型名称不能为空')
    return
  }

  saving.value = true
  try {
    await updateSettingsConfig({
      llm_api_key: form.llm_api_key.trim(),
      llm_base_url: form.llm_base_url.trim(),
      llm_model: form.llm_model.trim(),
      iwencai_api_key: form.iwencai_api_key.trim(),
    })
    ElMessage.success('配置已成功保存并实时生效！')
    emit('update:modelValue', false)
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e.message || '网络异常'}`)
  } finally {
    saving.value = false
  }
}

async function onReset(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确定恢复为系统出厂预置配置吗？当前自定义填写的 API Key 将被清除。',
      '恢复默认配置',
      {
        confirmButtonText: '确定恢复',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    return
  }

  loading.value = true
  try {
    const res = await resetSettingsConfig()
    form.llm_api_key = res.data.llm_api_key
    form.llm_base_url = res.data.llm_base_url
    form.llm_model = res.data.llm_model
    form.iwencai_api_key = res.data.iwencai_api_key
    form.has_custom_settings = false
    llmTestResult.value = null
    iwencaiTestResult.value = null
    ElMessage.success('已恢复系统预置默认配置')
  } catch (e: any) {
    ElMessage.error(`恢复失败: ${e.message || '网络异常'}`)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="系统与模型接口配置"
    width="680px"
    class="settings-modal"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading" class="dialog-body">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 16px"
      >
        <template #title>
          <span>
            配置保存在本机数据目录中，修改后即时热更新，五智能体（数据获取、分析、图表、撰写、融合）将立即应用新配置。
          </span>
        </template>
      </el-alert>

      <el-tabs v-model="activeTab" class="settings-tabs">
        <!-- Tab 1: LLM Engine -->
        <el-tab-pane label="🤖 大模型基座 (LLM)" name="llm">
          <div class="field-section">
            <div class="field-label">服务商快捷预设</div>
            <div class="preset-badges">
              <el-button
                v-for="p in PRESETS"
                :key="p.name"
                size="small"
                plain
                @click="applyPreset(p)"
              >
                {{ p.label }}
              </el-button>
            </div>
          </div>

          <el-form label-position="top" size="default">
            <el-form-item label="Base URL（兼容 OpenAI 规范的 API 接入地址）" required>
              <el-input
                v-model="form.llm_base_url"
                placeholder="例如: https://ark.cn-beijing.volces.com/api/plan/v3"
                clearable
              />
            </el-form-item>

            <el-form-item label="Model 模型名称" required>
              <el-input
                v-model="form.llm_model"
                placeholder="例如: deepseek-v4-flash, deepseek-chat, deepseek-reasoner"
                clearable
              />
            </el-form-item>

            <el-form-item label="LLM API Key">
              <el-input
                v-model="form.llm_api_key"
                type="password"
                show-password
                placeholder="粘贴您的 API Key（如 sk-... 或 ark-...）"
                clearable
              />
            </el-form-item>
          </el-form>

          <div class="test-action-bar">
            <el-button
              type="primary"
              plain
              size="small"
              :loading="testingLlm"
              @click="onTestLlm"
            >
              {{ testingLlm ? '正在测试连接...' : '🔌 测试大模型连通性' }}
            </el-button>
          </div>

          <div v-if="llmTestResult" style="margin-top: 10px">
            <el-alert
              :type="llmTestResult.success ? 'success' : 'error'"
              :title="llmTestResult.message"
              show-icon
              :closable="false"
            />
          </div>
        </el-tab-pane>

        <!-- Tab 2: iWenCai SkillHub -->
        <el-tab-pane label="📈 问财金融数据凭证" name="iwencai">
          <div class="tab-desc">
            同花顺问财官方金融技能凭证，负责驱动数据采集智能体抽取 A 股企业基本面、多年度财务三表与核心行情指标。
          </div>

          <el-form label-position="top" size="default" style="margin-top: 14px">
            <el-form-item label="问财 SkillHub Token">
              <el-input
                v-model="form.iwencai_api_key"
                type="password"
                show-password
                placeholder="sk-proj-00-..."
                clearable
              />
              <div class="hint-text">
                留空则使用系统预置的同花顺官方凭证池。
              </div>
            </el-form-item>
          </el-form>

          <div class="test-action-bar">
            <el-button
              type="primary"
              plain
              size="small"
              :loading="testingIwencai"
              @click="onTestIwencai"
            >
              {{ testingIwencai ? '正在测试数据接口...' : '🔌 测试问财接口' }}
            </el-button>
          </div>

          <div v-if="iwencaiTestResult" style="margin-top: 10px">
            <el-alert
              :type="iwencaiTestResult.success ? 'success' : 'error'"
              :title="iwencaiTestResult.message"
              show-icon
              :closable="false"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <div class="left-actions">
          <el-button
            size="default"
            type="danger"
            link
            @click="onReset"
          >
            恢复默认配置
          </el-button>
        </div>
        <div class="right-actions">
          <el-button @click="emit('update:modelValue', false)">取消</el-button>
          <el-button type="primary" :loading="saving" @click="onSave">
            保存配置
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-body {
  min-height: 320px;
}
.field-section {
  margin-bottom: 16px;
}
.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}
.preset-badges {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.test-action-bar {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}
.tab-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.hint-text {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}
.dialog-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
