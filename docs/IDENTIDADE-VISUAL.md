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
Inclui **commits e PRs de autoria de LL0rddd em repositórios públicos e privados,
inclusive de outros proprietários e organizações**, acessíveis à credencial. O contador
de repositórios continua restrito aos próprios, sem forks. Não publica nomes, código,
mensagens de commit, títulos de PRs, URLs ou outros detalhes dos repositórios privados.

- Commits: resultados indexados pela busca do GitHub, por autor e data de autoria,
  sem restringir o proprietário ou a visibilidade do repositório. A busca indexa a branch
  padrão; commits apenas locais ou em branches ainda não integradas podem não aparecer.
  Não equivalem ao número total de contribuições da conta.
- PRs: pull requests criados por LL0rddd no período, abertos, fechados ou integrados,
  incluindo colaborações em repositórios de terceiros e organizações. PRs apenas revisados
  ou comentados não contam como PRs de autoria própria.
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
  de meses fixos escritos manualmente.
- Respostas brutas da API ficam em `.metrics-raw/`, ignoradas pelo Git e sem tokens.
  Na execução local, ficam preservadas na pasta do projeto com permissões 700/600. No
  runner hospedado do Actions, são temporárias e não são enviadas a logs ou artifacts
  públicos; para investigação persistente, execute a coleta local e preserve essa pasta.
- A coleta exige autenticação como LL0rddd e acesso aos repositórios privados. Falha
  sem autenticação, sem privados visíveis ou com busca incompleta; não recua silenciosamente
  para números exclusivamente públicos. Quando a API informa a contagem privada esperada,
  ela é comparada à paginação. Uma credencial restrita ainda limita a cobertura disponível.

### Atualização automática

O workflow [Atualizar atividade do perfil](../.github/workflows/refresh-activity.yml)
executa **a cada hora, no minuto 17 (UTC)**, sem depender de este computador estar ligado.
Também permite execução manual em Actions → Atualizar atividade do perfil → Run workflow
e executa quando o coletor ou o próprio workflow são atualizados na `main`.

- Secret necessário: `PROFILE_METRICS_TOKEN`, de LL0rddd, com acesso de leitura aos
  repositórios privados que devem entrar nos totais. Um token dedicado de leitura é
  preferível; uma credencial pessoal mais ampla só deve ser armazenada com autorização.
  Não coloque tokens no README, no código, nos logs nem em comandos com o valor literal.
- O `GITHUB_TOKEN` automático só alcança o repositório do workflow; ele publica as imagens,
  enquanto o secret pessoal é disponibilizado **somente ao passo de coleta**.
- Actions oficiais fixadas por SHA; nenhuma execução em PRs/forks. Apenas `README.md`,
  o snapshot agregado e as imagens de atividade são adicionados ao commit, nunca os brutos.
- Testes antes e depois da coleta; em falha, os últimos indicadores válidos permanecem.
  O bot commita apenas quando há alterações, sem `--force` e sem modificar código ou
  arquivos dos outros repositórios. Commits do bot não são de autoria de LL0rddd.
- A agenda não é tempo real: o GitHub pode atrasar execuções, e sua busca também tem
  latência de indexação. Em repositórios públicos, schedules podem ser desativados após
  60 dias sem atividade; confira Actions se o rodapé ficar desatualizado.
- Expiração/revogação da credencial e restrições de SSO/organização afetam a cobertura.
  Os totais incluem apenas o que a credencial consegue consultar; não há fallback público.

Referências: [agendamento no GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule),
[escopo do GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token),
[busca de PRs por autor](https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests#search-by-author)
e [busca de commits](https://docs.github.com/en/search-github/searching-on-github/searching-commits).

Para atualizar manualmente, usando uma credencial já disponível em `GH_TOKEN` ou
`GITHUB_TOKEN` (nunca escreva seu valor no comando):

```sh
python3 -m pip install -r scripts/requirements.txt
python3 scripts/refresh_activity.py
```

Para regerar os badges com as cópias locais das marcas: `python3 scripts/build_profile_assets.py`.
Use `--download` apenas quando quiser buscar novamente os assets nas fontes registradas.
