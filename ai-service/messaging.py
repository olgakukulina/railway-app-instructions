"""RabbitMQ helpers compatible with Spring Jackson2JsonMessageConverter."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

import pika

log = logging.getLogger(__name__)

TYPE_IDS = {
    "PARSED": "com.railway.gateway.domain.event.ParsedEvent",
    "GENERATING_STARTED": "com.railway.gateway.domain.event.GeneratingStartedEvent",
    "GENERATED": "com.railway.gateway.domain.event.GeneratedEvent",
    "FAILED": "com.railway.gateway.domain.event.FailedEvent",
}


def rabbit_params() -> pika.ConnectionParameters:
    return pika.ConnectionParameters(
        host=os.getenv("RABBITMQ_HOST", "localhost"),
        port=int(os.getenv("RABBITMQ_PORT", "5672")),
        virtual_host=os.getenv("RABBITMQ_VHOST", "/"),
        credentials=pika.PlainCredentials(
            os.getenv("RABBITMQ_USER", "railway"),
            os.getenv("RABBITMQ_PASSWORD", "railway_secret"),
        ),
        heartbeat=600,  # ← УВЕЛИЧЕНО с 60 до 600 (10 минут) — генерация длится долго
        blocked_connection_timeout=300,
        connection_attempts=10,
        retry_delay=2,
        socket_timeout=600,
    )


def connect_with_retry(retries: int = 30, delay: float = 2.0) -> pika.BlockingConnection:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return pika.BlockingConnection(rabbit_params())
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log.warning("RabbitMQ connect failed (%s/%s): %s", attempt, retries, exc)
            time.sleep(delay)
    raise RuntimeError(f"Cannot connect to RabbitMQ: {last_error}")


def base_event(event_type: str, task_id: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "eventType": event_type,
        "eventId": str(uuid4()),
        "correlationId": task_id,
        "taskId": task_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    payload.update(extra)
    return payload


def publish_event(channel, exchange: str, routing_key: str, event: dict[str, Any]) -> None:
    event_type = event["eventType"]
    body = json.dumps(event, ensure_ascii=False).encode("utf-8")
    properties = pika.BasicProperties(
        content_type="application/json",
        content_encoding="UTF-8",
        delivery_mode=2,
        correlation_id=str(event.get("correlationId") or event.get("taskId")),
        message_id=str(event.get("eventId")),
        headers={"__TypeId__": TYPE_IDS.get(event_type, TYPE_IDS["FAILED"])},
    )
    channel.basic_publish(
        exchange=exchange,
        routing_key=routing_key,
        body=body,
        properties=properties,
    )
    log.info("Published %s taskId=%s", event_type, event.get("taskId"))


def consume_queue(queue_name: str, handler: Callable[[dict[str, Any]], None]) -> None:

    max_reconnects = 20
    reconnect_delay = 2.0

    for attempt in range(1, max_reconnects + 1):
        connection = None
        try:
            connection = connect_with_retry()
            channel = connection.channel()

            channel.basic_qos(prefetch_count=1)

            def _on_message(ch, method, properties, body):
                try:
                    event = json.loads(body.decode("utf-8"))
                except Exception:
                    log.exception("Failed to parse message from %s", queue_name)
                    try:
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
                    except Exception:
                        log.warning("Nack failed (соединение потеряно)")
                    return

                ack_ok = False
                try:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    ack_ok = True
                except Exception:
                    log.warning(
                        "Ack failed — соединение потеряно, но сообщение будет "
                        "повторно доставлено (это нормально для этого воркера)"
                    )

                try:
                    handler(event)
                except Exception:
                    log.exception(
                        "Handler failed for %s (сообщение уже ack'нуто)",
                        queue_name,
                    )

            channel.basic_consume(queue=queue_name, on_message_callback=_on_message)
            log.info("Listening on queue %s (attempt %s/%s)", queue_name, attempt, max_reconnects)
            channel.start_consuming()

        except KeyboardInterrupt:
            log.info("Interrupted, stopping consumer")
            break
        except (pika.exceptions.StreamLostError,
                pika.exceptions.ChannelWrongStateError,
                pika.exceptions.ConnectionClosedByBroker,
                pika.exceptions.AMQPConnectionError) as e:
            log.warning(
                "RabbitMQ connection lost (attempt %s/%s): %s. Reconnecting in %.1fs...",
                attempt, max_reconnects, e, reconnect_delay
            )
            time.sleep(reconnect_delay)
            continue
        except Exception as e:
            log.exception("Fatal error in consumer, reconnecting: %s", e)
            time.sleep(reconnect_delay)
            continue
        finally:
            try:
                if connection and connection.is_open:
                    connection.close()
            except Exception:
                pass

    log.error("Consumer for %s stopped after %s attempts", queue_name, max_reconnects)