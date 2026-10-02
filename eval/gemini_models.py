"""Scrub any leaked API key from saved projects, then ask Google which models the key can use (the key is never printed).
    python -m eval.gemini_models"""
import glob
import re

import requests
from dotenv import dotenv_values

KEY_IN_URL = re.compile(r"key=[^&\s\"'\\]+")


def main():
    n = 0
    for f in glob.glob("data/projects/*/project.json"):
        s = open(f, encoding="utf-8").read()
        s2 = KEY_IN_URL.sub("key=REDACTED", s)
        if s2 != s:
            open(f, "w", encoding="utf-8").write(s2)
            n += 1
    print("scrubbed project files:", n)
    key = dotenv_values(".env").get("GEMINI_API_KEY")
    red = lambda t: t.replace(key, "<KEY>") if key else t
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         params={"key": key, "pageSize": 200}, timeout=30)
        print("ListModels HTTP", r.status_code)
        if r.ok:
            ms = [m["name"].split("/")[-1] for m in r.json().get("models", [])
                  if "generateContent" in m.get("supportedGenerationMethods", [])]
            print(len(ms), "models support generateContent:", [m for m in ms if "gemini" in m][:30])
        else:
            print("response:", red(r.text[:500]))
    except Exception as e:
        print("ERR", red(str(e)))


if __name__ == "__main__":
    main()
