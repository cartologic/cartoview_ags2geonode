import json
from django.shortcuts import render, HttpResponse, redirect, HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from . import APP_NAME
from .tasks import import_layer_task
from celery.result import AsyncResult


@login_required
def import_layer(request):
    context = {}
    if request.method == "POST":
        info = json.loads(request.body)
        info["owner_username"] = request.user.username
        task = import_layer_task.delay(**info)
        data = {
            "id": task.id,
            "state": task.state,
            "result": {"msg": "Loading layer info"}
        }
        json_data = json.dumps(data)
        return HttpResponse(json_data, content_type='application/json')
    return render(request, "%s/import_layer.html" % APP_NAME, context=context)


@login_required
def import_layer_state(request):
    task_id = request.GET.get("task_id")
    task = AsyncResult(task_id)
    data = {
        "state": task.state,
        "result": task.result,
        "id": task.id,
    }
    json_data = json.dumps(data)
    return HttpResponse(json_data, content_type='application/json')



