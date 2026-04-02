"""Copilot-compatible subclasses for the OpenAI Responses API.

GitHub Copilot's Responses API streaming emits a *different* ``item_id`` on
each ``ResponseFunctionCallArgumentsDeltaEvent``, instead of reusing the
``item.id`` from the original ``ResponseOutputItemAddedEvent``.  This causes
pydantic-ai's parts manager to create orphan deltas that never merge with the
original ``ToolCallPart``, leaving it with empty arguments.

The classes below work around this by tracking the ``output_index`` →
``vendor_part_id`` mapping established during ``ResponseOutputItemAddedEvent``
and looking up the correct ID for subsequent delta events.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from openai.types import responses
from pydantic_ai.messages import ModelResponseStreamEvent
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import (
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
    OpenAIResponsesStreamedResponse,
)


@dataclass
class CopilotResponsesStreamedResponse(OpenAIResponsesStreamedResponse):
    """Streamed response that fixes Copilot's per-delta item_id mismatch."""

    _output_index_to_vendor_id: dict[int, str] = field(default_factory=dict, init=False)

    async def _get_event_iterator(self) -> AsyncIterator[ModelResponseStreamEvent]:
        """Override to fix item_id mapping for function call argument deltas.

        Copilot uses a different item_id on each argument delta event, so we
        wrap the raw stream to replace them with the original item.id before
        the parent processes them.
        """
        original_response = self._response
        self._response = self._patch_stream(original_response)
        async for event in super()._get_event_iterator():
            yield event

    async def _patch_stream(self, stream):
        """Wrap the raw SSE stream to fix item_id on argument delta events."""
        async for chunk in stream:
            if isinstance(chunk, responses.ResponseOutputItemAddedEvent):
                if isinstance(chunk.item, responses.ResponseFunctionToolCall):
                    self._output_index_to_vendor_id[chunk.output_index] = chunk.item.id

            elif isinstance(chunk, responses.ResponseFunctionCallArgumentsDeltaEvent):
                vendor_id = self._output_index_to_vendor_id.get(chunk.output_index)
                if vendor_id and chunk.item_id != vendor_id:
                    chunk = type(chunk).model_construct(
                        delta=chunk.delta,
                        item_id=vendor_id,
                        output_index=chunk.output_index,
                        sequence_number=chunk.sequence_number,
                        type=chunk.type,
                    )

            yield chunk


class CopilotResponsesModel(OpenAIResponsesModel):
    """OpenAI Responses model with Copilot streaming fixes."""

    async def _process_streamed_response(
        self,
        response,
        model_settings: OpenAIResponsesModelSettings,
        model_request_parameters: ModelRequestParameters,
    ) -> CopilotResponsesStreamedResponse:
        from pydantic_ai._utils import PeekableAsyncStream, number_to_datetime

        peekable_response = PeekableAsyncStream(response)
        first_chunk = await peekable_response.peek()

        assert isinstance(first_chunk, responses.ResponseCreatedEvent)
        return CopilotResponsesStreamedResponse(
            model_request_parameters=model_request_parameters,
            _model_name=first_chunk.response.model,
            _model_settings=model_settings,
            _response=peekable_response,
            _provider_name=self._provider.name,
            _provider_url=self._provider.base_url,
            _provider_timestamp=number_to_datetime(first_chunk.response.created_at)
            if first_chunk.response.created_at
            else None,
        )
