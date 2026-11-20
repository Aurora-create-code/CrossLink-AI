"""Read-only reports derived from saved candidates; no model calls or state changes."""
from urllib.parse import quote
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from app.database import connect
from app.knowledge import rows
from app.opportunities import render

DEMO_ID='74d147f4570446e9b6bc75d04493beb7'

def build_report(db,candidate_id):
    found=rows(db,'SELECT * FROM opportunity_items WHERE id=?',(candidate_id,))
    if not found:raise HTTPException(404,'没有找到该机会候选，请返回机会列表选择已有候选。')
    batch=rows(db,'SELECT * FROM opportunity_batches WHERE id=?',(found[0]['batch_id'],))[0]
    item=render(db,found[0],batch)
    # Plain-language demonstration is tied to this saved candidate and its evidence.
    # Other candidates use their actual persisted fields, never the PLA narrative.
    if candidate_id==DEMO_ID and item['title']=='梯度孔径PLA支架':
        title='孔洞怎么搭配，才能既通透又结实？'
        sections=[
            {'heading':'想解决什么','body':'把一种可降解塑料（PLA）做成供细胞进入、生长的多孔结构，也叫支架。希望它既让液体和细胞容易进去，又能保持结实。'},
            {'heading':'讲义提供什么依据','body':'讲义介绍了PLA用于组织再生，列出10—100微米的孔洞尺寸，并说明多孔结构可让体液和细胞进入、内部结构会影响材料表现。具体原文和知识ID见下方来源记录。'},
            {'heading':'AI提出什么建议','body':'比较两种结构：一种各处孔差不多大，另一种从外到内孔逐渐变小。看看哪种更能兼顾通透和结实。这是已保存候选的建议，不是讲义已经证实的结论。'},
            {'heading':'如何比较验证','body':'尽量保持材料、整体尺寸和总孔隙率相同，比较液体通过速度、抗压能力和细胞进入深度。已保存的具体计划：'+item['validation_plan']},
            {'heading':'目前还不知道什么','body':'大小孔搭配是否真的更好、能否稳定制造，以及是否已有同类研究，均需核实。候选列出的未验证假设：'+'；'.join(item['unverified_assumptions'])},
            {'heading':'这个工具能做什么','body':'从PDF整理知识，经人工确认或拒绝后提出有来源可查的想法，并形成可以下载的报告。'},
        ]
    else:
        title=item['title']
        sections=[{'heading':heading,'body':item[key]} for heading,key in [('想解决什么（假设）','need_hypothesis'),('如何连接知识（AI推理）','knowledge_connection'),('AI提出什么建议','proposed_solution'),('为什么可能有用（假设）','potential_value'),('如何比较验证（尚未执行）','validation_plan')]]
        sections.append({'heading':'目前还不知道什么','body':'；'.join(item['unverified_assumptions'])})
    return {'candidate_id':item['id'],'batch_id':item['batch_id'],'model':item['model'],'title':title,
        'introduction':'演示用研究想法：尚未做实验，也未核实是否已有同类研究。选作案例不表示用户认可或科学有效。',
        'sections':sections,'sources':item['sources'],'basis_changed':item['basis_changed'],'status':'unverified',
        'warning':'依据已变化，需要重新核对。下文依据与讲义概述保留生成时快照，不可继续当作当前有效的已确认依据。' if item['basis_changed'] else ''}

def markdown(report):
    # Escape Markdown syntax from persisted text, while retaining genuine quote text.
    def plain(value):
        return str(value).replace('\\','\\\\').replace('<','&lt;').replace('>','&gt;').replace('[','\\[').replace(']','\\]').replace('*','\\*').replace('_','\\_').replace('`','\\`').replace('#','\\#')
    lines=['# '+plain(report['title']),'',plain(report['introduction']),'']
    if report['warning']:lines+=['**'+plain(report['warning'])+'**','']
    for section in report['sections']:lines+=['## '+plain(section['heading']),'',plain(section['body']),'']
    lines+=['## 来源记录（生成时快照与当前状态）','']
    labels={'confirmed':'已确认','rejected':'已拒绝','pending':'待审核','missing':'来源已缺失'}
    for source in report['sources']:
        lines += ['- 知识ID：'+plain(source['id'])+'；文档ID：'+plain(source['document_id'])+'；物理页码：'+str(source['page_number']),
            '  生成时审核：已确认；当前审核：'+labels.get(source['review_status'],'未知')+'；'+('依据已变化，需要重新核对。' if source['changed'] else '与生成时依据一致。'),'',
            '  来源知识：'+plain(source['content']),'','原文引句（保留原有换行）：','']
        lines.extend('> '+plain(line) for line in source['quote'].split('\n'))
        doc=quote(source['document_id'],safe='');page=source['page_number']
        lines += ['','[阅读对应文字页](http://127.0.0.1:5173/?document='+doc+'&page='+str(page)+') · [打开原PDF对应页](http://127.0.0.1:5173/api/documents/'+doc+'/original#page='+str(page)+')','']
    lines+=['## 报告标识','', '候选ID：'+report['candidate_id'],'','批次ID：'+report['batch_id'],'','模型：'+plain(report['model']),'','状态：未验证；实验未执行，未核实创新性。','', '来源状态反映本次导出时的查询结果。离线文件不会自动更新；后续审核变化请重新打开网页核对。','']
    return '\n'.join(lines)

def router_for(path):
    router=APIRouter(prefix='/api/reports',tags=['reports'])
    @router.get('/{candidate_id}')
    def report(candidate_id:str):
        with connect(path) as db:return build_report(db,candidate_id)
    @router.get('/{candidate_id}/markdown')
    def export(candidate_id:str):
        with connect(path) as db:report=build_report(db,candidate_id)
        return Response(markdown(report),media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':'attachment; filename="crosslink-report-'+candidate_id+'.md"','Cache-Control':'no-store'})
    return router
