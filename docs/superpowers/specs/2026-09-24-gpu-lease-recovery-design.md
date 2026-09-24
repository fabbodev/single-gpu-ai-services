# Bloque 1: propiedad de GPU y recuperación ante fallos

Estado: DISEÑO PROPUESTO, pendiente de aprobación. No desplegar.
Fecha: 2026-09-24.
Base: single-gpu-ai-services, commit 8f36fe46ec5c7e5a81a6e804604f800720466ee7.

## Objetivo y límites

Corregir F01–F04 de la auditoría: esperas indefinidas, reservas huérfanas,
estado incierto de Docker y pérdida de exclusividad tras reinicios.
Se conserva MCP -> Gateway -> Dispatcher -> engines; una GPU y un Dispatcher.
No se introducen Redis, Kubernetes, una base de datos ni servicios adicionales.
No se cambia el formato público de peticiones de inferencia ni los modelos.
No se despliega, no se actualizan drivers/kernel ni se toca el almacenamiento.
Las pruebas se ejecutan localmente mediante Remote Desktop Commander.
No se lanza GitHub Actions. Las pruebas iniciales no usan GPU ni Docker real.

## Decisión que necesita aprobación

Los endpoints privados de reserva pasan a un contrato identificado y acotado.
Gateway y Dispatcher deberán desplegarse juntos, sin mezclar protocolos.
Una reserva vencida pierde el derecho a seguir ejecutando su engine.
Antes de conceder otra, el Dispatcher debe detener y verificar la anterior.
Si no puede comprobarlo, queda DEGRADED y rechaza trabajo nuevo; no supone éxito.
No se reinicia Proxmox ni la VM para recuperar una reserva.

## Diseño elegido

Admisión HTTP breve + consulta de estado, en vez de una petición HTTP bloqueada
mientras espera la GPU. La espera sigue dentro del mismo Dispatcher, en memoria.
La alternativa de conservar adquisiciones HTTP largas exige gestionar peticiones
que sobreviven a su cliente y consume capacidad de atender liberaciones.
La admisión breve permite cancelar, consultar y reintentar sin duplicar arranques.

## Identidad e idempotencia

- Cada proceso Dispatcher genera un epoch nuevo al arrancar.
- Gateway obtiene ese epoch y genera un request_id UUID antes de solicitar GPU.
- Toda mutación identifica epoch + request_id + servicio; nunca sólo servicio.
- La primera admisión fija una fecha de vencimiento y parámetros inmutables.
- Un reintento con los mismos datos devuelve la misma reserva/estado.
- Reutilizar el ID con otros datos se rechaza; no amplía el vencimiento.
- Una cancelación puede registrarse antes de llegar el acquire correspondiente.
- Una liberación repetida es inocua; una antigua no puede detener al nuevo dueño.
- Epoch antiguo se rechaza. No se reenvía automáticamente bajo un epoch nuevo.
- El registro de IDs terminales se conserva hasta que ya no puedan admitirse por
  su fecha original; la admisión rechaza vencidos y limita el horizonte máximo.
- La capacidad de registros es finita: se rechazan nuevas admisiones antes que
  descartar un identificador todavía válido. No se expulsan reservas activas.
- Gateway y Dispatcher comparten el reloj del host; las esperas internas usan
  deadlines monotónicos. Deben probarse saltos de reloj sin extender reservas.

## Estados y exclusividad

RECONCILING -> IDLE -> STARTING -> ACTIVE -> STOPPING -> IDLE.
Cualquier parada/inspección incierta mantiene propiedad y termina en DEGRADED.
Un solo trabajador de lifecycle ejecuta start/stop; el lock de estado no se
mantiene durante comandos Docker, healthchecks o esperas de red.
Las consultas y cancelaciones siguen respondiendo mientras el trabajador opera.
No se admiten varios procesos Uvicorn ni varias instancias propietarias de la GPU.
La exclusividad cubre los engines gestionados; no cubre procesos GPU ajenos.

## Presupuestos propuestos, configurables y sujetos a pruebas

| Fase | Límite inicial |
|---|---:|
| Espera por GPU | 90 s |
| Arranque + readiness del servicio lógico completo | 120 s |
| Inferencia en Gateway, duración total | 300 s |
| Reserva ACTIVE, desde que el engine queda listo | 330 s |
| Limpieza total de una reserva | 60 s |
| Consulta periódica de reservas vencidas | 1 s |
| Petición MCP completa hacia Gateway | 600 s |

No habrá renovaciones indefinidas en este bloque. Al alcanzar 300 s de inferencia,
Gateway cancela esa operación y solicita liberación. Los 30 s adicionales de la
reserva protegen la limpieza; no permiten empezar una inferencia nueva.
Esto hace explícito un límite total que el timeout por fase de HTTPX no garantiza.
Si necesitamos OCR más largo, los límites se amplían coordinadamente y se prueban.
El servidor valida que ningún presupuesto configurable sea negativo o infinito.
Cada comando externo usa el mínimo entre su límite local y el presupuesto restante.
Un proceso del sistema operativo bloqueado en el kernel no tiene garantía de
terminación instantánea; el estado seguirá no disponible, nunca libre por suposición.

## Docker y recuperación

Inspección distingue RUNNING, STOPPED, MISSING y UNKNOWN. Fallos de daemon o
permisos son UNKNOWN; MISSING requiere evidencia específica, no cualquier error.
Sólo se manipulan los siete nombres de contenedor ya gestionados por EngineManager.
OCR conserva start VLM -> API y stop API -> VLM. Si falla un stop, se intenta el
resto y se agregan los errores, sin ocultar el fallo original.
Después de stop se verifica el estado real. UNKNOWN o supervivientes bloquean IDLE.
Un timeout de docker start no prueba que Docker haya cancelado esa operación;
si el resultado queda ambiguo, no se autoriza una segunda GPU basándose en un
único inspect. Se conserva DEGRADED hasta reconciliar el resultado de lifecycle.
Al reiniciar Dispatcher se cambia epoch, se rechazan comandos viejos y se
reconcilian los engines antes de aceptar adquisiciones. Los trabajos huérfanos
se detienen; no se intenta adoptar silenciosamente una inferencia sin propietario.
La recuperación sólo publica disponibilidad al confirmar que los engines gestionados
están detenidos o ausentes. Un fallo conserva motivo de degradación observable.

## Contrato privado y compatibilidad

- GET /ready: protocolo, epoch, disponibilidad y causa de degradación sin secretos.
- POST /acquire/{service}: ID + epoch + vencimiento; 202 si está en cola/arrancando,
  200 si ese mismo ID ya posee una reserva lista, 409 ante conflicto/epoch antiguo.
- GET /leases/{request_id}: estado y epoch; nunca se infiere éxito del silencio.
- POST /release/{service}: ID + epoch requeridos; seguro ante duplicados.
- POST /cancel/{service}: ID + epoch; cancela pendientes o programa su limpieza.
- Registros terminales devuelven resultado estable; vencidos no resucitan.
- Gateway espera/pregunta sin mantener threads síncronos ocupados por la cola.
- Todas las rutas Gateway usan el mismo contexto de reserva y limpieza acotada,
  incluyendo cancelación, desconexión, pérdida de respuesta y excepción del backend.
- IDs/epoch dan correlación y protección contra operaciones tardías, NO reemplazan
  autenticación. La autenticación entre componentes corresponde al bloque 3.
- Gateway y Dispatcher se actualizan juntos y fallan explícitamente al detectar
  protocolos incompatibles. No se deja un endpoint de release sin ID por compatibilidad.
- Los endpoints públicos /v1 mantienen sus payloads; errores de timeout/recovery
  se devuelven explícitamente y sin transformar fallos de limpieza en éxitos.

## Alcance de archivos

Dispatcher: dispatcher.py, engine_manager.py, runner.py, app.py y sus tests.
Gateway: dispatcher_client.py, main.py y tests de lifecycle/contrato HTTP.
MCP: sólo alinear el timeout configurable con el presupuesto total.
Dockerfile de Dispatcher: un único worker explícito. Documentación del protocolo.
Fuera de este bloque: STT/TTS, imágenes/digests, modelos, recursos y autenticación.
No se modifica la configuración del host ni se publica nada sin revisión posterior.

## Aceptación mediante pruebas locales

1. Una admisión vencida antes de STARTING nunca arranca. Si la respuesta se
   pierde después de empezar, el ID recupera ese estado y la reserva se limpia
   por cancelación/vencimiento, o queda explícitamente DEGRADED.
2. Reintento del mismo ID no repite start; cambiar servicio o vencimiento se rechaza.
3. Release viejo/duplicado no interrumpe al siguiente trabajo del mismo servicio.
4. Cancel antes de acquire impide el arranque posterior del mismo ID.
5. Reinicio cambia epoch y reconcilia sin solapar engines.
6. Inspect fallido es UNKNOWN; fallo en un stop OCR no impide intentar el otro.
7. Healthcheck o subprocess que se cuelga termina por deadline o queda DEGRADED.
8. Una operación Docker ambigua nunca libera la GPU por suposición.
9. Caducidad ACTIVE inicia cleanup; no admite trabajo hasta confirmar parada.
10. Cancelación y fallo de Gateway no dejan una reserva sin recuperación acotada.
11. Reloj ajustado, cola llena y replay de ID terminal no amplían derechos de uso.
12. La suite anterior sigue pasando, con sus dobles adaptados al protocolo nuevo.
13. Contrato HTTP Gateway/Dispatcher y concurrencia se prueban juntos con Docker fake.
14. /ready responde no disponible en reconciliación/degradación; /health no se bloquea.

Los casos de fallo se escribirán antes del código y deberán fallar en la base vieja.
Las primeras pruebas no tienen acceso al socket Docker real ni a la GPU.
Las pruebas GPU reales y los builds de producción son otra puerta de aprobación.

## Evidencia inicial, no evidencia de corrección

En la base auditada se ejecutaron mediante DCR: Dispatcher 10 passed,
Gateway 20 passed, MCP 7 passed. Los nueve Compose validaron su sintaxis.
Entorno disponible: Python 3.14.4; aparecieron avisos de deprecación.
Las imágenes declaran Python 3.12 para Gateway/MCP: falta comprobar esa matriz.
Se reprodujeron con doubles: pérdida de dueño al reconstruir Dispatcher, release
sin identidad que afecta al siguiente dueño y error inspect interpretado como false.
No se invocó Docker lifecycle real. Aún no hay correcciones ni pruebas nuevas aplicadas.

## Referencias técnicas externas

HTTPX distingue timeout de conexión/lectura/escritura/pool; el de lectura mide
la espera por un fragmento, no un deadline global de inferencia.
https://www.python-httpx.org/advanced/timeouts/
subprocess.run(timeout=...) mata y espera a su hijo al vencer; no prueba que una
operación enviada a un daemon remoto haya sido anulada.
https://docs.python.org/3/library/subprocess.html
