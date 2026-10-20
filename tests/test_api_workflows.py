"""HTTP clients can safely edit and dispose conflicts using inspected revisions."""
import httpx
import pytest
from starlette.applications import Starlette

from remind.api import routes
from remind.file_store import FileMemoryStore
from remind.interface import MemoryInterface
from remind.models import Conflict
from remind.operations import record_revision
from remind.providers.deterministic import DeterministicEmbedding


@pytest.mark.asyncio
async def test_http_revision_conflict_and_dismissal(tmp_path, monkeypatch):
    store = FileMemoryStore(tmp_path / 'memory')
    memory = MemoryInterface(DeterministicEmbedding(), store=store)
    async def current(_):
        return memory, None
    monkeypatch.setattr(routes, '_get_memory_from_request', current)
    app = Starlette(routes=routes.api_routes)
    try:
        captured = await memory.remember('Original content')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            path = '/api/v1/episodes/' + captured.episode_id
            inspected = (await client.get(path)).json()
            revision = inspected['revision']
            assert (await client.patch(path, json={'content':'Updated content'}, headers={'If-Match':revision})).status_code == 200
            stale = await client.patch(path, json={'content':'Stale content'}, headers={'If-Match':revision})
            assert stale.status_code == 409
            assert memory.store.get_episode(captured.episode_id).content == 'Updated content'
            first = await memory.remember('TTL is 100 seconds', episode_type='fact')
            second = await memory.remember('TTL is 200 seconds', episode_type='fact')
            conflict = Conflict(fact_a_id=first.fact_id, fact_b_id=second.fact_id)
            store.add_conflict(conflict)
            response = await client.post('/api/v1/conflicts/'+conflict.id+'/dismiss', json={'resolved_by':'reviewer'},
                                         headers={'If-Match':record_revision(store, conflict.id)})
            assert response.status_code == 200, response.text
            assert store.get_conflict(conflict.id).status == 'dismissed'
            assert store.get_conflict(conflict.id).resolved_by == 'reviewer'
    finally:
        store.engine.dispose()
