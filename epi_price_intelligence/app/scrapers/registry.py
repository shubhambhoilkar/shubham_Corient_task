"""
Adding a new retailer = writing one adapter class + registering it here.
No changes to the orchestrator, models, or API are required (see README
"Adding a new source").
"""
from app.scrapers.croma import CromaAdapter
from app.scrapers.reliance_digital import RelianceDigitalAdapter
from app.scrapers.vijay_sales import VijaySalesAdapter

ADAPTER_REGISTRY = {
    CromaAdapter.source_name: CromaAdapter,
    VijaySalesAdapter.source_name: VijaySalesAdapter,
    RelianceDigitalAdapter.source_name: RelianceDigitalAdapter,
}


def get_enabled_adapters(settings, only: list[str] | None = None):
    names = only or list(ADAPTER_REGISTRY.keys())
    return [ADAPTER_REGISTRY[name](settings) for name in names if name in ADAPTER_REGISTRY]
