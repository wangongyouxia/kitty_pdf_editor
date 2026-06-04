# -*- coding: utf-8 -*-
"""Generate test-fixture PDFs with REAL embedded subset fonts (so the
subset-append / family-match cases are exercised against the same kind
of document the user edits)."""
import os
import fitz

OUT = os.path.join(os.path.dirname(__file__), "testfixtures")
os.makedirs(OUT, exist_ok=True)

WIN = "C:/Windows/Fonts/"

# ---- cjk_subset.pdf: several CJK runs, each in a different font ----
d = fitz.open()
p = d.new_page(width=480, height=400)
rows = [
    (60,  "粗体标题示例",   "yhbd", WIN + "msyhbd.ttc"),   # bold YaHei
    (110, "宋体正文内容",   "sun",  WIN + "simsun.ttc"),    # SimSun
    (160, "仿宋公文样式",   "fang", WIN + "simfang.ttf"),   # FangSong
    (210, "黑体小标题",     "hei",  WIN + "simhei.ttf"),    # SimHei
    (260, "楷体注释文字",   "kai",  WIN + "simkai.ttf"),    # KaiTi
    (310, "混合Abc123文字", "sun2", WIN + "simsun.ttc"),    # CJK + latin + digits
]
for y, text, alias, fontfile in rows:
    if os.path.isfile(fontfile):
        p.insert_text((50, y), text, fontsize=18, fontname=alias, fontfile=fontfile)
    else:
        p.insert_text((50, y), text, fontsize=18)
try:
    d.subset_fonts()   # make real SUBSET fonts (and shrink the file)
except Exception as e:
    print("subset_fonts failed:", e)
d.save(os.path.join(OUT, "cjk_subset.pdf"), garbage=4, deflate=True)
d.close()
print("wrote cjk_subset.pdf")

# ---- latin_subset.pdf: subset Latin fonts (Times Bold, Arial) ----
d = fitz.open()
p = d.new_page(width=480, height=240)
lat = [
    (60,  "Anti-productive", "tnrb", WIN + "timesbd.ttf"),   # Times New Roman Bold
    (110, "Workplace",       "ar",   WIN + "arial.ttf"),      # Arial
    (160, "Quietness",       "tnr",  WIN + "times.ttf"),      # Times New Roman
]
for y, text, alias, fontfile in lat:
    if os.path.isfile(fontfile):
        p.insert_text((50, y), text, fontsize=20, fontname=alias, fontfile=fontfile)
    else:
        p.insert_text((50, y), text, fontsize=20)
try:
    d.subset_fonts()
except Exception as e:
    print("subset_fonts failed:", e)
d.save(os.path.join(OUT, "latin_subset.pdf"), garbage=4, deflate=True)
d.close()
print("wrote latin_subset.pdf")

# ---- multi.pdf: 4 pages with distinct identifiable text ----
d = fitz.open()
for i in range(4):
    pg = d.new_page(width=400, height=300)
    pg.insert_text((60, 80), f"PAGE-{chr(ord('A') + i)}", fontsize=24)
    pg.insert_text((60, 140), f"page index {i}", fontsize=12)
d.save(os.path.join(OUT, "multi.pdf"))
d.close()
print("wrote multi.pdf")
