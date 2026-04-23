from __future__ import annotations

"""OCR 结果模型，保存任务对应的 Markdown。"""

from sqlalchemy import Boolean, Column, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from extensions import Base


class OcrResult(Base):
    """记录 OCR 结果正文。"""
    __tablename__ = "ocr_result"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("ocr_task.id"), nullable=False, index=True)
    markdown_content = Column(Text, nullable=False)
    verified_markdown = Column(Text, nullable=True)
    is_verified = Column(Boolean, nullable=False, default=False, index=True)

    task = relationship("OcrTask", back_populates="results")
