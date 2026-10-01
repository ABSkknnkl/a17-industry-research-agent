<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { marked } from 'marked'
import { ElMessage } from 'element-plus'
import {
  Search,
  Refresh,
  DataAnalysis,
  PieChart,
  Reading,
  Files,
  CollectionTag,
  CircleCheck,
  InfoFilled,
  CopyDocument,
  ArrowRight,
} from '@element-plus/icons-vue'
import { getSkillsCatalog, getSkillDetail } from '../api/client'
import type { AgentSkillGroup, SkillCatalogResponse, SkillItem } from '../api/types'

// ---------- 数据状态 ----------
const catalog = ref<SkillCatalogResponse | null>(null)
const loading = ref(false)
const refreshing = ref(false)
const activeStageFilter = ref<string>('all')
const searchQuery = ref('')
const activeCategory = ref<string>('all')

// 抽屉详情状态
const detailDrawerVisible = ref(false)
const selectedSkill = ref<SkillItem | null>(null)
const selectedAgent = ref<AgentSkillGroup | null>(null)
const detailLoading = ref(false)
const activeDetailTab = ref<'doc' | 'raw'>('doc')

// 阶段元信息与图标
const STAGE_META: Record<
  string,
  { label: string; icon: typeof DataAnalysis; color: string; desc: string }
> = {
  data_fetch: {
    label: 'Stage 1 数据获取智能体',
    icon: Search,
    color: '#0A2540',
    desc: '基于问财金融自然语言问答协议，结构化采集全量A股行情、财务、估值、资金与研报数据',
  },
  data_interpret: {
    label: 'Stage 2 数据解读智能体',
    icon: DataAnalysis,
    color: '#1E3A8A',
    desc: '运行量化分析、行业竞争格局识别、财务健康度评分与杜邦分析等专业投研指标挖掘',
  },
  chart_generate: {
    label: 'Stage 3 图表生成智能体',
    icon: PieChart,
    color: '#0D9488',
    desc: '按照申万与专业投研制图规范生成双轴图、杜邦拆解图、行业矩阵与产业链图谱',
  },
  chapter_write: {
    label: 'Stage 4 章节撰写智能体',
    icon: Reading,
    color: '#D97706',
    desc: '依据金字塔逻辑与严谨投研语体撰写宏观、产业链、竞争格局、财务与风险章节',
  },
  report_fusion: {
    label: 'Stage 5 研报融合智能体',
    icon: Files,
    color: '#4F46E5',
    desc: '完成全篇交叉质检、图表编号与正文绑定、证据链索引编排并交付多格式报告',
  },
}

// ---------- 统计计算 ----------
const totalSkills = computed(() => catalog.value?.total ?? 0)

const iwencaiSkillsCount = computed(() => {
  if (!catalog.value) return 0
  const fetchGroup = catalog.value.agents.find((a) => a.stage_id === 'data_fetch')
  return fetchGroup?.skills_count ?? 25
})

const methodologySkillsCount = computed(() => {
  return Math.max(0, totalSkills.value - iwencaiSkillsCount.value)
})

// 所有的分类列表（去重）
const categories = computed(() => {
  if (!catalog.value) return []
  const set = new Set<string>()
  for (const agent of catalog.value.agents) {
    for (const skill of agent.skills) {
      if (skill.category) {
        set.add(skill.category)
      }
    }
  }
  return Array.from(set)
})

// 各智能体独立分组，按搜索和分类过滤
const filteredGroups = computed(() => {
  if (!catalog.value) return []
  const query = searchQuery.value.trim().toLowerCase()
  const cat = activeCategory.value

  return catalog.value.agents
    .filter((agent) => {
      if (activeStageFilter.value === 'all') return true
      return agent.stage_id === activeStageFilter.value
    })
    .map((agent) => {
      const filteredSkills = agent.skills.filter((skill) => {
        // 分类匹配
        if (cat !== 'all' && skill.category !== cat) {
          return false
        }
        // 搜索词匹配
        if (!query) return true
        const matchName = skill.name?.toLowerCase().includes(query)
        const matchId = skill.id?.toLowerCase().includes(query)
        const matchDesc = skill.description?.toLowerCase().includes(query)
        const matchCat = skill.category?.toLowerCase().includes(query)
        const matchKeywords = skill.keywords?.some((k) => k.toLowerCase().includes(query))
        const matchDomains = skill.domains?.some((d) => d.toLowerCase().includes(query))
        return matchName || matchId || matchDesc || matchCat || matchKeywords || matchDomains
      })

      return {
        ...agent,
        skills: filteredSkills,
        filtered_count: filteredSkills.length,
      }
    })
})

// 计算匹配出的技能总数
const totalFilteredSkills = computed(() => {
  return filteredGroups.value.reduce((acc, g) => acc + g.filtered_count, 0)
})

// Markdown 渲染
const renderedDetailHtml = computed(() => {
  const doc = selectedSkill.value?.full_doc || selectedSkill.value?.doc_preview
  if (!doc) return '<p class="text-muted">暂无详细说明文档</p>'
  try {
    return marked.parse(doc, { async: false, gfm: true, breaks: false }) as string
  } catch {
    return `<pre>${doc}</pre>`
  }
})

// ---------- 加载数据 ----------
async function loadCatalog(refresh = false): Promise<void> {
  if (refresh) {
    refreshing.value = true
  } else {
    loading.value = true
  }
  try {
    const data = await getSkillsCatalog(refresh)
    catalog.value = data
    if (refresh) {
      ElMessage.success(`问财 Skill 库同步成功，共装载 ${data.total} 项专业技能`)
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : '网络或服务异常'
    ElMessage.error(`加载问财 Skill 库失败：${msg}`)
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

// 打开技能详情
async function openSkillDetail(skill: SkillItem, agent: AgentSkillGroup): Promise<void> {
  selectedSkill.value = skill
  selectedAgent.value = agent
  detailDrawerVisible.value = true
  activeDetailTab.value = 'doc'

  // 如果没有 full_doc，向后端拉取详细内容
  if (!skill.full_doc) {
    detailLoading.value = true
    try {
      const detailed = await getSkillDetail(agent.stage_id, skill.id)
      selectedSkill.value = detailed
    } catch {
      // 保持当前预览
    } finally {
      detailLoading.value = false
    }
  }
}

// 复制技能文档
function copySkillContent(): void {
  const text = selectedSkill.value?.full_doc || selectedSkill.value?.description || ''
  if (!text) return
  navigator.clipboard.writeText(text).then(
    () => {
      ElMessage.success('技能文档已复制到剪贴板')
    },
    () => {
      ElMessage.warning('复制失败，请手动选中文本复制')
    }
  )
}

onMounted(() => {
  void loadCatalog(false)
})
</script>

<template>
  <div class="skills-hub-view" v-loading="loading">
    <!-- 头部品牌横幅与统计指标 -->
    <div class="hub-hero">
      <div class="hero-left">
        <div class="hero-badge">
          <el-icon><CollectionTag /></el-icon>
          <span>金融多智能体专业能力矩阵 · 问财与投研规范体系</span>
        </div>
        <h1 class="hero-title">同花顺问财金融 Skill 知识库</h1>
        <p class="hero-subtitle">
          全链路 5
          大专业智能体技能清单：涵盖问财自然语言金融指标查询、量化投研解读模型、高阶可视化图表与严谨研报写作规范。
        </p>
      </div>

      <div class="hero-actions">
        <el-button
          type="primary"
          :icon="Refresh"
          :loading="refreshing"
          @click="() => loadCatalog(true)"
          class="refresh-btn"
        >
          重新同步 Skill 库
        </el-button>
      </div>
    </div>

    <!-- 指标卡片统计网格 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">总装载技能</span>
          <el-icon class="stat-icon"><CollectionTag /></el-icon>
        </div>
        <div class="stat-value">{{ totalSkills }}</div>
        <div class="stat-desc">5 大智能体全阶段覆盖</div>
      </div>

      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">问财专属查询技能</span>
          <el-icon class="stat-icon"><Search /></el-icon>
        </div>
        <div class="stat-value highlight">{{ iwencaiSkillsCount }}</div>
        <div class="stat-desc">Stage 1 自然语言问答指令集</div>
      </div>

      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">投研与写作规范技能</span>
          <el-icon class="stat-icon"><Reading /></el-icon>
        </div>
        <div class="stat-value">{{ methodologySkillsCount }}</div>
        <div class="stat-desc">解读、图表、撰写与融合标准</div>
      </div>

      <div class="stat-card">
        <div class="stat-header">
          <span class="stat-label">人机协同支持</span>
          <el-icon class="stat-icon"><CircleCheck /></el-icon>
        </div>
        <div class="stat-value">100%</div>
        <div class="stat-desc">全阶段支持人工审核与干预</div>
      </div>
    </div>

    <!-- 筛选与搜索控制栏 -->
    <div class="filter-toolbar">
      <!-- 智能体阶段标签切换 -->
      <div class="stage-tabs">
        <button
          class="stage-tab-btn"
          :class="{ active: activeStageFilter === 'all' }"
          @click="activeStageFilter = 'all'"
        >
          全部智能体 ({{ totalSkills }})
        </button>
        <button
          v-for="agent in catalog?.agents || []"
          :key="agent.stage_id"
          class="stage-tab-btn"
          :class="{ active: activeStageFilter === agent.stage_id }"
          @click="activeStageFilter = agent.stage_id"
        >
          Stage {{ agent.stage_num }}: {{ agent.agent_name }} ({{ agent.skills_count }})
        </button>
      </div>

      <!-- 搜索与分类次级过滤 -->
      <div class="filter-controls-row">
        <div class="search-box">
          <el-input
            v-model="searchQuery"
            placeholder="搜索技能名称、Skill ID、关键词或功能描述..."
            :prefix-icon="Search"
            clearable
            class="search-input"
          />
        </div>

        <div class="category-chips" v-if="categories.length > 0">
          <span class="category-label">分类筛选:</span>
          <el-tag
            :effect="activeCategory === 'all' ? 'dark' : 'plain'"
            class="chip-item"
            @click="activeCategory = 'all'"
          >
            全部
          </el-tag>
          <el-tag
            v-for="cat in categories"
            :key="cat"
            :effect="activeCategory === cat ? 'dark' : 'plain'"
            class="chip-item"
            @click="activeCategory = cat"
          >
            {{ cat }}
          </el-tag>
        </div>
      </div>
    </div>

    <!-- 搜索结果提示条 -->
    <div
      v-if="searchQuery || activeCategory !== 'all' || activeStageFilter !== 'all'"
      class="filter-summary-bar"
    >
      <span>
        已匹配到 <strong>{{ totalFilteredSkills }}</strong> 项符合条件的技能
      </span>
      <el-button
        link
        type="primary"
        @click="
          () => {
            searchQuery = ''
            activeCategory = 'all'
            activeStageFilter = 'all'
          }
        "
      >
        重置筛选
      </el-button>
    </div>

    <!-- 各智能体拥有的 Skill 分开展示核心网格 -->
    <div class="agents-container">
      <div
        v-for="group in filteredGroups"
        :key="group.stage_id"
        class="agent-section-card"
        v-show="group.skills.length > 0 || (!searchQuery && activeCategory === 'all')"
      >
        <!-- 智能体分组头部标题区 -->
        <div class="agent-section-header">
          <div class="agent-header-left">
            <span class="stage-badge">Stage {{ group.stage_num }}</span>
            <div class="agent-title-wrap">
              <h2 class="agent-name">{{ group.agent_name }}</h2>
              <span class="agent-role-tag">{{ group.agent_role }}</span>
            </div>
            <span class="skills-count-pill">{{ group.skills.length }} 项专业技能</span>
          </div>

          <div class="agent-header-right">
            <p class="agent-desc">
              {{ STAGE_META[group.stage_id]?.desc || group.description }}
            </p>
          </div>
        </div>

        <!-- 当前智能体拥有的 Skill 卡片网格 -->
        <div v-if="group.skills.length > 0" class="skills-grid">
          <div
            v-for="skill in group.skills"
            :key="skill.id"
            class="skill-card"
            @click="() => openSkillDetail(skill, group)"
          >
            <!-- 卡片头部：标题与分类标签 -->
            <div class="skill-card-top">
              <h3 class="skill-name" :title="skill.name">{{ skill.name }}</h3>
              <el-tag
                v-if="skill.category"
                size="small"
                effect="plain"
                class="skill-category-tag"
              >
                {{ skill.category }}
              </el-tag>
            </div>

            <!-- 卡片编码与来源 -->
            <div class="skill-meta-row">
              <span class="skill-id-badge">ID: {{ skill.id }}</span>
              <span v-if="skill.source" class="skill-source-badge">{{ skill.source }}</span>
            </div>

            <!-- 技能描述 -->
            <p class="skill-desc" :title="skill.description">
              {{ skill.description }}
            </p>

            <!-- 领域关键词与查看行动栏 -->
            <div class="skill-card-footer">
              <div class="skill-tags">
                <span v-for="tag in (skill.domains || []).slice(0, 3)" :key="tag" class="domain-tag">
                  {{ tag }}
                </span>
                <span v-if="(skill.domains || []).length > 3" class="domain-tag-more">
                  +{{ skill.domains!.length - 3 }}
                </span>
              </div>

              <button class="view-spec-btn" @click.stop="() => openSkillDetail(skill, group)">
                <span>查看规范</span>
                <el-icon><ArrowRight /></el-icon>
              </button>
            </div>
          </div>
        </div>

        <!-- 当前智能体在筛选下无匹配时 -->
        <div v-else class="agent-empty-skills">
          <el-icon :size="24"><InfoFilled /></el-icon>
          <span>该智能体下暂无匹配「{{ searchQuery }}」的技能项</span>
        </div>
      </div>

      <!-- 全局无匹配状态 -->
      <div v-if="totalFilteredSkills === 0" class="global-empty-state">
        <el-icon :size="48" class="empty-icon"><InfoFilled /></el-icon>
        <h3>未找到匹配的问财 Skill</h3>
        <p>请尝试减少筛选条件或调整搜索关键词</p>
        <el-button
          type="primary"
          @click="
            () => {
              searchQuery = ''
              activeCategory = 'all'
              activeStageFilter = 'all'
            }
          "
        >
          查看全部 66 项技能
        </el-button>
      </div>
    </div>

    <!-- 技能详情抽屉（规范查看） -->
    <el-drawer
      v-model="detailDrawerVisible"
      size="640px"
      :show-close="true"
      destroy-on-close
      class="skill-detail-drawer"
    >
      <template #header>
        <div class="drawer-header-content">
          <div class="drawer-title-row">
            <span class="drawer-stage-badge">
              Stage {{ selectedAgent?.stage_num }}: {{ selectedAgent?.agent_name }}
            </span>
            <el-tag v-if="selectedSkill?.category" size="small" effect="plain">
              {{ selectedSkill?.category }}
            </el-tag>
          </div>
          <h2 class="drawer-skill-title">{{ selectedSkill?.name }}</h2>
          <span class="drawer-skill-id">ID: {{ selectedSkill?.id }}</span>
        </div>
      </template>

      <div class="drawer-body" v-loading="detailLoading">
        <!-- 基础元属性卡片 -->
        <div class="skill-specs-box">
          <div class="spec-item">
            <span class="spec-label">所属智能体:</span>
            <span class="spec-value">{{ selectedAgent?.agent_name }} ({{ selectedAgent?.agent_role }})</span>
          </div>
          <div class="spec-item" v-if="selectedSkill?.source">
            <span class="spec-label">技能体系来源:</span>
            <span class="spec-value">{{ selectedSkill.source }}</span>
          </div>
          <div class="spec-item" v-if="selectedSkill?.adaptation">
            <span class="spec-label">适配与执行:</span>
            <span class="spec-value">{{ selectedSkill.adaptation }}</span>
          </div>
          <div class="spec-item" v-if="selectedSkill?.domains?.length">
            <span class="spec-label">覆盖领域:</span>
            <div class="spec-tags">
              <el-tag
                v-for="d in selectedSkill.domains"
                :key="d"
                size="small"
                effect="plain"
                class="spec-tag"
              >
                {{ d }}
              </el-tag>
            </div>
          </div>
          <div class="spec-item" v-if="selectedSkill?.keywords?.length">
            <span class="spec-label">检索关键词:</span>
            <div class="spec-tags">
              <el-tag
                v-for="k in selectedSkill.keywords"
                :key="k"
                size="small"
                type="info"
                class="spec-tag"
              >
                {{ k }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 描述与功能定位 -->
        <div class="drawer-section">
          <h4 class="section-title">功能定位与执行机制</h4>
          <p class="section-desc-text">{{ selectedSkill?.description }}</p>
        </div>

        <!-- 详细文档 / 投研指令规范 -->
        <div class="drawer-section">
          <div class="section-title-bar">
            <h4 class="section-title">技能详细规范与执行指令</h4>
            <div class="section-actions">
              <el-radio-group v-model="activeDetailTab" size="small">
                <el-radio-button label="doc">格式化规范</el-radio-button>
                <el-radio-button label="raw">原始定义</el-radio-button>
              </el-radio-group>
              <el-button size="small" :icon="CopyDocument" @click="copySkillContent">
                复制内容
              </el-button>
            </div>
          </div>

          <!-- Markdown 格式化规范内容 -->
          <div
            v-if="activeDetailTab === 'doc'"
            class="markdown-container"
            v-html="renderedDetailHtml"
          ></div>

          <!-- 原始 YAML/Markdown -->
          <div v-else class="raw-code-box">
            <pre>{{ selectedSkill?.full_doc || selectedSkill?.description }}</pre>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.skills-hub-view {
  max-width: 1380px;
  margin: 0 auto;
  padding: 24px 20px 60px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  color: #1e293b;
}

/* ---------- 英雄区品牌横幅 ---------- */
.hub-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 28px 32px;
  background: linear-gradient(135deg, #0a2540 0%, #1e3a8a 100%);
  border-radius: 12px;
  color: #ffffff;
  box-shadow: 0 6px 20px rgba(10, 37, 64, 0.15);
  margin-bottom: 24px;
}

.hero-left {
  max-width: 860px;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.25);
  border-radius: 16px;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.5px;
  margin-bottom: 12px;
  color: #f8fafc;
}

.hero-title {
  margin: 0 0 10px;
  font-size: 26px;
  font-weight: 700;
  letter-spacing: 0.8px;
  color: #ffffff;
}

.hero-subtitle {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.85);
}

.hero-actions {
  margin-top: 4px;
}

.refresh-btn {
  background-color: #d4af37;
  border-color: #d4af37;
  color: #0a2540;
  font-weight: 600;
}
.refresh-btn:hover {
  background-color: #e5c158;
  border-color: #e5c158;
}

/* ---------- 统计指标网格 ---------- */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 18px 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.stat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.stat-label {
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
}

.stat-icon {
  font-size: 18px;
  color: #94a3b8;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.2;
}

.stat-value.highlight {
  color: #1e3a8a;
}

.stat-desc {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 6px;
}

/* ---------- 筛选控制栏 ---------- */
.filter-toolbar {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

.stage-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
  border-bottom: 1px solid #f1f5f9;
  padding-bottom: 14px;
}

.stage-tab-btn {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s ease;
}

.stage-tab-btn:hover {
  background: #e2e8f0;
  color: #0f172a;
}

.stage-tab-btn.active {
  background: #0a2540;
  border-color: #0a2540;
  color: #ffffff;
  font-weight: 600;
}

.filter-controls-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.search-box {
  width: 380px;
  min-width: 280px;
}

.category-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.category-label {
  font-size: 13px;
  color: #64748b;
  margin-right: 4px;
}

.chip-item {
  cursor: pointer;
  border-radius: 4px;
}

.filter-summary-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: #f1f5f9;
  border-radius: 6px;
  font-size: 13px;
  color: #475569;
  margin-bottom: 20px;
}

/* ---------- 智能体分组卡片容器 ---------- */
.agents-container {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.agent-section-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.agent-section-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding-bottom: 16px;
  margin-bottom: 20px;
  border-bottom: 1px solid #f1f5f9;
  gap: 20px;
}

.agent-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.stage-badge {
  background: #0a2540;
  color: #ffffff;
  font-size: 12px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 4px;
  letter-spacing: 0.5px;
}

.agent-title-wrap {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.agent-name {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.agent-role-tag {
  font-size: 13px;
  color: #64748b;
  font-weight: 500;
}

.skills-count-pill {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  color: #334155;
  font-size: 12px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 12px;
}

.agent-header-right {
  max-width: 580px;
  text-align: right;
}

.agent-desc {
  margin: 0;
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

/* ---------- 技能卡片网格 ---------- */
.skills-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.skill-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  cursor: pointer;
  transition: all 0.2s ease;
  min-height: 175px;
}

.skill-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 4px 14px rgba(30, 58, 138, 0.08);
  transform: translateY(-2px);
}

.skill-card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
}

.skill-name {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-category-tag {
  font-size: 11px;
  flex-shrink: 0;
}

.skill-meta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.skill-id-badge {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  color: #475569;
  background: #f1f5f9;
  padding: 2px 6px;
  border-radius: 4px;
}

.skill-source-badge {
  font-size: 11px;
  color: #0369a1;
  background: #e0f2fe;
  padding: 1px 6px;
  border-radius: 4px;
}

.skill-desc {
  margin: 0 0 12px;
  font-size: 13px;
  color: #475569;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  flex-grow: 1;
}

.skill-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid #f8fafc;
  padding-top: 10px;
  margin-top: auto;
}

.skill-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.domain-tag {
  font-size: 11px;
  background: #f8fafc;
  color: #64748b;
  border: 1px solid #e2e8f0;
  padding: 1px 6px;
  border-radius: 4px;
}

.domain-tag-more {
  font-size: 11px;
  color: #94a3b8;
  padding: 1px 2px;
}

.view-spec-btn {
  background: transparent;
  border: none;
  color: #1e3a8a;
  font-size: 12px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  transition: background-color 0.15s ease;
}

.view-spec-btn:hover {
  background-color: #eff6ff;
  color: #0c4a6e;
}

.agent-empty-skills {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px;
  color: #94a3b8;
  font-size: 14px;
}

.global-empty-state {
  text-align: center;
  padding: 60px 20px;
  background: #ffffff;
  border-radius: 12px;
  border: 1px dashed #cbd5e1;
}

.empty-icon {
  color: #cbd5e1;
  margin-bottom: 12px;
}

.global-empty-state h3 {
  margin: 0 0 8px;
  font-size: 16px;
  color: #334155;
}

.global-empty-state p {
  margin: 0 0 16px;
  font-size: 13px;
  color: #64748b;
}

/* ---------- 技能详情抽屉 ---------- */
.drawer-header-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.drawer-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.drawer-stage-badge {
  font-size: 12px;
  font-weight: 600;
  color: #1e3a8a;
}

.drawer-skill-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
}

.drawer-skill-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  color: #64748b;
}

.drawer-body {
  padding: 0 4px;
}

.skill-specs-box {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 20px;
}

.spec-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
}

.spec-item:last-child {
  margin-bottom: 0;
}

.spec-label {
  width: 90px;
  flex-shrink: 0;
  color: #64748b;
  font-weight: 500;
}

.spec-value {
  color: #0f172a;
  font-weight: 500;
}

.spec-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.spec-tag {
  font-size: 12px;
}

.drawer-section {
  margin-bottom: 24px;
}

.section-title-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.section-title {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.section-desc-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: #334155;
  background: #fdfdfd;
  padding: 10px 12px;
  border-left: 3px solid #0a2540;
  border-radius: 0 4px 4px 0;
}

.section-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.markdown-container {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 18px 20px;
  font-size: 14px;
  line-height: 1.7;
  color: #1e293b;
}

.markdown-container :deep(h1),
.markdown-container :deep(h2),
.markdown-container :deep(h3) {
  color: #0a2540;
  margin-top: 18px;
  margin-bottom: 8px;
  font-weight: 600;
}

.markdown-container :deep(h1) {
  font-size: 18px;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 6px;
}

.markdown-container :deep(h2) {
  font-size: 16px;
}

.markdown-container :deep(h3) {
  font-size: 14px;
}

.markdown-container :deep(p) {
  margin: 8px 0;
}

.markdown-container :deep(ul),
.markdown-container :deep(ol) {
  padding-left: 20px;
  margin: 8px 0;
}

.markdown-container :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: #f1f5f9;
  color: #0f172a;
  padding: 2px 5px;
  border-radius: 4px;
  font-size: 12px;
}

.markdown-container :deep(pre) {
  background: #0f172a;
  color: #f8fafc;
  padding: 12px 14px;
  border-radius: 6px;
  overflow-x: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.markdown-container :deep(pre code) {
  background: transparent;
  color: inherit;
  padding: 0;
}

.markdown-container :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 13px;
}

.markdown-container :deep(th),
.markdown-container :deep(td) {
  border: 1px solid #cbd5e1;
  padding: 6px 10px;
  text-align: left;
}

.markdown-container :deep(th) {
  background: #f1f5f9;
  font-weight: 600;
}

.raw-code-box {
  background: #0f172a;
  color: #f8fafc;
  border-radius: 8px;
  padding: 14px 16px;
  max-height: 480px;
  overflow-y: auto;
}

.raw-code-box pre {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 响应式调整 */
@media (max-width: 992px) {
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .agent-section-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .agent-header-right {
    text-align: left;
  }
}

@media (max-width: 640px) {
  .hub-hero {
    flex-direction: column;
    gap: 16px;
  }
  .stats-grid {
    grid-template-columns: 1fr;
  }
  .skills-grid {
    grid-template-columns: 1fr;
  }
}
</style>
