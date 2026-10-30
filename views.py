"""Filtros de visualização: mesma população na tela e nas exportações."""
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from filters import AD_STATUSES, AD_GOALS, AD_SORTS
from settings import AppError
from numeric import parse_number
import re

def apply_view(snapshot, query):
    data = deepcopy(snapshot)
    if data.get('selection', {}).get('scope', 'account') == 'account':
        data['activity'] = list({(r['day'], r['hours']): r for r in data.get('activity', [])}.values())
        audience, weekday = query.get('audience','all'), query.get('weekday','Mon')
        if audience not in ('all','followers','nonfollowers') or weekday not in ('Mon','Tue','Wed','Thu','Fri','Sat','Sun'):
            raise AppError('invalid_filter','Filtro da conta inválido.')
        data['view_filters'] = {'audience': audience, 'weekday': weekday, 'scope': 'Público aplica-se somente às visualizações por conteúdo; dia aplica-se somente aos horários ativos.'}
        data['display_content'] = [{'type': row['type'], 'views': row.get('views' if audience == 'all' else 'views_' + audience), 'interactions': row.get('interactions')} for row in data.get('content', [])]
        data['display_activity'] = [r for r in data.get('activity', []) if r['day'] == weekday]
        return data
    if data.get('selection', {}).get('scope') != 'ads':
        return data
    status, goal, order = query.get('status', 'Tudo'), query.get('goal', 'Tudo'), query.get('sort', 'Mais recentes')
    days = query.get('ad_days', 'all')
    if status not in AD_STATUSES or goal not in AD_GOALS or order not in AD_SORTS or days not in ('all','7','14','30','90','custom'):
        raise AppError('invalid_filter','Filtro de anúncios inválido.')
    start = end = None
    now = datetime.now(ZoneInfo('America/Sao_Paulo')).date()
    if days == 'custom':
        try:
            start, end = datetime.fromisoformat(query.get('start','')).date(), datetime.fromisoformat(query.get('end','')).date()
        except ValueError:
            raise AppError('invalid_filter','Informe as duas datas do período.') from None
        if start > end:
            raise AppError('invalid_filter','A data inicial deve ser anterior à data final.')
    elif days != 'all':
        start, end = now - timedelta(days=int(days)-1), now
    rows = data.get('items', [])
    rows = [r for r in rows if (status == 'Tudo' or r['status'] == status) and (goal == 'Tudo' or r.get('goal_category', r['goal']) == goal)]
    if start:
        rows = [r for r in rows if r.get('end_epoch') and start <= datetime.fromtimestamp(r['end_epoch'], ZoneInfo('America/Sao_Paulo')).date() <= end]
    goal_orders = {'Mais visitas ao perfil': 'Visitas ao perfil', 'Maior número de visitas ao site': 'Visitas ao site', 'Mais mensagens': 'Mensagens', 'Mais compras': 'Compras'}
    def value(row):
        if order == 'Mais recentes': return row.get('end_epoch') or row.get('start_epoch')
        if order == 'Mais visualizações': return row.get('views')
        if order == 'Maior gasto': return parse_number(re.sub(r'^[^\d]+', '', row.get('spent') or ''))
        return row.get('goal_value') if row.get('goal_category',row.get('goal')) == goal_orders.get(order) else None
    rows.sort(key=lambda row: (value(row) is not None, value(row) or 0), reverse=True)
    data['items'] = rows
    data['view_filters'] = {'status': status, 'goal': goal, 'sort': order, 'ad_days': days, 'start': str(start) if start else None, 'end': str(end) if end else None, 'date_basis': 'Data de término do anúncio; resultados acumulados'}
    return data
