"""Internal service-to-service dispatcher.

This is the server side of :class:`apps.common.remote.RemoteServiceClient`. When
a module is extracted into its own deployment, the *new* deployment exposes this
endpoint and the core calls it instead of the local interface — with no change
at any call site.

    POST /internal/<service>/<method>/
    {"args": [...], "kwargs": {...}}
    -> {"success": true, "result": ...}

Access is restricted to callers presenting ``INTERNAL_SERVICE_TOKEN``. It is
never routed on a public listener in production — bind it to the internal mesh.
"""
import json
import logging

from decouple import config
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.common.exceptions import ZynoraError
from apps.common.registry import ServiceNotAvailable, services

logger = logging.getLogger("zynora.registry")

INTERNAL_TOKEN = config("INTERNAL_SERVICE_TOKEN", default="")


def _unauthorised():
    return JsonResponse(
        {"success": False, "error": {"code": "unauthorised", "message": "Invalid service token."}},
        status=401,
    )


@csrf_exempt
@require_POST
def dispatch(request, service_name, method):
    if not INTERNAL_TOKEN:
        return JsonResponse(
            {"success": False,
             "error": {"code": "disabled",
                       "message": "Internal RPC is disabled (no INTERNAL_SERVICE_TOKEN set)."}},
            status=503,
        )

    presented = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if presented != INTERNAL_TOKEN:
        logger.warning("rejected internal call to %s.%s", service_name, method)
        return _unauthorised()

    if method.startswith("_"):
        return JsonResponse(
            {"success": False,
             "error": {"code": "forbidden", "message": "Private methods are not callable."}},
            status=403,
        )

    try:
        interface = services.resolve(service_name)
    except ServiceNotAvailable as exc:
        return JsonResponse(
            {"success": False, "error": {"code": "not_deployed", "message": str(exc)}},
            status=404,
        )

    handler = getattr(interface, method, None)
    if not callable(handler):
        return JsonResponse(
            {"success": False,
             "error": {"code": "unknown_method",
                       "message": f"{service_name}.{method}() does not exist."}},
            status=404,
        )

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse(
            {"success": False, "error": {"code": "bad_request", "message": "Malformed JSON."}},
            status=400,
        )

    args = payload.get("args", [])
    kwargs = payload.get("kwargs", {})

    try:
        result = handler(*args, **kwargs)
    except ZynoraError as exc:
        return JsonResponse(
            {"success": False, "error": {"code": exc.code, "message": exc.message}},
            status=exc.status_code,
        )
    except TypeError as exc:
        logger.exception("bad signature for %s.%s", service_name, method)
        return JsonResponse(
            {"success": False, "error": {"code": "bad_arguments", "message": str(exc)}},
            status=400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("internal call %s.%s failed", service_name, method)
        return JsonResponse(
            {"success": False, "error": {"code": "internal_error", "message": str(exc)}},
            status=500,
        )

    return JsonResponse({"success": True, "result": result}, safe=False)
