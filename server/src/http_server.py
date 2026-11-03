"""
HTTP Server Module

Flask-based HTTP server for receiving RFID card scans from input client.
Designed for Docker deployment with split architecture.
"""

import logging
from typing import Optional
from flask import Flask, request, jsonify
from datetime import datetime
from .service_manager import ServiceManager


logger = logging.getLogger(__name__)


class _QuietPollFilter(logging.Filter):
    """Drop werkzeug access lines for SUCCESSFUL client reachability polls.

    The input client polls GET /health and GET /status every ~2s to confirm it
    can reach this server; at ~75k lines/day each they rotated all other log
    history out of the 30 MB docker log within two days. Non-200 responses and
    every other request are still logged.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if ('"GET /health ' in msg or '"GET /status ' in msg) and '" 200 ' in msg:
            return False
        return True


logging.getLogger("werkzeug").addFilter(_QuietPollFilter())


def create_app(use_mock_api: bool = False) -> tuple[Flask, ServiceManager]:
    """
    Create and configure Flask application

    Args:
        use_mock_api: Use mock API client for testing

    Returns:
        Tuple of (Flask app, ServiceManager instance)
    """
    app = Flask(__name__)
    app.config['JSON_SORT_KEYS'] = False

    # Initialize service manager
    service_manager = ServiceManager(use_mock_api=use_mock_api)

    from .card_admin import create_cards_blueprint
    app.register_blueprint(create_cards_blueprint(service_manager.card_store))

    from .request_log import RequestLog
    from .config import Config
    request_log = RequestLog(Config.DATABASE_FILE)

    # Initialize IDME module (optional - won't break if disabled or missing)
    try:
        from .idme import init_idme_module, idme_bp
        idme_orchestrator = init_idme_module(service_manager)
        if idme_orchestrator:
            app.register_blueprint(idme_bp)
            logger.info("IDME module registered at /idme/*")
    except ImportError:
        logger.debug("IDME module not available (optional)")
    except Exception as e:
        logger.warning(f"IDME module failed to initialize: {e}")

    @app.route('/health', methods=['GET'])
    def health():
        """
        Health check endpoint for container orchestration

        Returns:
            200 if healthy, 503 if unhealthy
        """
        is_healthy = service_manager.health_check()

        if is_healthy:
            return jsonify({
                "status": "healthy",
                "timestamp": datetime.now().isoformat()
            }), 200
        else:
            return jsonify({
                "status": "unhealthy",
                "timestamp": datetime.now().isoformat()
            }), 503

    @app.route('/status', methods=['GET'])
    def status():
        """
        Get detailed service status

        Returns:
            Comprehensive status information
        """
        try:
            status_info = service_manager.get_status()
            return jsonify({
                "status": "ok",
                "timestamp": datetime.now().isoformat(),
                # Reader outboxes only auto-resend an ambiguous tap to a server
                # that answers resends idempotently (see request_log.py).
                "capabilities": ["card_event_id", "card_scanned_at"],
                "service": status_info
            }), 200
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500

    @app.route('/card', methods=['POST'])
    def card_scan():
        """
        Process RFID card scan from input client

        Expected JSON body:
        {
            "card_id": "1234567890",
            "temperature": 36.5  // optional
        }

        Returns:
            Attendance processing result
        """
        try:
            data = request.get_json()

            if not data:
                return jsonify({
                    "success": False,
                    "message": "Request body must be JSON"
                }), 400

            card_id = data.get('card_id')
            if not card_id:
                return jsonify({
                    "success": False,
                    "message": "Missing 'card_id' field"
                }), 400

            # Validate card_id format (10 digits)
            card_id = str(card_id).strip()
            if not (len(card_id) == 10 and card_id.isdigit()):
                return jsonify({
                    "success": False,
                    "message": f"Invalid card_id format: expected 10 digits, got '{card_id}'"
                }), 400

            # Optional temperature
            temperature = data.get('temperature')
            if temperature is not None:
                try:
                    temperature = float(temperature)
                except (ValueError, TypeError):
                    return jsonify({
                        "success": False,
                        "message": "Invalid temperature value"
                    }), 400

            # Optional reader-outbox fields (used by ATTENDANCE_MODE=local):
            # original tap time, reader identity and an idempotency key.
            scanned_at = None
            if data.get('scanned_at'):
                try:
                    from .local_attendance import _parse_scanned_at
                    scanned_at = _parse_scanned_at(data.get('scanned_at'))
                except (ValueError, TypeError):
                    return jsonify({
                        "success": False,
                        "message": "Invalid scanned_at (expected ISO-8601)"
                    }), 400
            reader_id = (str(data['reader_id'])[:64] if data.get('reader_id') else None)
            event_id = (str(data['event_id'])[:128] if data.get('event_id') else None)

            # A reader outbox resends a tap it got no answer for; answer the
            # resend from the first attempt instead of processing it twice.
            if event_id:
                state, stored = request_log.begin(event_id, card_id)
                if state == "done":
                    return jsonify(stored), 200
                if state == "busy":
                    return jsonify({"success": False, "status": "processing",
                                    "message": "Still processing this tap"}), 409

            # Process attendance
            logger.info(f"Received card scan via HTTP: {card_id[:8]}...")
            result = service_manager.process_attendance(
                card_id, temperature,
                scanned_at=scanned_at, reader_id=reader_id, event_id=event_id)
            result = {"timestamp": datetime.now().isoformat(), **result}
            if event_id:
                request_log.finish(event_id, result)
            return jsonify(result), 200

        except Exception as e:
            logger.error(f"Error processing card scan: {e}")
            return jsonify({
                "success": False,
                "message": f"Internal error: {str(e)}"
            }), 500

    @app.route('/failed', methods=['GET'])
    def failed_scans():
        """
        Get list of permanently failed scan records

        Returns:
            List of failed records with card IDs, timestamps, and error messages
        """
        try:
            records = service_manager.queue.get_failed_records()
            return jsonify({
                "status": "ok",
                "timestamp": datetime.now().isoformat(),
                "count": len(records),
                "failed_records": records
            }), 200
        except Exception as e:
            logger.error(f"Error retrieving failed records: {e}")
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500

    @app.route('/attendance/status', methods=['GET'])
    def attendance_status():
        """Local attendance authority: mode, today's events, mirror backlog."""
        return jsonify({"status": "ok", "attendance": service_manager.attendance_status()}), 200

    @app.route('/attendance/compare', methods=['GET'])
    def attendance_compare():
        """Shadow-mode verdict: local card resolution vs Datang.my, per day."""
        store = service_manager.local_attendance
        if store is None:
            return jsonify({"status": "error",
                            "message": "ATTENDANCE_MODE is 'datang'; nothing recorded"}), 409
        scan_date = request.args.get('date') or datetime.now().date().isoformat()
        try:
            datetime.strptime(scan_date, "%Y-%m-%d")
        except ValueError:
            return jsonify({"status": "error", "message": "date must be YYYY-MM-DD"}), 400
        return jsonify({"status": "ok", "compare": store.compare(scan_date)}), 200

    @app.route('/sync', methods=['POST'])
    def sync_queue():
        """
        Manually trigger queue synchronization

        Returns:
            Sync statistics
        """
        try:
            logger.info("Manual queue sync triggered via HTTP")
            stats = service_manager.sync_queue()

            return jsonify({
                "status": "ok",
                "timestamp": datetime.now().isoformat(),
                "sync_stats": stats
            }), 200

        except Exception as e:
            logger.error(f"Error syncing queue: {e}")
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 500

    return app, service_manager


def run_http_server(host: str = '0.0.0.0', port: int = 8080, use_mock_api: bool = False):
    """
    Run the HTTP server

    Args:
        host: Host to bind to (default: 0.0.0.0 for Docker)
        port: Port to listen on (default: 8080)
        use_mock_api: Use mock API client for testing
    """
    logger.info(f"Starting HTTP server on {host}:{port}...")

    app, service_manager = create_app(use_mock_api=use_mock_api)

    # Start service manager
    if not service_manager.start():
        logger.error("Failed to start service manager")
        raise RuntimeError("Service initialization failed")

    logger.info("HTTP server ready to accept card scans")
    print("\n" + "="*60)
    print("Datang Reader - HTTP Server Mode")
    print("="*60)
    print(f"Listening on http://{host}:{port}")
    print("Endpoints:")
    print(f"  POST /card     - Submit card scan")
    print(f"  GET  /health   - Health check")
    print(f"  GET  /status   - Service status")
    print(f"  GET  /failed   - List failed scan records")
    print(f"  POST /sync     - Manual queue sync")
    print(f"  GET  /idme/*   - IDME module (if enabled)")
    print("="*60 + "\n")

    try:
        # Run Flask app
        app.run(host=host, port=port, debug=False)
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        service_manager.stop()


if __name__ == '__main__':
    # For testing: python -m src.http_server
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_http_server()
