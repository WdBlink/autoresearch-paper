#!/usr/bin/env python3
"""Index actual source-reading records; never invent readings or their content."""
import json
from pathlib import Path
import sys


def main(root):
    catalog=json.loads((root/'venue/sample-catalog.json').read_text())
    lines=['# 8 篇真实范文：逐图逐表阅读索引', '',
        '本次记录包括 53 图、54 表；475 个分面或表格语义分块另行登记。自动计数与实际视觉理解分别保存。',
        '阅读由主 Agent 和同模型家族的独立上下文原生 Agent 执行；不代表人类或跨模型审阅。', '',
        'S01 T13 的初读加粗误判已由独立 PDF 字体检查纠正；旧记录保留在 revisions/。', '']
    figures=tables=panels=0
    for sample in catalog:
        key=sample['id'];record=root/f'venue/analysis/{key}.json'
        reading=json.loads(record.read_text())
        nf=len(reading['figures']);nt=len(reading['tables'])
        np=sum(len(item.get('panels',[])) for item in reading['figures']+reading['tables'])
        figures+=nf;tables+=nt;panels+=np
        lines += [f'## {key} · {sample["title"]}', '',
            f'{sample["publication_date"]} · {nf} 图 / {nt} 表 / {np} 分面或语义分块', '',
            f'[出版商原文]({sample["url"]}) · [逐项阅读]({root}/venue/analysis/{key}.md) · [结构化记录]({record}) · [原 PDF]({root}/venue/samples/{key}/article.pdf)', '']
    assert (len(catalog),figures,tables,panels)==(8,53,54,475)
    (root/'venue/analysis/INDEX.md').write_text('\n'.join(lines)+'\n')
    print(f'Indexed {len(catalog)} actual reading records, {figures} figures, {tables} tables, {panels} facets/blocks')


if __name__=='__main__': main(Path(sys.argv[1]).resolve())
