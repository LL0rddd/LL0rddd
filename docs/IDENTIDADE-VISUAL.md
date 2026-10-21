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

O gráfico é um snapshot real dos **seis meses completos anteriores à coleta**, em UTC.
Não publica os números fictícios usados na prévia, nem nomes ou atividade de repositórios privados.

- Commits: resultados públicos indexados pela busca do GitHub, por autor e data de autoria.
  Não equivalem ao número total de contribuições da conta ou a todos os commits locais.
- PRs: pull requests públicos criados pelo usuário no período.
- Repositórios: repositórios atualmente públicos, próprios e sem forks, criados até o
  final de cada mês. Não reconstrói mudanças históricas de visibilidade, exclusões ou transferências.
- Escalas independentes e a partir de zero; a ausência de atividade aparece como zero.
- JSON de contagens: `assets/activity.json`; data da coleta visível no gráfico.
- GIF com animação finita e SVG estático para preferência de movimento reduzido.
- Respostas brutas da API ficam locais em `.metrics-raw/`, ignoradas pelo Git. Não há tokens nos arquivos.

Não há atualização agendada ou segredo novo. Para atualizar manualmente, usando uma
credencial já disponível em `GH_TOKEN` ou `GITHUB_TOKEN` (nunca escreva seu valor no comando):

```sh
python3 -m pip install -r scripts/requirements.txt
python3 scripts/refresh_activity.py
```

Para regerar os badges com as cópias locais das marcas: `python3 scripts/build_profile_assets.py`.
Use `--download` apenas quando quiser buscar novamente os assets nas fontes registradas.
