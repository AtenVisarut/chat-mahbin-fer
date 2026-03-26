"""
Update/Upsert อาร์เทมีส (Artemis) product in Supabase
"""
import os
import sys
import io
import json

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)


def generate_embedding(text: str) -> list:
    response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    )
    return response.data[0].embedding


def update_artemis():
    product_data = {
        "product_name": "อาร์เทมีส",
        "active_ingredient": "ไดฟีโนโคนาโซล + อะซ๊อคซีสโตรบิน (DIFENOCONAZOLE + AZOXYSTROBIN 12.5%+20% W/V SC)",
        "product_category": "ป้องกันโรค",
        "target_pest": (
            "(นาข้าว) โรคกาบใบแห้ง ใบขีดสีน้ำตาล เมล็ดด่าง เน่าคอรวง\n"
            "(ข้าวโพด) โรคใบไหม้แผลใหญ่\n"
            "(หอม กระเทียม) โรคหอมเลื้อย ใบจุดสีม่วง\n"
            "(ทุเรียน) แอนแทรคโนส ใบจุด ราสนิม ผลเน่า ใบติด ราสีชมพู"
        ),
        "applicable_crops": "นาข้าว ทุเรียน ข้าวโพด หอม กระเทียม ผัก ผลไม้",
        "how_to_use": (
            "(นาข้าว) ใช้ 50 ซีซี/ไร่ พ่นช่วงข้าวแตกกอ-ออกรวง ใช้ได้กับโดรน พ่นแม่นยำทั่วแปลง\n"
            "(ทุเรียน) ใช้ 10 ซีซี/น้ำ 20 ลิตร ฉีดพ่นทุก 7-10 วัน หรือตามการระบาดของโรค ฉีดพ่นให้ทั่วทรงพุ่ม"
        ),
        "usage_rate": (
            "(นาข้าว) 50 ซีซี/ไร่ (1 ขวด ใช้ได้ถึง 20 ไร่)\n"
            "(ทุเรียน) 10 ซีซี/น้ำ 20 ลิตร ฉีดพ่นทุก 7-10 วัน หรือตามการระบาดของโรค"
        ),
        "usage_period": (
            "(นาข้าว) พ่นช่วงข้าวแตกกอ-ออกรวง ในข้าวระยะตั้งท้อง เพื่อป้องกันโรคก่อนที่จะระบาด\n"
            "(ทุเรียน) ฉีดพ่นทุก 7-10 วัน หรือตามการระบาดของโรค"
        ),
        "selling_point": (
            "สารป้องกันกำจัดเชื้อราออกฤทธิ์ดูดซึม ผสม 2 พลังบวก (ไดฟีโนโคนาโซล+อะซอกซีสโตรบิน) | "
            "ป้องกันและรักษากว้างขวาง | ปลอดภัยต่อดอกและผลอ่อน | "
            "ใช้ได้ทั้งในนาข้าว ข้าวโพด หอม และไม้ผล เช่น ทุเรียน | "
            "แก้ปัญหาโรคใบติด ราสีชมพู และแอนแทรคโนสได้อย่างมีประสิทธิภาพสูง | "
            "ดูดซึมเร็ว ออกฤทธิ์ไว | ปกป้องได้ทุกระยะการเติบโต | "
            "ใช้ได้กับโดรน พ่นแม่นยำทั่วแปลง | "
            "ใช้แล้วใบเขียว ผิวนวล ผลสะอาด | "
            "สูตรเย็นปลอดภัยต่อดอกและผลอ่อน"
        ),
        "action_characteristics": "ออกฤทธิ์แบบดูดซึม (Systemic) ดูดซึมเร็ว ออกฤทธิ์ไว ป้องกันกำจัดเชื้อราได้กว้าง",
        "package_size": "1 ลิตร",
        "link_product": "http://system.icpladda.com/CDN//difeno_azoxystrobin_%E0%B8%AD%E0%B8%B2%E0%B8%A3%E0%B9%8C%E0%B9%80%E0%B8%97%E0%B8%A1%E0%B8%B4%E0%B8%AA_07042025_213519.pdf",
        "pathogen_type": "เชื้อรา",
    }

    # Generate embedding — ต้องครอบคลุมทุกพืช+โรค เพื่อให้ semantic search หาเจอ
    embedding_text = (
        f"ชื่อสินค้า: อาร์เทมีส | "
        f"ประเภท: ยาป้องกันกำจัดเชื้อรา โรคพืช Fungicide | "
        f"สารสำคัญ: ไดฟีโนโคนาโซล + อะซ๊อคซีสโตรบิน Difenoconazole Azoxystrobin | "
        f"โรคในนาข้าว: กาบใบแห้ง ใบขีดสีน้ำตาล เมล็ดด่าง เน่าคอรวง | "
        f"โรคในข้าวโพด: ใบไหม้แผลใหญ่ | "
        f"โรคในหอม กระเทียม: หอมเลื้อย ใบจุดสีม่วง | "
        f"โรคในทุเรียน: แอนแทรคโนส ใบจุด ราสนิม ผลเน่า ใบติด ราสีชมพู | "
        f"ใช้ได้กับพืช: นาข้าว ทุเรียน ข้าวโพด หอม กระเทียม ผัก ผลไม้ | "
        f"จุดเด่น: ดูดซึมเร็ว ปกป้องยาวนาน สูตรเย็นปลอดภัยต่อดอกและผลอ่อน ใช้ได้กับโดรน"
    )

    print("Generating embedding...")
    embedding = generate_embedding(embedding_text)
    if not embedding:
        print("Failed to generate embedding!")
        return

    product_data["embedding"] = embedding

    # Check if อาร์เทมีส already exists
    print("Checking existing data...")
    existing = supabase.table("products").select("id").eq("product_name", "อาร์เทมีส").execute()

    if existing.data:
        # Update existing
        row_id = existing.data[0]["id"]
        print(f"Found existing record id={row_id}, updating...")
        result = supabase.table("products").update(product_data).eq("id", row_id).execute()
        print(f"Updated successfully! id={row_id}")
    else:
        # Insert new
        print("No existing record, inserting new...")
        result = supabase.table("products").insert(product_data).execute()
        print(f"Inserted successfully! id={result.data[0]['id']}")

    # Verify
    verify = supabase.table("products").select(
        "id, product_name, active_ingredient, target_pest, applicable_crops, "
        "usage_rate, usage_period, how_to_use, selling_point, "
        "action_characteristics, package_size, pathogen_type"
    ).eq("product_name", "อาร์เทมีส").execute()
    if verify.data:
        row = verify.data[0]
        print(f"\nVerification:")
        for key in ["id", "product_name", "active_ingredient", "target_pest",
                     "applicable_crops", "usage_rate", "usage_period",
                     "how_to_use", "selling_point", "action_characteristics",
                     "package_size", "pathogen_type"]:
            val = row.get(key, "N/A")
            print(f"  {key}: {val}")


if __name__ == "__main__":
    print("=" * 60)
    print("Updating อาร์เทมีส (Artemis) in Supabase")
    print("=" * 60)
    update_artemis()
    print("\nDone!")
