"""Facts from the supplied workbook and schedule image, never from HTML demo quantities."""

import re

from sqlalchemy import select

from app.daily_report_schemas import ReportingConfig
from app.models import District, WorkType


def shashko_config(db=None):
    areas = [
        {"id": "area58", "contract_id": "58", "name": "1, 2, 2а, 3, 4, 7, 12, 16 микрорайоны, ул. Набережная", "district_ids": []},
        {"id": "area60", "contract_id": "60", "name": "11, 11а, 11б микрорайоны, ПНМК-6, ОБТОиК, ул. Киевская 1/2, АТБ-6, СУ-62", "district_ids": []},
    ]
    # Explicit aliases cover the organization's existing names, including one joint district.
    # No substring/fuzzy match: e.g. 1 must never bind 11 or 12.
    known_names = [
        [["1"], ["2"], ["2а"], ["3"], ["4"], ["7"], ["12"], ["16"], ["ул. Набережная", "Набережная"]],
        [["11"], ["11а"], ["11б"], ["ПНМК-6", "ПНМК-6, ОБТОиК"], ["ОБТОиК"],
         ["ул. Киевская 1/2", "Киевская"], ["АТБ-6"], ["СУ-62"]],
    ]
    def normalize(value):
        return re.sub(r"[^\w]", "", re.sub(r"микрорайон[а-я]*|мкр", "", value.lower()))
    available_codes = None
    if db is not None:
        available_codes = set(db.scalars(select(WorkType.code)))
        districts = list(db.execute(select(District.id, District.name).where(District.active)).all())
        for area, groups in zip(areas, known_names, strict=True):
            matched = []
            for names in groups:
                expected = {normalize(n) for n in names}
                matched.extend((id, name) for id, name in districts if normalize(name) in expected)
            matched = list(dict.fromkeys(matched))
            area["district_ids"] = [id for id, _ in matched]
            if matched:
                area["name"] = ", ".join(name for _, name in matched)

    def work(id, name, unit, season, recurrence, code, note, **kwargs):
        codes = [code] if isinstance(code, str) else code
        return {"id": id, "name": name, "unit": unit, "season": season, "recurrence": recurrence,
                "photo_codes": [c for c in codes if available_codes is None or c in available_codes],
                "schedule_note": note,
                "assignments": [{"area_id": a["id"], "quantity": None, "resources": ""} for a in areas], **kwargs}
    mowing_dates = ["06-12", "07-31", "08-30"]
    works = [
        work("bins", "Очистка урн от мусора (включая сбор, транспортировку и утилизацию)", "шт.", "all", "daily", "BIN_EMPTYING", "Круглогодично, ежедневно"),
        work("bin-wash", "Промывка урн", "шт.", "summer", "windows", "BIN_WASHING", "Два окна: 01–15 июня и 01–15 августа", windows=[{"start": "06-01", "end": "06-15"}, {"start": "08-01", "end": "08-15"}]),
        work("green-clean", "Уборка зелёных зон, газонов (включая сбор, транспортировку и утилизацию)", "м²", "summer", "four_windows", ["GREEN_CLEANING", "LAWN_LITTER"], "4 окна в месяц: 01–07, 08–14, 15–21, 22–конец месяца"),
        work("mowing", "Выкашивание травы (включая сбор, транспортировку и утилизацию)", "м²", "summer", "deadlines", "GRASS_MOWING", "3 раза: до 12 июня, 31 июля, 30 августа", dates=mowing_dates),
        work("raking", "Уборка зелёных зон, газонов под грабли", "м²", "summer", "event", "LAWN_RAKING", "Весна — до 15.05; осень — после заявки, до 15.10. Включение по подтверждённому заданию"),
        work("playground-monthly", "Содержание детских, спортивных, тренажёрных площадок", "шт.", "all", "monthly", "PLAYGROUND_MAINTENANCE", "Ежемесячно (12 месяцев)"),
        work("maf-inspection", "Осмотр МАФ детских и спортивных, тренажёрных площадок", "шт.", "all", "daily", "PLAYGROUND_MAINTENANCE", "Ежедневный осмотр МАФ"),
        work("playground-snow", "Содержание площадок / уборка снега", "уточнить", "winter", "event", "PLAYGROUND_MAINTENANCE", "После снегопада; крайний срок — 24 часа. Единицу и объём уточнить по полному контракту"),
        work("playground-summer", "Содержание площадок / летняя уборка", "уточнить", "summer", "four_windows", "PLAYGROUND_MAINTENANCE", "4 окна в месяц: 01–07, 08–14, 15–21, 22–последнее число месяца. Единицу уточнить по полному контракту"),
        work("playground-mowing", "Содержание площадок / покос", "уточнить", "summer", "deadlines", "GRASS_MOWING", "До 12.06; до 31.07; до 30.08. Единицу уточнить по полному контракту", dates=mowing_dates),
        work("paving-wash", "Мойка брусчатки", "м²", "summer", "dates", "PAVING_WASHING", "8 мая и 30 августа", dates=["05-08", "08-30"]),
        work("random-litter", "Уборка от случайного мусора (проезды и площади без покрытия)", "м²", "summer", "monthly", "UNPAVED_LITTER", "1 раз в месяц"),
        work("sweeping", "Подметание территории (подходы, проезды с покрытием, дорожки, парковки, брусчатка)", "м²", "summer", "monthly", "SWEEPING", "1 раз в месяц"),
        work("deicing", "Распределение противогололёдных материалов вручную", "м²", "winter", "event", "DEICING_MANUAL", "Событие скользкости; одно событие = один цикл"),
        work("snow-manual", "Уборка снега вручную (подходы к зданиям и сооружениям, накрывной камень цветников)", "м²", "winter", "interval", "SNOW_MANUAL", "1 раз в 5 дней в активный снежный период", requires_event=True),
    ]
    return ReportingConfig.model_validate({
        "profile": {"company_name": "Индивидуальный предприниматель Шашко Андрей Дмитриевич",
                    "short_name": "ИП Шашко А. Д.", "city": "Нефтеюганск",
                    "address": "628300, Россия, ХМАО-Югра, г. Нефтеюганск, 7 мкр., д. 24, кв. 5",
                    "inn": "860400307580", "ogrn": "304860413400240", "phone": "+7 (902) 852-97-99",
                    "email": "shashko@yandex.ru",
                    "recipient": ["ВРИО директора МКУ", "КХ «Служба единого заказчика»", "А. С. Анохину"],
                    "photo_url": "https://disk.yandex.ru/d/QNplNB1-yg2_Gg",
                    "subject": "по содержанию земель общего пользования города Нефтеюганска"},
        "contracts": [{"id": "58", "number": "ЭА.2026.00058", "prefix": "МК-58-"},
                      {"id": "60", "number": "ЭА.2026.00060", "prefix": "МК-60-"}],
        "areas": areas, "works": works,
        "source_notes": "Реквизиты и территории: ZOP_daily_reports_58_60_v8_ready.xlsx, включая шапку письма. "
                        "Периодичность: присланный фрагмент таблицы контракта. Полного контракта с объёмами нет. "
                        "558/14 урн, 22/6 площадок и 3 человека — факт только за 17.10.2026, не постоянные нормы. "
                        "Виды площадочных работ в фрагменте не имеют отдельной единицы: для них оставлено «уточнить». "
                        "Границы сезонов, нормы, годовые лимиты и следующий номер письма нужно уточнить. "
                        "Демонстрационные цифры, территории и резервы из HTML не импортированы. "
                        "Бланк и подпись с печатью добавляются в настройке отдельно для этой организации.",
    })
