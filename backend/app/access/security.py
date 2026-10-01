"""账号密码、会话与角色授权。"""

import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import AuthSession, User, UserRole, RolePermission
from app.core.orm import orm_session

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    # 每个账号使用独立盐值；scrypt 可直接由 Python 标准库提供。
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(actual, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    # 数据库仅保存令牌摘要，客户端持有的原始令牌不落盘。
    return hashlib.sha256(token.encode()).hexdigest()


def user_details(db: Session, user_id: int) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "登录已失效，请重新登录")
    roles = list(db.scalars(select(UserRole.role_code).where(UserRole.user_id == user_id).order_by(UserRole.role_code)))
    permissions = list(db.scalars(select(RolePermission.permission_code)
        .join(UserRole, UserRole.role_code == RolePermission.role_code)
        .where(UserRole.user_id == user_id).distinct().order_by(RolePermission.permission_code)))
    return {"id": user.id, "username": user.username, "is_active": bool(user.is_active),
            "roles": roles, "permissions": permissions,
            "full_name": user.full_name, "employee_no": user.employee_no, "phone": user.phone}


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "请先登录")
    with orm_session() as db:
        row = db.get(AuthSession, token_hash(credentials.credentials))
        if row is None or row.expires_at <= int(time.time()):
            raise HTTPException(401, "登录已失效，请重新登录")
        user = user_details(db, row.user_id)
        # 禁用账号即使持有尚未到期的令牌，也不能继续调用业务接口。
        if not user["is_active"]:
            raise HTTPException(401, "账号已停用")
        return user


def require(permission: str):
    # 权限判断始终在服务端执行，界面状态不能替代授权。
    def check(user: dict = Depends(current_user)) -> dict:
        if permission not in user["permissions"]:
            raise HTTPException(403, "没有执行此操作的权限")
        # 可读总账、往来或结账证据的岗位必须另获全部销售金额授权，防止从财务旁路读取。
        money_permissions = {'finance.view','finance.record','finance.reverse','journal.view',
            'opening_balance.view','accounting_period.closing_view','accounting_period.close','accounting_period.reopen'}
        if (permission in money_permissions or permission.startswith(('journal.', 'opening_balance.', 'business_journal.', 'profit_transfer.'))) and 'admin' not in user['roles'] and 'sales_amount.all' not in user['permissions']:
            raise HTTPException(403, '没有查看全部销售金额的权限')
        return user
    return check
