# LinArt Belege 🧾

**Receipts & invoices → bookkeeping for German small businesses (EÜR), read by a local vision LLM. No cloud, no subscription.**

Drop a photo or PDF of a receipt — the app reads date, vendor, invoice number, amounts, VAT lines and payment method,
suggests the EÜR category, archives the original with a SHA-256 hash and exports everything for your tax advisor.

## Features

- **Local vision LLM extraction** (LM Studio, tested with `qwen/qwen3-vl-30b`) with a strict JSON schema — no OCR service.
- **EÜR categories** (Anlage EÜR): goods, services, GWG / AfA thresholds by net price, software, telecom, travel, …
- **Kleinunternehmer (§ 19 UStG) aware** – income vs. expense detection based on *your* business name.
- **Tamper-evident archive** – originals stored unchanged, renamed by date/vendor/amount, SHA-256 hash and duplicate detection.
- **Inbox folder** – drop files into `Eingang/` (e.g. synced from your phone) and they are imported automatically.
- **Review UI** at `http://127.0.0.1:7880` – check/correct fields, re-extract, yearly summary per category.
- **Export** – XLSX and CSV with all fields (incl. archive path and hash) for your Steuerberater.
- Photos (JPG/PNG/HEIC) and PDFs.

## Install (Windows 10/11, Python 3.12)

```powershell
git clone https://github.com/Vikinges/linart-belege.git
cd linart-belege
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
set BELEGE_BUSINESS_NAME=Muster GmbH
set BELEGE_BUSINESS_DESC=baut Elektronik und Software
start_belege.bat               # opens http://127.0.0.1:7880
```

Start LM Studio with a **vision** model loaded (e.g. Qwen3-VL) and the local server enabled.

| Environment variable | Default |
|---|---|
| `BELEGE_BUSINESS_NAME` / `BELEGE_BUSINESS_DESC` | your company name / short description (used to tell income from expenses) |
| `BELEGE_LLM_URL` | `http://127.0.0.1:1234/v1` |
| `BELEGE_LLM_MODEL` | `qwen/qwen3-vl-30b` |
| `BELEGE_DATA` | `./data` (database + archive) |
| `BELEGE_EINGANG` | `./Eingang` (watched inbox) |

> **Disclaimer:** this is a helper tool, not tax advice and not a certified GoBD/DMS system. Always review the
> extracted values; your tax advisor has the final word.

## Part of LinArt Local AI

Small, private, offline-first tools that run entirely on your own PC — no cloud, no account, no telemetry:

| Project | What it does |
|---|---|
| [linart-diktat](https://github.com/Vikinges/linart-diktat) | Push-to-talk dictation + instant translation in any app |
| [linart-wissen](https://github.com/Vikinges/linart-wissen) | Ask questions about your own documents (local RAG with citations) |
| [linart-belege](https://github.com/Vikinges/linart-belege) | Receipts & invoices → bookkeeping (German EÜR) with a local vision LLM |
| [linart-3d-studio](https://github.com/Vikinges/linart-3d-studio) | Text/image → 3D model, plus a 3D-print check, on your own GPU |

Built and tested on an HP ZBook Ultra G1a (AMD Ryzen AI MAX+ PRO 395, Radeon 8060S, 128 GB unified memory) under Windows 11 with PyTorch ROCm, and designed to also run on NVIDIA (CUDA) or CPU.

## Author

**Vladimir Linartas** — founder of [LinArt Labs](https://linart.club), Bavaria, Germany. Self-hosted IoT, embedded systems and local AI.

## License

Apache License 2.0 — see [LICENSE](LICENSE). Third-party models are downloaded separately and keep their own licenses.
