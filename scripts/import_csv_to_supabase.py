"""
Import CSV data to Supabase with embeddings
"""
import os
import csv
import json
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI
import time

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

def generate_embedding(text: str) -> list:
    """Generate embedding using OpenAI"""
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"Error generating embedding: {e}")
        return None

def import_csv_to_supabase(csv_path: str):
    """Import CSV data to Supabase with embeddings"""
    
    print(f"Reading CSV file: {csv_path}")
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    print(f"Found {len(rows)} products")
    
    success_count = 0
    error_count = 0
    
    for idx, row in enumerate(rows, 1):
        try:
            # Extract key fields
            product_name = row.get('ชื่อสินค้า (ชื่อการค้า)', '').strip()
            if not product_name:
                print(f"Row {idx}: Skipping - no product name")
                continue
            
            active_ingredient = row.get('สารสําคัญ', '').strip()
            target_pest = row.get('ศัตรูพืชที่กำจัดได้', '').strip()
            applicable_crops = row.get('ใช้ได้กับพืช', '').strip()
            how_to_use = row.get('วิธีใช้', '').strip()
            product_group = row.get('กลุ่มสาร', '').strip()
            formulation = row.get('Formulation', '').strip()
            usage_rate = row.get('อัตราการใช้', '').strip()
            
            # Create enhanced text for embedding (focus on pest control info)
            # Extract product type
            product_type = ""
            if "Insecticide" in product_group or "แมลง" in target_pest or "หนอน" in target_pest or "เพลี้ย" in target_pest:
                product_type = "ยากำจัดแมลง ศัตรูพืช"
            elif "Fungicide" in product_group or "รา" in target_pest or "โรค" in target_pest:
                product_type = "ยากำจัดเชื้อรา โรคพืช"
            elif "Herbicide" in product_group or "วัชพืช" in target_pest:
                product_type = "ยากำจัดวัชพืช"
            
            # Build comprehensive embedding text
            embedding_parts = [
                f"ชื่อสินค้า: {product_name}",
                f"ประเภท: {product_type}" if product_type else "",
                f"สารสำคัญ: {active_ingredient}" if active_ingredient else "",
                f"ศัตรูพืชที่กำจัดได้: {target_pest}" if target_pest else "",
                f"ใช้ได้กับพืช: {applicable_crops}" if applicable_crops else "",
                f"กลุ่มสาร: {product_group}" if product_group else "",
            ]
            
            embedding_text = " | ".join([p for p in embedding_parts if p]).strip()
            
            # Generate embedding
            print(f"[{idx}/{len(rows)}] Processing: {product_name}")
            embedding = generate_embedding(embedding_text)
            
            if not embedding:
                print(f"  ⚠️  Failed to generate embedding")
                error_count += 1
                continue
            
            # Prepare data for Supabase
            data = {
                'product_name': product_name,
                'active_ingredient': active_ingredient,
                'target_pest': target_pest,
                'applicable_crops': applicable_crops,
                'how_to_use': how_to_use,
                'product_group': product_group,
                'formulation': formulation,
                'usage_rate': usage_rate,
                'metadata': json.dumps(row, ensure_ascii=False),
                'embedding': embedding
            }
            
            # Insert to Supabase
            result = supabase.table('products').insert(data).execute()
            
            print(f"  ✓ Imported successfully")
            success_count += 1
            
            # Rate limiting
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
            error_count += 1
            continue
    
    print("\n" + "="*60)
    print(f"Import completed!")
    print(f"Success: {success_count}")
    print(f"Errors: {error_count}")
    print("="*60)

if __name__ == "__main__":
    import sys
    
    # Check if CSV path provided as argument
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    else:
        csv_file = "Data ICPL product for iDA.csv"
    
    if not os.path.exists(csv_file):
        print(f"Error: CSV file not found: {csv_file}")
        print(f"Usage: python {sys.argv[0]} <path_to_csv>")
        exit(1)
    
    print("Starting CSV import to Supabase...")
    print("="*60)
    
    import_csv_to_supabase(csv_file)
