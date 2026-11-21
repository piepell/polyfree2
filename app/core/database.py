"""
SQLite Database Layer for Job & API Key Persistence
"""
import aiosqlite
import json
import structlog
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from app.core.config import settings

logger = structlog.get_logger(__name__)


def get_db_path() -> Path:
    """Get database path from settings"""
    return Path(settings.DATABASE_PATH)


async def init_db():
    """Initialize database schema"""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        # Jobs table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                quality TEXT NOT NULL,
                reconstruction_type TEXT NOT NULL,
                output_formats TEXT NOT NULL,  -- JSON array
                texture INTEGER NOT NULL,
                max_faces INTEGER,
                scale REAL,
                progress REAL DEFAULT 0.0,
                message TEXT DEFAULT '',
                current_step TEXT,
                error TEXT,
                result_files TEXT,  -- JSON object
                stats TEXT,  -- JSON object
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
        
        # API Keys table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                api_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                permissions TEXT NOT NULL,  -- JSON array
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                active INTEGER DEFAULT 1
            )
        """)
        
        # Create indexes
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at)")
        
        await db.commit()
    
    logger.info("database_initialized", db_path=str(DB_PATH))


@asynccontextmanager
async def get_db():
    """Get database connection"""
    db_path = get_db_path()
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        yield db


# Job persistence functions
async def save_job(job_data: Dict[str, Any]):
    """Save or update job in database"""
    async with get_db() as db:
        await db.execute("""
            INSERT OR REPLACE INTO jobs 
            (job_id, status, quality, reconstruction_type, output_formats, texture, 
             max_faces, scale, progress, message, current_step, error, 
             result_files, stats, created_at, updated_at, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_data["job_id"],
            job_data["status"],
            job_data["quality"],
            job_data["reconstruction_type"],
            json.dumps(job_data["output_formats"]),
            int(job_data["texture"]),
            job_data.get("max_faces"),
            job_data.get("scale"),
            job_data.get("progress", 0.0),
            job_data.get("message", ""),
            job_data.get("current_step"),
            job_data.get("error"),
            json.dumps(job_data.get("result_files", {})),
            json.dumps(job_data.get("stats", {})),
            job_data.get("created_at", datetime.utcnow().isoformat()),
            datetime.utcnow().isoformat(),
            job_data.get("started_at"),
            job_data.get("completed_at"),
        ))
        await db.commit()


async def load_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Load job from database"""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def load_all_jobs() -> List[Dict[str, Any]]:
    """Load all jobs from database"""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM jobs ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_job(job_id: str) -> bool:
    """Delete job from database"""
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
        await db.commit()
        return cursor.rowcount > 0


# API Key persistence functions
async def save_api_key(key_data: Dict[str, Any]):
    """Save API key to database"""
    async with get_db() as db:
        await db.execute("""
            INSERT OR REPLACE INTO api_keys (api_key, name, permissions, created_at, active)
            VALUES (?, ?, ?, ?, ?)
        """, (
            key_data["api_key"],
            key_data["name"],
            json.dumps(key_data["permissions"]),
            key_data["created_at"],
            int(key_data["active"]),
        ))
        await db.commit()


async def load_api_key(api_key: str) -> Optional[Dict[str, Any]]:
    """Load API key from database"""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM api_keys WHERE api_key = ? AND active = 1", (api_key,))
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None


async def load_all_api_keys() -> List[Dict[str, Any]]:
    """Load all API keys from database"""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM api_keys WHERE active = 1 ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def revoke_api_key(api_key: str) -> bool:
    """Revoke API key in database"""
    async with get_db() as db:
        cursor = await db.execute("UPDATE api_keys SET active = 0 WHERE api_key = ?", (api_key,))
        await db.commit()
        return cursor.rowcount > 0