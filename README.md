# Yagüven Kardex — Reporte Kardex de Inventario (Odoo 19)

## 1. Introducción

### Qué hace Odoo nativamente

Odoo 19 ofrece reportes de inventario como el **Informe de inventario** (`stock.quant`) y el **Historial de movimientos** (`stock.move.line`). Estos muestran el estado actual del stock o una lista plana de movimientos, pero **no calculan un saldo acumulado (running balance) por producto/ubicación en un rango de fechas**.

### Limitación

Para auditorías, control de stock y conciliación contable, se necesita un reporte tipo **Kardex** que muestre:

- Saldo inicial al comienzo del período
- Cada entrada y salida con su documento origen
- Saldo acumulado después de cada movimiento

Odoo no incluye este reporte de forma nativa.

### Qué mejora este módulo

**yaguven_kardex** agrega un reporte Kardex completo accesible desde *Inventario → Reportes → Kardex*, con:

- Saldo inicial calculado por SQL en una sola pasada
- Saldo acumulado (running balance) por producto
- Soporte para ubicaciones con hijos (excluye movimientos internos automáticamente)
- Filtros por producto, categoría, ubicación, lote y rango de fechas
- Exportación a Excel con formato profesional
- Click-through a la transferencia origen desde cada línea

---

## 2. Origen: port de `guvens_kardex` (Odoo 17)

Este módulo es un port directo de `guvens_kardex` (instancia productiva v17 de Lupatini). La lógica de negocio, el cálculo de saldos y el formato Excel son idénticos. Cambios de esquema entre v17 y v19, verificados en vivo antes de portar:

| Elemento v17 | Elemento v19 | Motivo |
|---|---|---|
| `<tree>` (vistas), `view_mode: 'tree'` | `<list>`, `view_mode: 'list'` | Odoo 19 renombró el tipo de vista tree → list |
| `product.product` filtrado por `('type', '=', 'product')` | `('is_storable', '=', True)` | El valor `'product'` (Storable Product) del selection `type` se eliminó en v19; se reemplaza por el booleano `is_storable` |
| Modelos `guvens.kardex.*` | `yaguven.kardex.*` | Convención de nombres del estudio para módulos nuevos |

Todo lo demás —campos de `stock.move.line` (`quantity`, `date`, `location_id`, `location_dest_id`, `lot_id`, `product_uom_id`), `stock.move` (`state`, `company_id`, `reference`, `origin`, `picking_id`), el menú `stock.menu_warehouse_report` y el grupo `stock.group_stock_user`— se verificó idéntico en v19 y no requirió cambios.

---

## 3. Funcionamiento para el usuario final

### Acceso

**Inventario → Reportes → Kardex**

Se abre un wizard con filtros:

| Campo | Descripción | Obligatorio |
|-------|-------------|:-----------:|
| Desde / Hasta | Rango de fechas del reporte | Sí |
| Ubicación | Ubicación o almacén a analizar (incluye hijos) | Sí |
| Productos | Filtrar por productos específicos | No |
| Categoría | Filtrar por categoría de producto | No |
| Lote / Serie | Filtrar por lote o número de serie | No |
| Incluir sin movimiento | Mostrar productos con saldo pero sin movimientos en el período | No |

### Flujo paso a paso

1. Ir a **Inventario → Reportes → Kardex**
2. Seleccionar el **rango de fechas** (por defecto: mes actual)
3. Seleccionar la **ubicación** (ej: `WH/Stock`, `A-Pad/Existencias`)
4. Opcionalmente filtrar por productos, categoría o lote
5. Clic en **"Ver Kardex"** → se abre la vista list con los resultados
6. O clic en **"Exportar Excel"** → descarga archivo XLSX

### Reglas visuales

- **Saldo Inicial**: fila en negrita con fondo celeste
- **Saldo negativo**: texto en rojo
- **Botón de link** (→): abre la transferencia origen en cada línea

### Por qué las reglas de negocio funcionan así

- **Saldo inicial**: se calcula sumando TODAS las entradas y restando TODAS las salidas anteriores a la fecha "Desde". Esto garantiza que el primer saldo del reporte coincide con el stock real a esa fecha.
- **Movimientos internos excluidos**: si la ubicación seleccionada tiene sub-ubicaciones, un movimiento entre ambas no cambia el saldo total del grupo. El Kardex lo omite automáticamente.
- **Lote/Serie**: cuando se filtra por lote, tanto el saldo inicial como los movimientos se restringen a ese lote específico.

---

## 4. Referencia técnica

### Arquitectura

```
yaguven_kardex/
├── __init__.py
├── __manifest__.py
├── security/
│   └── ir.model.access.csv
├── views/
│   └── kardex_views.xml
└── wizard/
    ├── __init__.py
    └── kardex_wizard.py          # Wizard + líneas del reporte
```

### Modelos

| Modelo | Tipo | Descripción |
|--------|------|-------------|
| `yaguven.kardex.wizard` | TransientModel | Wizard con filtros del reporte |
| `yaguven.kardex.line` | TransientModel | Líneas generadas del Kardex (auto-limpieza) |

No se crean modelos persistentes ni se modifican tablas existentes. Herencias: ninguna — módulo 100% aditivo.

### Por qué SQL directo en vez de ORM

`stock.move.line` puede tener millones de registros. El ORM generaría N+1 queries para recorrer movimientos y calcular el saldo acumulado. Con SQL directo se obtiene todo en 2 queries (opening balance con `CASE WHEN`, movements con `ORDER BY product_id, date, id`).

### Dependencias

| Módulo | Razón |
|--------|-------|
| `stock` | Modelos `stock.move.line`, `stock.location`, `stock.picking` |

Librería Python: `xlsxwriter`.

### Verificación / Testing

1. Instalar el módulo
2. Ir a Inventario → Reportes → Kardex
3. Seleccionar una ubicación con movimientos históricos
4. Verificar que el último saldo del Kardex coincida con el stock en Inventario → Reportes → Informe de inventario
5. Exportar a Excel y verificar que los totales de Entrada/Salida cuadren

Validación cruzada: `Saldo Inicial + Total Entradas - Total Salidas = Último Saldo` debe coincidir con la cantidad disponible en `stock.quant` para la misma ubicación/producto/lote.
