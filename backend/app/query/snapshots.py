"""有界、短期、按账号授权隔离的查询快照，分页与导出使用同一份结果。"""
from collections import OrderedDict
import json
from copy import deepcopy
from secrets import token_urlsafe
from threading import RLock
from time import monotonic
from fastapi import HTTPException

_lock=RLock()
_snapshots=OrderedDict()
# 同时限制数量、行数及寿命；服务重启后客户端必须重新查询，不伪造旧结果。
MAX_SNAPSHOTS=32
MAX_ROWS=200000
TTL=900


def identity(user):
    return (user['id'],tuple(sorted(user['roles'])),tuple(sorted(user['permissions'])))


def create_snapshot(result: dict, user: dict) -> str:
    rows=sum(len(value) for value in result.values() if isinstance(value,list))
    if rows>MAX_ROWS or len(json.dumps(result,ensure_ascii=False).encode('utf-8'))>8*1024*1024:
        raise HTTPException(422,'查询范围过大，请缩小日期或物料范围')
    token=token_urlsafe(24)
    with _lock:
        now=monotonic()
        for key in list(_snapshots):
            if now-_snapshots[key][0]>TTL: del _snapshots[key]
        while len(_snapshots)>=MAX_SNAPSHOTS: _snapshots.popitem(last=False)
        _snapshots[token]=(now,identity(user),deepcopy(result))
    return token


def read_snapshot(token: str, user: dict) -> dict:
    with _lock:
        item=_snapshots.get(token)
        if not item or monotonic()-item[0]>TTL or item[1]!=identity(user):
            raise HTTPException(409,'查询快照已失效或授权已变化，请重新查询')
        return item[2]


def snapshot_metadata(result: dict, user: dict, paths: tuple[str,...]) -> dict:
    token=create_snapshot(result,user)
    metadata=deepcopy(result)
    for path in paths:
        target=metadata
        parts=path.split('.')
        for part in parts[:-1]:
            target=target.get(part) if isinstance(target,dict) else None
        if isinstance(target,dict) and isinstance(target.get(parts[-1]),list): target[parts[-1]]=[]
    metadata.update(snapshot_id=token)
    # 导出内容只在显式点击导出时返回，分页查询不夹带全量 CSV。
    metadata['csv']=''
    return metadata
