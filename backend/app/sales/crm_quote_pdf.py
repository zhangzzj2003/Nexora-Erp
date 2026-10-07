"""用已冻结的报价资料生成可独立查看的中文 PDF。"""

from app.core.document_responses import NumberedRoute
from html import escape
from io import BytesIO
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Response
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.access.security import require
from app.core.orm import orm_session
from app.sales.crm_rules import get_record, raw_data, today


router = APIRouter(route_class=NumberedRoute, prefix='/api/v1/crm/quotes')
FONT_PATH = Path(__file__).with_name('fonts') / 'NotoSansSC-Regular.ttf'
FONT_NAME = 'NexoraNotoSansSC'
_font_lock = Lock()


def paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(value)).replace('\n', '<br/>'), style)


def quote_pdf(snapshot: dict, issued_on: str) -> bytes:
    """报价正文只使用 ORM 读取的冻结快照，不重新读取现行客户或物料名称。"""
    # ReportLab 的字体注册是进程级状态，首批并发导出只注册一次。
    with _font_lock:
        if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))
    standard = ParagraphStyle('quote-body', fontName=FONT_NAME, fontSize=9, leading=15, wordWrap='CJK')
    muted = ParagraphStyle('quote-muted', parent=standard, textColor=colors.HexColor('#526174'))
    heading = ParagraphStyle('quote-heading', parent=standard, fontSize=21, leading=28,
                             textColor=colors.HexColor('#16243a'))
    right = ParagraphStyle('quote-right', parent=standard, alignment=TA_RIGHT)
    small = ParagraphStyle('quote-small', parent=standard, fontSize=8, leading=12)

    data = BytesIO()
    document = SimpleDocTemplate(data, pagesize=A4, leftMargin=19*mm, rightMargin=19*mm,
                                 topMargin=22*mm, bottomMargin=20*mm, title='固定报价',
                                 author='Nexora ERP', pageCompression=1)
    width = A4[0] - 38*mm
    body = [paragraph('固定报价', heading), Spacer(1, 4*mm),
            paragraph(f"业务单号：{snapshot.get('document_no') or snapshot['reference']}　　参考号：{snapshot['reference']}　　导出日期：{issued_on}", muted), Spacer(1, 7*mm)]
    status = '已转销售订单，仅供历史核对' if snapshot['status'] == 'converted' else '已批准'
    if snapshot['valid_until'] < issued_on:
        status += '；有效期已过，仅供历史核对'
    party = snapshot['party']
    facts = [
        ('客户', party['customer_name']), ('联系人', party['contact_name'] or '未指定'),
        ('电话', party['phone'] or '未填写'), ('邮箱', party['email'] or '未填写'),
        ('状态', status), ('有效至', snapshot['valid_until']),
        ('审核时间', snapshot['reviewed_at'] or '未记录'), ('币种', '人民币（CNY）'),
    ]
    facts_table = Table([[paragraph(label, muted), paragraph(value, standard)] for label, value in facts],
                        colWidths=[29*mm, width-29*mm], hAlign='LEFT')
    facts_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4*mm), ('TOPPADDING', (0, 0), (-1, -1), 3*mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm),
        ('LINEBELOW', (0, -1), (-1, -1), .5, colors.HexColor('#d8e1ec')),
    ]))
    body.extend([facts_table, Spacer(1, 8*mm), paragraph('报价明细', standard), Spacer(1, 3*mm)])

    rows = [[paragraph(value, small) for value in ('序号', '物料编码 / 名称', '数量 / 单位', '单价（元）', '金额（元）')]]
    for line in snapshot['lines']:
        rows.append([paragraph(line['position'], standard),
                     paragraph(f"{line['sku']} / {line['material_name']}", standard),
                     paragraph(f"{line['quantity']} {line['unit']}", standard),
                     paragraph(line['unit_price'], right), paragraph(line['line_total'], right)])
    lines_table = LongTable(rows, colWidths=[12*mm, 65*mm, 28*mm, 32*mm, width-137*mm],
                            repeatRows=1, hAlign='LEFT')
    lines_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf2f8')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 2*mm),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2*mm), ('TOPPADDING', (0, 0), (-1, -1), 3*mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm),
        ('LINEBELOW', (0, 0), (-1, 0), .8, colors.HexColor('#a9bacd')),
        ('LINEBELOW', (0, 1), (-1, -1), .3, colors.HexColor('#d8e1ec')),
    ]))
    body.extend([lines_table, Spacer(1, 5*mm),
                 paragraph(f"合计：人民币 {snapshot['total_amount']} 元", right), Spacer(1, 8*mm)])
    terms = snapshot['terms'] or '未填写'
    body.append(KeepTogether([paragraph('交货及商务条款', standard), Spacer(1, 2*mm),
                              paragraph(terms, standard)]))
    body.extend([Spacer(1, 8*mm), paragraph('本文件基于已审核的固定报价资料生成；不代表销售订单、收款记录或税务发票。', muted)])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#d8e1ec'))
        canvas.line(19*mm, 15*mm, A4[0]-19*mm, 15*mm)
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(colors.HexColor('#526174'))
        canvas.drawString(19*mm, 10*mm, f"业务单号：{snapshot.get('document_no') or snapshot['reference']}")
        canvas.drawRightString(A4[0]-19*mm, 10*mm, f'第 {doc.page} 页')
        canvas.restoreState()

    document.build(body, onFirstPage=footer, onLaterPages=footer)
    return data.getvalue()


@router.get('/{identifier}/pdf')
def export_quote_pdf(identifier: int, user: dict = Depends(require('crm.view'))):
    with orm_session() as db:
        record = get_record(db, 'quote', identifier, user=user)
        if record.status not in ('approved', 'converted'):
            raise HTTPException(409, '只有已批准且未取消的报价可以导出 PDF')
        snapshot = raw_data(db, 'quote', record)
        snapshot['document_no'] = record.document_no
    content = quote_pdf(snapshot, today())
    return Response(content=content, media_type='application/pdf', headers={
        'Content-Disposition': f'attachment; filename="quote-{identifier}.pdf"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    })
