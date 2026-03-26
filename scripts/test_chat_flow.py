"""
Quick smoke test — ทดสอบ bot ดึงข้อมูลจาก Supabase ได้จริง
ทดสอบ 3 flow: ปุ๋ย (mahbin_npk), ตัวแทนจำหน่าย (dealers), สนทนาทั่วไป

Usage:
    python scripts/test_chat_flow.py
"""
import asyncio
import logging
import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test")

# ─── Test 1: Supabase connection + mahbin_npk table ─────────────────────────
async def test_supabase_tables():
    """ตรวจว่า 5 tables เข้าถึงได้"""
    from app.dependencies import supabase_client
    if not supabase_client:
        print("FAIL: Supabase client not initialized (check .env)")
        return False

    tables = {
        "mahbin_npk": "id",
        "user_fer(LINE,FACE)": "id",
        "conver_mem_mahbin": "id",
        "cache": "key",
        "dealers": "id",
    }
    all_ok = True
    for table, col in tables.items():
        try:
            result = supabase_client.table(table).select(col).limit(1).execute()
            count = len(result.data) if result.data else 0
            print(f"  OK  {table:30s} ({count} row(s) returned)")
        except Exception as e:
            print(f"  FAIL  {table:30s} — {e}")
            all_ok = False
    return all_ok


# ─── Test 2: Fertilizer search (mahbin_npk via RAG pipeline) ────────────────
async def test_fertilizer_question(question: str):
    """ทดสอบถามเรื่องปุ๋ย → ใช้ AgenticRAG ดึงจาก mahbin_npk"""
    from app.services.chat.handler import handle_natural_conversation

    test_user = "test_user_001"
    print(f"\n  Q: {question}")
    t0 = time.time()
    try:
        answer = await handle_natural_conversation(test_user, question)
        elapsed = time.time() - t0
        # Truncate long answers for display
        display = answer[:500] + "..." if len(answer) > 500 else answer
        print(f"  A: {display}")
        print(f"  ({elapsed:.1f}s)")
        return bool(answer and len(answer) > 20)
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


# ─── Test 3: Dealer lookup (dealers table) ───────────────────────────────────
async def test_dealer_question():
    """ทดสอบถามหาตัวแทนจำหน่าย"""
    from app.services.dealer_lookup import is_dealer_question, search_dealers

    question = "หาร้านขายปุ๋ยจังหวัดขอนแก่น"
    print(f"\n  Q: {question}")

    is_dealer = is_dealer_question(question)
    print(f"  is_dealer_question: {is_dealer}")

    try:
        results = await search_dealers(province="ขอนแก่น")
        print(f"  dealers found: {len(results)}")
        for d in results[:3]:
            name = d.get("dealer_name") or d.get("name", "?")
            dist = d.get("district", "?")
            print(f"    → {name} ({dist})")
        return len(results) > 0
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


# ─── Test 4: Hybrid search (mahbin_npk) ─────────────────────────────────────
async def test_hybrid_search():
    """ทดสอบ hybrid_search_products ดึงจาก mahbin_npk"""
    from app.services.product.recommendation import hybrid_search_products

    query = "ปุ๋ยอ้อย"
    print(f"\n  Q: {query}")
    try:
        results = await hybrid_search_products(query, match_count=5)
        print(f"  results: {len(results)}")
        for r in results[:3]:
            name = r.get("fertilizer_formula") or r.get("product_name", "?")
            crop = r.get("crop", "?")
            print(f"    → {name} (crop: {crop})")
        return len(results) > 0
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


# ─── Main ────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("Chatbot พี่ม้าบิน — Smoke Test")
    print("=" * 60)

    results = {}

    # Test 1: Tables
    print("\n[1] Supabase Tables")
    results["tables"] = await test_supabase_tables()

    # Test 2: Hybrid search
    print("\n[2] Hybrid Search (mahbin_npk)")
    results["hybrid"] = await test_hybrid_search()

    # Test 3: Dealer lookup
    print("\n[3] Dealer Lookup (dealers)")
    results["dealer"] = await test_dealer_question()

    # Test 4: Full chat flow — fertilizer questions
    print("\n[4] Full Chat Flow — Fertilizer")
    results["q1"] = await test_fertilizer_question("แนะนำปุ๋ยอ้อยหน่อย")
    results["q2"] = await test_fertilizer_question("ปุ๋ยข้าวโพด เร่งโตไวใช้สูตรไร")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, ok in results.items():
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"\n  {passed}/{total} passed")

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
