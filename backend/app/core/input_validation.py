"""写操作原因和通用字典边界校验，不依赖业务路由。"""
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field,field_validator,ValidationError

class Reason(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reason:str=Field(min_length=1,max_length=200)
    @field_validator('reason')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():raise ValueError('请填写原因')
        return value.strip()

def parse(model,payload):
    try:return model.model_validate(payload)
    except ValidationError as error:raise HTTPException(422,error.errors(include_context=False)) from None
