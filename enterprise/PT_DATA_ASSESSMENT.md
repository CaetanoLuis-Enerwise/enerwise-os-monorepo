# Avaliação de dados — um edifício (PT)

**Preço:** EUR 5.000–10.000.  
**Âmbito:** um edifício comercial em Portugal. Shadow / simulado apenas.

## Produto

Inteligência energética operacional. FastAPI + planner determinístico + dashboard React. Sem Streamlit. Sem lógica de negócio no frontend. ML prevê carga e PV; não despacha bateria. Sem comando físico ao inversor ou BMS. Sem savings garantidos.

## Quem

Um site. Comprador: diretor de energia / facility, CFO, ou gestor do edifício, com acesso lícito aos dados e à fatura.

Perfil: edifício comercial (escritórios, retalho, campus, logística leve) com PV e, de preferência, bateria instalada ou intenção de a instalar.

Assunção: a geometria solar do motor está calibrada para Porto/Gaia. Outra latitude fica anotada no relatório e não é vendida como calibração local.

Fora de âmbito: residencial, frota, closed-loop físico, participação em mercado / balancing.

## Dados necessários

| Item | Mínimo |
| --- | --- |
| Consumo no ponto de entrega | 6–12 meses, intervalo 15 ou 30 min, timestamps `Europe/Lisbon`, kW ou kWh |
| PV | mesma cadência, alinhada ao consumo |
| Tarifa | ciclo horário, potência contratada, termo de energia, compensação de exportação |
| Bateria (se existir) | kWh úteis, Pmax carga/descarga, SoC min/max/reserva, eficiência, AC ou DC |
| Topologia | ponto de medição claro (unifilar ou equivalente) |

Telemetria live é opcional nesta fase. Protocolo (Modbus, MQTT, REST, cloud do fabricante) entra só no gap de integração.

**Go de ingestão:** cobertura de intervalos ≥98% ou excepção escrita; unidades e fuso conhecidos; fatura reproduzível.

**No-go de ingestão:** buracos sistemáticos; PV só mensal; tarifa opaca; medição misturada sem mapa; bateria sem envelope operacional (não se simula despacho).

## Entrega

- Relatório de qualidade de dados
- Reconstrução da fatura baseline
- Simulação histórica em shadow (hybrid GB carga/PV + planner determinístico; mercado em `safe_mode` se os preços falharem)
- Estimativa de valor com premissas etiquetadas (autoconsumo solar, importação de rede, custo estimado)
- Gap de integração e segurança
- Recomendação go / no-go para piloto shadow EUR 15.000–30.000
- Journal local com cadeia SHA-256 (não substitui audit enterprise)

## Não entrega

Setpoint físico. Adapter de inversor/BMS em hardware. SLA de produção. Demo Streamlit. ML a comandar bateria. Savings garantidos.

## Go / no-go para o piloto shadow

**Go** se cumulativamente:

1. Os dados passam a qualidade e a fatura reconcilia.
2. Valor bruto esperado a 3 anos ≥ 3× implementação + opex, **ou** valor estratégico documentado (frota futura, resiliência, readiness regulatório).
3. Contactos nomeados (técnico, ciber, comercial) e acesso lícito.
4. O cliente aceita só recomendações auditadas. Zero comando físico nesta fase.

**No-go** se: dados irrecuperáveis; tarifa irreproduzível; pool de valor abaixo do floor; exigência de controlo físico ou de savings garantidos nesta fase; OT sem dono.

## Depois do go

Piloto shadow, um edifício, 8–12 semanas: ingestão read-only, planos a 30 min, dashboard React, review semanal, relatório KPI. EUR 15.000–30.000.

Hardware controlado é banda extra (EUR 20.000–50.000) e fica fora desta moção. Preços finais passam por qualificação e revisão legal. Ver `COMMERCIAL_MODEL.md` e `PILOT_PROPOSAL.md`.
