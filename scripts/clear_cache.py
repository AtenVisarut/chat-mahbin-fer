"""
Clear all caches in the application
"""
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

def clear_cache():
    print("=" * 60)
    print("Clearing Application Cache")
    print("=" * 60)
    
    print("\n1. In-memory caches will be cleared on server restart")
    print("   → Stop server (Ctrl+C)")
    print("   → Start server: python app/main.py")
    
    print("\n2. Conversation memory in Supabase...")
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Check if conversation_memory table exists
        result = supabase.table('conversation_memory').select('id').limit(1).execute()
        
        # Clear old conversations (optional)
        print("   Found conversation_memory table")
        print("   To clear: DELETE FROM conversation_memory;")
        
    except Exception as e:
        print(f"   No conversation_memory table or error: {e}")
    
    print("\n3. Browser/LINE cache...")
    print("   → Clear LINE app cache")
    print("   → Or send a new message to trigger fresh response")
    
    print("\n" + "=" * 60)
    print("RECOMMENDATION:")
    print("=" * 60)
    print("\n1. Restart your server: python app/main.py")
    print("2. Send a NEW image to LINE Bot (not old cached one)")
    print("3. Check if usage_period appears")

if __name__ == "__main__":
    clear_cache()
