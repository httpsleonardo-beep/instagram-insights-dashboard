"""Interface Streamlit da versão atual: Conta, Conteúdo e Anúncios."""
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from filters import DAYS, CONTENT_METRICS, CONTENT_SORTS, AD_STATUSES, AD_GOALS, AD_SORTS, AD_COLUMNS
from cloud_runtime import account_from_session
from settings import AppError

def fmt(value):
    return 'Indisponível' if value is None else f'{value:,.0f}'.replace(',','.')

def date(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M') if value else 'Indisponível'

def epoch(value):
    return datetime.fromtimestamp(value,ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y') if value else 'Indisponível'

def choose_filters(scope):
    selected={'scope':scope};view={};visible_columns=None
    if scope!='ads':
        columns=st.columns([1,1,1.5,1] if scope=='content' else [1,1,1])
        selected['days']=columns[0].selectbox('Período',DAYS,index=2,format_func=lambda d:f'Últimos {d} dias',key=scope+'_days')
        if scope=='content':
            selected['type']=columns[1].selectbox('Tipo de conteúdo',list(CONTENT_METRICS),key='content_type')
            choices=CONTENT_METRICS[selected['type']]
            if st.session_state.get('content_metric','Visualizações') not in choices:st.session_state['content_metric']='Visualizações'
            selected['metric']=columns[2].selectbox('Métrica',choices,index=choices.index('Visualizações'),key='content_metric')
            selected['order']=columns[3].selectbox('Ordenar por',CONTENT_SORTS,index=1,key='content_order')
    else:
        columns=st.columns(4)
        view['status']=columns[0].selectbox('Status',AD_STATUSES,key='ad_status')
        view['goal']=columns[1].selectbox('Meta do anúncio',AD_GOALS,key='ad_goal')
        view['sort']=columns[2].selectbox('Ordenar por',AD_SORTS,key='ad_sort')
        view['ad_days']=columns[3].selectbox('Data de término',['all','7','14','30','90','custom'],format_func=lambda v:'Todo o histórico' if v=='all' else 'Personalizado' if v=='custom' else f'Últimos {v} dias',key='ad_days')
        if view['ad_days']=='custom':
            today=datetime.now(ZoneInfo('America/Sao_Paulo')).date()
            interval=st.date_input('Período personalizado',(today-timedelta(days=30),today),format='DD/MM/YYYY',key='ad_range')
            if len(interval)!=2:
                st.info('Selecione as datas inicial e final.');return None,None,None
            view.update(start=interval[0].isoformat(),end=interval[1].isoformat())
        st.caption('As datas filtram anúncios pelo término. Os resultados e o gasto continuam acumulados por anúncio.')
        with st.expander('Colunas exibidas'):
            visible_columns=st.multiselect('Colunas',AD_COLUMNS,default=AD_COLUMNS,key='ad_columns')
    return selected,view,visible_columns

def account_chart(data):
    columns=st.columns(3)
    for col,key in zip(columns,('reach','engaged_accounts','followers')):
        item=data['metrics'][key];col.metric(item['label'],fmt(item['value']),help=item['definition'])
    columns=st.columns(4)
    for col,key in zip(columns,('views','interactions','viewers','facebook_views')):
        item=data['metrics'][key];col.metric(item['label'],fmt(item['value']))
    st.subheader('Desempenho por conteúdo')
    left,right=st.columns(2)
    metric=left.selectbox('Métrica do comparativo',['Visualizações no Instagram','Interações'],key='account_metric')
    audience=right.selectbox('Público das visualizações',['all','followers','nonfollowers'],format_func=lambda v:{'all':'Tudo','followers':'Seguidores','nonfollowers':'Não seguidores'}[v],key='account_audience',disabled=metric=='Interações')
    field='interactions' if metric=='Interações' else 'views' if audience=='all' else 'views_'+audience
    rows=[{'Tipo':r['type'],metric:r.get(field)} for r in data['content'] if r['type'] in ('Posts','Reels','Stories')]
    available=[r for r in rows if r[metric] is not None]
    if available:st.bar_chart(pd.DataFrame(available),x='Tipo',y=metric,color='Tipo',horizontal=True)
    else:st.info('Essa métrica não está disponível nesta coleta.')
    missing=[r['Tipo'] for r in rows if r[metric] is None]
    if missing:st.caption('Indisponível: '+', '.join(missing))
    with st.expander('Ver todos os tipos de conteúdo'):
        st.dataframe(pd.DataFrame([{'Tipo':r['type'],'Visualizações':r.get('views' if audience=='all' else 'views_'+audience),'Interações':r.get('interactions')} for r in data['content']]),hide_index=True,width='stretch')
    st.subheader('Horários mais ativos')
    weekdays={'Mon':'Segunda','Tue':'Terça','Wed':'Quarta','Thu':'Quinta','Fri':'Sexta','Sat':'Sábado','Sun':'Domingo'}
    weekday=st.selectbox('Dia da semana',list(weekdays),format_func=weekdays.get,key='account_weekday')
    st.caption('Seguidores · janela própria de 30 dias do Instagram.')
    activity=[{'Horário':r['hours']+'h','Seguidores':r['value']} for r in data.get('activity',[]) if r['day']==weekday]
    if activity:st.bar_chart(pd.DataFrame(activity),x='Horário',y='Seguidores',horizontal=True,sort=False)
    else:st.info('Horários indisponíveis nesta coleta.')
    return {'audience':audience if metric!='Interações' else 'all','weekday':weekday}

def content_table(data,selected):
    rows=[]
    for item in data.get('items',[]):
        row={'Publicação':item.get('shortcode') or item['id'],'Tipo':item['type'],selected['metric']:item['value']}
        rows.append(row)
    st.subheader('Insights sobre o conteúdo')
    st.caption(f"{len(rows)} conteúdos"+(' · lista parcial' if data.get('pagination_complete') is False else ''))
    if rows:st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
    else:st.info('Nenhum conteúdo corresponde a esta seleção.')

def ads_table(data,columns):
    rows=[]
    for item in data.get('items',[]):
        row={'Anúncio':item['id'],'Término':epoch(item.get('end_epoch')),'Status':item['status']}
        all_cols={'Visualizações':item['views'],'Meta':fmt(item['goal_value'])+' · '+item['goal'],'Gasto':(item['spent'] or 'Indisponível')+(' / '+item['budget'] if item['budget'] else ''),'Público':item['audience'],'Novos seguidores':item['followers']}
        row.update({k:all_cols[k] for k in columns});rows.append(row)
    st.subheader('Gerenciar anúncios')
    st.caption(f"{len(rows)} anúncios"+(' · lista parcial' if data.get('pagination_complete') is False else ''))
    if rows:st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
    else:st.info('Nenhum anúncio corresponde aos filtros.')

def run_dashboard(runtime,account,secret_reader):
    title,logout=st.columns([6,1]);title.title('Instagram Insights')
    if logout.button('Sair',width='stretch'):
        st.session_state.pop('authorized',None);st.rerun()
    tab=st.radio('Abas',['Conta','Conteúdo','Ferramentas para anúncios'],horizontal=True,label_visibility='collapsed',key='active_tab')
    scope={'Conta':'account','Conteúdo':'content','Ferramentas para anúncios':'ads'}[tab]
    @st.fragment(run_every='5s')
    def body():
        if st.session_state.get('authorized')!=hashlib.sha256(secret_reader('DASHBOARD_PASSWORD').encode()).hexdigest():st.rerun(scope='app')
        credential=secret_reader('INSTAGRAM_SESSIONID')
        keys=['account_days','account_metric','account_audience','account_weekday','content_days','content_type','content_metric','content_order','ad_status','ad_goal','ad_sort','ad_days','ad_range','ad_columns']
        memory=st.session_state.setdefault('_filter_memory',{})
        for key in keys:
            if key not in st.session_state and key in memory:st.session_state[key]=memory[key]
        try:
            if account_from_session(credential)!=account:st.rerun(scope='app')
            selected,view,columns=choose_filters(scope)
            if selected is None:return
            state=runtime.state(selected,view)
            if st.button('Atualizar dados',type='primary',disabled=state['busy'] or state['cooldown']>0,key='refresh_'+scope):
                accepted,message=runtime.start(credential,selected)
                if not accepted:st.info(message)
                state=runtime.state(selected,view)
            if state['error']:st.error(state['error'])
            elif state['busy']:st.info(state['message'])
            else:st.caption(state['message'])
            if state['cooldown'] and not state['busy']:st.caption(f"Nova coleta disponível em {state['cooldown']} segundos.")
            data=state['snapshot']
            if data is None:
                st.info('Esta combinação ainda não foi coletada. Clique em Atualizar dados.');return
            st.caption((' @'+data['account']['username']+' · ' if data['account'].get('username') else '')+'Coletado em '+date(data['collected_at']))
            if data['period'].get('start'):st.caption('Período: '+date(data['period']['start'])+' — '+date(data['period']['end']))
            if data['status']=='partial':st.warning('Coleta parcial. Alguns dados ou páginas não foram retornados pelo Instagram.')
            if scope=='account':
                view=account_chart(data);state=runtime.state(selected,view)
            elif scope=='content':content_table(data,selected)
            else:ads_table(data,columns)
            st.divider();st.subheader('Seus dados, organizados')
            st.caption('Excel e JSON da aba e dos filtros selecionados.'+(' O Excel inclui todas as colunas dos anúncios filtrados.' if scope=='ads' else ''))
            files=state['downloads'];left,right=st.columns(2)
            left.download_button('Exportar Excel',files['excel'],files['excel_name'],'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',width='stretch',key='excel_'+scope)
            right.download_button('Exportar JSON',files['json'],files['json_name'],'application/json',width='stretch',key='json_'+scope)
        except AppError as error:st.error(str(error))
        finally:
            for key in keys:
                if key in st.session_state:memory[key]=st.session_state[key]
    body()
