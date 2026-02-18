import bcrypt

def hash_password(password: str):
    pw_bytes = password.encode()
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode()

def verify_password(test_pw: str, db_hash: str):
    return bcrypt.checkpw(test_pw.encode(), db_hash.encode())