"""Public, server-rendered appeal links and previews; reuse the wall's access boundary."""

from html import escape
from io import BytesIO
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Response
from fastapi import Path as ApiPath
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import select
from starlette.responses import HTMLResponse

from app.config import base_settings
from app.models import AppealPhoto
from app.organization_registry import control_session

router = APIRouter(tags=["public appeal links"])
AppealId = Annotated[int, ApiPath(ge=1, le=2**31 - 1)]
STATUSES = {"NEW": "Новое", "IN_REVIEW": "На рассмотрении", "ASSIGNED": "Назначен исполнитель",
            "IN_PROGRESS": "В работе", "COMPLETED": "На проверке результата", "REJECTED": "Исполнитель отклонил",
            "CANCELLED": "Задача отменена", "RESOLVED": "Закрыто", "DECLINED": "Отказ"}


def public_origin():
    cfg = base_settings()
    return (cfg.public_appeals_origin or cfg.app_origin).rstrip("/")


def appeal_url(appeal_id):
    return f"{public_origin()}/a/{appeal_id}"


def photo_gallery(photos, label):
    if not photos:
        return ""
    return '<div class="signal-detail-photos">' + "".join(
        f'<a href="{escape(photo["url"], quote=True)}" target="_blank" rel="noopener noreferrer">'
        f'<img src="{escape(photo["preview_url"], quote=True)}" alt="{label}" loading="lazy"/></a>'
        for photo in photos) + "</div>"


def public_html(item):
    url = appeal_url(item["id"])
    status = STATUSES.get(item["status"], "На рассмотрении")
    title = f'{item["address"]} — обращение {item["number"]} | Сигнал'
    description = " ".join(item["description"].split())[:200]
    image = f'{url}/card.jpg?v={item["updated_at"].timestamp():.0f}'
    created = item["created_at"].astimezone(ZoneInfo(base_settings().app_timezone)).strftime("%d.%m.%Y в %H:%M")
    e = escape
    response = ""
    if item["response"]:
        result = item["response"]
        response = ('<section class="signal-detail-response"><h2>Ответ организации</h2>'
                    f'<p class="signal-detail-text">{e(result["comment"])}</p>'
                    + photo_gallery(result["photos"], "Фотография ответа организации") + "</section>")
    wall_url = "/?" + urlencode({"city": item["city"]})
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<meta name="theme-color" content="#f6f8f5"/><title>{e(title)}</title>
<meta name="description" content="{e(description, quote=True)}"/>
<link rel="canonical" href="{e(url, quote=True)}"/><link rel="icon" href="/favicon.svg"/>
<meta property="og:type" content="article"/><meta property="og:site_name" content="Сигнал"/>
<meta property="og:locale" content="ru_RU"/><meta property="og:title" content="{e(title, quote=True)}"/>
<meta property="og:description" content="{e(description, quote=True)}"/>
<meta property="og:url" content="{e(url, quote=True)}"/><meta property="og:image" content="{e(image, quote=True)}"/>
<meta property="og:image:width" content="1200"/><meta property="og:image:height" content="630"/>
<meta property="og:image:type" content="image/jpeg"/><meta property="og:image:alt" content="Обращение {e(item['number'])}: {e(item['address'], quote=True)}"/>
<meta name="twitter:card" content="summary_large_image"/>
<link rel="stylesheet" href="/appeal-detail.css"/><script src="/usage.js" defer></script><script src="/appeal-detail.js" defer></script></head>
<body data-usage-page="appeals"><div class="signal-detail-shell"><header class="signal-detail-header"><a class="signal-detail-brand" href="{e(wall_url, quote=True)}"><span aria-hidden="true">◉</span>Сигнал</a><span>{e(item["city"])}</span></header>
<main><a class="signal-detail-back" href="{e(wall_url, quote=True)}">← Все обращения города</a>
<article class="signal-detail-card"><div class="signal-detail-meta"><span>{e(item["number"])}</span><span class="signal-detail-status status-{item['status']}">{status}</span></div>
<h1>{e(item["address"])}</h1>{f'<p class="signal-detail-place">{e(item["place"])}</p>' if item["place"] else ''}
<p class="signal-detail-organization">{e(item["organization_name"])}</p><p class="signal-detail-date">{created}</p>
<p class="signal-detail-text">{e(item["description"])}</p>{photo_gallery(item["photos"], "Фотография обращения")}{response}
<section class="signal-detail-share" aria-label="Ссылка на обращение"><h2>Ссылка на обращение</h2>
<div class="signal-detail-share-actions"><button type="button" id="copy-link" data-url="{e(url, quote=True)}">Копировать ссылку</button></div>
<p id="copy-status" role="status" aria-live="polite"></p><label id="copy-manual" hidden>Скопируйте ссылку<input readonly value="{e(url, quote=True)}" aria-label="Ссылка на обращение"/></label></section></article>
<p class="signal-detail-footnote">Статус актуален на момент открытия. <a href="{e(url, quote=True)}">Обновить обращение</a></p>
</main><footer>Сигнал · обращения жителей и ответы организаций</footer></div></body></html>'''


@router.get("/a/{appeal_id}", response_class=HTMLResponse)
def shared_appeal(appeal_id: AppealId):
    from app.appeal_workflow import public_appeal, wall_dict
    from app.appeals import public_available

    with control_session() as db:
        public_available(db)
        try:
            return HTMLResponse(public_html(wall_dict(db, public_appeal(db, appeal_id))))
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return HTMLResponse('''<!doctype html><html lang="ru"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/><title>Обращение недоступно · Сигнал</title>
<meta name="robots" content="noindex"/><link rel="stylesheet" href="/appeal-detail.css"/></head>
<body><div class="signal-detail-shell"><header class="signal-detail-header"><a class="signal-detail-brand" href="/">Сигнал</a></header>
<main><article class="signal-detail-card"><h1>Обращение недоступно</h1><p class="signal-detail-text">Оно больше не опубликовано или ссылка указана неверно.</p>
<a class="signal-detail-back" href="/">← Перейти к обращениям жителей</a></article></main></div></body></html>''', status_code=404)


def card_font(size, bold=False):
    names = (["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf"] if bold else
             ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf"])
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def card_lines(draw, value, font, width, maximum):
    lines, line = [], ""
    for word in " ".join(value.split()).split(" "):
        candidate = (line + " " + word).strip()
        if draw.textlength(candidate, font=font) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ""
        # Only a single word wider than the entire card may break inside a word.
        for character in word:
            if draw.textlength(line + character, font=font) > width and line:
                lines.append(line.rstrip())
                line = ""
            line += character
    if line.strip():
        lines.append(line.rstrip())
    if len(lines) > maximum:
        lines = lines[:maximum]
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def preview_card(item, photo=None):
    canvas = Image.new("RGB", (1200, 630), "#f6f8f5")
    draw = ImageDraw.Draw(canvas)
    right = 646 if photo else 1140
    if photo:
        with Image.open(BytesIO(photo)) as source:
            canvas.paste(ImageOps.fit(source.convert("RGB"), (480, 630)), (720, 0))
        draw.rectangle((712, 0, 719, 630), fill="#dbe6d7")
    draw.rounded_rectangle((48, 44, 104, 100), radius=17, fill="#275c46")
    draw.ellipse((65, 61, 87, 83), outline="white", width=3)
    draw.ellipse((73, 69, 79, 75), fill="white")
    draw.text((120, 44), "Сигнал", font=card_font(39, True), fill="#275c46")
    y = 146
    for line in card_lines(draw, item["city"], card_font(25), right - 48, 2):
        draw.text((48, y), line, font=card_font(25), fill="#627668")
        y += 33
    y += 18
    for line in card_lines(draw, item["address"], card_font(42, True), right - 48, 4):
        draw.text((48, y), line, font=card_font(42, True), fill="#1d352c")
        y += 56
    y += 20
    remaining = min(3, max(0, (470 - y) // 32))
    if remaining and item.get("description"):
        for line in card_lines(draw, item["description"], card_font(23), right - 48, remaining):
            draw.text((48, y), line, font=card_font(23), fill="#627668")
            y += 32
    draw.text((48, 494), "Обращение " + item["number"], font=card_font(22), fill="#627668")
    draw.rounded_rectangle((48, 542, right, 590), radius=12, fill="#e3eddf")
    label = STATUSES.get(item["status"], "На рассмотрении")
    draw.text((65, 549), label, font=card_font(22, True), fill="#365e46")
    output = BytesIO()
    canvas.save(output, "JPEG", quality=88)
    return output.getvalue()


@router.get("/a/{appeal_id}/card.jpg")
def shared_appeal_card(appeal_id: AppealId):
    from app.appeal_workflow import public_appeal
    from app.appeals import public_available, receipt

    with control_session() as db:
        public_available(db)
        appeal = public_appeal(db, appeal_id)
        photo = db.scalar(select(AppealPhoto.preview).where(AppealPhoto.appeal_id == appeal.id)
                          .order_by(AppealPhoto.position).limit(1))
        item = {key: getattr(appeal, key) for key in ("city", "address", "status", "description")}
        item["number"] = receipt(appeal.id)["number"]
        return Response(preview_card(item, photo), media_type="image/jpeg", headers={"Cache-Control": "no-store"})
