import { onMounted, onUnmounted, ref, type Ref } from 'vue'
import { listRuns } from '../api/client'

/**
 * 待审任务计数（B43 / 前端 B5）。
 *
 * 任务停在 waiting_review 时此前没有任何聚合信号，用户必须逐个点开才发现。
 * 这里用现有的列表接口统计最近任务的待审数量，供顶栏角标展示；
 * 失败一律吞掉（角标是辅助信息，绝不能影响主流程）。
 */
export interface PendingReviews {
  count: Ref<number>
  refresh: () => Promise<void>
}

const SCAN_LIMIT = 100

export function usePendingReviews(intervalMs = 60_000): PendingReviews {
  const count = ref(0)
  let timer: ReturnType<typeof setInterval> | null = null
  let disposed = false

  async function refresh(): Promise<void> {
    try {
      const data = await listRuns(0, SCAN_LIMIT)
      if (disposed) return
      count.value =
        data.waiting_review_count ??
        data.items.filter((item) => item.status === 'waiting_review').length
    } catch {
      // 保持上一次的值，不打断主流程
    }
  }

  onMounted(() => {
    void refresh()
    timer = setInterval(() => void refresh(), intervalMs)
  })

  onUnmounted(() => {
    disposed = true
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  })

  return { count, refresh }
}
