# Onde Paramos — Espaço Parvati / Massera Estética

Resumo vivo do estado dos projetos. Atualizado em **06/07/2026**.

## 🤖 Mari (bot do WhatsApp da clínica)

**Status: SILENCIADA de propósito** (a pedido da Naiara, até resolver a IA).

O que já foi feito e está no ar:
- ✅ Corrigidos os bugs do "bot doido": memória de conversa que não salvava,
  respostas duplicadas, replay de mensagens antigas, nome trocado de cliente,
  perguntas registradas como nome
- ✅ Mari conhece o HIPRO Day / Lavieen Day (data na variável `PROXIMO_DAY`,
  hoje = 24/07 — **atualizar todo mês** no Vercel)
- ✅ Banco de dados permanente (Postgres/Neon) criado e conectado no Vercel —
  a partir de agora nada mais se perde
- ✅ Botão de pausa instalado

**O que falta para reativar a Mari (nesta ordem):**
1. Entrar em **console.anthropic.com** → **Billing** → conferir/adicionar
   créditos (~US$ 5). Toda resposta da Mari caía em "Desculpe, tive um
   probleminha" porque a chamada à IA está sendo recusada — causa mais
   provável: créditos esgotados ou chave inválida.
2. Reativar: no Vercel (projeto espaco-parvati) → Environment Variables →
   adicionar `BOT_ATIVO` = `1` → Redeploy. (Ou pedir ao Claude: "reativa a Mari".)
3. Testar: mandar "oi", conversar 3 mensagens (ela deve lembrar o nome),
   perguntar "quando é o HIPRO Day?" (deve responder 24/07).

## 📵 IABook (número 31 99303-1068)

**Status: PENDENTE — ainda respondendo.** É outro projeto (Oráculos de
Lemúria / ebook), fora deste repositório.

Para silenciar: descobrir o nome do projeto dele no painel do Vercel
(tela inicial → lista de projetos) → Settings → General → **Pause Project**.
Ou informar ao Claude o nome do repositório no GitHub para instalar o mesmo
botão de pausa da Mari.

## 📣 Agência de IA de tráfego

**Status: PRONTA no repositório.** Skills do Claude Code (usar em qualquer
conversa deste projeto):
- `/estrategia-trafego` · `/criar-campanha` · `/copy-anuncio` · `/relatorio-trafego`

Documentos prontos em `docs/agencia-ia/`:
- `produto.md` — brief (preços, WhatsApp, Conselheiro Lafaiete, R$ 100/mês)
- `estrategia-2026-07.md` — plano de julho (rajada 08–12/07 + Day 24/07)
- `campanhas/2026-07-08-limpeza-facial.md` — campanha completa da Limpeza
  Facial R$ 130 (3 anúncios, copies, públicos, passo a passo do Gerenciador)
- `campanhas/copies-2026-07-14-aquecimento-day.md` — copies da contagem
  regressiva do HIPRO/Lavieen Day + mensagem de disparo para a base
- `campanhas/prompts-veo3.md` — prompts de vídeo para gerar criativos no Veo 3

**Pendências da campanha (com a Naiara):**
1. Vincular o WhatsApp Business (31 99126-9732) à página do Facebook/Instagram
2. Gravar os 3 vídeos (roteiros no documento da campanha)
3. Montar a campanha no Gerenciador de Anúncios (R$ 20/dia, 15–19/07)
4. Dia 20/07: trazer as métricas e rodar `/relatorio-trafego`

## 🗄️ Sistema web da clínica

- O banco novo começa **vazio** (cadastros/agenda). O que aparecia antes
  estava em armazenamento temporário que se apagava sozinho.
- Se os clientes vieram do Clinicorp: existem scripts de importação em
  `scripts/` — pedir ao Claude para reimportar.

## 📌 Histórico técnico

Pull requests #1 a #5 no GitHub contam a história completa das correções.
Deploy: automático no Vercel a cada merge na branch `main`.
