"""往来期初、银行核对、辅助核算及管理财务报表；不自动生成业务凭证。"""
import csv
import json
from io import StringIO
from decimal import Decimal
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.access.security import require
from app.core.orm import orm_session, model_data, add_model
from app.core.models import (PartyOpening, PartyOpeningPayment, BankStatement, BankMatch, FinanceToolAudit,
    Customer, Supplier, LedgerAccount, Journal, JournalLine, JournalAuxiliary, ProfitTransfer, PaymentRecord)
from app.core.period_lock import ensure_date_unlocked
from app.finance.ledger_reports import LedgerReportQuery, trial_balance, confirmed_opening_lines
from app.finance.ledger import PeriodInput
from app.query.snapshots import snapshot_metadata
from app.reports.routes import csv_value

router=APIRouter(prefix='/api/v1/finance/tools')
ZERO=Decimal(0)


class ToolInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: Literal['openings','create_opening','confirm_opening','cancel_opening','settle_opening',
        'banks','import_bank','match_bank','unmatch_bank','reconcile','statements','auxiliary','history']
    payload: dict = Field(default_factory=dict)


class Reason(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reason: str = Field(min_length=1,max_length=200)
    @field_validator('reason')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():raise ValueError('请填写原因')
        return value.strip()


class Identity(Reason):
    id: int = Field(gt=0,strict=True)


class OpeningInput(Reason):
    kind: Literal['receivable','payable']
    party_id: int = Field(gt=0,strict=True)
    effective_date: str
    amount: Decimal = Field(ge=-999999999999,le=999999999999,decimal_places=2)
    ledger_account_id: int = Field(gt=0,strict=True)
    reference: str = Field(min_length=1,max_length=100)
    @field_validator('effective_date')
    @classmethod
    def date(cls,value): return PeriodInput.valid_date(value)


class Settlement(Identity):
    amount: Decimal = Field(ge=-999999999999,le=999999999999,decimal_places=2)
    reference: str = Field(min_length=1,max_length=100)


class BankRow(BaseModel):
    model_config=ConfigDict(extra='forbid')
    bank_account: str = Field(min_length=1,max_length=80)
    statement_date: str
    amount: Decimal = Field(ge=-999999999999,le=999999999999,decimal_places=2)
    reference: str = Field(min_length=1,max_length=100)
    @field_validator('statement_date')
    @classmethod
    def date(cls,value): return PeriodInput.valid_date(value)


class BankImport(Reason):
    rows: list[BankRow] = Field(min_length=1,max_length=100)


class Match(Identity):
    payment_id: int = Field(gt=0,strict=True)


class Scope(BaseModel):
    model_config=ConfigDict(extra='forbid')
    from_date: str
    to_date: str
    dimension: Literal['customer_id','supplier_id','department','project'] = 'department'
    @field_validator('from_date','to_date')
    @classmethod
    def date(cls,value): return PeriodInput.valid_date(value)


def parse(model,payload):
    # 命令入口仍用各业务模型校验，不能通过通用字典绕过类型或多传字段。
    from pydantic import ValidationError
    try:return model.model_validate(payload)
    except ValidationError as error:raise HTTPException(422,error.errors(include_context=False)) from None


def audit(db,user,kind,identifier,action,reason,evidence):
    db.add(FinanceToolAudit(kind=kind,record_id=identifier,action=action,reason=reason,
        evidence_json=json.dumps(evidence,ensure_ascii=False),created_by=user['id']))


def opening_row(db,row):
    party=db.get(Customer if row.kind=='receivable' else Supplier,row.party_id)
    paid=sum((Decimal(x) for x in db.scalars(select(PartyOpeningPayment.amount).where(PartyOpeningPayment.opening_id==row.id))),ZERO)
    return {**model_data(row),'party_name':party.name,'settled_amount':f'{paid:.2f}','outstanding_amount':f'{Decimal(row.amount)-paid:.2f}'}


def snapshot(rows,user,totals=None):
    keys=list(dict.fromkeys(key for row in rows for key in row if not isinstance(row[key],(list,dict))))
    output=StringIO();writer=csv.writer(output);writer.writerow(keys)
    for row in rows:writer.writerow([csv_value(str(row.get(key,''))) for key in keys])
    return snapshot_metadata({'columns':[{'key':key,'title':key} for key in keys],'rows':rows,'totals':totals or {},'csv':'\ufeff'+output.getvalue()},user,('rows',))


def statements(db,data):
    filters=LedgerReportQuery(kind='trial_balance',from_date=data.from_date,to_date=data.to_date)
    rows,totals=trial_balance(db,filters)
    accounts={a.id:a for a in db.scalars(select(LedgerAccount))}
    balances={key:ZERO for key in ('asset','liability','equity','cost')}
    result=[]
    for row in rows:
        account=accounts[int(row['account_id'])]
        net=Decimal(row['closing_debit'])-Decimal(row['closing_credit'])
        if account.category in balances:balances[account.category]+=net
        result.append({'statement':'资产负债','code':account.code,'name':account.name,'category':account.category,'amount':f'{net:.2f}'})
    # 损益表排除本期结转及其冲销，不以期末已清零余额冒充当期经营损益。
    transfers=set(db.scalars(select(ProfitTransfer.journal_id)))
    all_journals={j.id:j for j in db.scalars(select(Journal).where(Journal.status=='posted'))}
    excluded=transfers | {j.id for j in all_journals.values() if j.reversal_of_id in transfers}
    revenue=expense=ZERO
    for line,journal in db.execute(select(JournalLine,Journal).join(Journal,Journal.id==JournalLine.journal_id)
        .where(Journal.status=='posted',Journal.journal_date>=data.from_date,Journal.journal_date<=data.to_date)):
        if journal.id in excluded or line.category not in ('income','expense'):continue
        value=Decimal(line.credit)-Decimal(line.debit) if line.category=='income' else Decimal(line.debit)-Decimal(line.credit)
        if line.category=='income':revenue+=value
        else:expense+=value
        result.append({'statement':'利润','code':line.account_code,'name':line.account_name,'journal_id':journal.id,'category':line.category,'amount':f'{value:.2f}'})
    # 成本类别余额属于尚未转入损益的在制成本；未结转利润进入权益核对项。
    untransferred=ZERO
    for line,journal in db.execute(select(JournalLine,Journal).join(Journal,Journal.id==JournalLine.journal_id).where(Journal.status=='posted',Journal.journal_date<=data.to_date)):
        if line.category in ('income','expense'):untransferred+=Decimal(line.credit)-Decimal(line.debit)
    assets=balances['asset']+balances['cost'];liability=-balances['liability'];equity=-balances['equity']+untransferred
    return result,{'assets':f'{assets:.2f}','liabilities':f'{liability:.2f}','equity_with_current_profit':f'{equity:.2f}',
        'revenue':f'{revenue:.2f}','expense':f'{expense:.2f}','net_profit':f'{revenue-expense:.2f}',
        'balance_difference':f'{assets-liability-equity:.2f}','trial_balanced':totals['balanced']}


@router.post('')
def command(value:ToolInput,user:dict=Depends(require('finance.view'))):
    write=value.action.startswith(('create_','confirm_','cancel_','settle_','import_','match_','unmatch_'))
    if write:require('finance.record' if value.action not in ('cancel_opening','unmatch_bank') else 'finance.reverse')(user)
    try:
        with orm_session(write=write) as db:
            action=value.action
            if action=='create_opening':
                data=parse(OpeningInput,value.payload);ensure_date_unlocked(db,data.effective_date)
                if db.get(Customer if data.kind=='receivable' else Supplier,data.party_id) is None:raise HTTPException(422,'往来单位不存在')
                account=db.get(LedgerAccount,data.ledger_account_id)
                if account is None or not account.is_active or account.category not in ('asset','liability'):raise HTTPException(422,'请选择启用的资产或负债往来科目')
                row=add_model(db,PartyOpening(**data.model_dump(exclude={'amount'}),amount=f'{data.amount:.2f}',status='draft',created_by=user['id']))
                audit(db,user,'opening',row.id,'create',data.reason,opening_row(db,row))
                return snapshot([opening_row(db,row)],user)
            if action in ('confirm_opening','cancel_opening','settle_opening'):
                data=parse(Settlement if action=='settle_opening' else Identity,value.payload);row=db.get(PartyOpening,data.id)
                if row is None:raise HTTPException(404,'往来期初不存在')
                ensure_date_unlocked(db,row.effective_date)
                if action=='confirm_opening':
                    if row.status!='draft':raise HTTPException(409,'仅草稿可确认')
                    row.status='confirmed'
                elif action=='cancel_opening':
                    if row.status=='cancelled' or db.scalar(select(PartyOpeningPayment.id).where(PartyOpeningPayment.opening_id==row.id).limit(1)):raise HTTPException(409,'期初已取消或存在结算记录，不能作废')
                    row.status='cancelled'
                else:
                    outstanding=Decimal(opening_row(db,row)['outstanding_amount'])
                    if row.status!='confirmed' or data.amount==0 or data.amount*outstanding<=0 or abs(data.amount)>abs(outstanding):raise HTTPException(409,'结算须同方向且不能超过已确认期初余额')
                    db.add(PartyOpeningPayment(opening_id=row.id,amount=f'{data.amount:.2f}',reference=data.reference.strip(),reason=data.reason,created_by=user['id']))
                db.flush();audit(db,user,'opening',row.id,action,data.reason,opening_row(db,row));return snapshot([opening_row(db,row)],user)
            if action=='openings':return snapshot([opening_row(db,row) for row in db.scalars(select(PartyOpening).order_by(PartyOpening.id.desc()))],user)
            if action=='import_bank':
                data=parse(BankImport,value.payload)
                for item in data.rows:
                    ensure_date_unlocked(db,item.statement_date)
                    if item.amount==0 or not item.reference.strip() or not item.bank_account.strip():raise HTTPException(422,'银行流水金额和参考号不能为空')
                    row=add_model(db,BankStatement(**item.model_dump(exclude={'amount'}),amount=f'{item.amount:.2f}',created_by=user['id']))
                    audit(db,user,'bank',row.id,action,data.reason,model_data(row))
                return snapshot([],user,{'imported':str(len(data.rows))})
            if action in ('match_bank','unmatch_bank'):
                data=parse(Match if action=='match_bank' else Identity,value.payload);row=db.get(BankStatement,data.id)
                if row is None:raise HTTPException(404,'银行流水不存在')
                ensure_date_unlocked(db,row.statement_date);match=db.get(BankMatch,row.id)
                if action=='unmatch_bank':
                    if not match:raise HTTPException(409,'此流水没有已匹配记录')
                    evidence=model_data(match);db.delete(match)
                else:
                    if match:raise HTTPException(409,'此流水已经匹配')
                    payment=db.get(PaymentRecord,data.payment_id)
                    if payment is None or payment.action=='reversal' or db.scalar(select(PaymentRecord.id).where(PaymentRecord.reverses_id==payment.id)):raise HTTPException(409,'收付款不存在、已冲销或为冲销记录')
                    signed=Decimal(payment.amount)*(1 if payment.kind=='receivable' else -1)
                    if signed!=Decimal(row.amount):raise HTTPException(409,'银行方向或金额与收付款不一致')
                    evidence={'statement_id':row.id,'payment_id':payment.id};db.add(BankMatch(**evidence,created_by=user['id']))
                audit(db,user,'bank',row.id,action,data.reason,evidence);return snapshot([],user)
            if action=='banks':
                rows=[]
                for row in db.scalars(select(BankStatement).order_by(BankStatement.id.desc())):
                    match=db.get(BankMatch,row.id);rows.append({**model_data(row),'payment_id':match.payment_id if match else None,'status':'已匹配' if match else '未匹配'})
                return snapshot(rows,user,{'unmatched':str(sum(row['payment_id'] is None for row in rows))})
            if action=='history':return snapshot([model_data(row) for row in db.scalars(select(FinanceToolAudit).order_by(FinanceToolAudit.id.desc()))],user)
            if action=='reconcile':
                from app.finance.routes import financial_entries
                rows=[];entries=financial_entries(db)
                for account in db.scalars(select(LedgerAccount)):
                    openings=[row for row in db.scalars(select(PartyOpening).where(PartyOpening.ledger_account_id==account.id,PartyOpening.status=='confirmed'))]
                    if not openings:continue
                    subsidiary=sum((Decimal(row.amount)*(1 if row.kind=='receivable' else -1) for row in openings),ZERO)
                    ledger=sum((Decimal(row.debit)-Decimal(row.credit) for row in confirmed_opening_lines(db) if row.account_id==account.id),ZERO)
                    rows.append({'account_id':account.id,'code':account.code,'name':account.name,'party_opening':f'{subsidiary:.2f}','ledger_opening':f'{ledger:.2f}','difference':f'{subsidiary-ledger:.2f}'})
                return snapshot(rows,user,{'unpriced_business_sources':str(sum(row['amount'] is None for row in entries))})
            data=parse(Scope,value.payload)
            if data.to_date<data.from_date:raise HTTPException(422,'结束日期不能早于开始日期')
            if action=='statements':
                require('journal.view')(user);rows,totals=statements(db,data);return snapshot(rows,user,totals)
            require('journal.view')(user)
            groups={}
            for aux,line,journal in db.execute(select(JournalAuxiliary,JournalLine,Journal).join(JournalLine,JournalLine.id==JournalAuxiliary.line_id).join(Journal,Journal.id==JournalLine.journal_id)
                .where(Journal.status=='posted',Journal.journal_date>=data.from_date,Journal.journal_date<=data.to_date)):
                key=getattr(aux,data.dimension)
                if not key:continue
                values=groups.setdefault((line.account_id,str(key)),{'account_code':line.account_code,'account_name':line.account_name,'dimension':data.dimension,'value':str(key),'debit':ZERO,'credit':ZERO})
                values['debit']+=Decimal(line.debit);values['credit']+=Decimal(line.credit)
            rows=[{**row,'debit':f"{row['debit']:.2f}",'credit':f"{row['credit']:.2f}",'balance':f"{row['debit']-row['credit']:.2f}"} for row in groups.values()]
            return snapshot(rows,user)
    except IntegrityError:raise HTTPException(409,'参考号或匹配记录已存在，本次操作整体回滚') from None
