/**
 * OCR 页面共享运行态：PDF/分页、多段 markdown、待验证任务队列等。
 * 由 ocr-preview-nav、ocr-main 等模块读写；不依赖 DOM。
 * 全局：window.OCR_UNVERIFIED_TASK_IDS 由模板内联脚本注入。
 */

export const state = {
    pdfDoc: null,
    pdfTotalPages: 0,
    currentPageIndex: 1,
    /** data.pages：每段含 markdown、task_id、is_verified、file_url、file_type 等 */
    markdownPages: [],
    fileUrlForPdf: null,
    currentTaskId: null,
    isVerified: false,
    /** 待验证任务 ID（新到旧），与 GET /api/tasks/unverified-queue 一致 */
    unverifiedTaskIds: Array.isArray(window.OCR_UNVERIFIED_TASK_IDS)
        ? window.OCR_UNVERIFIED_TASK_IDS.slice()
        : [],
    /** currentTaskId 在 unverifiedTaskIds 中的下标，-1 表示不在队列 */
    queuePosition: -1,
    /** 验证前的队列位置，用于验证后（任务已移出队列）仍可导航到相邻任务 */
    lastQueuePosition: -1,
    /** 金加 CNC0 双表时：为 true 则校验与提交仅第一段，忽略第二段「品質明細表」及以下 */
    cnc0SecondBlockLocked: false,
};
