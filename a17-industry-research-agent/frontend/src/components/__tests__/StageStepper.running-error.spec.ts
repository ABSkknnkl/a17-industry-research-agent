import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import StageStepper from '../StageStepper.vue'
import { showStageError } from '../../api/stageStatus'
import type { StageResult } from '../../api/types'

function stage(status: StageResult['status'], error: string | null): StageResult {
  return {
    stage: 'chapter_write',
    status,
    revision: 2,
    error,
    data: {},
    artifacts: [],
    evidence_sources: [],
  }
}

describe('阶段执行状态优先于上次异常', () => {
  it('执行中和待执行不显示遗留异常', () => {
    expect(showStageError(stage('running', '上一轮异常'))).toBe(false)
    expect(showStageError(stage('pending', '上一轮异常'))).toBe(false)
    const wrapper = mount(StageStepper, {
      global: { plugins: [ElementPlus] },
      props: { stageResults: { chapter_write: stage('running', '上一轮异常') } },
    })
    expect(wrapper.get('[data-testid="stage-step-chapter_write"]').text()).toContain('正在执行')
    expect(wrapper.text()).not.toContain('有异常')
  })
  it('执行结束后需要处理的异常仍显示', () => {
    expect(showStageError(stage('waiting_review', '质量未通过'))).toBe(true)
    expect(showStageError(stage('failed', null))).toBe(true)
    expect(showStageError(stage('completed', null))).toBe(false)
    expect(showStageError(stage('approved', '质量缺口'))).toBe(false)
    const wrapper = mount(StageStepper, {
      global: { plugins: [ElementPlus] },
      props: { stageResults: { chapter_write: stage('approved', '质量缺口') } },
    })
    expect(wrapper.get('[data-testid="stage-step-chapter_write"]').text()).toContain(
      '已完成，质量待复核'
    )
  })
})

it('展示已完成阶段的结果，并在 A5 核验通过后更新 A4 摘要', async () => {
  const wrapper = mount(StageStepper, {
    global: { plugins: [ElementPlus] },
    props: {
      durationSeconds: { data_fetch: 4.54 },
      stageResults: {
        data_fetch: {
          ...stage('approved', null),
          stage: 'data_fetch',
          data: {
            total_records: 375,
            live_fetch: { live_observation_count: 373, archive_supplement_count: 2 },
            model_execution: { models: ['deepseek-v4-flash'], successful_requests: 1 },
          },
        },
        chapter_write: {
          ...stage('approved', '阶段稿有质量提示'),
          data: { chapters: [{ sections: [{ paragraphs: [{ text: '带证据的正文' }] }] }] },
        },
      },
    },
  })
  const dataFetch = wrapper.get('[data-testid="stage-step-data_fetch"]')
  expect(dataFetch.text()).toContain('同花顺 373 条')
  expect(dataFetch.text()).toContain('核验补齐 2 条')
  expect(dataFetch.text()).toContain('用时 4.5 秒')
  expect(dataFetch.text()).toContain('模型响应 1 次')
  expect(wrapper.get('[data-testid="stage-step-chapter_write"]').text()).toContain('待终审复核')
  await wrapper.setProps({ finalReportReady: true })
  expect(wrapper.get('[data-testid="stage-step-chapter_write"]').text()).toContain('终审核验通过')
})
