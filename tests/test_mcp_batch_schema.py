"""Batch schema makes fields discoverable while preserving retry payloads."""

import pytest
from fastmcp import Client

from remind import mcp_server
from remind.interface import MemoryInterface
from remind.providers.deterministic import DeterministicEmbedding
from remind.store import SQLAlchemyMemoryStore


@pytest.mark.asyncio
async def test_schema_exposes_item_types_and_source_reference():
    tool=(await mcp_server.create_mcp_server().get_tools())['remember_batch']
    item=tool.parameters['properties']['items']['items']
    assert item['required']==['content']
    fields=item['properties']
    assert fields['entities']['anyOf'][0]['type']=='array'
    assert fields['labels']['anyOf'][0]['type']=='object'
    assert 'every item' in fields['source_ref']['description']
    assert 'not a speaker' in fields['asserted_by']['description']


@pytest.mark.asyncio
async def test_pre_schema_capture_receipt_replays_through_mcp(tmp_path,monkeypatch):
    store=SQLAlchemyMemoryStore(f"sqlite:///{tmp_path/'memory.db'}")
    memory=MemoryInterface(DeterministicEmbedding(),store=store)
    async def current():
        return memory
    monkeypatch.setattr(mcp_server,'get_memory',current)
    items=[{'content':'A stable captured fact','episode_type':'fact','confidence':1,
            'metadata':None,'source_ref':'ticket:123','caller_hint':{'kept':True}}]
    try:
        # This uses the original raw-dict Python path, before the schema wrapper.
        original=await memory.remember_batch(items,idempotency_key='existing-key')
        before=store.export_data()
        async with Client(mcp_server.create_mcp_server()) as client:
            replay=await client.call_tool('remember_batch',{'items':items,'idempotency_key':'existing-key'})
        assert not replay.is_error
        assert original.results[0].episode_id in str(replay.content)
        assert store.export_data()==before
    finally:
        store.engine.dispose()
