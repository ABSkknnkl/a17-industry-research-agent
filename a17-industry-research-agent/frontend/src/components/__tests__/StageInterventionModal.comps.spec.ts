import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it } from 'vitest'
import StageInterventionModal from '../StageInterventionModal.vue'

// Catches projecting canonical entries onto aliases and discarding financial/evidence fields.
describe('comparable company editor contract', () => {
  const wrappers: ReturnType<typeof mount>[] = []
  afterEach(() => {
    wrappers.forEach((wrapper) => wrapper.unmount())
    wrappers.length = 0
    document.body.innerHTML = ''
  })

  async function open(data: Record<string, unknown>) {
    const wrapper = mount(StageInterventionModal, {
      props: { visible: true, stage: 'data_interpret', revision: 1, initialTab: 'comps', data },
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    wrappers.push(wrapper)
    await flushPromises()
    return wrapper
  }

  async function save() {
    const button = Array.from(document.querySelectorAll('button')).find((item) =>
      item.textContent?.includes('保存标的池调整')
    )
    expect(button).toBeDefined()
    button!.click()
    await flushPromises()
  }

  it('preserves the full canonical matrix on an unchanged save, including zeroes and evidence', async () => {
    const matrix = {
      entries: [
        {
          company_name: '测试科技',
          company_code: '600001.SH',
          market_cap: 0,
          pe_ttm: 0,
          pb: 0,
          revenue: 150,
          net_profit: 0,
          evidence_record_ids: ['R-test'],
          valuation_tier: 'loss_or_high_multiple',
          valuation_note: '亏损观察',
          custom: { retained: true },
        },
      ],
      total_market_cap: 0,
      median_pe: 16,
      currency: 'CNY',
      custom_matrix_note: 'retain',
    }
    const wrapper = await open({ comps_matrix: matrix })
    expect(Array.from(document.querySelectorAll('input')).map((input) => input.value)).toContain(
      '测试科技'
    )
    await save()
    expect(wrapper.emitted('submitDirectEdit')?.[0]?.[0]).toMatchObject({
      edited_data: { comps_matrix: matrix },
    })
  })

  it('saves changed company and numeric fields as canonical values while retaining the rest', async () => {
    const wrapper = await open({
      comps_matrix: {
        entries: [
          {
            company_name: '旧名称',
            company_code: '600001.SH',
            market_cap: 12,
            pe_ttm: 20,
            revenue: 150,
            net_profit: 10,
            evidence_record_ids: ['R-test'],
            valuation_tier: 'profitable',
          },
        ],
        total_market_cap: 12,
        currency: 'CNY',
      },
    })
    const inputs = document.querySelectorAll<HTMLInputElement>('.el-table input')
    inputs[0]!.value = '新名称'
    inputs[0]!.dispatchEvent(new Event('input'))
    inputs[2]!.value = '0'
    inputs[2]!.dispatchEvent(new Event('input'))
    inputs[3]!.value = ''
    inputs[3]!.dispatchEvent(new Event('input'))
    await save()
    expect(wrapper.emitted('submitDirectEdit')?.[0]?.[0]).toMatchObject({
      edited_data: {
        comps_matrix: {
          entries: [
            {
              company_name: '新名称',
              company_code: '600001.SH',
              market_cap: 0,
              pe_ttm: null,
              revenue: 150,
              net_profit: 10,
              evidence_record_ids: ['R-test'],
              valuation_tier: 'profitable',
            },
          ],
          total_market_cap: 0,
          currency: 'CNY',
        },
      },
    })
  })

  it('does not create fabricated comparable companies when no data exists', async () => {
    const wrapper = await open({})
    await save()
    expect(wrapper.emitted('submitDirectEdit')?.[0]?.[0]).toMatchObject({
      edited_data: { comps_matrix: { entries: [] } },
    })
  })
})
