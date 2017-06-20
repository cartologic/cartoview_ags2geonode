from django.db import models

class Task(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=50, null=True, blank=True)
    message = models.TextField(null=True, blank=True)
