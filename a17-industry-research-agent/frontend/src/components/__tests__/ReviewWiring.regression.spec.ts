/**
 * 人机审核接线回归（2026-11-18）
 *
 * 覆盖四条 P0 与一条 P1：
 *   P0-1 阶段二研判读写必须落在真实 insights 上，且不得兜底样例
 *   P0-2 只改评级不得下发空摘要（会清空报告 headline）
 *   P0-3 指标卡必须译中文名 / 归一亿元 / 百分比化 change_pct
 *   P0-4 补采清单必须来自真实 source_records
 *   P1-1 阶段二指标卡统计读 insights 而非 claims
 */
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it } from 'vitest'
import StageInterventionModal from '../StageInterventionModal.vue'
import MetricCards from '../MetricCards.vue'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  wrappers.length = 0
  document.body.innerHTML = ''
})

function openModal(props: Record<string, unknown>) {
  const wrapper = mount(StageInterventionModal, {
    props: { visible: true, revision: 1, stage: 'data_interpret', data: {}, ...props },
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
  wrappers.push(wrapper)
  return wrapper
}

/** el-input 会把透传属性放到内层 textarea 上，两种落点都要兼容 */
function summaryTextarea(): HTMLTextAreaElement {
  const host = document.querySelector('[data-testid="summary-text"]')
  const el = host?.tagName === 'TEXTAREA' ? host : host?.querySelector('textarea')
  expect(el).toBeTruthy()
  return el as HTMLTextAreaElement
}

async function clickButton(label: string) {
  const button = Array.from(document.querySelectorAll('button')).find((b) =>
    b.textContent?.includes(label)
  )
  expect(button).toBeTruthy()
  button!.click()
  await flushPromises()
}

const INSIGHTS = [
  {
    insight_id: 'I-01',
    title: '销量增速换挡',
    conclusion: '2025 年销量 1649 万辆，增速回落至个位数。',
    significance: '行业由总量扩张转向结构分化。',
    confidence: 'high',
    evidence_record_ids: ['R-a', 'R-b'],
    related_metrics: ['nev_sales'],
  },
  {
    insight_id: 'I-02',
    title: '利润向中游集中',
    conclusion: '电池龙头毛利率高于整车。',
    significance: '议价权决定利润分配。',
    evidence_record_ids: ['R-b', 'R-c'],
  },
]

describe('P0-1 阶段二研判裁决落在真实 insights 上', () => {
  it('弹窗条目来自 insights，且不再出现内置样例研判', async () => {
    openModal({
      stage: 'data_interpret',
      initialTab: 'knowledge_judgment',
      data: { insights: INSIGHTS },
    })
    await flushPromises()
    const text = document.body.textContent || ''
    expect(text).toContain('销量增速换挡')
    expect(text).toContain('利润向中游集中')
    expect(text).not.toContain('产业处于高景气周期与出海放量红利期')
    expect(text).not.toContain('J-1')
  })

  it('剔除为软标记，保留证据 ID 与置信度，且不再双写 findings', async () => {
    const wrapper = openModal({
      stage: 'data_interpret',
      initialTab: 'knowledge_judgment',
      data: { insights: INSIGHTS },
    })
    await flushPromises()
    const rejectRadio = Array.from(document.querySelectorAll('.el-radio-button')).find((el) =>
      el.textContent?.includes('剔除否定')
    )
    rejectRadio!.querySelector('input')?.click()
    await flushPromises()
    await clickButton('保存背景知识与判断修正')

    const payload = wrapper.emitted('submitDirectEdit')?.[0]?.[0] as {
      edited_data: Record<string, unknown>
    }
    expect(payload.edited_data.findings).toBeUndefined()
    expect(payload.edited_data.key_findings).toBeUndefined()
    const saved = payload.edited_data.insights as Record<string, unknown>[]
    expect(saved).toHaveLength(2)
    expect(saved[0]!.review_status).toBe('rejected')
    expect(saved[0]!.evidence_record_ids).toEqual(['R-a', 'R-b'])
    expect(saved[0]!.confidence).toBe('high')
    expect(saved[1]!.review_status).toBe('active')
  })

  it('insights 缺失时走空态并禁用保存，不发任何请求', async () => {
    const wrapper = openModal({
      stage: 'data_interpret',
      initialTab: 'knowledge_judgment',
      data: {},
    })
    await flushPromises()
    expect(document.querySelector('[data-testid="judgments-empty"]')).toBeTruthy()
    const save = document.querySelector<HTMLButtonElement>('[data-testid="save-judgments"]')
    expect(save!.disabled).toBe(true)
    save!.click()
    await flushPromises()
    expect(wrapper.emitted('submitDirectEdit')).toBeUndefined()
  })
})

describe('P0-2 摘要定稿不得清空报告执行摘要', () => {
  it('融合阶段无摘要时置只读，只改评级不下发 executive_summary', async () => {
    const wrapper = openModal({
      stage: 'report_fusion',
      initialTab: 'summary_rating',
      data: { title: '《新能源汽车》深度行业研究报告' },
    })
    await flushPromises()
    expect(document.querySelector('[data-testid="summary-readonly-hint"]')).toBeTruthy()
    const textarea = summaryTextarea()
    expect(textarea!.readOnly).toBe(true)

    await clickButton('保存评级与执行摘要定稿')
    const payload = wrapper.emitted('submitDirectEdit')?.[0]?.[0] as {
      edited_data: Record<string, unknown>
    }
    expect('executive_summary' in payload.edited_data).toBe(false)
  })

  it('跨阶段回填 A2 摘要后可编辑，改动才下发', async () => {
    const wrapper = openModal({
      stage: 'report_fusion',
      initialTab: 'summary_rating',
      data: { title: '标题' },
      crossStage: { executiveSummary: '原始摘要文本' },
    })
    await flushPromises()
    const textarea = summaryTextarea()
    expect(textarea!.value).toBe('原始摘要文本')
    expect(textarea!.readOnly).toBe(false)

    // 未改动 → 不下发摘要键
    await clickButton('保存评级与执行摘要定稿')
    let payload = wrapper.emitted('submitDirectEdit')?.[0]?.[0] as {
      edited_data: Record<string, unknown>
    }
    expect('executive_summary' in payload.edited_data).toBe(false)

    textarea!.value = '修订后的摘要'
    textarea!.dispatchEvent(new Event('input'))
    await flushPromises()
    await clickButton('保存评级与执行摘要定稿')
    payload = wrapper.emitted('submitDirectEdit')?.[1]?.[0] as {
      edited_data: Record<string, unknown>
    }
    expect(payload.edited_data.executive_summary).toBe('修订后的摘要')
  })
})

describe('P0-3 指标卡中文名 / 亿元口径 / 百分比涨跌', () => {
  it('把 revenue + 元 + 小数 change_pct 转成可发布的展示口径', async () => {
    const wrapper = openModal({
      stage: 'report_fusion',
      initialTab: 'metric_cards',
      data: {
        key_metrics: [
          {
            metric_id: 'K-1',
            name: 'revenue',
            entity: '比亚迪',
            value: 803964958000,
            unit: '元',
            period: '2025-12-31',
            change_pct: 0.03456751786995706,
            evidence_record_ids: ['R-prod'],
          },
        ],
      },
    })
    await flushPromises()
    const values = Array.from(document.querySelectorAll('.m-card-fields input')).map(
      (i) => (i as HTMLInputElement).value
    )
    expect(values).toContain('比亚迪 营业收入')
    expect(values).toContain('8039.65')
    expect(values).toContain('亿元')
    expect(values).toContain('+3.46%')

    await clickButton('保存 8 张核心指标卡定制')
    const payload = wrapper.emitted('submitDirectEdit')?.[0]?.[0] as {
      edited_data: Record<string, unknown>
    }
    expect(payload.edited_data.metrics_cards).toBeUndefined()
    const saved = (payload.edited_data.key_metrics as Record<string, unknown>[])[0]!
    expect(saved.label).toBe('比亚迪 营业收入')
    expect(saved.unit).toBe('亿元')
    expect(saved.evidence_record_ids).toEqual(['R-prod'])
    expect(saved.metric_id).toBe('K-1')
  })

  it('非法数值禁用保存且不发请求（T03）', async () => {
    const wrapper = openModal({
      stage: 'report_fusion',
      initialTab: 'metric_cards',
      data: {
        key_metrics: [
          { metric_id: 'K-BAD', name: 'revenue', entity: '比亚迪', value: '八千亿', unit: null },
        ],
      },
    })
    await flushPromises()
    const save = document.querySelector<HTMLButtonElement>('[data-testid="save-metric-cards"]')
    expect(save!.disabled).toBe(true)
    save!.click()
    await flushPromises()
    expect(wrapper.emitted('submitDirectEdit')).toBeUndefined()
  })
})

describe('P0-4 补采清单来自真实 source_records', () => {
  it('点号使用真实 record_id，且不出现内置样例点号与数值', async () => {
    openModal({
      stage: 'data_fetch',
      initialTab: 'partial_refetch',
      data: {
        industry_topic: '新能源汽车',
        source_records: [
          {
            record_id: 'R-real-1',
            metric: '新能源汽车:销量:累计值',
            value: 16490000,
            unit: '辆',
            entity_name: '中国',
            period: '2025-12-31',
            domain: 'industry',
            skill_name: 'hithink-industry-query',
          },
        ],
      },
    })
    await flushPromises()
    const text = document.body.textContent || ''
    expect(text).toContain('行业规模与景气')
    expect(text).toContain('16490000 辆')
    expect(text).toContain('行业数据')
    for (const fake of ['F-01', 'F-02', 'C-01', 'M-01', 'P-01', '样本龙头甲', '1,342']) {
      expect(text).not.toContain(fake)
    }
  })

  it('无 source_records 时空态且点级提交禁用（T02）', async () => {
    openModal({ stage: 'data_fetch', initialTab: 'partial_refetch', data: {} })
    await flushPromises()
    expect(document.querySelector('[data-testid="refetch-empty"]')).toBeTruthy()
    const submit = Array.from(document.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('启动定向补采')
    )
    expect((submit as HTMLButtonElement).disabled).toBe(true)
  })

  it('未满足的 metric_requirements 生成缺口点并默认勾选', async () => {
    const wrapper = openModal({
      stage: 'data_fetch',
      initialTab: 'partial_refetch',
      data: {
        industry_topic: '新能源汽车',
        source_records: [],
        metric_requirements: [
          {
            requirement_id: 'nev_export',
            label: '2025 年新能源汽车出口量',
            metric_terms: ['新能源汽车:出口量'],
            domain: 'industry',
            passed: false,
          },
        ],
      },
    })
    await flushPromises()
    expect(document.body.textContent).toContain('2025 年新能源汽车出口量')
    await clickButton('启动定向补采')
    const payload = wrapper.emitted('submitRevise')?.[0]?.[0] as {
      edited_data: { action_type: string; data_point_ids: string[]; domains: string[] }
    }
    expect(payload.edited_data.action_type).toBe('partial_refetch')
    expect(payload.edited_data.data_point_ids).toEqual(['REQ:nev_export:0'])
    expect(payload.edited_data.domains).toContain('industry')
  })
})

describe('P1-1 阶段二统计卡读 insights', () => {
  it('结论主张与引用证据不再恒为 0', async () => {
    const wrapper = mount(MetricCards, {
      props: { stage: 'data_interpret', data: { insights: INSIGHTS, dimension_coverage: [] } },
      global: { plugins: [ElementPlus] },
    })
    wrappers.push(wrapper)
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('结论主张')
    expect(text).toContain('2')
    // R-a / R-b / R-c 去重后为 3
    expect(text).toContain('3')
  })
})
