# คู่มือเพิ่มสินค้าและโรคใหม่ในระบบ Chatbot ICP Ladda

> อัปเดตล่าสุด: 14 มกราคม 2026

---

## สารบัญ
1. [ภาพรวมระบบ](#1-ภาพรวมระบบ)
2. [การเพิ่มสินค้าใหม่](#2-การเพิ่มสินค้าใหม่)
3. [การกำหนด pathogen_type](#3-การกำหนด-pathogen_type)
4. [การเพิ่มโรคใหม่ (Code)](#4-การเพิ่มโรคใหม่-code)
5. [SQL Templates](#5-sql-templates)
6. [Checklist](#6-checklist)

---

## 1. ภาพรวมระบบ

### Flow การแนะนำสินค้า
```
User ส่งรูปโรค → AI วิเคราะห์ → ระบุประเภทเชื้อ → Filter สินค้า → แนะนำ
```

### ประเภทเชื้อก่อโรค (pathogen_type)
| ประเภท | ตัวอย่างโรค | สารที่ใช้ |
|--------|------------|----------|
| `oomycetes` | รากเน่าโคนเน่า, ราน้ำค้าง | Fosetyl, Metalaxyl, Cymoxanil |
| `fungi` | ใบจุดสีน้ำตาล, แอนแทรคโนส, ราสนิม | Propiconazole, Carbendazim, Mancozeb |
| `insect` | เพลี้ย, หนอน | Imidacloprid, Fipronil |

### ความสำคัญของ pathogen_type
- ถ้าไม่กำหนด → ระบบอาจแนะนำยาผิดประเภท
- Oomycetes products จะถูกกรองออกสำหรับโรค True Fungi
- True Fungi products จะถูกกรองออกสำหรับโรค Oomycetes

---

## 2. การเพิ่มสินค้าใหม่

### 2.1 เข้า Supabase Dashboard
1. ไปที่ https://supabase.com/dashboard
2. เลือก Project
3. คลิก **Table Editor** → **products**
4. คลิก **Insert Row**

### 2.2 Fields ที่ต้องกรอก

| Field | คำอธิบาย | ตัวอย่าง | จำเป็น |
|-------|---------|---------|--------|
| `product_name` | ชื่อสินค้า (ไทย) | "อาร์เทมิส" | ✅ |
| `active_ingredient` | สารสำคัญ (อังกฤษ) | "DIFENOCONAZOLE + AZOXYSTROBIN 12.5%+20% W/V SC" | ✅ |
| `product_category` | ประเภทสินค้า | `ป้องกันโรค` / `กำจัดแมลง` / `กำจัดวัชพืช` | ✅ |
| `pathogen_type` | ประเภทเชื้อเป้าหมาย | `fungi` / `oomycetes` / `insect` | ✅ |
| `target_pest` | โรค/แมลงที่กำจัดได้ | "โรคใบจุด, โรคราสนิม, โรคกาบใบแห้ง" | ✅ |
| `applicable_crops` | พืชที่ใช้ได้ | "ข้าว, ทุเรียน, อ้อย, มันสำปะหลัง" | ✅ |
| `how_to_use` | วิธีใช้ | "พ่นทางใบ" | ⚪ |
| `usage_rate` | อัตราใช้ | "50 ซีซี/ไร่" | ⚪ |
| `usage_period` | ช่วงเวลาใช้ | "ระยะแตกกอ-ออกรวง" | ⚪ |
| `link_product` | ลิงก์ข้อมูลสินค้า | "https://..." | ⚪ |
| `image_url` | รูปสินค้า | "https://..." | ⚪ |

---

## 3. การกำหนด pathogen_type

### 3.1 สินค้าสำหรับ Oomycetes (pathogen_type = 'oomycetes')

**Active Ingredients:**
- Fosetyl-Aluminium (วอร์แรนต์, อะลูเอท)
- Metalaxyl / Mefenoxam (คาริสมา)
- Cymoxanil (ไซม๊อกซิเมท)
- Propamocarb
- Dimethomorph (โทมาฮอค)
- Mandipropamid

**โรคที่ใช้:**
- รากเน่าโคนเน่า (Phytophthora)
- ราน้ำค้าง (Downy Mildew)
- ผลเน่า (Fruit Rot)
- ยางไหล, เปลือกเน่า

### 3.2 สินค้าสำหรับ True Fungi (pathogen_type = 'fungi')

**Active Ingredients:**
- Triazoles: Propiconazole, Difenoconazole, Tebuconazole, Hexaconazole
- Benzimidazoles: Carbendazim, Benomyl
- Strobilurins: Azoxystrobin, Trifloxystrobin
- Dithiocarbamates: Mancozeb, Propineb
- Others: Prochloraz, Chlorothalonil, Copper compounds

**โรคที่ใช้:**
- ใบจุดสีน้ำตาล (Cercospora, Bipolaris)
- แอนแทรคโนส (Colletotrichum)
- ราสนิม (Puccinia)
- กาบใบแห้ง (Rhizoctonia)
- แส้ดำ (Sporisorium)

### 3.3 สินค้าสำหรับแมลง (pathogen_type = 'insect')

**Active Ingredients:**
- Neonicotinoids: Imidacloprid, Thiamethoxam
- Pyrethroids: Cypermethrin, Deltamethrin
- Others: Fipronil, Abamectin, Chlorpyrifos

**แมลงที่กำจัด:**
- เพลี้ยกระโดด, เพลี้ยจักจั่น, เพลี้ยอ่อน
- หนอนกอ, หนอนเจาะลำต้น
- แมลงหวี่ขาว

---

## 4. การเพิ่มโรคใหม่ (Code)

> ⚠️ ต้องแก้ไข Code เฉพาะเมื่อเพิ่มโรคใหม่ที่ไม่มี keyword ในระบบ

### 4.1 ไฟล์ที่ต้องแก้ไข
```
app/services/product_recommendation.py
```

### 4.2 เพิ่ม Keyword โรคเชื้อรา (True Fungi)

หา `FUNGAL_KEYWORDS` แล้วเพิ่ม keyword:

```python
FUNGAL_KEYWORDS = [
    # โรคที่มีอยู่แล้ว...

    # เพิ่มโรคใหม่ที่นี่
    "ชื่อโรคภาษาไทย", "english disease name", "ชื่อเชื้อ",
]
```

### 4.3 เพิ่ม Keyword โรค Oomycetes

หา `OOMYCETES_DISEASES` แล้วเพิ่ม keyword:

```python
OOMYCETES_DISEASES = [
    # โรคที่มีอยู่แล้ว...

    # เพิ่มโรคใหม่ที่นี่
    "ชื่อโรคภาษาไทย", "english disease name",
]
```

### 4.4 Deploy หลังแก้ Code

```bash
git add .
git commit -m "feat: เพิ่ม keyword โรคใหม่"
git push
```

Railway จะ auto-deploy ภายใน 2-3 นาที

---

## 5. SQL Templates

### 5.1 เพิ่มสินค้าใหม่

```sql
INSERT INTO products (
    product_name,
    active_ingredient,
    product_category,
    pathogen_type,
    target_pest,
    applicable_crops,
    how_to_use,
    usage_rate
) VALUES (
    'ชื่อสินค้า',
    'ACTIVE INGREDIENT XX% FORMULATION',
    'ป้องกันโรค',    -- หรือ 'กำจัดแมลง', 'กำจัดวัชพืช'
    'fungi',         -- หรือ 'oomycetes', 'insect'
    'โรคใบจุด, โรคราสนิม, โรคแอนแทรคโนส',
    'ข้าว, ทุเรียน, อ้อย, มันสำปะหลัง, ข้าวโพด',
    'พ่นทางใบ',
    '50 ซีซี/ไร่'
);
```

### 5.2 อัปเดต pathogen_type สินค้าที่มีอยู่

```sql
-- อัปเดตสินค้า Oomycetes
UPDATE products
SET pathogen_type = 'oomycetes'
WHERE active_ingredient ILIKE '%fosetyl%'
   OR active_ingredient ILIKE '%metalaxyl%'
   OR active_ingredient ILIKE '%cymoxanil%';

-- อัปเดตสินค้า Fungi
UPDATE products
SET pathogen_type = 'fungi'
WHERE active_ingredient ILIKE '%propiconazole%'
   OR active_ingredient ILIKE '%carbendazim%'
   OR active_ingredient ILIKE '%mancozeb%';

-- อัปเดตสินค้า Insect
UPDATE products
SET pathogen_type = 'insect'
WHERE product_category = 'กำจัดแมลง';
```

### 5.3 ตรวจสอบสินค้าตาม pathogen_type

```sql
-- ดูสรุปจำนวน
SELECT pathogen_type, COUNT(*) as count
FROM products
GROUP BY pathogen_type
ORDER BY count DESC;

-- ดูสินค้าที่ยังไม่มี pathogen_type
SELECT product_name, active_ingredient, product_category
FROM products
WHERE pathogen_type IS NULL OR pathogen_type = '';
```

---

## 6. Checklist

### เพิ่มสินค้าใหม่
- [ ] เพิ่มข้อมูลใน Supabase Table Editor
- [ ] กำหนด `product_category` ถูกต้อง
- [ ] กำหนด `pathogen_type` ถูกต้อง
- [ ] ใส่ `target_pest` ครอบคลุมโรคที่กำจัดได้
- [ ] ใส่ `applicable_crops` ครอบคลุมพืชที่ใช้ได้
- [ ] ทดสอบในระบบ

### เพิ่มโรคใหม่
- [ ] เพิ่ม keyword ใน `FUNGAL_KEYWORDS` หรือ `OOMYCETES_DISEASES`
- [ ] Commit และ Push code
- [ ] รอ Railway deploy (2-3 นาที)
- [ ] ทดสอบในระบบ

---

## ติดต่อ

หากมีปัญหาหรือต้องการความช่วยเหลือ:
- GitHub: https://github.com/AtenVisarut/Chatbot-ladda
- ติดต่อทีมพัฒนา

---

*สร้างโดย Claude Code - 14 มกราคม 2026*
