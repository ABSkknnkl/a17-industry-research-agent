from pathlib import Path

p = Path('/Users/Zhuanz1/PycharmProjects/同花顺/eval/scorers/stages.py')
s = p.read_text(encoding='utf-8')

old = '''    chapter_chart_ids = {
        item.get("chart_id")
        for item in chapters.get("chart_requests", []) or []
    }
'''

new = '''    # A3→A4 消费信号有两条：mock/规划路径的 chart_requests（planned）与
    # live 路径的章节/小节 chart_ids 引用（ready 图表由章节正文消费）。
    chapter_chart_ids = {
        item.get("chart_id")
        for item in chapters.get("chart_requests", []) or []
    }
    for chapter in chapters.get("chapters", []) or []:
        chapter_chart_ids.update(chapter.get("chart_ids", []) or [])
        for section in chapter.get("sections", []) or []:
            chapter_chart_ids.update(section.get("chart_ids", []) or [])
'''

assert old in s, 'scorer anchor not found'
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('scorers/stages.py patched')
