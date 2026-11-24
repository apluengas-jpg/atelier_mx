# ATELIER — edición comercial web / PWA

Producto web responsive con backend persistente y API. La identidad visual usa el logotipo original aportado por ATELIER y la paleta: `#24201A`, `#FDE8F7`, `#35369C`, `#C936AE`, `#9D96FF`.

## Ejecutar localmente

Requiere Python 3.10+ e internet para instalar dependencias, Leaflet, fuentes y mapas.

```bash
cd ATELIER_Lanzamiento
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python server.py
```

Abre **http://127.0.0.1:5000**. No abras `index.html` directamente: la app requiere servidor.

## Datos incluidos

- 14 artistas, 4 espacios y 10 actividades históricas de la Fase 1. No se consideran socios ni miembros activos.
- 5 espacios complementarios investigados con fuentes públicas.
- 7 eventos investigados con fecha, fuente y lugar. La agenda separa actividades históricas y próximas. La programación puede cambiar; confirma con el organizador.
- Los nombres de terceros y sus datos se muestran como **investigación editorial**, no como clientes o aliados.

## Funcionalidad real de esta instalación

- Cuentas con contraseñas hasheadas y sesión HTTP-only.
- Favoritos persistentes en SQLite, perfiles por rol, solicitudes de colaboración, reclamación de perfiles.
- Reseñas almacenadas con moderación, no publicadas automáticamente.
- Propuestas de eventos por miembros Pro con moderación previa.
- Panel de moderación para la cuenta definida en `ADMIN_EMAIL`.
- Mapa Leaflet / OpenStreetMap con marcadores por tipo. Geocodificación de direcciones a través de Nominatim con caché local; los puntos sin geocodificar no se inventan.
- PWA instalable cuando se sirve por HTTPS (con manifiesto e iconos). No es un paquete nativo de App Store/Google Play.

## Membresías

- Comunidad: gratuita.
- Artista Pro: $150 MXN/mes o $1,400 MXN/año.
- Espacio Pro: $250 MXN/mes o $2,200 MXN/año.

Los pagos **solo funcionan al configurar Stripe**: crea cuatro precios recurrentes MXN y rellena las variables `STRIPE_PRICE_*` en el entorno. Stripe Checkout crea sesiones de suscripción; el webhook firmado (`POST /api/stripe/webhook`) actualiza el estado y los permisos. El portal de facturación permite gestionar o cancelar. **Sin claves y webhook, los cobros quedan deshabilitados y no se simulan como pagados.**

### Variables de entorno

Copia `.env.example` a tu gestor de secretos; **el archivo .env no se carga automáticamente**. Exporta las variables o configúralas en tu proveedor de alojamiento. Usa `SECRET_KEY` estable, `DATABASE_PATH` persistente, `COOKIE_SECURE=1`, `PUBLIC_BASE_URL` HTTPS y `ADMIN_EMAIL`.

## Despliegue

En un hosting Python con disco persistente:

```bash
gunicorn -w 2 -b 0.0.0.0:$PORT server:app
```

Para tráfico significativo, migrar SQLite a PostgreSQL y usar Redis para límites de velocidad. Configurar backups, correo transaccional, recuperación de contraseña, política de privacidad, términos, proceso de baja, cumplimiento fiscal y protección de datos, registro de marca, permisos sobre imágenes y materiales de artistas, observabilidad y pruebas de penetración. Configurar moderación operativa y mecanismos de denuncia. Los proveedores de mapas deben usarse conforme a sus términos y cuotas.

## Fuentes de investigación

- Fase 1 ATELIER, pp. 30–36 (catálogo inicial).
- Sistema de Información Cultural (Secretaría de Cultura): Museo del Barro, casas de cultura.
- Toluca la Bella CD, Aquelarre edición 23, 19 nov 2026: https://tolucalabellacd.com/2026/11/19/eventos/aquelarre-edicion-23/
- Mi Escaparate, agenda 11 nov 2026: https://miescaparate.com.mx/navidad-toluca-metepec-2026-actividades/
- Sistema Mexiquense, Expo Navidad Forestal, 13 nov 2026: https://mexiquensedigital.com/public/index.php/noticias/noticia/15_20261114035423_3345
- Programa Quimera 2026: https://festivalquimera.com/

## Limitaciones antes de venta pública

Este entregable es **código funcional autohospedable**, no un servicio ya desplegado. No se proporcionan cuentas externas, dominio, claves de cobro, verificación legal de material de terceros ni autorizaciones comerciales. Las reseñas requieren moderación humana. No se han ejecutado pruebas de integración del servidor en este entorno porque las dependencias Flask/Stripe no están instaladas y el entorno no permite descargarlas. Se verificó la sintaxis Python y JavaScript, la estructura JSON y el contenido del paquete. Se recomienda pruebas de extremo a extremo y auditoría antes de aceptar pagos reales.


Actualización: sección Nosotros y 14 fotografías circulares con enlaces sociales. El HTML independiente incluido es una vista previa, no procesa pagos. Confirmar derechos de imágenes antes de publicación.

## Actualización comunidad
Mensajería privada entre cuentas profesionales y titulares con reclamación aprobada. Los perfiles investigados sin titular no reciben mensajes. Bandeja en Mi ATELIER > Mensajes. El HTML guarda comentarios y borradores solo localmente. API de edición, eliminación y reporte de reseñas disponible; interfaz de gestión aún pendiente. Requiere pruebas de integración, despliegue y configuración de pagos.

## Actualización de membresías
Solo usuario general gratuito. Artista: 150/800/1400 MXN; negocio: 250/1300/2200 MXN (mensual/semestral/anual). Configurar seis precios recurrentes Stripe, con intervalo de seis meses para semestral. Registro profesional queda pendiente hasta confirmación de pago. Vista previa local sin cobros. Límites operativos de bookings y beneficios requieren gestión adicional.
