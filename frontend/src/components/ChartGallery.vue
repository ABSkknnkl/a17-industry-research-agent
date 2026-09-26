<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { ChartOption, ChartSpec } from '../api/types'

/** chart_generate 阶段 data.chart_specs 的宽松类型（与后端 ChartSpec 对齐，仅取渲染所需字段） */
type ChartSpecLoose = Partial<ChartSpec> & { svg_uri?: string | null }

const props = defineProps<{
  specs: ChartSpecLoose[]
  runId?: string
}>()

/** 与后端 presentation.CHART_TYPE_LABELS 对齐 */
const CHART_TYPE_LABELS: Record<string, string> = {
  line: '折线图',
  bar: '柱状图',
  comparison_bar: '涨跌幅对比图',
  pie: '饼图',
  radar: '雷达图',
  industry_chain: '产业链图',
  combo: '双轴组合图',
  area: '面积图',
  scatter: '散点图',
  bubble: '气泡图',
  heatmap: '热力图',
  boxplot: '箱线图',
  treemap: '矩形树图',
}

const usable = computed(() =>
  props.specs.filter((spec) => {
    if (!spec) return false
    if (spec.render_mode === 'generated_image') return Boolean(spec.image_uri)
    return Boolean(spec.option)
  })
)

// ---- 图表布局分类（与后端 display_size 契约一致）----
/** 数据点达到该数量即视为「长图表」：独占一整行（full），否则每行 2 个（half）。 */
const FULL_MIN_POINTS = 10

type DisplaySize = 'full' | 'half'

/** 后端已下发 display_size 时直接采用；旧产物/缺字段时按 option 数据量兜底估算。 */
function estimateDisplaySize(spec: ChartSpecLoose): DisplaySize {
  if (spec.chart_type === 'industry_chain') return 'full'
  const opt = spec.option
  const lengths: number[] = []
  const rawXAxis = opt?.xAxis
  if (Array.isArray(rawXAxis)) {
    for (const axis of rawXAxis) {
      if (axis && Array.isArray((axis as { data?: unknown[] }).data)) {
        lengths.push((axis as { data: unknown[] }).data.length)
      }
    }
  } else if (rawXAxis && Array.isArray((rawXAxis as { data?: unknown[] }).data)) {
    lengths.push((rawXAxis as { data: unknown[] }).data.length)
  }
  for (const series of Array.isArray(opt?.series)
    ? (opt.series as Array<Record<string, unknown>>)
    : []) {
    if (series && Array.isArray(series.data)) lengths.push((series.data as unknown[]).length)
  }
  return Math.max(0, ...lengths) >= FULL_MIN_POINTS ? 'full' : 'half'
}

function displaySizeOf(spec: ChartSpecLoose): DisplaySize {
  if (spec.display_size === 'full' || spec.display_size === 'half') return spec.display_size
  return estimateDisplaySize(spec)
}

/** 全宽长图表在前，半宽小图表在后。 */
const ordered = computed(() =>
  [...usable.value].sort((a, b) => {
    const rank = (spec: ChartSpecLoose): number => (displaySizeOf(spec) === 'full' ? 0 : 1)
    return rank(a) - rank(b)
  })
)

/** 渲染用 option：剥离绘图区内的纯文本注释（挪到卡片下方 footnotes），统一 category 轴标签采样，并对拓扑关系图进行坐标与样式加固。 */
function sanitizedOption(spec: ChartSpecLoose, isPreview = false): ChartOption | null {
  if (!spec.option) return null
  const graphic = Array.isArray(spec.option.graphic) ? spec.option.graphic : []
  const textGraphics = graphic.filter((g) => g && g.type === 'text')
  const option =
    textGraphics.length === 0
      ? (JSON.parse(JSON.stringify(spec.option)) as ChartOption)
      : stripTextGraphics(spec.option)
  uniformCategoryAxisLabels(option)
  sanitizeAxes(option)
  sanitizeTooltip(option)
  sanitizeGraphOption(option, spec, isPreview)
  sanitizeScatterBubbleOption(option, spec, isPreview)
  return option
}

function sanitizeTooltip(option: ChartOption): void {
  if (!option.tooltip || typeof option.tooltip !== 'object') {
    return
  }
  const tip = option.tooltip as Record<string, unknown>
  if (!tip.valueFormatter) {
    tip.valueFormatter = (val: unknown) => {
      if (typeof val === 'number') {
        if (Number.isInteger(val)) return String(val)
        return String(Number(val.toFixed(2)))
      }
      return val as string
    }
  }
}

/** 常见英文字段名 -> 中文规范业务标签字典 */
const TECHNICAL_NAME_MAP: Record<string, string> = {
  close_price: '收盘价',
  change_pct: '涨跌幅',
  trade_volume: '成交量',
  volume: '成交量',
  turnover: '成交额',
  open_price: '开盘价',
  high_price: '最高价',
  low_price: '最低价',
  debt_ratio: '资产负债率',
  parent_net_profit: '归母净利润',
  revenue: '营业收入',
  net_profit: '净利润',
  operating_cash_flow: '经营活动现金流',
  gross_margin: '毛利率',
  net_margin: '净利率',
}

function hasLargeOrDecimalValues(option: ChartOption): boolean {
  const series = Array.isArray(option.series) ? option.series : option.series ? [option.series] : []
  for (const s of series) {
    if (!s || !Array.isArray(s.data)) continue
    for (const val of s.data) {
      const num = typeof val === 'number' ? val : Array.isArray(val) ? Number(val[1]) : Number(val)
      if (!Number.isNaN(num) && (Math.abs(num) >= 10000 || (Math.abs(num) > 0 && Math.abs(num) < 0.01))) {
        return true
      }
    }
  }
  return false
}

function formatAxisValue(val: number | string): string {
  const num = Number(val)
  if (Number.isNaN(num)) return String(val)
  const abs = Math.abs(num)
  if (abs >= 1e8) return `${Number((num / 1e8).toFixed(1))}亿`
  if (abs >= 1e4) return `${Number((num / 1e4).toFixed(1))}万`
  if (abs >= 1000) return `${Math.round(num)}`
  if (abs >= 1) return `${Number(num.toFixed(2))}`
  if (abs > 0) return `${Number(num.toFixed(3))}`
  return '0'
}

function sanitizeAxes(option: ChartOption): void {
  const needsScaleDefense = hasLargeOrDecimalValues(option)
  const allAxes = [
    ...(Array.isArray(option.xAxis) ? option.xAxis : option.xAxis ? [option.xAxis] : []),
    ...(Array.isArray(option.yAxis) ? option.yAxis : option.yAxis ? [option.yAxis] : []),
  ] as Record<string, unknown>[]

  for (const axis of allAxes) {
    if (!axis || typeof axis !== 'object') continue
    const isCategory = axis.type === 'category' || (!axis.type && Array.isArray(axis.data))
    if (isCategory && Array.isArray(axis.data)) {
      let changed = false
      const mapped = axis.data.map((item) => {
        if (typeof item === 'string') {
          const trimmed = item.trim()
          const clean = TECHNICAL_NAME_MAP[trimmed] ?? TECHNICAL_NAME_MAP[trimmed.toLowerCase()]
          if (clean && clean !== trimmed) {
            changed = true
            return clean
          }
        }
        return item
      })
      const nonNull = mapped.filter((x) => x !== null && x !== undefined && x !== '')
      if (mapped.length > 1 && nonNull.length === mapped.length && new Set(nonNull).size === 1) {
        axis.data = mapped.map((val, idx) => `${val} #${idx + 1}`)
      } else if (changed) {
        axis.data = mapped
      }
    } else if (needsScaleDefense && (!axis.type || axis.type === 'value')) {
      const axisLabel = (axis.axisLabel ??= {}) as Record<string, unknown>
      if (!axisLabel.formatter) {
        axisLabel.formatter = formatAxisValue
      }
      if (axis.splitNumber === undefined) {
        axis.splitNumber = 4
      }
    }
  }

  const seriesList = (Array.isArray(option.series) ? option.series : option.series ? [option.series] : []) as Record<string, unknown>[]
  for (const s of seriesList) {
    if (s && typeof s.name === 'string') {
      const trimmed = s.name.trim()
      const clean = TECHNICAL_NAME_MAP[trimmed] ?? TECHNICAL_NAME_MAP[trimmed.toLowerCase()]
      if (clean) s.name = clean
    }
  }

  if (option.legend && typeof option.legend === 'object') {
    const leg = option.legend as Record<string, unknown>
    if (Array.isArray(leg.data)) {
      leg.data = leg.data.map((item) => {
        if (typeof item === 'string') {
          const trimmed = item.trim()
          return TECHNICAL_NAME_MAP[trimmed] ?? TECHNICAL_NAME_MAP[trimmed.toLowerCase()] ?? trimmed
        }
        return item
      })
    }
  }
}

/** 移除绘图区内的纯文本注释，保留参考线/遮蔽等非文字 graphic。 */
function stripTextGraphics(option: Record<string, unknown>): ChartOption {
  const cleaned = JSON.parse(JSON.stringify(option)) as Record<string, unknown>
  const graphic = Array.isArray(option.graphic) ? option.graphic : []
  const kept = graphic.filter((g) => !g || g.type !== 'text')
  if (kept.length > 0) cleaned.graphic = kept
  else delete cleaned.graphic
  return cleaned as ChartOption
}

/** 常见股票代码反查字典（重点赛道代表标的兜底映射） */
const TICKER_NAME_MAP: Record<string, string> = {
  '001232.SZ': '天振股份',
  '002243.SZ': '力合科创',
  '300124.SZ': '汇川技术',
  '300474.SZ': '景嘉微',
  '300697.SZ': '电连技术',
  '301237.SZ': '和顺科技',
  '600118.SH': '中国卫星',
  '600879.SH': '航天电子',
  '600150.SH': '中国船舶',
  '600760.SH': '中航沈飞',
  '002025.SZ': '航天电器',
  '002384.SZ': '东山精密',
  '300327.SZ': '中来股份',
  '600456.SH': '宝钛股份',
  '601678.SH': '滨化股份',
  '688002.SH': '睿创微纳',
  '688126.SH': '沪硅产业',
  '688568.SH': '中科星图',
  '688220.SH': '翱捷科技',
  '688244.SH': '永信至诚',
  '688327.SH': '云从科技',
  '688787.SH': '海天瑞声',
}

function resolveEntityDisplayName(rawName: string): string {
  const trimmed = rawName.trim()
  if (TICKER_NAME_MAP[trimmed]) return TICKER_NAME_MAP[trimmed]
  const upper = trimmed.toUpperCase()
  if (TICKER_NAME_MAP[upper]) return TICKER_NAME_MAP[upper]
  const noSuffix = upper.replace(/\.(SZ|SH|BJ|HK|US)$/, '')
  for (const [k, v] of Object.entries(TICKER_NAME_MAP)) {
    if (k.startsWith(noSuffix)) return v
  }
  return trimmed
}

/** 与后端 uniform_category_axis_labels 相同的采样规则：卡片/预览/报告三处标签一致；小数据图表不做改动。 */
const CATEGORY_MAX_LABELS = 12

function uniformCategoryAxisLabels(option: ChartOption): void {
  const rawAxes = option.xAxis as unknown
  const axes = Array.isArray(rawAxes) ? rawAxes : [rawAxes]
  for (const rawAxis of axes) {
    if (!rawAxis || typeof rawAxis !== 'object') continue
    const axis = rawAxis as Record<string, unknown>
    if (String(axis.type ?? 'category') !== 'category') continue
    const data = axis.data
    if (!Array.isArray(data) || data.length === 0) continue

    const hasLongLabels = data.some(
      (d) => typeof d === 'string' && (d.length > 7 || /^\d{4}[-/.]\d{1,2}/.test(d))
    )
    const maxLabels = hasLongLabels ? 7 : CATEGORY_MAX_LABELS

    if (data.length > maxLabels) {
      const axisLabel = ((axis as Record<string, Record<string, unknown>>).axisLabel ??= {})
      axisLabel.hideOverlap = true
      axisLabel.interval = Math.ceil(data.length / maxLabels) - 1
      if (hasLongLabels && axisLabel.rotate === undefined) {
        axisLabel.rotate = 15
      }
    }
  }
}

/** 产业链拓扑关系图 (industry_chain / graph) 自动补全三段式坐标与出版级视觉样式 */
function sanitizeGraphOption(option: ChartOption, spec: ChartSpecLoose, isPreview = false): void {
  const isGraph =
    spec.chart_type === 'industry_chain' ||
    (Array.isArray(option.series) &&

      option.series.some((s: unknown) => s && (s as Record<string, unknown>).type === 'graph')) ||
    (option.series && (option.series as Record<string, unknown>).type === 'graph')

  if (!isGraph) return

  const seriesList = (
    Array.isArray(option.series) ? option.series : [option.series]
  ) as Record<string, unknown>[]

  for (const s of seriesList) {
    if (!s || s.type !== 'graph') continue
    const rawNodes = Array.isArray(s.data) ? (s.data as Record<string, unknown>[]) : []
    if (rawNodes.length === 0) continue

    const hasCoordinates = rawNodes.every(
      (n) =>
        typeof n === 'object' &&
        n !== null &&
        typeof n.x === 'number' &&
        typeof n.y === 'number' &&
        !Number.isNaN(n.x) &&
        !Number.isNaN(n.y)
    )

    const stageMap = {
      upstream: {
        name: '上游：基础支撑与核心供给',
        color: '#12b76a',
        bg: '#f0fdf4',
        border: '#12b76a',
        text: '#027a48',
        x: 180,
      },
      midstream: {
        name: '中游：核心产品与系统集成',
        color: '#155eef',
        bg: '#eff6ff',
        border: '#155eef',
        text: '#175cd3',
        x: 500,
      },
      downstream: {
        name: '下游：场景应用与商业化生态',
        color: '#f04438',
        bg: '#fef3f2',
        border: '#f04438',
        text: '#b42318',
        x: 820,
      },
    }

    const classifyNode = (
      node: Record<string, unknown>,
      idx: number,
      total: number
    ): 'upstream' | 'midstream' | 'downstream' => {
      const cat = String(node.category ?? node.stage ?? '').toLowerCase()
      if (
        cat.includes('上游') ||
        cat.includes('upstream') ||
        cat.includes('原料') ||
        cat.includes('资源') ||
        cat === '0'
      ) {
        return 'upstream'
      }
      if (
        cat.includes('下游') ||
        cat.includes('downstream') ||
        cat.includes('终端') ||
        cat.includes('整车') ||
        cat.includes('应用') ||
        cat === '2'
      ) {
        return 'downstream'
      }
      if (
        cat.includes('中游') ||
        cat.includes('midstream') ||
        cat.includes('制造') ||
        cat.includes('核心') ||
        cat.includes('器件') ||
        cat === '1'
      ) {
        return 'midstream'
      }
      if (idx < Math.ceil(total / 3)) return 'upstream'
      if (idx >= Math.floor((total * 2) / 3)) return 'downstream'
      return 'midstream'
    }

    if (!hasCoordinates) {
      const groups: Record<'upstream' | 'midstream' | 'downstream', Record<string, unknown>[]> = {
        upstream: [],
        midstream: [],
        downstream: [],
      }
      rawNodes.forEach((n, i) => {
        const g = classifyNode(n, i, rawNodes.length)
        groups[g].push(n)
      })

      const newNodes: Record<string, unknown>[] = []
      // 1. 各环节顶部标题胶囊节点
      for (const [key, conf] of Object.entries(stageMap)) {
        newNodes.push({
          id: `__hdr_${key}__`,
          name: conf.name,
          x: conf.x,
          y: 40,
          symbol: 'roundRect',
          symbolSize: [210, 32],
          itemStyle: {
            color: conf.color,
            borderColor: conf.color,
            shadowColor: 'rgba(0,0,0,0.06)',
            shadowBlur: 4,
          },
          label: {
            show: true,
            position: 'inside',
            color: '#ffffff',
            fontWeight: 700,
            fontSize: 11.5,
          },
          tooltip: { show: false },
          silent: true,
        })
      }

      // 2. 各环节所属实体卡片节点
      for (const [key, conf] of Object.entries(stageMap)) {
        const gNodes = groups[key as 'upstream' | 'midstream' | 'downstream']
        const count = gNodes.length
        if (count === 0) continue

        const stepY = count === 1 ? 0 : Math.min(64, 340 / (count - 1))
        const startY = count === 1 ? 240 : 105 + (340 - (count - 1) * stepY) / 2

        gNodes.forEach((node, idx) => {
          const y = startY + idx * stepY
          const rawNodeName = String(node.name || `节点${idx + 1}`)
          const nodeName = resolveEntityDisplayName(rawNodeName)
          const margin = String(node.margin || '')

          newNodes.push({
            ...node,
            name: nodeName,
            x: conf.x,
            y,
            symbol: 'roundRect',
            symbolSize: [180, 44],
            itemStyle: {
              color: conf.bg,
              borderColor: conf.border,
              borderWidth: 1.5,
              shadowColor: 'rgba(16, 24, 40, 0.05)',
              shadowBlur: 6,
            },
            label: {
              show: true,
              position: 'inside',
              formatter: () => {
                return margin ? `{name|${nodeName}}\n{margin|${margin}}` : `{name|${nodeName}}`
              },
              rich: {
                name: {
                  fontSize: 12,
                  fontWeight: 600,
                  color: '#101828',
                  lineHeight: 18,
                  align: 'center',
                },
                margin: {
                  fontSize: 10,
                  fontWeight: 600,
                  color: conf.text,
                  lineHeight: 14,
                  align: 'center',
                },
              },
            },
          })
        })
      }

      s.data = newNodes
      s.layout = 'none'

      // 3. 构建整齐、平行、无交叉的产业链拓扑连线（解决交叉乱射问题）
      const cleanLinks: Record<string, unknown>[] = []

      // 顶层三段式宏观传导箭头：上游 -> 中游 -> 下游
      cleanLinks.push({
        source: '__hdr_upstream__',
        target: '__hdr_midstream__',
        lineStyle: {
          color: '#155eef',
          width: 2.5,
          curveness: 0,
        },
      })
      cleanLinks.push({
        source: '__hdr_midstream__',
        target: '__hdr_downstream__',
        lineStyle: {
          color: '#f04438',
          width: 2.5,
          curveness: 0,
        },
      })

      // 实体卡片层：按排水平行流转对齐（绝不交叉乱射，保持完全水平平行）
      const upCards = groups.upstream
      const midCards = groups.midstream
      const downCards = groups.downstream

      const maxPairs1 = Math.min(upCards.length, midCards.length)
      for (let i = 0; i < maxPairs1; i++) {
        const uId = String(upCards[i].id || upCards[i].name || `upstream_${i}`)
        const mId = String(midCards[i].id || midCards[i].name || `midstream_${i}`)
        cleanLinks.push({
          source: uId,
          target: mId,
          lineStyle: {
            color: '#cbd5e1',
            width: 1.5,
            curveness: 0,
            type: 'dashed',
          },
        })
      }

      const maxPairs2 = Math.min(midCards.length, downCards.length)
      for (let i = 0; i < maxPairs2; i++) {
        const mId = String(midCards[i].id || midCards[i].name || `midstream_${i}`)
        const dId = String(downCards[i].id || downCards[i].name || `downstream_${i}`)
        cleanLinks.push({
          source: mId,
          target: dId,
          lineStyle: {
            color: '#cbd5e1',
            width: 1.5,
            curveness: 0,
            type: 'dashed',
          },
        })
      }

      s.links = cleanLinks
    }

    s.roam = isPreview
    s.edgeSymbol = ['circle', 'arrow']
    s.edgeSymbolSize = [3.5, 8]
    s.categories = [{ name: '上游' }, { name: '中游' }, { name: '下游' }]

    // 移除默认 legend 避免其尝试将上中下游当做 series 过滤而隐藏节点
    delete option.legend

    option.tooltip = {
      trigger: 'item',
      backgroundColor: 'rgba(255, 255, 255, 0.96)',
      borderColor: '#eaecf0',
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: '#101828', fontSize: 12 },
      formatter: (params: unknown) => {
        const p = params as {
          dataType?: string
          name?: string
          data?: { silent?: boolean; category?: string; margin?: string }
        }
        if (p.dataType === 'node') {
          if (p.data?.silent) return ''
          const d = p.data || {}
          const cat = d.category || ''
          const nodeDisplay = resolveEntityDisplayName(p.name ?? '')
          const margin = d.margin
            ? `<div style="color:${stageMap[classifyNode(d as Record<string, unknown>, 0, 1)]?.text || '#027a48'};font-weight:600;margin-top:2px;">${d.margin}</div>`
            : ''
          return `<div style="font-weight:700;font-size:13px;margin-bottom:2px;">${nodeDisplay}</div>
                  <div style="color:#667085;">环节: ${cat}</div>
                  ${margin}`
        }
        if (p.dataType === 'edge') {
          const edge = params as { data?: { source?: string; target?: string } }
          const src = resolveEntityDisplayName(edge.data?.source ?? '')
          const tgt = resolveEntityDisplayName(edge.data?.target ?? '')
          return `<div style="color:#475467;">供需流向: ${src} → ${tgt}</div>`
        }
        return ''
      },
    }
  }
}

/** 散点图与气泡图 (scatter / bubble) 坐标自适应、数据格式标准化与象限基准线增强 */
function sanitizeScatterBubbleOption(
  option: ChartOption,
  spec: ChartSpecLoose,
  _isPreview = false
): void {
  const isScatterOrBubble =
    spec.chart_type === 'scatter' ||
    spec.chart_type === 'bubble' ||
    (Array.isArray(option.series) &&
      option.series.some(
        (s: unknown) =>
          s &&
          ((s as Record<string, unknown>).type === 'scatter' ||
            (s as Record<string, unknown>).type === 'bubble')
      )) ||
    (option.series &&
      ((option.series as Record<string, unknown>).type === 'scatter' ||
        (option.series as Record<string, unknown>).type === 'bubble'))

  if (!isScatterOrBubble) return

  const seriesList = (
    Array.isArray(option.series) ? option.series : [option.series]
  ) as Record<string, unknown>[]

  // 1. 坐标轴尺度自适应保护：启用 scale: true 避免强制从 0 开始拉偏视野
  const rawXAxis = option.xAxis as unknown
  const xAxes = Array.isArray(rawXAxis) ? rawXAxis : [rawXAxis]
  for (const ax of xAxes) {
    if (ax && typeof ax === 'object') {
      const a = ax as Record<string, unknown>
      if (!a.type || a.type === 'value') {
        a.scale = true
        const splitLine = ((a.splitLine ??= {}) as Record<string, unknown>)
        splitLine.show = true
        splitLine.lineStyle = { type: 'dashed', color: '#eaecf0' }
      }
    }
  }

  const rawYAxis = option.yAxis as unknown
  const yAxes = Array.isArray(rawYAxis) ? rawYAxis : [rawYAxis]
  for (const ax of yAxes) {
    if (ax && typeof ax === 'object') {
      const a = ax as Record<string, unknown>
      if (!a.type || a.type === 'value') {
        a.scale = true
        const splitLine = ((a.splitLine ??= {}) as Record<string, unknown>)
        splitLine.show = true
        splitLine.lineStyle = { type: 'dashed', color: '#eaecf0' }
      }
    }
  }

  const xAxisName = ((xAxes[0] as Record<string, unknown>)?.name as string) || 'X'
  const yAxisName = ((yAxes[0] as Record<string, unknown>)?.name as string) || 'Y'

  // 2. 遍历 series 处理数据映射与气泡大小
  for (const s of seriesList) {
    if (!s || (s.type !== 'scatter' && s.type !== 'bubble')) continue
    const rawData = Array.isArray(s.data) ? s.data : []
    if (rawData.length === 0) continue

    // 收集气泡尺寸维度（用于动态计算归一化半径）
    const sizes: number[] = []
    for (const item of rawData) {
      if (Array.isArray(item)) {
        if (typeof item[0] === 'string' && item.length >= 4) {
          const sz = Number(item[3])
          if (!Number.isNaN(sz)) sizes.push(sz)
        } else if (item.length >= 3 && typeof item[2] === 'number') {
          const sz = Number(item[2])
          if (!Number.isNaN(sz)) sizes.push(sz)
        }
      } else if (typeof item === 'object' && item !== null) {
        const val = (item as Record<string, unknown>).value
        if (Array.isArray(val)) {
          if (typeof val[0] === 'string' && val.length >= 4) {
            const sz = Number(val[3])
            if (!Number.isNaN(sz)) sizes.push(sz)
          } else if (val.length >= 3 && typeof val[2] === 'number') {
            const sz = Number(val[2])
            if (!Number.isNaN(sz)) sizes.push(sz)
          }
        }
      }
    }

    const minSz = sizes.length ? Math.min(...sizes) : 0
    const maxSz = sizes.length ? Math.max(...sizes) : 0
    const spanSz = maxSz - minSz || 1

    const normalizedData: Record<string, unknown>[] = []

    for (let i = 0; i < rawData.length; i++) {
      const item = rawData[i]
      let name = `样本${i + 1}`
      let x = 0
      let y = 0
      let rawSize: number | null = null

      if (Array.isArray(item)) {
        if (typeof item[0] === 'string') {
          name = resolveEntityDisplayName(item[0])
          x = Number(item[1])
          y = Number(item[2])
          if (item.length >= 4 && !Number.isNaN(Number(item[3]))) {
            rawSize = Number(item[3])
          }
        } else {
          x = Number(item[0])
          y = Number(item[1])
          if (item.length >= 3) {
            if (typeof item[2] === 'number') {
              rawSize = Number(item[2])
              if (item.length >= 4 && typeof item[3] === 'string') {
                name = resolveEntityDisplayName(item[3])
              }
            } else if (typeof item[2] === 'string') {
              name = resolveEntityDisplayName(item[2])
            }
          }
        }
      } else if (typeof item === 'object' && item !== null) {
        const obj = item as Record<string, unknown>
        name = resolveEntityDisplayName(String(obj.name || `样本${i + 1}`))
        const val = obj.value
        if (Array.isArray(val)) {
          if (typeof val[0] === 'string') {
            name = resolveEntityDisplayName(val[0])
            x = Number(val[1])
            y = Number(val[2])
            if (val.length >= 4 && !Number.isNaN(Number(val[3]))) {
              rawSize = Number(val[3])
            }
          } else {
            x = Number(val[0])
            y = Number(val[1])
            if (val.length >= 3 && typeof val[2] === 'number') {
              rawSize = Number(val[2])
            }
          }
        } else {
          x = Number(obj.x ?? 0)
          y = Number(obj.y ?? 0)
        }
      }

      if (Number.isNaN(x) || Number.isNaN(y)) continue

      const radius =
        rawSize !== null && sizes.length > 0
          ? Math.round(10 + ((rawSize - minSz) / spanSz) * 16)
          : (spec.chart_type === 'bubble' ? 16 : 12)

      const isTarget = ['茅台', '五粮液', '泸州老窖'].some((k) => name.includes(k))
      const ptColor = isTarget ? '#1B365D' : '#0f766e'

      normalizedData.push({
        name,
        value: [x, y, rawSize ?? radius],
        symbolSize: radius,
        itemStyle: {
          color: ptColor,
          opacity: 0.85,
          borderColor: '#ffffff',
          borderWidth: 1.5,
        },
        label: {
          show: true,
          position: 'right',
          formatter: '{b}',
          fontSize: 11,
          color: '#344054',
          fontWeight: 600,
        },
      })
    }

    s.data = normalizedData
    s.type = 'scatter'
    delete s.symbolSize

    // 增加四象限辅助参考线（均值虚线）
    s.markLine = {
      silent: true,
      symbol: 'none',
      lineStyle: { type: 'dashed', color: '#94a3b8', width: 1 },
      data: [
        { type: 'average', name: 'X轴均值', valueIndex: 0 },
        { type: 'average', name: 'Y轴均值', valueIndex: 1 },
      ],
    }
  }

  // 3. 增强 Tooltip 交互展示
  option.tooltip = {
    trigger: 'item',
    backgroundColor: 'rgba(255, 255, 255, 0.96)',
    borderColor: '#eaecf0',
    borderWidth: 1,
    padding: [8, 12],
    textStyle: { color: '#101828', fontSize: 12 },
    formatter: (params: unknown) => {
      const p = params as {
        name?: string
        value?: [number, number, number?]
      }
      const name = p.name ?? ''
      const vals = p.value || [0, 0]
      const xv = typeof vals[0] === 'number' ? vals[0].toFixed(2) : String(vals[0])
      const yv = typeof vals[1] === 'number' ? vals[1].toFixed(2) : String(vals[1])
      const szLine =
        spec.chart_type === 'bubble' &&
        vals.length >= 3 &&
        typeof vals[2] === 'number'
          ? `<div style="color:#667085;margin-top:2px;">尺寸参照: ${vals[2]}</div>`
          : ''
      return `<div style="font-weight:700;font-size:13px;margin-bottom:4px;color:#1B365D;">${name}</div>
              <div style="color:#475467;">${xAxisName}: <strong style="color:#101828;">${xv}</strong></div>
              <div style="color:#475467;">${yAxisName}: <strong style="color:#101828;">${yv}</strong></div>
              ${szLine}`
    },
  }
}

function resolveChartSvgUrl(spec: ChartSpecLoose | null): string | null {
  if (!spec) return null
  if (spec.image_uri && /^(https?:|data:|\/)/.test(spec.image_uri)) return spec.image_uri
  if (spec.svg_uri) {
    const match = spec.svg_uri.match(/\/runs\/([^/]+)\/artifacts\/charts\/([^/]+)/)
    if (match) {
      return `/api/v1/runs/${match[1]}/artifacts/${match[2]}`
    }
    const fileNameMatch = spec.svg_uri.match(/([^/]+\.svg)$/)
    const rId =
      props.runId ||
      (typeof window !== 'undefined'
        ? window.location.pathname.match(/\/runs\/([^/]+)/)?.[1]
        : null)
    if (fileNameMatch && rId) {
      return `/api/v1/runs/${rId}/artifacts/${fileNameMatch[1]}`
    }
  }
  if (spec.chart_id && props.runId) {
    return `/api/v1/runs/${props.runId}/artifacts/${spec.chart_id}.svg`
  }
  return null
}

// ---- 缩略图渲染 ----
const thumbsRef = ref<HTMLElement[]>([])
const thumbInstances: echarts.ECharts[] = []
let resizeObserver: ResizeObserver | null = null

function chartFootnotes(spec: ChartSpecLoose | null): string[] {
  const notes = [
    ...new Set([
      ...(spec?.footnotes ?? []),
      ...(spec?.option?.footnotes ?? []),
      ...graphicTextNotes(spec?.option?.graphic as unknown),
    ]),
  ]
  return notes
}

/** 从 ECharts option.graphic 中收集纯文本注释（渲染时已从绘图区剥离，落到卡片下方）。 */
function graphicTextNotes(graphic: unknown): string[] {
  if (!Array.isArray(graphic)) return []
  const notes: string[] = []
  for (const item of graphic) {
    if (
      item &&
      (item as { type?: string }).type === 'text' &&
      typeof (item as { style?: { text?: unknown } }).style?.text === 'string'
    ) {
      notes.push((item as { style: { text: string } }).style.text)
    }
  }
  return notes
}

function renderThumbs(): void {
  disposeThumbs()
  if (props.specs.length === 0) return
  requestAnimationFrame(() => {
    ordered.value.forEach((spec, index) => {
      const el = thumbsRef.value[index]
      if (!el || !spec.option || spec.render_mode === 'generated_image') return
      const instance = echarts.init(el)
      instance.setOption(sanitizedOption(spec) ?? spec.option)
      thumbInstances.push(instance)
    })
    if (thumbInstances.length > 0) {
      resizeObserver = new ResizeObserver(() => {
        for (const instance of thumbInstances) instance.resize()
      })
      for (const instance of thumbInstances) {
        const dom = instance.getDom()
        if (dom.parentElement) resizeObserver.observe(dom.parentElement)
      }
    }
  })
}

function disposeThumbs(): void {
  resizeObserver?.disconnect()
  resizeObserver = null
  for (const instance of thumbInstances) instance.dispose()
  thumbInstances.length = 0
}

// ---- 大图预览 ----
const dialogVisible = ref(false)
const activeIndex = ref(0)
const previewMode = ref<'echarts' | 'svg'>('echarts')
const dialogRef = ref<HTMLElement | null>(null)
let dialogInstance: echarts.ECharts | null = null

const activeSpec = computed(() => ordered.value[activeIndex.value] ?? null)

function openChart(index: number): void {
  activeIndex.value = index
  previewMode.value = 'echarts'
  dialogVisible.value = true
}

function onPreviewModeChange(): void {
  if (previewMode.value === 'echarts') {
    nextTickRenderDialog()
  }
}

watch(dialogVisible, (visible) => {
  if (!visible) {
    dialogInstance?.dispose()
    dialogInstance = null
  }
})

watch(activeSpec, async () => {
  if (!dialogVisible.value) return
  await nextTickRenderDialog()
})

async function nextTickRenderDialog(): Promise<void> {
  await new Promise((resolve) => requestAnimationFrame(resolve))
  if (!dialogRef.value || !activeSpec.value?.option) return
  if (activeSpec.value.render_mode === 'generated_image' || previewMode.value === 'svg') return
  dialogInstance?.dispose()
  dialogInstance = echarts.init(dialogRef.value)
  dialogInstance.setOption(sanitizedOption(activeSpec.value, true) ?? activeSpec.value.option)
}

// ---- 展示辅助 ----
function typeLabel(type: string | undefined): string {
  if (!type) return '图表'
  return CHART_TYPE_LABELS[type] ?? type
}

function chartTitleId(spec: ChartSpecLoose, index: number): string {
  return `chart-title-${spec.chart_id ?? index}`
}

function chartPreviewLabel(spec: ChartSpecLoose): string {
  return `查看“${spec.title ?? '未命名图表'}”大图`
}

/** 版本号：spec 上有 unit_revision 时读取 */
function unitRevision(spec: ChartSpecLoose): number | null {
  return typeof spec.unit_revision === 'number' ? spec.unit_revision : null
}

function isLatest(spec: ChartSpecLoose): boolean {
  const rev = unitRevision(spec)
  if (rev === null) return false
  const revs = usable.value.map((s) => unitRevision(s)).filter((n): n is number => n !== null)
  return rev === Math.max(...revs)
}

function sourceLabel(spec: ChartSpecLoose): string | null {
  return spec.source_name ? spec.source_name : null
}

function updatedAtLabel(spec: ChartSpecLoose): string | null {
  const raw = spec.updated_at
  if (!raw) return null
  try {
    return new Date(raw).toLocaleString('zh-CN')
  } catch {
    return null
  }
}

onMounted(renderThumbs)
watch(
  () => props.specs,
  () => renderThumbs(),
  { deep: false }
)
onBeforeUnmount(disposeThumbs)
</script>

<script lang="ts">
export default { name: 'ChartGallery' }
</script>

<template>
  <div data-testid="chart-gallery">
    <el-empty
      v-if="usable.length === 0"
      description="暂无图表规格（chart_generate 阶段完成后可用）"
      :image-size="60"
    />
    <div v-else class="chart-list">
      <article
        v-for="(spec, index) in ordered"
        :key="spec.chart_id ?? index"
        :class="[
          'chart-card',
          displaySizeOf(spec) === 'full' ? 'chart-full' : 'chart-half',
          spec.chart_type === 'industry_chain' ? 'chart-chain' : '',
        ]"
        :aria-labelledby="chartTitleId(spec, index)"
      >
        <div class="chart-head" @click="openChart(index)">
          <div class="card-title-row">
            <h3 :id="chartTitleId(spec, index)" class="chart-title">
              {{ spec.title ?? '未命名图表' }}
            </h3>
            <span class="card-badges">
              <el-tag
                v-if="unitRevision(spec) !== null"
                size="small"
                type="primary"
                effect="plain"
                data-testid="chart-version-badge"
              >
                v{{ unitRevision(spec) }}
              </el-tag>
              <el-tag
                v-if="isLatest(spec)"
                size="small"
                type="warning"
                data-testid="chart-latest-badge"
              >
                最新
              </el-tag>
              <el-tag size="small" type="info" effect="plain">
                {{ typeLabel(spec.chart_type) }}
              </el-tag>
            </span>
          </div>
          <div class="card-meta">
            <span v-if="sourceLabel(spec)">来源：{{ sourceLabel(spec) }}</span>
            <span v-if="updatedAtLabel(spec)" class="meta-sep">·</span>
            <span v-if="updatedAtLabel(spec)">{{ updatedAtLabel(spec) }}</span>
          </div>
        </div>
        <!-- echarts 渲染 -->
        <div
          v-if="spec.render_mode !== 'generated_image'"
          class="chart-surface chart-thumb"
          role="button"
          tabindex="0"
          :aria-label="chartPreviewLabel(spec)"
          :ref="
            (el) => {
              thumbsRef[index] = el as HTMLElement
            }
          "
          @click="openChart(index)"
          @keydown.enter="openChart(index)"
          @keydown.space.prevent="openChart(index)"
        />
        <!-- AI 生成图 / SVG 产业链图：内联 URI -->
        <div v-else class="chart-thumb chart-img">
          <img
            v-if="resolveChartSvgUrl(spec)"
            :src="resolveChartSvgUrl(spec)!"
            :alt="spec.title ?? ''"
            data-testid="chart-svg-image"
          />
          <div v-else class="chart-img-missing muted">AI 生成图未内联，请从产出物下载查看</div>
        </div>
        <div v-if="spec.insight_goal" class="chart-insight">
          <span>分析目的</span>
          {{ spec.insight_goal }}
        </div>
        <div v-if="chartFootnotes(spec).length" class="chart-notes">
          <p v-for="(note, i) in chartFootnotes(spec)" :key="i" class="chart-footnote muted">
            {{ note }}
          </p>
        </div>
      </article>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="activeSpec?.title ?? '图表预览'"
      width="min(1120px, 94vw)"
      destroy-on-close
      data-testid="chart-preview-dialog"
      @opened="nextTickRenderDialog"
    >
      <div v-if="resolveChartSvgUrl(activeSpec)" class="dialog-toolbar">
        <el-radio-group v-model="previewMode" size="small" @change="onPreviewModeChange">
          <el-radio-button value="echarts">交互图表 (ECharts)</el-radio-button>
          <el-radio-button value="svg">出版级矢量图 (SVG)</el-radio-button>
        </el-radio-group>
      </div>

      <div
        v-if="
          (activeSpec?.render_mode === 'generated_image' && activeSpec.image_uri) ||
          previewMode === 'svg'
        "
        class="chart-svg-preview"
      >
        <img
          :src="resolveChartSvgUrl(activeSpec) || activeSpec?.image_uri || ''"
          :alt="activeSpec?.title ?? ''"
          class="chart-svg-img"
        />
      </div>
      <div v-else ref="dialogRef" class="chart-large" />
      <div v-if="activeSpec?.insight_goal" class="chart-goal muted">
        分析目的：{{ activeSpec.insight_goal }}
      </div>
      <div
        v-for="(note, i) in chartFootnotes(activeSpec)"
        :key="i"
        class="chart-goal chart-footnote muted"
      >
        {{ note }}
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.chart-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.chart-card {
  min-width: 0;
  border: 1px solid var(--rp-line);
  border-radius: 12px;
  background: var(--rp-card);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
/* 长图表独占一整行；小图表每行放置 2 个，等宽填满行内空缺 */
.chart-full {
  width: 100%;
}
.chart-half {
  width: calc(50% - 6px);
}
@media (max-width: 900px) {
  .chart-half {
    width: 100%;
  }
}
.chart-head {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  padding: 12px 14px 6px;
  cursor: zoom-in;
}
.card-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.card-badges {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 0;
  font-size: 12px;
  color: var(--rp-ink);
  opacity: 0.65;
}
.meta-sep {
  margin: 0 6px;
}
.chart-title {
  min-width: 0;
  margin: 0;
  font-family: var(--rp-serif);
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-navy);
  line-height: 1.4;
}
.chart-surface {
  border-radius: 10px;
  margin: 0 10px;
  cursor: zoom-in;
  outline: none;
}
.chart-surface:focus-visible {
  box-shadow: 0 0 0 3px var(--el-color-primary-light-7);
}
.chart-thumb {
  width: 100%;
  height: 260px;
  background: var(--rp-paper);
}
/* 产业链拓扑图专属扩容高度，确保上中下游多卡片与毛利率垂直舒展不重叠 */
.chart-chain .chart-thumb {
  height: 480px;
}
/* 小图表保持充裕刻度空间，避免坐标轴与图例挤压重叠 */
.chart-half .chart-thumb {
  height: 240px;
}
.chart-img {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--rp-paper);
}
.chart-img img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}
.chart-img-missing {
  font-size: 12px;
  padding: 20px;
  color: var(--el-text-color-secondary);
}
.chart-insight {
  margin: 6px 14px 0;
  padding: 10px 0 8px;
  border-top: 1px solid var(--el-border-color-extra-light);
  color: var(--el-text-color-regular);
  font-size: 12.5px;
  line-height: 1.6;
}
.chart-insight span {
  color: var(--rp-navy);
  font-weight: 700;
  margin-right: 8px;
}
.chart-notes {
  padding: 0 14px 10px;
}
.chart-footnote {
  margin: 2px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 11.5px;
  line-height: 1.55;
}
/* 预览弹窗内说明 */
.chart-goal {
  font-size: 12px;
  line-height: 1.6;
}
.chart-goal.muted {
  color: var(--rp-ink);
  opacity: 0.7;
}
.chart-large {
  width: 100%;
  height: min(66vh, 640px);
  min-height: 440px;
}
.chart-svg-preview {
  display: flex;
  justify-content: center;
  background: var(--rp-paper);
  padding: 12px;
  border-radius: 8px;
}
.chart-svg-preview img,
.chart-svg-img {
  max-width: 100%;
  max-height: 520px;
  object-fit: contain;
  border-radius: 6px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.dialog-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}
</style>
