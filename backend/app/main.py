"""FastAPI 应用组装与服务生命周期。"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sqlalchemy import select
from app.core.database import migrate
from app.core.models import ServerIdentity
from app.core.orm import orm_session
from app.service.discovery import DiscoveryPublisher
from app.access.routes import router as access_router
from app.access.menus import router as menu_router
from app.catalog.routes import router as catalog_router
from app.purchase.receipts import router as receipts_router
from app.purchase.orders import router as purchase_router
from app.purchase.requests import router as purchase_requests_router
from app.purchase.goods_receipts import router as goods_receipts_router
from app.purchase.returns import router as purchase_returns_router
from app.inventory.warehouse import router as inventory_router
from app.inventory.stocktake import router as stocktake_router
from app.inventory.stock import router as stock_router
from app.inventory.warnings import router as warnings_router
from app.inventory.warning_events import router as warning_events_router, run_warning_event_scheduler
from app.inventory.physical_lots import router as physical_lots_router
from app.inventory.movement_evidence import router as movement_evidence_router
from app.inventory.ledger import router as ledger_router
from app.inventory.valuation import router as valuation_router
from app.inventory.adjustments import router as adjustments_router
from app.inventory.inbounds import router as warehouse_inbounds_router
from app.inventory.outbounds import router as warehouse_outbounds_router
from app.sales.orders import router as sales_router
from app.sales.contracts import router as sales_contracts_router
from app.sales.contract_attachments import router as sales_contract_attachments_router
from app.sales.customer_import import router as customer_import_router
from app.sales.contact_import import router as contact_import_router
from app.sales.opportunity_import import router as opportunity_import_router
from app.sales.crm_forecast import router as crm_forecast_router
from app.sales.returns import router as sales_returns_router
from app.sales.crm import router as crm_router
from app.sales.crm_quotes import router as crm_quotes_router
from app.sales.crm_quote_attachments import router as crm_quote_attachments_router
from app.sales.crm_record_attachments import router as crm_record_attachments_router
from app.sales.crm_quote_pdf import router as crm_quote_pdf_router
from app.sales.after_sales import router as after_sales_router
from app.sales.after_sales_labor import router as after_sales_labor_router
from app.sales.after_sales_labor_cost import router as after_sales_labor_cost_router
from app.sales.after_sales_margin import router as after_sales_margin_router
from app.sales.after_sales_responsibility import router as after_sales_responsibility_router
from app.sales.after_sales_attachments import router as after_sales_attachments_router
from app.production.boms import router as production_router
from app.production.work_orders import router as work_orders_router
from app.production.material_issues import router as material_issues_router
from app.production.material_returns import router as material_returns_router
from app.production.completions import router as production_completions_router
from app.production.costs import router as production_costs_router
from app.production.settlements import router as production_settlements_router
from app.production.mrp import router as mrp_router
from app.production.quality import router as quality_router
from app.production.equipment import router as equipment_router
from app.production.equipment_hours import router as equipment_hours_router
from app.production.equipment_attachments import router as equipment_attachments_router
from app.finance.routes import router as finance_router
from app.finance.ledger import router as finance_ledger_router
from app.finance.journals import router as journals_router
from app.finance.journal_attachments import router as journal_attachments_router
from app.finance.ledger_reports import router as ledger_reports_router
from app.finance.opening_balances import router as opening_balances_router
from app.finance.period_closing import router as period_closing_router
from app.finance.business_journals import router as business_journals_router
from app.finance.profit_transfers import router as profit_transfers_router
from app.finance.statements import router as statements_router
from app.finance.auxiliary import router as auxiliary_router
from app.finance.subledger_openings import router as subledger_openings_router
from app.finance.bank_reconciliation import router as bank_reconciliation_router
from app.finance.bank_balance import router as bank_balance_router
from app.reports.routes import router as reports_router
from app.reports.dashboard import router as dashboard_router
from app.service.routes import router as service_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 启动时检查并升级本地数据库；不依赖桌面页面是否已经打开。
    migrate()
    publisher = None
    task = None
    warning_task = None
    port = os.environ.get("NEXORA_DISCOVERY_PORT")
    if port is not None:
        with orm_session() as db:
            instance_id = db.scalar(select(ServerIdentity.id).limit(1))
        publisher = DiscoveryPublisher(instance_id, "0.1.0", int(port))

        async def publish_periodically():
            # 系统服务可能早于网卡启动；重复检查也能处理 IP 地址变化。
            while True:
                try:
                    await asyncio.to_thread(publisher.sync)
                except Exception:
                    logging.getLogger(__name__).exception("局域网发现状态更新失败")
                await asyncio.sleep(15)

        task = asyncio.create_task(publish_periodically())
    try:
        warning_task = asyncio.create_task(run_warning_event_scheduler())
        yield
    finally:
        for running in (warning_task, task):
            if running is None:
                continue
            running.cancel()
            try:
                await running
            except asyncio.CancelledError:
                pass
        if publisher is not None:
            await asyncio.to_thread(publisher.close)


app = FastAPI(title="Nexora ERP API", version="0.1.0", lifespan=lifespan)
# 路由只在这里组装；各功能目录负责自己的参数校验与业务接口。
for router in (
    service_router, access_router, menu_router, catalog_router, receipts_router,
    inventory_router, stock_router, warnings_router, warning_events_router, physical_lots_router, movement_evidence_router, ledger_router, valuation_router, stocktake_router, adjustments_router,
    warehouse_inbounds_router, warehouse_outbounds_router,
    purchase_router, purchase_requests_router, goods_receipts_router,
    purchase_returns_router, sales_router, sales_contracts_router, sales_contract_attachments_router, customer_import_router, contact_import_router, opportunity_import_router, crm_forecast_router, sales_returns_router, crm_router, crm_record_attachments_router, crm_quotes_router, crm_quote_attachments_router, crm_quote_pdf_router, after_sales_labor_router, after_sales_labor_cost_router, after_sales_margin_router, after_sales_responsibility_router, after_sales_attachments_router, after_sales_router,
    production_router, work_orders_router, material_issues_router,
    material_returns_router, production_completions_router, production_costs_router, production_settlements_router, mrp_router, quality_router, equipment_router, equipment_hours_router, equipment_attachments_router,
    finance_router, finance_ledger_router, journals_router, journal_attachments_router, ledger_reports_router, opening_balances_router, subledger_openings_router, bank_reconciliation_router, bank_balance_router, period_closing_router, business_journals_router, profit_transfers_router, statements_router, auxiliary_router, reports_router, dashboard_router,
):
    app.include_router(router)
