"""Add rice herbicide data to knowledge table"""
import asyncio
import sys
import io
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from app.services.services import supabase_client, openai_client

# Rice herbicide data
RICE_HERBICIDES = [
    {
        "title": "โซนิก สำหรับข้าว",
        "product_name": "โซนิก",
        "category": "herbicide",
        "plant_type": "ข้าว",
        "target_pest": "ใช้ก่อนวัชพืชงอก (Pre-emergence) กำจัดวัชพืชประเภทใบแคบ เช่น หญ้าข้าวนก หญ้านกสีชมพู หญ้าดอกขาว หญ้าแดง ในนาหว่านน้ำตม",
        "usage_rate": "ใช้อัตรา 200-250 มล./ไร่ พ่นหลังหว่านข้าว 1-4 วัน แล้วทดน้ำเข้านา 2-3 วัน",
        "content": "โซนิก เป็นสารกำจัดวัชพืชประเภทก่อนงอก (Pre-emergence) สำหรับนาหว่านน้ำตม ใช้กำจัดหญ้าข้าวนก หญ้านกสีชมพู หญ้าดอกขาว หญ้าแดง อัตราใช้ 200-250 มล./ไร่ พ่นหลังหว่านข้าว 1-4 วัน แล้วทดน้ำเข้านา 2-3 วัน"
    },
    {
        "title": "อะนิลการ์ด สำหรับข้าว",
        "product_name": "อะนิลการ์ด",
        "category": "herbicide",
        "plant_type": "ข้าว",
        "target_pest": "ใช้หลังวัชพืชงอก (Post-emergence) กำจัดหญ้าข้าวนก หญ้านกสีชมพู หญ้าดอกขาว ในนาหว่านน้ำตม ใช้ร่วมกับโคเบิ้ล",
        "usage_rate": "ใช้อัตรา 50-100 มล./ไร่ ร่วมกับ โคเบิ้ล 200-250 มล./ไร่ พ่นหลังหว่าน 7-12 วัน ระบายน้ำออกก่อนพ่น แล้วทดน้ำ 1-3 วัน",
        "content": "อะนิลการ์ด เป็นสารกำจัดวัชพืชประเภทหลังงอก (Post-emergence) สำหรับนาหว่านน้ำตม ใช้กำจัดหญ้าข้าวนก หญ้านกสีชมพู ใช้ร่วมกับโคเบิ้ล อัตรา 50-100 มล./ไร่ + โคเบิ้ล 200-250 มล./ไร่ พ่นหลังหว่าน 7-12 วัน ระบายน้ำออกก่อนพ่น แล้วทดน้ำ 1-3 วัน"
    },
    {
        "title": "โคเบิ้ล สำหรับข้าว",
        "product_name": "โคเบิ้ล",
        "category": "herbicide",
        "plant_type": "ข้าว",
        "target_pest": "ใช้หลังวัชพืชงอก (Post-emergence) กำจัดหญ้าข้าวนก หญ้านกสีชมพู หญ้าดอกขาว ในนาหว่านน้ำตม ใช้ร่วมกับอะนิลการ์ด",
        "usage_rate": "ใช้อัตรา 200-250 มล./ไร่ ร่วมกับ อะนิลการ์ด 50-100 มล./ไร่ พ่นหลังหว่าน 7-12 วัน ระบายน้ำออกก่อนพ่น แล้วทดน้ำ 1-3 วัน",
        "content": "โคเบิ้ล เป็นสารกำจัดวัชพืชประเภทหลังงอก (Post-emergence) สำหรับนาหว่านน้ำตม ใช้กำจัดหญ้าข้าวนก หญ้านกสีชมพู ใช้ร่วมกับอะนิลการ์ด อัตรา 200-250 มล./ไร่ + อะนิลการ์ด 50-100 มล./ไร่ พ่นหลังหว่าน 7-12 วัน ระบายน้ำออกก่อนพ่น แล้วทดน้ำ 1-3 วัน"
    },
    {
        "title": "แกนเตอร์ สำหรับข้าว",
        "product_name": "แกนเตอร์",
        "category": "herbicide",
        "plant_type": "ข้าว",
        "target_pest": "ใช้หลังวัชพืชงอก (Post-emergence) กำจัดหญ้าข้าวนก หญ้านกสีชมพู หญ้าดอกขาว หญ้าแดง ในนาหว่านน้ำตม",
        "usage_rate": "ใช้อัตรา 200-250 มล./ไร่ พ่นหลังหว่าน 8-14 วัน ระบายน้ำออกก่อนพ่น แล้วทดน้ำ 1-3 วัน",
        "content": "แกนเตอร์ เป็นสารกำจัดวัชพืชประเภทหลังงอก (Post-emergence) สำหรับนาหว่านน้ำตม ใช้กำจัดหญ้าข้าวนก หญ้านกสีชมพู หญ้าดอกขาว หญ้าแดง อัตรา 200-250 มล./ไร่ พ่นหลังหว่าน 8-14 วัน ระบายน้ำออกก่อนพ่น แล้วทดน้ำ 1-3 วัน"
    },
]

async def generate_embedding(text: str):
    """Generate embedding for text"""
    response = await openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
        encoding_format="float"
    )
    return response.data[0].embedding

async def main():
    print("Adding rice herbicide data to knowledge table...")
    print("=" * 60)

    for herb in RICE_HERBICIDES:
        print(f"\nProcessing: {herb['title']}")

        # Generate embedding from content
        embedding_text = f"{herb['title']} {herb['content']} {herb['target_pest']}"
        embedding = await generate_embedding(embedding_text)
        print(f"  - Generated embedding ({len(embedding)} dimensions)")

        # Insert into knowledge table
        data = {
            "title": herb["title"],
            "product_name": herb["product_name"],
            "category": herb["category"],
            "plant_type": herb["plant_type"],
            "target_pest": herb["target_pest"],
            "usage_rate": herb["usage_rate"],
            "content": herb["content"],
            "embedding": embedding,
            "source": "ICP Ladda Rice Herbicide Guide"
        }

        try:
            result = supabase_client.table("knowledge").insert(data).execute()
            print(f"  - Inserted successfully!")
        except Exception as e:
            print(f"  - Error: {e}")

    print("\n" + "=" * 60)
    print("Done! Verifying...")

    # Verify
    result = supabase_client.table("knowledge").select("title, product_name, category").eq("plant_type", "ข้าว").eq("category", "herbicide").execute()

    print(f"\nRice herbicides in database: {len(result.data)}")
    for r in result.data:
        print(f"  - {r['product_name']}: {r['title']}")

if __name__ == "__main__":
    asyncio.run(main())
