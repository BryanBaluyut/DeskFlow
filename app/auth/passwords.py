from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def validate_password(password: str) -> list[str]:
    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    return errors
