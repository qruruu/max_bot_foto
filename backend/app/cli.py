import argparse
import getpass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hasher
from app.db import engine
from app.domain import audit
from app.integrations import MaxClient
from app.models import User


def main():
    parser = argparse.ArgumentParser(description="Метка: управление сервисом")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin")
    admin.add_argument("--login", required=True)
    admin.add_argument("--name", default="Администратор")
    webhook = sub.add_parser("subscribe")
    webhook.add_argument("--url", required=True)
    sub.add_parser("check-max")
    initialize = sub.add_parser("initialize-organizations", help="Сохранить текущую компанию и назначить владельца")
    initialize.add_argument("--owner-login", required=True)
    initialize.add_argument("--name", required=True)
    initialize.add_argument("--slug", required=True)
    sub.add_parser("migrate", help="Обновить общую базу и базы всех организаций")
    prepare_import = sub.add_parser("prepare-organization-import", help="Подготовить пустую организацию для переноса")
    prepare_import.add_argument("--organization", required=True)
    finish_import = sub.add_parser("finish-organization-import", help="Проверить перенесённые данные и закрепить чаты")
    finish_import.add_argument("--organization", required=True)
    finish_import.add_argument("--old-data-dir", default="/data")
    finish_import.add_argument("--disk-root", required=True)
    finish_import.add_argument("--training-root")
    finish_import.add_argument("--exchange-root")
    finish_import.add_argument("--spam-root")
    args = parser.parse_args()
    if args.command == "prepare-organization-import":
        from app.organization_import import prepare
        try:
            database, directory = prepare(args.organization)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print("База для восстановления:", database)
        print("Папка для previews, spool и models:", directory)
        print("Организация недоступна до finish-organization-import. Файл database.json сохраняйте.")
    elif args.command == "finish-organization-import":
        from app.config import Settings
        from app.organization_import import finish
        # Apply the same folder validation used at service startup.
        roots_config = Settings(yandex_disk_root=args.disk_root, yandex_training_root=args.training_root,
                                yandex_exchange_root=args.exchange_root, yandex_spam_root=args.spam_root)
        try:
            finish(args.organization, old_data_dir=args.old_data_dir, roots={
                "photo_root": roots_config.yandex_disk_root, "training_root": roots_config.training_folder,
                "exchange_root": roots_config.exchange_folder, "spam_root": roots_config.spam_folder,
            })
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print("Данные проверены. Организация приостановлена: проверьте её в кабинете владельца и возобновите работу.")
    elif args.command == "migrate":
        from alembic.config import Config

        from alembic import command
        from app.config import settings
        from app.models import Organization
        from app.organization_context import organization_scope
        from app.organization_registry import control_session, lifecycle_lock, scope_for

        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        command.upgrade(config, "head")
        if settings().organizations_enabled:
            with lifecycle_lock(), control_session() as db:
                records = list(db.scalars(select(Organization).where(
                    Organization.status.in_(["ACTIVE", "PAUSED"]))))
                if not db.scalar(select(Organization.id).limit(1)):
                    raise SystemExit("Сначала выполните initialize-organizations; рабочие данные не изменены")
                for record in records:
                    scope = scope_for(record)
                    if not record.legacy:
                        with organization_scope(scope):
                            command.upgrade(config, "head")
                    from app.signin_directory import sync_directory
                    sync_directory(scope)
        print("Базы обновлены")
    elif args.command == "initialize-organizations":
        from app.organization_registry import bootstrap
        try:
            organization_id = bootstrap(args.owner_login, args.name, args.slug)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print("Текущая компания сохранена. Адрес: /org/" + organization_id + "/")
        print("Теперь включите ORGANIZATIONS_ENABLED=true и перезапустите сервисы.")
    elif args.command == "create-admin":
        password = getpass.getpass("Пароль (минимум 12 символов): ")
        if len(password) < 12 or password != getpass.getpass("Повторите пароль: "):
            raise SystemExit("Пароли должны совпадать и содержать минимум 12 символов")
        with Session(engine()) as db:
            if db.scalar(select(User).where(User.login == args.login.lower())):
                raise SystemExit("Пользователь уже существует")
            user = User(
                login=args.login.lower(),
                name=args.name,
                password_hash=hasher.hash(password),
                role="ADMIN_OPERATOR",
                active=True,
            )
            db.add(user)
            db.flush()
            audit(db, None, "ADMIN_BOOTSTRAPPED", "user", user.id, None, {"login": user.login})
            db.commit()
        print("Администратор создан")
    elif args.command == "subscribe":
        MaxClient().subscribe(args.url)
        print("Webhook зарегистрирован")
    elif args.command == "check-max":
        result = MaxClient().request("GET", "/me")
        print("MAX подключён, ID бота:", result.get("user_id"))


if __name__ == "__main__":
    main()
