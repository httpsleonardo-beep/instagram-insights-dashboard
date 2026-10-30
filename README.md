# Instagram Insights — Streamlit Cloud

Versão atualizada em 30/10/2026. Três abas: Conta, Conteúdo e Ferramentas para anúncios. Sem as seções Histórico de coleta e Sobre os números no dashboard.

## Publicar pelo navegador

1. Extraia `instagram-insights-streamlit.zip` e abra a pasta extraída.
2. Na conta `httpsleonardo-beep` do GitHub, crie um repositório privado chamado `instagram-insights-dashboard`.
3. Use “uploading an existing file”, ou “Add file > Upload files”, e arraste o CONTEÚDO da pasta extraída. Inclua a pasta `.streamlit`. Não envie o ZIP nem uma pasta externa envolvendo todo o projeto.
4. Clique “Commit changes”. Verifique que `streamlit_app.py`, `requirements.txt` e `packages.txt` estão na raiz do repositório, e que `.streamlit/config.toml` está na subpasta `.streamlit`.
5. Acesse https://share.streamlit.io/ com sua conta. Clique “Create app”, depois “Yup, I have an app”. Se necessário, use “Deploy an app from GitHub”.
6. Repository: `httpsleonardo-beep/instagram-insights-dashboard`. Branch: `main`. Main file path: `streamlit_app.py`.
7. Em “Advanced settings”, escolha Python 3.12. No campo Secrets, preencha:

```toml
INSTAGRAM_SESSIONID = "SEU_COOKIE_SESSIONID_ATUAL"
DASHBOARD_PASSWORD = "SUA_SENHA_COM_PELO_MENOS_12_CARACTERES"
```

8. Salve e clique “Deploy”. Aguarde a instalação terminar.
9. Ao abrir o aplicativo, digite a senha definida em DASHBOARD_PASSWORD. Escolha a aba e os filtros, depois clique “Atualizar dados”.
10. Para a equipe acessar um app privado, use “Settings > Sharing” e adicione os e-mails permitidos. A senha do dashboard é uma segunda camada de acesso. O link será o endereço real mostrado pelo Streamlit, terminado em `.streamlit.app`.

O cookie pode ser copiado do `config.json` da instalação LOCAL existente, somente o valor de `sessionid`. Esse arquivo não acompanha este pacote e não deve ser enviado ao GitHub. Credenciais reais devem ser preenchidas apenas no campo Secrets do Streamlit.

O GitHub recebe código e exemplos vazios; o Streamlit recebe os segredos necessários para a coleta. Depois da publicação, a execução acontece na nuvem e não depende de deixar o PC ligado.

## Uso e filtros

- Conta: 7, 14, 30 e 90 dias, público do gráfico de visualizações e dia da semana dos horários ativos.
- Conteúdo: 7, 14, 30 e 90 dias, tipo, métricas compatíveis e ordenação.
- Anúncios: status, objetivo, ordenação, colunas e filtro local por data de término. Os resultados dos anúncios permanecem acumulados, mesmo ao filtrar datas.
- Cada aba guarda suas escolhas durante a sessão do navegador. Coletas ficam separadas por conta e combinação de filtros. Uma seleção sem dados não mostra resultados de outra seleção.
- Atualização compartilhada entre usuários, com uma coleta por vez e intervalo mínimo de dois minutos.
- Excel/JSON usam os filtros selecionados. Na aba Anúncios, o Excel inclui todas as colunas dos registros filtrados.
- Seguidores é o total atual. Horários ativos usam a janela própria `hourly_30_day`. Valores ausentes não viram zero; listas incompletas são marcadas como parciais.

## Armazenamento e sessão

O SQLite e as exportações ficam em `.runtime/`, no servidor. O armazenamento local do Community Cloud pode ser perdido quando o ambiente é recriado; este pacote não inclui banco persistente externo. Baixe as exportações que precisar guardar.

O Instagram pode recusar a sessão no servidor da nuvem ou pedir verificação. Se o app avisar que a sessão expirou, atualize INSTAGRAM_SESSIONID em Settings > Secrets e tente novamente. Abrir o dashboard com sucesso não prova que a primeira coleta autenticada funcionará; confirme-a após o deploy.

## Dependências

`requirements.txt` contém os pacotes Python. `packages.txt` instala Chromium no Linux do Streamlit. Em Windows, o coletor usa Edge; em Linux, usa o Chromium do sistema.

## Executar localmente

Python 3.12:

```text
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Para uso local, copie o exemplo de segredos para `.streamlit/secrets.toml` e preencha os valores. Nunca envie esse arquivo ao GitHub.

## Validação

16 testes locais com dados sintéticos: autenticação, proteção dos segredos, coleta concorrente, falhas, filtros independentes, isolamento de seleções e exportações. A coleta Linux dentro do Streamlit Cloud ainda depende da primeira implantação e verificação no ambiente real.

Referências oficiais:
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management
- https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app
