from __future__ import annotations

"""OCR 任务模型，保存一次上传与解析流程的元信息。"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from extensions import Base, now_beijing_naive


class OcrTask(Base):
    """记录文件落盘、处理状态和耗时。每条 task 对应一个已保存的识别单元（单页 PDF 或单图）。"""
    __tablename__ = "ocr_task"

    id = Column(Integer, primary_key=True)
    stored_file_name = Column(String(255), nullable=False)
    file_path = Column(String(1024), nullable=False)
    file_type = Column(String(32), nullable=False, index=True)
    file_size = Column(BigInteger, nullable=False)
    status = Column(String(32), nullable=False, default="uploaded", index=True)
    error_message = Column(Text, nullable=True)
    ocr_elapsed_ms = Column(Integer, nullable=True)
    created_at = Column(
        DateTime,
        default=now_beijing_naive,
        nullable=False,
        index=True,
    )

    results = relationship(
        "OcrResult",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
