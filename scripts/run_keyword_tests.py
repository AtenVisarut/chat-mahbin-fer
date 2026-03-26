import os
import sys

# Ensure workspace root is on path
SCRIPT_DIR = os.path.dirname(__file__)
WORKSPACE_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

from app.utils.text_processing import extract_keywords_from_question

TEST_QUERIES = [
    "Durian yield",
    "durian yield",
    "How to increase durian yield?",
    "ทุเรียน เพิ่มผลผลิต",
    "durian pests",
    "ทุเรียน เพลี้ยไฟ",
    "Fertilizer for durian",
    "What products for durian",
]

print("Running keyword extraction tests:\n")
for q in TEST_QUERIES:
    k = extract_keywords_from_question(q)
    print(f"Query: {q}")
    print(f"  crops: {k['crops']}")
    print(f"  pests: {k['pests']}")
    print(f"  products: {k['products']}")
    print(f"  intent: {k['intent']}")
    print(f"  is_product_query: {k['is_product_query']}")
    print('-' * 40)
