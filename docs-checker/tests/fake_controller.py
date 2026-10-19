"""A fake kagent controller: the alpha14 ``kagent.runtime.v1.TaskStoreService``.

Optimistic versions per task, a call log, the identity and session each call carried,
and the full method path of every call. The TaskStore contract test runs it in
process; the image smoke test (``tests/smoke_stack.py``) runs it as the controller
sidecar the container reaches at ``runtime.control_plane_url``. It imports neither
pytest nor any other test helper, so the sidecar needs only the runtime's packages.
"""

from __future__ import annotations

import grpc
from a2a.types import a2a_pb2
from kagent.runtime.v1 import task_store_pb2, task_store_pb2_grpc

IDENTITY_HEADER = "x-kagent-insecure-runtime-identity"
TASK_STORE_SERVICE = "kagent.runtime.v1.TaskStoreService"


class MethodLog(grpc.aio.ServerInterceptor):
    """The full method path of every call the controller received."""

    def __init__(self):
        self.methods: set[str] = set()

    async def intercept_service(self, continuation, handler_call_details):
        self.methods.add(handler_call_details.method)
        return await continuation(handler_call_details)


class FakeTaskStore(task_store_pb2_grpc.TaskStoreServiceServicer):
    """Optimistic versions per task, a call log, and the identity each call carried."""

    def __init__(self):
        self.tasks: dict[str, tuple[a2a_pb2.Task, int]] = {}
        self.log: list[tuple[str, str, int]] = []
        self.identities: set[str] = set()
        self.sessions: set[str] = set()
        self.settled: list[tuple[str, int]] = []
        self.wire = MethodLog()

    def _seen(self, context, request):
        metadata = dict(context.invocation_metadata())
        self.identities.add(metadata.get(IDENTITY_HEADER, ""))
        self.sessions.add(request.session_id)

    async def CreateTask(self, request, context):
        self._seen(context, request)
        self.tasks[request.task.id] = (request.task, 1)
        self.log.append(("create", a2a_pb2.TaskState.Name(request.task.status.state), 1))
        return task_store_pb2.TaskStoreServiceCreateTaskResponse(version=1)

    async def UpdateTask(self, request, context):
        self._seen(context, request)
        _, version = self.tasks[request.task.id]
        if request.expected_version != version:
            await context.abort(grpc.StatusCode.ABORTED, "version conflict")
        self.tasks[request.task.id] = (request.task, version + 1)
        self.log.append(("update", a2a_pb2.TaskState.Name(request.task.status.state), version + 1))
        return task_store_pb2.TaskStoreServiceUpdateTaskResponse(version=version + 1)

    async def GetTask(self, request, context):
        self._seen(context, request)
        if request.task_id not in self.tasks:
            await context.abort(grpc.StatusCode.NOT_FOUND, "no such task")
        task, version = self.tasks[request.task_id]
        return task_store_pb2.TaskStoreServiceGetTaskResponse(
            stored=task_store_pb2.StoredTask(task=task, version=version)
        )

    async def ListTasks(self, request, context):
        self._seen(context, request)
        return task_store_pb2.TaskStoreServiceListTasksResponse(result=a2a_pb2.ListTasksResponse())

    async def SettleTask(self, request, context):
        self._seen(context, request)
        self.settled.append((request.task_id, request.version))
        return task_store_pb2.TaskStoreServiceSettleTaskResponse()


async def start_controller(address: str) -> tuple[grpc.aio.Server, FakeTaskStore, int]:
    """Serve a fresh ``FakeTaskStore`` on ``address`` (``host:port``; port 0 picks one)."""
    store = FakeTaskStore()
    server = grpc.aio.server(interceptors=[store.wire])
    task_store_pb2_grpc.add_TaskStoreServiceServicer_to_server(store, server)
    port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"the fake controller could not bind {address}")
    await server.start()
    return server, store, port
