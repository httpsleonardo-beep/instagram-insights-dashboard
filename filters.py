"""Opções verificadas na interface autenticada em 21/10/2026."""
from settings import AppError

DAYS = (7, 14, 30, 90)
CONTENT_METRICS = {
    'Tudo': ['Contas com engajamento', 'Interações', 'Compartilhamentos', 'Visualizadores', 'Visualizações'],
    'Posts': ['Toques no endereço comercial', 'Comentários', 'Toques em links externos', 'Seguidores', 'Impressões', 'Curtidas', 'Interações com posts', 'Visitas ao perfil', 'Salvamentos', 'Compartilhamentos', 'Visualizadores', 'Visualizações'],
    'Reels': ['Comentários', 'Curtidas', 'Reproduções', 'Interações com reels', 'Salvamentos', 'Compartilhamentos', 'Visualizadores', 'Visualizações'],
    'Stories': ['Toques no endereço comercial', 'Toques em links externos', 'Seguidores', 'Impressões', 'Curtidas', 'Cliques no link', 'Visitas ao perfil', 'Respostas', 'Interações com stories', 'Visualizadores', 'Visualizações'],
}
CONTENT_SORTS = ['Mais recente', 'Mais alto', 'Mais baixo']
AD_STATUSES = ['Tudo', 'Rascunho', 'Ativo', 'Pausado', 'Encerrada', 'Não está em veiculação']
AD_GOALS = ['Tudo', 'Visitas ao perfil', 'Visitas ao site', 'Compras', 'Mensagens', 'Combinação de ações']
AD_SORTS = ['Mais recentes', 'Mais visualizações', 'Mais visitas ao perfil', 'Maior número de visitas ao site', 'Mais mensagens', 'Mais compras', 'Maior gasto']
AD_COLUMNS = ['Visualizações', 'Meta', 'Gasto', 'Público', 'Novos seguidores']
DEFAULT_SELECTION = {'scope': 'account', 'days': 30}

def selection(raw=None):
    raw = raw or {}
    scope = raw.get('scope', 'account')
    if scope not in ('account', 'content', 'ads'):
        raise AppError('invalid_filter', 'Aba inválida.')
    if scope == 'ads':
        # Os filtros de anúncios são aplicados ao conjunto completo já coletado.
        return {'scope': 'ads'}
    try:
        days = int(raw.get('days', 30))
    except (ValueError, TypeError):
        days = 0
    if days not in DAYS:
        raise AppError('invalid_filter', 'Escolha 7, 14, 30 ou 90 dias.')
    result = {'scope': scope, 'days': days}
    if scope == 'content':
        kind, metric, order = raw.get('type', 'Tudo'), raw.get('metric', 'Visualizações'), raw.get('order', 'Mais alto')
        if kind not in CONTENT_METRICS or metric not in CONTENT_METRICS[kind] or order not in CONTENT_SORTS:
            raise AppError('invalid_filter', 'Combinação de filtros de conteúdo inválida.')
        result.update(type=kind, metric=metric, order=order)
    return result

def catalog():
    return {'days': DAYS, 'content_metrics': CONTENT_METRICS, 'content_sorts': CONTENT_SORTS,
            'ad_statuses': AD_STATUSES, 'ad_goals': AD_GOALS, 'ad_sorts': AD_SORTS, 'ad_columns': AD_COLUMNS}

def snapshot_selection(snapshot):
    return snapshot.get('selection', {'scope': 'account', 'days': snapshot.get('period', {}).get('days', 30)})
