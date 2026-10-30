# Validação — 30/10/2026

- Coletor e filtros atualizados a partir da versão local validada em 21–22/10/2026.
- Navegador adaptado para Chromium Linux via packages.txt; Edge continua disponível em Windows.
- Três abas na interface Streamlit; métricas por tipo; estado independente por aba; histórico e Sobre os números removidos da tela.
- 16 testes locais passaram, usando credenciais e dados sintéticos.
- Login permanece obrigatório; erro de segredo e mudança de conta impedem acesso aos dados.
- A seleção de conta/aba/período é verificada antes de salvar; filtros de anúncios se aplicam à tela e aos downloads.
- Cookie privado verificado como ausente dos arquivos do pacote, nas formas codificada e decodificada.
- Dependências Streamlit 1.65.0, Playwright 1.63.0 e pandas 3.0.6 verificadas no PyPI.
- Não houve upload ao GitHub nem deploy no Streamlit nesta preparação. Não houve teste da coleta autenticada dentro de um servidor Linux do Community Cloud.
- A versão local Windows e seu executável permanecem separados deste pacote.
