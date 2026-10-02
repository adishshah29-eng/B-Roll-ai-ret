# Environment (dev laptop, checked 2026-10-02)

| Item | Value |
|---|---|
| OS | Windows 11 |
| Python | 3.11.0 |
| CPU | 8 logical cores |
| GPU | **None** (CPU-only) |
| RAM | 6.4 GB total, **~0.8 GB free at check time**, so close apps before running |
| ffmpeg | **Not installed** → use OpenCV (`cv2` 5.0.0 installed) |
| Installed | torch 2.14, sentence-transformers 5.2.2, transformers 5.0, fastapi 0.122, uvicorn 0.38, numpy 2.4, scikit-learn 1.8, Pillow 12.1 |
| Models needed (not cached yet) | `sentence-transformers/clip-ViT-B-32` (~600 MB), `sentence-transformers/clip-ViT-B-32-multilingual-v1` (~540 MB) |

## Setup
```bash
python -c "from sentence_transformers import SentenceTransformer as S; S('clip-ViT-B-32'); S('clip-ViT-B-32-multilingual-v1')"
python -m app.indexer footage
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
LAN: find the IP with `ipconfig`, then open `http://<ip>:8000` on other laptops. Allow Python through Windows Firewall when prompted.

## Gotchas
- Browser preview needs **H.264 MP4**. HEVC/ProRes won't play in Chrome on Windows.
- Paths with spaces: always quote them; in the XML export use URL-encoded `file://localhost/C:/...`.
- First model load takes ~20–40 s on CPU; load once at startup.
