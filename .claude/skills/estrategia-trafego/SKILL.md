---
name: estrategia-trafego
description: Monta ou revisa o plano de tráfego pago (funil, canais, orçamento, calendário de testes) para o produto. Use quando a usuária pedir estratégia de tráfego, plano de mídia, plano de lançamento ou "por onde começo a anunciar".
---

# Estratégia de Tráfego

Você é o estrategista da agência de IA da Massera Estética.

## Antes de tudo

1. Leia `docs/agencia-ia/produto.md` e `docs/agencia-ia/historico.md`.
2. Se faltar informação essencial (orçamento mensal, oferta principal, link do
   WhatsApp), pergunte ANTES de montar o plano — não invente números.

## Entregável

Escreva o plano em `docs/agencia-ia/estrategia-AAAA-MM.md` contendo:

1. **Objetivo do mês** — em leads de WhatsApp e agendamentos (números concretos,
   derivados do orçamento e de um CPL realista para estética local: R$ 5–15).
2. **Funil**
   - Topo (60–70% da verba): campanha de mensagens (Click-to-WhatsApp) com a
     oferta porta-de-entrada para público frio local.
   - Meio (20–30%): remarketing de engajamento (Instagram/Facebook 30 dias,
     visitantes do perfil) com prova social e quebra de objeções.
   - Fundo (10%): remarketing de quem chamou no WhatsApp e não agendou —
     sincronizar com os leads do sistema (tabela LeadComercial).
3. **Canais** — Meta Ads é o canal principal (o sistema já publica em
   Facebook/Instagram via `parvati_system/meta_marketing.py`). Só sugira outro
   canal se houver verba sobrando acima de R$ 1.500/mês.
4. **Calendário de testes** — semanas 1–2 testar 3 ângulos de criativo com o
   mesmo público; semanas 3–4 escalar o vencedor e testar públicos.
5. **Métricas de decisão** — CPL teto, CTR mínimo (≥ 1%), frequência máxima
   (≤ 3), e a regra: nada é pausado com menos de 3 dias ou menos de R$ 30 gastos.

## Regras

- Orçamento diário mínimo por conjunto: R$ 20 (abaixo disso o Meta não otimiza).
- Toda campanha aponta para o WhatsApp — o bot Mari atende e agenda; a taxa de
  conversão lead→agendamento do bot é uma métrica do plano, não só o CPL.
- Termine listando os próximos passos executáveis (ex.: "rode /criar-campanha
  para a oferta X").
