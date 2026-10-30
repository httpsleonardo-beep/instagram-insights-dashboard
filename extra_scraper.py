"""Leituras de Conteúdo e Ferramentas para anúncios pela interface do Instagram."""
from datetime import datetime
import json
import re
import time
from urllib.parse import urlsplit, parse_qs, unquote

from filters import selection, CONTENT_METRICS, CONTENT_SORTS
from numeric import parse_number
from scraper import TZ, check_login, path_value, browser_options
from settings import AppError

AD_OPS = {'usePolarisAdToolsAllBoostAdsQuery', 'PolarisAdToolsAllBoostAdsQuery_connection', 'usePolarisAdToolsAllBoostDraftAdsQuery'}
CONTENT_INITIAL = 'PolarisInsightsMediaGridCardViewInitialQuery'

def operation(response):
    url = urlsplit(response.url)
    if url.hostname not in {'www.instagram.com', 'instagram.com'} or url.path not in {'/api/graphql', '/graphql/query'}:
        return '', {}
    params = parse_qs(response.request.post_data or url.query)
    return params.get('fb_api_req_friendly_name', [''])[0], json.loads(params.get('variables', ['{}'])[0])

def connection(payload, field):
    # Relay pagination uses a node root; initial requests use user.
    for prefix in ('data.user.', 'data.node.'):
        value = path_value(payload, prefix + field)
        if isinstance(value, dict):
            return value
    return None

def content_rows(payload):
    conn = connection(payload, 'business_manager.medias')
    if conn is None:
        return None, None
    rows = []
    for edge in conn.get('edges', []):
        node = edge.get('node') or {}
        values = path_value(node, 'inline_insights_node.metric_single_value_query.results')
        value = parse_number(values[0].get('total_value')) if isinstance(values, list) and len(values) == 1 else None
        code = node.get('shortcode')
        rows.append({'id': str(node.get('instagram_media_id') or node.get('id')), 'shortcode': code if isinstance(code, str) and re.fullmatch(r'[\w-]+', code) else None,
                     'type': {'CLIPS': 'Reels', 'STORY': 'Stories', 'FEED': 'Posts', 'CAROUSEL_CONTAINER': 'Posts'}.get(node.get('instagram_media_product_type'), node.get('instagram_media_product_type') or 'Indisponível'), 'value': value})
    return rows, (conn.get('page_info') or {}).get('has_next_page')

def ad_rows(payload, account_id, draft=False):
    conn = connection(payload, 'all_boost_draft_ads' if draft else 'all_boost_ads')
    if conn is None:
        return None, None
    nodes = conn.get('draft_ads', []) if draft else [(e.get('node') or {}).get('ad') or {} for e in conn.get('edges', [])]
    rows = []
    for ad in nodes:
        if str(ad.get('organic_media_owner_igid', account_id)) != account_id:
            continue
        metric = ad.get('metric') or {}
        goal_category = {'PRODUCT_WEBSITE_VISIT_COUNT': 'Visitas ao site', 'PRODUCT_PROFILE_VISIT_COUNT': 'Visitas ao perfil',
                         'PRODUCT_MESSAGE_COUNT': 'Mensagens', 'PRODUCT_INITIATE_CHECKOUT_COUNT': 'Compras',
                         'PRODUCT_ENGAGEMENT_COUNT': 'Combinação de ações'}.get(str(metric.get('metric_name') or '').upper(), metric.get('metric_display_name') or ad.get('destination') or 'Indisponível')
        follows, seen_groups = [], set()
        for campaign in path_value(ad, 'campaign_group.campaigns.edges') or []:
            for edge in path_value(campaign, 'node.m0_adgroups.edges') or []:
                group = edge.get('node') or {}
                if group.get('id') in seen_groups:
                    continue
                seen_groups.add(group.get('id'))
                for insight in group.get('insights') or []:
                    if insight.get('metric_name') == 'PRODUCT_FOLLOWS_COUNT':
                        follows.append(parse_number(insight.get('metric_value')))
        status_code = ad.get('boosting_status')
        # PolarisAdToolsM0Types.m0StatusFromBoostingStatus, observado em 21/10/2026.
        anomaly = ad.get('payment_anomaly_type')
        status = ('Ativo' if status_code in {'ACTIVE','PENDING','REVIEW_NEEDED','CREATING'} else
                  'Pausado' if status_code == 'PAUSED' else
                  'Encerrada' if status_code in {'FINISHED','EXTENDABLE'} else 'Não está em veiculação')
        if status_code == 'PENDING' and anomaly or status == 'Ativo' and anomaly in {'account_spend_limit_reached','ACCOUNT_SPEND_LIMIT_REACHED'}:
            status = 'Não está em veiculação'
        if draft: status = 'Rascunho'
        rows.append({'id': str(ad.get('id') or ad.get('boosted_id')), 'status': status, 'status_code': status_code,
            'goal': metric.get('metric_display_name') or ad.get('destination') or 'Indisponível',
            'goal_category': goal_category,
            'goal_value': parse_number(metric.get('metric_value')), 'destination': ad.get('destination'),
            'views': next((parse_number(m.get('metric_value')) for m in ad.get('pca_metrics') or [] if m.get('metric_name') == 'PRODUCT_VIEWS_COUNT'), None),
            'spent': ad.get('formatted_spent_budget'), 'budget': ad.get('formatted_total_budget'),
            'spent_offset': ad.get('spent_budget_with_offset'),
            'audience': ad.get('audience_name'), 'followers': sum(follows) if follows and all(v is not None for v in follows) else None,
            'start_epoch': ad.get('start_time'), 'end_epoch': ad.get('stop_time')})
    return rows, False if draft else (conn.get('page_info') or {}).get('has_next_page')

def visible(page, label):
    return page.get_by_text(label, exact=True).filter(visible=True)

def scroll_results(page):
    page.evaluate('''() => { window.scrollTo(0, document.body.scrollHeight);
      for (const el of document.querySelectorAll('div')) {
        if (el.scrollHeight > el.clientHeight + 100 && el.clientHeight > 150 && ['auto','scroll'].includes(getComputedStyle(el).overflowY)) el.scrollTop = el.scrollHeight;
      }}''')

def collect_extra(cfg, progress=lambda message: None):
    from playwright.sync_api import sync_playwright, Error as PlaywrightError
    choice = selection(cfg.get('selection'))
    secret = cfg['sessionid']; account_id = unquote(secret).split(':', 1)[0]
    if not secret or not account_id.isdigit():
        raise AppError('session_missing', 'Atualize o sessionid nos Secrets do Streamlit para coletar.')
    scope = choice['scope']
    pages, errors = [], set()
    with sync_playwright() as p:
        browser = p.chromium.launch(**browser_options(cfg))
        try:
            context = browser.new_context(locale='pt-BR', timezone_id=str(TZ), viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{'name': 'sessionid', 'value': secret, 'domain': '.instagram.com', 'path': '/', 'secure': True, 'httpOnly': True, 'sameSite': 'None'}])
            page = context.new_page(); page.set_default_timeout(cfg['timeout_seconds'] * 1000)
            def capture(response):
                try:
                    name, variables = operation(response)
                    if not (name in AD_OPS if scope == 'ads' else 'InsightsMediaGrid' in name):
                        return
                    if response.status in (401,403,429): errors.add(response.status); return
                    if response.status != 200: return
                    owner = (variables.get('query_params') or {}).get('id')
                    if scope == 'content' and owner is not None and str(owner) != account_id: return
                    payload = response.json()
                    if scope == 'ads' and owner is not None and str(path_value(payload, 'data.user.id') or path_value(payload, 'data.node.id')) != str(owner): return
                    rows, more = ad_rows(payload, account_id, 'Draft' in name) if scope == 'ads' else content_rows(payload)
                    if rows is not None:
                        safe = {key: variables[key] for key in ('timeframe','metric','media_product_type','order_by_options') if key in variables}
                        pages.append({'operation': name, 'variables': safe, 'rows': rows, 'has_next_page': more, 'draft': 'Draft' in name})
                except (ValueError, TypeError, KeyError, PlaywrightError):
                    pass
            page.on('response', capture)
            progress('Abrindo ' + ('Ferramentas para anúncios…' if scope == 'ads' else 'Insights sobre o conteúdo…'))
            page.goto(cfg['start_url'] if scope == 'ads' else 'https://www.instagram.com/accounts/insights/content/', wait_until='domcontentloaded')
            page.wait_for_timeout(2000); check_login(page)
            if visible(page,'Entendi').count(): visible(page,'Entendi').click()
            if scope == 'content':
                period = page.get_by_text(re.compile(r'^Últimos \d+ dias$')).filter(visible=True)
                period.first.wait_for()
                deadline = time.monotonic() + cfg['timeout_seconds']
                while not pages and time.monotonic() < deadline: page.wait_for_timeout(300)
                def choose(current, target):
                    if current == target: return
                    visible(page,current).first.click()
                    # Each selection waits for its own fresh request, preventing stale combinations.
                    with page.expect_response(lambda r: operation(r)[0] == CONTENT_INITIAL) as expected:
                        visible(page,target).last.click()
                    expected.value.finished()
                    page.wait_for_timeout(250)
                choose(period.first.inner_text(), f"Últimos {choice['days']} dias")
                choose('Tudo', choice['type'])
                choose('Visualizações', choice['metric'])
                choose('Mais alto', choice['order'])
                for label in (f"Últimos {choice['days']} dias", choice['type'], choice['metric'], choice['order']):
                    if not visible(page,label).count():
                        raise AppError('filter_unverified', 'O Instagram não confirmou todos os filtros. Nenhum resultado foi publicado.')
                if not pages: raise AppError('schema_changed','O Instagram não retornou a lista de conteúdo.')
                current = pages[-1]
                # Only the final selection and its following pagination can contribute rows.
                pages[:] = [current]
            else:
                visible(page, 'Gerenciar anúncios').wait_for()
            deadline = time.monotonic() + min(120, cfg['timeout_seconds'] * 2)
            quiet = 0; previous = -1
            while time.monotonic() < deadline:
                page.wait_for_timeout(800); check_login(page)
                primary = [r for r in pages if not r['draft']]
                if primary and primary[-1]['has_next_page'] is False: break
                scroll_results(page)
                quiet = quiet + 1 if len(pages) == previous else 0; previous = len(pages)
                if quiet >= 12: break
            if errors:
                raise AppError('rate_limited' if 429 in errors else 'session_expired', 'O Instagram limitou a consulta ou recusou a sessão. Tente mais tarde ou atualize o sessionid.')
            primary = [r for r in pages if not r['draft']]
            if not primary: raise AppError('schema_changed', 'A lista não foi retornada pelo Instagram. Os dados anteriores foram preservados.')
            complete = primary[-1]['has_next_page'] is False
            if scope == 'content':
                signature = primary[0]['variables']
                if any(r['variables'] and r['variables'] != signature for r in primary):
                    raise AppError('filter_conflict','O Instagram misturou filtros na paginação. Atualize novamente.')
            rows = list({r['id']: r for batch in pages for r in batch['rows']}.values())
            warnings = [] if complete else ['O Instagram não concluiu a paginação. A lista é parcial; atualize novamente para tentar carregar o restante.']
            if scope == 'ads' and not any(r['draft'] for r in pages):
                warnings.append('A consulta de rascunhos não retornou; rascunhos indisponíveis nesta coleta.')
            label = 'Acumulado por anúncio' if scope == 'ads' else f"Últimos {choice['days']} dias"
            return {'schema_version': 2, 'selection': choice, 'collected_at': datetime.now(TZ).isoformat(timespec='seconds'),
                'account': {'id': account_id}, 'period': {'days': choice.get('days'), 'label': label, 'start': None, 'end': None, 'timezone': str(TZ), 'verified': True, 'dates_verified': False,
                    'evidence': 'Seletores visíveis e resposta da consulta de conteúdo' if scope == 'content' else 'Lista de anúncios; métricas acumuladas, sem período nativo'},
                'status': 'complete' if complete and not warnings else 'partial', 'metrics': {}, 'content': [],
                'items': rows, 'warnings': warnings, 'pagination_complete': complete,
                'sources': [{'operation': r['operation'], 'filters': r['variables'], 'has_next_page': r['has_next_page']} for r in pages]}
        finally:
            if 'page' in locals():
                page.remove_listener('response', capture)
            browser.close()
