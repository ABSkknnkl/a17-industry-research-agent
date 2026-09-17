import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import LimitedIntentDialog from '../LimitedIntentDialog.vue'

function mountDialog() {
  return mount(LimitedIntentDialog, {
    props: {
      modelValue: true,
      mode: 'revise',
      stageLabel: 'chart_generate',
      objectLabel: 'CHART-001',
      objectVersion: 'r3',
      allowQuestions: false,
      'onUpdate:modelValue': () => {},
    },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

describe('LimitedIntentDialog', () => {
  it('按钮型指令被拒绝', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    const input = wrapper.find('textarea[data-testid="intent-comment"]')
    expect(input.exists()).toBe(true)
    await input.setValue('请删除这张图')
    await flushPromises()
    expect(wrapper.find('[data-testid="intent-reject"]').exists()).toBe(true)
    const previewBtn = wrapper.findAll('button').find((b) => b.text().includes('预览修改'))
    expect(previewBtn!.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('合法意图可预览和确认', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    await wrapper
      .find('textarea[data-testid="intent-comment"]')
      .setValue('保留封装约束，避免绝对化表述')
    await flushPromises()
    const previewBtn = wrapper.findAll('button').find((b) => b.text().includes('预览修改'))!
    expect(previewBtn.attributes('disabled')).toBeUndefined()
    await previewBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="intent-preview"]').exists()).toBe(true)
    const confirmBtn = wrapper.findAll('button').find((b) => b.text().includes('确认执行'))!
    expect(confirmBtn.attributes('disabled')).toBeUndefined()
    await confirmBtn.trigger('click')
    await flushPromises()
    // emit confirm
    const emitted = wrapper.emitted('confirm')
    expect(emitted).toBeTruthy()
    expect(emitted![0]![0]).toMatchObject({
      comment: '保留封装约束，避免绝对化表述',
    })
    wrapper.unmount()
  })
})
