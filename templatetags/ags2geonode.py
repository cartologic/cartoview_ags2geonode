from django import template

register = template.Library()


@register.filter(name='template_exists')
def template_exists(template_name):
    try:
        template.loader.get_template(template_name)
        return True
    except template.TemplateDoesNotExist:
        return False
