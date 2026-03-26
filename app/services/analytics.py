"""
Analytics & Monitoring Module (No-op)
track methods เป็น log-only เนื่องจากไม่มี analytics_events / analytics_alerts tables ใน Supabase
"""

import logging
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)


class AnalyticsTracker:
    """Analytics tracker — log-only, ไม่เขียน DB"""

    def __init__(self, supabase_client=None):
        logger.info("✓ Analytics tracker initialized (log-only, no DB)")

    async def track_image_analysis(self, user_id: str, disease_name: str, **kwargs):
        logger.debug(f"[analytics] image_analysis: {disease_name} by {user_id[:8]}")

    async def track_question(self, user_id: str, question: str, **kwargs):
        logger.debug(f"[analytics] question by {user_id[:8]}: {question[:50]}")

    async def track_product_recommendation(self, user_id: str, disease_name: str, products: List[str]):
        logger.debug(f"[analytics] product_rec: {disease_name} → {len(products)} products")

    async def track_registration(self, user_id: str, **kwargs):
        logger.debug(f"[analytics] registration: {user_id[:8]}")

    async def track_error(self, user_id: str, error_type: str, error_message: str, **kwargs):
        logger.warning(f"[analytics] error: {error_type} — {error_message[:100]}")

    async def get_dashboard_stats(self, days: int = 1) -> dict:
        """Return empty stats structure"""
        return {
            "overview": {
                "unique_users": 0,
                "images_analyzed": 0,
                "questions_asked": 0,
                "total_requests": 0,
                "errors": 0
            },
            "performance": {
                "avg_response_time_ms": 0,
                "error_rate_percent": 0
            },
            "health": {"status": "healthy"},
            "top_diseases": [],
            "top_products": [],
            "pest_types": [],
            "top_provinces": [],
            "top_errors": [],
            "daily_activity": {},
            "daily_requests": {},
            "daily_users": {},
            "daily_response_time": {},
            "daily_error_rate": {},
            "date_range": {
                "start": datetime.now().isoformat(),
                "end": datetime.now().isoformat(),
                "days": days
            }
        }

    async def get_health_status(self) -> dict:
        return {
            "status": "healthy",
            "error_rate": 0,
            "avg_response_time_ms": 0,
            "warnings": [],
            "timestamp": datetime.now().isoformat()
        }


class AlertManager:
    """Alert manager — no-op, returns empty alerts"""

    def __init__(self, supabase_client=None):
        logger.info("✓ Alert manager initialized (no-op)")

    async def get_active_alerts(self) -> List[dict]:
        return []
