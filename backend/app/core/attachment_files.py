"""业务附件共用的文件名、内容与撤销原因校验。"""

import base64
import binascii
import re

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS = 10
FORMATS = {
    '.pdf': 'application/pdf',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
}


def safe_name(value: str) -> str:
    name = value.strip()
    if (not name or len(name) > 120 or name in ('.', '..') or name.endswith('.')
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)):
        raise ValueError('附件文件名无效')
    if not any(name.lower().endswith(suffix) for suffix in FORMATS):
        raise ValueError('仅支持 PDF、PNG 和 JPEG 附件')
    return name


class AttachmentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_name: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(min_length=1, max_length=6_990_508)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('file_name')
    @classmethod
    def valid_file_name(cls, value: str) -> str:
        return safe_name(value)

    @field_validator('reason')
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('附件依据不能为空')
        return value.strip()


class ReversalInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def valid_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('撤销原因不能为空')
        return value.strip()


def decode_content(data: AttachmentInput) -> tuple[bytes, str]:
    try:
        content = base64.b64decode(data.content_base64, validate=True)
    except binascii.Error:
        raise HTTPException(422, '附件内容须为 Base64 编码') from None
    if not content or len(content) > MAX_BYTES:
        raise HTTPException(422, '附件须为非空且不超过 5 MiB')
    suffix = '.' + data.file_name.rsplit('.', 1)[-1].lower()
    media_type = FORMATS[suffix]
    valid = (content.startswith(b'%PDF-') and b'%%EOF' in content[-1024:]
        if media_type == 'application/pdf' else
        content.startswith(b'\x89PNG\r\n\x1a\n')
        if media_type == 'image/png' else
        content.startswith(b'\xff\xd8\xff') and content.endswith(b'\xff\xd9'))
    if not valid:
        raise HTTPException(422, '附件内容与文件格式不符')
    return content, media_type
