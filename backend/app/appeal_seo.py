"""Search discovery of the same appeals that are available on the public wall."""

from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.appeal_sharing import public_origin
from app.appeal_workflow import public_conditions
from app.appeals import public_available
from app.models import CitizenAppeal
from app.organization_registry import control_session

router = APIRouter(tags=["public appeal discovery"])
SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


@router.get("/sitemap.xml", include_in_schema=False)
def public_sitemap():
    origin = public_origin()
    root = Element("urlset", xmlns=SITEMAP_NAMESPACE)
    SubElement(SubElement(root, "url"), "loc").text = origin + "/"
    with control_session() as db:
        public_available(db)
        # At most 50,000 URLs per sitemap, including the home page. Fetch IDs only:
        # no contacts, internal notes, photo blobs, or unpublished response content.
        ids = db.scalars(select(CitizenAppeal.id).where(*public_conditions())
                         .order_by(CitizenAppeal.id.desc()).limit(49_999))
        for appeal_id in ids:
            SubElement(SubElement(root, "url"), "loc").text = f"{origin}/a/{appeal_id}"
    return Response(tostring(root, encoding="utf-8", xml_declaration=True),
                    media_type="application/xml")
