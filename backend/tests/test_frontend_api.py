"""Run: PYTHONPATH=backend:. python -m unittest discover -s backend/tests -v.

Uses an isolated in-memory SQLite database and the real ASGI application.
No network, extra test dependencies, or production database access.
"""
import json
import unittest
import time
import uuid
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.main import app
from db.models import Player, Position, User


class AsyncSessionAdapter:
    def __init__(self, session):
        self.session = session

    def add(self, entity):
        self.session.add(entity)

    async def flush(self):
        self.session.flush()

    async def rollback(self):
        self.session.rollback()

    async def delete(self, entity):
        self.session.delete(entity)

    async def commit(self):
        self.session.commit()

    async def refresh(self, entity):
        self.session.refresh(entity)

    async def execute(self, statement):
        return self.session.execute(statement)

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def get(self, model, key):
        return self.session.get(model, key)


class FrontendAPI(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        Player.__table__.create(self.engine)
        User.__table__.create(self.engine)
        self.session = Session(self.engine)
        self.competition = uuid.uuid4()
        self.other = uuid.uuid4()
        self.players = []
        for index, position in enumerate(['GK', 'OT', 'OT', 'OT', 'OT', 'CF', 'CB', 'CF', 'CB', None]):
            player = Player(id=uuid.uuid4(), competition_id=self.competition,
                            name=f'Player {index}', real_club='Club A',
                            position=Position(position) if position else None,
                            current_cost=Decimal('7.00'))
            self.players.append(player)
        self.players.append(Player(id=uuid.uuid4(), competition_id=self.other,
                                   name='Literal % underscore_', real_club='Club B',
                                   position=Position.GK, current_cost=9))
        self.session.add_all(self.players)
        self.session.commit()

        async def isolated_db():
            yield AsyncSessionAdapter(self.session)
        app.dependency_overrides[get_db] = isolated_db

    def tearDown(self):
        app.dependency_overrides.clear()
        self.session.close()
        self.engine.dispose()

    async def request(self, path, payload=None, token=None, method=None):
        path, _, query = path.partition('?')
        messages = []
        body = json.dumps(payload).encode() if payload is not None else b''

        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}

        async def send(message):
            messages.append(message)

        await app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                   'method': method or ('POST' if payload is not None else 'GET'), 'scheme': 'http',
                   'path': path, 'raw_path': path.encode(), 'query_string': query.encode(),
                   'root_path': '', 'headers': [(b'content-type', b'application/json')] +
                   ([(b'authorization', f'Bearer {token}'.encode())] if token else []),
                   'client': ('test', 1), 'server': ('test', 80)}, receive, send)
        status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
        data = json.loads(b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body'))
        return status, data

    def lineup(self, formation='THREE_THREE', indices=None):
        indices = indices or [0, 1, 2, 3, 4, 5, 6]
        return {'formation': formation, 'active_player_ids': [str(self.players[i].id) for i in indices],
                'captain_id': str(self.players[0].id), 'competition_id': str(self.competition)}

    async def test_auth_roundtrip(self):
        credentials = {'email': 'player@example.com', 'password': 'correct-horse-123'}
        status, token = await self.request('/api/auth/register', {**credentials, 'display_name': 'Player'})
        self.assertEqual(status, 201)
        self.assertEqual(token['token_type'], 'bearer')
        status, profile = await self.request('/api/auth/me', token=token['access_token'])
        self.assertEqual(status, 200)
        self.assertEqual(profile['email'], credentials['email'])
        status, _ = await self.request('/api/auth/login', credentials)
        self.assertEqual(status, 200)
        status, _ = await self.request('/api/auth/login', {**credentials, 'password': 'wrong'})
        self.assertEqual(status, 401)
        status, _ = await self.request('/api/auth/register', {**credentials, 'display_name': 'Duplicate'})
        self.assertEqual(status, 409)
        for token in (None, 'invalid-token'):
            status, _ = await self.request('/api/auth/me', token=token)
            self.assertEqual(status, 401)

    async def test_auth_rejects_password_over_bcrypt_byte_limit(self):
        # Known issue in Claude auth commit4044304; remove expectedFailure when fixed.
        # Count UTF-8 bytes, not characters. bcrypt5 raises; bcrypt4 silently truncates.
        status, _ = await self.request('/api/auth/register', {
            'email': 'long@example.com', 'password': 'ž' * 40, 'display_name': 'Player',
        })
        self.assertEqual(status, 422)

    async def test_all_formations(self):
        for formation, indices in [('THREE_THREE', [0,1,2,3,4,5,6]),
                                   ('FOUR_TWO', [0,1,2,3,4,5,7]),
                                   ('TWO_FOUR', [0,1,2,3,4,6,8])]:
            status, body = await self.request('/api/lineups/validate', self.lineup(formation, indices))
            self.assertEqual(status, 200, body)
            self.assertTrue(body['valid'])
            self.assertEqual(body['counts']['OT'], 4)

    async def test_invalid_rosters(self):
        cases = []
        for indices in ([0,1,2,3,4,5,5], [0,1,2,3,4,5,9], [0,1,2,3,4,5,7], [10,1,2,3,4,5,6]):
            cases.append(self.lineup(indices=indices))
        for field, value in [('captain_id', str(uuid.uuid4())), ('competition_id', str(self.other)),
                             ('formation', 'INVALID'), ('active_player_ids', [str(uuid.uuid4())]*6)]:
            payload = self.lineup()
            payload[field] = value
            cases.append(payload)
        unknown = self.lineup()
        unknown['active_player_ids'][6] = str(uuid.uuid4())
        cases.append(unknown)
        for payload in cases:
            status, body = await self.request('/api/lineups/validate', payload)
            self.assertEqual(status, 422, body)

    async def test_catalog_pagination_and_filters(self):
        base = f'/api/players/catalog?competition_id={self.competition}&limit=3'
        status, first = await self.request(base)
        _, second = await self.request(base + '&offset=3')
        self.assertEqual(status, 200)
        self.assertEqual(first['total'], 10)
        self.assertEqual(len(first['items']), 3)
        self.assertFalse({p['id'] for p in first['items']} & {p['id'] for p in second['items']})
        _, repeated = await self.request(base)
        self.assertEqual(first, repeated)
        _, legacy_sort = await self.request(base + '&sort=current_cost_desc')
        self.assertEqual(first, legacy_sort)
        _, ascending = await self.request(base + '&sort=cost_asc')
        _, ascending_alias = await self.request(base + '&sort=current_cost_asc')
        self.assertEqual(ascending, ascending_alias)
        _, filtered = await self.request(base + '&position=OT&club=Club%20A&search=Player')
        self.assertEqual(filtered['total'], 4)
        _, literal = await self.request('/api/players/catalog?search=%25')
        self.assertEqual(literal['total'], 1)
        _, empty = await self.request(base + '&offset=100')
        self.assertEqual(empty['items'], [])
        self.assertEqual(empty['total'], 10)

    async def test_large_catalog_bounded_pages(self):
        self.session.bulk_insert_mappings(Player, [
            {'id': uuid.uuid4(), 'competition_id': self.competition,
             'name': f'Synthetic {index:05d}', 'real_club': f'Club {index % 20}',
             'position': Position.OT, 'current_cost': 7}
            for index in range(10000)
        ])
        self.session.commit()
        seen = set()
        durations = []
        for offset in range(0, 1000, 100):
            started = time.perf_counter()
            status, body = await self.request(
                f'/api/players/catalog?competition_id={self.competition}&limit=100&offset={offset}'
            )
            durations.append((time.perf_counter() - started) * 1000)
            self.assertEqual(status, 200)
            self.assertEqual(body['total'], 10010)
            self.assertEqual(len(body['items']), 100)
            ids = {player['id'] for player in body['items']}
            self.assertFalse(ids & seen)
            seen.update(ids)
        print(f'\nSQLite ASGI catalog: 10,010 rows, 10 pages, max {max(durations):.2f} ms; '
              'single-process synthetic check, not production capacity.')

    async def test_facets_and_request_limits(self):
        status, data = await self.request(f'/api/players/facets?competition_id={self.competition}')
        self.assertEqual(status, 200)
        self.assertEqual(data['clubs'], ['Club A'])
        self.assertEqual(set(data['positions']), {'GK', 'OT', 'CF', 'CB'})
        _, empty = await self.request(f'/api/players/facets?competition_id={uuid.uuid4()}')
        self.assertEqual(empty['clubs'], [])
        self.assertEqual(set(empty['positions']), {'GK', 'OT', 'CF', 'CB'})
        for query in ['limit=0', 'limit=101', 'offset=-1', 'position=XX', 'sort=invalid', 'search='+'a'*101]:
            status, _ = await self.request('/api/players/catalog?' + query)
            self.assertEqual(status, 422)
        status, _ = await self.request(f'/api/matchdays/{uuid.uuid4()}/top-performers?limit=101')
        self.assertEqual(status, 422)


if __name__ == '__main__':
    unittest.main()
