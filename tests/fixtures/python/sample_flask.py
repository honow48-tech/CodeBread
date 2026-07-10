"""Sample Flask app used as a parser test fixture."""
from flask import Flask
import requests
from sqlalchemy import Column, Integer, String
from db import Base, db

app = Flask(__name__)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)


def fetch_remote_profile(user_id: int) -> dict:
    """Fetch a user's profile from the upstream identity service."""
    resp = requests.get(f"/profiles/{user_id}")
    return resp.json()


@app.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    user = db.session.query(User).filter_by(id=user_id).first()
    return {"id": user.id, "name": user.name}


@app.route("/users", methods=["POST"])
def create_user():
    db.session.execute("INSERT INTO users (name) VALUES (:name)")
    return {"ok": True}
