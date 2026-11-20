"""SQLite v1: internal records are independent of any external platform DTO."""
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 4
SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, filename TEXT NOT NULL, media_type TEXT NOT NULL,
 content_sha256 TEXT NOT NULL, storage_path TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS data_schemas (
 id TEXT PRIMARY KEY, name TEXT NOT NULL,
 definition_json TEXT NOT NULL CHECK(json_valid(definition_json)),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS document_schemas (
 document_id TEXT NOT NULL REFERENCES documents(id),
 schema_id TEXT NOT NULL REFERENCES data_schemas(id),
 PRIMARY KEY(document_id, schema_id)
);
CREATE TABLE IF NOT EXISTS data_objects (
 id TEXT PRIMARY KEY, schema_id TEXT REFERENCES data_schemas(id),
 name TEXT NOT NULL, domain TEXT NOT NULL, object_type TEXT NOT NULL,
 attributes_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(attributes_json)),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS evidence (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 locator_json TEXT NOT NULL CHECK(json_valid(locator_json)), quote TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS object_evidence (
 object_id TEXT NOT NULL REFERENCES data_objects(id),
 evidence_id TEXT NOT NULL REFERENCES evidence(id),
 PRIMARY KEY(object_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS relations (
 id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES data_objects(id),
 target_id TEXT NOT NULL REFERENCES data_objects(id), relation_type TEXT NOT NULL,
 confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
 status TEXT NOT NULL DEFAULT 'proposed' CHECK(status IN ('proposed','accepted','rejected')),
 version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS relation_evidence (
 relation_id TEXT NOT NULL REFERENCES relations(id),
 evidence_id TEXT NOT NULL REFERENCES evidence(id),
 PRIMARY KEY(relation_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
CREATE INDEX IF NOT EXISTS idx_evidence_document ON evidence(document_id);
"""


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5, factory=Connection)
    connection.execute('PRAGMA foreign_keys = ON')
    return connection


def initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1, 2, 3, SCHEMA_VERSION):
            raise RuntimeError('Unsupported database schema version')
        db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA + '\nCOMMIT;')
        # Additive, transactional migration: existing document and domain rows survive.
        db.execute('BEGIN IMMEDIATE')
        columns = {row[1] for row in db.execute('PRAGMA table_info(documents)')}
        for name, definition in {
            'source_url': 'TEXT', 'size_bytes': 'INTEGER',
            'page_count': 'INTEGER', 'extracted_page_count': 'INTEGER',
        }.items():
            if name not in columns:
                db.execute(f'ALTER TABLE documents ADD COLUMN {name} {definition}')
        db.execute('''CREATE TABLE IF NOT EXISTS document_pages (
            document_id TEXT NOT NULL REFERENCES documents(id),
            page_number INTEGER NOT NULL CHECK(page_number > 0),
            text TEXT NOT NULL, has_text INTEGER NOT NULL CHECK(has_text IN (0,1)),
            PRIMARY KEY(document_id, page_number))''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_sha256)')
        db.execute('''CREATE TABLE IF NOT EXISTS extraction_batches (
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
            fingerprint TEXT NOT NULL UNIQUE, model TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
            error TEXT, usage_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS model_calls (
            id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES extraction_batches(id),
            page_number INTEGER NOT NULL, status TEXT NOT NULL,
            result_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS knowledge_items (
            id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES extraction_batches(id),
            document_id TEXT NOT NULL, page_number INTEGER NOT NULL,
            content TEXT NOT NULL, quote TEXT NOT NULL, model TEXT NOT NULL,
            extraction_status TEXT NOT NULL CHECK(extraction_status='source_verified'),
            review_status TEXT NOT NULL DEFAULT 'pending' CHECK(review_status IN ('pending','confirmed','rejected')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(document_id,page_number) REFERENCES document_pages(document_id,page_number),
            UNIQUE(batch_id,page_number,content,quote))''')
        db.execute('''CREATE TABLE IF NOT EXISTS opportunity_batches (
            id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, model TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
            snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
            usage_json TEXT NOT NULL DEFAULT '{}', error TEXT,
            insufficiency TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS opportunity_calls (
            id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES opportunity_batches(id),
            status TEXT NOT NULL, result_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''CREATE TABLE IF NOT EXISTS opportunity_items (
            id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES opportunity_batches(id),
            payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        db.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')


def health(path: Path) -> dict:
    # mode=ro prevents a health request from silently creating a missing database.
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5, factory=Connection) as db:
        db.execute('SELECT 1 FROM relations LIMIT 1').fetchone()
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if version != SCHEMA_VERSION:
            raise RuntimeError('Database schema mismatch')
    return {'status': 'ok', 'schema_version': version}
