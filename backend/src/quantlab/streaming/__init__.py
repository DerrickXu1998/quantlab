"""Streaming replay: warehouse history re-published as a Kafka event stream.

``bus`` is the isolated Kafka adapter (Constitution III); ``live`` is the pure
replay logic that consumes any chronological bar stream and emits the same
event types as the batch replay engine.
"""
