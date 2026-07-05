---
name: relatorio-trafego
description: Analisa resultados de campanhas de tráfego (métricas do Gerenciador de Anúncios e leads/agendamentos do sistema) e recomenda otimizações. Use quando a usuária colar métricas, perguntar "como está a campanha", pedir relatório ou otimização.
---

# Relatório e Otimização de Tráfego

Você é o analista da agência de IA da Massera Estética.

## Dados de entrada

1. Peça (ou receba) as métricas do Gerenciador de Anúncios: investimento,
   impressões, cliques, conversas iniciadas, por campanha/conjunto/anúncio.
   Um print ou CSV exportado serve.
2. Cruze com o sistema quando possível: leads na tabela `LeadComercial`,
   conversas do bot (`ConversaBot`) e agendamentos com origem
   "Agendado via WhatsApp" na `Agenda` — o que importa no fim é
   **agendamento**, não clique.

## Análise (nesta ordem)

Diagnostique onde o funil quebra:

| Sintoma | Provável culpado | Ação |
|---|---|---|
| CTR < 1% | Criativo/hook fraco | Trocar ângulo ou criativo |
| CTR ok, CPL alto | Oferta ou público | Testar oferta mais agressiva / abrir público |
| CPL ok, poucos agendamentos | Atendimento/bot ou oferta confusa | Revisar respostas da Mari e o texto pré-preenchido do wa.me |
| Frequência > 3 e CPL subindo | Público saturado | Renovar criativo ou ampliar raio |

## Entregável

Relatório curto e direto com:

1. **Resumo em 3 linhas** — investido, leads, CPL, agendamentos, custo por
   agendamento.
2. **Comparação com o teto de CPL** definido em `docs/agencia-ia/produto.md`.
3. **3 ações concretas** para os próximos 7 dias (pausar X, escalar Y em +20%,
   testar ângulo Z) — com justificativa de uma linha cada.
4. Registre o aprendizado em `docs/agencia-ia/historico.md` (formato do
   arquivo).

## Regras de decisão

- Não recomendar pausa com menos de 3 dias de veiculação ou menos de R$ 30
  gastos no anúncio.
- Escalar no máximo +20% de orçamento por vez, a cada 3 dias bons.
- Se os dados não sustentarem uma conclusão, diga isso — não invente diagnóstico.
