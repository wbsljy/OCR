/**
 * OCR 分页/待验证队列、左侧 PDF 或图片预览、当前页表格渲染、任务结果加载。
 * 依赖：state、dom、utils（setOcrTablesMessage）、table-editor（renderOcrTableEditor）。
 * 全局：pdfjsLib（由 ocr.html 先于本模块加载）。
 */

import { state } from "./ocr-state.js";
import {
    btnNextSegment,
    btnNextTask,
    btnPrevSegment,
    btnPrevTask,
    pageInfo,
    pageNav,
    segmentInfo,
    segmentNav,
    verifyBar,
    verifyStatus,
    btnVerify,
    getPreviewContainer,
    getOcrResultMeta,
    setStatus,
} from "./ocr-dom.js";
import { setOcrTablesMessage } from "./ocr-utils-html.js";
import { renderOcrTableEditor } from "./ocr-table-editor.js";

/** 与 .preview-container 左右 padding 之和一致，避免贴边裁切 */
const PREVIEW_PAD_X = 28;

/**
 * 在 fit-width 基础上额外提高栅格倍数（backing store 更密，CSS 仍按 displayScale 贴合容器）。
 * 桌面 PDF 阅读器观感更锐，需显著高于 1；过大则内存与耗时上升。
 */
const RENDER_SUPER_SAMPLE = 2;

/** 单页栅格宽度下限（px），避免窄侧栏时有效分辨率过低、与 WPS 等对比发糊 */
const MIN_BACKING_PAGE_WIDTH_PX = 3000;

/** displayScale 上限（仅限制「按页宽适配」倍数，不限制上面叠加的栅格增强） */
const DISPLAY_SCALE_CAP = 6;

/** pixelScale 相对「displayScale * dpr」的最大倍数，防止极端 PDF 撑爆内存 */
const MAX_PIXEL_SCALE_OVER_BASE = 10;

/** 单张 canvas 最大边长（px），超限则按比例收缩栅格 */
const MAX_CANVAS_EDGE_PX = 6144;

/** 预览区宽度变化时重绘防抖（ms） */
const PREVIEW_RESIZE_DEBOUNCE_MS = 120;

let previewResizeObserver = null;
let previewResizeDebounceTimer = null;
/** 监听父级面板宽度，避免监听 preview 自身导致「内容撑宽 → 重绘 → 再撑宽」 */
let lastPreviewPanelObservedWidth = 0;

function getPreviewContainerContentWidth(container) {
    const rect = container.getBoundingClientRect();
    let w = rect.width > 0 ? rect.width : container.clientWidth;
    if (!Number.isFinite(w) || w < 0) w = 0;
    return w;
}

/**
 * 布局未稳定时 clientWidth 可能为 0，延后一帧再量。
 * @param {HTMLElement} previewContainer
 * @returns {Promise<number>}
 */
function measurePreviewWidth(previewContainer) {
    let w = getPreviewContainerContentWidth(previewContainer);
    if (w >= 32) return Promise.resolve(w);
    return new Promise((resolve) => {
        requestAnimationFrame(() => {
            w = getPreviewContainerContentWidth(previewContainer);
            resolve(w >= 32 ? w : 600);
        });
    });
}

function slotIsPdfPreview(slot) {
    if (!slot || !slot.file_url) return false;
    const ftype = (slot.file_type || "").toLowerCase();
    if (ftype === "pdf") return true;
    return /\.pdf$/i.test(String(slot.file_url));
}

function schedulePdfPreviewRerender() {
    if (previewResizeDebounceTimer) clearTimeout(previewResizeDebounceTimer);
    previewResizeDebounceTimer = setTimeout(() => {
        previewResizeDebounceTimer = null;
        rerenderPdfPreviewIfNeeded();
    }, PREVIEW_RESIZE_DEBOUNCE_MS);
}

/**
 * 容器尺寸变化时仅重画左侧 PDF（不刷新右侧表格）。
 */
function rerenderPdfPreviewIfNeeded() {
    const previewContainer = getPreviewContainer();
    if (!previewContainer) return;
    if (typeof pdfjsLib === "undefined") return;

    const first = previewContainer.firstElementChild;
    if (first && first.tagName === "IFRAME") return;

    const slot = state.markdownPages[state.currentPageIndex - 1];
    const fromSlotPdf = slotIsPdfPreview(slot);
    const fromBlobPdf =
        Boolean(state.fileUrlForPdf) &&
        state.pdfDoc &&
        state.pdfTotalPages > 0 &&
        !fromSlotPdf;

    if (!fromSlotPdf && !fromBlobPdf) return;

    if (!state.pdfDoc || state.pdfTotalPages <= 0) {
        if (fromSlotPdf) loadLeftPreviewForCurrentIndex();
        return;
    }

    let pageNum = 1;
    if (fromBlobPdf) {
        pageNum = Math.min(state.currentPageIndex, state.pdfTotalPages);
    }

    state.pdfDoc
        .getPage(pageNum)
        .then((page) =>
            renderPdfPageToPreviewCanvas(page, previewContainer).then((canvas) => {
                previewContainer.innerHTML = "";
                previewContainer.appendChild(canvas);
            })
        )
        .catch(() => {
            /* 忽略 */
        });
}

function readResizeObserverEntryWidth(entry) {
    if (entry.borderBoxSize?.length) {
        const b = entry.borderBoxSize[0];
        const w = b.inlineSize;
        if (Number.isFinite(w) && w > 0) return w;
    }
    const cr = entry.contentRect?.width;
    if (Number.isFinite(cr) && cr > 0) return cr;
    return 0;
}

function attachPreviewResizeObserverOnce() {
    if (previewResizeObserver || typeof ResizeObserver === "undefined") return;
    const inner = getPreviewContainer();
    const panel = inner?.parentElement;
    if (!inner || !panel) return;
    previewResizeObserver = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (!entry) return;
        const w = readResizeObserverEntryWidth(entry);
        if (w <= 0) return;
        if (Math.abs(w - lastPreviewPanelObservedWidth) < 2) return;
        lastPreviewPanelObservedWidth = w;
        schedulePdfPreviewRerender();
    });
    previewResizeObserver.observe(panel);
}

/**
 * 将 PDF 单页渲染到 canvas。
 * 采用「逻辑 viewport + devicePixelRatio 放大画布 + render transform」与常见教程一致，
 * 使 backing store 与物理像素对齐，减轻高清屏发糊（参见 devicePixelRatio 适配写法）。
 * @param {object} page pdf.js 页面对象
 * @param {HTMLElement} previewContainer
 * @returns {Promise<HTMLCanvasElement>}
 */
function renderPdfPageToPreviewCanvas(page, previewContainer) {
    return measurePreviewWidth(previewContainer).then((cw) => {
        const rawDpr = typeof window.devicePixelRatio === "number" ? window.devicePixelRatio : 1;
        const dpr = Math.min(Math.max(rawDpr, 1), 4);
        const baseViewport = page.getViewport({ scale: 1 });
        const baseW = baseViewport.width;

        let displayScale = (cw - PREVIEW_PAD_X) / baseW;
        if (!Number.isFinite(displayScale) || displayScale <= 0) displayScale = 1;
        displayScale = Math.min(displayScale, DISPLAY_SCALE_CAP);

        /** 与 CSS 展示一致的逻辑尺寸（pdf.js 默认坐标系） */
        const viewport = page.getViewport({ scale: displayScale });

        /**
         * 输出倍率：至少为 dpr；并可提高栅格密度（超采样 + 最小宽度），
         * 再整体限制在 MAX_CANVAS_EDGE_PX 内。
         */
        let outputScale = Math.max(
            dpr,
            MIN_BACKING_PAGE_WIDTH_PX / viewport.width,
            dpr * RENDER_SUPER_SAMPLE
        );
        outputScale = Math.min(outputScale, dpr * MAX_PIXEL_SCALE_OVER_BASE);

        const maxEdgeLogical = Math.max(viewport.width, viewport.height);
        if (maxEdgeLogical * outputScale > MAX_CANVAS_EDGE_PX) {
            outputScale = MAX_CANVAS_EDGE_PX / maxEdgeLogical;
        }

        const canvas = document.createElement("canvas");
        const ctx = canvas.getContext("2d", { alpha: false });
        const bw = Math.floor(viewport.width * outputScale);
        const bh = Math.floor(viewport.height * outputScale);
        canvas.width = Math.max(1, bw);
        canvas.height = Math.max(1, bh);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;

        ctx.imageSmoothingEnabled = true;
        if ("imageSmoothingQuality" in ctx) ctx.imageSmoothingQuality = "high";

        const renderParams = {
            canvasContext: ctx,
            viewport,
        };
        if (Math.abs(outputScale - 1) > 1e-6) {
            renderParams.transform = [outputScale, 0, 0, outputScale, 0, 0];
        }

        return page.render(renderParams).promise.then(() => canvas);
    });
}

export function resetPagination() {
    state.pdfDoc = null;
    state.pdfTotalPages = 0;
    state.currentPageIndex = 1;
    state.markdownPages = [];
    state.fileUrlForPdf = null;
    state.currentTaskId = null;
    state.isVerified = false;
    state.lastQueuePosition = -1;
    state.cnc0SecondBlockLocked = false;
    if (pageNav) pageNav.style.display = "none";
    if (verifyBar) verifyBar.style.display = "none";
    if (segmentNav) segmentNav.style.display = "none";
}

/** 根据 state.currentTaskId 重算在待验证队列中的下标。 */
export function syncQueuePositionForCurrentTask() {
    if (state.currentTaskId == null) {
        state.queuePosition = -1;
        return;
    }
    state.queuePosition = state.unverifiedTaskIds.indexOf(state.currentTaskId);
}

/** 当前 data.pages 是否均为同一 task_id（用于显示分段导航）。 */
function allMarkdownPagesSameTask() {
    if (state.markdownPages.length <= 1) return false;
    const tid = state.markdownPages[0]?.task_id;
    if (tid == null) return false;
    return state.markdownPages.every((p) => p && p.task_id === tid);
}

export async function refreshUnverifiedQueue() {
    try {
        const response = await fetch("/api/tasks/unverified-queue");
        const data = await response.json().catch(() => ({}));
        if (response.ok && data.success && Array.isArray(data.task_ids)) {
            state.unverifiedTaskIds = data.task_ids;
            syncQueuePositionForCurrentTask();
        }
    } catch {
        /* 忽略 */
    }
}

/** 本地多页 PDF 未提交解析时的预览分页 */
export function showPdfPreviewNavigation() {
    if (!pageNav || state.pdfTotalPages <= 1) return;
    pageNav.style.display = "flex";
    updatePageInfo();
}

/**
 * OCR 结果已加载：显示导航（不少于 1 个任务也显示队列位置）。
 */
export function showOcrTaskNavigation() {
    if (!pageNav || state.markdownPages.length === 0) return;
    pageNav.style.display = "flex";
    updatePageInfo();
}

export function updatePageInfo() {
    if (!pageInfo) return;

    if (state.markdownPages.length === 0 && state.pdfTotalPages > 1 && state.fileUrlForPdf) {
        pageInfo.textContent = `预览 第 ${state.currentPageIndex} / ${state.pdfTotalPages} 页`;
        if (btnPrevTask) {
            btnPrevTask.disabled = state.currentPageIndex <= 1;
            btnPrevTask.textContent = "上一页";
        }
        if (btnNextTask) {
            btnNextTask.disabled = state.currentPageIndex >= state.pdfTotalPages;
            btnNextTask.textContent = "下一页";
        }
        if (segmentNav) segmentNav.style.display = "none";
        return;
    }

    if (btnPrevTask) btnPrevTask.textContent = "上一任务";
    if (btnNextTask) btnNextTask.textContent = "下一任务";

    if (state.markdownPages.length === 0) {
        return;
    }

    const qLen = state.unverifiedTaskIds.length;
    const inQueue =
        state.currentTaskId != null &&
        state.queuePosition >= 0 &&
        state.queuePosition < qLen &&
        state.unverifiedTaskIds[state.queuePosition] === state.currentTaskId;

    if (qLen > 0 && inQueue) {
        pageInfo.textContent = `待验证 ${state.queuePosition + 1} / ${qLen} · 任务 #${state.currentTaskId}`;
    } else if (state.currentTaskId != null) {
        pageInfo.textContent =
            qLen > 0 ? `任务 #${state.currentTaskId}（不在待验证队列）` : `任务 #${state.currentTaskId}`;
    } else pageInfo.textContent = "待验证队列";

    if (inQueue) {
        if (btnPrevTask) btnPrevTask.disabled = state.queuePosition <= 0;
        if (btnNextTask) btnNextTask.disabled = state.queuePosition >= qLen - 1;
    } else if (qLen > 0 && state.lastQueuePosition >= 0) {
        if (btnPrevTask) btnPrevTask.disabled = state.lastQueuePosition <= 0;
        if (btnNextTask) btnNextTask.disabled = state.lastQueuePosition >= qLen;
    } else {
        if (btnPrevTask) btnPrevTask.disabled = true;
        if (btnNextTask) btnNextTask.disabled = true;
    }

    const showSeg = allMarkdownPagesSameTask();
    if (segmentNav) segmentNav.style.display = showSeg ? "flex" : "none";
    if (showSeg && segmentInfo) {
        segmentInfo.textContent =
            `分段 ${state.currentPageIndex} / ${state.markdownPages.length}（验证仅针对本段）`;
    }
    if (btnPrevSegment) btnPrevSegment.disabled = !showSeg || state.currentPageIndex <= 1;
    if (btnNextSegment) btnNextSegment.disabled = !showSeg || state.currentPageIndex >= state.markdownPages.length;
}

export function goToMainNavPrev() {
    if (state.markdownPages.length === 0 && state.pdfTotalPages > 1 && state.fileUrlForPdf) {
        if (state.currentPageIndex <= 1) return;
        state.currentPageIndex--;
        renderCurrentPage();
        updatePageInfo();
        return;
    }
    if (state.markdownPages.length === 0) return;
    void goToPrevTask();
}

export function goToMainNavNext() {
    if (state.markdownPages.length === 0 && state.pdfTotalPages > 1 && state.fileUrlForPdf) {
        if (state.currentPageIndex >= state.pdfTotalPages) return;
        state.currentPageIndex++;
        renderCurrentPage();
        updatePageInfo();
        return;
    }
    if (state.markdownPages.length === 0) return;
    void goToNextTask();
}

export async function goToPrevTask() {
    if (state.queuePosition > 0) {
        await loadTaskResult(state.unverifiedTaskIds[state.queuePosition - 1]);
        return;
    }
    if (state.queuePosition < 0 && state.lastQueuePosition > 0) {
        const idx = state.lastQueuePosition - 1;
        if (idx < state.unverifiedTaskIds.length) {
            await loadTaskResult(state.unverifiedTaskIds[idx]);
        }
    }
}

export async function goToNextTask() {
    if (state.queuePosition >= 0 && state.queuePosition < state.unverifiedTaskIds.length - 1) {
        await loadTaskResult(state.unverifiedTaskIds[state.queuePosition + 1]);
        return;
    }
    if (state.queuePosition < 0 && state.lastQueuePosition >= 0) {
        const idx = state.lastQueuePosition;
        if (idx < state.unverifiedTaskIds.length) {
            await loadTaskResult(state.unverifiedTaskIds[idx]);
        }
    }
}

export function goToPrevSegment() {
    if (state.currentPageIndex <= 1) return;
    state.currentPageIndex--;
    updateCurrentTaskId();
    renderCurrentPage();
    updatePageInfo();
}

export function goToNextSegment() {
    if (!allMarkdownPagesSameTask()) return;
    if (state.currentPageIndex >= state.markdownPages.length) return;
    state.currentPageIndex++;
    updateCurrentTaskId();
    renderCurrentPage();
    updatePageInfo();
}

export function updateCurrentTaskId() {
    const page = state.markdownPages[state.currentPageIndex - 1];
    state.currentTaskId = page?.task_id || null;
    state.isVerified = page?.is_verified ?? false;
    updateVerifyBar();
}

/** 左侧预览：优先当前槽位 pages[i].file_url（与 task 一致），否则回退本地整本 PDF blob。 */
export function loadLeftPreviewForCurrentIndex() {
    const previewContainer = getPreviewContainer();
    if (!previewContainer) return;

    const slot = state.markdownPages[state.currentPageIndex - 1];

    if (slot && slot.file_url) {
        const abs = new URL(slot.file_url, window.location.origin).href;
        const ftype = (slot.file_type || "").toLowerCase();

        if (ftype === "pdf" || /\.pdf$/i.test(abs)) {
            if (typeof pdfjsLib !== "undefined") {
                pdfjsLib.getDocument({ url: abs }).promise
                    .then((pdf) => {
                        state.pdfDoc = pdf;
                        state.pdfTotalPages = pdf.numPages;
                        return pdf.getPage(1);
                    })
                    .then((page) =>
                        renderPdfPageToPreviewCanvas(page, previewContainer).then((canvas) => {
                            previewContainer.innerHTML = "";
                            previewContainer.appendChild(canvas);
                        })
                    )
                    .catch(() => {
                        previewContainer.innerHTML =
                            `<iframe src="${abs}" title="PDF 预览"></iframe>`;
                    });
            } else {
                previewContainer.innerHTML =
                    `<iframe src="${abs}" title="PDF 预览"></iframe>`;
            }
            return;
        }

        if (["png", "jpg", "jpeg", "webp"].includes(ftype)) {
            previewContainer.innerHTML = `<img src="${abs}" alt="预览">`;
            state.pdfDoc = null;
            state.pdfTotalPages = 0;
            return;
        }

        previewContainer.innerHTML = `<img src="${abs}" alt="预览">`;
        state.pdfDoc = null;
        state.pdfTotalPages = 0;
        return;
    }

    if (state.pdfDoc && state.pdfTotalPages > 0 && state.fileUrlForPdf) {
        const pageNum = Math.min(state.currentPageIndex, state.pdfTotalPages);
        state.pdfDoc.getPage(pageNum).then((page) => {
            renderPdfPageToPreviewCanvas(page, previewContainer).then((canvas) => {
                previewContainer.innerHTML = "";
                previewContainer.appendChild(canvas);
            });
        }).catch(() => {
            previewContainer.innerHTML = '<p class="empty-tip">无法渲染该页</p>';
        });
    }
}

export function renderCurrentPage() {
    loadLeftPreviewForCurrentIndex();

    if (state.markdownPages.length > 0) {
        const pageContent = state.markdownPages[state.currentPageIndex - 1]?.markdown
            ?? state.markdownPages[state.currentPageIndex - 1]
            ?? state.markdownPages[state.markdownPages.length - 1]?.markdown
            ?? state.markdownPages[state.markdownPages.length - 1];
        renderOcrTableEditor(pageContent);
    }
}

export function updateVerifyBar() {
    if (!verifyBar) return;
    if (!state.currentTaskId) {
        verifyBar.style.display = "none";
        return;
    }
    verifyBar.style.display = "flex";
    if (verifyStatus) {
        verifyStatus.textContent = state.isVerified
            ? "已验证（可修改后再次通过）"
            : "待验证";
    }
    if (btnVerify) {
        btnVerify.disabled = false;
        btnVerify.textContent = state.isVerified ? "再次通过" : "通过";
    }
}

/** 从 API 加载指定任务的解析结果并刷新左右栏与导航。 */
export async function loadTaskResult(taskId) {
    try {
        setStatus("加载中...");
        resetPagination();
        const response = await fetch(`/api/task/${taskId}/result`);
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.message || "加载失败");
        }
        state.markdownPages = data.pages || [];
        state.currentPageIndex = 1;
        state.currentTaskId = data.task_id;
        state.isVerified = data.is_verified ?? false;

        const slotHasUrl =
            state.markdownPages.length > 0 && Boolean(state.markdownPages[0].file_url);
        if (slotHasUrl) {
            state.fileUrlForPdf = null;
            state.pdfDoc = null;
            state.pdfTotalPages = 0;
        }

        syncQueuePositionForCurrentTask();
        showOcrTaskNavigation();
        updateVerifyBar();
        updatePageInfo();
        renderCurrentPage();

        setStatus(`已加载任务 #${taskId}，共 ${state.markdownPages.length} 个分段`);
    } catch (error) {
        setStatus(error.message || "加载失败", true);
        const metaLoadErr = getOcrResultMeta();
        if (metaLoadErr) metaLoadErr.innerHTML = "";
        setOcrTablesMessage('<p class="empty-tip">暂无内容</p>');
        if (verifyBar) verifyBar.style.display = "none";
    }
}
export function renderFilePreview(file) {
    const previewContainer = getPreviewContainer();
    if (!previewContainer) return;
    if (!file) {
        previewContainer.innerHTML = '<p class="empty-tip">上传后将在这里预览图片或 PDF。</p>';
        return;
    }

    const extension = file.name.split(".").pop().toLowerCase();
    const blobUrl = URL.createObjectURL(file);
    state.fileUrlForPdf = extension === "pdf" ? blobUrl : null;

    if (["png", "jpg", "jpeg", "webp"].includes(extension)) {
        previewContainer.innerHTML = `<img src="${blobUrl}" alt="上传预览">`;
        return;
    }

    if (extension === "pdf") {
        if (typeof pdfjsLib === "undefined") {
            previewContainer.innerHTML = `<iframe src="${blobUrl}" title="PDF 预览"></iframe>`;
            return;
        }
        pdfjsLib.getDocument({ url: blobUrl }).promise
            .then((pdf) => {
                state.pdfDoc = pdf;
                state.pdfTotalPages = pdf.numPages;
                state.currentPageIndex = 1;
                if (state.pdfTotalPages > 1) {
                    showPdfPreviewNavigation();
                    renderCurrentPage();
                } else {
                    state.pdfDoc.getPage(1).then((page) => {
                        renderPdfPageToPreviewCanvas(page, previewContainer).then((canvas) => {
                            previewContainer.innerHTML = "";
                            previewContainer.appendChild(canvas);
                        });
                    });
                }
            })
            .catch(() => {
                previewContainer.innerHTML = `<iframe src="${blobUrl}" title="PDF 预览"></iframe>`;
            });
        return;
    }

    previewContainer.innerHTML = '<p class="empty-tip">当前文件类型暂不支持预览。</p>';
}

/**
 * 页面初始化：同步待验证队列；若 URL/模板注入预设 task_id 则加载该任务。
 * 依赖 window.OCR_PRESET_TASK_ID（模板内联）。
 * @returns {Promise<void>}
 */
export async function initOcrPageQueue() {
    attachPreviewResizeObserverOnce();
    await refreshUnverifiedQueue();
    if (window.OCR_PRESET_TASK_ID) {
        await loadTaskResult(window.OCR_PRESET_TASK_ID);
    }
}

if (typeof window !== "undefined") {
    window.addEventListener("beforeunload", () => {
        if (previewResizeDebounceTimer) {
            clearTimeout(previewResizeDebounceTimer);
            previewResizeDebounceTimer = null;
        }
        if (previewResizeObserver) {
            previewResizeObserver.disconnect();
            previewResizeObserver = null;
        }
        lastPreviewPanelObservedWidth = 0;
    });
}
