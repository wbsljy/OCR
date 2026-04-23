/**
 * OCR 页面入口（ES Module）：上传表单、分页与分段按钮、验证提交、统计页任务行跳转、初始化队列。
 * 依赖：ocr-state、ocr-dom、ocr-utils-html、ocr-table-editor、ocr-board-validation、ocr-preview-nav。
 * 全局：window.OCR_PRESET_TASK_ID（模板）；pdfjsLib 由 ocr.html 先于本模块加载。
 */

import { state } from "./ocr-state.js";
import {
    form,
    fileInput,
    btnPrevTask,
    btnNextTask,
    btnPrevSegment,
    btnNextSegment,
    btnVerify,
    verifyBar,
    getPreviewContainer,
    getOcrResultMeta,
    setStatus,
} from "./ocr-dom.js";
import { setOcrTablesMessage } from "./ocr-utils-html.js";
import { renderOcrTableEditor } from "./ocr-table-editor.js";
import { collectVerifiedMarkdown, runBoardValidationBeforeSubmit } from "./ocr-board-validation.js";
import {
    goToMainNavNext,
    goToMainNavPrev,
    goToNextSegment,
    goToPrevSegment,
    initOcrPageQueue,
    loadTaskResult,
    refreshUnverifiedQueue,
    renderCurrentPage,
    renderFilePreview,
    resetPagination,
    showOcrTaskNavigation,
    syncQueuePositionForCurrentTask,
    updatePageInfo,
    updateVerifyBar,
} from "./ocr-preview-nav.js";

if (form && fileInput) {
    fileInput.addEventListener("change", () => {
        const file = fileInput.files[0];
        resetPagination();
        renderFilePreview(file);
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = fileInput?.files?.[0];
        if (!file) {
            setStatus("请先选择文件", true);
            return;
        }

        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) submitBtn.disabled = true;
        setStatus("OCR 解析中...");
        resetPagination();
        const metaEl = getOcrResultMeta();
        if (metaEl) metaEl.innerHTML = "";
        setOcrTablesMessage('<p class="empty-tip">解析中...</p>');

        const payload = new FormData();
        payload.append("file", file);

        try {
            const response = await fetch("/api/parse", {
                method: "POST",
                body: payload,
            });
            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.message || "解析失败");
            }

            const ext = file.name.split(".").pop().toLowerCase();
            state.markdownPages = data.pages || (data.markdown ? [{ markdown: data.markdown }] : []);
            state.currentPageIndex = 1;
            state.currentTaskId =
                state.markdownPages[0]?.task_id ?? data.task_ids?.[0] ?? data.task_id ?? null;
            state.isVerified = state.markdownPages[0]?.is_verified ?? false;

            const useServerPageUrls =
                state.markdownPages.length > 0 && Boolean(state.markdownPages[0].file_url);
            const previewContainer = getPreviewContainer();

            if (useServerPageUrls) {
                state.fileUrlForPdf = null;
                state.pdfDoc = null;
                state.pdfTotalPages = 0;
            } else if (ext === "pdf") {
                state.fileUrlForPdf = URL.createObjectURL(file);
                if (!previewContainer) {
                    state.fileUrlForPdf = null;
                } else if (typeof pdfjsLib === "undefined") {
                    previewContainer.innerHTML =
                        `<iframe src="${state.fileUrlForPdf}" title="PDF 预览"></iframe>`;
                } else {
                    try {
                        state.pdfDoc = await pdfjsLib.getDocument({ url: state.fileUrlForPdf }).promise;
                        state.pdfTotalPages = state.pdfDoc.numPages;
                    } catch {
                        state.pdfTotalPages = state.markdownPages.length;
                        previewContainer.innerHTML =
                            `<iframe src="${state.fileUrlForPdf}" title="PDF 预览"></iframe>`;
                    }
                }
            } else if (previewContainer) {
                previewContainer.innerHTML =
                    `<img src="${URL.createObjectURL(file)}" alt="上传预览">`;
            }

            await refreshUnverifiedQueue();
            syncQueuePositionForCurrentTask();
            showOcrTaskNavigation();
            updateVerifyBar();
            updatePageInfo();
            renderCurrentPage();

            setStatus(`解析完成，共 ${state.markdownPages.length} 个任务，耗时 ${data.elapsed_ms || 0} ms`);
        } catch (error) {
            setStatus(error.message || "OCR 服务调用失败。", true);
            const metaErr = getOcrResultMeta();
            if (metaErr) metaErr.innerHTML = "";
            setOcrTablesMessage('<p class="empty-tip">暂无内容</p>');
        } finally {
            if (submitBtn) submitBtn.disabled = false;
        }
    });
}

if (btnPrevTask) btnPrevTask.addEventListener("click", goToMainNavPrev);
if (btnNextTask) btnNextTask.addEventListener("click", goToMainNavNext);
if (btnPrevSegment) btnPrevSegment.addEventListener("click", goToPrevSegment);
if (btnNextSegment) btnNextSegment.addEventListener("click", goToNextSegment);

document.querySelectorAll(".task-row-clickable").forEach((row) => {
    row.addEventListener("click", () => {
        const taskId = row.dataset.taskId;
        if (taskId) loadTaskResult(parseInt(taskId, 10));
    });
});

async function postVerify(taskId, verifiedMarkdown, forceOverwrite) {
    const resp = await fetch(`/api/task/${taskId}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            verified_markdown: verifiedMarkdown,
            force_overwrite: Boolean(forceOverwrite),
        }),
    });
    const data = await resp.json().catch(() => ({}));
    return { resp, data };
}

if (btnVerify) {
    btnVerify.addEventListener("click", async () => {
        try {
            if (!state.currentTaskId) {
                setStatus("当前页缺少任务 ID，无法提交。", true);
                return;
            }
            setStatus("正在进行前端校验...");
            const validation = runBoardValidationBeforeSubmit();
            if (!validation.ok) {
                setStatus(
                    validation.message ||
                        `校验未通过：有 ${validation.errorCount} 个单元格格式不符，已标红。`,
                    true
                );
                if (validation.focusTarget) {
                    validation.focusTarget.scrollIntoView({ behavior: "smooth", block: "nearest" });
                }
                return;
            }

            const payload = collectVerifiedMarkdown();
            if (!payload.trim()) {
                setStatus("识别表格区为空，无法提交校对稿。", true);
                return;
            }

            btnVerify.disabled = true;
            setStatus("前端校验通过，正在提交...");
            let { resp, data } = await postVerify(state.currentTaskId, payload, false);

            if (resp.status === 409 && data.code === "dashboard_duplicate") {
                const ok = window.confirm(
                    data.message || "数据库中已有相同业务键的看板记录，是否覆盖？"
                );
                if (!ok) {
                    setStatus("已取消，未写入。", true);
                    btnVerify.disabled = false;
                    return;
                }
                setStatus("正在覆盖并提交...");
                ({ resp, data } = await postVerify(state.currentTaskId, payload, true));
            }

            if (resp.ok && data.success) {
                state.isVerified = true;
                const page = state.markdownPages[state.currentPageIndex - 1];
                if (page && typeof page === "object") {
                    page.is_verified = true;
                    page.markdown = payload;
                }
                renderOcrTableEditor(payload);
                updateVerifyBar();
                btnVerify.disabled = false;
                state.lastQueuePosition = state.queuePosition;
                void refreshUnverifiedQueue().then(() => {
                    syncQueuePositionForCurrentTask();
                    updatePageInfo();
                });
                setStatus("已保存校对稿并标记为通过验证");
            } else {
                const msg =
                    data.message ||
                    (Array.isArray(data.detail) ? data.detail.map((d) => d.msg).join(" ") : null) ||
                    data.detail ||
                    "验证失败";
                setStatus(String(msg), true);
                btnVerify.disabled = false;
            }
        } catch (e) {
            console.error("verify submit failed:", e);
            setStatus(e?.message ? `前端校验异常：${e.message}` : "验证请求失败", true);
            btnVerify.disabled = false;
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => void initOcrPageQueue());
} else {
    void initOcrPageQueue();
}
