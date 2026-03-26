# LINE Plant Disease Detection Bot

ระบบ LINE Chatbot สำหรับวิเคราะห์โรคพืชจากรูปภาพ และแนะนำผลิตภัณฑ์ที่เหมาะสม พร้อมระบบ Q&A และพยากรณ์สภาพอากาศสำหรับเกษตรกร

## สารบัญ

- [ฟีเจอร์หลัก](#ฟีเจอร์หลัก)
- [โครงสร้างโปรเจค](#โครงสร้างโปรเจค)
- [เทคโนโลยีที่ใช้](#เทคโนโลยีที่ใช้)
- [การติดตั้ง](#การติดตั้ง)
- [Environment Variables](#environment-variables)
- [API Endpoints](#api-endpoints)
- [การ Deploy](#การ-deploy)
- [การใช้งาน](#การใช้งาน)

---

## ฟีเจอร์หลัก

### 1. Disease Detection (วิเคราะห์โรคพืช)
- รับรูปภาพพืชจากผู้ใช้
- วิเคราะห์ด้วย **Gemini Vision API**
- ผลลัพธ์: ชื่อโรค, อาการ, ความรุนแรง, ความมั่นใจ
- รองรับ caching เพื่อเพิ่มความเร็ว

### 2. Product Recommendation (แนะนำผลิตภัณฑ์)
- ใช้ **Vector Search** (Supabase pgvector) จับคู่สินค้า
- Re-rank ด้วย LLM เพื่อความแม่นยำ
- เลือกระยะการเจริญเติบโตก่อนแนะนำ
- แสดงผลแบบ Carousel

### 3. Weather & Agro-Risk (สภาพอากาศ & ความเสี่ยง)
- รับ location จากผู้ใช้
- พยากรณ์ฝน 7 วัน
- วิเคราะห์ความเสี่ยงทางการเกษตร
- ให้คำแนะนำตามสภาพอากาศ

### 4. Natural Conversation (Q&A)
- ตอบคำถามทั่วไปเกี่ยวกับการเกษตร
- ใช้ Knowledge Base + GPT
- เก็บ conversation memory เพื่อบริบท

### 5. User Registration & LIFF
- LIFF web form สำหรับลงทะเบียน
- เก็บข้อมูลผู้ใช้ใน Supabase
- ต้องลงทะเบียนก่อนใช้งาน

### 6. Analytics Dashboard
- ติดตามสถิติการใช้งาน
- Dashboard แสดงข้อมูล
- Admin login protection

---

## โครงสร้างโปรเจค

```
.
├── app/
│   ├── main.py                    # FastAPI application หลัก
│   ├── config.py                  # Configuration & environment variables
│   ├── models.py                  # Pydantic models
│   ├── analytics.py               # Analytics & monitoring
│   │
│   ├── services/                  # Business Logic
│   │   ├── disease_detection.py   # วิเคราะห์โรคด้วย Gemini Vision
│   │   ├── product_recommendation.py  # Vector search & แนะนำสินค้า
│   │   ├── chat.py                # จัดการสนทนา Q&A
│   │   ├── agro_risk.py           # วิเคราะห์สภาพอากาศ
│   │   ├── knowledge_base.py      # RAG knowledge base
│   │   ├── response_generator.py  # สร้าง Flex Messages
│   │   ├── cache.py               # In-memory caching
│   │   ├── memory.py              # Conversation memory
│   │   ├── user_service.py        # จัดการผู้ใช้
│   │   ├── liff_service.py        # LIFF registration
│   │   ├── registration.py        # User registration logic
│   │   ├── reranker.py            # Product re-ranking
│   │   ├── disease_database.py    # ฐานข้อมูลโรคพืช
│   │   ├── welcome.py             # Welcome messages
│   │   ├── rich_menu.py           # LINE Rich Menu
│   │   └── services.py            # Service initialization
│   │
│   └── utils/                     # Utilities
│       ├── flex_messages.py       # LINE Flex Message builders
│       ├── line_helpers.py        # LINE API helpers
│       ├── question_templates.py  # Question templates
│       ├── rate_limiter.py        # Rate limiting
│       ├── response_template.py   # Response formatting
│       └── text_processing.py     # Text processing
│
├── api/
│   └── index.py                   # Vercel/serverless entry point
│
├── docs/                          # Documentation
├── config/                        # Project configs
├── liff/                          # LIFF web app
├── templates/                     # HTML templates
├── data/                          # Knowledge base data
├── scripts/                       # Helper scripts
│
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Docker configuration
├── .env.example                   # Environment template
└── README.md                      # This file
```

---

## เทคโนโลยีที่ใช้

| เทคโนโลยี | ใช้สำหรับ |
|-----------|----------|
| **FastAPI** | Web framework (async) |
| **Uvicorn** | ASGI server |
| **LINE Messaging API** | LINE bot interface |
| **OpenAI GPT** | Chat Q&A, Embeddings |
| **Gemini Vision** (OpenRouter) | Disease detection |
| **Supabase** | Database, Vector search, Auth |
| **pgvector** | Vector similarity search |
| **LIFF** | LINE web app (registration) |
| **Jinja2** | HTML templates |

---

## การติดตั้ง

### 1. Clone repository
```bash
git clone https://github.com/AtenVisarut/Chatbot-ladda.git
cd Chatbot-ladda
```

### 2. สร้าง Virtual Environment
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. ติดตั้ง Dependencies
```bash
pip install -r requirements.txt
```

### 4. ตั้งค่า Environment Variables
```bash
cp .env.example .env
# แก้ไขไฟล์ .env ใส่ค่าที่ถูกต้อง
```

### 5. รันแบบ Development
```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Environment Variables

```bash
# LINE Configuration (required)
LINE_CHANNEL_ACCESS_TOKEN=your_token
LINE_CHANNEL_SECRET=your_secret

# OpenAI Configuration (required)
OPENAI_API_KEY=sk-...

# OpenRouter - Gemini Vision (required)
OPENROUTER_API_KEY=sk-or-...

# Supabase Configuration (required)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_anon_key

# Agro-Risk API (optional)
AGRO_RISK_API_URL=https://thai-water.vercel.app

# Admin Authentication
ADMIN_USERNAME=ladda
ADMIN_PASSWORD=ladda123
SECRET_KEY=your-secret-key

# LIFF Configuration
LIFF_ID=your_liff_id

# Cache Settings
CACHE_TTL=3600
MAX_CACHE_SIZE=1000

# Rate Limiting
USER_RATE_LIMIT=10
USER_RATE_WINDOW=60

# Memory Settings
MAX_MEMORY_MESSAGES=40
MEMORY_CONTEXT_WINDOW=20
```

---

## API Endpoints

### Health Check
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Service status |
| GET | `/health` | Detailed health info |

### Cache
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/cache/stats` | Cache statistics |
| POST | `/cache/clear` | Clear all caches |

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/login` | Login page |
| POST | `/login` | Login handler |
| GET | `/logout` | Logout |

### Dashboard
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/dashboard` | Analytics dashboard |
| GET | `/api/analytics/dashboard` | Dashboard data |
| GET | `/api/analytics/health` | System health |
| GET | `/api/analytics/alerts` | Active alerts |

### LIFF (Registration)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/liff-register` | LIFF registration page |
| POST | `/api/liff/register` | Register user |
| GET | `/api/liff/status/{user_id}` | Check registration |

### LINE Webhook
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhook` | LINE webhook (รับข้อความ/รูปภาพ) |

---

## การ Deploy

### วิธีที่ 1: Railway.app (แนะนำ)

```bash
# 1. Push to GitHub
git add .
git commit -m "deploy: update code"
git push origin main

# 2. เชื่อมต่อ Railway กับ GitHub repo
# 3. ตั้งค่า Environment Variables ใน Railway Dashboard
# 4. Railway จะ auto deploy เมื่อ push
```

### วิธีที่ 2: Railway CLI

```bash
# ติดตั้ง Railway CLI
npm install -g @railway/cli

# Login
railway login

# Link project
railway link

# Deploy
railway up
```

### วิธีที่ 3: Docker

```bash
# Build image
docker build -t plant-disease-bot .

# Run container
docker run -p 8000:8000 --env-file .env plant-disease-bot
```

### วิธีที่ 4: Google Cloud Run

```bash
gcloud run deploy plant-disease-bot \
  --source . \
  --platform managed \
  --region asia-southeast1 \
  --allow-unauthenticated
```

---

## การใช้งาน

### User Flow

```
1. ผู้ใช้ Follow Bot
   └── รับ Welcome message + ลิงก์ลงทะเบียน

2. ลงทะเบียนผ่าน LIFF
   └── กรอกข้อมูล → บันทึกใน Supabase

3. ส่งรูปพืชที่มีปัญหา
   └── Bot ถามข้อมูลเพิ่มเติม (ระยะการเจริญเติบโต)

4. วิเคราะห์โรค
   └── Gemini Vision วิเคราะห์ → แสดงผลลัพธ์

5. แนะนำผลิตภัณฑ์
   └── Vector search → แสดง Carousel สินค้า

6. พยากรณ์อากาศ
   └── แชร์ location → ดูพยากรณ์ฝน 7 วัน

7. ถาม-ตอบ
   └── ถามคำถามเกี่ยวกับการเกษตร
```

### ตัวอย่างการใช้งาน

- **ส่งรูปพืช**: Bot จะวิเคราะห์และบอกโรค
- **พิมพ์ "ช่วยเหลือ"**: แสดงเมนูช่วยเหลือ
- **พิมพ์ "สินค้า"**: แสดงแคตตาล็อกสินค้า
- **แชร์ Location**: ดูพยากรณ์อากาศ
- **ถามคำถาม**: เช่น "ข้าวใบเหลืองเกิดจากอะไร"

---

## Services ที่ใช้

| Service | หน้าที่ | API Key |
|---------|--------|---------|
| **LINE Messaging API** | รับ-ส่งข้อความ | `LINE_CHANNEL_ACCESS_TOKEN` |
| **OpenAI** | Chat, Embeddings | `OPENAI_API_KEY` |
| **OpenRouter (Gemini)** | Vision Analysis | `OPENROUTER_API_KEY` |
| **Supabase** | Database, Vector | `SUPABASE_URL`, `SUPABASE_KEY` |
| **Agro-Risk API** | Weather Data | `AGRO_RISK_API_URL` |

---

## Performance

- **Response Time**: 3-5 วินาที
- **Concurrent Users**: 100+ (with scaling)
- **Uptime**: 99.9%
- **Cost**: $5-20/เดือน (ขึ้นอยู่กับการใช้งาน)

---

## License

Private - Ladda Agricultural Solutions

---

## Contact

- **GitHub**: [AtenVisarut/Chatbot-ladda](https://github.com/AtenVisarut/Chatbot-ladda)
