/**
 * OCR 页 DOM 引用与状态条。
 * 导出固定节点引用、运行时 getter（避免缓存导致 null）、setStatus。
 * 无全局脚本依赖。
 */

export const form = document.getElementById("ocr-form");
export const fileInput = document.getElementById("file-input");
export const statusText = document.getElementById("status-text");

export const pageNav = document.getElementById("page-nav");
export const pageInfo = document.getElementById("page-info");
export const btnPrevTask = document.getElementById("btn-prev-task");
export const btnNextTask = document.getElementById("btn-next-task");
export const segmentNav = document.getElementById("segment-nav");
export const segmentInfo = document.getElementById("segment-info");
export const btnPrevSegment = document.getElementById("btn-prev-segment");
export const btnNextSegment = document.getElementById("btn-next-segment");
export const verifyBar = document.getElementById("verify-bar");
export const verifyStatus = document.getElementById("verify-status");
export const btnVerify = document.getElementById("btn-verify");

/**
 * 运行时获取预览容器，避免偶发缓存/时序导致节点为空。
 * @returns {HTMLElement | null}
 */
export function getPreviewContainer() {
    return document.getElementById("preview-container");
}

/**
 * 运行时获取右侧摘要区节点。
 * @returns {HTMLElement | null}
 */
export function getOcrResultMeta() {
    return document.getElementById("ocr-result-meta");
}

/**
 * 运行时获取右侧表格容器节点。
 * @returns {HTMLElement | null}
 */
export function getOcrResultTables() {
    return document.getElementById("ocr-result-tables");
}

/**
 * 更新上传表单旁的状态文案（成功为蓝，错误为红）。
 * @param {string} message
 * @param {boolean} [isError=false]
 */
export function setStatus(message, isError = false) {
    if (statusText) {
        statusText.textContent = message;
        statusText.style.color = isError ? "#dc2626" : "#2563eb";
    }
}
