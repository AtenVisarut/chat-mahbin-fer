"""
Script: เปลี่ยนชื่อ อาร์เทมีส → อาร์เทมิส ใน embedding_text + regenerate embedding

Usage:
    python scripts/rename_artemis_embedding.py
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.chdir("C:\\clone_chatbot_ick\\Chatbot-ladda")
sys.path.insert(0, "C:\\clone_chatbot_ick\\Chatbot-ladda")

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from app.config import OPENAI_API_KEY
from app.services.services import supabase_client

openai_client = OpenAI(api_key=OPENAI_API_KEY)

PRODUCT_ID = 263  # อาร์เทมิส (formerly อาร์เทมีส)


def generate_embedding(text: str) -> list:
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding


def main():
    print("=== Rename อาร์เทมีส → อาร์เทมิส in embedding ===\n")

    # 1. Get current data
    result = supabase_client.table('products').select(
        'id, product_name, target_pest, embedding_text'
    ).eq('id', PRODUCT_ID).execute()

    if not result.data:
        print("ERROR: ไม่เจอ product id=263!")
        return

    current = result.data[0]
    print(f"Product: {current['product_name']}")
    old_embedding_text = current.get('embedding_text', '')
    print(f"Current embedding_text (first 200 chars):\n{old_embedding_text[:200]}...\n")

    # 2. Replace อาร์เทมีส → อาร์เทมิส in embedding_text
    if old_embedding_text and 'อาร์เทมีส' in old_embedding_text:
        new_embedding_text = old_embedding_text.replace('อาร์เทมีส', 'อาร์เทมิส')
        print("Replaced 'อาร์เทมีส' → 'อาร์เทมิส' in embedding_text")
    else:
        # Fallback: build new embedding_text from scratch
        new_embedding_text = (
            "ชื่อสินค้า: อาร์เทมิส | "
            "ประเภท: ยาป้องกันกำจัดเชื้อรา โรคพืช Fungicide | "
            "สารสำคัญ: ไดฟีโนโคนาโซล + อะซ๊อคซีสโตรบิน Difenoconazole Azoxystrobin | "
            "โรคในนาข้าว: กาบใบแห้ง ใบขีดสีน้ำตาล เมล็ดด่าง เน่าคอรวง | "
            "โรคในข้าวโพด: ใบไหม้แผลใหญ่ | "
            "โรคในหอม กระเทียม: หอมเลื้อย ใบจุดสีม่วง | "
            "โรคในทุเรียน: แอนแทรคโนส ใบจุด ราสนิม ผลเน่า ใบติด ราสีชมพู ฟิวซาเรียม | "
            "โรคเชื้อรา: ฟิวซาเรียม Fusarium โรคเหี่ยว โรคเน่า wilt | "
            "ใช้ได้กับพืช: นาข้าว ทุเรียน ข้าวโพด หอม กระเทียม ผัก ผลไม้ | "
            "จุดเด่น: ดูดซึมเร็ว ปกป้องยาวนาน สูตรเย็นปลอดภัยต่อดอกและผลอ่อน ใช้ได้กับโดรน"
        )
        print("Built new embedding_text from scratch (old text missing or no match)")

    print(f"\nNew embedding_text (first 200 chars):\n{new_embedding_text[:200]}...\n")

    # 3. Also rename product_name in DB if still old
    new_product_name = current['product_name']
    if current['product_name'] == 'อาร์เทมีส':
        new_product_name = 'อาร์เทมิส'
        print("Will also rename product_name: อาร์เทมีส → อาร์เทมิส")

    # 4. Regenerate embedding
    print("\nGenerating embedding...")
    embedding = generate_embedding(new_embedding_text)
    if not embedding:
        print("ERROR: Failed to generate embedding!")
        return
    print(f"Embedding generated: {len(embedding)} dimensions")

    # 5. Update in Supabase
    print("\nUpdating Supabase...")
    update_data = {
        "product_name": new_product_name,
        "embedding_text": new_embedding_text,
        "embedding": embedding,
    }

    supabase_client.table('products').update(update_data).eq('id', PRODUCT_ID).execute()
    print("Updated successfully!")

    # 6. Verify
    verify = supabase_client.table('products').select(
        'product_name, embedding_text'
    ).eq('id', PRODUCT_ID).execute()
    if verify.data:
        print(f"\n=== Verify ===")
        print(f"product_name: {verify.data[0]['product_name']}")
        et = verify.data[0].get('embedding_text', '')
        has_new = 'อาร์เทมิส' in et
        has_old = 'อาร์เทมีส' in et
        print(f"'อาร์เทมิส' in embedding_text: {has_new}")
        print(f"'อาร์เทมีส' in embedding_text: {has_old} (should be False)")

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
