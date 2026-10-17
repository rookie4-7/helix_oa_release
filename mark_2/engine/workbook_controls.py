"""Preserve Excel form controls that openpyxl does not round-trip."""
from copy import deepcopy
from pathlib import Path
import posixpath
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as ET

S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def runner_part(z):
    rels={r.get('Id'): r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
    for sheet in ET.fromstring(z.read('xl/workbook.xml')).find('{'+S+'}sheets'):
        if sheet.get('name')=='Runner':
            target=rels[sheet.get('{'+R+'}id')]
            return target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl',target))
    raise ValueError('Runner worksheet is missing')


def preserve_runner_controls(source, output):
    source,output=Path(source),Path(output)
    if source.resolve()==output.resolve():
        raise ValueError('Mark 2 must write to a separate output workbook')
    with ZipFile(source) as src, ZipFile(output) as dst:
        origin,target=runner_part(src),runner_part(dst)
        patches={}
        source_rels=posixpath.join(posixpath.dirname(origin),'_rels',posixpath.basename(origin)+'.rels')
        target_rels=posixpath.join(posixpath.dirname(target),'_rels',posixpath.basename(target)+'.rels')
        relroot=ET.fromstring(src.read(source_rels))
        def copy_part(name):
            if name in patches: return
            patches[name]=src.read(name)
            relname=posixpath.join(posixpath.dirname(name),'_rels',posixpath.basename(name)+'.rels')
            if relname in src.namelist():
                patches[relname]=src.read(relname)
                for r in ET.fromstring(patches[relname]):
                    if r.get('TargetMode')!='External':
                        t=r.get('Target')
                        copy_part(t.lstrip('/') if t.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(name),t)))
        for rel in relroot:
            if rel.get('TargetMode')=='External': continue
            t=rel.get('Target')
            resolved=t.lstrip('/') if t.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(origin),t))
            copy_part(resolved)
            rel.set('Target','/'+resolved)
        patches[target_rels]=ET.tostring(relroot,encoding='UTF-8',xml_declaration=True)
        old=ET.fromstring(src.read(origin)); new=ET.fromstring(dst.read(target))
        root=ET.Element(new.tag,attrib=new.attrib,nsmap=old.nsmap|new.nsmap)
        control_tags={'drawing','legacyDrawing','legacyDrawingHF','controls','AlternateContent'}
        for node in new:
            if ET.QName(node).localname not in control_tags: root.append(deepcopy(node))
        for node in old:
            if ET.QName(node).localname in control_tags: root.append(deepcopy(node))
        patches[target]=ET.tostring(root,encoding='UTF-8',xml_declaration=True)
        ct=ET.fromstring(dst.read('[Content_Types].xml'))
        keys={(n.tag,n.get('PartName'),n.get('Extension')) for n in ct}
        for node in ET.fromstring(src.read('[Content_Types].xml')):
            key=(node.tag,node.get('PartName'),node.get('Extension'))
            if key not in keys and (node.get('PartName','').lstrip('/') in patches or node.get('Extension')=='vml'):
                ct.append(deepcopy(node)); keys.add(key)
        patches['[Content_Types].xml']=ET.tostring(ct,encoding='UTF-8',xml_declaration=True)
        temp=output.with_suffix(output.suffix+'.mark2.tmp')
        with ZipFile(temp,'w',ZIP_DEFLATED) as out:
            for info in dst.infolist(): out.writestr(deepcopy(info),patches.pop(info.filename,dst.read(info.filename)))
            for name,content in patches.items(): out.writestr(name,content)
    temp.replace(output)
