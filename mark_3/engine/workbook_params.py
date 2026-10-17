"""Keep Mark 3's parameter presentation when the shared writer saves results."""
from copy import deepcopy
from pathlib import Path
import posixpath
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree as ET
from openpyxl.utils.cell import range_boundaries, get_column_letter

S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS = {'s': S}


def sheet_part(archive, name):
    rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
    for sheet in ET.fromstring(archive.read('xl/workbook.xml')).find('s:sheets', NS):
        if sheet.get('name') == name:
            target = rels[sheet.get('{' + R + '}id')]
            return target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
    raise ValueError(f'Missing worksheet: {name}')


class StyleMap:
    """Append remapped styles so existing destination style IDs remain valid."""

    def __init__(self, source, target):
        self.source, self.target = source, target
        self.cache = {}

    def append(self, group, node):
        parent = self.target.find('s:' + group, NS)
        if parent is None:
            parent = ET.Element('{' + S + '}' + group)
            self.target.insert(0, parent)  # Only optional numFmts may be absent.
        def key(value):
            return (value.tag, tuple(sorted(value.attrib.items())), value.text or '', tuple(key(c) for c in value))
        expected = key(node)
        for i, existing in enumerate(parent):
            if key(existing) == expected:
                return i
        parent.append(node)
        parent.set('count', str(len(parent)))
        return len(parent) - 1

    def number_format(self, index):
        if index < 164:
            return index
        formats = self.source.find('s:numFmts', NS)
        src = next(n for n in formats if int(n.get('numFmtId')) == index)
        dest = self.target.find('s:numFmts', NS)
        if dest is not None:
            for fmt in dest:
                if fmt.get('formatCode') == src.get('formatCode'):
                    return int(fmt.get('numFmtId'))
        node = deepcopy(src)
        new_id = max([163] + ([] if dest is None else [int(n.get('numFmtId')) for n in dest])) + 1
        node.set('numFmtId', str(new_id))
        self.append('numFmts', node)
        return new_id

    def map(self, group, index):
        key = group, int(index)
        if key in self.cache:
            return self.cache[key]
        node = deepcopy(self.source.find('s:' + group, NS)[int(index)])
        if group in ('cellXfs', 'cellStyleXfs'):
            for attr, child_group in [('fontId', 'fonts'), ('fillId', 'fills'), ('borderId', 'borders')]:
                if node.get(attr) is not None:
                    node.set(attr, str(self.map(child_group, node.get(attr))))
            if node.get('numFmtId') is not None:
                node.set('numFmtId', str(self.number_format(int(node.get('numFmtId')))))
            if group == 'cellXfs' and node.get('xfId') is not None:
                node.set('xfId', str(self.map('cellStyleXfs', node.get('xfId'))))
        self.cache[key] = self.append(group, node)
        return self.cache[key]


def preserve_parameter_sheet(source, output, hidden_rows=None):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError('Parameter presentation requires a separate output workbook')
    with ZipFile(source) as src, ZipFile(output) as dst:
        origin, target = sheet_part(src, 'Strategy_Params'), sheet_part(dst, 'Strategy_Params')
        old, new = ET.fromstring(src.read(origin)), ET.fromstring(dst.read(target))
        styles = StyleMap(ET.fromstring(src.read('xl/styles.xml')), ET.fromstring(dst.read('xl/styles.xml')))
        strings = ET.fromstring(src.read('xl/sharedStrings.xml')) if 'xl/sharedStrings.xml' in src.namelist() else []
        data = new.find('s:sheetData', NS)
        dest_rows = {row.get('r'): row for row in data}
        for row in old.find('s:sheetData', NS):
            number = row.get('r')
            dest = dest_rows.get(number)
            if dest is None:
                raise ValueError(f'Parameter row {number} missing from result workbook')
            for attr in ('ht', 'customHeight', 'hidden', 'outlineLevel', 'collapsed'):
                dest.attrib.pop(attr, None)
                if attr in row.attrib:
                    dest.set(attr, row.get(attr))
            if hidden_rows is not None:
                dest.set('hidden', '1' if int(number) in hidden_rows else '0')
            cells = {cell.get('r'): cell for cell in dest}
            for cell in row:
                address = cell.get('r', '')
                if not address or address.rstrip('0123456789') not in ('A', 'B', 'C', 'D', 'E', 'F'):
                    continue
                existing = cells.get(address)
                # Preserve the run's parameter values, not stale source values.
                clone = deepcopy(existing if address.startswith('C') and int(number) >= 4 and existing is not None else cell)
                clone.set('s', str(styles.map('cellXfs', cell.get('s', '0'))))
                if clone.get('t') == 's' and not (address.startswith('C') and int(number) >= 4 and existing is not None):
                    idx = int(clone.find('s:v', NS).text)
                    for child in list(clone):
                        clone.remove(child)
                    clone.set('t', 'inlineStr')
                    inline = ET.SubElement(clone, '{' + S + '}is')
                    for child in strings[idx]:
                        inline.append(deepcopy(child))
                if existing is None:
                    dest.append(clone)
                else:
                    dest.replace(existing, clone)
        for tag in ('cols', 'sheetViews', 'sheetFormatPr', 'dataValidations'):
            node, existing = old.find('s:' + tag, NS), new.find('s:' + tag, NS)
            if node is not None and existing is not None:
                new.replace(existing, deepcopy(node))
            elif node is not None:
                # Our workbook has these sections except possibly validations.
                if tag != 'dataValidations':
                    raise ValueError(f'Missing destination layout section: {tag}')
                before = new.find('s:pageMargins', NS)
                new.insert(new.index(before) if before is not None else len(new), deepcopy(node))
        if hidden_rows is not None:
            # Imported validation ranges can survive replacement in the authoring
            # library. Resolve overlaps once, favouring the newly authored rule.
            validations = new.find('s:dataValidations', NS)
            latest = {}
            for index, validation in enumerate(validations):
                for ref in validation.get('sqref').split():
                    left, top, right, bottom = range_boundaries(ref)
                    for row in range(top, bottom + 1):
                        for col in range(left, right + 1):
                            latest[f'{get_column_letter(col)}{row}'] = index
            for index, validation in enumerate(list(validations)):
                refs = [ref for ref, rule in latest.items() if rule == index]
                if not refs:
                    validations.remove(validation)
                    continue
                validation.set('sqref', ' '.join(refs))
                validation.set('showErrorMessage', '1')
                validation.set('errorStyle', 'stop')
                validation.set('allowBlank', '0')
                validation.set('errorTitle', 'Invalid parameter value')
                validation.set('error', 'Use a value matching this parameter type and allowed range.')
            validations.set('count', str(len(validations)))
        patches = {target: ET.tostring(new, encoding='UTF-8', xml_declaration=True),
                   'xl/styles.xml': ET.tostring(styles.target, encoding='UTF-8', xml_declaration=True)}
        temp = output.with_suffix(output.suffix + '.params.tmp')
        with ZipFile(temp, 'w', ZIP_DEFLATED) as out:
            for info in dst.infolist():
                out.writestr(deepcopy(info), patches.get(info.filename, dst.read(info.filename)))
    temp.replace(output)
