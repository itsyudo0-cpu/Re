"""
CleanReader & Media Summarizer Bot - Async MongoDB Database Layer (Motor)
=========================================================================
Manages user profiles, daily free-tier usage counters, automatic date rollover,
premium subscription expiry enforcement, payment audit logs, and global metrics.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple, AsyncIterator
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from config import Config

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, uri: str, database_name: str) -> None:
        self._client = AsyncIOMotorClient(uri)
        self.db: AsyncIOMotorDatabase = self._client[database_name]
        self.users = self.db["users"]
        self.payments = self.db["payments"]
        self.metrics = self.db["metrics"]
        self.settings = self.db["settings"]

    async def initialize_indexes(self) -> None:
        """Create indexes for fast lookups and uniqueness guarantees."""
        await self.users.create_index("user_id", unique=True)
        await self.users.create_index("is_premium")
        await self.payments.create_index("payment_id", unique=True)
        await self.payments.create_index("user_id")
        logger.info("MongoDB indexes initialized on '%s'.", Config.DATABASE_NAME)

    @staticmethod
    def _today_utc_str() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async def ensure_user(
        self,
        user_id: int,
        first_name: str = "User",
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch user document or create a default profile if first interaction.
        Also checks and auto-revokes expired premium status on the fly.
        """
        now = datetime.now(timezone.utc)
        today_str = self._today_utc_str()

        user = await self.users.find_one({"user_id": user_id})
        if not user:
            new_user: Dict[str, Any] = {
                "user_id": user_id,
                "first_name": first_name,
                "username": username,
                "joined_date": now,
                "is_premium": False,
                "premium_expiry": None,
                "daily_usage_count": 0,
                "last_usage_date": today_str,
                "total_reads": 0,
                "pending_payment_plan": None,
            }
            await self.users.insert_one(new_user)
            return new_user

        updates: Dict[str, Any] = {}

        # Sync profile metadata if changed
        if user.get("first_name") != first_name or user.get("username") != username:
            updates["first_name"] = first_name
            updates["username"] = username

        # Auto-expire premium if past premium_expiry
        if user.get("is_premium") and user.get("premium_expiry"):
            expiry: datetime = user["premium_expiry"]
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if now >= expiry:
                updates["is_premium"] = False
                updates["premium_expiry"] = None

        # Reset daily counter if UTC date rolled over
        if user.get("last_usage_date") != today_str:
            updates["daily_usage_count"] = 0
            updates["last_usage_date"] = today_str

        if updates:
            await self.users.update_one({"user_id": user_id}, {"$set": updates})
            user.update(updates)

        return user

    async def check_and_consume_quota(
        self,
        user_id: int,
        first_name: str = "User",
        username: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any], int]:
        """
        Verify if user can perform an article scrape or AI summary.
        Returns: (allowed: bool, user_doc: dict, remaining_today: int)
        - Premium users always return (True, user_doc, -1).
        - Free users are checked against Config.FREE_DAILY_LIMIT.
        """
        user = await self.ensure_user(user_id, first_name, username)

        if user.get("is_premium"):
            await self.users.update_one(
                {"user_id": user_id},
                {"$inc": {"total_reads": 1}},
            )
            return True, user, -1

        used = int(user.get("daily_usage_count", 0))
        if used >= Config.FREE_DAILY_LIMIT:
            return False, user, 0

        new_count = used + 1
        await self.users.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "daily_usage_count": new_count,
                    "last_usage_date": self._today_utc_str(),
                },
                "$inc": {"total_reads": 1},
            },
        )
        user["daily_usage_count"] = new_count
        remaining = max(0, Config.FREE_DAILY_LIMIT - new_count)
        return True, user, remaining

    async def grant_premium(self, user_id: int, days: int) -> datetime:
        """
        Grant or extend premium subscription for `days` days.
        Returns the new UTC expiry timestamp.
        """
        now = datetime.now(timezone.utc)
        user = await self.ensure_user(user_id)

        current_expiry = user.get("premium_expiry")
        if user.get("is_premium") and current_expiry:
            if current_expiry.tzinfo is None:
                current_expiry = current_expiry.replace(tzinfo=timezone.utc)
            base_time = max(now, current_expiry)
        else:
            base_time = now

        new_expiry = base_time + timedelta(days=days)
        await self.users.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "is_premium": True,
                    "premium_expiry": new_expiry,
                    "pending_payment_plan": None,
                }
            },
        )
        return new_expiry

    async def revoke_premium(self, user_id: int) -> bool:
        """Immediately revoke a user's premium status."""
        result = await self.users.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "is_premium": False,
                    "premium_expiry": None,
                }
            },
        )
        return result.modified_count > 0

    async def set_pending_payment_plan(
        self, user_id: int, plan_key: Optional[str]
    ) -> None:
        """Store which plan the user is currently submitting UTR/Screenshot proof for."""
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"pending_payment_plan": plan_key}},
            upsert=True,
        )

    async def create_payment_submission(
        self,
        payment_id: str,
        user_id: int,
        plan_key: str,
        amount: int,
        days: int,
        utr_or_caption: str,
    ) -> Dict[str, Any]:
        """Record a manual UPI payment proof awaiting admin verification."""
        doc = {
            "payment_id": payment_id,
            "user_id": user_id,
            "plan_key": plan_key,
            "amount": amount,
            "days": days,
            "utr_or_caption": utr_or_caption,
            "status": "pending",
            "created_at": datetime.now(timezone.utc),
            "reviewed_at": None,
            "reviewed_by": None,
        }
        await self.payments.insert_one(doc)
        return doc

    async def resolve_payment_submission(
        self, payment_id: str, status: str, admin_id: int
    ) -> Optional[Dict[str, Any]]:
        """Mark a payment submission as 'approved' or 'rejected'."""
        payment = await self.payments.find_one({"payment_id": payment_id})
        if not payment:
            return None

        await self.payments.update_one(
            {"payment_id": payment_id},
            {
                "$set": {
                    "status": status,
                    "reviewed_at": datetime.now(timezone.utc),
                    "reviewed_by": admin_id,
                }
            },
        )
        payment["status"] = status
        return payment

    async def increment_metric(self, key: str, amount: int = 1) -> None:
        """Increment global telemetry counters (articles_scraped, youtube_summaries, pdfs_exported)."""
        await self.metrics.update_one(
            {"_id": "global_stats"},
            {"$inc": {key: amount}},
            upsert=True,
        )

    async def get_stats(self) -> Dict[str, int]:
        """Return aggregated bot statistics for the /stats admin command."""
        total_users = await self.users.count_documents({})
        premium_users = await self.users.count_documents({"is_premium": True})
        metrics_doc = await self.metrics.find_one({"_id": "global_stats"}) or {}

        return {
            "total_users": total_users,
            "premium_users": premium_users,
            "free_users": max(0, total_users - premium_users),
            "articles_scraped": int(metrics_doc.get("articles_scraped", 0)),
            "youtube_summaries": int(metrics_doc.get("youtube_summaries", 0)),
            "pdfs_exported": int(metrics_doc.get("pdfs_exported", 0)),
        }

    async def iter_all_user_ids(self) -> AsyncIterator[int]:
        """Stream all registered user IDs for /broadcast."""
        cursor = self.users.find({}, {"user_id": 1})
        async for doc in cursor:
            if "user_id" in doc:
                yield int(doc["user_id"])

    # ------------------------------------------------------------------
    # Custom screen images (managed by admins via /setimg)
    # ------------------------------------------------------------------
    async def get_screen_images(self) -> Dict[str, str]:
        doc = await self.settings.find_one({"_id": "screen_images"}) or {}
        return dict(doc.get("images", {}))

    async def set_screen_image(self, screen: str, image: str) -> None:
        await self.settings.update_one(
            {"_id": "screen_images"},
            {"$set": {f"images.{screen}": image}},
            upsert=True,
        )

    async def delete_screen_image(self, screen: str) -> None:
        await self.settings.update_one(
            {"_id": "screen_images"},
            {"$unset": {f"images.{screen}": ""}},
            upsert=True,
        )


db = Database(Config.MONGO_URI, Config.DATABASE_NAME)
            
