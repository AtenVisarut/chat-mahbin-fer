"""
Import CSV using direct SQL (bypass Supabase client cache)
"""
import os
import csv
import json
import sys
import psycopg2
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Extract connection details from Supabase URL
# Format: https://xxxxx.supabase.co
project_ref = SUPABASE_URL.replace("https://", "").replace(".supabase.co", "")

# Supabase connection string
# You need to get this from Supabase Dashboard → Settings → Database
# Format: postgresql://postgres:[password]@db.[project-ref].supabase.co:5432/postgres

def generate_embedding(text: str, openai_client: OpenAI):
    """Generate embedding using OpenAI"""
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"  ✗ Error generating embedding: {e}")
        return None

def import_with_direct_sql(csv_path: str, db_password: str):
    """Import using direct PostgreSQL connection"""
    
    print("=" * 60)
    print("Import CSV using Direct SQL")
    print("=" * 60)
    
    # Initialize OpenAI
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
    
    # Connect to PostgreSQL
    conn_string = f"postgresql://postgres.{project_ref}:{db_password}@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
    
    print(f"\n1. Connecting to database...")
    try:
        conn = psycopg2.connect(conn_string)
        cur = conn.cursor()
        print("✓ Connected")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        print("\nPlease provide your database password from:")
        print("Supabase Dashboard → Settings → Database → Connection string")
        return
    
    # Read CSV
    print(f"\n2. Reading CSV: {csv_path}")
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"✓ Found {len(rows)} products")
    
    # Import
    print("\n3. Importing products...")
    success_count = 0
    error_count = 0
    
    for idx, row in enumerate(rows, 1):
        try:
            product_name = row.get('ชื่อสินค้า (ชื่อการค้า)', '').strip()
            if not product_name:
                continue
            
            print(f"[{idx}/{len(rows)}] {product_name}")
            
            # Build embedding text
            embedding_text = f"ชื่อสินค้า: {product_name} | " + \
                           f"สารสำคัญ: {row.get('สารสําคัญ', '')} | " + \
                           f"ศัตรูพืช: {row.get('ศัตรูพืชที่กำจัดได้', '')}"
            
            # Generate embedding
            print(f"  → Generating embedding...")
            embedding = generate_embedding(embedding_text, openai_client)
            if not embedding:
                error_count += 1
                continue
            
            # Insert using SQL
            print(f"  → Inserting...")
            cur.execute("""
                INSERT INTO products (
                    product_name, active_ingredient, target_pest,
                    applicable_crops, how_to_use, product_group,
                    formulation, usage_rate, metadata, embedding
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                product_name,
                row.get('สารสําคัญ', ''),
                row.get('ศัตรูพืชที่กำจัดได้', ''),
                row.get('ใช้ได้กับพืช', ''),
                row.get('วิธีใช้', ''),
                row.get('กลุ่มสาร', ''),
                row.get('Formulation', ''),
                row.get('อัตราการใช้', ''),
                json.dumps(row, ensure_ascii=False),
                embedding
            ))
            
            conn.commit()
            print(f"  ✓ Success!")
            success_count += 1
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
            error_count += 1
            conn.rollback()
            continue
    
    cur.close()
    conn.close()
    
    print("\n" + "=" * 60)
    print(f"Import completed!")
    print(f"✓ Success: {success_count}")
    print(f"✗ Errors: {error_count}")
    print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_direct_sql.py <csv_file> [db_password]")
        print("\nGet your database password from:")
        print("Supabase Dashboard → Settings → Database → Connection string")
        sys.exit(1)
    
    csv_file = sys.argv[1]
    db_password = sys.argv[2] if len(sys.argv) > 2 else input("Enter database password: ")
    
    if not os.path.exists(csv_file):
        print(f"Error: CSV file not found: {csv_file}")
        sys.exit(1)
    
    import_with_direct_sql(csv_file, db_password)
