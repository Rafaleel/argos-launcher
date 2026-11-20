# Argos Launcher: gerenciador local de jogos com estimativa de progresso por IA

> Documento de contexto para o Claude Code. Descreve o que é o projeto, as decisões já tomadas e a ordem de construção. Nome do projeto: Argos Launcher (pacote `argos`).

## 1. Visão geral

Aplicativo desktop **local e offline** para gerenciar uma biblioteca de jogos (ROMs de emulador, ISOs e jogos de PC instalados). O usuário consegue:

- escanear pastas e ter os jogos identificados e organizados automaticamente;
- clicar em **play** e abrir o jogo no emulador/executável correto;
- ver estatísticas de uso (tempo por jogo, plataforma, período, ritmo);
- ver **quanto do jogo já foi jogado (%)**, com um intervalo de confiança.

Gerenciadores assim já existem (Playnite, LaunchBox, ES-DE). O **diferencial deste projeto** é o motor de progresso: uma estimativa de % concluído obtida por **fusão de sinais** de várias fontes, com a incerteza explícita. É um projeto de aprendizado/portfólio com foco em engenharia de IA.

## 2. O problema central: "% do jogo"

- A ROM/ISO **não contém** informação de progresso; é conteúdo estático. Ela serve apenas para **identificar** o jogo (hash, serial).
- O progresso real está na **memória RAM** durante a execução e no **arquivo de save**.
- "% concluído" não é bem definido de forma universal. Cada jogo precisa de uma definição (padrão: **história principal**, modelada como uma lista ordenada de marcos).

### Fontes de sinal (da mais confiável para a menos)

| # | Sinal | Confiabilidade | Observação |
|---|---|---|---|
| 1 | Leitura de RAM do emulador | Muito alta | Exige mapa de memória por jogo (fontes: code notes do RetroAchievements, autosplitters do LiveSplit, decompilações) |
| 2 | Parse do arquivo de save | Muito alta | Formato varia por jogo |
| 3 | Conquistas (RetroAchievements, Steam) | Alta, parcial | Indica "pelo menos até aqui" |
| 4 | Screenshot classificado por modelo de visão | Média | Modelo pode errar a fase |
| 5 | Tempo jogado ÷ tempo médio para zerar | Baixa | Só empurra a estimativa. Fonte do tempo médio: IGDB (`game_time_to_beats`, dados da comunidade; confirmar campos na documentação) ou digitado à mão na primeira versão. HowLongToBeat não tem API pública oficial: não depender dele |

### Fusão de sinais (o núcleo de IA)

O progresso é uma **variável latente** estimada por um filtro bayesiano discreto exato (HMM) sobre os marcos do jogo. Com algumas dezenas de marcos em ordem, não precisa de filtro de partículas:

- **Estado:** distribuição de probabilidade sobre os marcos (não um número único).
- **Predição:** a cada intervalo de tempo jogado, a crença avança um pouco e fica mais incerta.
- **Correção:** cada sinal recebido atualiza a crença, com peso proporcional à sua confiabilidade (modelo de observação por tipo de sinal).
- **Monotonicidade:** o progresso quase nunca regride. Exceções (new game+, save antigo carregado) são tratadas como evento de reset.
- **Saída:** estimativa + intervalo de confiança (ex.: `62% ± 1` com RAM; `~40% ± 20` só com tempo).
- **Marcos:** a lista de marcos de cada jogo é escrita à mão (poucos jogos de referência no início), a partir de fontes como guias e conquistas. Cada sinal precisa de uma ligação explícita com os marcos (ex.: conquista X implica "pelo menos o marco 7"). "Conquistas ganhas ÷ total" não é progresso da história sem essa ligação.
- **Calibração:** em jogos com RAM/save como verdade, medir o erro dos outros sinais e ajustar os pesos; reutilizar esses pesos em jogos sem mapa. Ter métrica de erro e avaliação. Limite conhecido: com 1 ou 2 jogos mapeados e um único jogador, os pesos são só um ponto de partida e não generalizam; os intervalos de confiança devem refletir isso.

O sistema usa os sinais **que estiverem disponíveis** para cada jogo; nenhum é obrigatório.

## 3. Stack

| Camada | Tecnologia |
|---|---|
| Sistema operacional alvo | Linux |
| Interface | Tauri + React + TypeScript |
| Backend | Python + FastAPI (processo local) |
| Banco | SQLite (sqlite-vec para embeddings, fase final) |
| Modelos locais | Ollama (LLM e visão) |
| Fusão de sinais | numpy puro (implementar o filtro à mão) |

**Decisão:** começar como aplicação web local (FastAPI + React no navegador). Empacotar com Tauri só depois que as fases 1 e 2 estiverem funcionando. **Feito:** o app desktop (Tauri 2, `frontend/src-tauri`) abre a interface e inicia o backend sozinho na porta 8765 (usa `backend/.venv` ou `uv run`); ao fechar a janela, o backend é encerrado com SIGTERM. Se já houver um backend nessa porta, ele é reaproveitado (um segundo backend fecharia as sessões abertas do primeiro). Limite: o backend roda a partir do código-fonte; um pacote instalável precisa do backend embutido como sidecar, o que ainda não foi feito.

### Como rodar

- App desktop: `cd frontend && pnpm tauri dev` (desenvolvimento) ou `pnpm tauri build --no-bundle` e abrir `src-tauri/target/release/argos-launcher`.
- No navegador: `cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8765` e `cd frontend && pnpm dev` (http://127.0.0.1:5173).

### Interface

O Acervo destaca a última sessão disponível. Clique numa capa ou use as setas para folhear os títulos visíveis em grade ou lista. O destaque acompanha a seleção e apresenta cada mídia como caixa e disco, cartucho, caixa portátil ou capa simples. O tema escuro usa superfícies foscas e vermelho profundo. O claro usa marfim e retícula vermelha. A escolha fica salva localmente.

Discos da mesma edição e plataforma aparecem juntos na estante. A ficha permite escolher o disco, ver o tempo dele e jogá-lo. O indicador de conquistas aparece após sincronização. Controles de vínculo, vídeo e texturas abrem sob demanda. Arquivos não identificados têm filtro próprio.

Atividade abre com o diário, que registra cada sessão na data local em que começou. O diário agrupa as sessões de cada título no mesmo dia, incluindo os vários discos da edição, e permite folhear dias anteriores. Os gráficos abaixo continuam dividindo o tempo à meia-noite. Oficina reúne emuladores, controles e pastas. No desktop, pastas e pacotes usam o seletor nativo. No navegador, o usuário informa o caminho.

### Jogos em vários discos

Entradas do DAT que só diferem por "(Disc N)" (mesma plataforma e mesmo título) formam uma edição (`backend/app/editions.py`, igual a `frontend/src/collection.ts`). Ao jogar um disco no Dolphin, o Argos grava `playlists/<id>.m3u` ao lado do banco, com o disco escolhido primeiro e os outros depois, e liga `Core.AutoDiscChange`: quando o jogo pede o outro disco, o Dolphin troca sozinho para o próximo da lista (lido em `DVDInterface.cpp` e `Boot.cpp`). O sandbox do Flatpak lê essa pasta e as ISOs (verificado). Não verificado: a troca em si, que só acontece no fim do disco 1. Um disco faltando faz o jogo abrir só com o escolhido; outro disco da mesma edição aberto impede abrir um segundo Dolphin. O vínculo com o RetroAchievements vale para todos os discos, e uma sincronização busca o site uma vez por edição e grava o resultado em cada disco.

### Capas

Vêm dos repositórios libretro-thumbnails no GitHub (`raw.githubusercontent.com/libretro-thumbnails/<plataforma>/master/Named_Boxarts/<título>.png`), que usam os mesmos nomes dos DATs; para jogos em vários discos também é tentado o nome sem "(Disc N)". Baixadas uma vez e guardadas ao lado do banco (`covers/`). Só a plataforma e o título são enviados. O endereço `thumbnails.libretro.com` devolveu 404 para todos os jogos testados, por isso não é usado.

## 4. Arquitetura

```
frontend (React)  ──HTTP──>  backend (FastAPI)
                               ├── scanner      identifica arquivos por hash
                               ├── launcher     abre emulador/executável e monitora o processo
                               ├── sessions     registra início, fim e duração
                               ├── collectors   geram sinais durante a sessão
                               ├── progress     filtro de fusão -> estimativa
                               ├── stats        agregações para a interface
                               └── db           SQLite
```

### Módulos

1. **Scanner e identificação.** Varre pastas configuradas, calcula hash (CRC32/SHA-1) de cada arquivo e compara com arquivos DAT do No-Intro e Redump para identificar o jogo exato. Busca capa e metadados (IGDB ou ScreenScraper). Jogos de PC são adicionados apontando para o executável.
   - **Cabeçalhos:** os DATs do No-Intro para NES hasheiam a ROM sem o cabeçalho de 16 bytes; o scanner tira o cabeçalho antes do hash nesses sistemas. Outros sistemas com cabeçalho (SNES, Lynx, A7800) precisam ser conferidos um a um.
   - **Formatos:** o Redump hasheia as faixas cruas (bin/cue, iso). CHD, RVZ e zip não batem com o hash do DAT. Na fase 1, aceitar só imagens cruas e mostrar "não identificado" para o resto, dizendo o motivo.
   - **Cache:** guardar o hash por caminho, tamanho e data de modificação; só recalcular quando algum deles mudar (ISOs de vários GB).
2. **Launcher.** Cada plataforma tem um perfil de emulador com template de comando guardado como **lista de argumentos** (ex.: `["pcsx2", "{rom}", "--fullscreen"]`). O processo é aberto sem shell, para que um nome de arquivo com `"` ou `$(...)` não execute comandos.
3. **Sessões.** A sessão começa ao abrir o jogo e dura enquanto existir qualquer processo vivo na mesma **sessão do Linux** (o launcher usa `start_new_session`, então o id da sessão é o pid lançado). Isso cobre wrappers que saem na hora (scripts, Flatpak; testado com `flatpak run --command=sleep`). Um batimento é gravado a cada 15 s. Se o relógio pular mais de 60 s (suspensão), a sessão fecha no último instante visto e outra começa, então a suspensão não conta como tempo jogado. Ao iniciar o app, sessões abertas por uma queda são fechadas no último batimento; elas não são retomadas. O mesmo jogo não abre duas vezes. Fora do alcance: launchers que entregam a um programa já aberto (Steam) ou que chamam `setsid` escapam do rastreio e a sessão dura cerca de 0 s.
4. **Coletores.** Rodam durante a sessão e gravam eventos na tabela `signals`. Interface comum (`Collector`) para que novos sinais sejam plugáveis.
5. **Motor de progresso.** Consome `signals` e grava `progress_estimates`.
6. **Estatísticas.** Tempo por jogo/plataforma/semana, ritmo de progresso, jogos abandonados, previsão de horas restantes.

### Modelo de dados (SQLite)

- `settings` — chave, valor (JSON): pastas de ROMs e de DATs
- `games` — id, chave (única), título, plataforma (nome do cabeçalho do DAT), identificado, capa
- `files` — id, game_id, caminho, tamanho, mtime_ns, crc32, sha1, crc32_nohdr, sha1_nohdr (o hash guardado serve de cache do scan)
- `emulators` — id, plataforma, caminho do executável, template de comando
- `sessions` — id, game_id, início, fim, último batimento (a duração é calculada como fim − início na consulta, não guardada)
- `milestones` — id, game_id, ordem, nome (marcos da história principal, escritos à mão)
- `signals` — id, game_id, session_id (**pode ser nulo**: conquistas e saves podem chegar fora de uma sessão), tipo, payload (JSON), timestamp
- `progress_estimates` — id, game_id, timestamp, média, limite inferior, limite superior

**Regra:** os sinais brutos são sempre guardados. Se o filtro mudar, o histórico inteiro pode ser reprocessado.

### Limites conhecidos das fases 1 e 2

- Uma subpasta desmontada dentro de uma pasta configurada saudável perde as linhas dela (voltam quando a pasta volta, com novo hash).
- Um jogo com histórico de sessões nunca é apagado pelo scan; sem arquivos ele some da lista (sem botão Jogar), mas o tempo continua nas estatísticas.
- Uma atualização de DAT que renomeia o título dá ao jogo um novo id; o histórico fica no nome antigo.
- Se o app cair com o emulador aberto, o tempo depois do último batimento (até 15 s) se perde, e o que seguir rodando não é retomado.
- Se o relógio do sistema voltar no meio de uma sessão, a contagem congela até ele alcançar o último valor (tempo se perde, nunca é inventado).
- Vários workers do uvicorn, ou iniciar o backend uma segunda vez com um jogo aberto, não são suportados: o `close_orphans` do segundo fecha as sessões abertas do primeiro (ficam cortadas no último batimento).
- Ainda fora do escopo: ritmo de progresso, jogos abandonados e previsão de horas restantes (dependem do motor de progresso), e jogos de PC/Steam.
- O scan é uma requisição única e longa; em ISOs muito grandes o navegador pode desistir (o scan continua e grava o resultado).
- Uma pasta configurada que fica vazia (último jogo apagado ou movido para outra pasta) mantém as linhas antigas, com aviso, porque não dá para distinguir de um disco desmontado. Para limpar, tire a pasta das configurações.
- Lista de pastas de ROMs vazia é recusada: a biblioteca não pode ser zerada pela interface.

## Perfis do Dolphin (fora das fases numeradas)

O Argos configura o Dolphin sem abrir a interface dele. Vale só para emuladores cadastrados que apontam para o Dolphin (`flatpak run org.DolphinEmu.dolphin-emu` ou um executável `dolphin-emu`).

- **Vídeo:** backend (Vulkan/OpenGL), placa de vídeo (padrão do sistema ou NVIDIA), resolução interna, anisotropia, VSync, texturas HD e pré-carregamento. Há um padrão para todos os jogos e um ajuste por jogo; o do jogo vence. "Padrão" não mexe no valor que o Dolphin já tem.
- **Como é aplicado** (verificado no Dolphin 2609b): as opções `-C GFX.*` da linha de comando são **ignoradas**, então o Argos grava `GameSettings/<ID>.ini` antes de abrir o jogo (`-v` escolhe o backend). A placa NVIDIA vem de variáveis de PRIME, passadas como `--env=` do Flatpak (antes do id do app) ou no ambiente do processo. Provado pelo `nvidia-smi` e pelo log do Dolphin, em OpenGL e em Vulkan.
- **Pacotes de texturas:** o Argos valida a lista do arquivo (toda entrada precisa estar na pasta `<ID>/` ou `<3 letras>/` do jogo; recusa `..`, caminhos absolutos e links simbólicos), confere espaço em disco, extrai numa pasta temporária e troca. Usa o `7z`, pois o `unzip` não abre a compressão dos pacotes SHDP. O ID vem dos 6 primeiros bytes da ISO.
- **Controles (jogador 1):** teclado e mouse (padrão do Dolphin), teclado WASD e controle de Xbox (perfil "SDL Gamepad" que acompanha o Dolphin). O `GCPadNew.ini` anterior fica em `GCPadNew.ini.argos-bak` (a primeira cópia nunca é sobrescrita).
- **Limites:**
  - O mapeamento do mouse (C-Stick pelo mouse) não existe: não consegui verificar os nomes de entrada do mouse no Dolphin.
  - O nome do controle de Xbox vem do kernel e pode diferir do nome SDL que o Dolphin usa; se o controle não responder, use o nome exato mostrado nos Controles do Dolphin. Não testei com um controle de verdade.
  - Resolução, anisotropia e VSync seguem os nomes das chaves do Dolphin, mas só as texturas e a placa foram provadas no seu Dolphin.
  - Mudar controles ou texturas exige o Dolphin fechado.
  - "Padrão" desfaz só o que o Argos gravou (ele lembra as chaves por jogo, a partir do primeiro jogo aberto com esta versão); chaves que você mesmo pôs no `.ini` do jogo não são apagadas.
  - Sem ID do jogo (RVZ, WBFS, GCZ e CISO não trazem o ID no começo do arquivo), resolução, anisotropia, VSync e texturas não são aplicados; backend e placa de vídeo continuam valendo. A tela avisa.
  - Escolher a placa de vídeo com Flatpak exige cadastrar o emulador como `flatpak` com `run <id>`; o script exportado (`.../exports/bin/org.DolphinEmu.dolphin-emu`) não repassa o ambiente, e o Argos recusa a combinação com uma mensagem.
  - **OpenGL tem um bug de teclado no Dolphin 2609b** (issue 13354 do Dolphin; correção mesclada em 14/11/2026, ainda fora do Flatpak): depois que a janela do jogo perde o foco uma vez, ela deixa de receber eventos de foco e de teclado. Medido no Flatpak instalado: a janela do jogo em OpenGL não tem as máscaras `FocusChange` e `KeyPress`; em Vulkan tem. Vulkan evita esse defeito específico, mas não resolve o sintoma relatado abaixo. O "Background Input" é um contorno documentado, mas faz o jogo reagir a teclas de outros programas.
  - **Teclado que para depois de perder o foco** (relatado e reproduzido pelo dono, em Vulkan, aberto pelo Argos): o X11 entrega `FocusOut`/`FocusIn` corretamente à janela do jogo (medido, sem injetar teclas). No código do Dolphin, toda entrada passa por um portão que só abre com `Host_RendererHasFocus()` (definido por `WindowActivate`/`WindowDeactivate` do Qt) e sem o ImGui capturar o teclado. A causa exata no seu ambiente não foi comprovada. As opções "Renderizar na janela principal", "Entrada em segundo plano" e "Manter janela no topo" (passadas com `-C Dolphin.Display.RenderToMain`, `Dolphin.Input.BackgroundInput` e `Dolphin.Display.KeepWindowOnTop`, verificado que o `-C` do sistema principal funciona) existem para testar os contornos documentados. "Renderizar na janela principal" não funciona com `-b`: no modo batch o Dolphin nunca mostra a janela principal (`MainWindow.cpp`), então o jogo ficaria invisível; o Argos recusa abrir com essa combinação (lido no código-fonte, não executado).
  - A lista de placas vem do `lspci` (lido uma vez e guardado: pode levar uns 2 s e acordar a placa dedicada na primeira consulta).
  - Só o Dolphin tem adaptador; a estrutura permite acrescentar o RetroArch depois.

## Detecção de controles

O Argos pergunta à SDL3 do sistema (via ctypes) quais gamepads estão conectados e monta o dispositivo como o Dolphin espera: `SDL/<n>/<nome da SDL>`, numerando pads de mesmo nome a partir de 0. O nome da SDL difere do nome do kernel (ex.: kernel "Xbox Wireless Controller", SDL algo como "Xbox Series X Controller"), por isso a SDL vem primeiro. A SDL dentro do Dolphin é outra cópia, mas os nomes vêm do mesmo banco de controles. Sem SDL3, o Argos lê `/proc/bus/input/devices` e reconhece gamepads pelos botões (BTN_GAMEPAD/BTN_JOYSTICK), com o nome do kernel como palpite. A tela de controles procura a cada 3 s e escolhe o controle sozinha quando ele aparece (até o usuário escolher outra coisa). O preset usa os nomes padronizados da SDL ("Button A", "Left X+"), então serve para Xbox, PlayStation e outros. Não verificado: um controle real conectado, comparando o nome com o que o Dolphin mostra.

## Detecção de emuladores

- Depois de cada scan, toda plataforma da biblioteca que ainda não tem emulador recebe o melhor instalado; uma escolha feita pelo usuário nunca é trocada. `GET /api/emulators/detected` lista as opções de cada plataforma.
- Dolphin (Flatpak ou nativo): `-b -e {rom}`, verificado nesta máquina. RetroArch (Flatpak ou nativo): um candidato por core instalado, com as plataformas tiradas do campo `database` do `.info` do core, que usa os mesmos nomes dos DATs No-Intro/Redump; argumentos `-L <core> {rom}`. Emuladores dedicados vêm antes de um core do RetroArch.
- Não incluídos por enquanto (argumentos não verificados): DuckStation, PCSX2 e outros. Entram como uma linha nova em `emulators/detect.py`.

## Fase 3: conquistas do RetroAchievements

Primeiro sinal de progresso: o `Collector` do RetroAchievements grava um sinal `achievements` por sincronização (os sinais antigos ficam, para reprocessar depois). A tela mostra "ganhas de total (%)" por jogo, e há "Sincronizar" por jogo e para todos os vinculados.

- **Credenciais:** usuário e chave de API ficam no banco local (que passa a ter permissão `600`, e o WAL e o SHM também). A chave é só de escrita: nenhuma rota a devolve; as recusas de validação (422) não repetem o que foi enviado; as mensagens de erro nunca levam a URL (a chave vai na consulta, como a API exige) e, se o servidor repetir a chave no texto do erro, ela é trocada por `•••`. Dá para remover a chave pela tela.
- **Vínculo:** você pode informar o ID do jogo (ou a URL da página), ou usar "Detectar automaticamente": o Argos calcula o hash do disco como o RetroAchievements faz (GameCube: MD5 do cabeçalho do disco mais cada segmento não vazio do `main.dol`) e pergunta ao site (`dorequest.php?r=gameid`, o mesmo pedido dos emuladores) qual jogo é. Só o hash sai da máquina, sem usuário nem chave. Hoje só GameCube e imagens brutas (ISO/GCM; RVZ e outros comprimidos não servem). O algoritmo foi escrito lendo `rc_hash_disc.c` do rcheevos e o programa de referência não foi executado: quem confirma é a resposta do servidor. Se ele não reconhecer o disco, informe o ID à mão. Para outros consoles, basta registrar uma função em `HASHERS` (`collectors/ra_hash.py`).
- **Login do Dolphin:** quem ganha as conquistas é o Dolphin, não o Argos, e ele precisa estar logado. A chave de API não serve para isso: o Dolphin guarda usuário e um token que só sai de um login com senha (`dorequest.php?r=login2`, o mesmo pedido do rcheevos). O Argos pede a senha uma vez, faz esse login e grava `Enabled`, `Username` e `ApiToken` em `RetroAchievements.ini` do Dolphin, só com o Dolphin fechado. A senha não é guardada e o token nunca sai da API. Não verificado contra o site real: o primeiro login é o teste (se o site recusar clientes que não sejam emuladores, a mensagem de erro aparece na tela).
- **Rich presence (começo da fase 4):** com o Dolphin logado, ele envia ao RA uma frase montada pelo script de rich presence do jogo a partir da memória (RE2 GameCube, verificado: "On the Title Screen"). Durante cada sessão aberta pelo Argos, um coletor lê `API_GetUserSummary` a cada 60 s (`collectors/presence.py`) e grava cada frase nova como sinal `presence` da sessão. A frase é do usuário, não do jogo: só vale se `LastGameID` for o jogo vinculado e `RichPresenceMsgDate` (UTC, conferido com uma amostra real) for depois do início da sessão. A ficha do jogo mostra "Onde você parou". Ainda falta o mapa frase → marcos da história, que só dá para escrever com frases reais de jogo.
- **Cliente:** `API_GetGameInfoAndUserProgress` (`y` = chave, `u` = usuário, `g` = jogo). Sem redirecionamentos, 15 s por leitura e 30 s para a resposta inteira, resposta limitada a 8 MB, JSON sem `NaN`/`Infinity`, contagens só entre 0 e 1 000 000, uma pausa de 1 s entre jogos ao sincronizar vários, e para na primeira chave recusada ou limite de uso. Qualquer resposta estranha vira uma mensagem legível, nunca um erro 500.
- **O que NÃO foi verificado:** nenhuma chamada real foi feita (não havia chave). Os nomes dos campos seguem a documentação, que mostra duas grafias; o leitor aceita as duas e, se vier outra forma, avisa quais chaves recebeu. O primeiro "Sincronizar" real é o teste de verdade.
- **Apagar jogos:** o scan nunca apaga um jogo que ainda tenha sessões, sinais, marcos ou estimativas (as chaves estrangeiras recusavam, e o scan inteiro passava a falhar). Sem arquivos, ele fica escondido e volta com o mesmo id, e o histórico, se os arquivos voltarem.
- **Vínculo:** trocar ou remover o vínculo esconde o resultado do jogo anterior; voltar ao vínculo antigo traz de volta o último resultado dele.
- **Limites:** "Sincronizar todos" é uma única requisição que segura uma conexão por pelo menos 1 s por jogo; para bibliotecas grandes vincule só o que importa. Cada sincronização grava uma linha em `signals` (cresce sem limite, como o desenho manda guardar o histórico). Mais de um jogo pode usar o mesmo ID do RetroAchievements (vários discos).
- **Não é progresso da história:** "conquistas ganhas ÷ total" mede conquistas. A estimativa de progresso (e a tabela `progress_estimates`) fica para a fusão de sinais da fase 5; por isso a fase 3 não grava estimativas com intervalo.
- **GameCube:** o RetroAchievements suporta GameCube desde 2024, mas os IDs de RE2 (provável 3176), RE3 (provável 6870) e Code Veronica X de GameCube não foram confirmados (o site bloqueou a consulta automática). Confira a página no site antes de vincular; "Code Veronica Kanzenban" (3866) é outro jogo.

## 5. Ordem de construção

| Fase | Entrega | Critério de pronto |
|---|---|---|
| 1 | Scanner + biblioteca + launcher | Escaneia uma pasta, lista os jogos identificados e abre um jogo no emulador |
| 2 | Sessões + estatísticas de tempo | Tempo jogado registrado e exibido por jogo e por período |
| 3 | Progresso com um sinal (conquistas do RetroAchievements) | % exibido para jogos com conquistas |
| 4 | Leitura de RAM para 1–2 jogos | Marcos detectados em tempo real. Método: interface de rede (UDP, `READ_CORE_MEMORY`) do RetroArch como referência, por ser documentada e não exigir permissão especial. Segunda opção: PINE do DuckStation (confirmar o socket no Linux). Evitar `/proc/pid/mem` como caminho principal: exige `ptrace_scope=0`, `CAP_SYS_PTRACE` ou root |
| 5 | Fusão de sinais + calibração | Estimativa com intervalo de confiança; erro medido contra RAM |
| 6 | Visão, RAG por jogo e recomendação | Fora do escopo inicial |

**Começar pela fase 1.** Não implementar fases posteriores antes de a anterior estar funcionando, mas desde o início manter `signals` e a interface `Collector` no desenho.

## 6. Estrutura de pastas sugerida

```
argos/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── db/            schema e acesso ao SQLite
│   │   ├── scanner/
│   │   ├── launcher/
│   │   ├── sessions/
│   │   ├── collectors/
│   │   ├── progress/
│   │   └── stats/
│   ├── tests/
│   └── pyproject.toml
├── frontend/              React + TypeScript (Vite)
└── PROJETO.md
```

## 7. Diretrizes

- Tudo roda localmente; nenhuma dependência de serviço em nuvem obrigatória. APIs externas (metadados, conquistas) são opcionais e com cache.
- O app **não distribui nem baixa** ROMs/ISOs; só gerencia arquivos que o usuário já tem.
- Testes para o scanner (hash e matching) e para o filtro de fusão (com sinais sintéticos).
- Código e commits em inglês; interface em português.

## 8. Em aberto

- ~~Nome do projeto~~: decidido, Argos Launcher.
- ~~Sistema operacional alvo~~ — decidido: Linux.
- Quais emuladores e plataformas suportar primeiro (sugestão: RetroArch, pela fase 4).
- Quais jogos usar como referência na fase 4 (precisam ter mapa de RAM disponível).
- A confirmar: campos do `game_time_to_beats` no IGDB; socket do PINE (PCSX2 e DuckStation) no Linux; cabeçalhos nos DATs de SNES, Lynx e A7800.
