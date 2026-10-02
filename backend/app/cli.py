import argparse
import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import hasher
from app.db import engine
from app.domain import audit
from app.integrations import MaxClient
from app.models import User


def main():
    parser = argparse.ArgumentParser(description="MAX Фото: управление сервисом")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin")
    admin.add_argument("--login", required=True)
    admin.add_argument("--name", default="Администратор")
    webhook = sub.add_parser("subscribe")
    webhook.add_argument("--url", required=True)
    sub.add_parser("check-max")
    args = parser.parse_args()
    if args.command == "create-admin":
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
