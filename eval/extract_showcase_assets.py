import json
import os
import shutil
import cv2

os.makedirs('app/static/media/shots', exist_ok=True)

proj_path = 'data/projects/20261003-045037-34b289'
with open(os.path.join(proj_path, 'project.json'), 'r', encoding='utf-8') as f:
    proj = json.load(f)

print(f"Project: {proj['name']} (ID: {proj['id']})")
print(f"Slots: {len(proj.get('slots', []))}")

# 1. Copy shot thumbnails
for i, s in enumerate(proj.get('slots', [])):
    shot = s.get('shot')
    if shot:
        shot_id = shot.get('id')
        print(f"Slot {i}: anchor '{s.get('anchor')}' -> Shot ID {shot_id}, title: {shot.get('title')}")
        src_thumb = os.path.join('data/thumbs', f"{shot_id}.jpg")
        if os.path.exists(src_thumb):
            dst = os.path.join('app/static/media/shots', f"shot_{shot_id}.jpg")
            shutil.copy(src_thumb, dst)
            print(f"  Copied thumb {src_thumb} -> {dst}")
        
    for j, alt in enumerate(s.get('alts', [])[:3]):
        alt_id = alt.get('id')
        alt_thumb = os.path.join('data/thumbs', f"{alt_id}.jpg")
        if os.path.exists(alt_thumb):
            dst = os.path.join('app/static/media/shots', f"shot_{alt_id}.jpg")
            shutil.copy(alt_thumb, dst)

# 2. Copy representative video frames from final.mp4 / source.mp4
def extract_frame_at_sec(video_file, sec, out_name):
    if not os.path.exists(video_file):
        return
    cap = cv2.VideoCapture(video_file)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(sec * fps))
    ret, frame = cap.read()
    if ret:
        out_path = os.path.join('app/static/media/shots', out_name)
        cv2.imwrite(out_path, frame)
        print(f"Extracted {out_name} from {video_file} at {sec}s")
    cap.release()

extract_frame_at_sec(os.path.join(proj_path, 'source.mp4'), 2.0, 'travel_source_talkinghead.jpg')
extract_frame_at_sec(os.path.join(proj_path, 'final.mp4'), 5.0, 'travel_broll_cut_1.jpg')
extract_frame_at_sec(os.path.join(proj_path, 'final.mp4'), 10.0, 'travel_broll_cut_2.jpg')

# 3. Export clean JSON summary of travel-v3c for the landing page showcase
showcase_data = {
    "project_id": proj['id'],
    "name": proj['name'],
    "slots_count": len(proj.get('slots', [])),
    "slots": []
}

for s in proj.get('slots', []):
    sh = s.get('shot')
    showcase_data["slots"].append({
        "start": s.get('start'),
        "end": s.get('end'),
        "text": s.get('text'),
        "anchor": s.get('anchor'),
        "query": s.get('query'),
        "reason": s.get('reason'),
        "shot": {
            "id": sh.get('id') if sh else None,
            "title": sh.get('title') if sh else None,
            "author": sh.get('author') if sh else None,
            "source": sh.get('source') if sh else None,
            "licence": sh.get('licence') if sh else None,
            "verdict": sh.get('verdict') if sh else None,
            "thumb": f"/static/media/shots/shot_{sh.get('id')}.jpg" if sh and os.path.exists(os.path.join('app/static/media/shots', f"shot_{sh.get('id')}.jpg")) else (sh.get('thumb') if sh else None)
        } if sh else None
    })

with open('app/static/media/shots/showcase.json', 'w', encoding='utf-8') as f:
    json.dump(showcase_data, f, indent=2)

print("Showcase assets extracted successfully!")
