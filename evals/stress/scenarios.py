"""Perfiles multi-turno para el stress runner y MemoryDriftMetric.

Cada perfil es una lista de tuplas ``(turn_index, transcript, fact_to_remember)``.
Los ``fact_to_remember`` son anclas cortas que la métrica buscará en snapshots
de turnos posteriores (metadata, summary, historial recortado, etc.).

Perfiles
--------
- ``baseline`` — 3 turnos; acumulación básica de hechos sin presión de ventana.
- ``window_overflow`` — 8 turnos; supera ``MAX_TURNS`` (6) para forzar recorte
  del historial y medir si los hechos tempranos sobreviven vía metadata.
- ``constraint_locked`` — 5 turnos; restricciones duras (presupuesto, stack,
  plazo) que no deben perderse al refinar alcance.
"""

from __future__ import annotations

TurnScenario = tuple[int, str, str]

BASELINE_PROFILE: list[TurnScenario] = [
    (
        1,
        (
            "Necesitamos estimar el proyecto Nimbus: aplicación móvil de "
            "logística con seguimiento en tiempo real para flotas pequeñas. "
            "Stack propuesto Flutter y Firebase. Equipo de 4 desarrolladores."
        ),
        "project name: Nimbus",
    ),
    (
        2,
        (
            "Para Nimbus confirmamos backend en Node.js con PostgreSQL y "
            "autenticación OAuth2. Mantenemos el equipo de 4 personas y "
            "añadimos un QA dedicado en la fase de hardening del MVP."
        ),
        "stack includes PostgreSQL",
    ),
    (
        3,
        (
            "Refinamos Nimbus: priorizamos el módulo de rutas optimizadas y "
            "posponemos la integración con ERP hasta la fase 2. La estimación "
            "debe seguir alineada con Flutter en cliente y PostgreSQL en backend."
        ),
        "team size: 4 developers",
    ),
]

WINDOW_OVERFLOW_PROFILE: list[TurnScenario] = [
    (
        1,
        (
            "Kick-off del proyecto Nimbus: plataforma SaaS de reservas para "
            "coworkings con panel de administración y app móvil. "
            "Stack acordado: Flutter en móvil y React en web."
        ),
        "project name: Nimbus",
    ),
    (
        2,
        (
            "Para Nimbus fijamos presupuesto máximo bloqueado en 30 000 EUR "
            "sin posibilidad de ampliación en fase 1. Equipo asumido de "
            "3 desarrolladores full-time más un diseñador a media jornada."
        ),
        "budget locked: 30000 EUR",
    ),
    (
        3,
        (
            "Alcance inicial de Nimbus: login, catálogo de espacios, reservas "
            "con calendario, pagos con Stripe y notificaciones push. "
            "Excluimos facturación avanzada y multi-sede hasta fase 2."
        ),
        "stack includes Flutter",
    ),
    (
        4,
        (
            "Turno de refinamiento 4 para Nimbus: detallamos el flujo de "
            "cancelación de reservas, políticas de reembolso parcial y "
            "estados del ciclo de vida de una reserva en el panel admin."
        ),
        "scope: booking cancellation flow",
    ),
    (
        5,
        (
            "Turno de refinamiento 5 para Nimbus: estimamos esfuerzo del "
            "módulo de reportes operativos (ocupación, ingresos por sede) "
            "y exportación CSV para el equipo de operaciones del cliente."
        ),
        "scope: operational reports module",
    ),
    (
        6,
        (
            "Turno de refinamiento 6 para Nimbus: revisamos riesgos de "
            "integración con Stripe webhooks, reintentos idempotentes y "
            "manejo de pagos fallidos en checkout móvil y web."
        ),
        "risk: Stripe webhook idempotency",
    ),
    (
        7,
        (
            "Turno de refinamiento 7 para Nimbus: acordamos pruebas E2E en "
            "flujos críticos de reserva, hardening de roles admin vs operador "
            "y checklist de accesibilidad AA en formularios de reserva."
        ),
        "quality: E2E on booking flows",
    ),
    (
        8,
        (
            "Turno final de Nimbus: consolidamos la estimación recordando "
            "todas las restricciones acordadas — nombre del proyecto, stack "
            "móvil, techo de presupuesto y alcance excluido de multi-sede. "
            "¿Siguen vigentes Flutter y el límite de 30 000 EUR?"
        ),
        "budget locked: 30000 EUR",
    ),
]

CONSTRAINT_LOCKED_PROFILE: list[TurnScenario] = [
    (
        1,
        (
            "Estimación del proyecto Helios: portal B2B de contratos con "
            "firma electrónica y auditoría. Stack acordado TypeScript, "
            "Next.js y PostgreSQL. Plazo objetivo: entrega en Q3 2026."
        ),
        "project name: Helios",
    ),
    (
        2,
        (
            "Para Helios el presupuesto está bloqueado en 45 000 EUR totales "
            "para fase 1; no hay margen de contingencia. Equipo fijo de "
            "5 desarrolladores sin ampliación durante el proyecto."
        ),
        "budget locked: 45000 EUR",
    ),
    (
        3,
        (
            "Helios debe cumplir GDPR y retención documental de 7 años. "
            "Incluimos cifrado en reposo, trazabilidad de firmas y export "
            "legal de evidencias. Excluimos integración con Salesforce."
        ),
        "compliance: GDPR 7-year retention",
    ),
    (
        4,
        (
            "Refinamos Helios: priorizamos onboarding de empresas, plantillas "
            "de contrato y flujo de firma secuencial multi-firmante. "
            "Posponemos OCR de documentos escaneados a fase 2."
        ),
        "stack includes Next.js",
    ),
    (
        5,
        (
            "Cierre de estimación Helios: confirmamos que Next.js, PostgreSQL, "
            "el techo de 45 000 EUR, el plazo Q3 2026 y GDPR siguen siendo "
            "restricciones no negociables para el desglose final por fases."
        ),
        "deadline: Q3 2026",
    ),
]

SCENARIOS: dict[str, list[TurnScenario]] = {
    "baseline": BASELINE_PROFILE,
    "window_overflow": WINDOW_OVERFLOW_PROFILE,
    "constraint_locked": CONSTRAINT_LOCKED_PROFILE,
}
