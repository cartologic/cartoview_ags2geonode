import json
from django.shortcuts import render, HttpResponse, redirect, HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from . import APP_NAME
from .tasks import import_layer_task
from .models import Task
# from celery.result import AsyncResult
import threading


@login_required
def import_layer(request):
    context = {}
    if request.method == "POST":
        task = Task.objects.create(status="In Progress")
        task.save()
        info = json.loads(request.body)
        info["owner_username"] = request.user.username
        info["task_id"] = task.id
        t = threading.Thread(target=import_layer_task, kwargs=info)
        t.setDaemon(True)
        t.start()
        data = {
            "id": task.id,
            "status": task.status,
            "result": {"msg": "Loading layer info"}
        }
        json_data = json.dumps(data)
        return HttpResponse(json_data, content_type='application/json')
    return render(request, "%s/import_layer.html" % APP_NAME, context=context)


@login_required
def import_layer_status(request):
    task_id = request.GET.get("task_id")
    task = Task.objects.get(id=task_id)
    data = {
        "status": task.status,
        "message": json.loads(task.message),
        "id": task.id,
    }
    json_data = json.dumps(data)
    return HttpResponse(json_data, content_type='application/json')
