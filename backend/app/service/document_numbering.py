"""首次管理员设置实例级单据编号；业务写入门槛在路由边界统一执行。"""

from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import OperationalError

from app.access.security import current_user
from app.core.document_numbering import configuration, configuration_data, save_configuration
from app.core.orm import orm_session

router = APIRouter(prefix='/api/v1/system/document-numbering')


class NumberingInput(BaseModel):
    style: Literal['pinyin', 'english']
    timezone_mode: Literal['server', 'utc', 'specified']
    timezone: str | None = Field(default=None, max_length=100)
    version: int = Field(ge=0, strict=True)


@router.get('')
def get_configuration(_: dict = Depends(current_user)) -> dict:
    with orm_session() as db:
        return configuration_data(db)


@router.put('')
def configure(payload: NumberingInput, user: dict = Depends(current_user)) -> dict:
    if 'admin' not in user['roles']:
        raise HTTPException(403, '仅管理员可以设置实例编号规则')
    try:
        with orm_session(write=True) as db:
            return save_configuration(db, payload, user)
    except OperationalError as error:
        # 大库补号可能超过 SQLite 等待时间，第二位管理员应收到可重试的冲突。
        if 'locked' in str(error.orig).lower():
            raise HTTPException(409, '其他管理员或业务事务正在处理，请稍后重新读取编号规则') from None
        raise


def require_numbering(request: Request):
    path = request.url.path.removeprefix('/api/v1/')
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    # 查询型 POST 不改变业务；账号管理和编号设置必须在未配置时仍可完成。
    if path.split('/')[0] in ('auth', 'setup', 'users', 'roles', 'permissions', 'menu-icons', 'system'):
        return
    if path.endswith(('/query', '/preview', '/check', '/forecast', '/export', '/download', '/options')):
        return
    with orm_session() as db:
        record = configuration(db)
        if not record or not record.style:
            raise HTTPException(409, '请先由管理员设置单据编号规则，当前仅可查询业务数据')
