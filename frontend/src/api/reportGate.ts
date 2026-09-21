import type { ArtifactRef, StageName, WorkflowState } from './types'

/**
 * 「报告下载」入口门控。
 *
 * 为什么必须显式门控：
 * 后端下载接口（backend/app/api/routes.py:206-252）只校验任务归属与文件存在，
 * **不看任务状态**。而勾了审核门时会出现「阶段已完成、产物已落盘，但 run 仍是
 * waiting_review（尚未人工批准）」的合法组合——若不设门控，未批准的正式报告
 * 会被当成已交付产物放出去。
 *
 * 但不能一刀切只认 completed：
 * 后端 _finish（backend/app/workflow/graph.py:570-581）是 fail-closed 的——
 * 任一阶段结果带 error 时终态是 waiting_review 而不是 completed，此时阶段可能
 * 都跑过了、产物也在。这种情况要放行，但必须强告警。
 *
 * 所以按三态分类：normal（正常交付）/ exception（异常终态，放行+告警）/ blocked（禁下载）。
 */

export type ReportDownloadLevel = 'normal' | 'exception' | 'blocked'

export interface ReportDownloadGate {
  level: ReportDownloadLevel
  /** 是否启用「全部打包下载」按钮 */
  downloadable: boolean
  /** 面向用户的解释，blocked / exception 必填 */
  reason: string
  alertType: 'success' | 'warning' | 'error' | 'info'
  /** 报告融合阶段的产物条数 */
  artifactCount: number
}

/** 报告融合阶段的产物（遍历实际数组） */
export function reportArtifacts(run: WorkflowState): ArtifactRef[] {
  return run.stage_results.report_fusion?.artifacts ?? []
}

export function classifyReportDownload(run: WorkflowState): ReportDownloadGate {
  const artifactCount = reportArtifacts(run).length
  // fail-closed 判据：任一阶段结果带 error
  const errorBearing = Object.values(run.stage_results).some((result) => result?.error != null)

  switch (run.status) {
    case 'completed':
    case 'approved':
      return artifactCount > 0
        ? { level: 'normal', downloadable: true, reason: '', alertType: 'success', artifactCount }
        : {
            level: 'blocked',
            downloadable: false,
            alertType: 'warning',
            artifactCount,
            reason: '报告产物尚未生成，暂不可下载。',
          }

    case 'waiting_review':
      if (errorBearing) {
        return {
          level: 'exception',
          downloadable: artifactCount > 0,
          alertType: 'error',
          artifactCount,
          reason:
            '任务以异常终态结束（存在阶段错误，未走完正常人工审核流程）。产物可能不完整，仅供检查，请勿作为正式交付对外发布。',
        }
      }
      return {
        level: 'blocked',
        downloadable: false,
        alertType: 'warning',
        artifactCount,
        reason:
          '报告已生成但尚未通过人工审核，暂不可作为正式交付下载。请先在任务工作台通过「报告融合」阶段的审核。',
      }

    case 'running':
    case 'pending':
      return {
        level: 'blocked',
        downloadable: false,
        alertType: 'info',
        artifactCount,
        reason: '任务仍在执行中，报告尚未就绪。',
      }

    case 'rejected':
      return {
        level: 'blocked',
        downloadable: false,
        alertType: 'error',
        artifactCount,
        reason: '任务已被驳回，无可用正式报告。',
      }

    case 'failed':
      return {
        level: 'blocked',
        downloadable: false,
        alertType: 'error',
        artifactCount,
        reason: '任务执行失败，无可用正式报告。',
      }

    case 'cancelled':
      return {
        level: 'blocked',
        downloadable: false,
        alertType: 'info',
        artifactCount,
        reason: '任务已取消。',
      }

    default:
      return {
        level: 'blocked',
        downloadable: false,
        alertType: 'warning',
        artifactCount,
        reason: '任务状态未知，无法下载。',
      }
  }
}

// ------------------------------------------------------------------
// 「阶段五批准后自动跳转到下载页」的判定
// ------------------------------------------------------------------

/** 决策类动作：提交后终态确定（通过/带风险通过/自定义选择） */
export const DECISION_ACTIONS = [
  'approve',
  'accept_recommendation',
  'accept_with_risks',
  'customize',
] as const

export const isDecisionAction = (action?: string | null): boolean =>
  !!action && (DECISION_ACTIONS as readonly string[]).includes(action)

/**
 * 是否在本次审核提交后自动跳到下载页。
 * 必须同时看「被审阶段」和「动作类型」：只有 report_fusion 阶段且通过决策动作才跳转。
 */
export function shouldAutoJumpToDownload(
  reviewedStage: StageName | null,
  action?: string | null
): boolean {
  return reviewedStage === 'report_fusion' && isDecisionAction(action)
}
