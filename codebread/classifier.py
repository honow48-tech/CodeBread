"""Score-based Frontend / Backend / Database / Config classifier.

Combines framework import signatures, folder naming conventions, file
extensions/patterns, and extracted facts (routes, DB models). Ambiguous
files stay "unknown" (shown as Unclassified) rather than guessing wrong.
"""
from __future__ import annotations

import os
import re
from typing import Dict

from .models import FileInfo

FRONTEND_IMPORTS = re.compile(
    r"^(react|react-dom|next|vue|@vue|nuxt|@angular|svelte|solid-js|preact|"
    r"jquery|axios|@tanstack|redux|zustand|styled-components|@mui|antd|"
    r"tailwindcss|three|d3)($|/)", re.IGNORECASE)
BACKEND_IMPORTS = re.compile(
    r"^(express|koa|fastify|hapi|@nestjs|flask|django|fastapi|starlette|"
    r"bottle|tornado|sanic|aiohttp|gin|echo|fiber|laravel|symfony|rails|"
    r"sinatra|spring|springframework|gorilla|net/http|http\.server|"
    r"microsoft\.aspnetcore)($|/|\.)", re.IGNORECASE)
DB_IMPORTS = re.compile(
    r"^(sqlalchemy|django\.db|peewee|tortoise|pymongo|motor|redis|psycopg2?|"
    r"mysql|sqlite3|mongoose|prisma|@prisma|sequelize|typeorm|knex|pg|"
    r"mongodb|gorm|database/sql|entityframework|dapper|activerecord)"
    r"($|/|\.)", re.IGNORECASE)

FRONTEND_DIRS = {"client", "frontend", "front", "components", "pages", "views",
                 "ui", "www", "public", "static", "assets", "layouts", "hooks",
                 "styles", "templates", "screens", "widgets"}
BACKEND_DIRS = {"server", "backend", "back", "api", "routes", "controllers",
                "middleware", "services", "handlers", "endpoints", "resolvers",
                "views_api", "rest", "graphql", "app"}
DB_DIRS = {"models", "model", "db", "database", "migrations", "schema",
           "schemas", "entities", "repositories", "orm", "prisma", "sql"}

FRONTEND_EXTS = {".jsx", ".tsx", ".vue", ".svelte", ".html", ".htm",
                 ".css", ".scss", ".sass", ".less"}


def classify(info: FileInfo, raw_text: str = "") -> str:
    if info.language == "config":
        return "config"
    if info.language in ("markdown", "text"):
        return "unknown"
    if info.language == "sql":
        return "database"

    score: Dict[str, float] = {"frontend": 0.0, "backend": 0.0,
                               "database": 0.0}

    ext = os.path.splitext(info.path)[1].lower()
    if ext in FRONTEND_EXTS:
        score["frontend"] += 2.5
    if info.language in ("vue", "svelte"):
        score["frontend"] += 2.0

    parts = [p.lower() for p in info.path.split("/")[:-1]]
    for p in parts:
        if p in FRONTEND_DIRS:
            score["frontend"] += 1.5
        if p in BACKEND_DIRS:
            score["backend"] += 1.5
        if p in DB_DIRS:
            score["database"] += 2.0

    for imp in info.imports:
        if FRONTEND_IMPORTS.match(imp):
            score["frontend"] += 2.0
        if BACKEND_IMPORTS.match(imp):
            score["backend"] += 2.5
        if DB_IMPORTS.match(imp):
            score["database"] += 2.0

    # extracted facts are strong signals
    n_routes = len(info.routes) + sum(len(f.routes) for f in info.functions)
    if n_routes:
        score["backend"] += 2.0 + min(n_routes, 5) * 0.4
    if info.tables:
        score["database"] += 2.0 + min(len(info.tables), 5) * 0.6
    n_api = len(info.api_calls) + sum(len(f.api_calls) for f in info.functions)
    if n_api and score["backend"] < 1.0:
        score["frontend"] += 1.0  # things that *call* APIs lean frontend
    n_db = sum(len(f.db_refs) for f in info.functions)
    if n_db:
        score["database"] += min(n_db, 4) * 0.5
        score["backend"] += 0.5

    if raw_text and info.language in ("javascript", "typescript"):
        if re.search(r"\bdocument\.|window\.|useState\(|useEffect\(",
                     raw_text):
            score["frontend"] += 1.5
        if re.search(r"process\.env|require\(['\"]fs['\"]\)|__dirname",
                     raw_text):
            score["backend"] += 0.8

    best = max(score, key=lambda k: score[k])
    if score[best] < 1.5:
        return "unknown"
    return best
