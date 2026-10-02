"""Read the A-roll: speech (faster-whisper) + where the speaker's face dominates (OpenCV Haar)."""
import gc

import cv2
import numpy as np

WHISPER_SIZE = "small"
FACE_STEP_S = 0.5
FACE_BIG = 0.22          # face width / frame width above which the speaker "owns" the frame


def transcribe(path, progress=None) -> dict:
    """-> {"language", "segments": [{"start","end","text","words":[{"w","s","e"}]}]}. Model freed after use (RAM)."""
    from faster_whisper import WhisperModel
    model = WhisperModel(WHISPER_SIZE, device="cpu", compute_type="int8")
    try:
        segs, info = model.transcribe(str(path), word_timestamps=True, vad_filter=True, beam_size=1)
        out = []
        total = max(info.duration or 1.0, 1.0)
        for s in segs:
            words = [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)} for w in (s.words or [])]
            out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(), "words": words})
            if progress:
                progress(min(0.99, s.end / total))
        return {"language": info.language, "duration": info.duration, "segments": out}
    finally:
        del model
        gc.collect()


def face_map(path) -> list:
    """[(t, face_share)] every FACE_STEP_S: largest frontal face width as a share of frame width (0 = no face)."""
    if not hasattr(cv2, "CascadeClassifier"):        # OpenCV 5 moved Haar cascades out: face map is optional
        return []
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(fps * FACE_STEP_S)))
    out, i = [], 0
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            if i % step == 0:
                ok, fr = cap.retrieve()
                if not ok:
                    break
                h, w = fr.shape[:2]
                s = 320 / w
                g = cv2.cvtColor(cv2.resize(fr, (320, int(h * s))), cv2.COLOR_BGR2GRAY)
                faces = casc.detectMultiScale(g, 1.15, 5, minSize=(24, 24))
                share = max((fw for _, _, fw, _ in faces), default=0) / 320.0
                out.append((round(i / fps, 2), round(float(share), 3)))
            i += 1
    finally:
        cap.release()
    return out


def face_share(fmap, a, b) -> float:
    vals = [v for t, v in fmap if a <= t <= b]
    return float(np.mean(vals)) if vals else 0.0
