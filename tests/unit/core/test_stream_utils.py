"""Phase 30: ensure_consumer_group_with_reset removed from stream_utils.py.

stream_utils.py is now a deprecation stub pointing to kafka_utils.py.
Kafka consumer groups are managed by KafkaConsumerClient in kafka_utils.py.
Tests for Kafka consumer group management are in test_kafka_utils.py.
"""
