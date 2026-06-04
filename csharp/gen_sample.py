# -*- coding: utf-8 -*-
import fitz

d = fitz.open()
p = d.new_page(width=420, height=260)

def line(y, text, font, fontfile):
    p.insert_text((40, y), text, fontsize=20, fontname=font, fontfile=fontfile)

line(60,  "粗体雅黑标题",        "yh-bd", "C:/Windows/Fonts/msyhbd.ttc")   # 粗体雅黑标题
line(110, "仿宋常规正文示例", "fs",   "C:/Windows/Fonts/simfang.ttf")  # 仿宋常规正文示例
line(160, "BoldEnglish", "ar-bd", "C:/Windows/Fonts/arialbd.ttf")
line(210, "Regular text", "ar",   "C:/Windows/Fonts/arial.ttf")

out = "C:/Users/lzh/git/pdf_editor/csharp/sample_cjk.pdf"
d.save(out)
print("wrote", out)
