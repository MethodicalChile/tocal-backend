"""API JSON para frontend Vue. Django conserva todas las reglas del monolito.

Sesión Django con cookie HttpOnly, CSRF same-origin, autorización por obra.
No se publica una interfaz Data API de Supabase en el navegador.
"""
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from functools import wraps

from django import forms as django_forms
from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.forms.models import model_to_dict
from django.http import JsonResponse, Http404, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from . import models as m, forms as f, services as s, private_storage as storage
from .access import get_obra, visible_obras, visible_modules, can_edit, require_editor
from .calculations import sales_dashboard, extras_summary, rdi_summary, photo_summary, weighted_progress
from .presentation import (obra_cards, obra_overview, obra_header, pdr_overview, checklist_sections,
    staffing_chart_data, accidents_chart_data, safety_rows, avance_tabs, activity_rows,
    payments_tiles, extras_tiles, rdi_tiles, photo_tiles, report_facts, sales_overview,
    sales_monthly_data, sales_annual_data, sales_sector_data, sales_share_data)
from .templatetags.tocal import DOC_TYPES, RUBRO_NAMES

logger = logging.getLogger(__name__)


def primitive(obj, depth=0):
    """Convertir DTOs confiables a JSON sin serializar campos sensibles de User."""
    if depth > 11:
        return None
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, (tuple, list, set)):
        return [primitive(x, depth + 1) for x in obj]
    if isinstance(obj, dict):
        return {str(k): primitive(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, m.User):
        return {"id": obj.pk, "name": obj.name, "rol": obj.rol}
    if isinstance(obj, django_forms.BaseForm):
        return form_schema(obj)
    if hasattr(obj, '_meta') and hasattr(obj, 'pk'):
        record = {field.name: primitive(getattr(obj, field.attname), depth + 1)
                  for field in obj._meta.concrete_fields if field.name != 'legacy_password'}
        # Propiedades de presentación utilizadas por las vistas originales.
        for extra in ('days_open', 'overdue', 'photo_count'):
            if extra in obj.__dict__:
                record[extra] = primitive(getattr(obj, extra), depth + 1)
        return record
    return str(obj)


def response(payload, status=200):
    return JsonResponse(primitive(payload), status=status, json_dumps_params={'ensure_ascii': False})


def input_data(request):
    if request.content_type and request.content_type.split(';')[0] == 'application/json':
        if len(request.body) > 1_000_000:
            raise ValidationError('Solicitud demasiado grande')
        try:
            payload = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            raise ValidationError('JSON inválido')
        if not isinstance(payload, dict):
            raise ValidationError('El cuerpo debe ser un objeto JSON')
        return payload
    return request.POST


def api_call(verbs=('GET',)):
    def decorator(fn):
        @wraps(fn)
        @require_http_methods(list(verbs))
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return response({"error": "Sesión requerida"}, 401)
            try:
                return fn(request, *args, **kwargs)
            except ValidationError as exc:
                return response({'error': exc.messages}, 400)
            except IntegrityError:
                logger.info('Conflicto de integridad en API', exc_info=True)
                return response({'error': 'Registro duplicado o incompatible'}, 409)
        return wrapped
    return decorator


def form_schema(form):
    fields = []
    for name, field in form.fields.items():
        widget = field.widget
        typ = ('date' if isinstance(field, django_forms.DateField)
               else 'number' if isinstance(field, (django_forms.IntegerField, django_forms.FloatField, django_forms.DecimalField))
               else 'checkbox' if isinstance(field, django_forms.BooleanField)
               else 'select' if isinstance(field, django_forms.ChoiceField)
               else 'textarea' if isinstance(widget, django_forms.Textarea)
               else 'text')
        initial = form[name].value()
        if typ == 'date' and hasattr(initial, 'isoformat'):
            initial = initial.isoformat()
        if typ == 'textarea' and isinstance(initial, list):
            initial = field.prepare_value(initial)
        fields.append({'name': name, 'label': str(field.label or name), 'type': typ,
                       'required': field.required, 'help': str(field.help_text or ''),
                       'value': primitive(initial), 'choices': [(str(k), str(v)) for k, v in field.choices]
                       if hasattr(field, 'choices') else [],
                       'errors': list(form.errors.get(name, []))})
    return {'fields': fields, 'errors': list(form.non_field_errors())}


def save_form(form, linked=None):
    if not form.is_valid():
        return response({'errors': form.errors.get_json_data(), 'form': form_schema(form)}, 400)
    with transaction.atomic():
        obj = form.save(commit=False)
        for key, val in (linked or {}).items():
            setattr(obj, key, val)
        obj.save()
    return response({'ok': True, 'record': obj})



@require_http_methods(['GET'])
def health(request):
    return response({'status': 'ok'})


@api_call()
def private_file(request, key):
    from django.utils.http import content_disposition_header
    import mimetypes
    import httpx
    from pathlib import PurePosixPath
    obj = m.Foto.objects.filter(storage_path=key).first() or m.Informe.objects.filter(pdf_path=key).first()
    if not obj:
        raise Http404
    get_obra(request.user, obj.obra_id)
    try:
        payload = storage.read_bytes(key)
    except (ValidationError, FileNotFoundError, httpx.HTTPError):
        raise Http404
    name = PurePosixPath(key).name
    output = HttpResponse(payload, content_type=mimetypes.guess_type(name)[0] or 'application/octet-stream')
    output['Content-Disposition'] = content_disposition_header(name.lower().endswith('.pdf'), name)
    output['Cache-Control'] = 'private, no-store'
    output['X-Content-Type-Options'] = 'nosniff'
    return output


@require_http_methods(['GET'])
def csrf(request):
    result = response({'csrfToken': get_token(request)})
    result['Cache-Control'] = 'private, no-store'
    return result


@require_http_methods(['POST'])
def signin(request):
    data = input_data(request)
    email, password = str(data.get('email', ''))[:254], str(data.get('password', ''))
    if not email or not password:
        return response({'error': 'Ingresa correo y contraseña'}, 400)
    user = authenticate(request, username=email, password=password)
    if user is None or not user.is_active:
        return response({'error': 'Credenciales incorrectas'}, 401)
    login(request, user)
    request.session.cycle_key()
    return response({'user': {'id': user.pk, 'name': user.name, 'email': user.email, 'role': user.rol}})


@api_call(('POST',))
def signout(request):
    logout(request)
    return response({'ok': True})


@api_call()
def session(request):
    u = request.user
    return response({'id': u.pk, 'name': u.name, 'email': u.email, 'role': u.rol,
                     'modules': visible_modules(u), 'obras': [primitive(x) for x in visible_obras(u)]})


@api_call()
def dashboard(request):
    obras = list(visible_obras(request.user))
    summaries = [s.obra_summary(o, svg=False) for o in obras]
    today = timezone.localdate()
    sales = sales_dashboard(list(m.Venta.objects.values()), today.year) if request.user.rol == 'gerencia' else None
    curves = [entry['curves'][0]['state'] for entry in summaries if entry['curves'] and entry['curves'][0]['state']]
    return response({'cards': obra_cards(summaries, s.obra_rubros(obras) if obras else {}),
                     'active': sum(o.activa for o in obras),
                     'pending': sum(x['pending'] for x in summaries),
                     'staff': sum(x['total_people'] for x in summaries),
                     'accidents': sum((x['last_staff'] or {}).get('accidentes_acum', 0) for x in summaries),
                     'average_progress': sum(x['real'] for x in curves)/len(curves) if curves else None,
                     'sales': sales, 'year': today.year})


@api_call()
def obra_summary(request, obra_id):
    obra = get_obra(request.user, obra_id)
    summary = s.obra_summary(obra, svg=False)
    late = list(m.Actividad.objects.filter(obra=obra, status='atraso', es_resumen=False)
                .order_by('orden').values_list('descripcion', flat=True))
    return response({'obra': obra, 'header': obra_header(summary), 'overview': obra_overview(summary, late),
                     'summary': {k: v for k, v in summary.items() if k not in ('photos', 'reports')},
                     'modules': visible_modules(request.user)})


@api_call()
def pdr(request, obra_id):
    obra = get_obra(request.user, obra_id)
    weeks = list(m.Semana.objects.filter(obra=obra).order_by('-numero'))
    week = (get_object_or_404(m.Semana, obra=obra, pk=request.GET['semana'])
            if request.GET.get('semana') else (weeks[0] if weeks else None))
    checks = s.checklist_for(week) if week else None
    series = s.staffing_for(obra, week)
    safety = s.monthly_safety(series)
    data = {'weeks': weeks, 'week': week, 'editable': can_edit(request.user, 'pdr'),
            'staffing': form_schema(f.DotacionForm(instance=m.Dotacion.objects.filter(semana=week).first())) if week else None,
            'checklist': checks, 'sections': checklist_sections(checks) if checks else [],
            'series': series, 'safety': safety_rows(safety), 'tiles': pdr_overview(checks, week, series),
            'staffing_chart': staffing_chart_data(series), 'accidents_chart': accidents_chart_data(safety)}
    return response(data)


@api_call(('POST',))
def new_week(request, obra_id):
    obra = get_obra(request.user, obra_id)
    require_editor(request.user, 'pdr')
    return response({'week': s.create_week(obra)}, 201)


@api_call(('POST', 'PUT'))
def staffing_save(request, obra_id, week_id):
    obra = get_obra(request.user, obra_id)
    require_editor(request.user, 'pdr')
    week = get_object_or_404(m.Semana, pk=week_id, obra=obra)
    data = input_data(request)
    form = f.DotacionForm(data, instance=m.Dotacion.objects.filter(semana=week).first())
    if not form.is_valid():
        return response({'errors': form.errors.get_json_data()}, 400)
    with transaction.atomic():
        m.Semana.objects.select_for_update().get(pk=week.pk)
        obj = form.save(commit=False)
        obj.semana = week
        obj.updated_at = timezone.now()
        obj.save()
    return response({'ok': True, 'record': obj})


@api_call(('PUT', 'POST'))
def checklist_save(request, obra_id, week_id):
    obra = get_obra(request.user, obra_id)
    require_editor(request.user, 'pdr')
    week = get_object_or_404(m.Semana, pk=week_id, obra=obra)
    data = input_data(request)
    entries = data.get('rows')
    ids = list(m.ChecklistItem.objects.filter(activo=True).values_list('pk', flat=True))
    if (not isinstance(entries, list) or len(entries) != len(ids)
            or {str(x.get('id')) for x in entries if isinstance(x, dict)} != set(ids)):
        return response({'error': 'Debe enviar exactamente todos los ítems activos'}, 400)
    for x in entries:
        if x.get('estado') not in ('cumple', 'no_cumple', 'no_aplica') or len(str(x.get('observacion') or '')) > 500:
            return response({'error': 'Estado u observación inválidos'}, 400)
    with transaction.atomic():
        m.Semana.objects.select_for_update().get(pk=week.pk)
        ev, _ = m.ChecklistEvaluacion.objects.update_or_create(
            semana=week, defaults={'evaluado_por': str(data.get('evaluado_por', request.user.name))[:120],
                                   'updated_at': timezone.now()})
        for x in entries:
            m.ChecklistRespuesta.objects.update_or_create(evaluacion=ev, item_id=x['id'],
                defaults={'estado': x['estado'], 'observacion': x.get('observacion') or ''})
    return response({'ok': True})


@api_call()
def avance(request, obra_id):
    obra = get_obra(request.user, obra_id)
    curves = s.curves_for(obra, svg=False)
    activities = list(m.Actividad.objects.filter(obra=obra).order_by('orden'))
    return response({'curves': avance_tabs(curves), 'activities': activity_rows(activities),
                     'weighted': weighted_progress(list(m.Actividad.objects.filter(obra=obra).values())),
                     'point_schema': form_schema(f.PuntoForm()),
                     'editable': can_edit(request.user, 'avance')})


@api_call(('POST', 'PUT'))
def point_save(request, obra_id, curve_id):
    obra = get_obra(request.user, obra_id)
    require_editor(request.user, 'avance')
    curve = get_object_or_404(m.Curva, obra=obra, pk=curve_id)
    data = input_data(request)
    week = data.get('semana')
    existing = m.PuntoCurva.objects.filter(curva=curve, semana=week).first() if str(week).isdigit() else None
    form = f.PuntoForm(data, instance=existing)
    return save_form(form, {'curva': curve})


RESOURCE = {
    'edp': (m.EstadoPago, f.EdpForm, 'edp'),
    'adicionales': (m.Adicional, f.AdicionalForm, 'adicionales'),
    'rdi': (m.Rdi, f.RdiForm, 'rdi'),
    'actividad': (m.Actividad, f.ActividadForm, 'avance'),
    'fotos': (m.Foto, f.FotoForm, 'fotos'),
}


def resource_meta(module):
    if module not in RESOURCE:
        raise Http404
    return RESOURCE[module]


@api_call()
def resources(request, obra_id, module):
    obra = get_obra(request.user, obra_id)
    model, formclass, permission = resource_meta(module)
    rows = model.objects.filter(obra=obra).order_by('-pk')
    if module == 'rdi' and request.GET.get('estado') in ('pendiente', 'incompleta', 'respondida'):
        rows = rows.filter(estado=request.GET['estado'])
    return response({'results': list(rows[:1000]), 'schema': form_schema(formclass()),
                     'editable': can_edit(request.user, permission)})


@api_call(('GET', 'POST', 'PUT', 'DELETE'))
def resource(request, obra_id, module, pk=None):
    obra = get_obra(request.user, obra_id)
    model, formclass, permission = resource_meta(module)
    obj = get_object_or_404(model, obra=obra, pk=pk) if pk else None
    if request.method == 'GET':
        return response({'record': obj, 'schema': form_schema(formclass(instance=obj)),
                         'editable': can_edit(request.user, permission)})
    require_editor(request.user, permission)
    if module == 'actividad' and not pk:
        raise Http404
    if request.method == 'DELETE':
        if not obj or module == 'actividad':
            raise Http404
        obj.delete()
        return response({'ok': True})
    data = input_data(request)
    form = formclass(data, instance=obj)
    return save_form(form, {'obra': obra})


@api_call()
def photos(request, obra_id):
    obra = get_obra(request.user, obra_id)
    rows = m.Foto.objects.filter(obra=obra).order_by('-fecha', '-created_at')
    etiqueta = request.GET.get('etiqueta')
    if etiqueta in dict(m.Foto._meta.get_field('etiqueta').choices):
        rows = rows.filter(etiqueta=etiqueta)
    return response({'photos': list(rows[:500]), 'editable': can_edit(request.user, 'fotos'),
                     'choices': m.Foto._meta.get_field('etiqueta').choices,
                     'upload': form_schema(f.UploadForm())})


@api_call(('POST',))
def upload_photos(request, obra_id):
    obra = get_obra(request.user, obra_id)
    require_editor(request.user, 'fotos')
    form = f.UploadForm(request.POST)
    if not form.is_valid():
        return response({'errors': form.errors.get_json_data()}, 400)
    uploaded = s.upload_photos(obra, request.user, request.FILES.getlist('fotos'), form.cleaned_data)
    return response({'created': len(uploaded)}, 201)


@api_call(('GET', 'POST'))
def reports(request, obra_id):
    obra = get_obra(request.user, obra_id)
    if request.method == 'POST':
        require_editor(request.user, 'informes')
        data = input_data(request)
        week = get_object_or_404(m.Semana, pk=data.get('semana'), obra=obra)
        previous = m.Informe.objects.filter(obra=obra).order_by('-fecha_corte').first()
        report, _ = m.Informe.objects.get_or_create(obra=obra, semana=week, defaults={
            'titulo': previous.titulo if previous else f'INFORME OBRA, {obra.nombre}',
            'fecha_corte': week.fecha_fin,
            'nota_avance': previous.nota_avance if previous else '', 'autor': request.user})
        return response({'record': report}, 201)
    rows = list(m.Informe.objects.filter(obra=obra).select_related('semana').order_by('-fecha_corte'))
    counts = s.report_photo_counts(obra, rows)
    return response({'reports': [{**primitive(row), 'photo_count': counts.get(row.pk, 0)} for row in rows],
                     'weeks': list(m.Semana.objects.filter(obra=obra).order_by('-numero')),
                     'editable': can_edit(request.user, 'informes')})


@api_call(('GET', 'PUT', 'DELETE', 'POST'))
def report_detail(request, obra_id, pk):
    obra = get_obra(request.user, obra_id)
    report = get_object_or_404(m.Informe.objects.select_related('semana'), pk=pk, obra=obra)
    if request.method == 'GET':
        batch = s.report_photos(report)
        return response({'report': report, 'schema': form_schema(f.InformeForm(instance=report)),
                         'batch': batch, 'facts': report_facts(s.obra_summary(obra, report.semana, report.fecha_corte, svg=False), batch),
                         'editable': can_edit(request.user, 'informes') and report.estado != 'emitido'})
    require_editor(request.user, 'informes')
    if request.method == 'DELETE':
        report.delete()
        return response({'ok': True})
    data = input_data(request)
    if request.method == 'PUT':
        if report.estado == 'emitido':
            return response({'error': 'Reabre antes de editar'}, 409)
        form = f.InformeForm(data, instance=report)
        return save_form(form, {'autor': request.user, 'updated_at': timezone.now()})
    action = data.get('action')
    if action == 'reopen':
        report.estado = 'borrador'
        report.updated_at = timezone.now()
        report.save(update_fields=['estado', 'updated_at'])
    elif action == 'emit':
        if report.estado == 'emitido':
            return response({'error': 'Informe ya emitido'}, 409)
        pdf = s.generate_pdf(report)
        key = f'informes/{report.pk}/informe-{report.fecha_corte}-{m.new_id()}.pdf'
        storage.write_bytes(key, pdf, 'application/pdf')
        report.pdf_path = key
        report.estado = 'emitido'
        report.emitido_at = timezone.now()
        report.autor = request.user
        report.updated_at = timezone.now()
        report.save()
    elif action == 'reset_photos':
        if report.estado == 'emitido':
            return response({'error': 'Informe emitido'}, 409)
        m.InformeFoto.objects.filter(informe=report).delete()
    elif action == 'photo':
        if report.estado == 'emitido':
            return response({'error': 'Informe emitido'}, 409)
        photo = get_object_or_404(m.Foto, pk=data.get('foto'), obra=obra)
        override = m.InformeFoto.objects.filter(informe=report, foto=photo).first()
        form = f.FotoOverrideForm(data, instance=override)
        if not form.is_valid():
            return response({'errors': form.errors.get_json_data()}, 400)
        return save_form(form, {'informe': report, 'foto': photo})
    else:
        return response({'error': 'Acción inválida'}, 400)
    return response({'ok': True, 'record': report})


@api_call()
def report_pdf(request, obra_id, pk):
    obra = get_obra(request.user, obra_id)
    report = get_object_or_404(m.Informe, pk=pk, obra=obra)
    if not report.pdf_path:
        return response({'error': 'Informe todavía no emitido'}, 404)
    try:
        payload = storage.read_bytes(report.pdf_path)
    except (FileNotFoundError, ValidationError):
        raise Http404
    output = HttpResponse(payload, content_type='application/pdf')
    output['Content-Disposition'] = f'inline; filename="informe-{report.fecha_corte}.pdf"'
    output['Cache-Control'] = 'private, no-store'
    return output


def sales_query(request):
    qs = m.Venta.objects.all()
    term = request.GET.get('q', '')[:120]
    if term:
        qs = qs.filter(Q(razon_social__icontains=term) | Q(rut_cliente__icontains=term)
                       | Q(obra__icontains=term) | Q(numero__icontains=term))
    rubro = request.GET.get('rubro', '')
    if rubro in RUBRO_NAMES:
        qs = qs.filter(rubro=rubro)
    return qs


@api_call()
def sales(request):
    require_editor(request.user, 'ventas')
    years = list(m.Venta.objects.dates('fecha', 'year').values_list('fecha__year', flat=True).distinct())
    try:
        year = int(request.GET.get('anio') or max(years, default=timezone.localdate().year))
    except ValueError:
        year = timezone.localdate().year
    year = max(1901, min(year, 9998))
    data = sales_dashboard(list(sales_query(request).values()), year, timezone.localdate())
    return response({'sales': data, 'year': year, 'years': sorted(set(years) | {year}, reverse=True),
                     'overview': sales_overview(data, year), 'monthly': sales_monthly_data(data, year),
                     'annual': sales_annual_data(data, year), 'sector': sales_sector_data(data),
                     'share': sales_share_data(data), 'rubros': list(RUBRO_NAMES.items())})


@api_call()
def sales_docs(request):
    require_editor(request.user, 'ventas')
    qs = sales_query(request).order_by('-fecha', '-numero', 'id')
    if request.GET.get('anio', '').isdigit():
        qs = qs.filter(fecha__year=int(request.GET['anio']))
    kind = request.GET.get('tipo', '')
    if kind in DOC_TYPES:
        qs = qs.filter(tipo_documento=kind)
    page = max(1, int(request.GET.get('page', '1')) if str(request.GET.get('page', '1')).isdigit() else 1)
    from django.core.paginator import Paginator
    paginator = Paginator(qs, 50)
    part = paginator.get_page(page)
    total = qs.aggregate(uf=Sum('afecto_uf'), clp=Sum('afecto'))
    return response({'results': list(part.object_list), 'page': part.number,
                     'pages': paginator.num_pages, 'count': paginator.count, 'totals': total,
                     'schema': form_schema(f.VentaForm(fetch_uf=False)),
                     'kinds': list(DOC_TYPES.items()), 'rubros': list(RUBRO_NAMES.items())})


@api_call(('GET', 'POST', 'PUT', 'DELETE'))
def sales_doc(request, pk=None):
    require_editor(request.user, 'ventas')
    obj = get_object_or_404(m.Venta, pk=pk) if pk else None
    if request.method == 'GET':
        return response({'record': obj, 'schema': form_schema(f.VentaForm(instance=obj, fetch_uf=False))})
    if request.method == 'DELETE':
        if not obj:
            raise Http404
        obj.delete()
        return response({'ok': True})
    return save_form(f.VentaForm(input_data(request), instance=obj))


@api_call(('POST',))
def sales_import(request):
    require_editor(request.user, 'ventas')
    from .sales_import import import_workbook
    file = request.FILES.get('archivo')
    if file is None or file.size > 20*1024*1024 or not file.name.lower().endswith('.xlsx'):
        return response({'error': 'Adjunta una planilla XLSX de hasta 20 MB'}, 400)
    try:
        new, updated = import_workbook(file)
    except ValidationError as exc:
        return response({'error': exc.messages}, 400)
    return response({'new': new, 'updated': updated})


@api_call()
def sales_lookup(request):
    require_editor(request.user, 'ventas')
    result = {}
    rut = request.GET.get('rut', '').upper().replace('.', '').strip()[:16]
    if rut:
        row = m.Venta.objects.filter(rut_cliente=rut).order_by('-fecha').first()
        if row:
            result.update(razon_social=row.razon_social, rubro=row.rubro)
    if request.GET.get('fecha'):
        try:
            result['uf_dia'] = s.uf_for_date(date.fromisoformat(request.GET['fecha']))
        except ValueError:
            return response({'error': 'Fecha inválida'}, 400)
    return response(result)
