# Identidade visual do perfil

Banner e fontes mantidos. Azul/ciano: automação e ferramentas; roxo: qualidade e IA;
verde/teal: integrações e segurança. Badges, cabeçalhos e ícones usam a mesma linguagem.

O README usa imagens locais porque o GitHub não executa o JavaScript nem aplica o CSS da prévia.
As tabelas e a tipografia do conteúdo continuam sendo renderizadas pelo próprio GitHub.
O espaçamento e as bordas podem, portanto, diferir ligeiramente da prévia.

## Fontes

- Os logos técnicos vêm dos repositórios dos respectivos fornecedores.
- Os ícones de Claude Code, Codex e Antigravity vêm da biblioteca Lobe Icons. São
  reproduções, não kits oficiais dos fornecedores; Antigravity/Gemini é um rótulo personalizado.
- Os ícones de interface são Lucide 0.468.0; a licença acompanha os arquivos.
- Os badges são composições personalizadas, não identidades ou lockups oficiais.
- URLs e procedência: `assets/sources.json`. As marcas pertencem aos seus titulares.

## Atividade em código

O gráfico é um snapshot real dos **últimos seis meses de calendário, sempre incluindo
o mês atual**, parcial até a data da coleta. Em 21/10/2026, a janela é maio–outubro;
em novembro passa automaticamente a junho–novembro a cada nova coleta. A data de referência
é a de America/Sao_Paulo; as consultas de data do GitHub usam UTC.
Inclui **contagens agregadas dos repositórios pessoais públicos e privados de LL0rddd**
acessíveis à credencial, conforme solicitação do usuário. Não publica nomes, código,
mensagens de commit, títulos de PRs, URLs ou outros detalhes dos repositórios privados.

- Commits: resultados indexados pela busca do GitHub, por autor e data de autoria,
  restritos ao proprietário LL0rddd, sem filtro de visibilidade.
  Não equivalem ao número total de contribuições da conta ou a todos os commits locais.
- PRs: pull requests criados pelo usuário nos seus repositórios pessoais no período,
  públicos e privados. Organizações e repositórios de outros proprietários ficam de fora.
- Repositórios: repositórios próprios públicos e privados, sem forks, criados até o
  final de cada período; no mês atual, até a coleta. Não reconstrói mudanças históricas
  de visibilidade, exclusões ou transferências.
- Escalas independentes e a partir de zero; a ausência de atividade aparece como zero.
- JSON de contagens: `assets/activity.json`; data da coleta visível no gráfico.
- GIF com animação finita e SVG estático para preferência de movimento reduzido.
- As imagens alteradas usam nomes com hash do conteúdo em `assets/versioned/`,
  atualizados pelos geradores. Os arquivos canônicos e versões anteriores são mantidos.
  Parâmetros `?v=` não bastam: o redirecionamento de imagens raw do GitHub os descarta.
- O rodapé identifica explicitamente o mês atual como parcial; a janela nunca depende
  de meses fixos escritos manualmente. O snapshot ainda depende da execução do coletor.
- Respostas brutas da API ficam locais em `.metrics-raw/`, ignoradas pelo Git. Não há tokens nos arquivos.
- A coleta exige autenticação como LL0rddd e acesso aos repositórios privados. Falha
  sem autenticação, sem privados visíveis ou com busca incompleta; não recua silenciosamente
  para números exclusivamente públicos. Quando a API informa a contagem privada esperada,
  ela é comparada à paginação. Uma credencial restrita ainda limita a cobertura disponível.

Não há atualização agendada ou segredo novo. Para atualizar manualmente, usando uma
credencial já disponível em `GH_TOKEN` ou `GITHUB_TOKEN` (nunca escreva seu valor no comando):

```sh
python3 -m pip install -r scripts/requirements.txt
python3 scripts/refresh_activity.py
```

Para regerar os badges com as cópias locais das marcas: `python3 scripts/build_profile_assets.py`.
Use `--download` apenas quando quiser buscar novamente os assets nas fontes registradas.
