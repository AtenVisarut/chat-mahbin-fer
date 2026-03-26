"""
User Service
Handles LINE user profile tracking and database operations
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict
import httpx
from app.dependencies import supabase_client
from app.config import LINE_CHANNEL_ACCESS_TOKEN, FB_PAGE_ACCESS_TOKEN

logger = logging.getLogger(__name__)

LINE_PROFILE_API = "https://api.line.me/v2/bot/profile/{user_id}"
FB_GRAPH_API = "https://graph.facebook.com/v21.0/{psid}"


async def get_line_profile(user_id: str) -> Optional[Dict]:
    """
    Fetch user profile from LINE API
    
    Returns:
        dict with keys: userId, displayName, pictureUrl, statusMessage
        None if failed
    """
    try:
        headers = {
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                LINE_PROFILE_API.format(user_id=user_id),
                headers=headers,
                timeout=10.0
            )
            
        if response.status_code == 200:
            profile = response.json()
            logger.info(f"✓ Fetched LINE profile for {user_id}: {profile.get('displayName')}")
            return profile
        else:
            logger.error(f"Failed to fetch LINE profile: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error fetching LINE profile for {user_id}: {e}", exc_info=True)
        return None


async def get_facebook_profile(psid: str) -> Optional[Dict]:
    """
    Fetch user profile from Facebook Graph API

    Args:
        psid: Facebook Page-Scoped ID (without "fb:" prefix)

    Returns:
        dict with key: displayName
        None if failed
    """
    try:
        if not FB_PAGE_ACCESS_TOKEN:
            logger.warning("FB_PAGE_ACCESS_TOKEN not configured")
            return None

        params = {
            "fields": "first_name,last_name",
            "access_token": FB_PAGE_ACCESS_TOKEN
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                FB_GRAPH_API.format(psid=psid),
                params=params,
                timeout=10.0
            )

        if response.status_code == 200:
            data = response.json()
            first = data.get("first_name", "")
            last = data.get("last_name", "")
            display_name = f"{first} {last}".strip() or f"User_fb:{psid[:8]}"
            logger.info(f"✓ Fetched FB profile for {psid}: {display_name}")
            return {"displayName": display_name}
        else:
            logger.error(f"Failed to fetch FB profile: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        logger.error(f"Error fetching FB profile for {psid}: {e}", exc_info=True)
        return None


async def register_user_fer(user_id: str, display_name: str) -> bool:
    """
    Register user in user_fer(LINE,FACE) table for tracking LINE/FB users.
    - New user → insert with created_at
    - Existing user → update display_name + updated_at
    """
    try:
        if not supabase_client:
            logger.error("Supabase client not available for user_fer")
            return False

        now = datetime.now(timezone.utc).isoformat()

        # Check if already registered
        existing = supabase_client.table("user_fer(LINE,FACE)")\
            .select("id")\
            .eq("line_user_id", user_id)\
            .execute()

        if existing.data and len(existing.data) > 0:
            # Already exists → update updated_at
            supabase_client.table("user_fer(LINE,FACE)")\
                .update({"display_name": display_name, "updated_at": now})\
                .eq("line_user_id", user_id)\
                .execute()
            logger.debug(f"User {user_id} already in user_fer, updated timestamp")
            return True

        # Insert new record
        data = {
            "line_user_id": user_id,
            "display_name": display_name,
            "created_at": now,
            "updated_at": now
        }
        supabase_client.table("user_fer(LINE,FACE)").insert(data).execute()
        logger.info(f"✓ Registered user in user_fer: {user_id} ({display_name})")
        return True

    except Exception as e:
        logger.error(f"Error registering user_fer for {user_id}: {e}", exc_info=True)
        return False


async def get_user(user_id: str) -> Optional[Dict]:
    """Get user from database"""
    try:
        if not supabase_client:
            return None
            
        result = supabase_client.table('users')\
            .select('*')\
            .eq('line_user_id', user_id)\
            .execute()
        
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
        
    except Exception as e:
        logger.error(f"Error getting user {user_id}: {e}")
        return None


async def upsert_user(user_id: str, profile_data: Dict) -> bool:
    """
    Create or update user record (simplified for registration schema)
    
    Args:
        user_id: LINE user ID
        profile_data: Profile data from LINE API
    """
    try:
        if not supabase_client:
            logger.error("Supabase client not available")
            return False
        
        # Simple upsert with only columns that exist in the table
        data = {
            "line_user_id": user_id,
            "display_name": profile_data.get('displayName', 'Unknown')
        }
        
        supabase_client.table('users').upsert(data).execute()
        logger.info(f"✓ Upserted user {user_id}: {data['display_name']}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error upserting user {user_id}: {e}", exc_info=True)
        return False


async def update_last_seen(user_id: str) -> bool:
    """Update user's last interaction (simplified)"""
    try:
        if not supabase_client:
            return False
        
        existing_user = await get_user(user_id)
        if not existing_user:
            logger.warning(f"User {user_id} not found for update")
            return False
        
        # Just verify user exists
        logger.debug(f"✓ Verified user {user_id} exists")
        return True
        
    except Exception as e:
        logger.error(f"Error updating user {user_id}: {e}")
        return False


async def ensure_user_exists(user_id: str) -> bool:
    """
    Ensure user exists in database
    Fetches profile from LINE/FB if new user
    Always registers/updates in user_fer(LINE,FACE) table

    Args:
        user_id: LINE user ID or "fb:{psid}" for Facebook

    Returns:
        True if user exists/created, False if failed
    """
    try:
        # Check if user exists
        user = await get_user(user_id)

        if user:
            # User exists in users table → also ensure user_fer tracking
            display_name = user.get("display_name", f"User_{user_id[:8]}")
            await register_user_fer(user_id, display_name)
            await update_last_seen(user_id)
            return True

        # New user - detect platform and fetch profile
        logger.info(f"🆕 New user detected: {user_id}")

        if user_id.startswith("fb:"):
            # Facebook user
            psid = user_id[3:]  # strip "fb:" prefix
            profile = await get_facebook_profile(psid)
            fallback_name = f"User_fb:{psid[:8]}"
        else:
            # LINE user
            profile = await get_line_profile(user_id)
            fallback_name = f"User_{user_id[:8]}"

        if profile:
            # Create user with profile data
            success = await upsert_user(user_id, profile)
            display_name = profile.get("displayName", fallback_name)
        else:
            # Profile fetch failed, create with minimal data
            logger.warning(f"Failed to fetch profile for {user_id}, creating with minimal data")
            minimal_profile = {
                "displayName": fallback_name,
                "pictureUrl": None,
                "statusMessage": None
            }
            success = await upsert_user(user_id, minimal_profile)
            display_name = fallback_name

        if success:
            logger.info(f"✅ User {user_id} registered successfully")
            # Register in user_fer(LINE,FACE) table
            await register_user_fer(user_id, display_name)

        return success

    except Exception as e:
        logger.error(f"Error ensuring user exists {user_id}: {e}", exc_info=True)
        return False
