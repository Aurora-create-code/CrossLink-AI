"""Foundation contracts; in-memory DBs avoid touching live project records."""
import asyncio
from dataclasses import replace
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import database
from app.main import create_app
from app.config import Settings
from app.adapters.legacy import from_legacy_file
from app.adapters.thingo import ModelRequest, ThingoAdapter, ThingoNotReady


class FoundationTests(unittest.TestCase):
    def test_health_reports_config_without_secrets(self):
        settings = Settings(thingo_api_key='test-secret-never-expose')
        with patch('app.database.health', return_value={'status': 'ok', 'schema_version': 1}):
            response = TestClient(create_app(settings)).get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['thingo']['configuration_status'], 'incomplete')
        self.assertNotIn(settings.thingo_api_key, response.text)

    def test_database_failure_returns_503(self):
        with patch('app.database.health', side_effect=sqlite3.OperationalError('private path')):
            response = TestClient(create_app(Settings())).get('/api/health')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private path', response.text)

    def test_relations_require_existing_objects_and_valid_confidence(self):
        with sqlite3.connect(':memory:') as db:
            db.execute('PRAGMA foreign_keys = ON')
            db.executescript(database.SCHEMA)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO relations(id,source_id,target_id,relation_type,confidence) VALUES ('r','missing','also-missing','analogy',0.8)")
            db.execute("INSERT INTO data_objects(id,name,domain,object_type) VALUES ('a','a','energy','concept'),('b','b','health','concept')")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO relations(id,source_id,target_id,relation_type,confidence) VALUES ('r','a','b','analogy',1.5)")
            db.execute("INSERT INTO relations(id,source_id,target_id,relation_type,confidence) VALUES ('r','a','b','analogy',0.8)")
            self.assertEqual(db.execute('SELECT COUNT(*) FROM relations').fetchone()[0], 1)

    def test_legacy_contract_mapping(self):
        data = from_legacy_file({'filename':'paper.pdf','fileUrl':'/files/1','fileSize':'42'}, contract='data_file')
        message = from_legacy_file({'fileName':'paper.pdf','messageFileURL':'/files/1','fileSize':42}, contract='message')
        self.assertEqual(data, message)
        self.assertEqual(data.size_bytes, 42)
        with self.assertRaises(KeyError):
            from_legacy_file({'filename':'paper.pdf','fileUrl':'/files/1'}, contract='message')

    def test_thingo_is_explicitly_unimplemented(self):
        adapter = ThingoAdapter(Settings())
        self.assertEqual(adapter.configuration_status()['configuration_status'], 'not_configured')
        with self.assertRaises(ThingoNotReady):
            asyncio.run(adapter.generate(ModelRequest('instruction', 'context')))
        configured = replace(Settings(), thingo_endpoint='https://example.invalid/documented-endpoint', thingo_model='test-only', thingo_api_key='test-only', thingo_protocol='test-only')
        status = ThingoAdapter(configured).configuration_status()
        self.assertEqual(status['configuration_status'], 'configured_unverified')
        self.assertFalse(status['protocol_implemented'])
        self.assertFalse(status['connectivity_verified'])
        invalid = ThingoAdapter(replace(configured, thingo_endpoint='not-a-url')).configuration_status()
        self.assertEqual(invalid['configuration_status'], 'incomplete')


if __name__ == '__main__':
    unittest.main()
