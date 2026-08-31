import os
import hashlib
import requests
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, create_engine, select

app = FastAPI(title="Adslab Captcha Solver API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

class BatchItem(BaseModel):
    url: str
    answers: List[int]

class BatchSaveRequest(BaseModel):
    items: List[BatchItem]

class MultiCheckRequest(BaseModel):
    urls: List[str]

def get_image_md5(url: str) -> str:
    """Download image stream and compute MD5 hash based on image bytes"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail=f"Gagal download gambar: {url} (Status {resp.status_code})")
    return hashlib.md5(resp.content).hexdigest()

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/gui")

@app.post("/api/save")
def save_answer(data: SaveCaptchaRequest):
    """Simpan satu jawaban captcha"""
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

@app.post("/api/save-batch")
def save_batch_answers(data: BatchSaveRequest):
    """Simpan banyak jawaban captcha sekaligus (Multi URL)"""
    results = []
    with Session(engine) as session:
        for item in data.items:
            try:
                img_hash = get_image_md5(item.url)
                answer_str = ",".join(map(str, item.answers))
                record = session.exec(select(CaptchaRecord).where(CaptchaRecord.img_hash == img_hash)).first()
                if record:
                    record.answers = answer_str
                    record.captcha_url = item.url
                else:
                    record = CaptchaRecord(img_hash=img_hash, captcha_url=item.url, answers=answer_str)
                    session.add(record)
                results.append({"url": item.url, "hash": img_hash, "answers": item.answers, "status": "success"})
            except Exception as e:
                results.append({"url": item.url, "status": "error", "message": str(e)})
        session.commit()
    return {"status": "success", "count": len(results), "results": results}

@app.get("/api/solve")
def get_answer(url: str = Query(..., description="URL Captcha GIF")):
    """Cek satu URL captcha"""
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

@app.post("/api/solve-multi")
def solve_multi(data: MultiCheckRequest):
    """Cek banyak URL captcha sekaligus (misal cek captchaUrl + traps)"""
    results: Dict[str, Any] = {}
    with Session(engine) as session:
        for url in data.urls:
            try:
                img_hash = get_image_md5(url)
                record = session.exec(select(CaptchaRecord).where(CaptchaRecord.img_hash == img_hash)).first()
                if record:
                    results[url] = {
                        "solved": True,
                        "hash": img_hash,
                        "answers": [int(x) for x in record.answers.split(",") if x.strip()]
                    }
                else:
                    results[url] = {
                        "solved": False,
                        "hash": img_hash,
                        "answers": []
                    }
            except Exception as e:
                results[url] = {"solved": False, "error": str(e)}
    return results

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
    <title>Adslab Captcha Solver Multi-Manager</title>
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
        .wrapper { width: 100%; max-width: 900px; }
        h1 { font-size: 1.6rem; text-align: center; margin-bottom: 20px; color: var(--accent-color); }
        .card { background: var(--card-bg); border-radius: 12px; padding: 20px; border: 1px solid var(--border-color); margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); }
        
        textarea { width: 100%; height: 100px; padding: 12px; border-radius: 8px; border: 1px solid var(--border-color); background: #0f172a; color: white; font-size: 13px; font-family: monospace; resize: vertical; margin-bottom: 12px; outline: none; }
        textarea:focus { border-color: var(--accent-color); }
        
        .btn-load { width: 100%; padding: 10px; background: var(--accent-color); color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; font-size: 14px; margin-bottom: 15px; }
        .btn-load:hover { background: var(--accent-hover); }

        .items-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .captcha-card { background: #0f172a; border: 1px solid var(--border-color); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; align-items: center; position: relative; }
        .captcha-card img { width: 100%; height: 130px; object-fit: contain; background: #000; border-radius: 6px; margin-bottom: 10px; }
        
        .seq-tag { font-size: 13px; font-weight: bold; color: #facc15; margin-bottom: 8px; min-height: 18px; }
        .grid-box { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; width: 100%; margin-bottom: 8px; }
        .grid-btn { padding: 10px 0; font-size: 16px; font-weight: bold; background: #334155; color: white; border: none; border-radius: 6px; cursor: pointer; }
        .grid-btn:hover { background: var(--accent-color); }
        .grid-btn:active { transform: scale(0.95); }

        .card-actions { display: flex; gap: 6px; width: 100%; }
        .card-actions button { flex: 1; padding: 6px; font-size: 12px; font-weight: bold; border-radius: 4px; border: none; cursor: pointer; }
        .btn-single-reset { background: #64748b; color: white; }
        .btn-single-save { background: var(--success-color); color: white; }

        .batch-actions { display: flex; gap: 10px; margin-top: 10px; }
        .batch-save-all { flex: 2; padding: 12px; background: var(--success-color); color: white; font-weight: bold; font-size: 15px; border: none; border-radius: 8px; cursor: pointer; }
        .batch-save-all:hover { background: #16a34a; }

        .db-list { max-height: 400px; overflow-y: auto; }
        .db-item { display: flex; justify-content: space-between; align-items: center; padding: 10px; border-bottom: 1px solid var(--border-color); font-size: 13px; }
        .badge { background: #1e3a8a; color: #93c5fd; padding: 3px 8px; border-radius: 4px; font-weight: bold; }
        .btn-del { background: var(--danger-color); color: white; border: none; padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 12px; }
    </style>
</head>
<body>
<div class="wrapper">
    <h1>Adslab Multi-Captcha Solver</h1>
    
    <div class="card">
        <label style="font-size: 13px; color: #94a3b8; margin-bottom: 6px; display: block;">
            Paste Beberapa URL Captcha GIF (Pisahkan dengan baris baru / Enter):
        </label>
        <textarea id="multiUrls" placeholder="https://c2.adslab.me/6grid_strict_1.gif&#10;https://c2.adslab.me/6grid_strict_2.gif"></textarea>
        <button class="btn-load" onclick="loadBatchUrls()">Muat Semua Gambar GIF</button>

        <div id="captchaContainer" class="items-grid"></div>

        <div id="batchSaveContainer" style="display: none;" class="batch-actions">
            <button class="batch-save-all" onclick="saveAllAnswers()">Simpan Semua Jawaban yang Sudah Dipilih</button>
        </div>
    </div>

    <div class="card">
        <h3 style="margin-bottom: 10px; font-size: 1rem; color: #94a3b8;">Database Jawaban Tersimpan (<span id="count">0</span>)</h3>
        <div id="savedList" class="db-list">
            <div style="color: #64748b; font-size: 13px; text-align: center; padding: 10px;">Memuat data...</div>
        </div>
    </div>
</div>

<script>
    let activeCards = [];

    function loadBatchUrls() {
        const text = document.getElementById('multiUrls').value.trim();
        if (!text) {
            alert("Masukkan URL gif terlebih dahulu!");
            return;
        }

        const lines = text.split(/\\r?\\n/).map(l => l.trim()).filter(l => l.length > 0);
        const container = document.getElementById('captchaContainer');
        container.innerHTML = '';
        activeCards = [];

        lines.forEach((url, idx) => {
            activeCards.push({ id: idx, url: url, answers: [] });
            
            const card = document.createElement('div');
            card.className = 'captcha-card';
            card.id = `card-${idx}`;
            card.innerHTML = `
                <img src="${url}" onerror="this.src='https://placehold.co/300x150/1e293b/ef4444?text=Gagal+Muat+Gambar'">
                <div class="seq-tag" id="seq-${idx}">Belum dipilih</div>
                <div class="grid-box">
                    <button class="grid-btn" onclick="clickGrid(${idx}, 1)">1</button>
                    <button class="grid-btn" onclick="clickGrid(${idx}, 2)">2</button>
                    <button class="grid-btn" onclick="clickGrid(${idx}, 3)">3</button>
                    <button class="grid-btn" onclick="clickGrid(${idx}, 4)">4</button>
                    <button class="grid-btn" onclick="clickGrid(${idx}, 5)">5</button>
                    <button class="grid-btn" onclick="clickGrid(${idx}, 6)">6</button>
                </div>
                <div class="card-actions">
                    <button class="btn-single-reset" onclick="resetSingle(${idx})">Reset</button>
                    <button class="btn-single-save" onclick="saveSingle(${idx})">Simpan</button>
                </div>
            `;
            container.appendChild(card);
        });

        document.getElementById('batchSaveContainer').style.display = lines.length > 0 ? 'flex' : 'none';
    }

    function clickGrid(cardId, num) {
        const cardData = activeCards.find(c => c.id === cardId);
        if (cardData) {
            cardData.answers.push(num);
            document.getElementById(`seq-${cardId}`).innerText = cardData.answers.join(" -> ");
        }
    }

    function resetSingle(cardId) {
        const cardData = activeCards.find(c => c.id === cardId);
        if (cardData) {
            cardData.answers = [];
            document.getElementById(`seq-${cardId}`).innerText = "Belum dipilih";
        }
    }

    async function saveSingle(cardId) {
        const cardData = activeCards.find(c => c.id === cardId);
        if (!cardData || cardData.answers.length === 0) {
            alert("Pilih urutan angka grid terlebih dahulu!");
            return;
        }

        try {
            const res = await fetch('/api/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: cardData.url, answers: cardData.answers })
            });
            const data = await res.json();
            if (res.ok) {
                alert("✅ Berhasil disimpan!");
                loadSavedList();
            } else {
                alert("❌ Gagal: " + (data.detail || "Error"));
            }
        } catch (e) {
            alert("❌ Error: " + e.message);
        }
    }

    async function saveAllAnswers() {
        const readyItems = activeCards.filter(c => c.answers.length > 0);
        if (readyItems.length === 0) {
            alert("Belum ada captcha yang dipilih urutannya!");
            return;
        }

        try {
            const res = await fetch('/api/save-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    items: readyItems.map(item => ({ url: item.url, answers: item.answers }))
                })
            });
            const data = await res.json();
            if (res.ok) {
                alert(`✅ Berhasil menyimpan ${data.count} captcha sekaligus!`);
                loadSavedList();
            } else {
                alert("❌ Gagal batch save: " + (data.detail || "Error"));
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
