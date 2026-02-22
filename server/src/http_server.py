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

            # Process attendance
            logger.info(f"Received card scan via HTTP: {card_id[:8]}...")
            result = service_manager.process_attendance(card_id, temperature)

            return jsonify({
                "timestamp": datetime.now().isoformat(),
                **result
            }), 200

        except Exception as e:
            logger.error(f"Error processing card scan: {e}")
            return jsonify({
                "success": False,
                "message": f"Internal error: {str(e)}"
            }), 500

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
