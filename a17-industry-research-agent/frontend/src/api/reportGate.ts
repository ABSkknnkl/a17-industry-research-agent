import type { ArtifactRef, StageName, WorkflowState } from './types'

import type { StageResult } from './types'

export function isReportSignoffBlocked(data: Record<string, unknown>): boolean {
  const decision = data.decision_package as { blocking_risk_codes?: string[] } | undefined
  return Boolean(data.quality_notice || data.exports_stale || decision?.blocking_risk_codes?.length)
}

export function isReportSignoffOnHold(result: StageResult): boolean {
  return (
    result.stage === 'report_fusion' &&
    result.status === 'waiting_review' &&
    isReportSignoffBlocked(result.data)
  )
}

export function artifactDownloadMode(
  run: WorkflowState,
  artifactId: string
): 'formal' | 'draft' | undefined {
  const options = run.report_download
  if (!options) return classifyReportDownload(run).mode ?? 'formal'
  if (options.formal_artifact_ids.includes(artifactId)) return 'formal'
  if (options.draft_artifact_ids.includes(artifactId)) return 'draft'
}

export type ReportDownloadLevel = 'normal' | 'exception' | 'blocked'

export interface ReportDownloadGate {
  mode?: 'formal' | 'draft'
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
  const fusion = run.stage_results.report_fusion
  const data = (fusion?.data ?? {}) as Record<string, unknown>
  if (run.report_download) {
    const { formal_artifact_ids, draft_artifact_ids } = run.report_download
    if (formal_artifact_ids.length) {
      return data.validation_version
        ? {
            level: 'normal',
            mode: 'formal',
            downloadable: true,
            reason: '',
            alertType: 'success',
            artifactCount,
          }
        : {
            level: 'exception',
            mode: 'formal',
            downloadable: true,
            alertType: 'warning',
            artifactCount,
            reason: '历史报告可供查阅，旧的通过标记不代表本轮核验结论。',
          }
    }
    if (draft_artifact_ids.length) {
      return {
        level: 'exception',
        mode: 'draft',
        downloadable: true,
        alertType: 'warning',
        artifactCount,
        reason: '当前产物仅供审阅，请勿作为正式报告发布。',
      }
    }
    return {
      level: 'blocked',
      downloadable: false,
      alertType: 'warning',
      artifactCount,
      reason:
        typeof data.delivery_block_reason === 'string'
          ? data.delivery_block_reason
          : run.status === 'waiting_review'
            ? '正式报告尚待审核，请返回任务工作台。'
            : '当前版本没有可下载的报告产物。',
    }
  }
  const builtAt = data.built_at_revision
  if (
    artifactCount > 0 &&
    ((builtAt != null && builtAt !== run.revision) || data.exports_stale || data.delivery_blocked)
  ) {
    return {
      level: 'blocked',
      downloadable: false,
      alertType: 'warning',
      artifactCount,
      reason: '报告内容已更新，当前导出文件需要重新生成。',
    }
  }
  const quality = data.quality as { passed?: boolean } | undefined
  const limited =
    data.hard_blocked || quality?.passed === false || data.delivery_status === 'ready_with_limits'
  if (limited && artifactCount > 0) {
    const available = data.draft_available === true && data.draft_sanitized === true
    return {
      level: available ? 'exception' : 'blocked',
      mode: 'draft',
      downloadable: available,
      alertType: 'warning',
      artifactCount,
      reason: available
        ? '受限草稿：尚未通过正式质量门禁，未核验数字已移除。可下载检查资料缺口，请勿作为正式报告发布。'
        : '报告尚未通过正式质量门禁，受限草稿尚未就绪。请检查问题清单并重新融合。',
    }
  }
  if (
    artifactCount > 0 &&
    !data.validation_version &&
    ['completed', 'approved'].includes(run.status)
  ) {
    return {
      level: 'exception',
      downloadable: true,
      alertType: 'warning',
      artifactCount,
      reason:
        '历史报告：尚未按当前期间、指标和事实核验规则复验。可下载查阅，旧的通过标记不代表本轮正式核验结论。',
    }
  }
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
  action?: string | null,
  status?: WorkflowState['status']
): boolean {
  if (status && status !== 'completed' && status !== 'approved') return false
  return reviewedStage === 'report_fusion' && isDecisionAction(action)
}
