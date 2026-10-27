"""Familiar customer letters with an unbounded row count and an explicit draft mark."""

import base64
import math
import re
import textwrap
from datetime import timedelta
from html import escape
from io import BytesIO

from openpyxl import Workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins

from app.daily_report_schemas import ReportingConfig, ReportingDocument
from app.reports import literal


def document_title(report, *, draft=False):
    config = ReportingConfig.model_validate(report.config if draft else report.approved_config)
    company = config.profile.short_name or config.profile.company_name
    company = re.sub(r'[\\/<>:"|?*\x00-\x1f\x7f]', " ", company)
    company = re.sub(r"\s+", " ", company).strip()[:100].rstrip()
    prefix = "Черновик — " if draft else ""
    if report.cohort == "test":
        prefix += "Тестовый — "
    return f"{prefix}Отчёт {company or 'организации'} за {report.day - timedelta(days=1):%d.%m.%Y}"


def letter_data(report, draft=False):
    config = ReportingConfig.model_validate(report.config if draft else report.approved_config)
    document = ReportingDocument.model_validate(report.draft if draft else report.approved)
    works = {w.id: w for w in config.works}
    areas = {a.id: a for a in config.areas}
    letters = []
    for contract in config.contracts:
        blocks = []
        for kind in ("fact", "plan"):
            rows = []
            for line in getattr(document, kind):
                if line.decision not in {"include", "info"} or areas[line.area_id].contract_id != contract.id:
                    continue
                work, area = works[line.work_id], areas[line.area_id]
                rows.append({"work": work.name, "area": area.name, "resources": line.resources,
                             "quantity": line.quantity if line.decision == "include" else None,
                             "unit": work.unit, "note": line.note})
            blocks.append(rows)
        letters.append({"contract": contract, "number": report.letter_numbers.get(contract.id, ""),
                        "fact": blocks[0], "plan": blocks[1]})
    return config, document, letters


def export_xlsx(report, *, draft=False):
    config, document, letters = letter_data(report, draft)
    wb = Workbook()
    # Match the source workbook's column-width font; document text remains Times New Roman.
    wb._named_styles[0].font = Font(name="Carlito", size=11)
    wb.remove(wb.active)
    profile = config.profile
    summary = wb.create_sheet("Сведения")
    values = [("Дата письма", report.day), ("Факт за день", report.day - timedelta(days=1)),
              ("План на день", report.day), ("Организация", profile.company_name),
              ("Режим", "Тестовый" if report.cohort == "test" else "Рабочий"),
              ("Статус", "ЧЕРНОВИК" if draft else "Утверждён"), ("Версия", report.version if draft else report.approved_version),
              ("Фотоотчёт", profile.photo_url), ("Примечание", document.note)]
    for label, value in values:
        summary.append([literal(label), literal(value)])
    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 85
    for row in summary:
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if not isinstance(cell.value, str) and hasattr(cell.value, "year"):
                cell.number_format = "dd.mm.yyyy"
    for index, letter in enumerate(letters, 1):
        contract = letter["contract"]
        suffix = re.sub(r"[\\/*?:\[\]]", "-", contract.number)[-20:]
        sheet = wb.create_sheet((f"Письмо {index} " + suffix)[:31])
        sheet.sheet_view.showGridLines = False
        widths = [5.375, 24, 28, 13, 10, 13]
        for column, width in zip("ABCDEF", widths, strict=True):
            sheet.column_dimensions[column].width = width
        sheet.page_setup.orientation = "portrait"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_margins = PageMargins(left=.35, right=.35, top=.45, bottom=.4, header=.15, footer=.15)
        sheet.sheet_view.zoomScale = 90
        row = 1
        def wide(value, *, bold=False, center=False, height=24, size=11, sheet=sheet):
            nonlocal row
            for part in textwrap.wrap(str(value), width=1600, replace_whitespace=False, drop_whitespace=False) or [""]:
                sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
                cell = sheet.cell(row, 1, literal(part))
                cell.font = Font(name="Times New Roman", size=size, bold=bold)
                cell.alignment = Alignment(wrap_text=True, horizontal="center" if center else "left", vertical="center")
                lines = max(1, math.ceil(len(part) / (84 * 11 / size)))
                sheet.row_dimensions[row].height = max(height, lines * size * 1.4)
                row += 1
        if draft or report.cohort == "test":
            wide("ЧЕРНОВИК" if draft else "ТЕСТОВЫЙ ОТЧЁТ", bold=True, center=True)
        def picture(value, sheet=sheet, widths=widths):
            nonlocal row
            picture = Image(BytesIO(base64.b64decode(value.split(",", 1)[1])))
            width = sum(widths) * 7 + 5 * len(widths)
            height = picture.height * width / picture.width
            picture.width, picture.height = width, height
            sheet.add_image(picture, f"A{row}")
            # Reserve real rows so neither text nor the print area overlaps the drawing.
            for _ in range(math.ceil(height * .75 / 15.75)):
                sheet.row_dimensions[row].height = 15.75
                row += 1
        if profile.letterhead_image:
            picture(profile.letterhead_image)
        else:
            wide(profile.company_name, bold=True, center=True, height=36, size=14)
            wide(profile.address, height=24, size=10)
            wide("   ".join(v for v in [f"ИНН {profile.inn}" if profile.inn else "", f"ОГРНИП/ОГРН {profile.ogrn}" if profile.ogrn else "", profile.phone, profile.email] if v), size=10)
        row += 1
        for i in range(max(1, len(profile.recipient))):
            for start, end, value in [(1, 3, f"№ {letter['number'] or 'б/н'} от {report.day:%d.%m.%Y}" if i == 0 else ""),
                                      (4, 6, profile.recipient[i] if i < len(profile.recipient) else "")]:
                sheet.merge_cells(start_row=row, start_column=start, end_row=row, end_column=end)
                cell = sheet.cell(row, start, literal(value))
                cell.font = Font(name="Times New Roman", size=11)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
            sheet.row_dimensions[row].height = max(17, math.ceil(len(profile.recipient[i]) / 40) * 15 if i < len(profile.recipient) else 17)
            row += 1
        row += 1
        wide(f"В рамках исполнения контракта {contract.number} сообщаю следующую информацию:", height=30)
        border = Border(*(Side(style="thin", color="444444") for _ in range(4)))
        for kind, title, day in [("fact", "Фактическая дислокация оказания услуг (производства работ)", report.day - timedelta(days=1)),
                                  ("plan", "Плановая дислокация оказания услуг", report.day)]:
            wide(title, bold=True, center=True, height=22)
            wide(profile.subject, center=True, height=18)
            wide(profile.short_name or profile.company_name, center=True, height=18)
            wide(f"{'За' if kind == 'fact' else 'На'} {day:%d.%m.%Y} года", bold=True, center=True, height=20)
            headers = ["№", "Наименование работ, услуг", "Место оказания услуг (производства работ)", "Спецтехника, персонал", "Объём" if kind == "fact" else "План, объём", "Примечания"]
            for col, value in enumerate(headers, 1):
                cell = sheet.cell(row, col, value)
                cell.font = Font(name="Times New Roman", size=11, bold=True)
                cell.fill = PatternFill("solid", fgColor="E8ECF0")
                cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
                cell.border = border
            sheet.row_dimensions[row].height = 36
            row += 1
            lines = letter[kind]
            detailed_notes = []
            if not lines:
                wide("Работы не заявлены" + (": " + document.note if document.note else ""), height=34)
            for n, line in enumerate(lines, 1):
                shown = dict(line)
                for field, limit, label in [("area", 600, "Место оказания услуг"), ("resources", 250, "Персонал и техника"), ("note", 300, "Примечание")]:
                    if len(shown[field]) > limit:
                        detailed_notes.append(f"Строка {n}. {label}: {shown[field]}")
                        shown[field] = f"См. подробное примечание к строке {n} под таблицей"
                for col, value in enumerate([n, shown["work"], shown["area"], shown["resources"], shown["quantity"] if shown["quantity"] is not None else "—", shown["note"]], 1):
                    cell = sheet.cell(row, col, literal(value))
                    cell.font = Font(name="Times New Roman", size=11)
                    cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center" if col == 1 else "right" if col == 5 else "left")
                    cell.border = border
                    if col == 5 and shown["quantity"] is not None:
                        cell.number_format = ('0' if float(value).is_integer() else '0.###') + ' "' + line["unit"].replace('"', '""') + '"'
                # Expanded rows are retained and may span multiple printed pages.
                wraps = max(sum(max(1, math.ceil(len(part) / width)) for part in str(value).splitlines())
                            for value, width in [(shown["work"], 25), (shown["area"], 29),
                                                 (shown["resources"], 13), (shown["note"], 14)])
                sheet.row_dimensions[row].height = min(400, max(30, wraps * 14 + 6))
                row += 1
            for note in detailed_notes:
                wide(note, size=10)
            row += 1
        if profile.photo_url:
            wide("Фотоотчёт доступен по ссылке " + profile.photo_url, height=28, size=11)
        if document.note:
            wide("Примечание: " + document.note, size=10)
        if not draft and report.cohort == "production" and profile.signature_image:
            picture(profile.signature_image)
        else:
            wide(profile.short_name or profile.company_name, height=40)
        sheet.print_area = f"A1:F{row}"
        sheet.oddFooter.center.text = "Страница &P из &N"
    # Open the customer letter first; service metadata belongs after the documents.
    wb.move_sheet(summary, offset=len(letters))
    wb.active = 0
    result = BytesIO()
    wb.save(result)
    return result.getvalue()


def export_html(report, *, draft=False):
    config, document, letters = letter_data(report, draft)
    profile = config.profile
    def esc(value):
        return escape(str(value if value is not None else ""), quote=True)
    content = []
    for letter in letters:
        parts = ["<article>"]
        if draft or report.cohort == "test":
            parts.append("<div class='draft'>" + ("ЧЕРНОВИК" if draft else "ТЕСТОВЫЙ ОТЧЁТ") + "</div>")
        if profile.letterhead_image:
            parts.append(f"<header class='letterhead'><img src='{esc(profile.letterhead_image)}' alt='Фирменный бланк'></header>")
        else:
            parts.append(f"<header><h1>{esc(profile.company_name)}</h1><p>{esc(profile.address)}</p>"
                         f"<p>ИНН {esc(profile.inn)} · ОГРНИП/ОГРН {esc(profile.ogrn)} · {esc(profile.phone)} · {esc(profile.email)}</p></header>")
        parts += [
                  f"<div class='recipient'><p>№ {esc(letter['number'] or 'без номера (черновик)')} от {report.day:%d.%m.%Y}</p><div>" + "<br>".join(map(esc, profile.recipient)) + "</div></div>",
                  f"<p>В рамках исполнения контракта {esc(letter['contract'].number)} сообщаю следующую информацию:</p>"]
        for kind, title, day in [("fact", "Фактическая дислокация оказания услуг (производства работ)", report.day - timedelta(days=1)), ("plan", "Плановая дислокация оказания услуг", report.day)]:
            parts.append(f"<div class='block-title'><h2>{title}</h2><div class='center'>{esc(profile.subject)}<br>{esc(profile.short_name or profile.company_name)}<br><b>{'За' if kind == 'fact' else 'На'} {day:%d.%m.%Y} года</b></div></div>")
            volume = "Объём" if kind == "fact" else "План, объём"
            parts.append("<table><colgroup><col style='width:5%'><col style='width:27%'><col style='width:30%'><col style='width:14%'><col style='width:11%'><col style='width:13%'></colgroup><thead><tr><th>№</th><th>Наименование работ, услуг</th><th>Место оказания услуг (производства работ)</th><th>Спецтехника, персонал</th><th>" + volume + "</th><th>Примечания</th></tr></thead><tbody>")
            for n, row in enumerate(letter[kind], 1):
                quantity = f"{row['quantity']:g} {row['unit']}" if row["quantity"] is not None else "—"
                parts.append("<tr>" + "".join("<td>" + esc(value) + "</td>" for value in [n, row["work"], row["area"], row["resources"], quantity, row["note"]]) + "</tr>")
            if not letter[kind]:
                parts.append("<tr><td colspan='6'>Работы не заявлены. " + esc(document.note) + "</td></tr>")
            parts.append("</tbody></table>")
        if profile.photo_url:
            parts.append(f"<p>Фотоотчёт доступен по ссылке <a href='{esc(profile.photo_url)}'>{esc(profile.photo_url)}</a></p>")
        if document.note:
            parts.append("<p>Примечание: " + esc(document.note) + "</p>")
        if not draft and report.cohort == "production" and profile.signature_image:
            parts.append(f"<div class='signature'><img src='{esc(profile.signature_image)}' alt='Подпись и печать организации'></div>")
        else:
            parts.append("<p class='signature'>" + esc(profile.short_name or profile.company_name) + "</p>")
        parts.append("</article>")
        content.append("".join(parts))
    return """<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><title>""" + esc(document_title(report, draft=draft)) + """</title><style>
      *{box-sizing:border-box}body{font:11pt 'Times New Roman',serif;background:#e5e5e5;margin:0;color:#111;line-height:1.3}article{background:#fff;width:210mm;min-height:297mm;margin:20px auto;padding:12mm;border:1px solid #ccc}header{text-align:center;border-bottom:2px solid #111;padding-bottom:8px}header h1{font-size:14pt}header p{font-size:10pt;margin:5px 0}.letterhead{border:0;padding:0}.letterhead img,.signature img{display:block;width:100%;height:auto}h2{font-size:11pt;text-align:center;margin:0 0 3px}.recipient{display:flex;justify-content:space-between;gap:12mm;margin:7mm 0}.recipient p{margin:0}.recipient>div{width:40%;flex-shrink:0}.center{text-align:center;line-height:1.4}.block-title{margin-top:5mm;break-after:avoid}table{width:100%;table-layout:fixed;border-collapse:collapse;margin:4mm 0 6mm;font-size:10pt}td,th{border:1px solid #222;padding:5px 4px;overflow-wrap:break-word;vertical-align:middle}td:first-child{text-align:center}td:nth-child(5){text-align:right}thead{display:table-header-group}th{background:#e8ecf0;font-weight:bold}.signature{margin:6mm 0 0;break-inside:avoid}.draft{text-align:center;font-weight:bold;margin-bottom:4mm}nav{font:14px system-ui;padding:15px;text-align:center}button{padding:10px 20px;cursor:pointer}tr{break-inside:avoid}a{color:inherit;overflow-wrap:anywhere}@page{size:A4;margin:12mm}@media screen and (max-width:800px){body{overflow-x:auto}article{margin:12px 0}}@media print{body{background:#fff}nav{display:none}article{width:auto;min-height:0;border:0;margin:0;padding:0;break-after:page}article:last-child{break-after:auto}}
    </style><nav><button onclick="window.print()">Печать / Сохранить в PDF</button></nav>""" + "".join(content) + "</html>"
