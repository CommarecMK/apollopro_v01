# extensions.py — re-exportuje db z __init__ pro zpětnou kompatibilitu ostatních modulů
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
