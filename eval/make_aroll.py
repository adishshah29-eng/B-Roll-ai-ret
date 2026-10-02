"""Make a test A-roll with real speech: Windows text-to-speech narration over a looping background clip.
    python -m eval.make_aroll      -> footage/test_aroll/monsoon_aroll.mp4  (a stand-in for a creator's talking-head video)"""
import subprocess
import tempfile
from pathlib import Path

from app.editor import ffmpeg

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "test_aroll"
BG = ROOT / "footage" / "pixabay_273921.mp4"      # person at a laptop: stands in for the presenter
TEXT = ("Hi everyone, welcome back to the channel. "
        "Today I want to talk about the monsoon in Mumbai. "
        "Heavy rain lashed the city this week, bringing traffic to a halt. "
        "Commuters waited for hours at flooded local train stations. "
        "Street vendors covered their stalls with plastic sheets. "
        "By evening, the roads had turned into rivers. "
        "I think we need better drainage, and I want to hear what you think. "
        "Let me know in the comments, and subscribe for more.")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    wav = Path(tempfile.gettempdir()) / "epoch_narration.wav"
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.Rate = 0; $s.SetOutputToWaveFile('{wav}'); $s.Speak(@'\n{TEXT}\n'@); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    dst = OUT / "monsoon_aroll.mp4"
    ffmpeg.run(["-stream_loop", "-1", "-i", str(BG), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-shortest",
                "-vf", "scale=-2:720", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(dst)])
    print(dst, ffmpeg.probe(dst))


if __name__ == "__main__":
    main()
