import zipfile
import copy
from lxml import etree

SRC = "/Users/Zhuanz1/Downloads/行业研究智能体-全链路系统 4/文档11111_参赛版.docx"
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

with zipfile.ZipFile(SRC) as z:
    xml = z.read("word/document.xml")
root = etree.fromstring(xml)
body = root.find(f'{{{W}}}body')
paras = body.findall(f'{{{W}}}p')

def para_text(p):
    return ''.join(t.text or '' for t in p.findall(f'.//{{{W}}}t'))

tpl_toc2 = None
tpl_toc3 = None
for p in paras:
    txt = para_text(p)
    if '2.1 项目概述' in txt and tpl_toc2 is None:
        tpl_toc2 = p
    elif '1.1.1 行业研究工作' in txt and tpl_toc3 is None:
        tpl_toc3 = p
print("tpl_toc2 found:", tpl_toc2 is not None, "| tpl_toc3 found:", tpl_toc3 is not None)

fix_list = [
    ("1.6 组织管理与开发计划", "10", "toc2"),
    ("1.6.1 团队架构", "10", "toc3"),
    ("1.6.2 项目开发计划", "10", "toc3"),
    ("1.6.3 各部分负责人", "10", "toc3"),
    ("3.12 后端编排与接口实现", "21", "toc2"),
    ("3.13 依赖环境与运行方式", "22", "toc2"),
]

def replace_toc_para(target_p, title, page, tpl):
    new_p = copy.deepcopy(tpl)
    ts = new_p.findall(f'.//{{{W}}}t')
    if ts:
        ts[0].text = title
        if len(ts) > 1:
            ts[1].text = page
    target_p.addprevious(new_p)
    target_p.getparent().remove(target_p)

fixed = 0
for title, page, kind in fix_list:
    for p in paras:
        txt = para_text(p)
        if title in txt:
            pPr = p.find(f'{{{W}}}pPr')
            if pPr is None:
                continue
            pstyle = pPr.find(f'{{{W}}}pStyle')
            if pstyle is None:
                continue
            tpl = tpl_toc2 if kind == "toc2" else tpl_toc3
            replace_toc_para(p, title, page, tpl)
            fixed += 1
            break

print("修复目录项数量:", fixed)

xml_out = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
with zipfile.ZipFile(SRC) as zin:
    items = {n: zin.read(n) for n in zin.namelist()}
items['word/document.xml'] = xml_out

tmp = SRC + '.tmp'
with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
    for n, data in items.items():
        zout.writestr(n, data)
import os
os.replace(tmp, SRC)
print("已保存修复后的文件")
