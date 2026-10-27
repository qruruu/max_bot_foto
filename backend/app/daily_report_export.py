"""Familiar customer letters with an unbounded row count and an explicit draft mark."""

import re
from datetime import timedelta
from html import escape
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment

from app.daily_report_layout import COLUMN_PERCENTAGES
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


def quantity_text(value, unit):
    if value is None:
        return "—"
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", ",") + " " + unit


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
    from app.daily_report_layout import LetterSheet

    config, document, letters = letter_data(report, draft)
    wb = Workbook()
    wb.remove(wb.active)
    profile = config.profile
    summary = wb.create_sheet("Сведения")
    for label, value in [("Дата письма", report.day), ("Факт за день", report.day - timedelta(days=1)),
                         ("План на день", report.day), ("Организация", profile.company_name),
                         ("Режим", "Тестовый" if report.cohort == "test" else "Рабочий"),
                         ("Статус", "ЧЕРНОВИК" if draft else "Утверждён"),
                         ("Версия", report.version if draft else report.approved_version),
                         ("Фотоотчёт", profile.photo_url), ("Примечание", document.note)]:
        summary.append([literal(label), literal(value)])
    summary.column_dimensions["A"].width, summary.column_dimensions["B"].width = 24, 85
    for cells in summary:
        for cell in cells:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if not isinstance(cell.value, str) and hasattr(cell.value, "year"):
                cell.number_format = "dd.mm.yyyy"
    for index, letter in enumerate(letters, 1):
        contract = letter["contract"]
        suffix = re.sub(r"[\\/*?:\[\]]", "-", contract.number)[-20:]
        sheet = wb.create_sheet((f"Письмо {index} " + suffix)[:31])
        layout = LetterSheet(sheet, contract)
        signed = not draft and report.cohort == "production" and profile.signature_image
        signature_height = layout.image_height(profile.signature_image, .8, 116) if signed else 24
        footer_keep = signature_height + 28 + (20 if profile.photo_url else 0)
        if draft or report.cohort == "test":
            layout.text("ЧЕРНОВИК" if draft else "ТЕСТОВЫЙ ОТЧЁТ", bold=True, center=True)
        if profile.letterhead_image:
            layout.image(profile.letterhead_image)
        else:
            layout.text(profile.company_name, bold=True, center=True, size=13)
            layout.text(profile.address, size=10)
            layout.text("   ".join(value for value in [f"ИНН {profile.inn}" if profile.inn else "",
                        f"ОГРНИП/ОГРН {profile.ogrn}" if profile.ogrn else "", profile.phone, profile.email] if value), size=10)
        layout.space()
        layout.recipient(letter["number"], report.day, profile.recipient)
        layout.space()
        layout.text(f"В рамках исполнения контракта {contract.number} сообщаю следующую информацию:")
        detailed_notes = []
        for kind, title, day in [("fact", "Фактическая дислокация оказания услуг (производства работ)", report.day - timedelta(days=1)),
                                 ("plan", "Плановая дислокация оказания услуг", report.day)]:
            rows = []
            for number, line in enumerate(letter[kind], 1):
                displayed = dict(line)
                for field, limit, label in [("area", 600, "Место оказания услуг"), ("resources", 250, "Персонал и техника"), ("note", 300, "Примечание")]:
                    if len(displayed[field]) > limit:
                        detailed_notes.append(f"{('Факт' if kind == 'fact' else 'План')}, строка {number}. {label}: {displayed[field]}")
                        displayed[field] = f"См. примечание к строке {number}"
                quantity = quantity_text(line["quantity"], line["unit"])
                values = [number, displayed["work"], displayed["area"], displayed["resources"], quantity, displayed["note"]]
                # Extremely long unbroken text belongs to the notes, not a >409 pt Excel row.
                for column in (1, 2, 3, 5):
                    if layout.cells(values)[1] <= 390:
                        break
                    if len(str(values[column])) > 70:
                        detailed_notes.append(f"{('Факт' if kind == 'fact' else 'План')}, строка {number}: {values[column]}")
                        values[column] = f"См. примечание к строке {number}"
                rows.append((values, line))
            headers = ["№", "Наименование работ, услуг", "Место оказания услуг (производства работ)",
                       "Спецтехника, персонал", "Объём" if kind == "fact" else "План, объём", "Примечания"]
            header_height = layout.cells(headers, bold=True)[1]
            first_height = layout.cells(rows[0][0])[1] if rows else 28
            tail = footer_keep if kind == "plan" and len(rows) <= 1 and not detailed_notes and not document.note else 0
            layout.ensure(56 + header_height + first_height + tail)
            layout.space()
            layout.text(title, bold=True, center=True)
            layout.text(profile.subject, center=True)
            layout.text(f"{profile.short_name or profile.company_name} {'за' if kind == 'fact' else 'на'} {day:%d.%m.%Y} года", bold=True, center=True)
            layout.table_row(headers, header=True)
            if not rows:
                layout.text("Работы не заявлены" + (": " + document.note if document.note else ""), minimum=28,
                            keep=footer_keep if kind == "plan" and not detailed_notes else 0)
            for number, (values, line) in enumerate(rows, 1):
                height = layout.cells(values)[1]
                tail = footer_keep if kind == "plan" and number == len(rows) and not detailed_notes and not document.note else 0
                if layout.ensure(height + tail):
                    layout.text(f"Контракт {contract.number}. {'Выполнено за' if kind == 'fact' else 'Запланировано на'} {day:%d.%m.%Y}. Продолжение", size=10)
                    layout.table_row(headers, header=True)
                layout.table_row(values, number=line["quantity"], unit=line["unit"])
        for note in detailed_notes:
            layout.space()
            layout.text(note, size=10)
        layout.space()
        if profile.photo_url:
            layout.text("Фотоотчёт доступен по ссылке " + profile.photo_url, size=10,
                        keep=signature_height + 6 if not document.note else 20)
        if document.note:
            layout.text("Примечание: " + document.note, size=10, keep=signature_height + 6)
        layout.space()
        if signed:
            layout.image(profile.signature_image, scale=.8, max_height=116)
        else:
            layout.text(profile.short_name or profile.company_name, minimum=24)
        layout.finish()
    wb.move_sheet(summary, offset=len(letters))
    if letters:
        # Retain traceability in Excel without printing service metadata as customer letters.
        summary.sheet_state = "hidden"
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
        parts = ["<article class='daily-letter'>"]
        if draft or report.cohort == "test":
            parts.append("<div class='daily-letter-draft'>" + ("ЧЕРНОВИК" if draft else "ТЕСТОВЫЙ ОТЧЁТ") + "</div>")
        if profile.letterhead_image:
            parts.append(f"<header class='daily-letter-image-header'><img src='{esc(profile.letterhead_image)}' alt='Фирменный бланк'></header>")
        else:
            parts.append(f"<header><h2>{esc(profile.company_name)}</h2><p>{esc(profile.address)}</p>"
                         f"<p>ИНН {esc(profile.inn)} · ОГРНИП/ОГРН {esc(profile.ogrn)} · {esc(profile.phone)} · {esc(profile.email)}</p></header>")
        parts += [
                  f"<div class='daily-letter-recipient'><p>№ {esc(letter['number'] or 'без номера (черновик)')} от {report.day:%d.%m.%Y}</p><div>" + "<br>".join(map(esc, profile.recipient)) + "</div></div>",
                  f"<p>В рамках исполнения контракта {esc(letter['contract'].number)} сообщаю следующую информацию:</p>"]
        for kind, title, day in [("fact", "Фактическая дислокация оказания услуг (производства работ)", report.day - timedelta(days=1)), ("plan", "Плановая дислокация оказания услуг", report.day)]:
            parts.append(f"<section class='daily-letter-block'><h3>{title}</h3><p class='daily-letter-center'>{esc(profile.subject)}<br><b>{esc(profile.short_name or profile.company_name)} {'за' if kind == 'fact' else 'на'} {day:%d.%m.%Y} года</b></p>")
            volume = "Объём" if kind == "fact" else "План, объём"
            parts.append("<table class='" + kind + "-table'><colgroup>" + "".join(f"<col style='width:{width}%'>" for width in COLUMN_PERCENTAGES) + "</colgroup><thead><tr><th>№</th><th>Наименование работ, услуг</th><th>Место оказания услуг (производства работ)</th><th>Спецтехника, персонал</th><th>" + volume + "</th><th>Примечания</th></tr></thead><tbody>")
            for n, row in enumerate(letter[kind], 1):
                quantity = quantity_text(row["quantity"], row["unit"])
                parts.append("<tr>" + "".join("<td>" + esc(value) + "</td>" for value in [n, row["work"], row["area"], row["resources"], quantity, row["note"]]) + "</tr>")
            if not letter[kind]:
                parts.append("<tr><td colspan='6'>Работы не заявлены. " + esc(document.note) + "</td></tr>")
            parts.append("</tbody></table></section>")
        if document.note:
            parts.append("<p>Примечание: " + esc(document.note) + "</p>")
        parts.append("<div class='daily-letter-ending'>")
        if profile.photo_url:
            parts.append(f"<p>Фотоотчёт доступен по ссылке <a href='{esc(profile.photo_url)}'>{esc(profile.photo_url)}</a></p>")
        if not draft and report.cohort == "production" and profile.signature_image:
            parts.append(f"<div class='daily-letter-signature'><img src='{esc(profile.signature_image)}' alt='Подпись и печать организации'></div>")
        else:
            parts.append("<p class='daily-letter-signature'>" + esc(profile.short_name or profile.company_name) + "</p>")
        parts.append("</div></article>")
        content.append("".join(parts))
    styles = Path(__file__).with_name("report_letter.css").read_text()
    return ("<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<meta name='color-scheme' content='light'><title>" + esc(document_title(report, draft=draft)) +
            "</title><style>" + styles + "</style></head><body class='report-document'>"
            "<nav><button onclick='window.print()'>Печать / Сохранить в PDF</button></nav>" +
            "".join(content) + "</body></html>")
