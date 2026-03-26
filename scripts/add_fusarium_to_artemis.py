"""
Script: เพิ่ม ฟิวซาเรียม (Fusarium) ใน อาร์เทมีส target_pest + regenerate embedding
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

PRODUCT_ID = 263  # อาร์เทมีส


def generate_embedding(text: str) -> list:
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding


def main():
    print("=== เพิ่ม ฟิวซาเรียม (Fusarium) ใน อาร์เทมีส ===\n")

    # 1. Get current data
    result = supabase_client.table('products').select('product_name, target_pest').eq('id', PRODUCT_ID).execute()
    if not result.data:
        print("ERROR: ไม่เจออาร์เทมีส!")
        return

    current = result.data[0]
    print(f"Product: {current['product_name']}")
    print(f"Current target_pest:\n{current['target_pest']}\n")

    # 2. Update target_pest — เพิ่มฟิวซาเรียมในส่วนทุเรียน
    new_target_pest = (
        "(นาข้าว) โรคกาบใบแห้ง ใบขีดสีน้ำตาล เมล็ดด่าง เน่าคอรวง\n"
        "(ข้าวโพด) โรคใบไหม้แผลใหญ่\n"
        "(หอม กระเทียม) โรคหอมเลื้อย ใบจุดสีม่วง\n"
        "(ทุเรียน) แอนแทรคโนส ใบจุด ราสนิม ผลเน่า ใบติด ราสีชมพู ฟิวซาเรียม\n"
        "(ทั่วไป) โรคเชื้อราฟิวซาเรียม (Fusarium)"
    )

    print(f"New target_pest:\n{new_target_pest}\n")

    # 3. Regenerate embedding — เพิ่ม Fusarium keywords
    embedding_text = (
        f"ชื่อสินค้า: อาร์เทมีส | "
        f"ประเภท: ยาป้องกันกำจัดเชื้อรา โรคพืช Fungicide | "
        f"สารสำคัญ: ไดฟีโนโคนาโซล + อะซ๊อคซีสโตรบิน Difenoconazole Azoxystrobin | "
        f"โรคในนาข้าว: กาบใบแห้ง ใบขีดสีน้ำตาล เมล็ดด่าง เน่าคอรวง | "
        f"โรคในข้าวโพด: ใบไหม้แผลใหญ่ | "
        f"โรคในหอม กระเทียม: หอมเลื้อย ใบจุดสีม่วง | "
        f"โรคในทุเรียน: แอนแทรคโนส ใบจุด ราสนิม ผลเน่า ใบติด ราสีชมพู ฟิวซาเรียม | "
        f"โรคเชื้อรา: ฟิวซาเรียม Fusarium โรคเหี่ยว โรคเน่า wilt | "
        f"ใช้ได้กับพืช: นาข้าว ทุเรียน ข้าวโพด หอม กระเทียม ผัก ผลไม้ | "
        f"จุดเด่น: ดูดซึมเร็ว ปกป้องยาวนาน สูตรเย็นปลอดภัยต่อดอกและผลอ่อน ใช้ได้กับโดรน"
    )

    print("Generating embedding...")
    embedding = generate_embedding(embedding_text)
    if not embedding:
        print("ERROR: Failed to generate embedding!")
        return
    print(f"Embedding generated: {len(embedding)} dimensions\n")

    # 4. Update in Supabase
    print("Updating Supabase...")
    update_data = {
        "target_pest": new_target_pest,
        "embedding": embedding,
    }

    supabase_client.table('products').update(update_data).eq('id', PRODUCT_ID).execute()
    print("Updated successfully!\n")

    # 5. Verify
    verify = supabase_client.table('products').select('product_name, target_pest').eq('id', PRODUCT_ID).execute()
    if verify.data:
        print("=== Verify ===")
        print(f"target_pest:\n{verify.data[0]['target_pest']}")
        has_fusarium = 'ฟิวซาเรียม' in verify.data[0]['target_pest']
        print(f"\nฟิวซาเรียม in target_pest: {has_fusarium}")

    print("\n=== DONE ===")


if __name__ == "__main__":
    main()
