"""外部 OCR 服务客户端，统一封装请求参数和结果解析。"""

import io
import time
import uuid
import zipfile
from pathlib import Path

import requests
from requests.exceptions import SSLError


class OcrClient:
    """负责向外部 OCR 接口发送文件并提取 Markdown 结果。"""
    def __init__(
        self,
        api_url: str,
        api_token: str,
        model_version: str = "vlm",
        language: str = "ch",
        timeout: int = 120,
        poll_interval: int = 2,
    ):
        self.api_url = api_url.rstrip("/")
        self.api_token = api_token
        self.model_version = model_version
        self.language = language
        self.timeout = timeout
        self.poll_interval = poll_interval

    def parse_file(self, file_path: str) -> dict:
        """上传本地文件到 OCR 服务，并返回标准化结果。"""
        path = Path(file_path)
        started = time.perf_counter()
        data_id = uuid.uuid4().hex
        batch_data = self._create_batch(path, data_id)
        upload_url = self._extract_upload_url(batch_data)
        batch_id = batch_data["batch_id"]

        self._upload_file(upload_url, path)
        result_data = self._poll_batch_result(batch_id, path.name, data_id)
        zip_url = result_data.get("full_zip_url")
        if not zip_url:
            raise ValueError("MinerU 未返回结果压缩包地址。")

        markdown = self._download_markdown(zip_url)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "markdown": markdown,
            "raw_json": {
                "batch_id": batch_id,
                "batch_create": batch_data,
                "batch_result": result_data,
                "full_zip_url": zip_url,
            },
            "elapsed_ms": elapsed_ms,
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }

    def _create_batch(self, path: Path, data_id: str) -> dict:
        response = requests.post(
            f"{self.api_url}/file-urls/batch",
            headers=self._headers(),
            json={
                "files": [
                    {
                        "name": path.name,
                        "data_id": data_id,
                        "is_ocr": True,
                    }
                ],
                "model_version": self.model_version,
                "language": self.language,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        self._ensure_success(data, "申请上传地址失败")
        return data["data"]

    def _extract_upload_url(self, batch_data: dict) -> str:
        file_urls = batch_data.get("file_urls") or batch_data.get("files") or []
        if not file_urls:
            raise ValueError("MinerU 未返回上传地址。")
        return file_urls[0]

    def _upload_file(self, upload_url: str, path: Path) -> None:
        with path.open("rb") as file_handle:
            response = requests.put(upload_url, data=file_handle, timeout=self.timeout)
        response.raise_for_status()

    def _poll_batch_result(self, batch_id: str, file_name: str, data_id: str) -> dict:
        deadline = time.monotonic() + self.timeout
        last_state = "waiting-file"

        while time.monotonic() < deadline:
            response = requests.get(
                f"{self.api_url}/extract-results/batch/{batch_id}",
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            self._ensure_success(payload, "查询解析结果失败")
            result = self._match_result(payload["data"].get("extract_result", []), file_name, data_id)
            if result:
                last_state = result.get("state", last_state)
                if last_state == "done":
                    return result
                if last_state == "failed":
                    raise ValueError(result.get("err_msg") or "MinerU 解析失败。")
            time.sleep(self.poll_interval)

        raise TimeoutError(f"MinerU 处理超时，最后状态：{last_state}")

    def _match_result(self, results: list[dict], file_name: str, data_id: str) -> dict | None:
        for result in results:
            if result.get("data_id") == data_id:
                return result
        for result in results:
            if result.get("file_name") == file_name:
                return result
        return results[0] if results else None

    def _download_with_retry(self, zip_url: str) -> bytes:
        """下载 ZIP，遇到 SSL 错误时重试并尝试禁用证书验证。"""
        for attempt in range(3):
            try:
                verify = attempt == 0  # 首次使用默认验证，后续关闭以应对 CDN SSL 兼容性问题
                response = requests.get(
                    zip_url,
                    timeout=self.timeout,
                    verify=verify,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                )
                response.raise_for_status()
                return response.content
            except SSLError:
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
        raise RuntimeError("下载失败")

    def _download_markdown(self, zip_url: str) -> str:
        content = self._download_with_retry(zip_url)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            markdown_files = [
                name for name in archive.namelist()
                if name.lower().endswith(".md") and not name.endswith("/")
            ]
            if not markdown_files:
                raise ValueError("MinerU 结果压缩包中未找到 Markdown 文件。")
            markdown_files.sort()
            with archive.open(markdown_files[0]) as file_handle:
                return file_handle.read().decode("utf-8").strip()

    def _ensure_success(self, payload: dict, default_message: str) -> None:
        if payload.get("code") != 0:
            raise ValueError(payload.get("msg") or default_message)
