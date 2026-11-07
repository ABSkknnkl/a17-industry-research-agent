import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it } from 'vitest'
import StageInterventionModal from '../StageInterventionModal.vue'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount())
  wrappers.length = 0
  document.body.innerHTML = ''
})

async function open(data: Record<string, unknown>) {
  const wrapper = mount(StageInterventionModal, {
    props: {
      visible: true,
      stage: 'report_fusion',
      revision: 1,
      initialTab: 'audit_steering',
      data,
    },
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return {
    values: Array.from(document.querySelectorAll('.audit-board .audit-val')).map((value) =>
      value.textContent?.trim()
    ),
    signoff: document.querySelector('.signoff-box')?.textContent,
    board: document.querySelector('.audit-board')?.textContent,
  }
}

// Catches substituting presentation defaults for the backend quality result.
describe('report intervention quality reflects the current quality result', () => {
  it('shows unknown values and pending verification when no quality result is provided', async () => {
    const view = await open({})
    expect(view.values).toEqual(['未知 / 未知 章', '未知', '未知', '待填写'])
    expect(view.board).toContain('未知 / 未知 节')
    expect(view.signoff).toContain('待核验')
    expect(view.signoff).not.toContain('VERIFIED')
    expect(view.signoff).not.toContain('已通过')
    expect(view.signoff).not.toContain('符合金融出版')
  })

  it('shows failed checks and actual partial counts rather than claiming full verification', async () => {
    const view = await open({
      quality: {
        passed: false,
        chapter_count: 2,
        expected_chapter_count: 4,
        section_count: 5,
        expected_section_count: 12,
        evidence_coverage: 0.625,
        included_chart_count: 1,
        issues: ['证据覆盖不足'],
      },
    })
    expect(view.values).toEqual(['2 / 4 章', '62.5%', '1 幅', '待填写'])
    expect(view.board).toContain('5 / 12 节')
    expect(view.signoff).toContain('质检未通过')
    expect(view.signoff).toContain('证据覆盖不足')
    expect(view.signoff).not.toContain('VERIFIED')
    expect(view.signoff).not.toContain('已通过')
  })

  it('retains valid zero values and reports backend-passed checks as awaiting human approval', async () => {
    const view = await open({
      quality: {
        passed: true,
        chapter_count: 0,
        expected_chapter_count: 0,
        section_count: 0,
        expected_section_count: 0,
        evidence_coverage: 0,
        included_chart_count: 0,
      },
    })
    expect(view.values).toEqual(['0 / 0 章', '0%', '0 幅', '待填写'])
    expect(view.signoff).toContain('质检通过，待人工核准')
    expect(view.signoff).not.toContain('符合金融出版')
  })
})
