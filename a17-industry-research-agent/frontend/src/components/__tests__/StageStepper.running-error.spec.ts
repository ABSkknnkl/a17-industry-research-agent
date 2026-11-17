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
      '已通过，存在质量缺口'
    )
  })
})
