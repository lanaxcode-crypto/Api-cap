import os
import hashlib
import requests
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine, select

app = FastAPI(title="Adslab Captcha Solver API", version="1.0.0")

# Enable CORS for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///captcha.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})

class CaptchaRecord(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    img_hash: str = Field(index=True, unique=True)
    captcha_url: Optional[str] = None
    answers: str  # Format: "5,3,4"

SQLModel.metadata.create_all(engine)

class SaveCaptchaRequest(BaseModel):
    url: str
    answers: List[int]

def get_image_md5(url: str) -> str:
    """Download image stream and compute MD5 hash based on image bytes"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Gagal download gambar (Status {resp.status_code})")
    return hashlib.md5(resp.content).hexdigest()

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/gui")

@app.post("/api/save")
def save_answer(data: SaveCaptchaRequest):
    """Simpan atau perbarui jawaban captcha berdasarkan URL gambar"""
    if not data.answers:
        raise HTTPException(status_code=400, detail="Jawaban tidak boleh kosong")
    
    img_hash = get_image_md5(data.url)
    answer_str = ",".join(map(str, data.answers))

    with Session(engine) as session:
        record = session.exec(select(CaptchaRecord).where(CaptchaRecord.img_hash == img_hash)).first()
        if record:
            record.answers = answer_str
            record.captcha_url = data.url
        else:
            record = CaptchaRecord(img_hash=img_hash, captcha_url=data.url, answers=answer_str)
            session.add(record)
        session.commit()

    return {
        "status": "success",
        "hash": img_hash,
        "answers": data.answers,
        "url": data.url,
        "message": "Jawaban berhasil disimpan!"
    }

@app.get("/api/solve")
def get_answer(url: str = Query(..., description="URL Captcha GIF")):
    """Cek apakah captcha sudah ada jawabannya di database"""
    try:
        img_hash = get_image_md5(url)
    except HTTPException as e:
        raise e
    except Exception as err:
        raise HTTPException(status_code=400, detail=str(err))

    with Session(engine) as session:
        record = session.exec(select(CaptchaRecord).where(CaptchaRecord.img_hash == img_hash)).first()
        if not record:
            return {
                "solved": False,
                "hash": img_hash,
                "answers": [],
                "message": "Captcha baru! Belum ada jawaban di database."
            }

        answers = [int(x) for x in record.answers.split(",") if x.strip()]
        return {
            "solved": True,
            "hash": img_hash,
            "answers": answers,
            "message": "Jawaban ditemukan"
        }

@app.get("/api/list")
def list_records():
    """Lihat semua data captcha yang tersimpan"""
    with Session(engine) as session:
        records = session.exec(select(CaptchaRecord)).all()
        return [
            {
                "id": r.id,
                "hash": r.img_hash,
                "url": r.captcha_url,
                "answers": [int(x) for x in r.answers.split(",") if x.strip()]
            }
            for r in records
        ]

@app.delete("/api/delete/{img_hash}")
def delete_record(img_hash: str):
    """Hapus data captcha berdasarkan hash"""
    with Session(engine) as session:
        record = session.exec(select(CaptchaRecord).where(CaptchaRecord.img_hash == img_hash)).first()
        if not record:
            raise HTTPException(status_code=404, detail="Data tidak ditemukan")
        session.delete(record)
        session.commit()
    return {"status": "success", "message": f"Data {img_hash} berhasil dihapus"}

@app.get("/gui", response_class=HTMLResponse)
def gui_page():
    return """<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Adslab Captcha Solver Manager</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --text-color: #f8fafc;
            --accent-color: #3b82f6;
            --accent-hover: #2563eb;
            --danger-color: #ef4444;
            --success-color: #22c55e;
            --border-color: #334155;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { background: var(--bg-color); color: var(--text-color); padding: 20px; display: flex; justify-content: center; }
        .wrapper { width: 100%; max-width: 600px; }
        h1 { font-size: 1.5rem; text-align: center; margin-bottom: 20px; color: var(--accent-color); }
        .card { background: var(--card-bg); border-radius: 12px; padding: 20px; border: 1px solid var(--border-color); margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); }
        input[type="text"] { width: 100%; padding: 12px 14px; border-radius: 8px; border: 1px solid var(--border-color); background: #0f172a; color: white; font-size: 14px; margin-bottom: 15px; outline: none; }
        input[type="text"]:focus { border-color: var(--accent-color); }
        .preview-container { text-align: center; margin-bottom: 15px; min-height: 160px; background: #0f172a; border-radius: 8px; display: flex; align-items: center; justify-content: center; border: 1px dashed var(--border-color); overflow: hidden; }
        .preview-img { max-width: 100%; max-height: 220px; border-radius: 6px; display: none; }
        .empty-placeholder { color: #64748b; font-size: 13px; }
        .sequence-display { background: #0f172a; padding: 12px; border-radius: 8px; text-align: center; font-size: 16px; margin-bottom: 15px; border: 1px solid var(--border-color); }
        .sequence-val { color: #facc15; font-weight: bold; }
        .grid-box { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 15px; }
        .btn-grid { padding: 18px 0; font-size: 20px; font-weight: bold; background: #334155; color: white; border: none; border-radius: 8px; cursor: pointer; transition: 0.15s ease; }
        .btn-grid:hover { background: var(--accent-color); }
        .btn-grid:active { transform: scale(0.95); }
        .actions { display: flex; gap: 10px; }
        button.btn { flex: 1; padding: 12px; font-size: 15px; font-weight: bold; border: none; border-radius: 8px; cursor: pointer; transition: 0.15s ease; }
        .btn-save { background: var(--success-color); color: white; }
        .btn-save:hover { background: #16a34a; }
        .btn-reset { background: #64748b; color: white; }
        .btn-reset:hover { background: #475569; }
        .db-list { margin-top: 15px; }
        .db-item { display: flex; justify-content: space-between; align-items: center; padding: 10px; border-bottom: 1px solid var(--border-color); font-size: 13px; }
        .db-item:last-child { border-bottom: none; }
        .badge { background: #1e3a8a; color: #93c5fd; padding: 3px 8px; border-radius: 4px; font-weight: bold; }
        .btn-del { background: var(--danger-color); color: white; border: none; padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 12px; }
    </style>
</head>
<body>
<div class="wrapper">
    <h1>Adslab Captcha Solver</h1>
    
    <div class="card">
        <input type="text" id="captchaUrl" placeholder="Paste URL Captcha .gif disini..." oninput="onUrlChange()">
        
        <div class="preview-container">
            <span id="placeholderText" class="empty-placeholder">Preview Gambar akan muncul disini</span>
            <img id="imgPreview" class="preview-img" src="" alt="Preview">
        </div>

        <div class="sequence-display">
            Urutan Jawaban: <span id="seqText" class="sequence-val">Belum dipilih</span>
        </div>

        <!-- 6 Grid Box -->
        <div class="grid-box">
            <button type="button" class="btn-grid" onclick="selectGrid(1)">1</button>
            <button type="button" class="btn-grid" onclick="selectGrid(2)">2</button>
            <button type="button" class="btn-grid" onclick="selectGrid(3)">3</button>
            <button type="button" class="btn-grid" onclick="selectGrid(4)">4</button>
            <button type="button" class="btn-grid" onclick="selectGrid(5)">5</button>
            <button type="button" class="btn-grid" onclick="selectGrid(6)">6</button>
        </div>

        <div class="actions">
            <button type="button" class="btn btn-reset" onclick="resetSequence()">Reset</button>
            <button type="button" class="btn btn-save" onclick="submitAnswer()">Simpan Jawaban</button>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 10px; font-size: 1rem; color: #94a3b8;">Daftar Jawaban Tersimpan (<span id="count">0</span>)</h3>
        <div id="savedList" class="db-list">
            <div style="color: #64748b; font-size: 13px; text-align: center; padding: 10px;">Memuat data...</div>
        </div>
    </div>
</div>

<script>
    let currentSequence = [];

    function onUrlChange() {
        const url = document.getElementById('captchaUrl').value.trim();
        const img = document.getElementById('imgPreview');
        const placeholder = document.getElementById('placeholderText');
        if (url) {
            img.src = url;
            img.style.display = 'block';
            placeholder.style.display = 'none';
        } else {
            img.src = '';
            img.style.display = 'none';
            placeholder.style.display = 'inline';
        }
        resetSequence();
    }

    function selectGrid(num) {
        currentSequence.push(num);
        document.getElementById('seqText').innerText = currentSequence.join(" -> ");
    }

    function resetSequence() {
        currentSequence = [];
        document.getElementById('seqText').innerText = "Belum dipilih";
    }

    async function submitAnswer() {
        const url = document.getElementById('captchaUrl').value.trim();
        if (!url) {
            alert("Masukkan URL Captcha terlebih dahulu!");
            return;
        }
        if (currentSequence.length === 0) {
            alert("Pilih urutan grid (misal klik kotak 5, 3, 4)!");
            return;
        }

        try {
            const res = await fetch('/api/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url, answers: currentSequence })
            });
            const data = await res.json();
            if (res.ok) {
                alert("✅ Berhasil disimpan! Hash: " + data.hash);
                document.getElementById('captchaUrl').value = '';
                onUrlChange();
                loadSavedList();
            } else {
                alert("❌ Gagal: " + (data.detail || "Terjadi kesalahan"));
            }
        } catch (e) {
            alert("❌ Error: " + e.message);
        }
    }

    async function loadSavedList() {
        try {
            const res = await fetch('/api/list');
            const data = await res.json();
            const container = document.getElementById('savedList');
            document.getElementById('count').innerText = data.length;

            if (data.length === 0) {
                container.innerHTML = '<div style="color: #64748b; font-size: 13px; text-align: center; padding: 10px;">Belum ada data.</div>';
                return;
            }

            container.innerHTML = data.map(item => `
                <div class="db-item">
                    <div>
                        <div style="font-family: monospace; font-size: 11px; color: #94a3b8;">${item.hash}</div>
                        <div style="margin-top: 4px;"><span class="badge">Jawaban: ${item.answers.join(" -> ")}</span></div>
                    </div>
                    <button class="btn-del" onclick="deleteItem('${item.hash}')">Hapus</button>
                </div>
            `).join('');
        } catch (e) {
            console.error(e);
        }
    }

    async function deleteItem(hash) {
        if (!confirm("Yakin ingin menghapus?")) return;
        await fetch('/api/delete/' + hash, { method: 'DELETE' });
        loadSavedList();
    }

    loadSavedList();
</script>
</body>
</html>
