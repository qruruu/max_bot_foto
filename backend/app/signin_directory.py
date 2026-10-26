"""The platform routes a login to a database without exposing company names before authentication."""

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import database_engine
from app.models import Inspector, OrganizationLogin, User
from app.organization_registry import control_session


def register_user(scope, user):
    if scope is None or user.id == scope.owner_user_id:
        return
    with control_session() as control:
        if control.scalar(select(Inspector.id).where(Inspector.login == user.login.lower())):
            raise HTTPException(409, "Этот логин занят проверяющим. Выберите другой логин.")
        control.execute(insert(OrganizationLogin).values(login=user.login.lower(), organization_id=scope.id,
                                                        user_id=user.id).on_conflict_do_update(
            index_elements=[OrganizationLogin.login, OrganizationLogin.organization_id], set_={"user_id": user.id}))
        control.commit()


def sync_directory(scope):
    with Session(database_engine(scope.database_url)) as tenant:
        users = list(tenant.execute(select(User.id, User.login).where(User.id != scope.owner_user_id)))
    with control_session() as control:
        control.execute(delete(OrganizationLogin).where(OrganizationLogin.organization_id == scope.id))
        control.add_all(OrganizationLogin(login=login.lower(), organization_id=scope.id, user_id=id)
                        for id, login in users)
        control.commit()
